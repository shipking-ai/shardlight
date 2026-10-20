"""Interior rooms (houses, shops, halls) and procedural dungeons for Hollowmere.

Both return a :class:`WorldMap` (``name`` carries the visual style) with ``exits`` (``door`` / ``up``), spots for
NPC anchors, ``spawns`` and chest ``markers``.  Dungeons are seeded, validated (every room reachable from the entry,
bosses/chests reachable) and deterministic.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from ...core.rng import Rng
from . import tiles as T
from .worldmap import Marker, WorldMap

# enter-id -> layout kind
KIND_OF = {
    "inn": "inn", "tavern": "inn", "alehouse": "inn", "store": "shop", "healer": "healer", "hospice": "healer",
    "smithy": "smithy", "forge": "smithy", "oilpress": "smithy", "carpenter": "smithy", "lamp_house": "lamp_house",
    "cottage": "cottage", "cairnkeeper": "cottage", "farmhouse": "cottage", "sedge_hut": "hut",
    "harbormaster": "hall", "moot": "hall", "hollow_hall": "hollow",
}
SIZE_OF = {"inn": (18, 11), "shop": (12, 9), "healer": (12, 9), "smithy": (13, 9), "lamp_house": (12, 9),
           "cottage": (11, 8), "hut": (9, 7), "hall": (16, 10), "hollow": (28, 20)}


def _room(w: int, h: int, name: str, wall: int = T.CRYPTWALL, floor: int = T.WOODFLOOR) -> WorldMap:
    wm = WorldMap(w, h, 0, name)
    wm.ground[:, :] = T.VOID
    wm.ground[1:h - 1, 1:w - 1] = floor
    wm.ground[0, :] = wall
    wm.ground[h - 1, :] = wall
    wm.ground[:, 0] = wall
    wm.ground[:, w - 1] = wall
    wm.dark = False
    wm.ground[h - 1, w // 2] = T.PLANK          # door cell: stepping onto it leaves
    wm.exits["door"] = (w // 2, h - 1)
    wm.start = (w // 2, h - 2)
    return wm


def _put(wm: WorldMap, x: int, y: int, name: str) -> None:
    if 0 < x < wm.W - 1 and 0 < y < wm.H - 1:
        wm.obj[y, x] = T.O[name]


def _finish(wm: WorldMap) -> WorldMap:
    wm.recompute_walk()
    return wm


def build_interior(enter: str, seed: int | str = 0, label: str = "") -> WorldMap:
    kind = KIND_OF.get(enter, "cottage")
    w, h = SIZE_OF[kind]
    wm = _room(w, h, f"house:{kind}")
    wm.label = label  # type: ignore[attr-defined]
    cx = w // 2
    rng = Rng(seed).child("interior", enter)
    if kind == "cottage":
        _put(wm, cx, 1, "hearth"); _put(wm, 2, 2, "bed"); _put(wm, w - 3, 2, "bed"); _put(wm, 1, 1, "shelf"); _put(wm, w - 2, 1, "shelf")
        _put(wm, cx - 1, 4, "table"); _put(wm, cx + 1, 4, "bench"); _put(wm, w - 2, h - 2, "barrel"); _put(wm, 1, h - 2, "crate")
        for dx in (-1, 0, 1):
            _put(wm, cx + dx, 5, "rug")
        wm.spots.update({"npc": (cx, 3), "bed": (3, 2), "hearth": (cx, 2), "seat": (cx + 1, 5)})
    elif kind == "hut":
        _put(wm, cx, 1, "hearth"); _put(wm, 2, 2, "bed"); _put(wm, w - 2, 1, "shelf"); _put(wm, cx + 1, 4, "table"); _put(wm, 1, h - 2, "net" if False else "barrel")
        wm.spots.update({"npc": (cx, 3), "bed": (3, 2), "hearth": (cx, 2), "seat": (cx - 1, 4)})
    elif kind in ("shop", "healer"):
        for x in range(2, w - 2):
            _put(wm, x, 1, "shelf")
        for x in range(2, w - 3):
            _put(wm, x, 4, "counter")
        _put(wm, 1, h - 2, "barrel"); _put(wm, w - 2, h - 2, "crate"); _put(wm, w - 2, 3, "barrel")
        if kind == "healer":
            _put(wm, 1, 3, "bed"); _put(wm, 1, 5, "bed")
        wm.spots.update({"npc": (cx - 1, 3), "bed": (2, 3), "seat": (cx + 1, 3)})
    elif kind == "smithy":
        _put(wm, 2, 1, "forge"); _put(wm, 4, 1, "forge" if False else "barrel"); _put(wm, 3, 3, "anvil"); _put(wm, w - 3, 1, "shelf")
        for x in range(w // 2 + 1, w - 2):
            _put(wm, x, 4, "counter")
        _put(wm, w - 2, h - 2, "crate"); _put(wm, 1, h - 2, "barrel"); _put(wm, w - 2, 2, "barrel")
        wm.spots.update({"npc": (cx + 2, 3), "forge": (2, 2), "bed": (w - 2, 3), "seat": (cx, 3)})
    elif kind == "lamp_house":
        _put(wm, cx, 1, "hearth"); _put(wm, 2, 2, "bed"); _put(wm, 2, 5, "bench"); _put(wm, 4, 5, "bench"); _put(wm, w - 2, 1, "shelf")
        _put(wm, 1, 1, "shelf"); _put(wm, w - 3, 5, "table"); _put(wm, w - 2, h - 2, "barrel")
        for x in (3, 6, 9):
            _put(wm, x, 1, "candle")
        wm.spots.update({"npc": (cx, 3), "bed": (3, 2), "bench": (3, 5), "hearth": (cx, 2), "seat": (w - 4, 5)})
    elif kind == "inn":
        _put(wm, cx, 1, "hearth"); _put(wm, cx - 1, 1, "shelf"); _put(wm, cx + 1, 1, "shelf")
        for x in range(2, 9):
            _put(wm, x, 3, "counter")
        for (x, y) in ((11, 4), (14, 4), (11, 7), (14, 7)):
            _put(wm, x, y, "table"); _put(wm, x - 1, y, "bench"); _put(wm, x + 1, y, "bench")
        for y in (2, 5):
            _put(wm, w - 2, y, "bed")
        for x in (1, 3):
            _put(wm, x, h - 2, "barrel")
        _put(wm, 1, 1, "shelf")
        wm.spots.update({"npc": (5, 2), "bed": (w - 3, 2), "bed2": (w - 3, 5), "hearth": (cx, 2), "seat": (12, 5), "seat2": (7, 6)})
    elif kind == "hall":
        for x in range(4, w - 4):
            _put(wm, x, 5, "table")
        for x in range(w // 2 - 1, w // 2 + 2):
            for y in range(1, h - 1):
                if wm.obj[y, x] == 0:
                    wm.obj[y, x] = 0
        _put(wm, 2, 2, "brazier"); _put(wm, w - 3, 2, "brazier"); _put(wm, cx, 1, "statue"); _put(wm, 1, 5, "bench"); _put(wm, w - 2, 5, "bench")
        wm.spots.update({"npc": (cx, 3), "seat": (cx, 7), "bed": (2, 6)})
        for x in range(cx - 1, cx + 2):
            wm.ground[2:h - 1, x] = T.CARPET
    elif kind == "hollow":
        wm.name = "house:hollow"
        wm.dark = True
        for x in range(w // 2 - 2, w // 2 + 2):
            wm.ground[1:h - 1, x] = T.CARPET
        for y in (5, 9, 13):
            _put(wm, 5, y, "pillar"); _put(wm, w - 6, y, "pillar")
            _put(wm, 8, y, "brazier")
            _put(wm, w - 9, y, "brazier")
        _put(wm, cx - 1, 2, "greatlamp")
        wm.spots["greatlamp"] = (cx - 1, 3)
        wm.spots["npc"] = (cx, 6)
        for (x, y) in ((3, 3), (w - 4, 3), (3, 16), (w - 4, 16)):
            _put(wm, x, y, "statue")
        wm.markers.append(Marker("chest", 2, 8, "hollow_hall", {"kind": "chest", "loot": "crypt_chest", "id": "hall_hidden", "obj": "chest"}))
        wm.obj[8, 2] = T.O["chest"]
    return _finish(wm)


# --------------------------------------------------------------------------------------------- dungeons
DUNGEONS: dict[str, dict] = {
    "hollow_roots": dict(title="The Hollow Roots", style="cave", size=(66, 50), rooms=10, enemies=[("crawler", 2), ("bogwight", 1)],
                         boss="root_mother", chests=3, ore=7, loot="crypt_chest"),
    "cairn_of_debts": dict(title="Cairn of Debts", style="crypt", size=(58, 46), rooms=9, enemies=[("shade", 2)],
                           boss="debt_collector", chests=3, ore=0, loot="crypt_chest"),
    "drowned_chapel": dict(title="The Drowned Crypt", style="crypt", size=(58, 46), rooms=9, enemies=[("drowned", 2), ("shade", 1)],
                           boss="bell_warden", chests=3, ore=0, loot="crypt_chest", water=True),
    "listening_stones": dict(title="Beneath the Stones", style="cave", size=(30, 20), rooms=0, enemies=[], boss="", chests=1, ore=0,
                             loot="ruin_chest", chamber=True),
}


def _carve_rect(g: np.ndarray, x: int, y: int, w: int, h: int, tile: int) -> None:
    g[y:y + h, x:x + w] = tile


def build_dungeon(area: str, seed: int | str = 0) -> WorldMap:
    cfg = DUNGEONS[area]
    for attempt in range(8):
        wm = _try_dungeon(area, cfg, Rng(seed).child("dungeon", area, attempt))
        if wm is not None:
            wm.attempt = attempt
            return wm
    raise RuntimeError(f"could not build dungeon {area}")


def _flood(walk: np.ndarray, start: tuple[int, int]) -> np.ndarray:
    H, W = walk.shape
    seen = np.zeros_like(walk)
    if not walk[start[1], start[0]]:
        return seen
    seen[start[1], start[0]] = True
    dq = deque([start])
    while dq:
        x, y = dq.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < W and 0 <= ny < H and walk[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                dq.append((nx, ny))
    return seen


def _try_dungeon(area: str, cfg: dict, rng: Rng) -> WorldMap | None:
    W, H = cfg["size"]
    cave = cfg["style"] == "cave"
    floor = T.CAVE if cave else T.CRYPT
    wall = T.CAVEWALL if cave else T.CRYPTWALL
    wm = WorldMap(W, H, 0, f"{'cave' if cave else 'crypt'}:{area}")
    wm.ground[:, :] = T.VOID
    wm.dark = True
    rooms: list[tuple[int, int, int, int]] = []
    if cfg.get("chamber"):
        _carve_rect(wm.ground, 3, 3, W - 6, H - 6, floor)
        rooms.append((3, 3, W - 6, H - 6))
        corridor_cells: set[tuple[int, int]] = set()
    else:
        tries = 0
        while len(rooms) < cfg["rooms"] and tries < 500:
            tries += 1
            rw, rh = rng.randint(8, 13), rng.randint(7, 10)
            rx, ry = rng.randint(2, W - rw - 3), rng.randint(2, H - rh - 3)
            if any(rx < ox + ow + 3 and rx + rw + 3 > ox and ry < oy + oh + 3 and ry + rh + 3 > oy for ox, oy, ow, oh in rooms):
                continue
            rooms.append((rx, ry, rw, rh))
        if len(rooms) < max(5, cfg["rooms"] - 3):
            return None
        rooms.sort(key=lambda r: (r[1], r[0]))
        for (x, y, w, h) in rooms:
            if cave:                                  # rounded cave pockets
                for yy in range(y, y + h):
                    for xx in range(x, x + w):
                        if (xx - x - w / 2 + 0.5) ** 2 / (w / 2) ** 2 + (yy - y - h / 2 + 0.5) ** 2 / (h / 2) ** 2 <= 1.05:
                            wm.ground[yy, xx] = floor
            else:
                _carve_rect(wm.ground, x, y, w, h, floor)
        corridor_cells = set()
        centres = [(x + w // 2, y + h // 2) for (x, y, w, h) in rooms]
        order = [0]
        left = set(range(1, len(rooms)))
        edges = []
        while left:                                    # nearest-neighbour spanning tree
            best = min(((abs(centres[i][0] - centres[j][0]) + abs(centres[i][1] - centres[j][1]), i, j) for i in order for j in left))
            _, i, j = best
            edges.append((i, j))
            order.append(j)
            left.discard(j)
        extra = rng.randrange(len(rooms))
        edges.append((extra, (extra + 2) % len(rooms)))
        for i, j in edges:
            (ax, ay), (bx, by) = centres[i], centres[j]
            hor_first = rng.chance(0.5)
            pts = []
            if hor_first:
                pts += [(x, ay) for x in range(min(ax, bx), max(ax, bx) + 1)]
                pts += [(bx, y) for y in range(min(ay, by), max(ay, by) + 1)]
            else:
                pts += [(ax, y) for y in range(min(ay, by), max(ay, by) + 1)]
                pts += [(x, by) for x in range(min(ax, bx), max(ax, bx) + 1)]
            for (x, y) in pts:
                for dx in (0, 1):
                    for dy in (0, 1):
                        if 1 <= x + dx < W - 1 and 1 <= y + dy < H - 1:
                            if wm.ground[y + dy, x + dx] == T.VOID:
                                corridor_cells.add((x + dx, y + dy))
                            wm.ground[y + dy, x + dx] = floor
    # walls around floor
    g = wm.ground
    isfloor = (g == floor)
    pad = np.pad(isfloor, 1)
    near = np.zeros_like(isfloor)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near |= pad[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
    g[(g == T.VOID) & near] = wall
    wm.rooms = [tuple(r) for r in rooms]
    # entry in the first room
    x0, y0, w0, h0 = rooms[0] if cfg.get("chamber") else min(rooms, key=lambda r: (-r[1], r[0]))
    entry_room = (x0, y0, w0, h0)
    ex, ey = x0 + w0 // 2, y0 + h0 - 2
    wm.obj[ey, ex] = T.O["stairup"]
    wm.exits["up"] = (ex, ey)
    wm.start = (ex, ey - 1)
    wm.recompute_walk()
    reach = _flood(wm.walk, wm.start)
    # distances for boss placement
    dist = _bfs_dist(wm.walk, wm.start)
    taken: set[tuple[int, int]] = {(ex, ey), wm.start} | corridor_cells

    def free_cells(room, margin=1):
        x, y, w, h = room
        out = []
        for yy in range(y + margin, y + h - margin):
            for xx in range(x + margin, x + w - margin):
                if wm.walk[yy, xx] and (xx, yy) not in taken and reach[yy, xx] and not any(
                        (xx + dx, yy + dy) in corridor_cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                    out.append((xx, yy))
        return out

    far_room = max(rooms, key=lambda r: dist[r[1] + r[3] // 2, r[0] + r[2] // 2]) if len(rooms) > 1 else rooms[0]
    others = [r for r in rooms if r != entry_room and r != far_room] if len(rooms) > 2 else list(rooms)
    rng2 = rng.child("fill")

    def pick(room):
        cells = free_cells(room)
        if not cells:
            return None
        c = cells[rng2.randrange(len(cells))]
        taken.add(c)
        return c

    if cfg.get("chamber"):
        tx, ty = x0 + w0 // 2, y0 + 2
        wm.obj[ty, tx] = T.O["tablet"]
        wm.spots["tablet"] = (tx, ty + 1)
        taken.add((tx, ty + 1))
        for (px, py) in ((x0 + 3, y0 + 3), (x0 + w0 - 4, y0 + 3), (x0 + 3, y0 + h0 - 4), (x0 + w0 - 4, y0 + h0 - 4)):
            wm.obj[py, px] = T.O["glowmoss"]
    boss = cfg.get("boss")
    if boss:
        c = pick(far_room)
        if c is None:
            return None
        wm.spawns.append({"id": f"{area}.boss", "enemy": boss, "count": 1, "x": c[0], "y": c[1], "radius": 2, "area": area,
                          "unique": True, "site": area})
        wm.spots["boss"] = c
        # the far room also holds the best chest
        cc = pick(far_room)
        if cc:
            wm.markers.append(Marker("chest", cc[0], cc[1], area, {"kind": "chest", "loot": cfg["loot"], "id": f"{area}.chest.boss", "obj": "chest"}))
            wm.obj[cc[1], cc[0]] = T.O["chest"]
    n_chest = 0
    for room in others:
        if n_chest >= cfg["chests"] - (1 if boss else 0):
            break
        c = pick(room)
        if c:
            wm.markers.append(Marker("chest", c[0], c[1], area, {"kind": "chest", "loot": cfg["loot"], "id": f"{area}.chest.{n_chest}", "obj": "chest"}))
            wm.obj[c[1], c[0]] = T.O["chest"]
            n_chest += 1
    # monsters
    for k, room in enumerate(others):
        for (en, cnt) in cfg["enemies"]:
            if rng2.chance(0.8):
                c = pick(room)
                if c:
                    wm.spawns.append({"id": f"{area}.{en}.{k}", "enemy": en, "count": cnt, "x": c[0], "y": c[1], "radius": 3,
                                      "area": area, "unique": False, "site": area})
    # dressing: ore, moss, candles, graves, water
    for _ in range(cfg["ore"]):
        room = others[rng2.randrange(len(others))] if others else rooms[0]
        x, y, w, h = room
        cands = [(xx, yy) for yy in range(y, y + h) for xx in range(x, x + w)
                 if wm.ground[yy, xx] == floor and any(wm.ground[yy + dy, xx + dx] == wall for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                 and (xx, yy) not in taken and (xx, yy) not in corridor_cells
                 and not any((xx + dx, yy + dy) in corridor_cells for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
        if cands:
            c = cands[rng2.randrange(len(cands))]
            taken.add(c)
            wm.obj[c[1], c[0]] = T.O["ore"]
    for room in rooms:
        for _ in range(3):
            c = pick(room)
            if c:
                wm.obj[c[1], c[0]] = T.O[("glowmoss" if cave else rng2.choice(["candle", "candle", "grave", "pillar"]))]
    if cfg.get("water"):
        for room in others:
            x, y, w, h = room
            cx, cy = x + w // 2, y + h // 2
            for yy in range(cy - 1, cy + 2):
                for xx in range(cx - 2, cx + 3):
                    if (xx, yy) not in taken and wm.ground[yy, xx] == floor and wm.obj[yy, xx] == 0 and (xx, yy) not in corridor_cells:
                        wm.ground[yy, xx] = T.SHALLOW
    wm.recompute_walk()
    # validation: everything reachable, nothing blocking the entry
    reach = _flood(wm.walk, wm.start)
    for sp in wm.spawns:
        if not reach[sp["y"], sp["x"]]:
            return None
    for m in wm.markers:
        if not (reach[m.y + 1, m.x] or reach[m.y - 1, m.x] or reach[m.y, m.x + 1] or reach[m.y, m.x - 1]):
            return None
    for (x, y, w, h) in rooms:
        if not reach[y + h // 2, x + w // 2] and wm.walk[y + h // 2, x + w // 2]:
            return None
    return wm


def _bfs_dist(walk: np.ndarray, start: tuple[int, int]) -> np.ndarray:
    H, W = walk.shape
    d = np.full((H, W), -1, dtype=np.int32)
    d[start[1], start[0]] = 0
    dq = deque([start])
    while dq:
        x, y = dq.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < W and 0 <= ny < H and walk[ny, nx] and d[ny, nx] < 0:
                d[ny, nx] = d[y, x] + 1
                dq.append((nx, ny))
    return d
