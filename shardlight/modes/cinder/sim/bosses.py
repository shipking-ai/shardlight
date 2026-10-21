"""Bosses: multi-phase fights built from the same hitbox / projectile / hazard primitives as everything else.

* ``slag_colossus``  (floor 3)  slams, shockwaves, molten sprays; phase 2 adds charges and falling slag.
* ``crown_of_embers`` (floor 5) spirals of embers, beams, blinks; phase 2 braziers and lances; phase 3 the floor burns.
* ``choir_warden``   (optional, unlocked through a cross-shard echo) rings of sound on a rhythm; orbiting voices.

Every attack telegraphs with the hitbox that later deals the damage.  Bosses cannot be poise-broken, but a parry still
staggers them, and every phase change grants a short breather.
"""
from __future__ import annotations

import math

from ....core.ai import Evidence
from ..defs import EnemyDef
from .brains import Brain, Enemy
from .entities import ENEMY_TEAM, Hazard, Hitbox, Projectile
from .geometry import angle_to, dist, turn_toward, unit

BOSS_NAMES = {"slag_colossus": "The Slag Colossus", "crown_of_embers": "The Crown of Embers",
              "choir_warden": "The Choir Warden", "ash_wyrm": "The Ash Wyrm"}
BOSS_HP = {"slag_colossus": 460.0, "crown_of_embers": 640.0, "choir_warden": 420.0, "ash_wyrm": 520.0}
BOSS_PHASES = {"slag_colossus": (0.55,), "crown_of_embers": (0.66, 0.28), "choir_warden": (0.66, 0.3),
               "ash_wyrm": (0.6, 0.25)}


class Boss(Enemy):
    kind = "boss"

    def __init__(self, bid: str, room, x: float, y: float) -> None:
        d = EnemyDef(id=bid, name=BOSS_NAMES[bid], ai="dummy", hp=BOSS_HP[bid], speed=0.75, radius=13.0 if bid != "choir_warden" else 11.0,
                     damage=20.0, poise=1e9, cost=0, min_floor=1, weight=0, role="boss",
                     vision={"range": 600, "fov": 360, "peripheral": 600}, reaction=10)
        hp_scale = room.mods["boss_hp"] * room.run.difficulty.enemy_hp
        super().__init__(d, x, y, room, False, hp_scale)
        self.title = BOSS_NAMES[bid]
        self.max_poise = 1e9
        self.slag = 30
        self.brain = {"slag_colossus": Colossus, "crown_of_embers": Crown, "choir_warden": Warden,
                      "ash_wyrm": AshWyrm}[bid](self, room)
        self.untargetable = True
        self.spawn_t = 0
        self.boss_id = bid


def make_boss(bid: str):
    def factory(room):
        return Boss(bid, room, 224.0, 78.0)
    return factory


