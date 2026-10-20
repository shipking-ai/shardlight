"""Enemy bodies and brains.  Each enemy kind has its own decision logic built on the shared perception/memory kit.

Fairness rules (also asserted by tests): enemies act on what they *perceived* (vision cone + line of sight, or an
ally alert, or being hurt), wait out an explicit reaction time before their first action, telegraph every attack with
the same ``Hitbox`` that later deals the damage, and adaptation only nudges aim, spacing and timing within the bounds
defined in ``adaptive.py`` - never damage.
"""
from __future__ import annotations

import math

from ....core.ai import Evidence, Memory, VisionCone
from ..defs import EnemyDef
from .entities import ENEMY_TEAM, PLAYER_TEAM, Entity, Hazard, Hitbox, Projectile
from .geometry import angle_diff, angle_to, dist, segment_blocked, turn_toward, unit

ELITE_TRAITS = ("frenzied", "armored", "volatile", "twin", "volley", "chorus")


class Enemy(Entity):
    kind = "enemy"

    def __init__(self, edef: EnemyDef, x: float, y: float, room, elite: bool = False, hp_scale: float = 1.0) -> None:
        d = edef
        hp = d.hp * hp_scale
        self.elite = elite and d.elite is not None
        params = dict(d.params)
        self.trait = ""
        self.title = d.name
        if self.elite:
            hp *= d.elite.get("hp_mul", 1.5)
            params.update(d.elite.get("params", {}))
            self.trait = d.elite["trait"]
            self.title = d.elite["name"]
        super().__init__(x, y, d.radius * (1.12 if self.elite else 1.0), hp, ENEMY_TEAM)
        self.edef = d
        self.params = params
        self.max_poise = d.poise * (2.2 if self.trait == "armored" else 1.0)
        self.speed = d.speed * room.run.mods["enemy_speed"] * (1.25 if self.trait == "frenzied" else 1.0)
        self.dmg_mul = room.run.mods["enemy_damage"] * room.run.difficulty.enemy_damage * (1 + 0.08 * (room.floor - 1))
        self.spawn_t = 40
        self.untargetable = True
        self.guard_front = False
        self.guard_arc = 0.0
        self.guard_cut = 0.0
        self.brain: Brain = BRAINS[d.ai](self, room)
        self.slag = max(1, int(d.cost * (2.0 if self.elite else 1.0)))
        self.owner_id = 0               # summoner id for minions
        self.last_source = ""
        self.last_tags: tuple = ()
        self.telegraph_style = "normal"
        self.anim = 0.0

    @property
    def name(self) -> str:
        return self.title


