"""Rival drivers.  They use exactly the same car model and limits as the player: difficulty only changes
*skill* (braking margin, line quality, reaction noise, contact tolerance), never speed.

* Racing line: lateral offset that cuts corners (inside at the apex, wide on approach) computed from curvature.
* Speed profile: grip-limited corner speed per sample, then a backward braking pass so the car brakes for corners
  it cannot see yet only as far ahead as its skill allows.
* Overtaking: when a slower car is ahead and there is room, commit to a lane for a moment; avoid side contact.
* Recovery: if facing the wrong way or stuck, realign (the race also auto-respawns after a timeout).
* Adaptation (bounded): if the human keeps passing on the inside, rivals defend the inside line a little more.
"""
from __future__ import annotations

import math

from ...core.ai import Adaptation, AdaptiveController, PlayerModel
from ...core.rng import Rng
from .physics import BASE_GRIP, SURFACE_MU, Controls
from .track import SPACING, Track

PERSONALITIES = {
    "clean": {"margin": 0.90, "gap": 38.0, "noise": 0.02, "bold": 0.35, "defend": 0.5},
    "aggressive": {"margin": 0.97, "gap": 20.0, "noise": 0.04, "bold": 0.9, "defend": 0.9},
    "erratic": {"margin": 0.93, "gap": 28.0, "noise": 0.10, "bold": 0.6, "defend": 0.3},
}


class LineModel:
    """Per-track precomputed racing line and speed limits for one vehicle (cached by the scene)."""

    def __init__(self, track: Track, spec, margin: float = 0.92):
        self.track = track
        n = track.n
        kap = [abs(k) for k in track.kappa]
        sm = []
        w = 14
        for i in range(n):
            sm.append(sum(track.kappa[(i + d) % n] for d in range(-w, w + 1)) / (2 * w + 1))
        self.lat = []
        for i in range(n):
            half = track.width[i] * 0.5
            self.lat.append(max(-0.62 * half, min(0.62 * half, sm[i] * 95.0 * half * 0.62)))
        a_lat = BASE_GRIP * spec.grip * 0.82 * margin
        self.vmax = []
        for i in range(n):
            mu = SURFACE_MU[track.surface[i]]
            k = max(kap[i], abs(sm[i]) * 0.9, 1e-4) * 0.75       # the line is wider than the centreline
            self.vmax.append(min(spec.top_speed * 1.0, math.sqrt(a_lat * mu / k)))
        a_brake = spec.brake * 0.55 * margin
        for _ in range(3):
            for i in range(n - 1, -1, -1):
                nxt = self.vmax[(i + 1) % n]
                self.vmax[i] = min(self.vmax[i], math.sqrt(nxt * nxt + 2 * a_brake * SPACING))


