"""Seeded generation of a night's building: BSP rooms from templates, two-wide corridors with doors, props, loot,
notes, story dressings and the night's objective chain - validated for solvability (every key, fuse, crank and
exit reachable in an order the player can actually follow) and regenerated deterministically if not.

Pure logic: no pygame.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from ...core.rng import Rng, derive_seed
from .catalog import Catalog
from .consts import DOOR, FLOOR, SURFACE_BY_NAME, VOID, WALL
from .props import HIDE_RULES, PROP_DEFS, footprint

MIN_LEAF_W, MIN_LEAF_H = 9, 7


@dataclass
class Room:
    id: int
    tid: str
    name: str
    role: str
    x: int
    y: int
    w: int
    h: int
    hall: bool = False
    surface: int = 0
    lamp: bool = False
    window: bool = False
    loot: float = 1.0
    tags: tuple = ()
    doors: list = field(default_factory=list)       # door ids

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def contains(self, c: tuple[int, int]) -> bool:
        return self.x <= c[0] < self.x + self.w and self.y <= c[1] < self.y + self.h

    def cells(self):
        return [(x, y) for y in range(self.y, self.y + self.h) for x in range(self.x, self.x + self.w)]


@dataclass
class Prop:
    kind: str
    cell: tuple[int, int]
    rot: bool = False
    room: int = -1
    contents: list = field(default_factory=list)        # [item_id, count]
    searched: bool = False
    note: str = ""
    state: dict = field(default_factory=dict)

    @property
    def cells(self) -> list[tuple[int, int]]:
        return footprint(self.kind, self.cell, self.rot)


@dataclass
class DoorDef:
    id: int
    cells: list[tuple[int, int]]
    vertical: bool                  # True: a doorway in a vertical wall (passage runs left-right)
    a: int                          # room ids joined
    b: int
    locks: list[str] = field(default_factory=list)       # key item ids required (all)
    gate: bool = False               # opens only when the winch is turned
    safe: bool = False               # door of a safe room: enemies never go through it


@dataclass
class Level:
    night: int
    seed: int
    w: int
    h: int
    grid: np.ndarray
    surface: np.ndarray
    rooms: list[Room]
    props: list[Prop]
    doors: list[DoorDef]
    start: tuple[int, int]
    safe_rooms: list[int]
    objective: dict
    lamps: list[tuple[int, int]]
    windows: list[tuple[int, int]]
    notes: list[tuple[str, tuple[int, int]]]
    stories: list[dict]
    items_floor: list[tuple[str, tuple[int, int], int]]        # (item, cell, count)
    enemies: list[str]
    problems: list[str] = field(default_factory=list)
    attempt: int = 0

    def room_of(self, c: tuple[int, int]) -> Room | None:
        for r in self.rooms:
            if r.contains(c):
                return r
        return None

    def room_by_role(self, role: str) -> Room | None:
        return next((r for r in self.rooms if r.role == role), None)


# ----------------------------------------------------------------------------------------------- build
def generate(night: int, seed: int, cat: Catalog) -> Level:
    """A validated level for ``night`` (1-based) and ``seed``; deterministic."""
    last = None
    for attempt in range(12):
        lv = _build(night, seed, cat, attempt)
        lv.problems = validate(lv, cat)
        lv.attempt = attempt
        last = lv
        if not lv.problems:
            return lv
    return last


class _Leaf:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.l = self.r = None
        self.room: Room | None = None

    def leaves(self):
        if self.l is None:
            return [self]
        return self.l.leaves() + self.r.leaves()


def _split(rng: Rng, leaf: _Leaf, target: int) -> None:
    leaves = [leaf]
    while len(leaves) < target:
        cand = [n for n in leaves if n.w >= MIN_LEAF_W * 2 or n.h >= MIN_LEAF_H * 2]
        if not cand:
            break
        n = max(cand, key=lambda m: m.w * m.h)
        can_v = n.w >= MIN_LEAF_W * 2
        can_h = n.h >= MIN_LEAF_H * 2
        vertical = can_v and (not can_h or n.w / n.h > 1.15 or rng.random() < 0.35)
        if vertical:
            cut = rng.randint(MIN_LEAF_W, n.w - MIN_LEAF_W)
            n.l, n.r = _Leaf(n.x, n.y, cut, n.h), _Leaf(n.x + cut, n.y, n.w - cut, n.h)
        else:
            cut = rng.randint(MIN_LEAF_H, n.h - MIN_LEAF_H)
            n.l, n.r = _Leaf(n.x, n.y, n.w, cut), _Leaf(n.x, n.y + cut, n.w, n.h - cut)
        leaves.remove(n)
        leaves += [n.l, n.r]


def _build(night: int, seed: int, cat: Catalog, attempt: int) -> Level:
    nd = cat.night(night)
    rng = Rng(derive_seed(seed, "umbra", night, attempt))
    W, H = int(nd["size"][0]), int(nd["size"][1])
    style = nd["style"]
    grid = np.full((H, W), WALL, dtype=np.int8)
    surface = np.zeros((H, W), dtype=np.int8)
    root = _Leaf(1, 1, W - 2, H - 2)
    _split(rng, root, 8 + (W * H) // 170)
    leaves = root.leaves()
    templates = [t for t in cat.rooms() if style in t.get("tags", []) and t["id"] not in ("corridor", "gallery", "tunnel")]
    by_id = {t["id"]: t for t in cat.rooms()}
    hall_tid = {"infirmary": "corridor", "manor": "gallery", "cellar": "tunnel"}[style]

    # ---- assign templates: required roles first (biggest leaves for the big ones)
    need = ["safe_room"] * int(nd.get("safe_rooms", 1))
    if nd["objective"] == "power":
        need.append("generator_room")
    elif nd["objective"] == "keys":
        need.append("archive_room")
    else:
        need += ["gate_hall", "stair_landing"]
    if night >= 2:
        need.append("clock_room")
    order = sorted(leaves, key=lambda n: -(n.w * n.h))
    assigned: dict[int, str] = {}
    big_first = sorted(need, key=lambda t: -by_id[t].get("min_w", 4) * by_id[t].get("min_h", 4))
    free = list(range(len(order)))
    for tid in big_first:
        t = by_id[tid]
        fits = [i for i in free if order[i].w - 2 >= t["min_w"] and order[i].h - 2 >= t["min_h"]]
        if not fits:
            continue
        pick = fits[0] if tid not in ("safe_room", "stair_landing") else fits[-1]
        assigned[pick] = tid
        free.remove(pick)
    for i in free:
        n = order[i]
        cand = [t for t in templates if t.get("role") in (None, "any") and n.w - 2 >= t["min_w"] and n.h - 2 >= t["min_h"] and not t.get("unique")]
        if not cand:
            cand = [by_id.get("linen_store") or templates[0]]
        assigned[i] = rng.weighted([t["id"] for t in cand], [t.get("weight", 1.0) for t in cand])

    rooms: list[Room] = []
    for i, n in enumerate(order):
        tid = assigned.get(i)
        if tid is None:
            continue
        t = by_id[tid]
        rw = rng.randint(t["min_w"], max(t["min_w"], min(t["max_w"], n.w - 2)))
        rh = rng.randint(t["min_h"], max(t["min_h"], min(t["max_h"], n.h - 2)))
        rx = rng.randint(n.x + 1, n.x + n.w - rw - 1) if n.w - rw - 2 >= 0 else n.x + 1
        ry = rng.randint(n.y + 1, n.y + n.h - rh - 1) if n.h - rh - 2 >= 0 else n.y + 1
        r = Room(len(rooms), tid, t["name"], t.get("role") or "any", rx, ry, rw, rh, False,
                 SURFACE_BY_NAME[t.get("surface", "wood")], rng.random() < t.get("lamp", 0.3), rng.random() < t.get("window", 0.0),
                 float(t.get("loot", 1.0)), tuple(t.get("tags", ())))
        n.room = r
        rooms.append(r)
        grid[ry:ry + rh, rx:rx + rw] = FLOOR
        surface[ry:ry + rh, rx:rx + rw] = r.surface

    # ---- connect siblings with 2-wide corridors, then add loops
    hall_t = by_id[hall_tid]
    hall_surface = SURFACE_BY_NAME[hall_t.get("surface", "tile")]
    doors: list[DoorDef] = []
    halls: list[Room] = []
    connected: set[tuple[int, int]] = set()

    def rooms_of(node: _Leaf) -> list[Room]:
        return [l.room for l in node.leaves() if l.room]

    def connect(a: Room, b: Room, locked: bool = False) -> None:
        if (a.id, b.id) in connected or (b.id, a.id) in connected or a.id == b.id:
            return
        connected.add((a.id, b.id))
        _corridor(rng, grid, surface, rooms, halls, doors, a, b, hall_surface, hall_t, hall_tid)

    def walk(node: _Leaf) -> None:
        if node.l is None:
            return
        walk(node.l)
        walk(node.r)
        ra, rb = rooms_of(node.l), rooms_of(node.r)
        if not ra or not rb:
            return
        best = min(((a, b) for a in ra for b in rb), key=lambda p: abs(p[0].center[0] - p[1].center[0]) + abs(p[0].center[1] - p[1].center[1]))
        connect(*best)

    walk(root)
    # loops: connect a few near pairs that are not yet linked
    pairs = sorted(((a, b) for a in rooms for b in rooms if a.id < b.id and (a.id, b.id) not in connected),
                   key=lambda p: abs(p[0].center[0] - p[1].center[0]) + abs(p[0].center[1] - p[1].center[1]))
    loops = 0
    for a, b in pairs:
        if loops >= 2 + len(rooms) // 6:
            break
        if abs(a.center[0] - b.center[0]) + abs(a.center[1] - b.center[1]) > 34:
            continue
        before = len(doors)
        connect(a, b)
        if len(doors) > before:
            loops += 1
    all_rooms = rooms + halls
    for i, r in enumerate(all_rooms):
        r.id = i
    # mark door cells
    for d in doors:
        for c in d.cells:
            grid[c[1], c[0]] = DOOR
    # re-index door room ids after hall renumbering
    _reindex_doors(doors, all_rooms)

    safe = [r.id for r in all_rooms if r.role == "safe"]
    for d in doors:
        if d.a in safe or d.b in safe:
            d.safe = True
    lv = Level(night, seed, W, H, grid, surface, all_rooms, [], doors, (0, 0), safe, {}, [], [], [], [], [], list(nd["enemies"]))
    _place_props(rng, lv, cat, by_id)
    _lights(rng, lv)
    start_room = lv.rooms[safe[0]] if safe else lv.rooms[0]
    lv.start = _free_cell_in(lv, start_room, rng, prefer_center=True)
    _objectives(rng, lv, cat, nd)
    _stories_and_notes(rng, lv, cat, night)
    _scatter_supplies(rng, lv, cat, nd)
    return lv


def _reindex_doors(doors: list[DoorDef], rooms: list[Room]) -> None:
    for d in doors:
        d.cells = [tuple(c) for c in d.cells]
    for r in rooms:
        r.doors = []
    for d in doors:
        for r in rooms:
            if r.id in (d.a, d.b):
                r.doors.append(d.id)


def _corridor(rng, grid, surface, rooms, halls, doors, a: Room, b: Room, hall_surface, hall_t, hall_tid) -> None:
    """Carve a 2-wide L-shaped corridor between rooms ``a`` and ``b``; place doors where it meets each room."""
    ax, ay = a.center
    bx, by = b.center
    horizontal_first = rng.random() < 0.5
    pts = [(ax, ay), (bx, ay) if horizontal_first else (ax, by), (bx, by)]
    rects = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 == x1 and y0 == y1:
            continue
        if y0 == y1:
            lo, hi = sorted((x0, x1))
            rects.append((lo, y0, hi - lo + 1, 2, False))          # horizontal run, 2 tall
        else:
            lo, hi = sorted((y0, y1))
            rects.append((x0, lo, 2, hi - lo + 1, True))
    H, W = grid.shape
    carved: list[tuple[int, int, int, int]] = []
    for x, y, w, h, vert in rects:
        x2, y2 = min(W - 2, x + w), min(H - 2, y + h)
        x, y = max(1, x), max(1, y)
        for yy in range(y, y2):
            for xx in range(x, x2):
                if grid[yy, xx] == WALL:
                    grid[yy, xx] = FLOOR
                    surface[yy, xx] = hall_surface
        carved.append((x, y, x2 - x, y2 - y))
    # hall pseudo-rooms for prop placement: only long enough runs
    for x, y, w, h in carved:
        if max(w, h) >= 5 and min(w, h) >= 2:
            halls.append(Room(-1, hall_tid, hall_t["name"], "hall", x, y, w, h, True, hall_surface, rng.random() < hall_t.get("lamp", 0.3),
                              rng.random() < hall_t.get("window", 0.0), 0.5, tuple(hall_t.get("tags", ()))))
    # doors: cells of the room's wall ring that the corridor opened
    for room in (a, b):
        ring = []
        for x in range(room.x - 1, room.x + room.w + 1):
            ring += [(x, room.y - 1, "top"), (x, room.y + room.h, "bottom")]
        for y in range(room.y, room.y + room.h):
            ring += [(room.x - 1, y, "left"), (room.x + room.w, y, "right")]
        opened = [(x, y, side) for x, y, side in ring if 0 < x < W - 1 and 0 < y < H - 1 and grid[y, x] == FLOOR
                  and not any(r2.contains((x, y)) for r2 in rooms if r2 is not room and r2.id >= 0 and False)]
        # group the ring cells by side and adjacency
        groups: dict[str, list[tuple[int, int]]] = {}
        for x, y, side in opened:
            groups.setdefault(side, []).append((x, y))
        for side, cells in groups.items():
            cells.sort()
            run = [cells[0]]
            for c in cells[1:]:
                if (side in ("top", "bottom") and c[1] == run[-1][1] and c[0] == run[-1][0] + 1) or \
                        (side in ("left", "right") and c[0] == run[-1][0] and c[1] == run[-1][1] + 1):
                    run.append(c)
                else:
                    _add_door(doors, run, side, a, b, room)
                    run = [c]
            _add_door(doors, run, side, a, b, room)


def _add_door(doors, run, side, a: Room, b: Room, room: Room) -> None:
    if not run or len(run) > 3:
        return
    # only place a door at the boundary where the corridor really enters this room (not one already doored)
    if any(set(run) & set(map(tuple, d.cells)) for d in doors):
        return
    other = b if room is a else a
    doors.append(DoorDef(len(doors), list(run), side in ("left", "right"), room.id, other.id))


# ----------------------------------------------------------------------------------------------- props
def _walkable(lv: Level, c) -> bool:
    x, y = c
    return 0 <= x < lv.w and 0 <= y < lv.h and lv.grid[y, x] in (FLOOR, DOOR)


def _blocked_cells(lv: Level) -> set[tuple[int, int]]:
    s = set()
    for p in lv.props:
        if PROP_DEFS[p.kind].solid:
            s.update(p.cells)
    return s


def _door_clear(lv: Level) -> set[tuple[int, int]]:
    s = set()
    for d in lv.doors:
        for (x, y) in d.cells:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    s.add((x + dx, y + dy))
    return s


def _zone_cells(room: Room, zone: str, lv: Level) -> list[tuple[int, int]]:
    out = []
    for (x, y) in room.cells():
        edge = x in (room.x, room.x + room.w - 1) or y in (room.y, room.y + room.h - 1)
        corner = x in (room.x, room.x + room.w - 1) and y in (room.y, room.y + room.h - 1)
        inner = room.x + 2 <= x < room.x + room.w - 2 and room.y + 2 <= y < room.y + room.h - 2
        if zone == "wall" and edge and not corner:
            out.append((x, y))
        elif zone == "corner" and corner:
            out.append((x, y))
        elif zone == "center" and (inner or (room.w <= 4 or room.h <= 4) and not edge):
            out.append((x, y))
        elif zone == "any":
            out.append((x, y))
    return out


def _place_props(rng: Rng, lv: Level, cat: Catalog, by_id: dict) -> None:
    clear = _door_clear(lv)
    occupied: set[tuple[int, int]] = set()
    for room in lv.rooms:
        t = by_id.get(room.tid)
        if not t:
            continue
        for spec in t.get("props", []):
            n = rng.randint(spec["count"][0], spec["count"][1])
            for _ in range(n):
                cells = _zone_cells(room, spec.get("zone", "wall"), lv)
                cells = rng.shuffled(cells)
                for c in cells[:24]:
                    rot = rng.random() < 0.5
                    fp = footprint(spec["prop"], c, rot)
                    d = PROP_DEFS[spec["prop"]]
                    if not all(room.contains(q) and q not in occupied and (not d.solid or q not in clear) for q in fp):
                        continue
                    if d.solid and _would_isolate(lv, occupied, fp, room):
                        continue
                    lv.props.append(Prop(spec["prop"], c, rot, room.id))
                    if d.solid:
                        occupied.update(fp)
                    else:
                        occupied.update(q for q in fp if False)
                    break


def _would_isolate(lv: Level, occupied: set, fp: list, room: Room) -> bool:
    """True if blocking ``fp`` would cut the room's floor into pieces or wall off a door."""
    blocked = set(occupied) | set(fp)
    cells = [c for c in room.cells() if c not in blocked]
    if not cells:
        return True
    seen = {cells[0]}
    dq = deque([cells[0]])
    cs = set(cells)
    while dq:
        x, y = dq.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in cs and n not in seen:
                seen.add(n)
                dq.append(n)
    if len(seen) != len(cs):
        return True
    for d in lv.doors:
        if room.id in (d.a, d.b):
            ins = []
            for (x, y) in d.cells:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    q = (x + dx, y + dy)
                    if q in cs:
                        ins.append(q)
            if ins and not any(q in seen for q in ins):
                return True
    return False