class Brain:
    uses_slot = False
    slot_role = "any"

    def __init__(self, e: Enemy, room) -> None:
        self.e = e
        self.room = room
        d = e.edef
        self.cone = VisionCone(range=d.vision["range"], fov_deg=d.vision["fov"], peripheral_range=d.vision["peripheral"])
        self.mem = Memory(decay_per_s=0.12)
        self.aware = False
        self.react = 0
        self.state = "idle"
        self.t = 0
        self.cd = room.rng.randint(15, 70)
        self.token = False
        self.path: list = []
        self.path_t = 0
        self.attack_hb: Hitbox | None = None
        self.noticed = False
        self.facing_target = e.facing
        self.guarding = False

    # -- helpers -------------------------------------------------------------------------------------
    @property
    def reaction_frames(self) -> int:
        r = self.e.edef.reaction + self.room.run.difficulty.reaction_add - int(self.room.run.mods["reaction_cut"])
        return max(4, r)

    def hear_ally(self, pos) -> None:
        if not self.aware:
            self.become_aware(pos)

    def become_aware(self, pos) -> None:
        self.aware = True
        self.react = self.reaction_frames
        self.mem.observe(Evidence("seen", pos, self.room.t / 60.0, 1.0))
        self.room.emit("notice", self.e.x, self.e.y)

    def perceive(self, room) -> tuple[bool, tuple[float, float] | None]:
        e, p = self.e, room.player
        los = not segment_blocked(room.proj_solid, e.x, e.y, p.x, p.y)
        facing = math.degrees(e.facing)
        vis = 0.55 if room.run.mods["dim_light"] > 0 else 1.0
        sees = self.cone.sees((e.x, e.y), facing, (p.x, p.y), lambda a, b: los, vis) and p.alive
        if sees:
            self.mem.observe(Evidence("seen", (p.x, p.y), room.t / 60.0, 1.0))
            if not self.aware:
                self.become_aware((p.x, p.y))
                room.squad.alert(e, (p.x, p.y))
        elif not self.aware and e.hp < e.max_hp:
            self.become_aware((p.x, p.y))
        self.mem.update(1 / 60)
        return sees, self.mem.last_known()

    def turn(self, ang: float, rate: float = 0.12) -> None:
        self.e.facing = turn_toward(self.e.facing, ang, rate)

    def move_to(self, room, tx: float, ty: float, speed: float, stop: float = 0.0) -> bool:
        """Walk toward a point (path-following around walls). Returns True when within ``stop``."""
        e = self.e
        d = dist(e.x, e.y, tx, ty)
        if d <= stop:
            return True
        sx, sy = tx, ty
        if segment_blocked(room.proj_solid, e.x, e.y, tx, ty):
            self.path_t -= 1
            if self.path_t <= 0 or not self.path:
                self.path = room.find_path(e.x, e.y, tx, ty)
                self.path_t = 18
            while self.path and dist(e.x, e.y, self.path[0][0], self.path[0][1]) < 6:
                self.path.pop(0)
            if self.path:
                sx, sy = self.path[0]
        ux, uy = unit(sx - e.x, sy - e.y)
        sep = room.separation(e)
        vx = (ux + sep[0] * 0.7) * speed * e.status.slow_mult()
        vy = (uy + sep[1] * 0.7) * speed * e.status.slow_mult()
        room.move_entity(e, vx, vy)
        e.anim += math.hypot(vx, vy) * 0.12
        return False

    def start_attack_hb(self, hb: Hitbox) -> Hitbox:
        self.attack_hb = hb
        self.room.add_hitbox(hb)
        return hb

    def cancel_attack(self) -> None:
        if self.attack_hb is not None:
            self.attack_hb.done = True
            self.attack_hb = None
        if self.token:
            self.room.squad.release(self.e)
            self.token = False

    def dmg(self, base: float) -> float:
        return base * self.e.dmg_mul

    def on_parried(self) -> None:
        self.cancel_attack()
        self.e.stun = max(self.e.stun, 52)
        self.state = "stunned"
        self.t = 0

    def on_stagger(self) -> None:
        self.cancel_attack()
        self.state = "stunned"
        self.t = 0

    # -- main ----------------------------------------------------------------------------------------
    def update(self, room, e: Enemy) -> None:
        self.t += 1
        e.anim += 0.02
        if self.cd > 0:
            self.cd -= 1
        if e.stun > 0:
            e.stun -= 1
            if e.stun == 0 and self.state == "stunned":
                self.state = "idle"
            return
        sees, last = self.perceive(room)
        if not self.aware:
            return
        if self.react > 0:
            self.react -= 1
            if last:
                self.turn(angle_to(e.x, e.y, last[0], last[1]), 0.2)
            return
        self.think(room, e, sees, last)

    def think(self, room, e: Enemy, sees: bool, last) -> None:
        raise NotImplementedError


# ================================================================================================ swarmer
class Swarmer(Brain):
    uses_slot = True
    slot_role = "any"

    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        tgt = (p.x, p.y) if sees else last
        if tgt is None:
            return
        d = dist(e.x, e.y, p.x, p.y)
        if self.state in ("idle", "approach"):
            self.state = "approach"
            sx, sy = room.squad.slot_pos(e, (p.x, p.y), prm.get("ring", 26) + 6)
            want_attack = d < prm["reach"] + e.r + 14 and self.cd <= 0 and sees
            if want_attack and room.squad.request(e):
                self.token = True
                self.state = "windup"
                self.t = 0
                feint = room.adapt.feint(room.rng)
                ang = angle_to(e.x, e.y, p.x, p.y) + room.adapt.lead_angle(room.lateral_sign(e, p))
                e.facing = ang
                hb = Hitbox(owner=e, team=ENEMY_TEAM, shape="arc", x=e.x, y=e.y, facing=ang, reach=prm["reach"],
                            arc=prm["arc"], damage=self.dmg(e.edef.damage), poise=20, knock=3.0, stop=4, shake=0.15,
                            windup=prm["windup"] + feint, active=prm["active"], follow=True,
                            track=max(0, prm["windup"] - 5), track_fn=lambda: angle_to(e.x, e.y, p.x, p.y),
                            move_name="claw", source=e.edef.id)
                self.start_attack_hb(hb)
                return
            if not sees and d > 20:
                self.move_to(room, tgt[0], tgt[1], e.speed * 0.9)
            elif d > prm.get("ring", 26) + 30:
                self.move_to(room, p.x, p.y, e.speed)
                self.turn(angle_to(e.x, e.y, p.x, p.y))
            else:
                self.move_to(room, sx, sy, e.speed * 0.8)
                self.turn(angle_to(e.x, e.y, p.x, p.y))
        elif self.state == "windup":
            hb = self.attack_hb
            if hb is None or hb.done:
                self.state = "recover"
                self.t = 0
            elif hb.t == hb.windup:
                e.add_knock(hb.facing, prm["lunge"] * 2.2)
            elif hb.t > hb.windup + hb.active:
                self.state = "recover"
                self.t = 0
        elif self.state == "recover":
            if self.t >= prm["recover"]:
                self.cancel_attack()
                self.cd = int(prm["cooldown"] * room.adapt.quicken() * (0.6 if e.trait == "frenzied" else 1.0))
                self.state = "approach"
        elif self.state == "stunned":
            pass