class Driver:
    def __init__(self, line: LineModel, personality: str = "clean", skill: float = 0.9, seed: int = 0,
                 adapt: AdaptiveController | None = None):
        self.line = line
        self.p = dict(PERSONALITIES[personality])
        self.personality = personality
        self.skill = skill
        self.rng = Rng(seed).child("driver", personality)
        self.lane_shift = 0.0
        self.lane_until = 0.0
        self.reverse_t = 0.0
        self.noise = 0.0
        self.adapt = adapt
        self.log: list[str] = []

    def control(self, race, racer) -> Controls:
        tr = self.line.track
        n = tr.n
        c = racer.car
        i = racer.hint
        spd = c.speed
        t = race.t
        ctl = Controls()
        # --- recovery: pointing the wrong way
        fwd_ang = math.atan2(tr.tang[i][1], tr.tang[i][0])
        misalign = (c.heading - fwd_ang + math.pi) % math.tau - math.pi
        if abs(misalign) > 1.7 and spd < 90:
            self.reverse_t = 0.7
        if self.reverse_t > 0:
            self.reverse_t -= 1 / 60
            ctl.brake = 1.0
            ctl.steer = 1.0 if misalign > 0 else -1.0       # reversing flips the steering sense
            return ctl
        # --- lane choice (overtake / defend)
        self._lanes(race, racer, i, t)
        look = int((26 + spd * 0.26) / SPACING)
        j = (i + max(2, look)) % n
        half = tr.width[j] * 0.5
        lat = self.line.lat[j] + self.lane_shift * half * 0.5
        lat = max(-half * 0.8, min(half * 0.8, lat))
        tx = tr.pts[j][0] + tr.norm[j][0] * lat
        ty = tr.pts[j][1] + tr.norm[j][1] * lat
        # the shortcut is a bold line: aggressive drivers enter it at the mouth and follow the corridor
        cut = tr.cut
        if cut is not None and self.p["bold"] > 0.5 and self.skill > 0.7:
            cd, ct = cut.lateral(c.x, c.y)
            before = (cut.ia - i) % n
            if cd < cut.half + 4 and 0.0 < ct < 0.98:
                tx = cut.ax + (cut.bx - cut.ax) * min(1.0, ct + 0.22)
                ty = cut.ay + (cut.by - cut.ay) * min(1.0, ct + 0.22)
            elif before < 30 and spd < 215:
                tx, ty = cut.ax, cut.ay
        ang = math.atan2(ty - c.y, tx - c.x)
        err = (ang - c.heading + math.pi) % math.tau - math.pi
        self.noise += (self.rng.uniform(-1, 1) - self.noise) * 0.05
        steer = err * 1.9 - c.yaw * 0.12 + self.noise * self.p["noise"] * 8 * (1.0 - self.skill + 0.2)
        ctl.steer = max(-1.0, min(1.0, steer))
        # --- speed: look ahead as far as the braking distance requires, scaled by skill
        horizon = int((spd * spd / (2 * 300.0) + 40) / SPACING * (0.6 + 0.4 * self.skill)) + 2
        vt = min(self.line.vmax[(i + k) % n] for k in range(0, horizon, 2 if horizon > 12 else 1))
        vt *= 0.9 + 0.1 * self.skill
        vt = min(vt, c.spec.top_speed * 1.01)
        if racer.zone != "track":
            vt = min(vt, 150)
        if spd < vt - 4:
            ctl.throttle = 1.0
        elif spd > vt + 8:
            ctl.brake = min(1.0, (spd - vt) / 40)
            ctl.throttle = 0.0
        else:
            ctl.throttle = 0.45
        # --- tools
        straight = abs(tr.kappa[i]) < 0.0018 and abs(err) < 0.15
        if c.boost > 45 and straight and spd < c.spec.top_speed * 0.97 and race.state == "racing":
            ctl.boost = True
        if self.p["bold"] > 0.5 and abs(err) > 0.55 and spd > 140 and abs(misalign) < 1.2:
            ctl.handbrake = True
        if c.spec.special == "rewind" and racer.rewind_ready and racer.wall_hits and spd < 40:
            ctl.rewind = True
        if racer.wall_hits > 0 and spd < 15:
            racer.wall_hits = 0
        return ctl

    # ------------------------------------------------------------------ overtaking / defending
    def _lanes(self, race, racer, i: int, t: float) -> None:
        tr = self.line.track
        if t < self.lane_until:
            return
        self.lane_shift *= 0.5
        c = racer.car
        fx, fy = math.cos(c.heading), math.sin(c.heading)
        for o in race.racers:
            if o is racer:
                continue
            dx, dy = o.car.x - c.x, o.car.y - c.y
            ahead = dx * fx + dy * fy
            side = -dx * fy + dy * fx             # positive = other car is to my right
            if 0 < ahead < 90 and abs(side) < 16:
                slower = o.car.speed < c.speed * 1.02
                if slower:
                    half = tr.width[i] * 0.5
                    room_r = half - tr.lateral(i, o.car.x, o.car.y) - 18
                    room_l = half + tr.lateral(i, o.car.x, o.car.y) - 18
                    pref = -1.0 if (side > 0) else 1.0
                    self.lane_shift = pref if (room_r if pref > 0 else room_l) > 10 else -pref
                    self.lane_until = t + 0.9 + 0.5 * self.p["gap"] / 38
                    self.log.append("overtake")
                    return
            elif -40 < ahead < 10 and abs(side) < 15:       # a car right beside: ease away
                self.lane_shift = -1.0 if side > 0 else 1.0
                self.lane_until = t + 0.5
                return
        # defend: the human is close behind on the inside -> drift toward the apex side
        if self.adapt is not None:
            lvl = self.adapt.level("block_inside")
            if lvl > 0.02:
                for o in race.racers:
                    if o.human >= 0 and -60 < ((o.car.x - c.x) * fx + (o.car.y - c.y) * fy) < -6:
                        k = tr.kappa[i]
                        self.lane_shift = max(-1.0, min(1.0, (1 if k > 0 else -1) * lvl * 2.2))
                        self.lane_until = t + 0.6
                        self.log.append("defend")
                        return


def make_adaptation(strength: float = 1.0) -> tuple[PlayerModel, AdaptiveController]:
    model = PlayerModel(half_life=40.0)
    ctl = AdaptiveController(model, [Adaptation("block_inside", "pass_inside", ("pass_inside", "pass_outside"),
                                                threshold=0.62, min_weight=2.5, max_bonus=0.3)],
                             strength=strength, cooldown=20.0)
    return model, ctl


def classify_pass(track: Track, passer, passed) -> str:
    """Did the human pass on the inside of the corner (toward its apex) or the outside?"""
    i = passed.hint
    k = track.kappa[i]
    if abs(k) < 0.0015:
        return "straight"
    side = track.lateral(i, passer.car.x, passer.car.y) - track.lateral(i, passed.car.x, passed.car.y)
    return "pass_inside" if side * k > 0 else "pass_outside"
