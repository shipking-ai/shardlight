"""Tactical battles: a small deterministic grid fight between two stacks of up to eight units.

Phase based: the attacker's side acts (every unit may move and then act once), then the defender's side.
Units have facing (flanking matters), terrain matters, abilities have cooldowns and morale breaks lines.
The same ``Battle`` object is driven by the player's input or by ``BattleAI`` - the AI uses the public action API
and the same rules, so ``auto_resolve`` is simply the AI playing both sides.

Pure logic: no pygame.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any

from ...core.rng import Rng
from .rules import Rules, house_mods, tech_unit_effects
from .state import Unit

GRID_W, GRID_H = 11, 7
ROUND_LIMIT = 16
ATTACKER, DEFENDER = 0, 1

OPEN, FOREST, HILL, ROCK, MARSH, WALL, WATER, FORD = "open", "forest", "hill", "rock", "marsh", "wall", "water", "ford"
TILE_COST = {OPEN: 1, FOREST: 2, HILL: 2, ROCK: 99, MARSH: 2, WALL: 99, WATER: 99, FORD: 2}
BLOCKS_SIGHT = {ROCK, WALL}
DIRS8 = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
POSITIVE = ("shielded", "braced", "inspired", "enraged")
NEGATIVE = ("slow", "marked", "stagger")

ROLE_ORDER = {"pike": 0, "infantry": 0, "banner": 1, "cavalry": 1, "skirmisher": 1, "healer": 2, "archer": 2, "siege": 3}


def cheb(ax: int, ay: int, bx: int, by: int) -> int:
    dx = ax - bx
    dy = ay - by
    if dx < 0:
        dx = -dx
    if dy < 0:
        dy = -dy
    return dx if dx > dy else dy


@dataclass
class BUnit:
    id: int
    side: int
    type: str
    name: str
    role: str
    uid: int                      # campaign unit uid (-1 for none)
    x: int
    y: int
    hp: float
    maxhp: float
    atk: float
    arm: float
    move: int
    range: int
    morale: float
    maxmorale: float
    rank: int = 0
    traits: tuple = ()
    ability: dict | None = None
    upgrades: tuple = ()
    facing: tuple = (1, 0)
    cd: int = 0
    status: dict = field(default_factory=dict)
    alive: bool = True
    routed: bool = False
    moved: int = 0                # tiles moved this phase
    straight: int = 0             # length of the current straight run toward its facing (cavalry charge)
    acted: bool = False
    done: bool = False
    took_damage: bool = False
    kills: int = 0
    dealt: float = 0.0

    @property
    def active(self) -> bool:
        return self.alive and not self.routed


@dataclass
class Event:
    kind: str
    a: int = -1
    b: int = -1
    x: int = 0
    y: int = 0
    amount: float = 0.0
    text: str = ""


# ------------------------------------------------------------------------------------------------- stats
def unit_stats(rules: Rules, unit: Unit, techs: list[str], mods: dict[str, float]) -> dict[str, Any]:
    """Final combat stats of a campaign unit: base + techs + rank + house modifiers."""
    d = rules.units[unit.type]
    s = {"hp": float(d["hp"]), "atk": float(d["atk"]), "arm": float(d["arm"]), "move": int(d["move"]),
         "range": int(d["range"]), "morale": float(d.get("morale", 60))}
    upgrades = []
    for eff in tech_unit_effects(rules, techs):
        if eff["kind"] == "unit_mod" and eff["role"] == d["role"]:
            s[eff["stat"]] = s.get(eff["stat"], 0) + eff["value"]
        elif eff["kind"] == "upgrade":
            upgrades.append(eff["trait"])
    s["morale"] += mods.get("morale", 0.0)
    rank = unit.rank
    s["hp"] *= 1 + 0.06 * rank
    s["atk"] *= 1 + 0.04 * rank
    s["upgrades"] = tuple(upgrades)
    s["rank"] = rank
    return s


# ------------------------------------------------------------------------------------------------ battle
class Battle:
    def __init__(self, rules: Rules, seed: int, terrain: str, attackers: list[tuple[Unit, dict]],
                 defenders: list[tuple[Unit, dict]], fort: int = 0, river: bool = False, names: tuple[str, str] = ("", ""),
                 houses: tuple[str, str] = ("", "")):
        """``attackers`` / ``defenders`` are ``(Unit, stats)`` pairs (stats from :func:`unit_stats`)."""
        self.rules = rules
        self.rng = Rng(seed).child("battle")
        self.terrain = terrain
        self.fort = fort
        self.river = river
        self.names = names
        self.houses = houses
        self.tiles: list[list[str]] = [[OPEN] * GRID_W for _ in range(GRID_H)]
        self.wall_hp: dict[tuple[int, int], float] = {}
        self.units: list[BUnit] = []
        self.events: list[Event] = []
        self.round = 1
        self.phase = ATTACKER
        self.log: list[str] = []
        self._next_id = 1
        self._build_tiles()
        self._deploy(ATTACKER, attackers)
        self._deploy(DEFENDER, defenders)
        self.start_hp = {s: sum(u.hp for u in self.units if u.side == s) for s in (0, 1)}
        self.result: dict | None = None

    # ------------------------------------------------------------------ setup
    def _build_tiles(self) -> None:
        r = self.rng.child("tiles")
        t = self.terrain
        share = {"plain": {FOREST: 0.06, HILL: 0.06}, "forest": {FOREST: 0.34, HILL: 0.05},
                 "hill": {HILL: 0.34, FOREST: 0.06, ROCK: 0.04}, "mountain": {ROCK: 0.2, HILL: 0.22},
                 "marsh": {MARSH: 0.4, FOREST: 0.05}}[t]
        for y in range(GRID_H):
            for x in range(GRID_W):
                if x <= 1 or x >= GRID_W - 2:
                    continue                                    # deployment columns stay open
                roll = r.random()
                acc = 0.0
                for kind, p in share.items():
                    acc += p
                    if roll < acc:
                        self.tiles[y][x] = kind
                        break
        if self.river:
            cx = GRID_W // 2 - 1
            fords = {r.randint(1, 2), r.randint(4, 5)}
            for y in range(GRID_H):
                self.tiles[y][cx] = FORD if y in fords else WATER
        if self.fort > 0:
            wx = GRID_W - 5
            gate = GRID_H // 2
            for y in range(GRID_H):
                if y == gate:
                    self.tiles[y][wx] = OPEN
                else:
                    self.tiles[y][wx] = WALL
                    self.wall_hp[(wx, y)] = 22.0 * self.fort
            for dx in (-1, 1):
                for y in range(GRID_H):
                    if self.tiles[y][wx + dx] in (WATER, ROCK):
                        self.tiles[y][wx + dx] = OPEN

    def _deploy(self, side: int, army: list[tuple[Unit, dict]]) -> None:
        d = self.rules.units
        ordered = sorted(army, key=lambda p: (ROLE_ORDER[d[p[0].type]["role"]], p[0].uid))
        cols = [0, 1] if side == ATTACKER else [GRID_W - 1, GRID_W - 2]
        if side == DEFENDER and self.fort > 0:
            cols = [GRID_W - 4, GRID_W - 3, GRID_W - 2, GRID_W - 1]
        # front line occupies the column nearest the enemy; fill rows from the centre outwards
        rows = sorted(range(GRID_H), key=lambda y: (abs(y - GRID_H // 2), y))
        slots = []
        for col in (cols if side == DEFENDER else list(reversed(cols))):
            for y in rows:
                slots.append((col, y))
        if side == ATTACKER:
            slots = [(c, y) for c in (1, 0) for y in rows]
        else:
            slots = [(c, y) for c in cols for y in rows]
        for unit, st in ordered:
            ud = d[unit.type]
            while slots and self.tiles[slots[0][1]][slots[0][0]] in (WALL, ROCK, WATER):
                slots.pop(0)
            if not slots:
                break
            x, y = slots.pop(0)
            b = BUnit(self._next_id, side, unit.type, ud["name"], ud["role"], unit.uid, x, y, min(unit.hp, st["hp"]), st["hp"],
                      st["atk"], st["arm"], st["move"], st["range"], st["morale"], st["morale"], st["rank"],
                      tuple(ud.get("traits", [])), ud.get("ability"), st["upgrades"],
                      (1, 0) if side == ATTACKER else (-1, 0))
            self._next_id += 1
            self.units.append(b)

    # ------------------------------------------------------------------ queries
    def unit(self, uid: int) -> BUnit:
        for u in self.units:
            if u.id == uid:
                return u
        raise KeyError(uid)

    def at(self, x: int, y: int) -> BUnit | None:
        for u in self.units:
            if u.active and u.x == x and u.y == y:
                return u
        return None

    def side_units(self, side: int) -> list[BUnit]:
        return [u for u in self.units if u.side == side and u.active]

    def enemies_of(self, u: BUnit) -> list[BUnit]:
        side = u.side
        return [e for e in self.units if e.side != side and e.alive and not e.routed]

    def tile(self, x: int, y: int) -> str:
        return self.tiles[y][x]

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < GRID_W and 0 <= y < GRID_H

    def has_status(self, u: BUnit, s: str) -> bool:
        return u.status.get(s, 0) > 0

    def effective_move(self, u: BUnit) -> int:
        m = u.move
        if self.has_status(u, "slow"):
            m = max(1, m - 2)
        return m

    def adjacent_allies(self, u: BUnit) -> list[BUnit]:
        return [a for a in self.units if a.active and a.side == u.side and a.id != u.id and cheb(a.x, a.y, u.x, u.y) == 1]

    def reachable(self, u: BUnit, budget: int | None = None) -> dict[tuple[int, int], int]:
        """Tiles ``u`` can end on this phase mapped to their movement cost (enemies block; allies can be passed)."""
        if u.done or not u.active:
            return {}
        skirm = "_skirmish" in u.status
        if u.acted and not skirm:
            return {}
        budget = (2 if skirm else self.effective_move(u)) if budget is None else budget
        foes = self.enemies_of(u)
        enemies = {(e.x, e.y) for e in foes}
        engaged = {(e.x + dx, e.y + dy) for e in foes for dx, dy in DIRS8} if "skirmish" not in u.traits else set()
        allies = {(a.x, a.y) for a in self.side_units(u.side) if a.id != u.id}
        tiles = self.tiles
        dist = {(u.x, u.y): 0}
        pq = [(0, u.x, u.y)]
        while pq:
            c, x, y = heapq.heappop(pq)
            if c > dist.get((x, y), 99):
                continue
            for dx, dy in DIRS8:
                nx, ny = x + dx, y + dy
                if not self.inside(nx, ny) or (nx, ny) in enemies:
                    continue
                step = TILE_COST[tiles[ny][nx]]
                if step >= 99:
                    continue
                if dx and dy and (TILE_COST[tiles[y][nx]] >= 99 and TILE_COST[tiles[ny][x]] >= 99):
                    continue                                    # no squeezing between two blocked corners
                if (nx, ny) in engaged:
                    step += 1                                   # engagement: slipping past enemies costs extra
                nc = c + step
                if nc <= budget and nc < dist.get((nx, ny), 99):
                    dist[(nx, ny)] = nc
                    heapq.heappush(pq, (nc, nx, ny))
        return {p: c for p, c in dist.items() if p == (u.x, u.y) or p not in allies}

    def los(self, ax: int, ay: int, bx: int, by: int) -> bool:
        """Straight-line sight between tiles; rocks and walls block it (endpoints excluded)."""
        n = max(abs(bx - ax), abs(by - ay))
        for i in range(1, n):
            t = i / n
            x = round(ax + (bx - ax) * t)
            y = round(ay + (by - ay) * t)
            if self.tiles[y][x] in BLOCKS_SIGHT:
                return False
        return True

    def attack_range(self, u: BUnit, ability: bool = False) -> int:
        r = u.range
        if ability and u.ability and u.ability["kind"] in ("empowered_attack", "splash_attack") and u.ability.get("range"):
            r = max(r, int(u.ability["range"]))
        return r

    def targets(self, u: BUnit, from_xy: tuple[int, int] | None = None, ability: bool = False) -> list[BUnit]:
        x, y = from_xy or (u.x, u.y)
        r = self.attack_range(u, ability)
        out = []
        for e in self.enemies_of(u):
            d = cheb(x, y, e.x, e.y)
            if d <= r and (d == 1 or u.role == "siege" or self.los(x, y, e.x, e.y)):
                out.append(e)
        return out

    def wall_targets(self, u: BUnit, from_xy: tuple[int, int] | None = None) -> list[tuple[int, int]]:
        if u.role != "siege" or u.side != ATTACKER:
            return []
        x, y = from_xy or (u.x, u.y)
        return [w for w in self.wall_hp if self.wall_hp[w] > 0 and cheb(x, y, w[0], w[1]) <= u.range]

    # ------------------------------------------------------------------ damage model
    def facing_factor(self, attacker: BUnit, target: BUnit) -> float:
        """+30% from behind, +12% from the side (flankers add more)."""
        vx, vy = attacker.x - target.x, attacker.y - target.y
        n = math.hypot(vx, vy) or 1.0
        fx, fy = target.facing
        fn = math.hypot(fx, fy) or 1.0
        dot = (vx * fx + vy * fy) / (n * fn)
        bonus = 0.30 if dot < -0.45 else 0.12 if abs(dot) <= 0.45 else 0.0
        if bonus and "flanker" in attacker.traits:
            bonus *= 1.8
        return 1.0 + bonus

    def terrain_arm(self, target: BUnit, ranged: bool) -> float:
        t = self.tiles[target.y][target.x]
        bonus = {FOREST: 2.0 if ranged else 1.0, HILL: 1.0, MARSH: -1.0}.get(t, 0.0)
        if self.fort and target.side == DEFENDER and any(self.tiles[target.y][x] == WALL for x in (target.x - 1,) if self.inside(x, target.y)):
            bonus += 2.0 if ranged else 0.5
        return bonus

    def effective_atk(self, u: BUnit) -> float:
        a = u.atk
        if "rage" in u.traits and u.hp <= u.maxhp * 0.5:
            a *= 1.3
        if self.has_status(u, "enraged"):
            a *= 1.3
        if self.has_status(u, "inspired"):
            a *= 1.15
        if "resonant_line" in u.traits:
            n = min(3, sum(1 for a2 in self.adjacent_allies(u) if "resonant_line" in a2.traits))
            a *= 1 + n * (0.14 if "resonant_line" in u.upgrades else 0.08)
        return a

    def effective_arm(self, u: BUnit) -> float:
        a = u.arm
        if self.has_status(u, "braced") or ("pike_wall" in u.traits and not u.moved and not u.acted):
            a += 2.0
        if self.has_status(u, "enraged"):
            a -= 1.0
        if "resonant_line" in u.upgrades and "resonant_line" in u.traits:
            a += min(3, sum(1 for a2 in self.adjacent_allies(u) if "resonant_line" in a2.traits)) * 0.5
        return max(0.0, a)

    def damage_estimate(self, a: BUnit, t: BUnit, mult: float = 1.0, from_xy: tuple[int, int] | None = None,
                        charge: int | None = None) -> float:
        ax, ay = from_xy or (a.x, a.y)
        ranged = cheb(ax, ay, t.x, t.y) > 1
        arm = self.effective_arm(t) + self.terrain_arm(t, ranged)
        base = self.effective_atk(a) * mult
        dmg = base * 100.0 / (100.0 + 14.0 * arm)
        probe = BUnit(**{**a.__dict__, "x": ax, "y": ay})
        dmg *= self.facing_factor(probe, t)
        if a.role == "pike" and t.role == "cavalry":
            dmg *= 1.6
        run = a.straight if charge is None else charge
        if a.role == "cavalry" and not ranged and run >= 3:
            dmg *= 1.45 + (0.2 if "charge_plus" in a.traits else 0.0)
        if ranged and a.role in ("archer", "skirmisher") and cheb(ax, ay, t.x, t.y) > 1 and any(
                cheb(ax, ay, e.x, e.y) == 1 for e in self.enemies_of(a)):
            dmg *= 0.7
        if not ranged and a.role == "archer":
            dmg *= 0.7
        if self.has_status(t, "marked"):
            dmg *= 1.25
        if self.has_status(t, "shielded"):
            dmg *= 0.65
        if self.tiles[ay][ax] == HILL and self.tiles[t.y][t.x] != HILL:
            dmg *= 1.10
        return max(1.0, dmg)

    # ------------------------------------------------------------------ actions
    def _emit(self, kind: str, a: int = -1, b: int = -1, x: int = 0, y: int = 0, amount: float = 0.0, text: str = "") -> None:
        self.events.append(Event(kind, a, b, x, y, amount, text))

    def drain(self) -> list[Event]:
        ev, self.events = self.events, []
        return ev

    def can_move_to(self, u: BUnit, x: int, y: int) -> bool:
        return (x, y) in self.reachable(u) and (x, y) != (u.x, u.y)

    def move(self, u: BUnit, x: int, y: int) -> bool:
        if u.side != self.phase or (x, y) == (u.x, u.y):
            return False
        reach = self.reachable(u)
        if (x, y) not in reach:
            return False
        cost = reach[(x, y)]
        dx, dy = x - u.x, y - u.y
        n = max(abs(dx), abs(dy))
        step = (int(math.copysign(1, dx)) if dx else 0, int(math.copysign(1, dy)) if dy else 0)
        straight = (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and all(
            self.tiles[u.y + step[1] * i][u.x + step[0] * i] == OPEN or i == 0 for i in range(1, n + 1))
        u.straight = (u.straight + n if u.facing == step else n) if straight else 0
        if straight:
            u.facing = step
        else:
            u.facing = (int(math.copysign(1, dx)) if dx else 0, int(math.copysign(1, dy)) if dy else 0)
            if u.facing == (0, 0):
                u.facing = (1, 0) if u.side == ATTACKER else (-1, 0)
        u.x, u.y = x, y
        u.moved += cost
        u.status.pop("_skirmish", None)
        self._emit("move", u.id, x=x, y=y)
        return True

    def _face(self, u: BUnit, tx: int, ty: int) -> None:
        dx, dy = tx - u.x, ty - u.y
        if dx or dy:
            u.facing = (int(math.copysign(1, dx)) if dx else 0, int(math.copysign(1, dy)) if dy else 0)

    def attack(self, u: BUnit, t: BUnit, mult: float = 1.0, splash: float = 0.0, status: str | None = None,
               status_turns: int = 1, from_ability: bool = False) -> bool:
        if u.side != self.phase or u.acted or not u.active or not t.active or t.side == u.side:
            return False
        if t not in self.targets(u, ability=from_ability):
            return False
        self._face(u, t.x, t.y)
        # braced pikes bite cavalry that charge them from the front
        retaliation = 0.0
        if u.role == "cavalry" and t.role == "pike" and "pike_wall" in t.traits and not t.moved and u.straight >= 2 \
                and self.facing_factor(u, t) <= 1.0:
            retaliation = t.atk * 0.9 * 100.0 / (100.0 + 14.0 * u.arm)
        dmg = self.damage_estimate(u, t, mult)
        dist_ = cheb(u.x, u.y, t.x, t.y)
        self._hit(u, t, dmg, flank=self.facing_factor(u, t) > 1.2)
        if splash > 0 and t.alive:
            pass
        if splash > 0:
            for e in self.enemies_of(u):
                if e.id != t.id and cheb(e.x, e.y, t.x, t.y) == 1:
                    self._hit(u, e, dmg * splash, flank=False)
        if status and t.alive:
            t.status[status] = max(t.status.get(status, 0), status_turns)
        if retaliation and u.active:
            self._hit(t, u, retaliation, flank=False, retaliate=True)
        u.acted = True
        u.straight = 0
        if "skirmish" in u.traits and u.active and dist_ >= 1:
            u.status["_skirmish"] = 1                           # hit and run: one short move after the shot, no second attack
        self._emit("attack", u.id, t.id, t.x, t.y, dmg)
        return True

    def _hit(self, src: BUnit, t: BUnit, dmg: float, flank: bool, retaliate: bool = False) -> None:
        dmg = min(dmg, t.hp)
        t.hp -= dmg
        src.dealt += dmg
        t.took_damage = True
        loss = dmg / t.maxhp * 38.0 + (6.0 if flank else 0.0)
        if "steady" in t.traits:
            loss *= 0.6
        t.morale -= loss
        self._emit("hit", src.id, t.id, t.x, t.y, dmg, "flank" if flank else "")
        if t.hp <= 0.001:
            t.alive = False
            src.kills += 1
            self._emit("death", src.id, t.id, t.x, t.y)
            for a in self.units:
                if a.active and a.side == t.side and cheb(a.x, a.y, t.x, t.y) <= 2:
                    a.morale -= 7.0 * (0.6 if "steady" in a.traits else 1.0)
            self._check_rout()
        elif t.morale <= 0:
            self._rout(t)

    def _check_rout(self) -> None:
        for u in self.units:
            if u.active and u.morale <= 0:
                self._rout(u)

    def _rout(self, u: BUnit) -> None:
        if u.routed or not u.alive:
            return
        u.routed = True
        self._emit("rout", u.id, x=u.x, y=u.y)
        for a in self.units:
            if a.active and a.side == u.side and cheb(a.x, a.y, u.x, u.y) <= 2:
                a.morale -= 4.0

    def attack_wall(self, u: BUnit, w: tuple[int, int]) -> bool:
        if u.side != self.phase or u.acted or w not in self.wall_targets(u):
            return False
        dmg = self.effective_atk(u) * 2.2
        self.wall_hp[w] -= dmg
        self._face(u, w[0], w[1])
        if self.wall_hp[w] <= 0:
            self.tiles[w[1]][w[0]] = OPEN
            self._emit("wall_down", u.id, x=w[0], y=w[1])
        else:
            self._emit("wall_hit", u.id, x=w[0], y=w[1], amount=dmg)
        u.acted = True
        return True

    def ability_ready(self, u: BUnit) -> bool:
        return bool(u.ability) and u.cd <= 0 and not u.acted and u.active and not self.has_status(u, "stagger")

    def ability_targets(self, u: BUnit) -> list:
        """Legal targets: enemy BUnits, ally BUnits, ``None`` for self-only abilities, or free (x, y) tiles."""
        ab = u.ability
        if not ab or not self.ability_ready(u):
            return []
        k = ab["kind"]
        r = int(ab.get("range", 1) or 1)
        if k in ("empowered_attack", "splash_attack"):
            return self.targets(u, ability=True)
        if k in ("self_buff", "aura_buff", "rally"):
            return [None]
        if k == "heal":
            return [a for a in self.side_units(u.side) if cheb(a.x, a.y, u.x, u.y) <= max(1, r) and a.hp < a.maxhp - 0.5]
        if k == "purge":
            ally = [a for a in self.side_units(u.side) if cheb(a.x, a.y, u.x, u.y) <= max(1, r) and any(s in a.status for s in NEGATIVE)]
            foe = [e for e in self.enemies_of(u) if cheb(e.x, e.y, u.x, u.y) <= max(1, r) and any(s in e.status for s in POSITIVE)]
            return ally + foe
        if k == "reposition":
            return [(x, y) for y in range(GRID_H) for x in range(GRID_W)
                    if cheb(x, y, u.x, u.y) <= max(1, r) and TILE_COST[self.tiles[y][x]] < 99 and self.at(x, y) is None
                    and (x, y) != (u.x, u.y)]
        return []

    def use_ability(self, u: BUnit, target: Any = None) -> bool:
        ab = u.ability
        if not self.ability_ready(u) or u.side != self.phase or target not in self.ability_targets(u):
            return False
        k = ab["kind"]
        cd = int(ab.get("cd", 3))
        status = ab.get("status")
        turns = int(ab.get("turns", 2))
        if k == "empowered_attack":
            ok = self.attack(u, target, mult=float(ab.get("mult", 1.5)), status=status, status_turns=turns, from_ability=True)
            if not ok:
                return False
        elif k == "splash_attack":
            ok = self.attack(u, target, mult=float(ab.get("mult", 1.0)), splash=float(ab.get("splash", 0.5)), status=status,
                             status_turns=turns, from_ability=True)
            if not ok:
                return False
        elif k == "self_buff":
            u.status[status or "braced"] = max(u.status.get(status or "braced", 0), turns)
            u.acted = True
            self._emit("buff", u.id, x=u.x, y=u.y, text=status or "braced")
        elif k == "aura_buff":
            for a in self.side_units(u.side):
                if cheb(a.x, a.y, u.x, u.y) <= int(ab.get("radius", 2)):
                    a.status[status or "shielded"] = max(a.status.get(status or "shielded", 0), turns)
            u.acted = True
            self._emit("buff", u.id, x=u.x, y=u.y, text=status or "shielded")
        elif k == "rally":
            for a in self.side_units(u.side):
                if cheb(a.x, a.y, u.x, u.y) <= int(ab.get("radius", 3)):
                    a.morale = min(a.maxmorale, a.morale + float(ab.get("morale", 20)))
                    if status:
                        a.status[status] = max(a.status.get(status, 0), turns)
            u.acted = True
            self._emit("rally", u.id, x=u.x, y=u.y)
        elif k == "heal":
            amt = float(ab.get("amount", 12))
            target.hp = min(target.maxhp, target.hp + amt)
            u.acted = True
            self._emit("heal", u.id, target.id, target.x, target.y, amt)
        elif k == "purge":
            if target.side == u.side:
                for s in NEGATIVE:
                    target.status.pop(s, None)
                target.morale = min(target.maxmorale, target.morale + float(ab.get("morale", 8)))
            else:
                for s in POSITIVE:
                    target.status.pop(s, None)
            u.acted = True
            self._emit("purge", u.id, target.id, target.x, target.y)
        elif k == "reposition":
            dx, dy = target[0] - u.x, target[1] - u.y
            u.x, u.y = target
            self._face(u, u.x + dx, u.y + dy)
            u.acted = False                                     # repositioning does not consume the attack
            self._emit("move", u.id, x=u.x, y=u.y)
        u.cd = cd
        if k == "reposition":
            u.status["_reposed"] = 1
        return True

    def end_unit(self, u: BUnit) -> None:
        u.done = True

    # ------------------------------------------------------------------ phases
    def end_phase(self) -> None:
        """Close the current side's phase: statuses and cooldowns tick, morale recovers, the other side begins."""
        side = self.phase
        for u in self.side_units(side):
            u.cd = max(0, u.cd - 1)
            for s in list(u.status):
                if s.startswith("_"):
                    del u.status[s]
                    continue
                u.status[s] -= 1
                if u.status[s] <= 0:
                    del u.status[s]
            if not u.took_damage:
                u.morale = min(u.maxmorale, u.morale + 3.0)
            for b in self.side_units(side):
                if b.role == "banner" and b.id != u.id and cheb(b.x, b.y, u.x, u.y) <= 3:
                    u.morale = min(u.maxmorale, u.morale + 2.0)
                    break
            u.took_damage = False
        self._check_rout()
        self.phase = 1 - side
        if self.phase == ATTACKER:
            self.round += 1
        for u in self.units:
            if u.side == self.phase:
                u.moved = 0
                u.acted = False
                u.done = False
                u.straight = 0
                if self.has_status(u, "stagger"):
                    u.acted = True
        self._finish_if_over()

    def _finish_if_over(self) -> None:
        a, d = self.side_units(ATTACKER), self.side_units(DEFENDER)
        win = None
        if not a and not d:
            win = DEFENDER
        elif not a:
            win = DEFENDER
        elif not d:
            win = ATTACKER
        elif self.round > ROUND_LIMIT:
            win = DEFENDER                                      # the attacker failed to break the line in time
        if win is not None and self.result is None:
            self.result = self._summary(win)

    @property
    def over(self) -> bool:
        return self.result is not None

    def check_over(self) -> bool:
        self._finish_if_over()
        return self.over

    def _summary(self, winner: int) -> dict:
        out = {"winner": winner, "rounds": self.round, "units": {}}
        for u in self.units:
            if u.uid < 0:
                continue
            out["units"][u.uid] = {"side": u.side, "hp": max(0.0, u.hp), "dead": not u.alive, "routed": u.routed,
                                   "kills": u.kills, "dealt": round(u.dealt, 1)}
        out["losses"] = {s: sum(1 for u in self.units if u.side == s and not u.alive) for s in (0, 1)}
        out["hp_left"] = {s: sum(max(0.0, u.hp) for u in self.units if u.side == s) for s in (0, 1)}
        out["hp_start"] = dict(self.start_hp)
        return out

    def state_hash(self) -> str:
        import hashlib
        s = "|".join(f"{u.id}:{u.x},{u.y},{u.hp:.2f},{u.morale:.1f},{int(u.alive)},{int(u.routed)}" for u in self.units)
        return hashlib.sha256(f"{self.round}{self.phase}{s}".encode()).hexdigest()[:16]


