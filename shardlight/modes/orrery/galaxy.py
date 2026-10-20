"""Seeded procedural galaxy: systems, stars, bodies on analytic orbits, hyperlanes, civ homes, resources, signals.

Everything here is a pure function of ``(seed, features)``.  ``features`` are the cross-mode unlock gates that change
what exists (``beacon_echo``, ``concord_envoys``); they are applied through *independent* RNG streams so the rest of
the galaxy is identical with or without them.  ``generate`` validates the result and, if a rule fails, regenerates
deterministically from the next attempt index.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Iterable

from ...core.rng import Rng, derive_seed
from . import signals as sigmod
from .defs import Defs
from .orbits import Orbit, equilibrium_temp, habitable_zone_wu, kepler_period, orbit_state

BASE_RANGE = 165.0          # longest lane a stock drive can take (matches the starter hull)
LONG_LANE_MAX = 232.0
FUEL_PER_UNIT = 1.0 / 38.0  # fuel per lane length unit
MAP_W, MAP_H = 1200.0, 760.0
MIN_SEP = 66.0
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]

STAR_CLASSES: dict[str, dict] = {
    "M": dict(label="red dwarf", lum=(0.25, 0.45), mass=0.5, radius=34, color=(255, 150, 112), temp=3300, w=30),
    "K": dict(label="orange dwarf", lum=(0.5, 0.8), mass=0.8, radius=40, color=(255, 194, 124), temp=4800, w=24),
    "G": dict(label="yellow dwarf", lum=(0.9, 1.3), mass=1.0, radius=46, color=(255, 238, 168), temp=5800, w=20),
    "F": dict(label="white-yellow star", lum=(1.8, 2.8), mass=1.3, radius=52, color=(255, 248, 224), temp=6800, w=11),
    "A": dict(label="white star", lum=(4.0, 6.0), mass=1.8, radius=58, color=(226, 236, 255), temp=9000, w=5),
    "B": dict(label="blue giant", lum=(8.0, 12.0), mass=2.5, radius=66, color=(170, 204, 255), temp=18000, w=1.5),
    "RG": dict(label="red giant", lum=(3.0, 5.0), mass=1.2, radius=92, color=(255, 122, 84), temp=3900, w=4),
    "WD": dict(label="white dwarf", lum=(0.3, 0.5), mass=0.9, radius=16, color=(214, 228, 255), temp=12000, w=2.5),
    "PSR": dict(label="pulsar", lum=(0.15, 0.2), mass=1.4, radius=10, color=(190, 236, 255), temp=60000, w=0.9),
    "LAMP": dict(label="guttering lamp-star", lum=(0.4, 0.5), mass=0.9, radius=38, color=(255, 200, 140), temp=4200, w=0),
}
HOME_STARS = ("M", "K", "G", "F")

PLANET_RES: dict[str, dict[str, tuple[int, int]]] = {
    "rock": {"ore": (1, 3), "crystal": (0, 1)},
    "scorched": {"ore": (2, 3), "crystal": (0, 2)},
    "lava": {"ore": (2, 3), "crystal": (1, 2)},
    "desert": {"ore": (1, 2), "crystal": (0, 2)},
    "tundra": {"ore": (0, 2), "water": (1, 2), "fuel": (0, 1)},
    "ice": {"water": (2, 3), "fuel": (0, 2)},
    "temperate": {"food": (2, 3), "water": (1, 2), "ore": (0, 1)},
    "ocean": {"water": (2, 3), "food": (1, 3)},
    "gas": {"fuel": (2, 3)},
}
SUITABLE = {   # which body types can plausibly grow a raw good (used when engineering distribution)
    "ore": ("rock", "scorched", "lava", "desert", "tundra", "belt"),
    "water": ("ice", "ocean", "tundra", "temperate", "belt"),
    "fuel": ("gas", "ice", "tundra"),
    "food": ("temperate", "ocean"),
    "crystal": ("lava", "desert", "scorched", "rock", "belt"),
}
HAB_BY_TYPE = {"temperate": 1.0, "ocean": 0.9, "tundra": 0.38, "desert": 0.34, "rock": 0.14, "scorched": 0.05,
               "ice": 0.1, "lava": 0.0, "gas": 0.0}

_PRE = ["Al", "Bren", "Cal", "Dov", "Eph", "Fen", "Gal", "Hal", "Ith", "Jor", "Kel", "Lum", "Mar", "Nor", "Ose",
        "Per", "Quil", "Ros", "Sal", "Tam", "Ulm", "Vel", "Wyn", "Yar", "Zen", "Ash", "Bel", "Cor", "Dra", "Eld"]
_MID = ["a", "e", "i", "o", "u", "an", "en", "il", "or", "ar", "el", "in"]
_END = ["dor", "ris", "vane", "mere", "thon", "lyn", "wick", "stead", "haven", "fall", "gate", "reach", "ton", "mar",
        "dal", "rest", "wyn", "cairn", "light", "hollow"]
STATION_KINDS = ("port", "skimmer", "foundry", "habitat", "outpost")


@dataclass
class Star:
    cls: str
    label: str
    lum: float
    mass: float
    radius: float
    color: tuple[int, int, int]
    temp: float


@dataclass
class Body:
    idx: int
    id: str
    name: str
    kind: str                    # planet | moon | belt | station | anomaly | derelict | lamp
    sub: str                     # planet type / station kind / anomaly kind / derelict kind
    parent: int | None
    orbit: Orbit
    radius: float
    atmosphere: str = "none"
    temp: float = 0.0
    res: dict[str, int] = field(default_factory=dict)
    hab: float = 0.0
    ring: bool = False
    seed: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def solid(self) -> bool:
        return self.kind in ("planet", "moon")


@dataclass
class System:
    id: int
    name: str
    x: float
    y: float
    star: Star
    bodies: list[Body] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    hidden: bool = False

    def extent(self) -> float:
        """Outermost orbit radius, used for the jump-ready boundary and camera limits."""
        r = 400.0
        for b in self.bodies:
            if b.parent is None:
                reach = b.extra.get("r1", b.orbit.a * (1 + b.orbit.e))
                r = max(r, reach)
        return r

    def stations(self) -> list[Body]:
        return [b for b in self.bodies if b.kind == "station"]

    def has_port(self) -> bool:
        return any(b.kind == "station" for b in self.bodies)

    def body(self, bid: str) -> Body | None:
        for b in self.bodies:
            if b.id == bid:
                return b
        return None


@dataclass
class Lane:
    a: int
    b: int
    length: float
    kind: str = "normal"         # normal | long | hidden
    reveal: str = ""             # hidden lanes: token naming what reveals them ("anomaly:<body id>", "signal:<id>")

    @property
    def fuel(self) -> float:
        return max(1.0, round(self.length * FUEL_PER_UNIT * 2) / 2)

    @property
    def key(self) -> tuple[int, int]:
        return (self.a, self.b) if self.a < self.b else (self.b, self.a)


class Galaxy:
    def __init__(self, seed: int, features: tuple[str, ...] = ()):
        self.seed = seed
        self.features = tuple(sorted(features))
        self.attempt = 0
        self.systems: list[System] = []
        self.lanes: dict[tuple[int, int], Lane] = {}
        self.adj: dict[int, list[int]] = {}
        self.home: dict[str, int] = {}
        self.start = 0
        self.last_lamp = 0
        self.signal_sources: dict[str, int] = {}
        self.envoy_system: int | None = None
        self.region: dict[int, str] = {}          # system -> civ id of the nearest home (hop metric)
        self.problems: list[str] = []

    # -- graph --------------------------------------------------------------------------------
    def lane(self, a: int, b: int) -> Lane | None:
        return self.lanes.get((a, b) if a < b else (b, a))

    def neighbors(self, sid: int, revealed: Iterable[tuple[int, int]] = (), max_range: float = 1e9,
                  include_hidden: bool = False) -> list[int]:
        """Systems reachable by one lane; hidden lanes only count once revealed."""
        rev = set(revealed)
        out = []
        for n in self.adj.get(sid, []):
            ln = self.lane(sid, n)
            if ln.kind == "hidden" and not include_hidden and ln.key not in rev:
                continue
            if ln.length <= max_range:
                out.append(n)
        return out

    def dist(self, a: int, b: int) -> float:
        sa, sb = self.systems[a], self.systems[b]
        return math.hypot(sa.x - sb.x, sa.y - sb.y)

    def hops_from(self, src: int, include_hidden: bool = False, max_range: float = 1e9,
                  revealed: Iterable[tuple[int, int]] = ()) -> dict[int, int]:
        seen = {src: 0}
        q = [src]
        rev = list(revealed)
        for cur in q:
            for n in self.neighbors(cur, rev, max_range, include_hidden):
                if n not in seen:
                    seen[n] = seen[cur] + 1
                    q.append(n)
        return seen

    def route(self, a: int, b: int, max_range: float = BASE_RANGE, revealed: Iterable[tuple[int, int]] = (),
              blocked: Iterable[int] = (), include_hidden: bool = False) -> list[int] | None:
        """Shortest route by lane length (Dijkstra); ``None`` if unreachable under the constraints."""
        blk = set(blocked)
        rev = list(revealed)
        dist = {a: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, a)]
        while heap:
            d, cur = heapq.heappop(heap)
            if cur == b:
                path = [b]
                while path[-1] != a:
                    path.append(prev[path[-1]])
                return path[::-1]
            if d > dist.get(cur, 1e18):
                continue
            for n in self.neighbors(cur, rev, max_range, include_hidden):
                if n in blk and n != b:
                    continue
                nd = d + self.lane(cur, n).length
                if nd < dist.get(n, 1e18):
                    dist[n] = nd
                    prev[n] = cur
                    heapq.heappush(heap, (nd, n))
        return None

    def fuel_feasible(self, a: int, b: int, tank: float, max_range: float = BASE_RANGE) -> bool:
        """Can a ship with ``tank`` fuel get from ``a`` to ``b`` if it may refuel in any system with a port?"""
        best = {a: tank}
        heap = [(-tank, a)]
        while heap:
            nf, cur = heapq.heappop(heap)
            f = -nf
            if cur == b:
                return True
            if f < best.get(cur, -1):
                continue
            for n in self.neighbors(cur, max_range=max_range):
                cost = self.lane(cur, n).fuel
                if cost > f:
                    continue
                nf2 = f - cost
                if self.systems[n].has_port():
                    nf2 = tank
                if nf2 > best.get(n, -1):
                    best[n] = nf2
                    heapq.heappush(heap, (-nf2, n))
        return False

    def system_of_body(self, bid: str) -> tuple[System, Body] | None:
        try:
            sid = int(bid.split(".")[0])
        except ValueError:
            return None
        if not 0 <= sid < len(self.systems):
            return None
        b = self.systems[sid].body(bid)
        return (self.systems[sid], b) if b else None


# ------------------------------------------------------------------------------ orbit evaluation
def body_state(system: System, idx: int, t: float) -> tuple[float, float, float, float]:
    """(x, y, vx, vy) of body ``idx`` in the system frame (star at the origin) at time ``t``."""
    b = system.bodies[idx]
    x, y, vx, vy = orbit_state(b.orbit, t)
    if b.parent is not None:
        px, py, pvx, pvy = body_state(system, b.parent, t)
        return x + px, y + py, vx + pvx, vy + pvy
    return x, y, vx, vy


def belt_rock_state(system: System, belt: Body, k: int, count: int, t: float) -> tuple[float, float]:
    """Position of the k-th decorative/minable rock on a belt at time ``t`` (rigid rotation plus jitter by index)."""
    r0, r1 = belt.extra["r0"], belt.extra["r1"]
    h = derive_seed(belt.seed, k)
    ang = (k + (h % 1000) / 1000.0) / count * math.tau
    rad = r0 + ((h >> 12) % 1000) / 1000.0 * (r1 - r0)
    ang += belt.orbit.m0 + math.tau / belt.orbit.period * t * (0.8 + 0.4 * ((r0 + r1) / 2 / max(rad, 1)))
    return math.cos(ang) * rad, math.sin(ang) * rad


# --------------------------------------------------------------------------------- generation
def generate(seed: int, features: Iterable[str] = (), defs: Defs | None = None) -> Galaxy:
    """Build and validate a galaxy; regenerates deterministically (attempt 1, 2, ...) if validation fails."""
    from .defs import standalone_defs
    defs = defs or standalone_defs()
    feats = tuple(sorted(set(features)))
    last: Galaxy | None = None
    for attempt in range(10):
        g = _build(seed, feats, defs, attempt)
        g.problems = validate(g, defs)
        g.attempt = attempt
        last = g
        if not g.problems:
            return g
    assert last is not None
    return last


def _gen_name(rng: Rng, used: set[str]) -> str:
    for _ in range(60):
        n = rng.pick(_PRE) + rng.pick(_MID) + rng.pick(_END)
        n = n[0].upper() + n[1:]
        if n not in used:
            used.add(n)
            return n
    n = f"Unnamed {len(used)}"
    used.add(n)
    return n


def _arm_density(x: float, y: float) -> float:
    cx, cy = MAP_W / 2, MAP_H / 2
    dx, dy = (x - cx) / (MAP_W / 2), (y - cy) / (MAP_H / 2)
    r = math.hypot(dx, dy)
    if r > 1.0:
        return 0.0
    th = math.atan2(dy, dx)
    arm = 0.5 + 0.5 * math.cos(2.0 * (th - 2.2 * math.log(r + 0.15)))
    return 0.45 + 0.55 * arm * (1.0 if r > 0.15 else 0.6)


def _layout(rng: Rng, n: int) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    sep = MIN_SEP
    tries = 0
    while len(pts) < n:
        tries += 1
        if tries > 60000:
            sep *= 0.94
            tries = 0
        x = rng.uniform(30, MAP_W - 30)
        y = rng.uniform(30, MAP_H - 30)
        if rng.random() > _arm_density(x, y):
            continue
        if all((x - px) ** 2 + (y - py) ** 2 >= sep * sep for px, py in pts):
            pts.append((x, y))
    return pts


def _pick_star(rng: Rng) -> Star:
    keys = [k for k in STAR_CLASSES if STAR_CLASSES[k]["w"] > 0]
    cls = rng.weighted(keys, [STAR_CLASSES[k]["w"] for k in keys])
    return _make_star(rng, cls)


def _make_star(rng: Rng, cls: str) -> Star:
    c = STAR_CLASSES[cls]
    lum = rng.uniform(*c["lum"])
    return Star(cls, c["label"], round(lum, 3), c["mass"], c["radius"] * rng.uniform(0.92, 1.1), c["color"], c["temp"])


def _build(seed: int, feats: tuple[str, ...], defs: Defs, attempt: int) -> Galaxy:
    root = Rng(derive_seed(seed, "orrery.galaxy", attempt))
    g = Galaxy(seed, feats)
    n = 60 + root.child("count").randrange(0, 61)
    pts = _layout(root.child("layout"), n)
    names = root.child("names")
    used: set[str] = set()
    srng = root.child("stars")
    for i, (x, y) in enumerate(pts):
        g.systems.append(System(i, _gen_name(names, used), round(x, 1), round(y, 1), _pick_star(srng)))
    _build_lanes(g, root.child("lanes"))
    _choose_special_systems(g, root.child("special"), defs)
    for s in g.systems:
        _populate(s, root.child("bodies", s.id), g)
    _assign_homes(g, root.child("homes"), defs)
    _ensure_start(g, root.child("start"))
    _engineer_resources(g, root.child("resources"), defs)
    _add_lane_extras(g, root.child("extras"))
    _place_signals(g, root.child("signals"), defs)
    if "concord_envoys" in feats:
        _place_envoys(g, root.child("envoys"))
    return g


# --- lanes ---------------------------------------------------------------------------------
def _build_lanes(g: Galaxy, rng: Rng) -> None:
    n = len(g.systems)
    pairs = sorted(((g.dist(i, j), i, j) for i in range(n) for j in range(i + 1, n)))
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    mst: set[tuple[int, int]] = set()
    for d, i, j in pairs:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            mst.add((i, j))
    # Gabriel graph over short pairs
    for d, i, j in pairs:
        if d > BASE_RANGE:
            break
        mx = (g.systems[i].x + g.systems[j].x) / 2
        my = (g.systems[i].y + g.systems[j].y) / 2
        r2 = (d / 2) ** 2
        ok = True
        for k, s in enumerate(g.systems):
            if k != i and k != j and (s.x - mx) ** 2 + (s.y - my) ** 2 < r2 * 0.98:
                ok = False
                break
        if ok:
            mst.add((i, j))
    deg = {i: 0 for i in range(n)}
    for i, j in mst:
        deg[i] += 1
        deg[j] += 1
    # trim over-connected nodes (drop longest non-bridge edges first), keep graph connected
    by_len = sorted(mst, key=lambda p: -g.dist(*p))
    for i, j in by_len:
        if deg[i] > 5 or deg[j] > 5:
            trial = mst - {(i, j)}
            if _connected(n, trial):
                mst = trial
                deg[i] -= 1
                deg[j] -= 1
    for i, j in sorted(mst):
        d = round(g.dist(i, j), 1)
        g.lanes[(i, j)] = Lane(i, j, d, "normal" if d <= BASE_RANGE else "long")
    _rebuild_adj(g)


def _connected(n: int, edges: Iterable[tuple[int, int]]) -> bool:
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for i, j in edges:
        adj[i].append(j)
        adj[j].append(i)
    seen = {0}
    q = [0]
    for c in q:
        for m in adj[c]:
            if m not in seen:
                seen.add(m)
                q.append(m)
    return len(seen) == n


def _rebuild_adj(g: Galaxy) -> None:
    g.adj = {s.id: [] for s in g.systems}
    for (a, b) in g.lanes:
        g.adj[a].append(b)
        g.adj[b].append(a)
    for k in g.adj:
        g.adj[k].sort()


def _add_lane_extras(g: Galaxy, rng: Rng) -> None:
    """Long lanes (need a better drive) and hidden lanes (revealed by anomalies/signals): both are shortcuts."""
    n = len(g.systems)
    hops = {i: g.hops_from(i) for i in range(n)}
    cands = []
    for i in range(n):
        for j in range(i + 1, n):
            if g.lane(i, j) is not None:
                continue
            d = g.dist(i, j)
            if BASE_RANGE < d <= LONG_LANE_MAX and hops[i][j] >= 4:
                cands.append((hops[i][j] - d / 80.0, i, j))
    cands.sort(reverse=True)
    used: set[int] = set()
    count = 0
    for _, i, j in cands:
        if count >= 4:
            break
        if i in used or j in used or g.last_lamp in (i, j):
            continue
        used.update((i, j))
        g.lanes[(i, j)] = Lane(i, j, round(g.dist(i, j), 1), "long")
        count += 1
    # hidden shortcuts of normal drive length, three or four of them
    cands = []
    for i in range(n):
        for j in range(i + 1, n):
            if g.lane(i, j) is not None:
                continue
            d = g.dist(i, j)
            if d <= BASE_RANGE + 20 and hops[i][j] >= 3 and g.last_lamp not in (i, j):
                cands.append((hops[i][j] * 10 - d / 20 + rng.random(), i, j))
    cands.sort(reverse=True)
    used = set()
    hidden = 0
    for _, i, j in cands:
        if hidden >= 4:
            break
        if i in used or j in used:
            continue
        used.update((i, j))
        g.lanes[(i, j)] = Lane(i, j, round(g.dist(i, j), 1), "hidden", reveal=f"fold:{hidden}")
        hidden += 1
    _rebuild_adj(g)
    # attach one lensing-fold anomaly at the first end of each of the first two hidden lanes
    for ln in [x for x in g.lanes.values() if x.kind == "hidden"][:2]:
        s = g.systems[ln.a]
        k = int(ln.reveal.split(":")[1])
        _add_anomaly(s, "lensing_fold", rng, extra={"lane": [ln.a, ln.b]})
        ln.reveal = f"anomaly:{s.bodies[-1].id}"
        _ = k


def _choose_special_systems(g: Galaxy, rng: Rng, defs: Defs) -> None:
    """Last Lamp: a peripheral, low-degree system far from the galactic centre."""
    cx, cy = MAP_W / 2, MAP_H / 2
    best, best_score = 0, -1e9
    for s in g.systems:
        d_core = math.hypot(s.x - cx, s.y - cy)
        score = d_core - 22.0 * len(g.adj[s.id]) + rng.uniform(0, 30)
        if score > best_score:
            best, best_score = s.id, score
    g.last_lamp = best
    s = g.systems[best]
    s.star = _make_star(rng, "LAMP")
    s.tags.append("last_lamp")
    s.hidden = True


# --- bodies --------------------------------------------------------------------------------
def _planet_type(rng: Rng, temp: float, a_ratio: float) -> str:
    if a_ratio > 1.45 and rng.chance(0.55):
        return "gas"
    if temp > 720:
        return "lava" if rng.chance(0.5) else "scorched"
    if temp > 470:
        return "scorched" if rng.chance(0.55) else "rock"
    if temp > 335:
        return rng.weighted(["desert", "rock", "scorched"], [5, 3, 1])
    if temp > 262:
        return rng.weighted(["temperate", "ocean", "rock", "desert", "tundra"], [4, 2.4, 1.4, 1.1, 0.8])
    if temp > 205:
        return rng.weighted(["tundra", "rock", "ice"], [3, 2, 1.5])
    return rng.weighted(["ice", "rock", "gas"], [4, 2, 1.5]) if a_ratio > 1.8 else "ice"


def _atmosphere(rng: Rng, ptype: str) -> str:
    opts = {
        "temperate": (["breathable", "dense", "thin"], [6, 1.5, 1]),
        "ocean": (["breathable", "dense", "toxic"], [5, 2, 1]),
        "tundra": (["thin", "none", "dense"], [4, 2, 1]),
        "desert": (["thin", "none", "toxic"], [3, 2, 1.5]),
        "rock": (["none", "thin"], [4, 1.5]),
        "scorched": (["none", "toxic", "thin"], [3, 2, 1]),
        "lava": (["toxic", "none"], [3, 1]),
        "ice": (["none", "thin"], [4, 1]),
        "gas": (["hydrogen"], [1]),
    }[ptype]
    return rng.weighted(*opts)


GREENHOUSE = {"none": 0.0, "thin": 0.015, "breathable": 0.04, "dense": 0.12, "toxic": 0.22, "hydrogen": 0.05}


def _rolled_res(rng: Rng, ptype: str) -> dict[str, int]:
    out = {}
    for good, (lo, hi) in PLANET_RES.get(ptype, {}).items():
        v = rng.randint(lo, hi)
        if v > 0:
            out[good] = v
    return out


def _populate(s: System, rng: Rng, g: Galaxy) -> None:
    star = s.star
    if star.cls == "LAMP":
        _populate_lamp(s, rng)
        return
    hz = habitable_zone_wu(star.lum)
    if star.cls == "PSR":
        n_planets = rng.weighted([0, 1], [3, 1])
    elif star.cls in ("WD", "B"):
        n_planets = rng.weighted([1, 2, 3], [3, 3, 1])
    else:
        n_planets = rng.weighted([2, 3, 4, 5, 6], [2, 4, 4, 3, 1.4])
    r0 = max(star.radius * 3.2 + 70.0, 0.34 * hz)
    r0 = max(r0, 340.0) * rng.uniform(1.0, 1.25)
    a = r0
    planets: list[Body] = []
    for i in range(n_planets):
        if a > 4600:
            break
        temp0 = equilibrium_temp(star.lum, a)
        ptype = _planet_type(rng, temp0, a / hz)
        atmos = _atmosphere(rng, ptype)
        temp = equilibrium_temp(star.lum, a, albedo=0.3) * (1.0 + GREENHOUSE[atmos])
        gas = ptype == "gas"
        radius = rng.uniform(30, 50) if gas else rng.uniform(13, 27)
        ecc = rng.uniform(0.0, 0.07 if gas else 0.14)
        mass = 0.08 if gas else 0.02
        orb = Orbit(a, ecc, rng.uniform(0, math.tau), rng.uniform(0, math.tau), kepler_period(a, star.mass))
        body = Body(len(s.bodies), f"{s.id}.{len(s.bodies)}", f"{s.name} {ROMAN[len(planets)]}", "planet", ptype, None,
                    orb, round(radius, 1), atmos, round(temp, 1), _rolled_res(rng, ptype),
                    HAB_BY_TYPE[ptype] if atmos in ("breathable", "thin", "dense", "none") else 0.0,
                    ring=gas and rng.chance(0.4), seed=rng.randrange(1 << 30))
        if atmos == "toxic":
            body.hab *= 0.4
        if ptype in ("temperate", "ocean") and atmos != "breathable":
            body.hab *= 0.5
        body.extra["mass"] = mass
        s.bodies.append(body)
        planets.append(body)
        # moons
        n_moons = rng.weighted([0, 1, 2, 3], [4, 3, 2, 1]) if gas else rng.weighted([0, 1], [5, 1])
        ma = radius + 26
        for m in range(n_moons):
            ma += rng.uniform(22, 44)
            mtype = rng.weighted(["rock", "ice", "lava"], [3, 3, 0.4 if temp0 < 600 else 2])
            morb = Orbit(ma, rng.uniform(0, 0.05), rng.uniform(0, math.tau), rng.uniform(0, math.tau),
                         kepler_period(ma, mass, 500.0) * (1.0 if gas else 1.0))
            mb = Body(len(s.bodies), f"{s.id}.{len(s.bodies)}", f"{body.name}-{chr(97 + m)}", "moon", mtype,
                      body.idx, morb, round(rng.uniform(5, 10), 1), "none", round(temp * 0.95, 1),
                      _rolled_res(rng, mtype), 0.02, seed=rng.randrange(1 << 30))
            s.bodies.append(mb)
        a *= rng.uniform(1.42, 1.9)
    # asteroid belts: in a gap or beyond the last planet
    if star.cls != "PSR" and rng.chance(0.5):
        kind = rng.weighted(["metal", "ice", "crystal"], [5, 3, 1.4])
        if planets:
            a_belt = planets[min(len(planets) - 1, rng.randrange(len(planets)))].orbit.a * rng.uniform(1.14, 1.3)
        else:
            a_belt = 600.0
        a_belt = min(a_belt, 4200.0)
        res = {"metal": {"ore": rng.randint(2, 3)}, "ice": {"water": rng.randint(2, 3)},
               "crystal": {"crystal": rng.randint(1, 2), "ore": 1}}[kind]
        orb = Orbit(a_belt, 0.0, 0.0, rng.uniform(0, math.tau), kepler_period(a_belt, star.mass) * 1.4)
        s.bodies.append(Body(len(s.bodies), f"{s.id}.{len(s.bodies)}", f"{s.name} Belt", "belt", kind, None, orb,
                             60.0, res=res, seed=rng.randrange(1 << 30),
                             extra={"r0": a_belt - 70, "r1": a_belt + 70, "rocks": 26}))
    _maybe_station(s, rng)
    if rng.chance(0.32):
        _add_anomaly(s, None, rng)
    if rng.chance(0.28):
        _add_derelict(s, rng)
    if star.cls == "PSR":
        s.tags.append("pulsar")


def _populate_lamp(s: System, rng: Rng) -> None:
    """The Last Lamp: a dim star ringed by five unlit gear-nodes, plus one old shelter station."""
    star = s.star
    for i in range(5):
        a = 260.0 + i * 130.0
        period = 22.0 + i * 16.0      # outer nodes turn more slowly (inner = smallest gear = fastest)
        orb = Orbit(a, 0.0, 0.0, rng.uniform(0, math.tau), period)
        s.bodies.append(Body(len(s.bodies), f"{s.id}.{len(s.bodies)}", f"Gear {ROMAN[i]}", "lamp", "gear", None, orb,
                             22.0, seed=rng.randrange(1 << 30), extra={"order": i}))
    sh_orb = Orbit(1100.0, 0.0, rng.uniform(0, math.tau), rng.uniform(0, math.tau), kepler_period(1100.0, star.mass))
    s.bodies.append(Body(len(s.bodies), f"{s.id}.{len(s.bodies)}", "Lamplighters' Shelter", "station", "outpost", None,
                         sh_orb, 12.0, seed=rng.randrange(1 << 30), extra={"shipyard": False, "service": "shelter"}))


def _maybe_station(s: System, rng: Rng, force: bool = False) -> None:
    solid = [b for b in s.bodies if b.kind == "planet"]
    best_hab = max((b.hab for b in solid), default=0.0)
    prob = 0.82 if best_hab >= 0.8 else 0.6 if best_hab >= 0.3 else 0.42
    if not (force or rng.chance(prob)):
        return
    host = None
    kind = "outpost"
    gas = [b for b in solid if b.sub == "gas"]
    habs = sorted(solid, key=lambda b: -b.hab)
    belts = [b for b in s.bodies if b.kind == "belt"]
    if habs and habs[0].hab >= 0.3:
        host, kind = habs[0], "habitat" if habs[0].hab < 0.8 else "port"
    elif gas:
        host, kind = gas[0], "skimmer"
    elif belts:
        host, kind = belts[0], "foundry"
    elif solid:
        host = solid[rng.randrange(len(solid))]
    if host is None:
        # free station orbiting the star
        a = rng.uniform(500, 1500)
        orb = Orbit(a, 0.0, rng.uniform(0, math.tau), rng.uniform(0, math.tau), kepler_period(a, s.star.mass))
        parent = None
    elif host.kind == "belt":
        orb = Orbit(host.orbit.a, 0.0, 0.0, host.orbit.m0 + 0.6, host.orbit.period)
        parent = None
    else:
        a = host.radius + rng.uniform(34, 52)
        orb = Orbit(a, 0.0, rng.uniform(0, math.tau), rng.uniform(0, math.tau),
                    kepler_period(a, host.extra.get("mass", 0.02), 500.0))
        parent = host.idx
    idx = len(s.bodies)
    s.bodies.append(Body(idx, f"{s.id}.{idx}", f"{s.name} {kind.capitalize()}", "station", kind, parent, orb, 9.0,
                         seed=rng.randrange(1 << 30), extra={"shipyard": kind in ("port", "habitat") and rng.chance(0.7)}))


ANOMALY_KINDS = ("lensing_fold", "ancient_beacon", "crystal_bloom", "orrery_fragment")
DERELICT_KINDS = ("wreck_cargo", "blueprint_cache", "logbook", "fuel_hulk")


def _add_anomaly(s: System, kind: str | None, rng: Rng, extra: dict | None = None) -> None:
    kind = kind or rng.weighted(list(ANOMALY_KINDS), [1.0, 1.6, 2.2, 1.0])
    a = rng.uniform(420, 1700)
    orb = Orbit(a, 0.0, rng.uniform(0, math.tau), 0.0, 0.0)       # anomalies are fixed in space
    idx = len(s.bodies)
    s.bodies.append(Body(idx, f"{s.id}.{idx}", {"lensing_fold": "Lensing Fold", "ancient_beacon": "Ancient Beacon",
                                                "crystal_bloom": "Crystal Bloom",
                                                "orrery_fragment": "Orrery Fragment"}[kind],
                         "anomaly", kind, None, orb, 16.0, seed=rng.randrange(1 << 30), extra=dict(extra or {})))


def _add_derelict(s: System, rng: Rng, kind: str | None = None) -> None:
    kind = kind or rng.weighted(list(DERELICT_KINDS), [3, 1.2, 2, 1.5])
    a = rng.uniform(380, 1900)
    orb = Orbit(a, rng.uniform(0, 0.2), rng.uniform(0, math.tau), rng.uniform(0, math.tau),
                kepler_period(a, s.star.mass) * 2.4)
    idx = len(s.bodies)
    nm = {"wreck_cargo": "Drifting Hulk", "blueprint_cache": "Sealed Vault", "logbook": "Silent Courier",
          "fuel_hulk": "Tanker Wreck"}[kind]
    trapped = rng.chance(0.3)
    s.bodies.append(Body(idx, f"{s.id}.{idx}", nm, "derelict", kind, None, orb, 10.0, seed=rng.randrange(1 << 30),
                         extra={"trapped": trapped}))


# --- homes, start, resources ---------------------------------------------------------------
def _assign_homes(g: Galaxy, rng: Rng, defs: Defs) -> None:
    civs = defs.civ_ids()
    cands = [s for s in g.systems if s.star.cls in HOME_STARS and s.id != g.last_lamp and len(g.adj[s.id]) >= 2]
    first = rng.pick(cands)
    chosen = [first]
    while len(chosen) < len(civs):
        best, bd = None, -1.0
        for s in cands:
            if s in chosen:
                continue
            d = min(g.dist(s.id, c.id) for c in chosen)
            d += rng.uniform(0, 25)
            if d > bd:
                best, bd = s, d
        chosen.append(best)
    order = rng.shuffled(civs)
    for civ, s in zip(order, chosen):
        g.home[civ] = s.id
        s.tags.append(f"home:{civ}")
        _ensure_homeworld(s, rng)
    # regions: nearest home by hop count, ties by euclidean distance
    hop_maps = {civ: g.hops_from(sid) for civ, sid in g.home.items()}
    for s in g.systems:
        g.region[s.id] = min(g.home, key=lambda c: (hop_maps[c].get(s.id, 99), g.dist(s.id, g.home[c])))


def _ensure_homeworld(s: System, rng: Rng) -> None:
    """Every civ needs a habitable homeworld: pick the planet nearest the habitable zone and make it one."""
    hz = habitable_zone_wu(s.star.lum)
    planets = [b for b in s.bodies if b.kind == "planet" and b.sub != "gas"]
    ok = [b for b in planets if b.sub in ("temperate", "ocean") and b.atmosphere == "breathable"]
    if ok:
        home = min(ok, key=lambda b: abs(b.orbit.a - hz))
    else:
        if not planets:
            a = hz
            orb = Orbit(a, 0.03, rng.uniform(0, math.tau), rng.uniform(0, math.tau), kepler_period(a, s.star.mass))
            idx = len(s.bodies)
            home = Body(idx, f"{s.id}.{idx}", f"{s.name} Prime", "planet", "temperate", None, orb, 22.0, seed=rng.randrange(1 << 30))
            s.bodies.append(home)
        else:
            home = min(planets, key=lambda b: abs(b.orbit.a - hz))
        home.sub = "temperate" if rng.chance(0.6) else "ocean"
        home.atmosphere = "breathable"
        a = hz * rng.uniform(0.93, 1.07)
        home.orbit = Orbit(a, min(home.orbit.e, 0.05), home.orbit.w, home.orbit.m0, kepler_period(a, s.star.mass))
        home.temp = round(equilibrium_temp(s.star.lum, a) * (1 + GREENHOUSE["breathable"]), 1)
        home.radius = max(home.radius, 20.0)
        home.hab = 1.0 if home.sub == "temperate" else 0.9
        home.res = {"food": 3, "water": 2} if home.sub == "temperate" else {"water": 3, "food": 2}
        home.ring = False
    home.extra["homeworld"] = True
    # make sure a big port station orbits it
    for b in list(s.bodies):
        if b.kind == "station" and b.parent == home.idx:
            b.sub = "port"
            b.extra["shipyard"] = True
            return
    a = home.radius + rng.uniform(36, 50)
    idx = len(s.bodies)
    s.bodies.append(Body(idx, f"{s.id}.{idx}", f"{s.name} Port", "station", "port", home.idx,
                         Orbit(a, 0.0, rng.uniform(0, math.tau), rng.uniform(0, math.tau), kepler_period(a, 0.02, 500.0)),
                         10.0, seed=rng.randrange(1 << 30), extra={"shipyard": True}))


def _ensure_start(g: Galaxy, rng: Rng) -> None:
    """A neutral free port near the centre with a belt and an anomaly to scan: where the player starts."""
    cx, cy = MAP_W / 2, MAP_H / 2
    homes = set(g.home.values())
    cands = [s for s in g.systems if s.id not in homes and s.id != g.last_lamp and s.star.cls in ("K", "G", "F", "M")
             and len(g.adj[s.id]) >= 2]
    s = min(cands, key=lambda c: math.hypot(c.x - cx, c.y - cy))
    g.start = s.id
    s.tags.append("start")
    if not s.has_port():
        _maybe_station(s, rng, force=True)
    st = s.stations()[0]
    st.name = "Tallow Quay" if "Tallow Quay" not in [x.name for x in g.systems] else st.name
    st.extra["shipyard"] = True
    st.extra["freeport"] = True
    if not any(b.kind == "belt" for b in s.bodies):
        a = max([b.orbit.a for b in s.bodies if b.parent is None and b.kind == "planet"] + [500.0]) * 1.2
        orb = Orbit(a, 0.0, 0.0, rng.uniform(0, math.tau), kepler_period(a, s.star.mass) * 1.4)
        s.bodies.append(Body(len(s.bodies), f"{s.id}.{len(s.bodies)}", f"{s.name} Belt", "belt", "metal", None, orb, 60.0,
                             res={"ore": 3}, seed=rng.randrange(1 << 30), extra={"r0": a - 70, "r1": a + 70, "rocks": 26}))
    if not any(b.kind == "anomaly" for b in s.bodies):
        _add_anomaly(s, "ancient_beacon", rng)
    # the start belt is rich in ore so a broke pilot can always mine their way out
    for b in s.bodies:
        if b.kind == "belt":
            b.res["ore"] = max(b.res.get("ore", 0), 3)
            break


def _engineer_resources(g: Galaxy, rng: Rng, defs: Defs) -> None:
    """Shape supply so civs have a strong specialty and a real shortage: trade is then worth doing."""
    raw = [gid for gid in defs.goods if defs.goods[gid].get("tier", "raw") == "raw"]
    for civ, c in defs.civs.items():
        sys_ids = [sid for sid, r in g.region.items() if r == civ]
        sp, lack = c.get("specialty"), c.get("lack")
        if lack in raw:
            kept = 0
            for sid in sys_ids:
                for b in g.systems[sid].bodies:
                    if lack in b.res:
                        if kept < 1 and b.res[lack] >= 2 and rng.chance(0.3):
                            b.res[lack] = 1
                            kept += 1
                        else:
                            del b.res[lack]
        if sp in raw:
            _boost(g, sys_ids, sp, 9, rng)
    # make every raw good have a handful of strong producers somewhere on the map
    for gid in raw:
        strong = [(s.id, b) for s in g.systems for b in s.bodies if b.res.get(gid, 0) >= 2]
        if len(strong) < 8:
            _boost(g, [s.id for s in g.systems if g.region[s.id] not in _lack_regions(defs, gid)], gid, 8 - len(strong), rng)
    # home systems always grow their own staple
    for civ, sid in g.home.items():
        for b in g.systems[sid].bodies:
            if b.extra.get("homeworld"):
                for gd in ("food", "water"):
                    if not (defs.civs[civ].get("lack") == gd):
                        b.res[gd] = max(b.res.get(gd, 0), 2)
                if defs.civs[civ].get("lack") in b.res:
                    del b.res[defs.civs[civ]["lack"]]


def _lack_regions(defs: Defs, gid: str) -> set[str]:
    return {c for c, d in defs.civs.items() if d.get("lack") == gid}


def _suits(b: Body, gid: str) -> bool:
    if b.kind == "belt":
        return {"metal": "ore", "ice": "water", "crystal": "crystal"}.get(b.sub) == gid
    return b.kind in ("planet", "moon") and b.sub in SUITABLE.get(gid, ())


def _boost(g: Galaxy, sys_ids: list[int], gid: str, amount: int, rng: Rng) -> None:
    """Raise richness of ``gid`` on suitable bodies in ``sys_ids`` until about ``amount`` strong points are added."""
    cands = rng.shuffled([b for sid in sys_ids for b in g.systems[sid].bodies if _suits(b, gid)])
    added = 0
    for b in cands:
        if added >= amount:
            break
        cur = b.res.get(gid, 0)
        if cur < 3:
            b.res[gid] = min(3, max(cur, 2) + (1 if cur >= 2 else 0))
            added += max(1, b.res[gid] - cur)


# --- signals / envoys ----------------------------------------------------------------------
def _place_signals(g: Galaxy, rng: Rng, defs: Defs) -> None:
    """Pick a source system for each enabled signal such that triangulation by bearings is unambiguous."""
    enabled = [sid for sid, s in defs.signals.items()
               if s.get("always") or (s.get("unlock") and _feature_for(s["unlock"]) in g.features)]
    taken: set[int] = set(g.home.values()) | {g.start, g.last_lamp}
    positions = [(s.x, s.y) for s in g.systems]
    ordered = sorted(enabled, key=lambda k: (not defs.signals[k].get("always"), k))   # base ones first
    for sid in ordered:
        srng = rng.child(sid)
        rngw = defs.signals[sid]["range"]
        cands = [s.id for s in g.systems if s.id not in taken and not s.hidden]
        cands = srng.shuffled(cands)
        # prefer sources whose neighbourhood is reasonably far from the start so signals are worth chasing
        cands.sort(key=lambda i: 0 if 120 < g.dist(i, g.start) < rngw * 0.95 else 1)
        pick = None
        for c in cands:
            if sigmod.triangulable(positions, c, rngw, g.seed, sid):
                pick = c
                break
        if pick is None:
            pick = cands[0]
        g.signal_sources[sid] = pick
        taken.add(pick)
        if defs.signals[sid].get("reward", {}).get("route"):
            for ln in g.lanes.values():
                if ln.kind == "hidden" and ln.reveal.startswith("fold:"):
                    ln.reveal = f"signal:{sid}"
                    break
        s = g.systems[pick]
        s.tags.append(f"signal:{sid}")
        _add_emitter(s, defs.signals[sid], srng)


def features_from_unlocks(defs: Defs, has_unlock) -> tuple[str, ...]:
    """Feature flags implied by the cross-mode unlocks the player currently holds."""
    feats = set()
    for s in defs.signals.values():
        if s.get("unlock") and has_unlock(s["unlock"]):
            feats.add(_feature_for(s["unlock"]))
    if has_unlock("orrery.contact.concord_envoys"):
        feats.add("concord_envoys")
    return tuple(sorted(feats))


def _feature_for(unlock_id: str) -> str:
    return {"orrery.signal.beacon_echo": "beacon_echo", "orrery.contact.concord_envoys": "concord_envoys"}.get(
        unlock_id, unlock_id)


def _add_emitter(s: System, sig: dict, rng: Rng) -> None:
    a = rng.uniform(500, 1600)
    idx = len(s.bodies)
    s.bodies.append(Body(idx, f"{s.id}.{idx}", f"{sig['name']} Source", "anomaly", "emitter", None,
                         Orbit(a, 0.0, rng.uniform(0, math.tau), 0.0, 0.0), 14.0, seed=rng.randrange(1 << 30),
                         extra={"signal": sig["id"], "emitter": sig.get("emitter", "relay")}))


def _place_envoys(g: Galaxy, rng: Rng) -> None:
    """Concord envoy barge: parks in a system a couple of lanes from the start, not a home."""
    hops = g.hops_from(g.start)
    homes = set(g.home.values())
    cands = [sid for sid, h in hops.items() if 2 <= h <= 3 and sid not in homes and sid != g.last_lamp and
             sid not in g.signal_sources.values()]
    if not cands:
        return
    sid = rng.pick(sorted(cands))
    g.envoy_system = sid
    s = g.systems[sid]
    s.tags.append("envoys")
    a = rng.uniform(600, 1100)
    idx = len(s.bodies)
    s.bodies.append(Body(idx, f"{s.id}.{idx}", "Envoy Barge Halcyon", "station", "envoy", None,
                         Orbit(a, 0.0, rng.uniform(0, math.tau), rng.uniform(0, math.tau), kepler_period(a, s.star.mass)),
                         12.0, seed=rng.randrange(1 << 30), extra={"envoy": True, "shipyard": False}))


# --------------------------------------------------------------------------------- validation
def region_totals(g: Galaxy, defs: Defs) -> dict[str, dict[str, int]]:
    tot: dict[str, dict[str, int]] = {c: {} for c in defs.civs}
    for s in g.systems:
        r = g.region[s.id]
        for b in s.bodies:
            for gid, v in b.res.items():
                tot[r][gid] = tot[r].get(gid, 0) + v
    return tot


def validate(g: Galaxy, defs: Defs) -> list[str]:
    """Return a list of rule violations (empty means the galaxy is valid)."""
    out: list[str] = []
    n = len(g.systems)
    if not 60 <= n <= 120:
        out.append(f"system count {n} outside 60..120")
    names = [s.name for s in g.systems]
    if len(set(names)) != n:
        out.append("duplicate system names")
    # graph connectivity with ordinary lanes (no hidden/long) and the stock drive
    seen = g.hops_from(g.start, max_range=BASE_RANGE)
    if len(seen) != n:
        out.append(f"graph not connected with stock drive ({len(seen)}/{n})")
    for ln in g.lanes.values():
        if ln.kind == "normal" and ln.length > BASE_RANGE + 1e-6:
            out.append(f"normal lane {ln.key} longer than stock range")
    if any(len(g.adj[i]) == 0 for i in range(n)):
        out.append("isolated system")
    # homes
    homes = list(g.home.values())
    if len(g.home) != len(defs.civs) or len(set(homes)) != len(homes):
        out.append("civ homes missing or shared")
    for civ, sid in g.home.items():
        s = g.systems[sid]
        hw = [b for b in s.bodies if b.extra.get("homeworld")]
        if not hw or hw[0].sub not in ("temperate", "ocean") or hw[0].atmosphere != "breathable" or hw[0].hab < 0.85:
            out.append(f"civ {civ} has no habitable homeworld")
        elif not any(b.kind == "station" and b.extra.get("shipyard") for b in s.bodies):
            out.append(f"civ {civ} home has no shipyard")
    for i, a in enumerate(homes):
        for b in homes[i + 1:]:
            if g.hops_from(a).get(b, 99) < 3:
                out.append("two homes closer than 3 jumps")
    # resource distribution
    raw = [gid for gid in defs.goods if defs.goods[gid].get("tier", "raw") == "raw"]
    tot = region_totals(g, defs)
    for gid in raw:
        suppliers = sum(1 for c in defs.civs if tot[c].get(gid, 0) >= 3)
        if suppliers < 2:
            out.append(f"good {gid} supplied by fewer than two regions")
    for civ, c in defs.civs.items():
        sp, lack = c.get("specialty"), c.get("lack")
        if sp in raw and tot[civ].get(sp, 0) < 7:
            out.append(f"civ {civ} specialty {sp} too weak")
        if lack in raw:
            if tot[civ].get(lack, 0) > 2:
                out.append(f"civ {civ} lacks {lack} but grows {tot[civ].get(lack, 0)}")
            near = [h for sid, h in g.hops_from(g.home[civ]).items()
                    if any(b.res.get(lack, 0) >= 2 for b in g.systems[sid].bodies) and g.region[sid] != civ]
            if not near or min(near) > 8:
                out.append(f"civ {civ} has no reachable supplier of {lack}")
    # start / last lamp
    st = g.systems[g.start]
    if not st.has_port() or not any(b.kind == "belt" for b in st.bodies):
        out.append("start lacks port or belt")
    tank = defs.hull_stats("wayfarer")["fuel"]
    if g.hops_from(g.start, max_range=BASE_RANGE, include_hidden=False).get(g.last_lamp) is None:
        out.append("Last Lamp unreachable")
    elif not g.fuel_feasible(g.start, g.last_lamp, tank, BASE_RANGE):
        out.append("Last Lamp unreachable on fuel")
    # signals
    positions = [(s.x, s.y) for s in g.systems]
    for sid, src in g.signal_sources.items():
        if not sigmod.triangulable(positions, src, defs.signals[sid]["range"], g.seed, sid):
            out.append(f"signal {sid} cannot be triangulated")
    if "choir" not in g.signal_sources:
        out.append("choir signal missing")
    # orbits
    for s in g.systems:
        for b in s.bodies:
            if b.kind in ("planet",) and b.orbit.a * (1 - b.orbit.e) < s.star.radius * 2.2:
                out.append(f"body {b.id} inside star")
            if b.kind in ("planet", "moon") and b.orbit.period <= 0:
                out.append(f"body {b.id} has no period")
    return out
