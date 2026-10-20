"""Seeded procedural campaign map: land shape, terrain, rivers, resources, roads, chokepoints, start regions.

Generation is attempt-based: each attempt is a pure function of ``(seed, attempt)``; a candidate that fails
validation (connectivity, size, fairness of the four start regions) is repaired where cheap and otherwise
discarded, so the same seed always yields the same valid map.
"""
from __future__ import annotations

import heapq
import math
from collections import deque

from ...core.rng import Rng
from . import hexgrid
from .rules import TERRAIN_BASE, TERRAIN_MOVE
from .state import MapData, Province, pair

SIZES = {"small": (9, 8, 42), "medium": (11, 9, 60), "large": (12, 10, 78)}
START_PROVINCES = {"small": 4, "medium": 5, "large": 6}

_PRE = ["Ash", "Bar", "Cal", "Dun", "Eld", "Fen", "Gal", "Har", "Isk", "Jor", "Kel", "Lor", "Mor", "Nor", "Ost",
        "Pen", "Quen", "Rav", "Sal", "Tarn", "Ul", "Var", "Wen", "Yar", "Zan", "Brin", "Cor", "Dra", "Ember", "Gil"]
_MID = ["a", "e", "o", "an", "en", "ar", "or", "in", "el", "ow", "a", "e", "o", "ir"]
_SUF = ["mere", "ford", "holt", "wick", "stead", "ridge", "marsh", "fall", "gate", "haven", "moor", "reach", "wold",
        "barrow", "cross", "water", "dale", "crown", "field", "hollow", "mark", "tor", "pool", "ton"]


class MapGenError(RuntimeError):
    pass


def generate(seed: int, size: str, house_ids: list[str]) -> MapData:
    """Return a validated map with capitals chosen and start regions owned.  Deterministic in ``seed``."""
    if size not in SIZES:
        raise ValueError(f"unknown map size {size!r}")
    for attempt in range(60):
        m = _attempt(seed, size, house_ids, attempt)
        if m is not None and not validate(m, house_ids):
            return m
    raise MapGenError(f"no valid map for seed {seed} size {size}")


# ---------------------------------------------------------------------------------------------- shape
def _blobs(rng: Rng, cols: int, rows: int, n: int, spread: float) -> list[tuple[float, float, float, float]]:
    return [(rng.uniform(0.2, 0.8) * cols, rng.uniform(0.2, 0.8) * rows, rng.uniform(0.18, 0.34) * max(cols, rows) * spread,
             rng.uniform(0.6, 1.0)) for _ in range(n)]


def _field(blobs, x: float, y: float) -> float:
    v = 0.0
    for bx, by, br, amp in blobs:
        d2 = ((x - bx) ** 2 + (y - by) ** 2) / (br * br)
        v += amp * math.exp(-d2)
    return v


def _land_cells(rng: Rng, cols: int, rows: int, target: int) -> list[tuple[int, int]] | None:
    shape = _blobs(rng.child("shape"), cols, rows, 5, 1.0)
    jitter = rng.child("jit")
    score: dict[tuple[int, int], float] = {}
    for r in range(rows):
        for c in range(cols):
            x, y = hexgrid.center(c, r, 1.0)
            nx, ny = x / (cols * math.sqrt(3)), y / (rows * 1.5)
            edge = min(nx, 1 - nx, ny, 1 - ny)
            score[(c, r)] = _field(shape, c + 0.5 * (r & 1), r) + 0.35 * jitter.random() + 1.6 * min(edge, 0.15)
    cells = sorted(score, key=lambda k: (-score[k], k))[:target]
    chosen = set(cells)
    # keep the largest connected component only
    seen: set[tuple[int, int]] = set()
    best: set[tuple[int, int]] = set()
    for start in sorted(chosen):
        if start in seen:
            continue
        comp = {start}
        dq = deque([start])
        while dq:
            cur = dq.popleft()
            for nb in hexgrid.neighbors(*cur):
                if nb in chosen and nb not in comp:
                    comp.add(nb)
                    dq.append(nb)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    if len(best) < target - 3:
        return None
    return sorted(best, key=lambda k: (k[1], k[0]))