def _lights(rng: Rng, lv: Level) -> None:
    for r in lv.rooms:
        if r.lamp:
            cells = _zone_cells(r, "wall", lv)
            cells = [c for c in cells if c not in _door_clear(lv)]
            if cells:
                lv.lamps.append(rng.pick(cells))
        if r.window and not r.hall:
            cells = [c for c in _zone_cells(r, "wall", lv) if c[1] == r.y]
            if cells:
                lv.windows.append(rng.pick(cells))
    for r in lv.rooms:
        if r.role == "safe":
            c = r.center
            lv.lamps.append((r.x + 1, r.y + 1))


def _free_cell_in(lv: Level, room: Room, rng: Rng, prefer_center: bool = False) -> tuple[int, int]:
    blocked = _blocked_cells(lv)
    cells = [c for c in room.cells() if c not in blocked and all(c != q for d in lv.doors for q in d.cells)]
    if prefer_center:
        cx, cy = room.center
        cells.sort(key=lambda c: abs(c[0] - cx) + abs(c[1] - cy))
        return cells[0]
    return rng.pick(cells)


# --------------------------------------------------------------------------------------------- objectives
def _non_safe_rooms(lv: Level, far_from: Room | None = None) -> list[Room]:
    out = [r for r in lv.rooms if not r.hall and r.role in ("any",) and r.tid not in ("safe_room",)]
    if far_from is not None:
        cx, cy = far_from.center
        out.sort(key=lambda r: -(abs(r.center[0] - cx) + abs(r.center[1] - cy)))
    return out