# ================================================================================================ kiter
class Kiter(Brain):
    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        d = dist(e.x, e.y, p.x, p.y)
        spacing = room.adapt.spacing()
        want_min = prm["min_range"] + spacing * 0.5
        want_max = prm["range"] + spacing
        if self.state in ("idle", "approach"):
            self.state = "approach"
            if not sees:
                if last:
                    self.move_to(room, last[0], last[1], e.speed)
                return
            self.turn(angle_to(e.x, e.y, p.x, p.y), 0.14)
            if d < want_min:
                ax, ay = unit(e.x - p.x, e.y - p.y)
                room.move_entity(e, ax * prm["retreat_speed"], ay * prm["retreat_speed"])
                # cornered: strafe instead of freezing against the wall
                if segment_blocked(room.proj_solid, e.x, e.y, e.x + ax * 14, e.y + ay * 14):
                    room.move_entity(e, -ay * e.speed, ax * e.speed)
            elif d > want_max:
                self.move_to(room, p.x, p.y, e.speed)
            else:
                room.move_entity(e, -math.sin(e.facing) * e.speed * 0.4, math.cos(e.facing) * e.speed * 0.4)
            if self.cd <= 0 and want_min * 0.8 < d < want_max + 40:
                self.state = "aim"
                self.t = 0
                self.cd = 0
        elif self.state == "aim":
            self.turn(angle_to(e.x, e.y, p.x, p.y), 0.2)
            if self.t == 1:
                room.emit("aim", e.x, e.y, ang=e.facing)
            if self.t >= prm["windup"]:
                self._fire(room, e, p)
                self.state = "recover"
                self.t = 0
        elif self.state == "recover":
            if self.t >= prm["recover"]:
                self.cd = int(prm["cooldown"] * room.adapt.quicken() * (0.7 if e.trait == "frenzied" else 1.0))
                self.state = "approach"

    def _fire(self, room, e, p) -> None:
        prm = e.params
        speed = prm["proj_speed"]
        d = dist(e.x, e.y, p.x, p.y)
        t = d / speed
        # honest prediction: aim ahead of the player's current velocity, only 55% of the way
        lead_x = p.x + p.vx * t * 0.55
        lead_y = p.y + p.vy * t * 0.55
        base = angle_to(e.x, e.y, lead_x, lead_y) + room.adapt.lead_angle(room.lateral_sign(e, p))
        fan = int(prm.get("fan", 1))
        for i in range(fan):
            a = base + (i - (fan - 1) / 2) * 0.22
            room.add_projectile(Projectile(e.x + math.cos(a) * 7, e.y + math.sin(a) * 7, math.cos(a) * speed,
                                           math.sin(a) * speed, 3.0, self.dmg(prm["damage"]), ENEMY_TEAM, e, life=140,
                                           kind="arrow", parryable=True, poise=12, knock=2.2, source=e.edef.id,
                                           color=(255, 200, 110)))
        room.emit("shoot", e.x, e.y, ang=base)


