"""Creatures, hazards and projectiles for Hollowmere.

Enemy behaviour is deliberately readable: every attack has a visible wind-up (the sprite flashes, bosses draw
telegraph circles), enemies only react to what they have seen or heard, and adaptation is a bounded, *visible*
change (a shield on a few bandits when you rely on melee, archers that close the distance when you rely on the
bow) - never a hidden damage multiplier.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import count

from .phys import fits, move

_uid = count(1)
SIGHT_LOSS = 6.0


@dataclass
class Hazard:
    kind: str                # circle | ring
    x: float
    y: float
    r: float
    t: float                 # circle: seconds until it lands; ring: elapsed
    dur: float
    dmg: float
    owner: int = 0
    hit: bool = False
    linger: float = 0.25
    area: str = ""


@dataclass
class Projectile:
    x: float
    y: float
    vx: float
    vy: float
    dmg: float
    friendly: bool
    life: float = 1.6
    kind: str = "arrow"
    area: str = ""
    r: float = 0.35


class Enemy:
    def __init__(self, game, kind: str, x: float, y: float, zone: str = "", idx: int = 0, n: int = 1):
        self.uid = next(_uid)
        self.kind = kind
        self.d = game.cat.enemy(kind)
        self.x, self.y = x, y
        self.hp = self.maxhp = float(self.d["hp"])
        self.zone = zone
        self.idx, self.n = idx, n
        self.st = "idle"
        self.t = 0.0
        self.facing = game.rng.random() * 360
        self.dead = False
        self.home = (x, y)
        self.cd = game.rng.random() * 1.0
        self.stun = 0.0
        self.kx = self.ky = 0.0
        self.knock_t = 0.0
        self.path: list[tuple[float, float]] | None = None
        self.path_t = 0.0
        self.aggro = 0.0
        self.los_t = 0.0
        self.sees = False
        self.flash = 0.0
        self.hurt_total = 0.0
        self.aux: dict = {}
        self.r = 0.3 * float(self.d.get("size", 1.0))
        self.guard = False
        self.summoned = False
        self.wander_t = 0.0
        self.wander_to: tuple[float, float] | None = None
        self.dash = (0.0, 0.0, 0.0)
        self.windup_total = 0.4
        if self.d["ai"] == "melee" and kind == "bandit":
            lvl = game.adapt.level("guard")
            self.guard = game.rng.random() < lvl
        self.walk_phase = 0.0
        self.alpha = 1.0

    @property
    def speed(self) -> float:
        return float(self.d.get("speed", 2.5))


# --------------------------------------------------------------------------------------------- helpers
def lamp_light(game, x: float, y: float, radius: float = 6.5) -> bool:
    if game.area != "overworld":
        return False
    r2 = radius * radius
    for (lx, ly) in game.lit:
        if (lx + 0.5 - x) ** 2 + (ly + 0.5 - y) ** 2 <= r2:
            return True
    return False


def _walk(game, e: Enemy, dx: float, dy: float) -> bool:
    wm = game.wm
    e.x, e.y, blocked = move(game.walkb(), wm.W, wm.H, e.x, e.y, dx, dy, e.r)
    return blocked


def _speed_here(game, e: Enemy) -> float:
    return game.wm.speed_at(int(e.x), int(e.y)) or 1.0


def _steer(game, e: Enemy, tx: float, ty: float, sp: float, dt: float) -> None:
    """Move toward a point; fall back to a cached A* path when the straight line is blocked."""
    wm = game.wm
    dist = math.hypot(tx - e.x, ty - e.y)
    if dist < 0.05:
        return
    direct = game.los((e.x, e.y), (tx, ty)) or dist < 1.2
    if direct:
        e.path = None
        dx, dy = (tx - e.x) / dist, (ty - e.y) / dist
    else:
        e.path_t -= dt
        if e.path is None or e.path_t <= 0:
            e.path = game.path(game.area, (e.x, e.y), (tx, ty), 900)
            e.path_t = 0.8
        if not e.path:
            return
        while e.path and math.hypot(e.path[0][0] - e.x, e.path[0][1] - e.y) < 0.45:
            e.path.pop(0)
        if not e.path:
            return
        wx, wy = e.path[0]
        d2 = math.hypot(wx - e.x, wy - e.y) or 1.0
        dx, dy = (wx - e.x) / d2, (wy - e.y) / d2
    step = sp * _speed_here(game, e) * dt
    blocked = _walk(game, e, dx * step, dy * step)
    if blocked and direct:
        # slide around a corner: try the two perpendicular directions
        _walk(game, e, -dy * step * 0.7, dx * step * 0.7)
    e.facing = math.degrees(math.atan2(dy, dx))
    e.walk_phase += dt * 8


def _face(e: Enemy, tx: float, ty: float) -> None:
    e.facing = math.degrees(math.atan2(ty - e.y, tx - e.x))


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


# --------------------------------------------------------------------------------------------- player attacks
def player_melee(game) -> None:
    P = game.p
    w = game.weapon()
    reach = float(w.get("reach", 1.4))
    base = float(w.get("dmg", 3)) * (1.0 + 0.05 * game.skill("blade"))
    hits = 0
    for e in game.enemies:
        if e.dead:
            continue
        d = math.hypot(e.x - P.x, e.y - P.y)
        if d > reach + e.r + 0.15:
            continue
        ang = math.degrees(math.atan2(e.y - P.y, e.x - P.x))
        if _angle_diff(ang, P.facing) > 72 and d > 0.7:
            continue
        dmg = base * game.rng.uniform(0.9, 1.12)
        damage_enemy(game, e, dmg, math.cos(math.radians(ang)), math.sin(math.radians(ang)), "melee")
        hits += 1
        if hits >= 3:
            break
    if hits:
        game.fx_add("hitstop", P.x, P.y, frames=3 + 2 * min(2, hits), life=0.01)
    game.model.record("melee", game.t)
    game.alert_noise(P.x, P.y, 7.0)


def player_shoot(game) -> None:
    P = game.p
    bow = game.bow()
    if not bow or game.count("arrow") <= 0:
        if bow:
            game.toast("No arrows.")
            P.shoot_cd = 0.5
        return
    game.take("arrow", 1)
    ang = P.facing
    best = None
    for e in game.enemies:
        if e.dead:
            continue
        a = math.degrees(math.atan2(e.y - P.y, e.x - P.x))
        dd = _angle_diff(a, ang)
        d = math.hypot(e.x - P.x, e.y - P.y)
        if dd < 22 and d < float(bow.get("reach", 10)) + 2 and (best is None or dd < best[0]):
            best = (dd, a)
    if best:
        ang = best[1]
    dmg = float(bow.get("dmg", 5)) * (1.0 + 0.05 * game.skill("bow"))
    sp = 15.0
    game.projectiles.append(Projectile(P.x, P.y, math.cos(math.radians(ang)) * sp, math.sin(math.radians(ang)) * sp, dmg, True,
                                       life=float(bow.get("reach", 10)) / sp + 0.15, kind="arrow", area=game.area))
    P.shoot_cd = float(bow.get("swing", 0.5))
    P.facing = ang
    game.sfx("verdant_bow")
    game.model.record("ranged", game.t)
    game.alert_noise(P.x, P.y, 5.0)


def damage_enemy(game, e: Enemy, dmg: float, dx: float, dy: float, source: str) -> None:
    if e.dead:
        return
    if e.guard:
        # a visible shield covers the front arc: toward the player when they are facing us
        to_player = math.degrees(math.atan2(game.p.y - e.y, game.p.x - e.x))
        if _angle_diff(to_player, e.facing) < 70 and e.st != "windup":
            dmg *= 0.3
            game.float_text("Guarded", e.x, e.y - 0.9, (170, 200, 255))
            game.fx_add("spark", e.x, e.y, life=0.25)
            game.sfx("verdant_block")
    if e.kind in ("bogwight", "shade") and lamp_light(game, e.x, e.y):
        dmg *= 1.5
        game.float_text("Lamplight!", e.x, e.y - 1.1, (255, 230, 140))
    if e.d["ai"] == "boss" and e.aux.get("armor_t", 0) > 0:
        dmg *= 0.5
    e.hp -= dmg
    e.hurt_total += dmg
    e.flash = 0.18
    e.aggro = SIGHT_LOSS + 4
    e.knock_t = 0.12
    kb = 3.0 if e.d["ai"] != "boss" else 0.6
    e.kx, e.ky = dx * kb * 2.2, dy * kb * 2.2
    if e.st == "windup" and e.d["ai"] != "boss":
        e.stun = 0.35
        e.st = "recover"
        e.t = 0.35
    game.float_text(str(int(round(dmg))), e.x, e.y - 0.7, (255, 240, 200))
    game.fx_add("hit", e.x, e.y, life=0.3, color=(255, 220, 160))
    game.sfx("verdant_hit")
    game.add_skill_xp("blade" if source == "melee" else "bow", 0.6)
    if e.hp <= 0:
        kill(game, e, source)


def kill(game, e: Enemy, source: str = "melee") -> None:
    e.dead = True
    game.fx_add("poof", e.x, e.y, life=0.6, color=tuple(e.d.get("color", (200, 200, 200))))
    gold = max(0, int(game.rng.uniform(0.3, 1.0) * (e.d.get("xp", 5) / 2.5)))
    if gold:
        game.drops.append({"x": e.x, "y": e.y, "item": "gold", "n": gold, "area": game.area, "age": 0.0})
    for dr in e.d.get("drops", []):
        if game.rng.random() <= dr.get("chance", 1.0):
            n = game.rng.randint(dr.get("min", 1), max(dr.get("min", 1), dr.get("max", 1)))
            if n > 0:
                game.drops.append({"x": e.x + game.rng.uniform(-0.4, 0.4), "y": e.y + game.rng.uniform(-0.4, 0.4), "item": dr["item"],
                                   "n": n, "area": game.area, "age": 0.0})
    xp = float(e.d.get("xp", 5))
    game.add_skill_xp("blade" if source == "melee" else "bow", xp * 0.35)
    game.add_skill_xp("vigor", xp * 0.25)
    game.float_text(f"+{int(xp)} xp", e.x, e.y - 1.2, (140, 220, 255))
    game.sfx("verdant_kill")
    if not e.summoned:
        game.enemy_died(e)
    else:
        game.kills[e.kind] = game.kills.get(e.kind, 0) + 1
        game.quests.on_kill(game, e.kind)


# --------------------------------------------------------------------------------------------- per-tick update
def update(game, dt: float) -> None:
    P = game.p
    wm = game.wm
    walkb = game.walkb()
    for e in game.enemies:
        if e.dead:
            continue
        e.flash = max(0.0, e.flash - dt)
        e.cd = max(0.0, e.cd - dt)
        e.stun = max(0.0, e.stun - dt)
        e.knock_t = max(0.0, e.knock_t - dt)
        if e.knock_t > 0:
            e.x, e.y, _ = move(walkb, wm.W, wm.H, e.x, e.y, e.kx * dt, e.ky * dt, e.r)
        dist = math.hypot(P.x - e.x, P.y - e.y)
        e.los_t -= dt
        if e.los_t <= 0:
            e.los_t = 0.22
            e.sees = dist < float(e.d.get("sight", 8)) and (game.los((e.x, e.y), (P.x, P.y)) or dist < 2.0) and not game.dead
        if e.sees:
            e.aggro = SIGHT_LOSS
        else:
            e.aggro = max(0.0, e.aggro - dt)
        if e.stun > 0:
            continue
        ai = e.d["ai"]
        if e.kind in ("bogwight", "shade") and game.is_night() and lamp_light(game, e.x, e.y, 5.5) and e.d["ai"] == "lurker":
            ax, ay = e.x - P.x, e.y - P.y
            if lamp_light(game, e.x, e.y, 5.5):
                _walk(game, e, 0.0, 0.0)
                e.st = "idle"
                e.aggro = 0
                continue
        if ai == "boss":
            _boss(game, e, dt, dist)
        elif ai == "ranged":
            _ranged(game, e, dt, dist)
        elif ai == "pack":
            _pack(game, e, dt, dist)
        else:
            _melee(game, e, dt, dist)
        if dist > 90 and game.area == "overworld":
            pass
    game.enemies = [e for e in game.enemies if not e.dead or True]
    game.enemies = [e for e in game.enemies if not e.dead]
    _hazards(game, dt)
    _projectiles(game, dt)


def alert_noise(game, x: float, y: float, radius: float) -> None:
    for e in game.enemies:
        if not e.dead and math.hypot(e.x - x, e.y - y) <= radius:
            e.aggro = max(e.aggro, 3.0)


def _idle(game, e: Enemy, dt: float) -> None:
    e.wander_t -= dt
    if e.wander_t <= 0:
        e.wander_t = game.rng.uniform(1.5, 4.0)
        if game.rng.random() < 0.55:
            ang = game.rng.random() * math.tau
            r = game.rng.uniform(0.5, 2.5)
            e.wander_to = (e.home[0] + math.cos(ang) * r, e.home[1] + math.sin(ang) * r)
        else:
            e.wander_to = None
    if e.wander_to:
        if math.hypot(e.wander_to[0] - e.x, e.wander_to[1] - e.y) < 0.2:
            e.wander_to = None
        else:
            _steer(game, e, e.wander_to[0], e.wander_to[1], e.speed * 0.35, dt)


def _melee(game, e: Enemy, dt: float, dist: float) -> None:
    P = game.p
    reach = 0.95 + 0.4 * float(e.d.get("size", 1.0))
    flee_hp = float(e.d.get("flee", 0.0))
    if e.st in ("idle", "chase"):
        if e.aggro <= 0:
            e.st = "idle"
            _idle(game, e, dt)
            return
        e.st = "chase"
        if flee_hp and e.hp < e.maxhp * flee_hp and not e.aux.get("fled"):
            e.aux["fled"] = True
            e.st = "flee"
            e.t = 3.0
            return
        # keep the guard facing the player
        _steer(game, e, P.x, P.y, e.speed * (1.0 + 0.15 * game.adapt.level("rush")), dt)
        if dist <= reach and e.cd <= 0 and not game.dead:
            e.st = "windup"
            e.windup_total = e.t = 0.5 if e.kind != "bogwight" else 0.65
            _face(e, P.x, P.y)
    elif e.st == "windup":
        e.t -= dt
        if e.t <= 0:
            if math.hypot(P.x - e.x, P.y - e.y) <= reach + 0.4:
                if game.hurt_player(float(e.d.get("dmg", 4)), e.x, e.y) and e.kind == "bogwight" and game.rng.random() < 0.25 and not game.p.fever:
                    game.p.fever = True
                    game.toast("You feel feverish.")
            e.st = "recover"
            e.t = 0.6
            e.cd = 0.9
    elif e.st == "recover":
        e.t -= dt
        if e.t <= 0:
            e.st = "chase"
    elif e.st == "flee":
        e.t -= dt
        ax, ay = e.x - P.x, e.y - P.y
        d = math.hypot(ax, ay) or 1.0
        _walk(game, e, ax / d * e.speed * 1.1 * dt, ay / d * e.speed * 1.1 * dt)
        if e.t <= 0:
            e.st = "chase"


def _pack(game, e: Enemy, dt: float, dist: float) -> None:
    P = game.p
    if e.st in ("idle", "circle"):
        if e.aggro <= 0:
            e.st = "idle"
            _idle(game, e, dt)
            return
        e.st = "circle"
        mates = [m for m in game.enemies if m.zone == e.zone and not m.dead and m.d["ai"] == "pack"]
        k = max(1, len(mates))
        try:
            i = mates.index(e)
        except ValueError:
            i = 0
        base = game.t * (0.5 + 0.6 * game.adapt.level("rush"))
        ang = base + i * math.tau / k
        ring = 2.6 + 0.4 * (i % 2)
        tx, ty = P.x + math.cos(ang) * ring, P.y + math.sin(ang) * ring
        if dist > 7:
            tx, ty = P.x, P.y
        _steer(game, e, tx, ty, e.speed * 0.85, dt)
        lead = (i == int(game.t * 0.35) % k)
        if e.cd <= 0 and dist < 3.8 and lead and not game.dead:
            e.st = "windup"
            e.windup_total = e.t = 0.38
            _face(e, P.x, P.y)
        flee_hp = float(e.d.get("flee", 0.0))
        if flee_hp and e.hp < e.maxhp * flee_hp:
            e.st = "flee"
            e.t = 2.5
    elif e.st == "windup":
        e.t -= dt
        _face(e, P.x, P.y)
        if e.t <= 0:
            a = math.radians(e.facing)
            e.dash = (math.cos(a), math.sin(a), 0.3)
            e.st = "dash"
    elif e.st == "dash":
        dx, dy, t = e.dash
        t -= dt
        e.dash = (dx, dy, t)
        blocked = _walk(game, e, dx * 8.5 * dt, dy * 8.5 * dt)
        if math.hypot(P.x - e.x, P.y - e.y) < 0.8:
            game.hurt_player(float(e.d.get("dmg", 4)), e.x, e.y)
            t = 0
        if t <= 0 or blocked:
            e.st = "recover"
            e.t = 0.8
            e.cd = 1.6
    elif e.st == "recover":
        e.t -= dt
        if e.t <= 0:
            e.st = "circle"
    elif e.st == "flee":
        e.t -= dt
        ax, ay = e.x - P.x, e.y - P.y
        d = math.hypot(ax, ay) or 1.0
        _walk(game, e, ax / d * e.speed * 1.2 * dt, ay / d * e.speed * 1.2 * dt)
        if e.t <= 0:
            e.st = "circle"
            e.hp = min(e.maxhp, e.hp + 3)


def _ranged(game, e: Enemy, dt: float, dist: float) -> None:
    P = game.p
    rush = game.adapt.level("rush")
    keep = 5.2 - 2.4 * rush
    if e.st in ("idle", "aim_ready"):
        if e.aggro <= 0:
            e.st = "idle"
            _idle(game, e, dt)
            return
        e.st = "aim_ready"
        if dist < keep - 1.0:
            ax, ay = e.x - P.x, e.y - P.y
            d = math.hypot(ax, ay) or 1.0
            _walk(game, e, ax / d * e.speed * dt, ay / d * e.speed * dt)
            _face(e, P.x, P.y)
        elif dist > keep + 2.5 or not e.sees:
            _steer(game, e, P.x, P.y, e.speed, dt)
        else:
            _face(e, P.x, P.y)
        if e.cd <= 0 and e.sees and dist < float(e.d.get("sight", 10)) and not game.dead:
            e.st = "windup"
            e.windup_total = e.t = 0.6
    elif e.st == "windup":
        e.t -= dt
        _face(e, P.x, P.y)
        if e.t <= 0:
            a = math.radians(e.facing)
            game.projectiles.append(Projectile(e.x, e.y, math.cos(a) * 9.5, math.sin(a) * 9.5, float(e.d.get("dmg", 4)), False,
                                               life=1.7, kind="arrow", area=game.area))
            game.sfx("verdant_bow")
            e.st = "aim_ready"
            e.cd = 1.9 - 0.5 * rush


# --------------------------------------------------------------------------------------------- bosses
def _spawn_add(game, e: Enemy, kind: str, n: int) -> None:
    for i in range(n):
        a = game.rng.random() * math.tau
        x, y = e.x + math.cos(a) * 2.0, e.y + math.sin(a) * 2.0
        if not fits(game.walkb(), game.wm.W, game.wm.H, x, y, 0.35):
            x, y = e.x, e.y
        m = Enemy(game, kind, x, y, "", i, n)
        m.summoned = True
        m.aggro = SIGHT_LOSS + 4
        m.st = "chase"
        game.enemies.append(m)
    game.float_text("Reinforcements!", e.x, e.y - 1.5, (255, 180, 120))


def _boss(game, e: Enemy, dt: float, dist: float) -> None:
    P = game.p
    aux = e.aux
    aux["armor_t"] = max(0.0, aux.get("armor_t", 0.0) - dt)
    if e.aggro <= 0 and e.st in ("idle", "chase"):
        e.st = "idle"
        if e.hp < e.maxhp:
            e.hp = min(e.maxhp, e.hp + 8 * dt)
        return
    phase2 = e.hp < e.maxhp * 0.5
    k = e.kind
    if e.st in ("idle", "chase"):
        e.st = "chase"
        rng_to = 1.6 if k in ("rook_captain", "bell_warden", "debt_collector") else 3.0
        if dist > rng_to:
            _steer(game, e, P.x, P.y, e.speed, dt)
        else:
            _face(e, P.x, P.y)
        # one-off phase events
        if k == "rook_captain" and phase2 and not aux.get("summoned"):
            aux["summoned"] = True
            _spawn_add(game, e, "bandit", 2)
        if k == "root_mother":
            for thr, key in ((0.65, "s1"), (0.3, "s2")):
                if e.hp < e.maxhp * thr and not aux.get(key):
                    aux[key] = True
                    _spawn_add(game, e, "crawler", 2)
        if e.cd <= 0 and not game.dead:
            _boss_pick(game, e, dist, phase2)
    elif e.st == "windup":
        e.t -= dt
        a = aux.get("atk")
        if a in ("slash", "swing") or a is None:
            _face(e, P.x, P.y)
        if e.t <= 0:
            _boss_fire(game, e, a, phase2)
    elif e.st == "charge":
        dx, dy, t = e.dash
        t -= dt
        e.dash = (dx, dy, t)
        blocked = _walk(game, e, dx * 10.5 * dt, dy * 10.5 * dt)
        if math.hypot(P.x - e.x, P.y - e.y) < 1.1:
            game.hurt_player(float(e.d["dmg"]) * 1.2, e.x, e.y, 5.0)
            t = 0
        if t <= 0 or blocked:
            e.st = "recover"
            e.t = 1.1
            e.cd = 1.2
    elif e.st == "recover":
        e.t -= dt
        if e.t <= 0:
            e.st = "chase"


def _boss_pick(game, e: Enemy, dist: float, phase2: bool) -> None:
    P = game.p
    k = e.kind
    r = game.rng
    if k == "rook_captain":
        a = "charge" if dist > 3.0 or r.random() < 0.3 else "slash"
        tw = 0.8 if a == "charge" else 0.5
    elif k == "debt_collector":
        a = r.choice(["slam", "slam", "fan", "blink"]) if dist > 2.0 else r.choice(["slash", "slam", "fan"])
        tw = 0.9 if a == "slam" else 0.55
    elif k == "bell_warden":
        a = r.choice(["ring", "swing", "swing"]) if dist < 5 else r.choice(["ring", "ring", "charge"])
        tw = 0.9 if a == "ring" else 0.55
    else:  # root_mother
        a = r.choice(["roots", "roots", "spit", "swing"]) if dist > 2.2 else r.choice(["swing", "roots"])
        tw = 0.95 if a == "roots" else 0.6
    e.aux["atk"] = a
    e.st = "windup"
    e.windup_total = e.t = tw * (0.85 if phase2 else 1.0)
    _face(e, P.x, P.y)
    if a == "slam":
        n = 3 if phase2 else 1
        for i in range(n):
            ox = P.x + (r.uniform(-2.2, 2.2) if i else 0)
            oy = P.y + (r.uniform(-2.2, 2.2) if i else 0)
            game.hazards.append(Hazard("circle", ox, oy, 1.9, e.t + 0.15 * i, e.t, float(e.d["dmg"]) * 1.1, e.uid, area=game.area))
    elif a == "roots":
        n = 4 if phase2 else 3
        for i in range(n):
            ang = r.random() * math.tau
            rad = 0.0 if i == 0 else r.uniform(1.2, 3.0)
            game.hazards.append(Hazard("circle", P.x + math.cos(ang) * rad, P.y + math.sin(ang) * rad, 1.5, e.t + 0.2 * i, e.t,
                                       float(e.d["dmg"]), e.uid, area=game.area))
    elif a == "ring":
        game.hazards.append(Hazard("ring", e.x, e.y, 7.0 if phase2 else 6.0, 0.0, 1.5, float(e.d["dmg"]), e.uid, linger=0.0, area=game.area))
        e.aux["armor_t"] = 1.5
        if phase2:
            game.hazards.append(Hazard("ring", e.x, e.y, 8.5, -0.6, 1.8, float(e.d["dmg"]), e.uid, linger=0.0, area=game.area))
        game.sfx("verdant_bell")


def _boss_fire(game, e: Enemy, a: str | None, phase2: bool) -> None:
    P = game.p
    d = float(e.d["dmg"])
    if a in ("slash", "swing"):
        if math.hypot(P.x - e.x, P.y - e.y) <= 1.5 + 0.5 * e.d.get("size", 1):
            game.hurt_player(d, e.x, e.y, 4.5)
        e.st = "recover"
        e.t = 0.7
        e.cd = 0.9
    elif a == "charge":
        ang = math.atan2(P.y - e.y, P.x - e.x)
        e.dash = (math.cos(ang), math.sin(ang), 0.55)
        e.st = "charge"
    elif a == "fan":
        base = math.atan2(P.y - e.y, P.x - e.x)
        n = 5 if phase2 else 3
        for i in range(n):
            ang = base + (i - (n - 1) / 2) * 0.28
            game.projectiles.append(Projectile(e.x, e.y, math.cos(ang) * 7.0, math.sin(ang) * 7.0, d * 0.7, False, life=2.2, kind="bolt",
                                               area=game.area, r=0.45))
        e.st = "recover"
        e.t = 0.6
        e.cd = 1.1
    elif a == "blink":
        for _ in range(16):
            ang = game.rng.random() * math.tau
            x, y = P.x + math.cos(ang) * 2.8, P.y + math.sin(ang) * 2.8
            if fits(game.walkb(), game.wm.W, game.wm.H, x, y, e.r) and game.los((x, y), (P.x, P.y)):
                e.x, e.y = x, y
                game.fx_add("poof", x, y, life=0.4, color=(190, 170, 230))
                break
        e.st = "recover"
        e.t = 0.5
        e.cd = 0.6
    elif a == "spit":
        ang = math.atan2(P.y - e.y, P.x - e.x)
        for off in (-0.2, 0.0, 0.2):
            game.projectiles.append(Projectile(e.x, e.y, math.cos(ang + off) * 6.5, math.sin(ang + off) * 6.5, d * 0.7, False, life=2.2,
                                               kind="bolt", area=game.area, r=0.45))
        e.st = "recover"
        e.t = 0.7
        e.cd = 1.3
    else:                                              # slam / ring / roots: hazards were placed at wind-up start
        e.st = "recover"
        e.t = 0.9
        e.cd = 1.3 if not phase2 else 0.9


# --------------------------------------------------------------------------------------------- hazards & projectiles
def _hazards(game, dt: float) -> None:
    P = game.p
    keep = []
    for h in game.hazards:
        if h.area != game.area:
            continue
        if h.kind == "circle":
            h.t -= dt
            if h.t <= 0 and not h.hit:
                h.hit = True
                if math.hypot(P.x - h.x, P.y - h.y) < h.r:
                    game.hurt_player(h.dmg, h.x, h.y, 5.0)
                game.fx_add("boom", h.x, h.y, life=0.35, r=h.r)
                game.sfx("verdant_slam")
            if h.hit:
                h.linger -= dt
                if h.linger <= 0:
                    continue
        else:  # ring
            h.t += dt
            if h.t < 0:
                keep.append(h)
                continue
            cur = h.r * min(1.0, h.t / h.dur)
            d = math.hypot(P.x - h.x, P.y - h.y)
            if not h.hit and abs(d - cur) < 0.65 and h.t > 0.05:
                if game.hurt_player(h.dmg, h.x, h.y, 5.5):
                    h.hit = True
            if h.t >= h.dur + 0.1:
                continue
        keep.append(h)
    game.hazards = keep


def _projectiles(game, dt: float) -> None:
    P = game.p
    wm = game.wm
    walkb = game.walkb()
    keep = []
    for p in game.projectiles:
        if p.area != game.area:
            continue
        p.life -= dt
        nx, ny = p.x + p.vx * dt, p.y + p.vy * dt
        ix, iy = int(nx), int(ny)
        if p.life <= 0 or ix < 0 or iy < 0 or ix >= wm.W or iy >= wm.H or not walkb[iy * wm.W + ix]:
            if p.life > 0 and 0 <= ix < wm.W and 0 <= iy < wm.H and wm.ground[iy, ix] in (6, 7) and False:
                pass
            game.fx_add("spark", nx, ny, life=0.2)
            continue
        p.x, p.y = nx, ny
        if p.friendly:
            hit = None
            for e in game.enemies:
                if not e.dead and math.hypot(e.x - p.x, e.y - p.y) < e.r + p.r:
                    hit = e
                    break
            if hit:
                n = math.hypot(p.vx, p.vy) or 1.0
                damage_enemy(game, hit, p.dmg, p.vx / n, p.vy / n, "arrow")
                continue
        else:
            if math.hypot(P.x - p.x, P.y - p.y) < 0.38 + p.r * 0.3:
                if game.hurt_player(p.dmg, p.x - p.vx * 0.1, p.y - p.vy * 0.1, 3.0):
                    continue
        keep.append(p)
    game.projectiles = keep
