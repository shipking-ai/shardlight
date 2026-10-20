"""The Lampwright: movement, dodge, parry and weapon move execution (all data-driven by WeaponDef).

States: free | attack | charge | dodge | parry | hurt | dead.  Inputs are buffered in *simulation* frames
(the buffer clock does not advance during hit-stop, so a press made during a freeze is never lost).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..defs import MoveDef, WeaponDef
from .entities import PLAYER_TEAM, Entity, Hazard, Hitbox, Projectile
from .geometry import angle_diff, angle_to, dist, segment_blocked, turn_toward, unit

# Movement tuning (pixels per tick, pixels per tick^2)
BASE_SPEED = 1.62
ACCEL = 0.34           # reaches top speed in ~5 frames
FRICTION = 0.46        # stops in ~3-4 frames
PLAYER_RADIUS = 5.0
BASE_HP = 100.0
HURT_IFRAMES = 40

BUFFER_WINDOWS = {"attack": 9, "heavy": 8, "dodge": 10, "parry": 8, "interact": 6, "flare": 8, "swap": 6}


@dataclass
class Intent:
    """One tick of player input in game terms (built by the scene from ``PlayerState``)."""
    move: tuple[float, float] = (0.0, 0.0)
    aim: tuple[float, float] = (0.0, 0.0)
    pressed: set = field(default_factory=set)       # attack heavy dodge parry interact swap flare
    held: set = field(default_factory=set)          # attack heavy parry
    aim_assist: bool = True


class InputBuffer:
    def __init__(self) -> None:
        self.t = 0
        self.last: dict[str, int] = {}

    def record(self, pressed) -> None:
        for p in pressed:
            self.last[p] = self.t

    def advance(self) -> None:
        self.t += 1

    def peek(self, name: str, frames: int | None = None) -> bool:
        f = self.last.get(name)
        return f is not None and self.t - f <= (frames if frames is not None else BUFFER_WINDOWS.get(name, 8))

    def consume(self, name: str) -> bool:
        if self.peek(name):
            self.last[name] = -10_000
            return True
        return False

    def clear(self) -> None:
        self.last.clear()


def pick_target(room, x: float, y: float, facing: float, max_dist: float, cone_deg: float,
                need_los: bool = False):
    """Best enemy in a cone: nearest, weighted by angular offset."""
    best, best_s = None, 1e9
    half = math.radians(cone_deg) / 2
    for e in room.enemies:
        if not e.alive or getattr(e, "untargetable", False):
            continue
        d = dist(x, y, e.x, e.y)
        if d > max_dist + e.r:
            continue
        a = abs(angle_diff(angle_to(x, y, e.x, e.y), facing))
        if a > half:
            continue
        if need_los and segment_blocked(room.proj_solid, x, y, e.x, e.y):
            continue
        s = d + a * 38
        if s < best_s:
            best, best_s = e, s
    return best


class Player(Entity):
    kind = "player"

    def __init__(self, x: float, y: float, run) -> None:
        super().__init__(x, y, PLAYER_RADIUS, BASE_HP, PLAYER_TEAM)
        self.run = run
        self.buffer = InputBuffer()
        self.state = "free"
        self.move: MoveDef | None = None
        self.t = 0                    # frames in current state
        self.combo_i = 0
        self.combo_idle = 99
        self.move_spawned = False
        self.charge_t = 0
        self.charge_tier = 0
        self.dodge_dir = (1.0, 0.0)
        self.dodge_cd = 0
        self.dodge_total = 13
        self.dodge_iframes = 12
        self.dodge_recover = 7
        self.dodge_dist = 56.0
        self.vault_z = 0.0
        self.parry_t = 0
        self.parry_cd = 0
        self.parry_window = 8
        self.parry_recover = 18
        self.riposte_t = 0
        self.hurt_t = 0
        self.lunge_t = 0
        self.lunge_v = 0.0
        self.swing_dir = 1
        self.post_dodge = 0           # frames since a dodge ended (dash-attack window)
        self.trail_t = 0
        self.trail_args: dict = {}
        self.attack_label = ""
        self.last_aim_target = None
        self.charge_armor = False
        self.armor = False
        self.walk_phase = 0.0
        self.moving = False
        self.dead_anim = 0
        self.perfect_flash = 0
        self.damage_flash_color = (255, 255, 255)
        self.dodge_style = "roll"
        self.unarmed_t = 0
        self.damage_bonus = 1.0

    # ---------------------------------------------------------------------------- derived stats
    @property
    def weapon(self) -> WeaponDef:
        return self.run.weapon

    @property
    def perks(self):
        return self.run.perks

    def max_speed(self) -> float:
        s = BASE_SPEED * self.perks.get("move_speed_mul") * self.status.slow_mult()
        if self.status.has("ash"):
            s *= max(0.2, 1.0 - self.perks.get("ash_move_penalty"))
        return s

    def attack_rate(self) -> float:
        return max(0.3, self.perks.get("attack_speed_mul"))

    # ---------------------------------------------------------------------------- aiming
    def aim_angle(self, room, intent: Intent, ranged: bool = False, reach: float = 60.0) -> float:
        """Direction for a new action: aim stick > assisted target > last movement direction."""
        ax, ay = intent.aim
        if ax * ax + ay * ay > 0.09:
            return math.atan2(ay, ax)
        mx, my = intent.move
        base = math.atan2(my, mx) if mx * mx + my * my > 0.04 else self.facing
        if intent.aim_assist:
            if ranged:
                tgt = pick_target(room, self.x, self.y, base, 260, 80, need_los=True)
            else:
                tgt = pick_target(room, self.x, self.y, base, reach + 28, 100)
            if tgt is not None:
                self.last_aim_target = tgt
                return angle_to(self.x, self.y, tgt.x, tgt.y)
        return base

    # ---------------------------------------------------------------------------- main update
    def update(self, room, intent: Intent) -> None:
        self.age += 1
        self.buffer.record(intent.pressed)
        self.buffer.advance()
        if self.iframes > 0:
            self.iframes -= 1
        if self.flash > 0:
            self.flash -= 1
        if self.riposte_t > 0:
            self.riposte_t -= 1
        if self.dodge_cd > 0:
            self.dodge_cd -= 1
        if self.parry_cd > 0:
            self.parry_cd -= 1
        if self.perfect_flash > 0:
            self.perfect_flash -= 1
        self.combo_idle += 1
        self.post_dodge += 1
        if not self.alive:
            self.dead_anim += 1
            return
        self.armor = False
        st = self.state
        if st == "hurt":
            self._hurt(room, intent)
        elif st == "dodge":
            self._dodge(room, intent)
        elif st == "attack":
            self._attack(room, intent)
        elif st == "charge":
            self._charge(room, intent)
        elif st == "parry":
            self._parry(room, intent)
        else:
            self._free(room, intent)
        if self.combo_idle > 22 and self.state != "attack":
            self.combo_i = 0
        self._integrate(room)

    # ---------------------------------------------------------------------------- movement
    def _steer(self, intent: Intent, mult: float) -> None:
        mx, my = intent.move
        mag = math.hypot(mx, my)
        top = self.max_speed() * mult
        if mag > 0.05:
            mag = min(1.0, mag)
            tx, ty = mx / math.hypot(mx, my) * top * mag, my / math.hypot(mx, my) * top * mag
            ex, ey = tx - self.vx, ty - self.vy
            e = math.hypot(ex, ey)
            step = ACCEL * (1.0 if mult >= 0.6 else 1.4)
            if e <= step:
                self.vx, self.vy = tx, ty
            else:
                self.vx += ex / e * step
                self.vy += ey / e * step
            self.moving = True
        else:
            sp = math.hypot(self.vx, self.vy)
            if sp <= FRICTION:
                self.vx = self.vy = 0.0
            else:
                k = (sp - FRICTION) / sp
                self.vx *= k
                self.vy *= k
            self.moving = False

    def _integrate(self, room) -> None:
        vx, vy = self.vx, self.vy
        if self.lunge_t > 0:
            self.lunge_t -= 1
            vx += math.cos(self.facing) * self.lunge_v
            vy += math.sin(self.facing) * self.lunge_v
        vx += self.kx
        vy += self.ky
        self.kx *= 0.82
        self.ky *= 0.82
        if abs(self.kx) < 0.02:
            self.kx = 0.0
        if abs(self.ky) < 0.02:
            self.ky = 0.0
        if vx or vy:
            nx, ny, hx, hy = room.move_entity(self, vx, vy, through_enemies=self.state == "dodge")
            if hx:
                self.vx = 0.0
            if hy:
                self.vy = 0.0
            if self.moving and self.state in ("free", "attack", "charge", "parry"):
                self.walk_phase += math.hypot(vx, vy) * 0.11

    # ---------------------------------------------------------------------------- free state
    def _free(self, room, intent: Intent) -> None:
        self._steer(intent, 1.0)
        mx, my = intent.move
        if mx * mx + my * my > 0.04:
            self.facing = math.atan2(my, mx)
        ax, ay = intent.aim
        if ax * ax + ay * ay > 0.09:
            self.facing = math.atan2(ay, ax)
        b = self.buffer
        if b.peek("dodge") and self.dodge_cd <= 0:
            b.consume("dodge")
            self.start_dodge(room, intent)
            return
        if b.peek("parry") and self.parry_cd <= 0:
            b.consume("parry")
            self.start_parry(room, intent)
            return
        if b.peek("heavy"):
            b.consume("heavy")
            self.start_charge(room, intent)
            return
        if b.peek("attack"):
            b.consume("attack")
            self.start_light(room, intent)

    # ---------------------------------------------------------------------------- attacks
    def _ranged(self, mv: MoveDef) -> bool:
        return mv.shape == "proj"

    def start_move(self, room, mv: MoveDef, intent: Intent, damage_bonus: float = 1.0, label: str = "") -> None:
        self.state = "attack"
        self.move = mv
        self.t = 0
        self.move_spawned = False
        self.damage_bonus = damage_bonus
        self.attack_label = label or mv.name
        reach = mv.reach + mv.offset
        self.facing = self.aim_angle(room, intent, self._ranged(mv), reach)
        self.swing_dir = -self.swing_dir
        self.run.note_attack(self.weapon)
        self.run.on_attack(mv, self.weapon)
        room.emit("attack_start", self.x, self.y, move=mv.name, sfx=mv.sfx, heavy="heavy" in mv.tags)

    def start_light(self, room, intent: Intent) -> None:
        w = self.weapon
        if self.riposte_t > 0 and w.riposte is not None:
            self.riposte_t = 0
            self.combo_i = 0
            self.start_move(room, w.riposte, intent, 1.5, "riposte")
            return
        if self.post_dodge <= 10 and self.state == "free" and w.dash_attack is not None:
            self.start_move(room, w.dash_attack, intent, 1.0, "dash")
            return
        if self.combo_idle > 22:
            self.combo_i = 0
        mv = w.light[self.combo_i % len(w.light)]
        bonus = 1.5 if self.riposte_t > 0 else 1.0
        self.start_move(room, mv, intent, bonus)
        self.combo_i = (self.combo_i + 1) % len(w.light)

    def start_charge(self, room, intent: Intent) -> None:
        self.state = "charge"
        self.t = 0
        self.charge_t = 0
        self.charge_tier = 0
        self.charge_armor = self.weapon.charge_armor
        room.emit("charge_start", self.x, self.y)

    def _charge(self, room, intent: Intent) -> None:
        w = self.weapon
        self.charge_t += 1
        self.t += 1
        self.armor = w.charge_armor
        self._steer(intent, w.charge_speed)
        mx, my = intent.move
        ax, ay = intent.aim
        if ax * ax + ay * ay > 0.09:
            self.facing = turn_toward(self.facing, math.atan2(ay, ax), 0.35)
        elif mx * mx + my * my > 0.04:
            self.facing = turn_toward(self.facing, math.atan2(my, mx), 0.25)
        gain = self.perks.get("charge_speed_mul")
        eff = int(self.charge_t * gain * self.attack_rate())
        tier = 0
        for i, tr in enumerate(w.heavy):
            if eff >= tr.hold:
                tier = i
        if tier > self.charge_tier:
            self.charge_tier = tier
            room.emit("charge_tier", self.x, self.y, tier=tier, top=tier == len(w.heavy) - 1)
        if self.buffer.peek("dodge") and self.dodge_cd <= 0 and self.charge_t > 3:
            self.buffer.consume("dodge")
            self.start_dodge(room, intent)
            return
        if "heavy" not in intent.held:
            mv = w.heavy[self.charge_tier].move
            self.start_move(room, mv, intent, 1.0, f"heavy{self.charge_tier}")
            room.run.on_charge_release(self.charge_tier, len(w.heavy))
            room.fire("charge_release", tier=self.charge_tier, x=self.x, y=self.y)

    def _attack(self, room, intent: Intent) -> None:
        mv = self.move
        w = self.weapon
        rate = self.attack_rate()
        self.t += 1 if rate <= 1.0 or self.t % 3 else 2
        t = self.t
        self.armor = mv.armor
        # movement during the move
        self._steer(intent, mv.move_mult)
        if t == mv.windup and not self.move_spawned:
            self.move_spawned = True
            self._spawn_move(room, mv)
        elif mv.hits > 1 and mv.windup < t < mv.windup + mv.active and (t - mv.windup) % mv.interval == 0 \
                and mv.shape != "proj":
            self._spawn_move(room, mv)
        elif mv.shape == "proj" and mv.hits > 1 and mv.windup < t < mv.windup + mv.active and \
                (t - mv.windup) % mv.interval == 0:
            self._spawn_move(room, mv)
        end_active = mv.windup + mv.active
        b = self.buffer
        if t >= mv.windup + 1 and b.peek("dodge") and self.dodge_cd <= 0:
            b.consume("dodge")
            self.start_dodge(room, intent)
            return
        if t >= end_active and b.peek("parry") and self.parry_cd <= 0:
            b.consume("parry")
            self.start_parry(room, intent)
            return
        if t >= end_active + mv.cancel:
            if b.peek("attack"):
                b.consume("attack")
                self.combo_idle = 0
                self.start_light(room, intent)
                return
            if b.peek("heavy"):
                b.consume("heavy")
                self.start_charge(room, intent)
                return
        if t >= mv.total:
            self.state = "free"
            self.move = None
            self.combo_idle = 0

    def _spawn_move(self, room, mv: MoveDef) -> None:
        w = self.weapon
        perks = self.perks
        dmg = w.damage * mv.damage * self.run.weapon_level_mult() * perks.get("damage_mul") * self.damage_bonus
        dmg *= self.run.kill_streak_mult()
        crit = False
        if perks.get("crit_chance") > 0 and room.rng.random() < perks.get("crit_chance"):
            dmg *= 1.6
            crit = True
        reach_mul = perks.get("reach_mul")
        if mv.lunge > 0 and mv.lunge_frames > 0:
            self.lunge_t = mv.lunge_frames
            self.lunge_v = mv.lunge
        room.emit("swing", self.x, self.y, move=mv.name, facing=self.facing, fx=mv.fx, shape=mv.shape,
                  reach=mv.reach * reach_mul, arc=mv.arc, color=w.color, dir=self.swing_dir, heavy="heavy" in mv.tags)
        if mv.shape == "proj":
            self._fire(room, mv, dmg, crit)
            return
        shape = mv.shape
        hb = Hitbox(
            owner=self, team=PLAYER_TEAM, shape=shape, x=self.x, y=self.y, facing=self.facing,
            reach=mv.reach * reach_mul, arc=mv.arc, width=mv.width, inner=mv.inner, damage=dmg,
            poise=mv.poise * 10 * perks.get("poise_mul"),
            knock=mv.knock, stop=mv.stop, shake=mv.shake, windup=0, active=max(2, mv.active - 1 if mv.hits == 1 else 3),
            apply=mv.apply, follow=shape in ("arc", "thrust"), follow_offset=mv.offset,
            ring_from=mv.inner if shape == "ring" else 0.0, tags=mv.tags, move_name=mv.name, crit=crit,
            source=self.weapon.id)
        if shape == "circle":
            hb.x += math.cos(self.facing) * mv.offset
            hb.y += math.sin(self.facing) * mv.offset
        room.add_hitbox(hb)

    def _fire(self, room, mv: MoveDef, dmg: float, crit: bool) -> None:
        p = mv.proj
        perks = self.perks
        count = int(p.get("count", 1))
        spread = math.radians(float(p.get("spread", 0)))
        speed = float(p.get("speed", 4.0))
        charged = "charged" in mv.tags
        for i in range(count):
            off = 0.0 if count == 1 else (i / (count - 1) - 0.5) * spread
            a = self.facing + off
            ox = self.x + math.cos(a) * (self.r + 4)
            oy = self.y + math.sin(a) * (self.r + 4)
            pr = Projectile(
                x=ox, y=oy, vx=math.cos(a) * speed, vy=math.sin(a) * speed, r=float(p.get("radius", 3)),
                damage=dmg, team=PLAYER_TEAM, owner=self, life=int(p.get("life", 90)),
                kind=p.get("kind", "bolt"), pierce=int(p.get("pierce", 0)) + int(perks.get("pierce_add")),
                ricochet=int(p.get("ricochet", 0)) + (int(perks.get("ricochet_add")) if charged or p.get("ricochet") else 0),
                parryable=False, apply=mv.apply, poise=mv.poise * 10, knock=mv.knock,
                homing=float(p.get("homing", 0)), chain=int(p.get("chain", 0)), color=self.weapon.color,
                source=self.weapon.id, stop=mv.stop, charged=charged)
            room.add_projectile(pr)
        # recoil
        self.add_knock(self.facing + math.pi, 0.6 if charged else 0.25)

    # ---------------------------------------------------------------------------- dodge
    def start_dodge(self, room, intent: Intent) -> None:
        w = self.weapon
        d = w.dodge
        perks = self.perks
        mx, my = intent.move
        if mx * mx + my * my > 0.04:
            dx, dy = unit(mx, my)
        else:
            dx, dy = math.cos(self.facing), math.sin(self.facing)
        self.state = "dodge"
        self.t = 0
        self.dodge_dir = (dx, dy)
        self.dodge_style = d.get("kind", "roll")
        self.dodge_total = int(d.get("frames", 13))
        self.dodge_iframes = int(d.get("iframes", 12)) + int(perks.get("dodge_iframes_add"))
        self.dodge_recover = max(1, int(d.get("recover", 7) * perks.get("dodge_recover_mul")))
        self.dodge_dist = float(d.get("dist", 56)) * perks.get("dodge_dist_mul")
        self.iframes = max(self.iframes, self.dodge_iframes)
        self.facing = math.atan2(dy, dx)
        self.vx = self.vy = 0.0
        self.lunge_t = 0
        self.move = None
        self.status.clear("burn")        # rolling smothers flames
        # classify the dodge relative to the nearest threat for the adaptive model
        room.note_dodge(self, dx, dy)
        room.emit("dodge", self.x, self.y, dx=dx, dy=dy, style=self.dodge_style)
        room.fire("dodge", x=self.x, y=self.y, dx=dx, dy=dy)

    def _dodge(self, room, intent: Intent) -> None:
        n = self.dodge_total
        self.t += 1
        t = self.t
        total = n + self.dodge_recover
        if t <= n:
            # decelerating dash: v(t) proportional to (1 - t/n); integral equals dodge_dist
            k = (1 - (t - 1) / n) * 2 / (n + 1)
            sp = self.dodge_dist * k
            self.vx = self.dodge_dir[0] * sp
            self.vy = self.dodge_dir[1] * sp
            if self.dodge_style == "vault":
                self.vault_z = math.sin(math.pi * t / n) * 11
            if self.trail_t > 0 and t % 3 == 0:
                room.add_hazard(Hazard(self.x, self.y, 8, int(self.trail_args.get("duration", 150)),
                                       dps=float(self.trail_args.get("dps", 8)), team=PLAYER_TEAM, kind="trail",
                                       apply=(("burn", 1, 1.0),), harms_all=False))
        else:
            self.vx *= 0.5
            self.vy *= 0.5
            self.vault_z = 0.0
        if self.trail_t > 0:
            self.trail_t -= 1
        b = self.buffer
        if t >= n - 3:
            if b.peek("attack"):
                b.consume("attack")
                self.finish_dodge()
                self.post_dodge = 0
                self.start_light(room, intent)
                return
            if b.peek("heavy"):
                b.consume("heavy")
                self.finish_dodge()
                self.start_charge(room, intent)
                return
        if t > n and b.peek("parry") and self.parry_cd <= 0:
            b.consume("parry")
            self.finish_dodge()
            self.start_parry(room, intent)
            return
        if t >= total:
            self.finish_dodge()

    def finish_dodge(self) -> None:
        self.state = "free"
        self.vault_z = 0.0
        self.post_dodge = 0
        self.dodge_cd = 3
        self.vx *= 0.4
        self.vy *= 0.4

    # ---------------------------------------------------------------------------- parry
    def start_parry(self, room, intent: Intent) -> None:
        p = self.weapon.parry
        self.state = "parry"
        self.t = 0
        self.parry_t = 0
        self.parry_window = max(4, int(p.get("window", 8)) + int(self.perks.get("parry_window_add"))
                                + int(room.mods["parry_window"]) + room.difficulty.parry_bonus)
        self.parry_recover = max(self.parry_window + 4, int(p.get("recover", 18) * self.perks.get("parry_recover_mul")))
        self.parry_cd = self.parry_recover + 4
        # face the nearest threat if assisted so the gesture is not wasted
        nearest = room.nearest_threat(self.x, self.y)
        if nearest is not None and intent.aim_assist and math.hypot(intent.aim[0], intent.aim[1]) < 0.3:
            self.facing = angle_to(self.x, self.y, nearest[0], nearest[1])
        room.emit("parry_start", self.x, self.y, facing=self.facing)

    @property
    def parry_active(self) -> bool:
        return self.state == "parry" and self.parry_t < self.parry_window

    def _parry(self, room, intent: Intent) -> None:
        self.t += 1
        self.parry_t += 1
        self._steer(intent, 0.25)
        if self.t >= self.parry_recover:
            self.state = "free"
            return
        if self.parry_t >= self.parry_window and self.buffer.peek("dodge") and self.dodge_cd <= 0:
            self.buffer.consume("dodge")
            self.start_dodge(room, intent)

    def parry_success(self, room, perfect: bool) -> None:
        """Called by the room when a parry connects: no recovery, riposte window opens."""
        p = self.weapon.parry
        self.state = "free"
        self.parry_cd = 0
        self.riposte_t = int(p.get("riposte_frames", 24)) + (8 if perfect else 0)
        self.iframes = max(self.iframes, 22)
        self.perfect_flash = 18 if perfect else 0
        self.combo_i = 0
        self.vx *= 0.3
        self.vy *= 0.3

    # ---------------------------------------------------------------------------- damage reactions
    def take_hit(self, ang: float, knock: float, stagger: int) -> None:
        self.add_knock(ang, knock)
        self.iframes = max(self.iframes, HURT_IFRAMES)
        self.flash = 6
        if stagger > 0 and not self.armor:
            self.state = "hurt"
            self.hurt_t = stagger
            self.move = None
            self.t = 0
            self.lunge_t = 0
            self.charge_t = 0

    def _hurt(self, room, intent: Intent) -> None:
        self.hurt_t -= 1
        self._steer(Intent(), 0.0)
        if self.hurt_t <= 0:
            self.state = "free"

    def die(self) -> None:
        self.alive = False
        self.state = "dead"
        self.dead_anim = 0
        self.vx = self.vy = 0.0

    # ---------------------------------------------------------------------------- render helpers
    def swing_angle(self) -> float | None:
        """Weapon angle for drawing during an attack (sweeps across the move's arc)."""
        mv = self.move
        if self.state != "attack" or mv is None:
            return None
        t = self.t
        half = math.radians(mv.arc if mv.shape == "arc" else 70) / 2
        s = self.swing_dir
        start = self.facing - half * s
        end = self.facing + half * s
        if mv.shape in ("thrust", "proj"):
            start = end = self.facing
        if t < mv.windup:
            k = t / max(1, mv.windup)
            return start - 0.5 * s * (1 - k) * (0 if mv.shape in ("thrust", "proj") else 1)
        a = t - mv.windup
        if a < mv.active:
            k = a / max(1, mv.active - 1)
            return start + (end - start) * k
        return end