class BossBrain(Brain):
    """Shared scheduler: pick an attack, run it frame by frame, rest, repeat."""

    ATTACKS: dict[int, list[tuple[str, float]]] = {}

    def __init__(self, e, room) -> None:
        super().__init__(e, room)
        self.phase = 0
        self.atk = ""
        self.last_atk = ""
        self.rest = 80
        self.pause = 0
        self.aware = True
        self.vars: dict = {}

    # perception is irrelevant: bosses always know where you are, but they still telegraph every attack
    def perceive(self, room):
        p = room.player
        self.mem.observe(Evidence("seen", (p.x, p.y), room.t / 60.0, 1.0))
        return True, (p.x, p.y)

    def update(self, room, e) -> None:
        self.t += 1
        e.anim += 0.02
        if e.stun > 0:
            e.stun -= 1
            if e.stun == 0:
                self.rest = 20
            return
        if not room.combat_started:
            return
        self.think(room, e, True, (room.player.x, room.player.y))

    def hp_frac(self) -> float:
        return self.e.hp / max(1.0, self.e.max_hp)

    def faster(self) -> float:
        return 1.0 - 0.12 * self.phase

    def think(self, room, e, sees, last) -> None:
        p = room.player
        # phase transitions
        thresholds = BOSS_PHASES[e.boss_id]
        if self.phase < len(thresholds) and self.hp_frac() <= thresholds[self.phase]:
            self.phase += 1
            self.cancel_attack()
            self.atk = ""
            self.pause = 90
            e.untargetable = True
            for h in room.hazards:
                if h.team == ENEMY_TEAM and h.kind != "fire":
                    h.life = 0
            for pr in room.projectiles:
                if pr.team == ENEMY_TEAM:
                    pr.alive = False
            room.emit("phase", e.x, e.y, phase=self.phase)
            self.on_phase(room, e)
            return
        if self.pause > 0:
            self.pause -= 1
            if self.pause == 0:
                e.untargetable = False
            return
        e.untargetable = False if self.atk != "blink" else e.untargetable
        self.turn(angle_to(e.x, e.y, p.x, p.y), 0.05)
        if not self.atk:
            self.rest -= 1
            self.drift(room, e, p)
            if self.rest <= 0:
                self.atk = self.choose(room)
                self.t = 0
                self.vars = {}
            return
        done = getattr(self, "atk_" + self.atk)(room, e, p, self.t)
        if done:
            self.last_atk = self.atk
            self.atk = ""
            self.rest = int(self.rest_time() * self.faster())

    def rest_time(self) -> int:
        return 70

    def choose(self, room) -> str:
        opts = [(n, w) for n, w in self.ATTACKS[min(self.phase, max(self.ATTACKS))] if n != self.last_atk]
        return room.rng.weighted([o[0] for o in opts], [o[1] for o in opts])

    def drift(self, room, e, p) -> None:
        d = dist(e.x, e.y, p.x, p.y)
        if d > 70:
            self.move_to(room, p.x, p.y, e.speed * 0.6)

    def on_phase(self, room, e) -> None:
        pass

    # primitives
    def hit(self, room, shape: str, x: float, y: float, facing: float, reach: float, windup: int, active: int, dmg: float,
            arc: float = 360.0, width: float = 14.0, follow: bool = False, parryable: bool = False, style: str = "heavy",
            ring_from: float = 0.0, poise: float = 40.0, knock: float = 5.0) -> Hitbox:
        hb = Hitbox(owner=self.e, team=ENEMY_TEAM, shape=shape, x=x, y=y, facing=facing, reach=reach, arc=arc, width=width,
                    damage=self.dmg(dmg), poise=poise, knock=knock, stop=7, shake=0.5, windup=int(windup * self.faster()),
                    active=active, follow=follow, parryable=parryable, ring_from=ring_from, style=style,
                    move_name=self.atk, source=self.e.boss_id)
        room.add_hitbox(hb)
        return hb

    def shot(self, room, x: float, y: float, ang: float, speed: float, dmg: float, life: int = 160, kind: str = "orb",
             parryable: bool = True, r: float = 4.0) -> None:
        room.add_projectile(Projectile(x, y, math.cos(ang) * speed, math.sin(ang) * speed, r, self.dmg(dmg), ENEMY_TEAM,
                                       self.e, life=life, kind=kind, parryable=parryable, poise=14, knock=2.5,
                                       source=self.e.boss_id, color=(255, 150, 70)))