# ================================================================================================ shield
class Shield(Brain):
    uses_slot = True
    slot_role = "tank"

    def __init__(self, e, room):
        super().__init__(e, room)
        e.guard_front = True
        e.guard_arc = math.radians(e.params["shield_arc"])
        e.guard_cut = e.params["shield_cut"]

    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        d = dist(e.x, e.y, p.x, p.y)
        if self.state in ("idle", "approach"):
            self.state = "approach"
            e.guard_front = True
            tgt = (p.x, p.y) if sees else last
            if tgt:
                self.turn(angle_to(e.x, e.y, tgt[0], tgt[1]), prm["turn"])
                if d > prm["reach"] + e.r:
                    self.move_to(room, tgt[0], tgt[1], e.speed, 0)
            if sees and d < prm["reach"] + e.r + 8 and self.cd <= 0 and room.squad.request(e):
                self.token = True
                self.state = "windup"
                self.t = 0
                hb = Hitbox(owner=e, team=ENEMY_TEAM, shape="arc", x=e.x, y=e.y, facing=e.facing, reach=prm["reach"],
                            arc=prm["arc"], damage=self.dmg(e.edef.damage), poise=40, knock=4.5, stop=6, shake=0.3,
                            windup=prm["windup"] + room.adapt.feint(room.rng), active=prm["active"], follow=True,
                            track=max(0, prm["windup"] - 8), track_fn=lambda: angle_to(e.x, e.y, p.x, p.y),
                            move_name="bash", source=e.edef.id, style="heavy")
                self.start_attack_hb(hb)
        elif self.state == "windup":
            e.guard_front = False if self.t > 6 else True       # the shield drops while winding up: a window
            hb = self.attack_hb
            if hb is None or hb.done or hb.t > hb.windup + hb.active:
                self.state = "recover"
                self.t = 0
        elif self.state == "recover":
            e.guard_front = False
            if self.t >= prm["recover"]:
                self.cancel_attack()
                self.cd = int(prm["cooldown"] * room.adapt.quicken())
                self.state = "approach"
        elif self.state == "stunned":
            e.guard_front = False

    def on_stagger(self) -> None:
        super().on_stagger()
        self.e.guard_front = False


# ================================================================================================ bomber
class Bomber(Brain):
    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        d = dist(e.x, e.y, p.x, p.y)
        if self.state in ("idle", "approach"):
            self.state = "approach"
            tgt = (p.x, p.y) if sees else last
            if tgt:
                self.move_to(room, tgt[0], tgt[1], e.speed)
                self.turn(angle_to(e.x, e.y, tgt[0], tgt[1]), 0.25)
            if sees and d < prm["trigger"] + e.r:
                self.state = "fuse"
                self.t = 0
                hb = Hitbox(owner=e, team=ENEMY_TEAM, shape="ring", x=e.x, y=e.y, facing=0.0, reach=prm["blast"],
                            arc=360, damage=self.dmg(e.edef.damage), poise=40, knock=5.0, stop=7, shake=0.5,
                            windup=prm["fuse"], active=7, follow=True, ring_from=4.0, parryable=False,
                            move_name="blast", source=e.edef.id, style="heavy")
                self.start_attack_hb(hb)
                room.emit("fuse", e.x, e.y)
        elif self.state == "fuse":
            self.move_to(room, p.x, p.y, e.speed * 0.25)
            hb = self.attack_hb
            if hb is not None and hb.t == hb.windup:
                room.emit("explode", e.x, e.y, radius=prm["blast"])
            if hb is None or hb.done or (hb.t > hb.windup + 1):
                e.hp = 0.0
                e.alive = False
                room.on_enemy_removed(e, killed=False)


# ================================================================================================ charger
class Charger(Brain):
    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        d = dist(e.x, e.y, p.x, p.y)
        if self.state in ("idle", "approach"):
            self.state = "approach"
            tgt = (p.x, p.y) if sees else last
            if tgt:
                self.turn(angle_to(e.x, e.y, tgt[0], tgt[1]), 0.1)
                if d > 60:
                    self.move_to(room, tgt[0], tgt[1], e.speed)
                else:
                    ax, ay = unit(e.x - p.x, e.y - p.y)
                    room.move_entity(e, ax * e.speed * 0.6, ay * e.speed * 0.6)
            clear = sees and not segment_blocked(room.proj_solid, e.x, e.y, p.x, p.y)
            if clear and self.cd <= 0 and 50 < d < prm["charge_range"]:
                self.state = "tell"
                self.t = 0
                ang = angle_to(e.x, e.y, p.x, p.y) + room.adapt.lead_angle(room.lateral_sign(e, p))
                e.facing = ang
                self.dir = ang
                hb = Hitbox(owner=e, team=ENEMY_TEAM, shape="thrust", x=e.x, y=e.y, facing=ang, reach=prm["charge_range"] + 40,
                            width=e.r * 2, damage=0.0, windup=prm["tell"], active=1, follow=False, parryable=False,
                            move_name="telegraph", source=e.edef.id, style="line", track=max(0, prm["tell"] - 8),
                            track_fn=lambda: angle_to(e.x, e.y, p.x, p.y) + room.adapt.lead_angle(room.lateral_sign(e, p)))
                self.start_attack_hb(hb)
        elif self.state == "tell":
            if self.attack_hb is not None:
                self.dir = self.attack_hb.facing
                e.facing = self.dir
            if self.t >= prm["tell"]:
                self.state = "charge"
                self.t = 0
                self.cancel_attack()
                body = Hitbox(owner=e, team=ENEMY_TEAM, shape="circle", x=e.x, y=e.y, facing=self.dir, reach=e.r + 5,
                              damage=self.dmg(e.edef.damage), poise=60, knock=6.0, stop=7, shake=0.45, windup=0,
                              active=prm["charge_time"], follow=True, parryable=False, move_name="ram", source=e.edef.id)
                self.start_attack_hb(body)
                room.emit("charge", e.x, e.y)
        elif self.state == "charge":
            vx, vy = math.cos(self.dir) * prm["charge_speed"], math.sin(self.dir) * prm["charge_speed"]
            _, _, hx, hy = room.move_entity(e, vx, vy)
            if hx or hy:
                room.emit("crash", e.x, e.y)
                e.stun = prm["stun"]
                e.poise = 0
                self.cancel_attack()
                self.state = "stunned"
                self.t = 0
                self.cd = prm["cooldown"]
            elif self.t >= prm["charge_time"]:
                self.cancel_attack()
                self.state = "recover"
                self.t = 0
        elif self.state == "recover":
            if self.t >= 30:
                self.cd = int(prm["cooldown"] * room.adapt.quicken())
                self.state = "approach"

    dir = 0.0