def _put_item(rng: Rng, lv: Level, room: Room, item: str, count: int = 1, prefer_container: bool = True) -> None:
    conts = [p for p in lv.props if p.room == room.id and PROP_DEFS[p.kind].container]
    if conts and prefer_container and rng.random() < 0.8:
        p = rng.pick(conts)
        p.contents.append([item, count])
        return
    lv.items_floor.append((item, _free_cell_in(lv, room, rng), count))


def _reachable_rooms(lv: Level, closed_door_ids: set[int]) -> list[Room]:
    """Real rooms the player can reach from the start with the given doors shut."""
    reach = _bfs(walkable_grid(lv, closed_door_ids), lv.start)
    return [r for r in lv.rooms if not r.hall and any(c in reach for c in r.cells())]


def _lock_doors_of(lv: Level, room: Room, keys: list[str]) -> set[int]:
    ids = set()
    for d in lv.doors:
        if room.id in (d.a, d.b):
            d.locks = list(keys)
            ids.add(d.id)
    return ids


def _objectives(rng: Rng, lv: Level, cat: Catalog, nd: dict) -> None:
    obj = nd["objective"]
    safe = lv.rooms[lv.safe_rooms[0]] if lv.safe_rooms else lv.rooms[0]
    o: dict = {"type": obj, "safe": safe.id}

    def pool(closed: set[int], exclude: set[int]) -> list[Room]:
        rs = [r for r in _reachable_rooms(lv, closed) if r.role == "any" and r.id not in exclude and r.tid != "safe_room"]
        cx, cy = safe.center
        rs.sort(key=lambda r: -(abs(r.center[0] - cx) + abs(r.center[1] - cy)))
        return rs

    if obj == "power":
        gen = lv.room_by_role("generator")
        o["generator_room"] = gen.id if gen else -1
        closed: set[int] = set()
        if gen:
            _prop_at_free(rng, lv, gen, "generator", False)
            _prop_at_free(rng, lv, gen, "fuse_box", True)
            _prop_at_free(rng, lv, gen, "fuse_box", True)
            _prop_at_free(rng, lv, gen, "lever", True)
            closed = _lock_doors_of(lv, gen, ["boiler_key"])
        rooms = pool(closed, {gen.id} if gen else set())
        picks = rng.shuffled(rooms)
        if len(picks) < 3:
            picks = picks * 3
        for i in range(int(nd.get("fuses", 2))):
            _put_item(rng, lv, picks[i], "fuse", 1)
        _put_item(rng, lv, picks[int(nd.get("fuses", 2))], "boiler_key", 1)
        o["fuses"] = int(nd.get("fuses", 2))
    elif obj == "keys":
        arch = lv.room_by_role("archive")
        o["archive_room"] = arch.id if arch else -1
        keys = ["brass_key", "bone_key", "iron_key"][:int(nd.get("keys", 3))]
        closed = _lock_doors_of(lv, arch, keys) if arch else set()
        picks = rng.shuffled(pool(closed, {arch.id} if arch else set()))
        if len(picks) < len(keys):
            picks = picks * len(keys)
        for i, k in enumerate(keys):
            _put_item(rng, lv, picks[i], k, 1)
        if arch:
            desk = next((p for p in lv.props if p.room == arch.id and p.kind == "desk"), None)
            if desk:
                desk.contents.append(["cellar_key", 1])
            else:
                lv.items_floor.append(("cellar_key", _free_cell_in(lv, arch, rng, True), 1))
    else:
        gate = lv.room_by_role("gate")
        exit_ = lv.room_by_role("exit")
        o["gate_room"] = gate.id if gate else -1
        o["exit_room"] = exit_.id if exit_ else -1
        closed = set()
        if gate:
            _prop_at_free(rng, lv, gate, "winch", False)
        if exit_:
            for d in lv.doors:
                if exit_.id in (d.a, d.b):
                    d.gate = True
                    closed.add(d.id)
        # a side room holds the wheel behind a latch key
        cands = pool(closed, {gate.id if gate else -1})
        picks = rng.shuffled(cands)
        wheel_room = next((r for r in picks if len(r.doors) <= 2), picks[0])
        wclosed = closed | _lock_doors_of(lv, wheel_room, ["crank_room_key"])
        rest = [r for r in pool(wclosed, {wheel_room.id, gate.id if gate else -1})]
        rest = rng.shuffled(rest)
        if len(rest) < 2:
            rest = rest * 2
        _put_item(rng, lv, rest[0], "crank", 1)
        _put_item(rng, lv, rest[1], "crank_room_key", 1)
        _put_item(rng, lv, wheel_room, "gate_wheel", 1)
    lv.objective = o