# ------------------------------------------------------------------------------------------------------ AI
class BattleAI:
    """Plays one side with utility scoring over (tile, action) pairs.  It sees only what the rules allow a player
    to see (positions and stats are public in battle) and acts through the same API as the human."""

    def __init__(self, battle: Battle, side: int, aggression: float = 0.5, caution: float = 0.5, rng: Rng | None = None):
        self.b = battle
        self.side = side
        self.aggr = aggression
        self.caut = caution
        self.rng = rng or Rng(7)
        self._eatk: dict[int, float] = {}

    def phase_order(self) -> list[BUnit]:
        """Units of this side in the order they will act (siege and cavalry first, supports last)."""
        b = self.b
        mine = b.side_units(self.side)
        self._eatk = {e.id: b.effective_atk(e) for e in b.enemies_of(mine[0])} if mine else {}
        return sorted(mine, key=lambda u: ({"siege": 0, "cavalry": 1, "skirmisher": 1, "infantry": 2, "pike": 2, "archer": 3,
                                            "banner": 4, "healer": 5}.get(u.role, 3), u.id))

    def play_phase(self) -> None:
        b = self.b
        if b.phase != self.side or b.over:
            return
        for u in self.phase_order():
            if not u.active or b.over:
                continue
            self.act(u)
        b.end_phase()

    # -------------------------------------------------------------------------------- scoring
    def act(self, u: BUnit) -> None:
        b = self.b
        best, best_score = None, -1e9
        reach = b.reachable(u)
        for (x, y), cost in reach.items():
            for kind, tgt, mult, ab in self._options(u, x, y):
                s = self._score(u, x, y, cost, kind, tgt, mult, ab)
                if s > best_score:
                    best, best_score = (x, y, kind, tgt, ab), s
        if best is None:
            return
        x, y, kind, tgt, ab = best
        if (x, y) != (u.x, u.y):
            b.move(u, x, y)
        if kind == "attack":
            if ab:
                b.use_ability(u, tgt)
            else:
                b.attack(u, tgt)
        elif kind == "wall":
            b.attack_wall(u, tgt)
        elif kind == "ability":
            b.use_ability(u, tgt)
        if "_skirmish" in u.status and u.active:
            self._skirmish_retreat(u)
        b.end_unit(u)

    def _options(self, u: BUnit, x: int, y: int):
        b = self.b
        yield "move", None, 1.0, False
        probe = BUnit(**{**u.__dict__, "x": x, "y": y})
        run = u.straight
        if (x, y) != (u.x, u.y):
            dx, dy = x - u.x, y - u.y
            n = max(abs(dx), abs(dy))
            run = n if (dx == 0 or dy == 0 or abs(dx) == abs(dy)) else 0
        probe.straight = run
        # plain attacks
        saved = (u.x, u.y)
        u.x, u.y = x, y
        try:
            for t in b.targets(u):
                yield "attack", t, 1.0, False
            for w in b.wall_targets(u):
                yield "wall", w, 1.0, False
            if u.ability and u.cd <= 0 and not b.has_status(u, "stagger"):
                for t in b.ability_targets(u):
                    if u.ability["kind"] in ("empowered_attack", "splash_attack", "heal", "purge"):
                        yield "attack" if u.ability["kind"] in ("empowered_attack", "splash_attack") else "ability", t, \
                            float(u.ability.get("mult", 1.0)), True
                    elif u.ability["kind"] != "reposition":
                        yield "ability", t, 1.0, True
        finally:
            u.x, u.y = saved

    def _score(self, u: BUnit, x: int, y: int, cost: int, kind: str, tgt, mult: float, ab: bool) -> float:
        b = self.b
        foes = b.enemies_of(u)
        friends = [a for a in b.side_units(u.side) if a.id != u.id]
        s = 0.0
        saved = (u.x, u.y)
        if kind == "attack":
            dmg = b.damage_estimate(u, tgt, mult, from_xy=(x, y), charge=_run_to(u, x, y))
            if ab and u.ability.get("splash"):
                dmg *= 1 + float(u.ability["splash"]) * sum(1 for e in foes if e.id != tgt.id and cheb(e.x, e.y, tgt.x, tgt.y) == 1) * 0.6
            frac = min(dmg, tgt.hp) / tgt.maxhp
            s += 10 * frac + (6 if dmg >= tgt.hp else 0)
            s += {"healer": 2.5, "banner": 2.0, "siege": 2.0, "archer": 1.2}.get(tgt.role, 0.0) * min(1.0, frac * 2)
            if b.facing_factor(BUnit(**{**u.__dict__, "x": x, "y": y}), tgt) > 1.2:
                s += 1.5
            s += 1.0 * self.aggr
            if ab:
                s += 0.5
        elif kind == "wall":
            s += 5.0 if u.role == "siege" else 0.0
        elif kind == "ability":
            s += self._support_value(u, tgt)
        else:
            s += self._approach_value(u, x, y, foes, friends)
        # safety: what the enemy could do to this tile next phase
        s -= self._exposure(u, x, y, foes) * (0.35 + 0.5 * self.caut) * (1.3 if u.role in ("archer", "healer", "banner", "siege") else 0.7)
        # terrain
        t = b.tiles[y][x]
        s += {FOREST: 0.6, HILL: 0.7, MARSH: -0.6}.get(t, 0.0) * (1.4 if u.range > 1 else 1.0)
        # supports hug the line
        if u.role in ("healer", "banner") and friends:
            near = min(cheb(x, y, a.x, a.y) for a in friends)
            s -= 0.5 * max(0, near - 2)
        # ranged keep their distance
        if u.range > 1 and u.role != "siege" and foes:
            close = min(cheb(x, y, e.x, e.y) for e in foes)
            if close <= 1:
                s -= 2.0
        s -= 0.04 * cost
        return s

    def _support_value(self, u: BUnit, tgt) -> float:
        k = u.ability["kind"]
        if k == "heal":
            return 8.0 * min(1.0, (tgt.maxhp - tgt.hp) / max(1.0, float(u.ability.get("amount", 12)))) * (1.2 if tgt.role != "siege" else 0.8)
        if k == "purge":
            return 5.0
        if k == "rally":
            low = sum(1 for a in self.b.side_units(u.side) if cheb(a.x, a.y, u.x, u.y) <= int(u.ability.get("radius", 3)) and a.morale < a.maxmorale * 0.7)
            return 1.0 + 2.0 * low
        if k == "aura_buff":
            n = sum(1 for a in self.b.side_units(u.side) if cheb(a.x, a.y, u.x, u.y) <= int(u.ability.get("radius", 2)))
            enemy_near = any(cheb(e.x, e.y, u.x, u.y) <= 4 for e in self.b.enemies_of(u))
            return (0.6 * n) if enemy_near else 0.0
        if k == "self_buff":
            return 1.5 if any(cheb(e.x, e.y, u.x, u.y) <= 3 for e in self.b.enemies_of(u)) else 0.0
        return 0.0

    def _approach_value(self, u: BUnit, x: int, y: int, foes: list[BUnit], friends: list[BUnit]) -> float:
        if not foes:
            return 0.0
        near = min(foes, key=lambda e: cheb(x, y, e.x, e.y) * 10 + abs(e.y - y))
        d = cheb(x, y, near.x, near.y)
        want = max(1, u.range - 1) if u.range > 1 else 1
        if u.role == "pike" and self.caut > 0.35:
            # hold the line when the enemy cavalry is close; otherwise advance with the group
            if any(e.role == "cavalry" and cheb(e.x, e.y, u.x, u.y) <= 5 for e in foes):
                return 1.5 if (x, y) == (u.x, u.y) else -0.5
        score = -abs(d - want) * (0.5 + self.aggr * 0.6)
        if friends and u.role not in ("cavalry", "skirmisher"):
            cx = sum(a.x for a in friends) / len(friends)
            cy = sum(a.y for a in friends) / len(friends)
            score -= 0.15 * math.hypot(x - cx, y - cy)
        if u.role == "cavalry":
            # prefer a long straight run onto a flank
            score += 0.3 * _run_to(u, x, y)
        if self.side == DEFENDER and self.b.fort and not self.aggr > 0.8:
            score -= 0.4 * abs(x - (GRID_W - 3))                 # sit behind the walls
        return score

    def _exposure(self, u: BUnit, x: int, y: int, foes: list[BUnit]) -> float:
        total = 0.0
        for e in foes:
            reach = e.move + e.range
            d = cheb(x, y, e.x, e.y)
            if d <= reach + (1 if e.role == "cavalry" else 0):
                dmg = self._eatk.get(e.id, e.atk) * 100.0 / (100.0 + 14.0 * self.b.effective_arm(u))
                total += min(dmg, u.hp) / u.maxhp * (1.0 if d - e.range <= e.move else 0.5)
        return total * 4.0

    def _skirmish_retreat(self, u: BUnit) -> None:
        b = self.b
        foes = b.enemies_of(u)
        if not foes:
            return
        reach = b.reachable(u, 2)
        best = max(reach, key=lambda p: (min(cheb(p[0], p[1], e.x, e.y) for e in foes), -reach[p], p))
        if best != (u.x, u.y):
            b.move(u, *best)
        u.status.pop("_skirmish", None)


def _run_to(u: BUnit, x: int, y: int) -> int:
    dx, dy = x - u.x, y - u.y
    n = max(abs(dx), abs(dy))
    if n == 0:
        return u.straight
    if dx == 0 or dy == 0 or abs(dx) == abs(dy):
        step = (int(math.copysign(1, dx)) if dx else 0, int(math.copysign(1, dy)) if dy else 0)
        return (u.straight + n) if step == u.facing else n
    return 0


def auto_resolve(battle: Battle, ai_att: BattleAI | None = None, ai_def: BattleAI | None = None, max_phases: int = 80) -> dict:
    """Let two AIs fight the battle to its end and return the result summary."""
    ai_att = ai_att or BattleAI(battle, ATTACKER, 0.7, 0.4, battle.rng.child("a"))
    ai_def = ai_def or BattleAI(battle, DEFENDER, 0.4, 0.6, battle.rng.child("d"))
    for _ in range(max_phases):
        if battle.over:
            break
        (ai_att if battle.phase == ATTACKER else ai_def).play_phase()
    if not battle.over:
        battle.result = battle._summary(DEFENDER)
    return battle.result
