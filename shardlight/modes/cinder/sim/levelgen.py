"""Seeded floor generation: room graph, tile layouts, enemy budgets and validation.

A floor is a tree of 8-10 rooms on a 4x3 grid.  The start room is on the left; the exit (stair or boss) is the room
farthest from it.  Dead ends become reward, forge, rest, secret or choir rooms; everything else is an arena.
Every layout is validated (all floor reachable from every door, spawn cells exist) and falls back to an open
room if an obstacle pattern would partition the arena.  Same (seed, floor) always gives the same floor.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ....core.rng import Rng
from ..defs import Library
from .perks import Modifiers

W_T, H_T = 28, 14
TILE = 16
SIDES = {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}
OPP = {"n": "s", "s": "n", "w": "e", "e": "w"}
GRID_W, GRID_H = 4, 3

DOOR_CELLS = {
    "n": [(c, 0) for c in range(12, 16)], "s": [(c, H_T - 1) for c in range(12, 16)],
    "w": [(0, r) for r in range(5, 9)], "e": [(W_T - 1, r) for r in range(5, 9)],
}
DOOR_INNER = {"n": (13.5, 2.0), "s": (13.5, H_T - 3.0), "w": (2.0, 6.5), "e": (W_T - 3.0, 6.5)}

PATTERNS = {
    "open": [],
    "pillars": [(7, 4, 2, 2), (19, 4, 2, 2), (7, 8, 2, 2), (19, 8, 2, 2)],
    "cross": [(12, 5, 4, 1), (12, 8, 4, 1), (13, 4, 2, 1), (13, 9, 2, 1)],
    "bars": [(5, 3, 7, 1), (16, 10, 7, 1)],
    "corners": [(3, 2, 3, 2), (22, 2, 3, 2), (3, 10, 3, 2), (22, 10, 3, 2)],
    "ring": [(9, 4, 1, 1), (18, 4, 1, 1), (9, 9, 1, 1), (18, 9, 1, 1), (13, 3, 2, 1), (13, 10, 2, 1)],
    "lanes": [(7, 5, 1, 4), (20, 5, 1, 4), (13, 6, 2, 2)],
    "braziers": [(6, 6, 1, 1), (21, 6, 1, 1), (13, 3, 1, 1), (14, 10, 1, 1)],
}
KIND_PATTERNS = {"arena": ["pillars", "cross", "bars", "corners", "ring", "lanes", "braziers", "open"],
                 "elite": ["pillars", "ring", "corners", "open", "lanes"],
                 "boss": ["open", "braziers"], "start": ["open", "braziers"],
                 "reward": ["open"], "forge": ["braziers"], "rest": ["open"], "secret": ["open"],
                 "choir": ["open"], "stair": ["pillars", "open"]}


@dataclass
class RoomSpec:
    id: int
    gx: int
    gy: int
    kind: str
    seed: int
    doors: dict[str, int] = field(default_factory=dict)      # side -> neighbour room id
    hidden: set[str] = field(default_factory=set)            # sides whose door is a cracked wall
    layout: list[str] = field(default_factory=list)
    waves: list[list[tuple[str, bool]]] = field(default_factory=list)
    boss: str = ""
    pattern: str = "open"
    cleared: bool = False
    visited: bool = False
    reward_taken: bool = False
    props: list[dict] = field(default_factory=list)
    vents: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class FloorPlan:
    floor: int
    seed: int
    rooms: dict[int, RoomSpec]
    start: int
    exit: int
    boss: str = ""
    problems: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------ layouts
def build_layout(pattern: str, doors: set[str]) -> list[str]:
    g = [["." for _ in range(W_T)] for _ in range(H_T)]
    for x in range(W_T):
        g[0][x] = g[H_T - 1][x] = "#"
    for y in range(H_T):
        g[y][0] = g[y][W_T - 1] = "#"
    for (x, y, w, h) in PATTERNS[pattern]:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                g[yy][xx] = "o" if (w == 1 and h == 1) else "#"
    for side in doors:                              # door openings and a free landing in front of each
        for (x, y) in DOOR_CELLS[side]:
            g[y][x] = "D"
        ix, iy = DOOR_INNER[side]
        for yy in range(int(iy) - 2, int(iy) + 3):
            for xx in range(int(ix) - 2, int(ix) + 3):
                if 0 < xx < W_T - 1 and 0 < yy < H_T - 1:
                    g[yy][xx] = "."
    return ["".join(r) for r in g]


def walkable(ch: str) -> bool:
    return ch in ".D"


def floor_cells(layout: list[str]) -> list[tuple[int, int]]:
    return [(x, y) for y, row in enumerate(layout) for x, ch in enumerate(row) if ch == "."]


def reachable(layout: list[str], start: tuple[int, int]) -> set[tuple[int, int]]:
    seen = {start}
    dq = deque([start])
    while dq:
        x, y = dq.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W_T and 0 <= ny < H_T and (nx, ny) not in seen and walkable(layout[ny][nx]):
                seen.add((nx, ny))
                dq.append((nx, ny))
    return seen


def layout_ok(layout: list[str], doors: set[str]) -> bool:
    cells = set(floor_cells(layout))
    if len(cells) < 220:
        return False
    anchor = None
    for side in (doors or {"w"}):
        ix, iy = DOOR_INNER[side]
        anchor = (int(ix), int(iy))
        break
    if anchor is None or layout[anchor[1]][anchor[0]] != ".":
        return False
    seen = reachable(layout, anchor)
    if not cells <= seen:
        return False
    for side in doors:
        ix, iy = DOOR_INNER[side]
        if (int(ix), int(iy)) not in seen:
            return False
    return True


def spawn_cells(layout: list[str], doors: set[str], min_door: float = 5.0) -> list[tuple[int, int]]:
    out = []
    for (x, y) in floor_cells(layout):
        if not (2 <= x <= W_T - 3 and 2 <= y <= H_T - 3):
            continue
        near = any((x - DOOR_INNER[s][0]) ** 2 + (y - DOOR_INNER[s][1]) ** 2 < min_door ** 2 for s in doors)
        if near:
            continue
        # keep spawn points off cells touching obstacles
        if any(layout[y + dy][x + dx] in "#o" for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            continue
        out.append((x, y))
    return out


# ------------------------------------------------------------------------------------------ waves
def plan_waves(rng: Rng, lib: Library, floor: int, mods: Modifiers, elite: bool, boss_room: bool = False) -> list:
    if boss_room:
        return []
    budget = 3.5 + floor * 1.8 + mods["extra_budget"] + (3 if elite else 0)
    waves_n = 2 if floor < 3 else 3
    if elite:
        waves_n = 2
    pool = [e for e in lib.enemies.values() if e.min_floor <= floor and e.weight > 0]
    waves: list[list[tuple[str, bool]]] = []
    for w in range(waves_n):
        b = budget / waves_n * (0.8 if w == 0 else 1.1)
        wave: list[tuple[str, bool]] = []
        guard = 0
        while b > 0.9 and guard < 40:
            guard += 1
            affordable = [e for e in pool if e.cost <= b + 0.01]
            if not affordable:
                break
            e = rng.weighted(affordable, [x.weight for x in affordable])
            is_elite = bool(e.elite) and floor >= e.elite.get("min_floor", 2) and rng.chance(
                0.08 + 0.04 * floor + mods["elite_chance"] + (0.3 if elite else 0))
            cost = e.elite["cost"] if is_elite else e.cost
            if cost > b + 0.01 and is_elite:
                is_elite = False
                cost = e.cost
            wave.append((e.id, is_elite))
            b -= cost
        if wave:
            waves.append(wave)
    return waves


# ------------------------------------------------------------------------------------------ floor graph
def generate_floor(lib: Library, seed: int, floor: int, mods: Modifiers, choir_unlocked: bool = False,
                   secrets: bool = True) -> FloorPlan:
    """Deterministic floor; retries with derived seeds until validation passes."""
    for attempt in range(25):
        plan = _try_floor(lib, Rng(seed).child("floor", floor, attempt), seed, floor, mods, choir_unlocked, secrets)
        problems = validate_floor(plan)
        if not problems:
            return plan
    plan.problems = problems
    return plan


def _try_floor(lib: Library, rng: Rng, seed: int, floor: int, mods: Modifiers, choir: bool, secrets: bool) -> FloorPlan:
    target = rng.randint(8, 10)
    start = (0, rng.randrange(GRID_H))
    cells = {start: 0}
    order = [start]
    adj: dict[int, set[int]] = {0: set()}
    side_of: dict[tuple[int, int], str] = {}
    frontier = [start]
    guard = 0
    while len(cells) < target and guard < 400:
        guard += 1
        cur = rng.pick(frontier) if rng.chance(0.55) else frontier[-1]
        sides = [s for s, (dx, dy) in SIDES.items()
                 if 0 <= cur[0] + dx < GRID_W and 0 <= cur[1] + dy < GRID_H and (cur[0] + dx, cur[1] + dy) not in cells]
        if not sides:
            frontier.remove(cur) if len(frontier) > 1 else None
            if not frontier:
                break
            continue
        s = rng.pick(sides)
        nxt = (cur[0] + SIDES[s][0], cur[1] + SIDES[s][1])
        cells[nxt] = len(cells)
        adj[cells[nxt]] = {cells[cur]}
        adj[cells[cur]].add(cells[nxt])
        side_of[(cells[cur], cells[nxt])] = s
        side_of[(cells[nxt], cells[cur])] = OPP[s]
        order.append(nxt)
        frontier.append(nxt)
    # BFS distances for the exit and for dead ends
    dist = {0: 0}
    dq = deque([0])
    while dq:
        a = dq.popleft()
        for b in adj[a]:
            if b not in dist:
                dist[b] = dist[a] + 1
                dq.append(b)
    exit_id = max(dist, key=lambda k: (dist[k], k))
    boss = {3: "slag_colossus", 5: "crown_of_embers", 7: "crown_of_embers"}.get(floor, "")
    leaves = [i for i in adj if len(adj[i]) == 1 and i not in (0, exit_id)]
    rng.shuffle(leaves)
    kinds: dict[int, str] = {0: "start", exit_id: "boss" if boss else "stair"}
    specials = ["reward", "forge"]
    if floor >= 2:
        specials.append("rest")
    if mods["fewer_rewards"] > 0 and "reward" in specials and len(leaves) > 2:
        specials.remove("reward")
    if choir and floor in (2, 4):
        specials.insert(0, "choir")
    if secrets:
        specials.append("secret")
    inner = [i for i in adj if i not in (0, exit_id) and i not in leaves]
    rng.shuffle(inner)
    if "secret" in specials and leaves:
        kinds[leaves.pop()] = "secret"
    for k in specials:
        if k == "secret":
            continue
        src = leaves if leaves else inner
        if src:
            kinds[src.pop()] = k
    rooms: dict[int, RoomSpec] = {}
    inv = {v: k for k, v in cells.items()}
    for rid in adj:
        gx, gy = inv[rid]
        kind = kinds.get(rid, "arena")
        if kind == "arena" and floor >= 2 and rid != 0 and rng.chance(0.22):
            kind = "elite"
        rooms[rid] = RoomSpec(rid, gx, gy, kind, rng.randrange(1 << 30), boss=boss if kind == "boss" else "")
    for (a, b), s in side_of.items():
        rooms[a].doors[s] = b
    for rid, spec in rooms.items():
        if spec.kind == "secret":
            (side,) = list(spec.doors)
            parent = spec.doors[side]
            rooms[parent].hidden.add(OPP[side])      # the *parent's* door toward the secret is hidden
        if spec.kind == "arena" and mods["fire_floor"] > 0:
            pass
    for spec in rooms.values():
        r = Rng(spec.seed)
        pats = KIND_PATTERNS.get(spec.kind, ["open"])
        door_set = set(spec.doors)
        for _ in range(8):
            pat = r.pick(pats)
            lay = build_layout(pat, door_set)
            if layout_ok(lay, door_set):
                spec.layout, spec.pattern = lay, pat
                break
        else:
            spec.layout, spec.pattern = build_layout("open", door_set), "open"
        if spec.kind in ("arena", "elite", "stair"):
            spec.waves = plan_waves(r, lib, floor, mods, spec.kind == "elite")
        if mods["fire_floor"] > 0 and spec.kind in ("arena", "elite"):
            free = spawn_cells(spec.layout, door_set, 6)
            r.shuffle(free)
            spec.vents = free[:3]
    return FloorPlan(floor, seed, rooms, 0, exit_id, boss)


def validate_floor(plan: FloorPlan) -> list[str]:
    problems: list[str] = []
    rooms = plan.rooms
    if not 6 <= len(rooms) <= 12:
        problems.append(f"room count {len(rooms)}")
    seen = {plan.start}
    dq = deque([plan.start])
    while dq:
        a = dq.popleft()
        for s, b in rooms[a].doors.items():
            if b not in seen and s not in rooms[a].hidden:
                seen.add(b)
                dq.append(b)
    if plan.exit not in seen:
        problems.append("exit unreachable without secrets")
    for rid, spec in rooms.items():
        if not layout_ok(spec.layout, set(spec.doors)):
            problems.append(f"room {rid} layout invalid")
        for s, b in spec.doors.items():
            if rooms[b].doors.get(OPP[s]) != rid:
                problems.append(f"door mismatch {rid}->{b}")
        if spec.kind in ("arena", "elite") and not spec.waves:
            problems.append(f"room {rid} has no enemies")
        if spec.kind in ("arena", "elite", "stair") and len(spawn_cells(spec.layout, set(spec.doors))) < 8:
            problems.append(f"room {rid} lacks spawn cells")
    if plan.boss and rooms[plan.exit].kind != "boss":
        problems.append("boss floor without boss room")
    if not plan.boss and rooms[plan.exit].kind != "stair":
        problems.append("missing stair")
    if sum(1 for s in rooms.values() if s.kind in ("reward", "forge", "rest", "secret", "choir")) < 1:
        problems.append("no special rooms")
    return problems