def _prop_at_free(rng: Rng, lv: Level, room: Room, kind: str, wall: bool) -> None:
    occupied = _blocked_cells(lv)
    clear = _door_clear(lv)
    zone = "wall" if wall else "center"
    cells = _zone_cells(room, zone, lv) or room.cells()
    for c in rng.shuffled(cells):
        fp = footprint(kind, c, False)
        if all(room.contains(q) and q not in occupied and q not in clear for q in fp):
            lv.props.append(Prop(kind, c, False, room.id))
            return
    c = _free_cell_in(lv, room, rng)
    lv.props.append(Prop(kind, c, False, room.id))


# --------------------------------------------------------------------------------------- notes and stories
def _stories_and_notes(rng: Rng, lv: Level, cat: Catalog, night: int) -> None:
    placed_notes: set[str] = set()
    stories = [s for s in cat.stories() if night in s.get("nights", [night])]
    for s in stories:
        if s["id"] == "tally_by_safe_room" or s["kind"] == "stopped_clock":
            continue
        cands = [r for r in lv.rooms if r.tid in s.get("rooms", []) or any(t in s.get("rooms", []) for t in r.tags)]
        if not cands or rng.random() > min(1.0, s.get("weight", 1) / 3.0):
            continue
        room = rng.pick(cands)
        _dress(rng, lv, room, s)
        if s.get("note"):
            placed_notes.add(s["note"])
            lv.stories.append({"id": s["id"], "room": room.id, "note": s["note"]})
    for r in lv.rooms:
        if r.role == "safe":
            s = next((x for x in cat.stories() if x["id"] == "tally_by_safe_room"), None)
            if s:
                _dress(rng, lv, r, s)
                lv.stories.append({"id": s["id"], "room": r.id, "note": s.get("note", "")})
        if r.role == "clock":
            s = next((x for x in cat.stories() if x["id"] == "the_stopped_clock"), None)
            if s:
                _prop_at_free(rng, lv, r, "clock", True)
                lv.stories.append({"id": s["id"], "room": r.id, "note": s.get("note", ""), "relic": s["params"].get("relic", "stopped_clock")})
    # diary pages: spread series so earlier pages appear in rooms matching their tags
    notes = [n for n in cat.notes() if night in n.get("nights", [night]) and n["id"] not in placed_notes]
    count = 0
    for n in rng.shuffled(notes):
        if count >= 7 + night:
            break
        rooms = [r for r in lv.rooms if not r.hall and (not n.get("tags") or r.tid in n["tags"] or any(t in n["tags"] for t in r.tags))]
        if not rooms:
            continue
        room = rng.pick(rooms)
        cell = _free_cell_in(lv, room, rng)
        kind = {"note": "papers", "log": "papers", "sign": "sign", "drawing": "drawing"}.get(n.get("kind", "note"), "papers")
        lv.props.append(Prop(kind, cell, False, room.id, note=n["id"]))
        lv.notes.append((n["id"], cell))
        count += 1
    for sc in lv.stories:
        if sc.get("note"):
            room = lv.rooms[sc["room"]]
            cell = _free_cell_in(lv, room, rng)
            n = cat.note(sc["note"])
            kind = "drawing" if n and n.get("kind") == "drawing" else "papers"
            lv.props.append(Prop(kind, cell, False, room.id, note=sc["note"]))
            lv.notes.append((sc["note"], cell))