# ================================================================================================ summoner
class Summoner(Brain):
    def __init__(self, e, room):
        super().__init__(e, room)
        self.minions: list[Enemy] = []

    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        d = dist(e.x, e.y, p.x, p.y)
        self.minions = [m for m in self.minions if m.alive]
        if self.state in ("idle", "approach"):
            self.state = "approach"
            if sees or last:
                tx, ty = (p.x, p.y) if sees else last
                self.turn(angle_to(e.x, e.y, tx, ty), 0.1)
            if d < prm["keep_distance"] - 20:
                ax, ay = unit(e.x - p.x, e.y - p.y)
                room.move_entity(e, ax * e.speed, ay * e.speed)
            elif d > prm["keep_distance"] + 80 and sees:
                self.move_to(room, p.x, p.y, e.speed * 0.8)
            if sees and self.cd <= 0 and len(self.minions) < prm["max_minions"]:
                self.state = "cast"
                self.t = 0
                room.emit("cast", e.x, e.y)
        elif self.state == "cast":
            if self.t >= prm["cast"]:
                n = min(2 if e.trait != "chorus" else 3, prm["max_minions"] - len(self.minions))
                for i in range(n):
                    a = e.facing + math.pi * (i + 0.5) / max(1, n) * 2 - math.pi / 2
                    sx, sy = e.x + math.cos(a) * 22, e.y + math.sin(a) * 22
                    m = room.spawn_enemy(prm["summon"], sx, sy, elite=False)
                    if m:
                        m.owner_id = e.id
                        m.spawn_t = 28
                        self.minions.append(m)
                self.cd = int(prm["cooldown"] * room.adapt.quicken())
                self.state = "approach"


# ================================================================================================ sniper
class Sniper(Brain):
    def think(self, room, e, sees, last):
        p = room.player
        prm = e.params
        d = dist(e.x, e.y, p.x, p.y)
        if self.state in ("idle", "approach"):
            self.state = "approach"
            if sees:
                self.turn(angle_to(e.x, e.y, p.x, p.y), 0.12)
            if sees and d < prm["range"] and self.cd <= 0:
                self.state = "aim"
                self.t = 0
                hb = Hitbox(owner=e, team=ENEMY_TEAM, shape="thrust", x=e.x, y=e.y, facing=e.facing, reach=prm["range"],
                            width=5, damage=self.dmg(prm["damage"]), poise=25, knock=4.0, stop=5, shake=0.3,
                            windup=prm["aim"], active=3, follow=False, parryable=False, move_name="beam", source=e.edef.id,
                            style="line", track=max(0, prm["aim"] - 14),
                            track_fn=lambda: angle_to(e.x, e.y, p.x, p.y) + room.adapt.lead_angle(room.lateral_sign(e, p)) * 0.6)
                self.start_attack_hb(hb)
        elif self.state == "aim":
            hb = self.attack_hb
            if hb is not None and not hb.done:
                e.facing = hb.facing
            if hb is None or hb.done or hb.t > hb.windup + hb.active:
                self.cancel_attack()
                self.cd = int(prm["cooldown"] * room.adapt.quicken() * (0.7 if e.trait == "frenzied" else 1))
                self.state = "approach"
                room.emit("shoot", e.x, e.y, ang=e.facing)


BRAINS: dict[str, type[Brain]] = {"swarmer": Swarmer, "kiter": Kiter, "shield": Shield, "bomber": Bomber,
                                  "charger": Charger, "summoner": Summoner, "sniper": Sniper, "dummy": Brain}