# ================================================================================================ Slag Colossus
class Colossus(BossBrain):
    ATTACKS = {0: [("slam", 4), ("sweep", 3), ("spray", 3)],
               1: [("slam", 3), ("sweep", 2), ("spray", 2), ("charge", 3), ("rockfall", 3)]}

    def on_phase(self, room, e) -> None:
        e.speed *= 1.2
        for (vx, vy) in ((70, 60), (378, 60), (70, 190), (378, 190)):
            room.add_hazard(Hazard(vx, vy, 14, 10 ** 9, dps=12, team=ENEMY_TEAM, kind="vent", period=240, on_frames=50,
                                   warn=55, phase=int(vx + vy) % 240))

    def atk_slam(self, room, e, p, t) -> bool:
        v = self.vars
        if t == 1:
            v["ang"] = angle_to(e.x, e.y, p.x, p.y)
        if "hb" not in v and t < 6:
            self.move_to(room, p.x, p.y, e.speed * 1.4, stop=40)
        if t == 6:
            fx, fy = e.x + math.cos(v["ang"]) * 34, e.y + math.sin(v["ang"]) * 34
            v["hb"] = self.hit(room, "circle", fx, fy, v["ang"], 30, 38, 5, 24)
            v["pos"] = (fx, fy)
        if t == 6 + int(38 * self.faster()) + 4:
            fx, fy = v["pos"]
            self.hit(room, "ring", fx, fy, 0, 78, 34, 7, 14, arc=360, ring_from=18.0, poise=20, knock=3.0, style="normal")
            room.emit("quake", fx, fy)
        return t > 70

    def atk_sweep(self, room, e, p, t) -> bool:
        v = self.vars
        if t == 1:
            v["hb"] = self.hit(room, "arc", e.x, e.y, angle_to(e.x, e.y, p.x, p.y), 54, 32, 6, 20, arc=230, follow=True,
                               parryable=True)
            v["hb"].track = 22
            v["hb"].track_fn = lambda: angle_to(e.x, e.y, p.x, p.y)
        return t > 50

    def atk_spray(self, room, e, p, t) -> bool:
        if t == 1:
            room.emit("cast", e.x, e.y)
        if t in (30, 40, 50) and t:
            base = angle_to(e.x, e.y, p.x, p.y)
            for i in range(-2, 3):
                a = base + i * 0.2 + (0.05 if t == 40 else -0.05 if t == 50 else 0)
                room.add_projectile(Projectile(e.x + math.cos(a) * 14, e.y + math.sin(a) * 14, math.cos(a) * 1.9, math.sin(a) * 1.9,
                                               5.0, self.dmg(14), ENEMY_TEAM, e, life=52, kind="glob", parryable=False,
                                               poise=14, knock=3.0, source="slag", color=(255, 120, 50)))
        return t > 66

    def atk_charge(self, room, e, p, t) -> bool:
        v = self.vars
        if t == 1:
            v["ang"] = angle_to(e.x, e.y, p.x, p.y)
            v["tell"] = self.hit(room, "thrust", e.x, e.y, v["ang"], 260, 36, 1, 0.0, width=e.r * 2, style="line")
            v["tell"].track = 28
            v["tell"].track_fn = lambda: angle_to(e.x, e.y, p.x, p.y)
        if t < 36:
            v["ang"] = v["tell"].facing
            e.facing = v["ang"]
        if t == 36:
            v["body"] = self.hit(room, "circle", e.x, e.y, v["ang"], e.r + 6, 0, 40, 22, follow=True, poise=60, knock=7.0)
        if 36 <= t < 76:
            _, _, hx, hy = room.move_entity(e, math.cos(v["ang"]) * 3.6, math.sin(v["ang"]) * 3.6)
            if hx or hy:
                room.emit("crash", e.x, e.y)
                e.stun = 70
                v["body"].done = True
                return True
        return t > 90

    def atk_rockfall(self, room, e, p, t) -> bool:
        v = self.vars
        if t in (10, 34, 58):
            k = (t - 10) // 24
            tx = p.x + (p.vx * 12 if k else 0)
            ty = p.y + (p.vy * 12 if k else 0)
            tx = min(max(tx, 40), 408)
            ty = min(max(ty, 40), 200)
            self.hit(room, "circle", tx, ty, 0, 26, 42, 4, 20, style="heavy")
            room.emit("warn", tx, ty)
        return t > 108