def _dress(rng: Rng, lv: Level, room: Room, story: dict) -> None:
    k = story["kind"]
    occupied = _blocked_cells(lv)
    clear = _door_clear(lv)

    def add(kind, zone="wall", n=1):
        for _ in range(n):
            for c in rng.shuffled(_zone_cells(room, zone, lv))[:20]:
                fp = footprint(kind, c, False)
                if all(room.contains(q) and q not in occupied and (not PROP_DEFS[kind].solid or q not in clear) for q in fp):
                    if PROP_DEFS[kind].solid and _would_isolate(lv, occupied, fp, room):
                        continue
                    lv.props.append(Prop(kind, c, False, room.id))
                    if PROP_DEFS[kind].solid:
                        occupied.update(fp)
                    break

    if k == "barricade_inside":
        add("barricade", "wall", 2)
        add("chair", "any", 1)
    elif k == "candle_room":
        add("candle", "center", 2)
        add("bloodstain", "center", 1)
    elif k == "dinner_table":
        add("candle", "center", 1)
    elif k == "wheelchair":
        add("wheelchair", "wall", 1)
    elif k == "covered_mirror":
        add("mirror", "wall", 1)
    elif k == "strapped_cot":
        add("cot", "wall", 1)
        add("bloodstain", "center", 1)
    elif k == "ransacked":
        add("bloodstain", "any", 1)
        room.loot = max(0.3, room.loot * 0.5)
    elif k == "chalk_tally":
        add("tally", "wall", 1)
    elif k == "child_drawing":
        add("drawing", "wall", 1)