# ------------------------------------------------------------------------------------------- attempt
def _attempt(seed: int, size: str, house_ids: list[str], attempt: int) -> MapData | None:
    cols, rows, target = SIZES[size]
    rng = Rng(seed).child("map", size, attempt)
    cells = _land_cells(rng, cols, rows, target)
    if cells is None:
        return None
    index = {c: i for i, c in enumerate(cells)}
    n = len(cells)
    provs = [Province(i, c, r, "plain", "") for i, (c, r) in enumerate(cells)]
    m = MapData.from_dict({"cols": cols, "rows": rows, "provinces": [p.to_dict() for p in provs],
                           "roads": [], "rivers": [], "capitals": {}})
    provs = m.provinces
    adj = m.adj

    # ---- terrain from elevation and moisture
    erng = rng.child("elev")
    elev_blobs = _blobs(erng, cols, rows, 4, 0.8)
    wet_blobs = _blobs(rng.child("wet"), cols, rows, 4, 0.9)
    elev = [_field(elev_blobs, p.col + 0.5 * (p.row & 1), p.row) + 0.45 * erng.random() for p in provs]
    wet = [_field(wet_blobs, p.col + 0.5 * (p.row & 1), p.row) + 0.35 * erng.random() for p in provs]
    order = sorted(range(n), key=lambda i: (-elev[i], i))
    n_mount, n_hill = max(3, round(n * 0.10)), max(4, round(n * 0.17))
    terr = ["plain"] * n
    for rank, i in enumerate(order):
        if rank < n_mount:
            terr[i] = "mountain"
        elif rank < n_mount + n_hill:
            terr[i] = "hill"
    rest = [i for i in range(n) if terr[i] == "plain"]
    rest_by_wet = sorted(rest, key=lambda i: (-wet[i], i))
    n_forest, n_marsh = round(n * 0.22), max(3, round(n * 0.09))
    low = sorted(rest, key=lambda i: (elev[i], i))
    marsh = set(low[:n_marsh * 2])
    for i in rest_by_wet:
        if n_marsh <= 0:
            break
        if i in marsh:
            terr[i] = "marsh"
            n_marsh -= 1
    for i in rest_by_wet:
        if n_forest <= 0:
            break
        if terr[i] == "plain":
            terr[i] = "forest"
            n_forest -= 1
    for p in provs:
        p.terrain = terr[p.id]
    _ridge(provs, adj, rng.child("ridge"), terr)
    for p in provs:
        p.terrain = terr[p.id]
    counts = {t: terr.count(t) for t in set(terr)}
    if any(counts.get(t, 0) < 3 for t in ("plain", "forest", "hill", "mountain", "marsh")):
        return None

    # ---- capitals (farthest-point sampling over solid cells) and start regions
    cand = [p.id for p in provs if p.terrain in ("plain", "hill") and len(adj[p.id]) >= 5]
    if len(cand) < len(house_ids) * 2:
        return None
    crng = rng.child("cap")
    caps = [crng.pick(cand)]
    min_sep = max(3, max(cols, rows) // 3)
    while len(caps) < len(house_ids):
        far = max(cand, key=lambda c: (min(hexgrid.distance((provs[c].col, provs[c].row), (provs[k].col, provs[k].row))
                                           for k in caps), -c))
        if min(hexgrid.distance((provs[far].col, provs[far].row), (provs[k].col, provs[k].row)) for k in caps) < min_sep:
            return None
        caps.append(far)
    assign = crng.shuffled(house_ids)
    for hid, cap in zip(assign, caps):
        m.capitals[hid] = cap
    k_start = START_PROVINCES[size]
    claimed: dict[int, str] = {m.capitals[h]: h for h in assign}
    frontier = {h: deque([m.capitals[h]]) for h in assign}
    owned_count = {h: 1 for h in assign}
    while any(owned_count[h] < k_start and frontier[h] for h in assign):
        for h in assign:
            if owned_count[h] >= k_start:
                continue
            while frontier[h] and owned_count[h] < k_start:
                cur = frontier[h][0]
                free = [nb for nb in adj[cur] if nb not in claimed and provs[nb].terrain != "mountain"]
                if not free:
                    frontier[h].popleft()
                    continue
                nb = min(free, key=lambda x: (TERRAIN_MOVE[provs[x].terrain], x))
                claimed[nb] = h
                frontier[h].append(nb)
                owned_count[h] += 1
                break
    if any(owned_count[h] < k_start for h in assign):
        return None
    for pid, h in claimed.items():
        provs[pid].owner = h
        provs[pid].home = h

    # ---- resource yields, features and fairness repair
    frng = rng.child("res")
    for p in provs:
        p.base = {k: v for k, v in TERRAIN_BASE[p.terrain].items() if v}
        if frng.chance(0.25):
            key = frng.pick(sorted(TERRAIN_BASE[p.terrain] or {"grain": 1}))
            p.base[key] = p.base.get(key, 0) + 1
    free_ids = [p.id for p in provs if p.owner is None]
    n_ink = max(4, round(n * 0.08))
    inkable = sorted((p.id for p in provs if p.terrain in ("plain", "hill", "forest")), key=lambda i: frng.random())
    for pid in inkable[:n_ink]:
        provs[pid].feature = "inkwell"
    pans = sorted((p.id for p in provs if p.terrain in ("marsh", "plain") and p.feature is None), key=lambda i: frng.random())
    for pid in pans[:max(3, round(n * 0.06))]:
        provs[pid].feature = "saltpan"
    for hid in assign:
        _repair_region(m, hid, frng)
    # chokepoints: articulation points that separate meaningful chunks
    for pid in _articulation(adj, n, {p.id for p in provs if p.terrain == "mountain"}):
        if pid not in m.capitals.values():
            provs[pid].choke = True

    # ---- rivers then roads
    _rivers(m, rng.child("rivers"), elev)
    _roads(m, rng.child("roads"), assign)
    _name_all(m, rng.child("names"))
    return m


def _ridge(provs: list[Province], adj: list[list[int]], rng: Rng, terr: list[str]) -> None:
    """Raise a mountain ridge between two distant coastal provinces, leaving one or two passes (the chokepoints)."""
    coast = [p.id for p in provs if len(adj[p.id]) < 6]
    if len(coast) < 4:
        return
    a = rng.pick(coast)
    far = sorted(coast, key=lambda c: (-hexgrid.distance((provs[a].col, provs[a].row), (provs[c].col, provs[c].row)), c))
    b = far[rng.randrange(max(1, len(far) // 4))]
    path = [a]
    while path[-1] != b and len(path) < 40:
        cur = path[-1]
        opts = [x for x in adj[cur] if x not in path]
        if not opts:
            break
        opts.sort(key=lambda x: (hexgrid.distance((provs[x].col, provs[x].row), (provs[b].col, provs[b].row))
                                 + rng.random() * 1.4, x))
        path.append(opts[0])
    if len(path) < 5:
        return
    gaps = {path[len(path) // 3], path[(2 * len(path)) // 3]} if len(path) > 8 else {path[len(path) // 2]}
    for pid in path:
        terr[pid] = "hill" if pid in gaps else "mountain"


def _region(m: MapData, hid: str) -> set[int]:
    own = {p.id for p in m.provinces if p.owner == hid}
    ring = set(own)
    for pid in own:
        ring.update(m.adj[pid])
    return ring


def _repair_region(m: MapData, hid: str, rng: Rng) -> None:
    """Ensure a start region (owned provinces plus their ring) offers every resource; patch deterministically."""
    ring = _region(m, hid)
    cap = m.capitals[hid]
    provs = m.provinces

    def have(pred) -> bool:
        return any(pred(provs[i]) for i in ring)

    def convert(candidates: list[int], terrain: str | None = None, feature: str | None = None) -> None:
        pool = [i for i in candidates if i != cap and i in ring]
        if not pool:
            pool = [i for i in ring if i != cap]
        pool.sort(key=lambda i: (hexgrid.distance((provs[i].col, provs[i].row), (provs[cap].col, provs[cap].row)), i))
        pid = pool[0]
        if terrain:
            provs[pid].terrain = terrain
            provs[pid].base = {k: v for k, v in TERRAIN_BASE[terrain].items() if v}
        if feature:
            provs[pid].feature = feature

    plains = [i for i in ring if provs[i].terrain in ("plain", "hill")]
    if sum(1 for i in ring if provs[i].terrain == "plain") < 2:
        convert(plains, "plain")
    if not have(lambda p: p.terrain == "forest"):
        convert([i for i in ring if provs[i].terrain == "plain"], "forest")
    if not have(lambda p: p.terrain in ("hill", "mountain")):
        convert([i for i in ring if provs[i].terrain in ("plain", "forest")], "hill")
    if not have(lambda p: p.terrain == "marsh" or p.feature == "saltpan"):
        convert([i for i in ring if provs[i].terrain in ("plain", "marsh")], None, "saltpan")
    if not have(lambda p: p.feature == "inkwell"):
        convert([i for i in ring if provs[i].terrain in ("plain", "hill", "forest") and provs[i].feature is None], None, "inkwell")


def _articulation(adj: list[list[int]], n: int, blocked: set[int] | None = None) -> list[int]:
    """Chokepoints on the graph without ``blocked`` (mountains): articulation points splitting off a chunk of >= 3
    provinces, and corridor provinces with exactly two unconnected exits."""
    blocked = blocked or set()
    out = []
    for v in range(n):
        if v in blocked:
            continue
        nbrs = [x for x in adj[v] if x not in blocked]
        seen = {v}
        sizes = []
        for s in nbrs:
            if s in seen:
                continue
            comp = {s}
            dq = deque([s])
            seen.add(s)
            while dq:
                cur = dq.popleft()
                for nb in adj[cur]:
                    if nb not in seen and nb not in blocked:
                        seen.add(nb)
                        comp.add(nb)
                        dq.append(nb)
            sizes.append(len(comp))
        if sum(1 for s in sizes if s >= 3) >= 2 or (len(nbrs) == 2 and nbrs[1] not in adj[nbrs[0]] and len(adj[v]) >= 4):
            out.append(v)
    return out


def _rivers(m: MapData, rng: Rng, elev: list[float]) -> None:
    provs, adj = m.provinces, m.adj
    n = len(provs)
    sources = sorted((p.id for p in provs if p.terrain in ("mountain", "hill")), key=lambda i: (-elev[i], i))
    want = 2 + n // 25
    made = 0
    used: set[int] = set()
    centers = [hexgrid.center(p.col, p.row, 1.0) for p in provs]
    for s in sources:
        if made >= want:
            break
        if s in used or rng.chance(0.25):
            continue
        path = [s]
        cur = s
        while len(path) < 12:
            lower = [nb for nb in adj[cur] if nb not in path and elev[nb] < elev[cur] and nb not in used]
            if not lower:
                break
            cur = min(lower, key=lambda x: (elev[x], x))
            path.append(cur)
            if len(adj[cur]) < 6:
                break
        if len(path) < 4:
            continue
        side = rng.pick((-1, 1))
        edges = set()
        for a, b in zip(path, path[1:]):
            common = [x for x in adj[a] if x in adj[b]]
            if not common:
                continue
            ax, ay = centers[a]
            bx, by = centers[b]

            def cross(x):
                cx, cy = centers[x]
                return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

            pick = [x for x in common if cross(x) * side > 0]
            if pick:
                edges.add(pair(a, pick[0]))
                edges.add(pair(b, pick[0]))
        if edges:
            m.rivers |= edges
            used.update(path)
            made += 1


def _roads(m: MapData, rng: Rng, houses: list[str]) -> None:
    provs, adj = m.provinces, m.adj
    n = len(provs)

    def cost(a: int, b: int) -> float:
        c = TERRAIN_MOVE[provs[b].terrain] + (1.0 if m.river(a, b) else 0.0)
        return c + (1.0 if provs[b].terrain == "mountain" else 0.0)

    def route(src: int, dst: int) -> list[int]:
        dist = {src: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, src)]
        while heap:
            d, cur = heapq.heappop(heap)
            if cur == dst:
                break
            if d > dist.get(cur, 1e9):
                continue
            for nb in adj[cur]:
                nd = d + cost(cur, nb)
                if nd < dist.get(nb, 1e9):
                    dist[nb] = nd
                    prev[nb] = cur
                    heapq.heappush(heap, (nd, nb))
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        return path[::-1]

    caps = [m.capitals[h] for h in houses]
    hubs = list(caps)
    towns = [p.id for p in provs if p.terrain in ("plain", "hill") and p.id not in caps and rng.chance(0.14)]
    hubs += towns
    links: list[tuple[int, int]] = []
    for i in range(1, len(caps)):                                     # spanning chain between capitals
        links.append((caps[i - 1], caps[i]))
    links.append((caps[-1], caps[0]))
    for t in towns:
        near = min((h for h in hubs if h != t), key=lambda h: (hexgrid.distance((provs[t].col, provs[t].row),
                                                                                (provs[h].col, provs[h].row)), h))
        links.append((t, near))
    for h in houses:                                                  # a road from each capital to each owned neighbour
        cap = m.capitals[h]
        for nb in adj[cap]:
            if provs[nb].owner == h:
                links.append((cap, nb))
    for a, b in links:
        path = route(a, b)
        for x, y in zip(path, path[1:]):
            m.roads.add(pair(x, y))


def _name_all(m: MapData, rng: Rng) -> None:
    used: set[str] = set()
    for p in m.provinces:
        for _ in range(40):
            nm = rng.pick(_PRE) + (rng.pick(_MID) if rng.chance(0.35) else "") + rng.pick(_SUF)
            if nm not in used:
                break
        else:
            nm = f"{rng.pick(_PRE)}{p.id}"
        used.add(nm)
        p.name = nm.capitalize() if nm[0].islower() else nm


# ------------------------------------------------------------------------------------------ validation
def components(adj: list[list[int]], skip: set[int] | None = None) -> int:
    skip = skip or set()
    seen: set[int] = set()
    comps = 0
    for s in range(len(adj)):
        if s in seen or s in skip:
            continue
        comps += 1
        dq = deque([s])
        seen.add(s)
        while dq:
            cur = dq.popleft()
            for nb in adj[cur]:
                if nb not in seen and nb not in skip:
                    seen.add(nb)
                    dq.append(nb)
    return comps


def validate(m: MapData, house_ids: list[str]) -> list[str]:
    """Return a list of problems (empty = valid)."""
    errs: list[str] = []
    n = len(m.provinces)
    if not 38 <= n <= 82:
        errs.append(f"province count {n} out of range")
    if components(m.adj) != 1:
        errs.append("land is not connected")
    if len(m.capitals) != len(house_ids) or len(set(m.capitals.values())) != len(house_ids):
        errs.append("capitals missing or shared")
    for h, cap in m.capitals.items():
        if m.provinces[cap].owner != h:
            errs.append(f"capital of {h} not owned by it")
        if sum(1 for p in m.provinces if p.owner == h) < 4:
            errs.append(f"{h} has too few start provinces")
    names = [p.name for p in m.provinces]
    if len(set(names)) != len(names) or any(not x for x in names):
        errs.append("province names not unique")
    for a, b in m.roads | m.rivers:
        if b not in m.adj[a]:
            errs.append("road or river joins non-adjacent provinces")
            break
    # every house can reach every other house's capital over land
    caps = list(m.capitals.values())
    reach = {caps[0]}
    dq = deque([caps[0]])
    while dq:
        cur = dq.popleft()
        for nb in m.adj[cur]:
            if nb not in reach:
                reach.add(nb)
                dq.append(nb)
    if not all(c in reach for c in caps):
        errs.append("capitals not mutually reachable")
    if not any(p.feature == "inkwell" for p in m.provinces):
        errs.append("no ink source on the map")
    # start-region fairness: terrain value of each house's start provinces within 30 percent
    vals = []
    for h in house_ids:
        v = 0.0
        for p in m.provinces:
            if p.owner == h:
                v += sum(p.base.values()) + (2 if p.feature else 0)
        vals.append(v)
    if vals and min(vals) < 0.7 * max(vals):
        errs.append("unfair start regions")
    return errs