# ================================================================================================ Crown of Embers
class Crown(BossBrain):
    ATTACKS = {0: [("spiral", 4), ("rays", 3), ("blink", 2)],
               1: [("spiral", 2), ("rays", 3), ("lances", 3), ("pulse", 3), ("blink", 1)],
               2: [("spiral", 2), ("lances", 3), ("pulse", 3), ("rays", 2), ("blink", 1)]}

    def __init__(self, e, room) -> None:
        super().__init__(e, room)
        self.collapse_t = 0

    def on_phase(self, room, e) -> None:
        if self.phase == 1:
            for k in range(2):
                room.spawn_enemy("fuse_imp", e.x + (-30 if k else 30), e.y + 30, False)
            for (bx, by) in ((100, 70), (348, 70), (100, 180), (348, 180)):
                room.add_hazard(Hazard(bx, by, 16, 10 ** 9, dps=12, team=ENEMY_TEAM, kind="vent", period=300, on_frames=60,
                                       warn=60, phase=(bx * 3 + by) % 300))
        if self.phase == 2:
            self.collapse_t = 1
            room.emit("collapse", e.x, e.y)

    def rest_time(self) -> int:
        return 60 if self.phase == 0 else 48

    def drift(self, room, e, p) -> None:
        d = dist(e.x, e.y, p.x, p.y)
        if d < 70:
            ax, ay = unit(e.x - p.x, e.y - p.y)
            room.move_entity(e, ax * 0.9, ay * 0.9)
        elif d > 150:
            self.move_to(room, p.x, p.y, e.speed * 0.6)

    def update(self, room, e) -> None:
        super().update(room, e)
        if self.collapse_t and room.combat_started:
            self.collapse_t += 1
            ring = (self.collapse_t // 420)
            if self.collapse_t % 420 == 1 and ring < 4:
                # the arena burns inward from the edges, one band at a time (each band is telegraphed 70 frames)
                inset = ring * 40
                for x in range(16 + inset, 448 - inset, 24):
                    for (y) in (36 + inset, 236 - inset - 24):
                        room.add_hazard(Hazard(x, y + 8, 14, 10 ** 9, dps=12, team=ENEMY_TEAM, kind="fire", warmup=70))
                for y in range(36 + inset, 236 - inset, 24):
                    for x in (16 + inset, 448 - inset - 16):
                        room.add_hazard(Hazard(x + 8, y + 8, 14, 10 ** 9, dps=12, team=ENEMY_TEAM, kind="fire", warmup=70))

    def atk_spiral(self, room, e, p, t) -> bool:
        arms = 3
        if t == 1:
            room.emit("cast", e.x, e.y)
        if 24 <= t <= 24 + 70 and t % 5 == 0:
            base = (t - 24) * 0.075 * (1 if self.phase != 1 else -1)
            for a in range(arms):
                ang = base + a * math.tau / arms
                self.shot(room, e.x, e.y, ang, 1.7, 9, 170)
        return t > 120

    def atk_rays(self, room, e, p, t) -> bool:
        v = self.vars
        if t == 1:
            base = angle_to(e.x, e.y, p.x, p.y)
            n = 3 if self.phase < 2 else 5
            v["beams"] = [self.hit(room, "thrust", e.x, e.y, base + (i - (n - 1) / 2) * 0.55, 330, 54, 4, 20, width=7, style="line")
                          for i in range(n)]
        return t > 88

    def atk_blink(self, room, e, p, t) -> bool:
        if t == 1:
            e.untargetable = True
            room.emit("blink_out", e.x, e.y)
        if t == 16:
            cells = room.free_cells(70.0)
            if cells:
                far = max(cells, key=lambda c: dist(c[0], c[1], p.x, p.y) * (0.6 + room.rng.random() * 0.4))
                e.x, e.y = far
            room.emit("blink_in", e.x, e.y)
        if t == 28:
            e.untargetable = False
            for i in range(8):
                self.shot(room, e.x, e.y, i * math.tau / 8, 1.8, 8, 120)
        return t > 40

    def atk_lances(self, room, e, p, t) -> bool:
        v = self.vars
        for k, tt in enumerate((1, 30, 59)):
            if t == tt:
                ang = angle_to(e.x, e.y, p.x, p.y)
                self.hit(room, "thrust", e.x, e.y, ang, 340, 38, 4, 22, width=9, style="line", follow=False)
                v["last"] = ang
        return t > 105

    def atk_pulse(self, room, e, p, t) -> bool:
        if t == 1:
            self.hit(room, "ring", e.x, e.y, 0, 190, 40, 36, 16, ring_from=10, poise=20, knock=3.0, style="normal")
        if t in (1, 40):
            gap = angle_to(e.x, e.y, p.x, p.y)
            for i in range(20):
                a = i * math.tau / 20
                if abs(((a - gap + math.pi) % math.tau) - math.pi) < 0.35:
                    continue
                self.shot(room, e.x, e.y, a, 1.4, 8, 190)
        return t > 96


class AshWyrm(Crown):
    ATTACKS = {0: [("spiral", 3), ("blink", 2), ("pulse", 2)],
               1: [("spiral", 2), ("pulse", 3), ("rays", 2), ("blink", 1)],
               2: [("pulse", 3), ("rays", 3), ("spiral", 2), ("blink", 1)]}

    def on_phase(self, room, e) -> None:
        if self.phase == 1:
            for (bx, by) in ((120, 90), (328, 90), (120, 160), (328, 160)):
                room.add_hazard(Hazard(bx, by, 18, 10 ** 9, dps=10, team=ENEMY_TEAM, kind="vent", period=260, on_frames=50,
                                       warn=50, phase=(bx + by) % 260))
        if self.phase == 2:
            self.collapse_t = 1
            room.emit("collapse", e.x, e.y)


# ================================================================================================ Choir Warden
class Warden(BossBrain):
    BEAT = 42

    ATTACKS = {0: [("verse", 4), ("chord", 3)], 1: [("verse", 2), ("chord", 3), ("voices", 4)],
               2: [("chord", 3), ("voices", 3), ("discord", 4)]}

    def __init__(self, e, room) -> None:
        super().__init__(e, room)
        self.orbs: list[list[float]] = []

    def rest_time(self) -> int:
        return 60 if self.phase == 0 else 44

    def drift(self, room, e, p) -> None:
        # the Warden glides in a slow circle around the arena centre
        a = room.t * 0.01
        cx, cy = 224 + math.cos(a) * 66, 110 + math.sin(a) * 36
        self.move_to(room, cx, cy, e.speed * 0.7, stop=4)

    def on_phase(self, room, e) -> None:
        if self.phase == 1:
            self.orbs = [[k * math.tau / 3, 34.0] for k in range(3)]

    def update(self, room, e) -> None:
        super().update(room, e)
        # voice orbs circle the Warden and sing needles on the beat
        if self.orbs and room.combat_started and e.alive:
            for o in self.orbs:
                o[0] += 0.03
            if room.t % self.BEAT == 0 and not self.pause:
                p = room.player
                for o in self.orbs:
                    ox, oy = e.x + math.cos(o[0]) * o[1], e.y + math.sin(o[0]) * o[1]
                    self.shot(room, ox, oy, angle_to(ox, oy, p.x, p.y), 1.9, 7, 140, "needle", True, 3.0)

    def atk_verse(self, room, e, p, t) -> bool:
        """Rings on the beat: one expanding ring per beat, each with a quiet lane to roll through."""
        if t in (self.BEAT // 2, self.BEAT // 2 + self.BEAT, self.BEAT // 2 + 2 * self.BEAT):
            self.hit(room, "ring", e.x, e.y, 0, 150, 34, 30, 14, ring_from=8, poise=20, knock=3.0, style="normal")
            room.emit("note", e.x, e.y)
        return t > self.BEAT * 3 + 20

    def atk_chord(self, room, e, p, t) -> bool:
        """Three arcs fan out from the Warden; the gaps between them are safe."""
        v = self.vars
        if t == 1:
            v["base"] = angle_to(e.x, e.y, p.x, p.y)
        if t == 8:
            for k in range(3):
                a = v["base"] + math.tau * k / 3 + math.pi / 3
                self.hit(room, "arc", e.x, e.y, a, 230, 40, 8, 17, arc=70, style="normal", follow=False, poise=18, knock=3.0)
        return t > 70

    def atk_voices(self, room, e, p, t) -> bool:
        if t in (10, 10 + self.BEAT, 10 + 2 * self.BEAT):
            for i in range(10):
                a = i * math.tau / 10 + t * 0.01
                self.shot(room, e.x, e.y, a, 1.5, 7, 170, "note")
        return t > self.BEAT * 3 + 10

    def atk_discord(self, room, e, p, t) -> bool:
        """Two offset ring waves a half-beat apart: the timing is the puzzle."""
        if t in (10, 10 + self.BEAT // 2, 10 + self.BEAT, 10 + self.BEAT + self.BEAT // 2):
            self.hit(room, "ring", e.x, e.y, 0, 190, 30, 28, 14, ring_from=8, poise=20, knock=3.0, style="normal")
            room.emit("note", e.x, e.y)
        if t == 20:
            self.hit(room, "arc", e.x, e.y, angle_to(e.x, e.y, p.x, p.y), 260, 44, 6, 16, arc=48, style="line")
        return t > self.BEAT * 2 + 40