# ----------------------------------------------------------------------------------------------- loot
def _scatter_supplies(rng: Rng, lv: Level, cat: Catalog, nd: dict) -> None:
    sup = nd.get("supplies", {})
    rooms = [r for r in lv.rooms if not r.hall and r.role != "safe"]
    weights = [max(0.05, r.loot) for r in rooms]
    for item, n in sup.items():
        if item not in cat.item_ids():
            continue
        for _ in range(int(n)):
            r = rng.weighted(rooms, weights)
            _put_item(rng, lv, r, item, 1)
    # a little something in the safe room so a restart is never hopeless
    for sid in lv.safe_rooms[:1]:
        safe = lv.rooms[sid]
        lv.items_floor.append(("matches", _free_cell_in(lv, safe, rng), 2))


# ------------------------------------------------------------------------------------------ validation
def walkable_grid(lv: Level, closed_doors: set[int] | None = None) -> np.ndarray:
    """Boolean grid of cells an actor may stand on (solid props block; ``closed_doors`` ids block)."""
    g = (lv.grid == FLOOR) | (lv.grid == DOOR)
    for p in lv.props:
        if PROP_DEFS[p.kind].solid:
            for (x, y) in p.cells:
                g[y, x] = False
    if closed_doors:
        for d in lv.doors:
            if d.id in closed_doors:
                for (x, y) in d.cells:
                    g[y, x] = False
    return g


