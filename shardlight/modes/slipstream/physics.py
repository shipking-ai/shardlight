"""Physics-lite car model: engine force curve + gearbox, dynamic bicycle model with per-axle slip angles,
friction-ellipse traction, handbrake drift, boost, slipstream drag reduction and soft collisions.

Pure Python (no pygame).  Units: pixels and seconds, y axis points down, heading 0 = +x, positive yaw = clockwise
on screen.  The car's body-frame lateral axis ("right") is ``(-sin h, cos h)``.

The lateral tyre force follows a Pacejka-like curve ``sin(C*atan(B*x))`` of the slip angle, so grip peaks at
``ALPHA_PEAK`` and falls off slightly beyond it - that fall-off is what makes a slide feel like a slide.
Rear-axle grip is shared between lateral force and drive/brake force through a friction ellipse, so hard
acceleration on a low-grip surface (salt) breaks the tail loose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .vehicle import VehicleSpec

# surfaces ---------------------------------------------------------------------------------------------
TARMAC, SALT, DUST, ROUGH, OIL = 0, 1, 2, 3, 4
SURFACE_MU = {TARMAC: 1.0, SALT: 0.60, DUST: 0.80, ROUGH: 0.70, OIL: 0.20}
SURFACE_DRAG = {TARMAC: 0.0, SALT: 0.0, DUST: 0.10, ROUGH: 0.55, OIL: 0.0}
SURFACE_NAMES = {TARMAC: "tarmac", SALT: "salt", DUST: "dust", ROUGH: "rough", OIL: "oil"}

# tuning -----------------------------------------------------------------------------------------------
BASE_GRIP = 440.0          # px/s^2 of lateral acceleration at grip 1.0 on tarmac
V_MIN = 55.0               # slip angles are regularised below this speed (stability + low-speed feel)
ALPHA_PEAK = 0.27          # slip angle (rad) of peak tyre force
_B, _C = 2.0, 1.4
SUBSTEPS = 3
ROLL_DRAG = 0.15           # 1/s
TORQUE = ((0.0, 0.50), (0.25, 0.78), (0.55, 1.0), (0.8, 0.97), (1.0, 0.75), (1.15, 0.15), (1.4, 0.0))
GEAR_TOPS = (0.30, 0.50, 0.68, 0.85, 1.0)      # fraction of top speed at redline, per gear
SHIFT_TIME = 0.11
REVERSE_ACCEL = 120.0
REVERSE_MAX = 70.0
BOOST_USE = 42.0           # meter per second while boosting
BOOST_ACCEL = 0.75         # x power
ASSIST_START, ASSIST_GAIN, ASSIST_MAX = 0.10, 0.9, 0.38
DRIFT_ON, DRIFT_OFF = 0.22, 0.14     # slip angle thresholds (rad)
DRIFT_MIN_SPEED = 70.0
DRIFT_RATE = 80.0          # boost bank per second at 1 rad slip and 300 px/s
DRAFT_RATE = 15.0          # boost per second at full slipstream


def torque_at(r: float) -> float:
    if r <= TORQUE[0][0]:
        return TORQUE[0][1]
    for (r0, t0), (r1, t1) in zip(TORQUE, TORQUE[1:]):
        if r <= r1:
            return t0 + (t1 - t0) * (r - r0) / (r1 - r0)
    return 0.0


def tire_curve(x: float) -> float:
    """Normalised tyre force for normalised slip ``x`` (1.0 = peak)."""
    return math.sin(_C * math.atan(_B * x))


def _sign(v: float) -> float:
    return 1.0 if v >= 0 else -1.0


@dataclass
class Controls:
    throttle: float = 0.0
    brake: float = 0.0
    steer: float = 0.0
    handbrake: bool = False
    boost: bool = False
    rewind: bool = False
    reset: bool = False


@dataclass
class Env:
    """What the track says about the ground under a car this tick."""
    mu: float = 1.0
    drag: float = 0.0
    wind_x: float = 0.0
    wind_y: float = 0.0
    draft: float = 0.0           # target slipstream strength 0..1
    surface: int = TARMAC


class Car:
    def __init__(self, spec: VehicleSpec, x: float = 0.0, y: float = 0.0, heading: float = 0.0):
        self.spec = spec
        self.x, self.y, self.heading = x, y, heading
        self.vx = self.vy = 0.0
        self.yaw = 0.0
        self.steer_in = 0.0
        self.steer_angle = 0.0
        self.gear = 0
        self.shift_t = 0.0
        self.rpm = 0.15
        self.drive = 0.0               # applied drive acceleration (for effects / sound)
        self.mu = 1.0
        self.hand = 1.0                # rear grip multiplier from handbrake (1 = off)
        self.boost = 0.0
        self.boosting = False
        self.draft = 0.0
        self.drifting = False
        self.drift_time = 0.0
        self.bank = 0.0                # boost earned by the current drift, committed when it ends cleanly
        self._bank_idle = 0.0
        self.slip = 0.0                # body slip angle (rad, signed)
        self.skid = 0.0                # 0..1 tyre-squeal intensity
        self.committed = 0.0           # boost committed by the last drift (for UI feedback)
        self.surface = TARMAC
        self.oil_t = 0.0
        self.ghost_t = 0.0             # >0: no car-car collisions (respawn / rewind grace)
        self._setup()

    # ------------------------------------------------------------------ derived constants
    def _setup(self) -> None:
        s = self.spec
        L = s.wheelbase
        self.a = L * (1.0 - s.wf)             # CG -> front axle
        self.b = L * s.wf                     # CG -> rear axle
        self.inertia = s.mass * (L * L / 4.0) * 1.25
        a_top = torque_at(1.0) * s.power
        self.c_roll = ROLL_DRAG
        self.c_drag = max(1e-5, (a_top / s.top_speed - ROLL_DRAG) / s.top_speed)
        self.gear_tops = [f * s.top_speed for f in GEAR_TOPS]
        self.gear_mult = [(GEAR_TOPS[-1] / f) ** 0.55 for f in GEAR_TOPS]

    def set_spec(self, spec: VehicleSpec) -> None:
        self.spec = spec
        self._setup()

    # ------------------------------------------------------------------ state helpers
    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def fwd(self) -> tuple[float, float]:
        return math.cos(self.heading), math.sin(self.heading)

    def body_velocity(self) -> tuple[float, float]:
        c, s = math.cos(self.heading), math.sin(self.heading)
        return self.vx * c + self.vy * s, -self.vx * s + self.vy * c

    @property
    def forward_speed(self) -> float:
        return self.body_velocity()[0]

    def circles(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        c, s = math.cos(self.heading), math.sin(self.heading)
        off = self.spec.length * 0.25
        r = self.spec.width * 0.5 + 0.5
        return (self.x + c * off, self.y + s * off, r), (self.x - c * off, self.y - s * off, r)

    def place(self, x: float, y: float, heading: float, speed: float = 0.0) -> None:
        self.x, self.y, self.heading = x, y, heading
        self.vx, self.vy = math.cos(heading) * speed, math.sin(heading) * speed
        self.yaw = 0.0
        self.steer_in = self.steer_angle = 0.0
        self.drifting = False
        self.bank = 0.0
        self.hand = 1.0
        self.slip = 0.0

    def snapshot(self) -> tuple:
        return (self.x, self.y, self.heading, self.vx, self.vy, self.yaw, self.steer_in, self.boost, self.gear)

    def restore(self, snap: tuple) -> None:
        (self.x, self.y, self.heading, self.vx, self.vy, self.yaw, self.steer_in, self.boost, self.gear) = snap
        self.bank = 0.0
        self.drifting = False
        self.hand = 1.0

    # ------------------------------------------------------------------ steering authority
    def steer_limit(self, speed: float, mu: float) -> float:
        """Max steering angle (rad): full lock when slow, shrinking with speed to ~grip-limit authority."""
        s = self.spec
        a_lat = BASE_GRIP * s.grip * max(mu, 0.15)
        grip_limited = s.wheelbase * a_lat * s.agility / max(speed * speed, 1.0)
        return min(s.steer, grip_limited)

    # ------------------------------------------------------------------ main step
    def step(self, ctl: Controls, env: Env, dt: float) -> None:
        s = self.spec
        self.surface = env.surface
        # grip adapts quickly to the surface; loss of grip (oil) is immediate
        k_mu = 1.0 - math.exp(-(45.0 if env.mu < self.mu else 16.0) * dt)
        self.mu += (env.mu - self.mu) * k_mu
        mu = self.mu
        self.ghost_t = max(0.0, self.ghost_t - dt)
        self.oil_t = max(0.0, self.oil_t - dt)

        # steering input smoothing (keyboard => ramps, analog => follows)
        tgt = max(-1.0, min(1.0, ctl.steer))
        rate = (9.0 if abs(tgt) < abs(self.steer_in) else 6.5) * dt
        self.steer_in += max(-rate, min(rate, tgt - self.steer_in))

        vf, vl = self.body_velocity()
        speed = math.hypot(vf, vl)
        delta = self.steer_in * self.steer_limit(speed, mu * self.hand ** 0.25)
        if vf > 25.0:
            # counter-steer assist: the front wheels follow the slide (readable drifts on a keyboard)
            beta = math.atan2(vl, vf)
            mag = abs(beta)
            if mag > ASSIST_START:
                k = min(1.0, (mag - ASSIST_START) / 0.1)
                delta += max(-ASSIST_MAX, min(ASSIST_MAX, ASSIST_GAIN * beta)) * k
        delta = max(-s.steer, min(s.steer, delta))
        self.steer_angle = delta

        # handbrake: rear grip drops quickly, returns more gently
        hand_target = s.slide if ctl.handbrake else 1.0
        self.hand += (hand_target - self.hand) * (1.0 - math.exp(-(16.0 if ctl.handbrake else 5.0) * dt))

        # boost
        self.boosting = bool(ctl.boost and self.boost > 0.0 and vf > -5.0)
        if self.boosting:
            self.boost = max(0.0, self.boost - BOOST_USE * dt)

        # slipstream
        k_d = 2.2 if env.draft > self.draft else 3.5
        self.draft += (env.draft - self.draft) * min(1.0, k_d * dt)
        draft_f = self.draft * s.draft
        if draft_f > 0.02 and not self.boosting:
            self.boost = min(s.boost_cap, self.boost + DRAFT_RATE * draft_f * dt)

        # gearbox / engine
        a_eng = self._engine(ctl, vf, dt)

        A = BASE_GRIP * s.grip * mu * (0.92 if self.boosting else 1.0)
        capf, capr = A * s.wf, A * (1.0 - s.wf)
        capr_eff = capr * (self.hand if self.hand < 1.0 else 1.0)
        long_cap_r = max(1.0, capr)
        a_drive = min(a_eng, long_cap_r * 1.05)
        wheelspin = a_eng > long_cap_r
        # braking (ABS-limited by grip) / reverse
        reverse = ctl.brake > 0.05 and vf < 3.0
        brake_cmd = 0.0 if reverse else ctl.brake
        a_brake = min(brake_cmd * s.brake, A * 0.98)
        brake_f = min(a_brake * 0.62, capf)
        brake_r = min(a_brake * 0.38, capr)
        x_df = brake_f / max(capf, 1.0)
        x_dr = (a_drive + brake_r) / long_cap_r
        latf = math.sqrt(max(0.2, 1.0 - 0.5 * x_df * x_df)) * (1.0 - 0.10 * draft_f)
        latr = math.sqrt(max(0.12, 1.0 - 0.5 * min(1.3, x_dr) ** 2))
        if self.boosting:
            a_boost = BOOST_ACCEL * s.boost_power * s.power
        else:
            a_boost = 0.0
        a_hand = 70.0 * mu if (ctl.handbrake and speed > 20.0) else 0.0

        h = dt / SUBSTEPS
        a, b = self.a, self.b
        cd, sd = math.cos(delta), math.sin(delta)
        w = self.yaw
        th = self.heading
        for _ in range(SUBSTEPS):
            speed_h = math.hypot(vf, vl)
            drag_h = self.c_drag * (1.0 - min(0.6, 0.38 * draft_f)) * speed_h + self.c_roll + env.drag
            vyf = vl + a * w
            vyr = vl - b * w
            vlong_f = vf * cd + vyf * sd
            vlat_f = vyf * cd - vf * sd
            alpha_f = math.atan2(vlat_f, max(abs(vlong_f), V_MIN))
            alpha_r = math.atan2(vyr, max(abs(vf), V_MIN))
            ff = -capf * latf * tire_curve(alpha_f / ALPHA_PEAK)
            fr = -capr_eff * latr * tire_curve(alpha_r / ALPHA_PEAK)
            ax = vl * w - ff * sd - drag_h * vf
            ay = ff * cd + fr - vf * w - drag_h * vl
            if reverse:
                if vf > -REVERSE_MAX:
                    ax -= REVERSE_ACCEL * ctl.brake
            else:
                ax += a_drive * (1.0 - 0.8 * brake_cmd) + a_boost
                if a_brake > 0.0 or a_hand > 0.0:
                    sgn = _sign(vf)
                    ax -= sgn * min(a_brake + a_hand, abs(vf) / h)
            az = (a * ff * cd - b * fr) / self.inertia * s.mass
            # coulomb friction keeps a parked car parked
            if speed_h < 6.0 and ctl.throttle < 0.05 and ctl.brake < 0.05:
                ax -= _sign(vf) * min(abs(vf) / h, 40.0)
                ay -= _sign(vl) * min(abs(vl) / h, 40.0)
            vf += ax * h
            vl += ay * h
            w += az * h
            w *= max(0.0, 1.0 - 0.6 * h)         # structural yaw damping
            th += w * h
            c, sn = math.cos(th), math.sin(th)
            self.vx = vf * c - vl * sn
            self.vy = vf * sn + vl * c
            self.vx += env.wind_x * h
            self.vy += env.wind_y * h
            self.x += self.vx * h
            self.y += self.vy * h
            # re-derive body velocity after wind (keeps frame consistent)
            vf = self.vx * c + self.vy * sn
            vl = -self.vx * sn + self.vy * c
        self.yaw = w
        self.heading = (th + math.pi) % math.tau - math.pi

        self._update_drift(ctl, vf, vl, dt, wheelspin)
        self.drive = a_drive

    # ------------------------------------------------------------------ engine
    def _engine(self, ctl: Controls, vf: float, dt: float) -> float:
        s = self.spec
        v = max(0.0, vf)
        if self.shift_t > 0.0:
            self.shift_t = max(0.0, self.shift_t - dt)
        top_g = self.gear_tops[self.gear]
        r = v / top_g
        if self.shift_t <= 0.0:
            if r > 0.93 and self.gear < len(self.gear_tops) - 1:
                self.gear += 1
                self.shift_t = SHIFT_TIME
            elif r < 0.42 and self.gear > 0:
                self.gear -= 1
                self.shift_t = SHIFT_TIME * 0.5
        top_g = self.gear_tops[self.gear]
        r = v / top_g
        target_rpm = 0.2 + 0.8 * min(1.15, r)
        if ctl.throttle < 0.05:
            target_rpm = max(0.15, target_rpm - 0.12)
        elif v < 20.0:
            target_rpm = max(target_rpm, 0.2 + 0.5 * ctl.throttle)       # clutch slip at launch
        self.rpm += (target_rpm - self.rpm) * min(1.0, 14.0 * dt)
        if ctl.throttle <= 0.0 or vf < -5.0:
            return 0.0
        tq = torque_at(r)
        if self.boosting:
            tq = max(tq, torque_at(1.0))
        cut = 0.2 if self.shift_t > 0.0 else 1.0
        return s.power * tq * self.gear_mult[self.gear] * cut * max(0.0, min(1.0, ctl.throttle))

    # ------------------------------------------------------------------ drift bookkeeping
    def _update_drift(self, ctl: Controls, vf: float, vl: float, dt: float, wheelspin: bool) -> None:
        speed = math.hypot(vf, vl)
        self.slip = math.atan2(vl, vf) if vf > 1.0 else 0.0
        a = abs(self.slip)
        was = self.drifting
        if not was and a > DRIFT_ON and speed > DRIFT_MIN_SPEED:
            self.drifting = True
        elif was and (a < DRIFT_OFF or speed < DRIFT_MIN_SPEED * 0.8):
            self.drifting = False
        skid_target = 0.0
        if self.drifting:
            skid_target = min(1.0, 0.45 + a)
        elif a > 0.1 and speed > 60.0:
            skid_target = min(1.0, a * 3.0)
        if wheelspin and speed < 140.0 and self.surface != OIL:
            skid_target = max(skid_target, 0.5)
        if self.surface == OIL:
            skid_target = max(skid_target, 0.4)
        self.skid += (skid_target - self.skid) * min(1.0, 12.0 * dt)
        if self.drifting:
            self.drift_time += dt
            self.bank = min(self.spec.boost_cap, self.bank + DRIFT_RATE * a * (speed / 300.0)
                            * self.spec.drift_charge * dt)
            self._bank_idle = 0.0
        else:
            self.drift_time = 0.0
            if self.bank > 0.0:
                self._bank_idle += dt
                if self._bank_idle >= 0.30:
                    gained = self.bank
                    self.boost = min(self.spec.boost_cap, self.boost + gained)
                    self.committed = gained
                    self.bank = 0.0
                    self._bank_idle = 0.0

    def lose_drift(self) -> float:
        """A crash cancels the uncommitted drift bank (the risk side of drift boost)."""
        lost, self.bank = self.bank, 0.0
        self.drifting = False
        return lost


# ------------------------------------------------------------------------------------ collisions
CAR_RESTITUTION = 0.22
WALL_RESTITUTION = 0.18
MAX_PUSH = 8.0


def resolve_cars(a: Car, b: Car) -> tuple[float, float, float] | None:
    """Soft circle-pair collision.  Returns (impact speed, contact x, contact y) or None."""
    if a.ghost_t > 0.0 or b.ghost_t > 0.0:
        return None
    dx, dy = b.x - a.x, b.y - a.y
    reach = (a.spec.length + b.spec.length) * 0.5 + 1.0
    if dx * dx + dy * dy > reach * reach:
        return None
    best = None
    for ax, ay, ar in a.circles():
        for bx, by, br in b.circles():
            ddx, ddy = ax - bx, ay - by
            d2 = ddx * ddx + ddy * ddy
            lim = ar + br
            if d2 < lim * lim:
                d = math.sqrt(d2) or 1e-6
                pen = lim - d
                if best is None or pen > best[0]:
                    best = (pen, ddx / d, ddy / d, (ax + bx) * 0.5, (ay + by) * 0.5)
    if best is None:
        return None
    pen, nx, ny, cx, cy = best
    ma, mb = a.spec.mass, b.spec.mass
    tot = ma + mb
    push = min(pen, MAX_PUSH) * 0.85
    a.x += nx * push * mb / tot
    a.y += ny * push * mb / tot
    b.x -= nx * push * ma / tot
    b.y -= ny * push * ma / tot
    rax, ray = cx - a.x, cy - a.y
    rbx, rby = cx - b.x, cy - b.y
    vax = a.vx - a.yaw * ray
    vay = a.vy + a.yaw * rax
    vbx = b.vx - b.yaw * rby
    vby = b.vy + b.yaw * rbx
    vn = (vax - vbx) * nx + (vay - vby) * ny
    if vn >= 0.0:
        return None
    ca = rax * ny - ray * nx
    cb = rbx * ny - rby * nx
    inv = 1.0 / ma + 1.0 / mb + ca * ca / a.inertia + cb * cb / b.inertia
    j = -(1.0 + CAR_RESTITUTION) * vn / inv
    j = min(j, 160.0 * min(ma, mb) * 1.8)
    a.vx += j * nx / ma
    a.vy += j * ny / ma
    b.vx -= j * nx / mb
    b.vy -= j * ny / mb
    a.yaw += max(-3.0, min(3.0, j * ca / a.inertia)) * 0.8
    b.yaw -= max(-3.0, min(3.0, j * cb / b.inertia)) * 0.8
    a.yaw *= 0.9
    b.yaw *= 0.9
    return -vn, cx, cy


def wall_response(car: Car, nx: float, ny: float, depth: float, px: float, py: float) -> float:
    """Push ``car`` out of a wall (normal pointing back into the drivable area).  Returns impact speed."""
    push = min(depth, MAX_PUSH)
    car.x += nx * push
    car.y += ny * push
    vn = car.vx * nx + car.vy * ny
    if vn >= 0.0:
        return 0.0
    vt_x, vt_y = car.vx - vn * nx, car.vy - vn * ny
    # scrape: lose a little tangential speed in proportion to how hard we hit
    scrape = 1.0 - min(0.35, 0.10 + 0.0015 * -vn)
    car.vx = vt_x * scrape - WALL_RESTITUTION * vn * nx
    car.vy = vt_y * scrape - WALL_RESTITUTION * vn * ny
    rx, ry = px - car.x, py - car.y
    torque = rx * (-vn * ny) - ry * (-vn * nx)
    car.yaw += max(-2.5, min(2.5, torque * 0.5 / car.inertia * car.spec.mass * 6.0))
    car.yaw *= 0.8
    return -vn


def circle_bump(car: Car, ox: float, oy: float, radius: float, loss: float = 0.82) -> float:
    """Collide a car with a small static solid (boulder): shove the car out and bleed speed."""
    for cx, cy, r in car.circles():
        dx, dy = cx - ox, cy - oy
        lim = r + radius
        d2 = dx * dx + dy * dy
        if d2 < lim * lim:
            d = math.sqrt(d2) or 1e-6
            nx, ny = dx / d, dy / d
            car.x += nx * (lim - d)
            car.y += ny * (lim - d)
            vn = car.vx * nx + car.vy * ny
            if vn < 0.0:
                car.vx -= 1.3 * vn * nx
                car.vy -= 1.3 * vn * ny
                car.vx *= loss
                car.vy *= loss
                car.yaw += 0.8 * (1 if (dx * ny - dy * nx) > 0 else -1)
                return -vn
    return 0.0