def _bfs(g: np.ndarray, start: tuple[int, int]) -> set[tuple[int, int]]:
    seen = {start}
    dq = deque([start])
    H, W = g.shape
    while dq:
        x, y = dq.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and g[ny, nx] and (nx, ny) not in seen:
                seen.add((nx, ny))
                dq.append((nx, ny))
    return seen


def item_cells(lv: Level) -> list[tuple[str, tuple[int, int]]]:
    """Every collectible with the cell the player must reach to get it."""
    out = [(it, c) for it, c, n in lv.items_floor]
    for p in lv.props:
        for it, n in p.contents:
            out.append((it, p.cells[0]))
    return out


def solve_order(lv: Level, cat: Catalog) -> tuple[set[str], set[int]]:
    """Fixpoint reachability: grow the set of reachable cells, collected items and opened doors."""
    closed = {d.id for d in lv.doors if d.locks or d.gate}
    have: set[str] = set()
    items = item_cells(lv)
    while True:
        g = walkable_grid(lv, closed)
        # props are reached from an adjacent cell
        reach = _bfs(g, lv.start)
        got = set(have)
        for it, c in items:
            if c in reach or any((c[0] + dx, c[1] + dy) in reach for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                got.add(it)
        opened = {d.id for d in lv.doors if d.id in closed and all(k in got for k in d.locks) and not d.gate}
        if got == have and not opened:
            return have, closed
        have = got
        closed -= opened


def validate(lv: Level, cat: Catalog) -> list[str]:
    P: list[str] = []
    nd = cat.night(lv.night)
    if not lv.safe_rooms:
        P.append("no safe room")
    for role in ({"power": ["generator"], "keys": ["archive"], "escape": ["gate", "exit"]}[nd["objective"]]):
        if lv.room_by_role(role) is None:
            P.append(f"missing {role} room")
    if lv.night >= 2 and lv.room_by_role("clock") is None:
        P.append("missing clock room")
    if P:
        return P
    g = walkable_grid(lv)
    if not g[lv.start[1], lv.start[0]]:
        return ["start blocked"]
    full = _bfs(g, lv.start)
    for r in lv.rooms:
        if not r.hall and not any(c in full for c in r.cells()):
            P.append(f"room {r.name} unreachable")
    have, closed = solve_order(lv, cat)
    o = lv.objective
    need_items = {"power": ["fuse", "boiler_key"], "keys": ["brass_key", "bone_key", "iron_key", "cellar_key"], "escape": ["crank", "gate_wheel"]}[o["type"]]
    for it in need_items:
        if it not in have:
            P.append(f"{it} cannot be obtained")
    if closed - {d.id for d in lv.doors if d.gate}:
        P.append("a locked door can never be opened")
    n_fuse = sum(1 for it, c in item_cells(lv) if it == "fuse")
    if o["type"] == "power" and n_fuse < o.get("fuses", 2):
        P.append("not enough fuses")
    # supplies the player needs (the night's `need` block)
    have_n: dict[str, int] = {}
    for it, c in item_cells(lv):
        have_n[it] = have_n.get(it, 0) + 1
    for it, n in nd.get("need", {}).items():
        if it == "throwable":
            tot = sum(v for k, v in have_n.items() if cat.item(k).get("kind") == "throwable")
        else:
            tot = have_n.get(it, 0)
        if tot < n:
            P.append(f"too few {it}: {tot} < {n}")
    # hiding places exist in most rooms and the safe room is reachable without crossing a gate/lock
    if sum(1 for p in lv.props if PROP_DEFS[p.kind].hide) < max(4, len([r for r in lv.rooms if not r.hall]) // 2):
        P.append("too few hiding places")
    # every door joins two real rooms
    for d in lv.doors:
        if d.a < 0 or d.b < 0:
            P.append("dangling door")
            break
    if len(lv.doors) < len([r for r in lv.rooms if not r.hall]) - 1:
        P.append("rooms are under-connected")
    return P
