"""Seeded procedural overworld: noise + rules for regions, a river with crossings, landmark siting,
roads, decoration, hidden caches and spawn zones, then validation and deterministic repair.

``generate(seed, templates)`` is a pure function of its arguments (same seed -> identical map).  A failed
validation (an unreachable settlement, site or cache) is first repaired by carving a corridor, and if that
fails the next *attempt* (a different derived stream) is tried, so the result is always deterministic.
"""
from __future__ import annotations

import heapq
import math
from collections import deque

import numpy as np

from ...core import log
from ...core.rng import Rng, derive_seed
from . import tiles as T
from .landmarks import stamp_template
from .noise import box_sums, dilate, fbm, gradient_mag
from .worldmap import Feature, Marker, Site, WorldMap

LOG = log.get("verdant.worldgen")
SIZE = 256
BORDER = 3

# (id, template, kind, weights, near=(site, dmin, dmax), water_ok, min_sep)
SETTLEMENT_PLAN = [
    dict(id="tidewick", template="tidewick", kind="settlement", want={"sea": 2.5, "flat": 1.2, "meadow": 0.6, "edge": 0.4},
         water_ok=True, sea_side="right"),
    dict(id="harrow_cairn", template="harrow_cairn", kind="settlement", want={"moor": 3.0, "flat": 1.5, "high": 1.0},
         water_ok=False),
    dict(id="reedholm", template="reedholm", kind="settlement", want={"marsh": 3.0, "water": 1.4, "flat": 0.5},
         water_ok=True),
    dict(id="wickering", template="wickering", kind="settlement", want={"meadow": 3.0, "flat": 1.5, "edge": 2.2},
         water_ok=False),
]
SITE_PLAN = [
    dict(id="hollow_hall", template="hollow_hall", kind="ruin", want={"meadow": 1.4, "forest": 0.8, "center": 2.5, "flat": 1.2}),
    dict(id="tamsin_farm", template="farmstead", kind="farm", want={"meadow": 2.0, "flat": 1.5}, near=("wickering", 20, 38)),
    dict(id="cairn_of_debts", template="cairn_of_debts", kind="ruin", want={"moor": 1.5, "meadow": 0.5, "flat": 1.2},
         near=("harrow_cairn", 26, 62)),
    dict(id="drowned_chapel", template="drowned_chapel", kind="ruin", want={"marsh": 2.2, "water": 0.5, "flat": 0.6},
         near=("reedholm", 24, 64), water_ok=True),
    dict(id="sedge_hut", template="sedge_hut", kind="hut", want={"marsh": 2.0, "flat": 0.6}, near=("reedholm", 16, 42),
         water_ok=True),
    dict(id="listening_stones", template="listening_stones", kind="stones", want={"moor": 2.0, "high": 2.0, "flat": 1.2},
         near=("harrow_cairn", 30, 90), hidden=True, unlock="verdant.site.listening_stones"),
    dict(id="rook_camp", template="bandit_camp", kind="camp", want={"forest": 1.4, "meadow": 0.8, "flat": 1.0},
         near=("tidewick", 38, 80)),
    dict(id="hollow_roots", template="roots_entrance", kind="dungeon", want={"forest": 3.0, "flat": 0.8},
         near=("hollow_hall", 18, 70)),
    dict(id="wolf_den_a", template="wolf_den", kind="den", want={"forest": 3.0}, near=("wickering", 36, 90)),
    dict(id="wolf_den_b", template="wolf_den", kind="den", want={"forest": 2.0, "moor": 1.0}, near=("harrow_cairn", 30, 90)),
    dict(id="ford_shrine", template="wayshrine", kind="shrine", want={"meadow": 1.5, "flat": 1.0}, near=("hollow_hall", 20, 80)),
]


# ------------------------------------------------------------------------------------------------ A*
def astar4(cost: list[float], W: int, H: int, start: int, goal: int | set[int], hw: float = 1.35,
           max_nodes: int = 400000) -> list[int] | None:
    """4-neighbour weighted A* on a flat cost list (cost < 0 = blocked).  ``goal`` may be a set (Dijkstra)."""
    goals = goal if isinstance(goal, set) else {goal}
    single = None if isinstance(goal, set) else goal
    if single is not None:
        gx, gy = single % W, single // W
    best = {start: 0.0}
    came: dict[int, int] = {}
    heap = [(0.0, start)]
    closed: set[int] = set()
    n = 0
    while heap:
        _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        if cur in goals:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path
        closed.add(cur)
        n += 1
        if n > max_nodes:
            return None
        cx, cy = cur % W, cur // W
        g0 = best[cur]
        for nb, ok in ((cur + 1, cx + 1 < W), (cur - 1, cx > 0), (cur + W, cy + 1 < H), (cur - W, cy > 0)):
            if not ok:
                continue
            c = cost[nb]
            if c < 0 or nb in closed:
                continue
            ng = g0 + c
            if ng < best.get(nb, 1e18):
                best[nb] = ng
                came[nb] = cur
                h = 0.0 if single is None else (abs(nb % W - gx) + abs(nb // W - gy)) * 0.55 * hw
                heapq.heappush(heap, (ng + h, nb))
    return None


def line_pts(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    from ...core.nav import line_cells
    return list(line_cells(a, b))


def flood(walk: np.ndarray, start: tuple[int, int]) -> np.ndarray:
    """Boolean mask of cells 4-connected to ``start`` through walkable cells (equivalent to diagonal-no-corner BFS)."""
    H, W = walk.shape
    flat = walk.ravel().tolist()
    seen = bytearray(W * H)
    s = start[1] * W + start[0]
    if not flat[s]:
        return np.zeros_like(walk)
    seen[s] = 1
    dq = deque([s])
    while dq:
        c = dq.popleft()
        x = c % W
        for nb, ok in ((c + 1, x + 1 < W), (c - 1, x > 0), (c + W, c + W < W * H), (c - W, c >= W)):
            if ok and flat[nb] and not seen[nb]:
                seen[nb] = 1
                dq.append(nb)
    return np.frombuffer(bytes(seen), dtype=np.uint8).reshape(H, W).astype(bool)


# ------------------------------------------------------------------------------------------------ generator
class Generator:
    def __init__(self, seed: int, templates: dict[str, dict], size: int = SIZE, attempt: int = 0):
        self.seed = seed
        self.tpls = templates
        self.W = self.H = size
        self.attempt = attempt
        self.rng = Rng(seed).child("verdant.world", attempt)
        self.wm = WorldMap(size, size, seed, "overworld")
        self.wm.attempt = attempt
        self.placed: list[tuple[int, int, int, int]] = []
        self.centers: dict[str, tuple[int, int]] = {}
        self._frac_cache: dict[tuple[int, int], dict[str, np.ndarray]] = {}

    def np_rng(self, label: str) -> np.random.Generator:
        return np.random.default_rng(derive_seed(self.seed, "np", self.attempt, label) & 0xFFFFFFFF)

    def noise(self, label: str, scale: float, octaves: int = 4) -> np.ndarray:
        return fbm(self.W, self.H, derive_seed(self.seed, label, self.attempt), scale, octaves)

    # ------------------------------------------------------------------ terrain fields
    def build(self) -> WorldMap:
        self._fields()
        self._rivers()
        self._classify()
        self._border()
        self._place_landmarks()
        self._roads()
        self._lamps()
        self._decorate()
        self._caches()
        self._spawns()
        self._finish()
        return self.wm

    def _fields(self) -> None:
        W, H = self.W, self.H
        wm = self.wm
        xs = (np.arange(W)[None, :] + 0.5) / W
        ys = (np.arange(H)[:, None] + 0.5) / H
        n1 = self.noise("e1", 90, 5)
        n2 = self.noise("e2", 30, 3)
        nc = self.noise("coast", 46, 4)
        ramp = np.clip(1.3 - 1.8 * np.hypot(xs - 0.16, ys - 0.15), 0, 1)
        e = 0.46 * n1 + 0.14 * n2 + 0.40 * ramp
        sea_d = xs + 0.14 * (nc - 0.5)
        flip_x = self.rng.chance(0.5)
        flip_y = self.rng.chance(0.5)
        coast_edge = 0.835 + 0.02 * self.rng.random()
        sea = sea_d > coast_edge
        deep = sea_d > coast_edge + 0.04
        # beaches: land falls toward the sea so there is a sandy shelf
        fall = np.clip((sea_d - (coast_edge - 0.12)) / 0.12, 0, 1)
        e = e * (1 - 0.55 * fall * fall)
        if flip_x:
            e, sea, deep = e[:, ::-1], sea[:, ::-1], deep[:, ::-1]
        if flip_y:
            e, sea, deep = e[::-1], sea[::-1], deep[::-1]
        self.flip = (flip_x, flip_y)
        self.e = np.ascontiguousarray(e, dtype=np.float32)
        self.sea = np.ascontiguousarray(sea)
        self.sea_deep = np.ascontiguousarray(deep)
        wm.elev = self.e

    # ------------------------------------------------------------------ rivers
    def _rivers(self) -> None:
        W, H, e = self.W, self.H, self.e
        land = ~self.sea
        thr = np.quantile(e[land], 0.97)
        cand = np.argwhere((e >= thr) & land & (np.arange(W)[None, :] > 12) & (np.arange(W)[None, :] < W - 12)
                           & (np.arange(H)[:, None] > 12) & (np.arange(H)[:, None] < H - 12))
        src = cand[self.rng.randrange(len(cand))]
        coast = np.argwhere(self.sea & ~dilate(~self.sea, 0))  # all sea cells
        # sink: a shoreline cell in the middle band of the coast
        shore = np.argwhere(self.sea & dilate(land, 1))
        mid = shore[(shore[:, 0] > H * 0.3) & (shore[:, 0] < H * 0.72)]
        if len(mid) == 0:
            mid = shore
        snk = mid[self.rng.randrange(len(mid))]
        wob = self.noise("rivwob", 22, 3)
        base = 1.0 + 26.0 * np.square(np.clip(e, 0, 1)) + 3.0 * wob
        cost = base.astype(np.float64)
        cost[self.sea] = 1.0
        cost[:BORDER + 2, :] = -1
        cost[-BORDER - 2:, :] = -1
        cost[:, :BORDER + 2] = -1
        cost[:, -BORDER - 2:] = -1
        s, g = int(src[0]) * W + int(src[1]), int(snk[0]) * W + int(snk[1])
        cost[snk[0], snk[1]] = 1.0
        path = astar4(cost.ravel().tolist(), W, H, s, g, hw=1.6)
        if path is None:
            path = [s, g]
        pts = np.array([(p % W, p // W) for p in path], dtype=np.float64)
        k = 9
        if len(pts) > k:
            pad = np.pad(pts, ((k // 2, k // 2), (0, 0)), mode="edge")
            kern = np.ones(k) / k
            sm = np.stack([np.convolve(pad[:, 0], kern, "valid"), np.convolve(pad[:, 1], kern, "valid")], 1)
            sm[0], sm[-1] = pts[0], pts[-1]
            pts = sm
        self.river_pts = pts
        n = len(pts)
        deep_m = np.zeros((H, W), dtype=bool)
        shal_m = np.zeros((H, W), dtype=bool)
        yy, xx = np.mgrid[0:H, 0:W]
        for i in range(n):
            t = i / max(1, n - 1)
            rw = 1.5 + 2.0 * t
            px, py = pts[i]
            x0, x1 = int(max(0, px - rw - 2)), int(min(W, px + rw + 3))
            y0, y1 = int(max(0, py - rw - 2)), int(min(H, py + rw + 3))
            d = np.hypot(xx[y0:y1, x0:x1] - px, yy[y0:y1, x0:x1] - py)
            shal_m[y0:y1, x0:x1] |= d <= rw
            if t > 0.12:
                deep_m[y0:y1, x0:x1] |= d <= rw - 1.0
        self.river_deep = deep_m & ~self.sea
        self.river_shallow = shal_m & ~self.sea & ~self.river_deep
        # tributary: a shallow brook from a second high point joining the main river
        thr2 = np.quantile(e[land], 0.93)
        c2 = np.argwhere((e >= thr2) & land & (np.arange(W)[None, :] > 12) & (np.arange(H)[:, None] > 12)
                         & (np.arange(W)[None, :] < W - 12) & (np.arange(H)[:, None] < H - 12))
        far = [c for c in c2[::max(1, len(c2) // 400)] if np.hypot(c[1] - src[1], c[0] - src[0]) > 50]
        brook = np.zeros((H, W), dtype=bool)
        if far:
            b = far[self.rng.randrange(len(far))]
            targets = {int(p[1]) * W + int(p[0]) for p in pts[n // 3: 2 * n // 3]}
            cost2 = cost.copy()
            cost2[self.river_deep] = -1
            p2 = astar4(cost2.ravel().tolist(), W, H, int(b[0]) * W + int(b[1]), targets)
            if p2:
                for c in p2:
                    brook[c // W, c % W] = True
                brook = dilate(brook, 0)
                brook &= ~self.river_deep
        self.brook = brook & ~self.sea
        self.river_shallow |= self.brook & ~self.river_deep

    # ------------------------------------------------------------------ classification
    def _classify(self) -> None:
        W, H, wm = self.W, self.H, self.wm
        e = self.e
        sea, river_d, river_s = self.sea, self.river_deep, self.river_shallow
        water = sea | river_d | river_s
        land = ~sea
        elq = lambda q: float(np.quantile(e[land & ~river_d], q))
        prox = box_sums(np.pad(water, 10), 21, 21).astype(np.float32) / 441.0
        moist = 0.55 * self.noise("moist", 55, 4) + 0.9 * np.clip(prox * 2.2, 0, 1) * 0.5
        forest_n = self.noise("forest", 38, 4)
        rock_n = self.noise("rock", 14, 3)
        patch_n = self.noise("patch", 9, 2)
        ground = np.full((H, W), T.GRASS, dtype=np.uint8)
        region = np.full((H, W), T.R["meadow"], dtype=np.uint8)
        moor = land & ~river_d & ~river_s & (e > elq(0.80))
        low = land & (e < elq(0.34)) & ~moor
        marsh = low & (moist > np.quantile(moist[low], 0.40)) & ~sea
        forest = land & ~moor & ~marsh & (forest_n > np.quantile(forest_n[land], 0.58)) & (moist > np.quantile(moist[land], 0.25))
        region[forest] = T.R["forest"]
        region[marsh] = T.R["marsh"]
        region[moor] = T.R["highmoor"]
        ground[forest] = T.FOREST
        ground[moor] = T.MOOR
        ground[moor & (rock_n > 0.66)] = T.ROCK
        ground[marsh] = T.MUD
        ground[marsh & (patch_n > 0.62)] = T.BOG
        cliffs = moor & (e > elq(0.965)) & (rock_n > 0.58)
        ground[cliffs] = T.CLIFF
        near_sea = dilate(sea, 2) & land
        near_river = dilate(river_d | river_s, 1) & land
        ground[near_sea & ~moor] = T.SAND
        region[near_sea] = T.R["coast"]
        bank_sand = near_river & ~marsh & ~moor & (patch_n > 0.5)
        ground[bank_sand] = T.SAND
        ground[sea] = T.SHALLOW
        ground[self.sea_deep] = T.DEEP
        sea_edge = sea & ~self.sea_deep
        ground[sea_edge] = T.SHALLOW
        ground[river_s] = T.SHALLOW
        ground[river_d] = T.DEEP
        region[sea] = T.R["sea"]
        region[river_d | river_s] = T.R["river"]
        wm.ground, wm.region = ground, region
        self.masks = {
            "meadow": (region == T.R["meadow"]), "forest": forest, "marsh": marsh, "moor": moor,
            "sea": sea, "water": water, "cliff": ground == T.CLIFF, "sand": ground == T.SAND,
        }
        slope = gradient_mag(e)
        self.masks["flat"] = slope < np.quantile(slope, 0.62)
        wm.recompute_walk()

    def _border(self) -> None:
        g = self.wm.ground
        b = BORDER
        for sl in (g[:b, :], g[-b:, :], g[:, :b], g[:, -b:]):
            land = (sl != T.DEEP) & (sl != T.SHALLOW)
            sl[land] = T.CLIFF
        self.wm.obj[:b, :] = 0
        self.wm.obj[-b:, :] = 0
        self.wm.obj[:, :b] = 0
        self.wm.obj[:, -b:] = 0
        self.wm.recompute_walk()

    # ------------------------------------------------------------------ landmark siting
    def _fractions(self, tw: int, th: int) -> dict[str, np.ndarray]:
        key = (tw, th)
        if key in self._frac_cache:
            return self._frac_cache[key]
        area = float(tw * th)
        out = {n: box_sums(m, tw, th).astype(np.float32) / area for n, m in self.masks.items()}
        out["high"] = box_sums((self.e * 100).astype(np.int32), tw, th).astype(np.float32) / area / 100.0
        self._frac_cache[key] = out
        return out

    def _find_site(self, plan: dict, tw: int, th: int) -> tuple[int, int, bool]:
        W, H = self.W, self.H
        fr = self._fractions(tw, th)
        ny, nx = H - th + 1, W - tw + 1
        ys, xs = np.mgrid[0:ny, 0:nx]
        cx, cy = xs + tw / 2.0, ys + th / 2.0
        score = np.zeros((ny, nx), dtype=np.float32)
        want = plan.get("want", {})
        for k, wgt in want.items():
            if k == "center":
                score += wgt * (1 - np.hypot(cx - W / 2, cy - H / 2) / (W * 0.7))
            elif k == "edge":
                de = np.minimum(np.minimum(cx, cy), np.minimum(W - cx, H - cy))
                score += wgt * (1 - np.abs(de - 30) / 90.0)
            else:
                score += wgt * fr[k][:ny, :nx]
        mirror = False
        side = plan.get("sea_side")
        if side:
            sea_w = max(3, int(tw * 0.42))
            sea_r = box_sums(self.masks["sea"], sea_w, th).astype(np.float32) / (sea_w * th)
            pad_r = np.zeros((ny, nx), dtype=np.float32)
            pad_l = np.zeros((ny, nx), dtype=np.float32)
            pad_r[:, :] = sea_r[:ny, np.minimum(xs + (tw - sea_w), sea_r.shape[1] - 1)[0]]
            pad_l[:, :] = sea_r[:ny, :nx]
            right_better = (pad_r.max() >= pad_l.max())
            mirror = not right_better
            chosen = pad_r if right_better else pad_l
            other = pad_l if right_better else pad_r
            score += 3.0 * chosen - 3.0 * other
        valid = np.ones((ny, nx), dtype=bool)
        m = 10
        valid &= (xs >= m) & (ys >= m) & (xs + tw <= W - m) & (ys + th <= H - m)
        valid &= fr["cliff"][:ny, :nx] < 0.08
        if not plan.get("water_ok"):
            valid &= fr["water"][:ny, :nx] < 0.02
        else:
            valid &= fr["sea"][:ny, :nx] < 0.55
        for (px, py, pw, ph) in self.placed:
            valid &= ~((xs < px + pw + 7) & (xs + tw > px - 7) & (ys < py + ph + 7) & (ys + th > py - 7))
        near = plan.get("near")
        if near and near[0] in self.centers:
            ax, ay = self.centers[near[0]]
            d = np.hypot(cx - ax, cy - ay)
            lo, hi = near[1], near[2]
            ok = valid & (d >= lo) & (d <= hi)
            tries = 0
            while not ok.any() and tries < 5:
                lo, hi = lo * 0.7, hi * 1.35
                ok = valid & (d >= lo) & (d <= hi)
                tries += 1
            valid = ok if ok.any() else valid
        if not valid.any():
            valid = np.ones((ny, nx), dtype=bool)
            valid &= (xs >= 6) & (ys >= 6) & (xs + tw <= W - 6) & (ys + th <= H - 6)
        noise = self.np_rng("site-" + plan["id"]).random((ny, nx)).astype(np.float32) * 0.06
        score = np.where(valid, score + noise, -1e9)
        iy, ix = np.unravel_index(int(np.argmax(score)), score.shape)
        return int(ix), int(iy), mirror

    def _place_landmarks(self) -> None:
        wm = self.wm
        for plan in SETTLEMENT_PLAN + SITE_PLAN:
            tpl = self.tpls.get(plan["template"])
            if tpl is None:
                LOG.warning("template %s missing", plan["template"])
                continue
            tw, th = len(tpl["rows"][0]), len(tpl["rows"])
            x0, y0, mirror = self._find_site(plan, tw, th)
            if not tpl.get("mirror", True):
                mirror = False
            elif not plan.get("sea_side") and self.rng.chance(0.4):
                mirror = True
            st = stamp_template(wm, tpl, x0, y0, plan["id"], mirror)
            self.placed.append(st.rect)
            self.centers[plan["id"]] = (x0 + tw // 2, y0 + th // 2)
            front = st.spots.get("front") or st.spots.get("arrival") or next(iter(st.spots.values()), (x0 + tw // 2, y0 + th))
            site = Site(plan["id"], plan["kind"], tpl.get("name", plan["id"]), plan["template"], st.rect, front,
                        interior=tpl.get("meta", {}).get("interior", ""), hidden=plan.get("hidden", False),
                        unlock=plan.get("unlock", ""), faction=tpl.get("meta", {}).get("faction", ""))
            wm.sites[plan["id"]] = site
            rid = T.R["town"] if plan["kind"] == "settlement" else T.R["ruins"] if plan["kind"] in ("ruin", "stones") else None
            if rid is not None:
                wm.region[y0:y0 + th, x0:x0 + tw] = rid
        wm.index_doors()
        wm.recompute_walk()
        wm.start = wm.spots.get("wickering.arrival", wm.spots.get("wickering.gate_w", wm.start))
        # the Listening Stones stay a plain cairn on the moor until unlocked
        self._stones_feature()

    def _stones_feature(self) -> None:
        wm = self.wm
        st = wm.sites.get("listening_stones")
        tpl = self.tpls.get("listening_stones")
        if st is None or tpl is None:
            return
        x0, y0, w, h = st.rect
        cells = [(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)
                 if wm.obj[y, x] in (T.O["standing"], T.O["stairdown"], T.O["cairn"])]
        revealed = [(int(wm.ground[y, x]), int(wm.obj[y, x])) for x, y in cells]
        hidden = []
        for (x, y), (g, o) in zip(cells, revealed):
            hidden.append((g if g != T.FLAG else T.MOOR, T.O["boulder"] if o == T.O["standing"] and (x + y) % 3 == 0 else
                           T.O["stones"] if o == T.O["standing"] else 0))
        wm.features["listening_stones"] = Feature("listening_stones", cells, {"hidden": hidden, "revealed": revealed},
                                                  "hidden", label="Listening Stones")
        wm.apply_feature("listening_stones", "hidden")

    # ------------------------------------------------------------------ roads
    def _cost_grid(self) -> np.ndarray:
        wm = self.wm
        g = wm.ground
        c = np.full(g.shape, -1.0, dtype=np.float64)
        table = {T.GRASS: 1.0, T.FOREST: 1.5, T.MOOR: 1.3, T.SAND: 1.1, T.MUD: 2.6, T.BOG: 14.0, T.ROCK: 2.2,
                 T.DIRT: 0.5, T.ROAD: 0.4, T.BRIDGE: 0.5, T.PLANK: 0.6, T.FLAG: 0.8, T.COBBLE: 0.7, T.RUIN: 1.2,
                 T.FARM: 1.4, T.SHALLOW: 9.0, T.BLIGHT: 1.4}
        for gid, v in table.items():
            c[g == gid] = v
        c[wm.bmask] = -1
        blk = T.OBJ_BLOCKS[wm.obj] & (c > 0)
        c[blk] += 3.0
        c += 0.5 * self.noise("roadwob", 12, 3)
        c[c < 0] = -1
        return c

    def _carve(self, cells: list[tuple[int, int]], ground: int, width: int, cost: np.ndarray | None = None) -> None:
        wm = self.wm
        natural = (T.GRASS, T.FOREST, T.MOOR, T.SAND, T.MUD, T.ROCK, T.DIRT, T.FARM, T.BLIGHT, T.ROAD)
        nat = np.isin(wm.ground, natural)
        for (x, y) in cells:
            for dx in range(width):
                for dy in range(width if width > 1 else 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < wm.W and 0 <= yy < wm.H and nat[yy, xx] and not wm.bmask[yy, xx]:
                        if ground == T.DIRT and wm.ground[yy, xx] == T.ROAD:
                            continue
                        wm.ground[yy, xx] = ground
                        if T.OBJ_BLOCKS[wm.obj[yy, xx]] or T.OBJ_LIST[wm.obj[yy, xx]].decor:
                            wm.obj[yy, xx] = 0

    def _route(self, a: tuple[int, int], b: tuple[int, int] | set[tuple[int, int]], cost: np.ndarray
               ) -> list[tuple[int, int]] | None:
        W, H = self.W, self.H
        flat = cost.ravel().tolist()
        s = a[1] * W + a[0]
        for cell in [a] + ([b] if isinstance(b, tuple) else list(b)):
            flat[cell[1] * W + cell[0]] = max(flat[cell[1] * W + cell[0]], 0.8)
        if isinstance(b, tuple):
            goal: int | set[int] = b[1] * W + b[0]
        else:
            goal = {c[1] * W + c[0] for c in b}
        p = astar4(flat, W, H, s, goal, hw=1.5)
        if p is None:
            return None
        pts = [(c % W, c // W) for c in p]
        return self._straighten(pts, cost)

    @staticmethod
    def _straighten(pts: list[tuple[int, int]], cost: np.ndarray) -> list[tuple[int, int]]:
        """String-pull the staircase path through cells that are cheap and free, then re-rasterise."""
        if len(pts) < 3:
            return pts
        ok = lambda c: 0 <= cost[c[1], c[0]] < 4.0
        out = [pts[0]]
        anchor = 0
        i = 2
        while i < len(pts):
            if not all(ok(c) for c in line_pts(pts[anchor], pts[i])):
                out.append(pts[i - 1])
                anchor = i - 1
            i += 1
        out.append(pts[-1])
        cells: list[tuple[int, int]] = []
        for a, b in zip(out, out[1:]):
            cells.extend(line_pts(a, b))
        return cells

    def _gate_for(self, sid: str, toward: tuple[int, int]) -> tuple[int, int]:
        wm = self.wm
        gates = [v for k, v in wm.spots.items() if k.startswith(f"{sid}.gate")]
        if not gates:
            return wm.sites[sid].front
        return min(gates, key=lambda g: (g[0] - toward[0]) ** 2 + (g[1] - toward[1]) ** 2)

    def _roads(self) -> None:
        wm = self.wm
        cost = self._cost_grid()
        # settlement graph: minimum spanning tree plus the shortest missing edge (a loop for caravans)
        ids = [s for s, v in wm.sites.items() if v.kind == "settlement"]
        edges = sorted(((math.dist(self.centers[a], self.centers[b]), a, b) for i, a in enumerate(ids) for b in ids[i + 1:]))
        parent = {s: s for s in ids}

        def find(s):
            while parent[s] != s:
                s = parent[s]
            return s
        chosen, rest = [], []
        for d, a, b in edges:
            if find(a) != find(b):
                parent[find(a)] = find(b)
                chosen.append((a, b))
            else:
                rest.append((a, b))
        if rest:
            chosen.append(rest[0])
        self.road_edges = chosen
        for a, b in chosen:
            ga = self._gate_for(a, self.centers[b])
            gb = self._gate_for(b, self.centers[a])
            # keep other settlements' interiors expensive so highways skirt them
            c2 = cost.copy()
            for sid in ids:
                if sid in (a, b):
                    continue
                x, y, w, h = wm.sites[sid].rect
                c2[y:y + h, x:x + w] = np.where(c2[y:y + h, x:x + w] > 0, c2[y:y + h, x:x + w] * 6, -1)
            path = self._route(ga, gb, c2)
            if path is None:
                LOG.warning("no road %s-%s", a, b)
                continue
            wm.roads.append(path)
            self._carve(path, T.ROAD, 2)
            for p in path:
                for dx in (0, 1):
                    for dy in (0, 1):
                        xx, yy = p[0] + dx, p[1] + dy
                        if 0 <= xx < self.W and 0 <= yy < self.H and cost[yy, xx] > 0:
                            cost[yy, xx] = 0.35
        # trails from every other landmark to the nearest road cell
        road_cells = [c for r in wm.roads for c in r]
        stub_done = False
        for sid, site in wm.sites.items():
            if site.kind == "settlement":
                continue
            fx, fy = site.front
            if not wm.roads:
                break
            targets = set(road_cells[::3]) or set(road_cells)
            near = sorted(targets, key=lambda c: (c[0] - fx) ** 2 + (c[1] - fy) ** 2)[:40]
            c2 = cost.copy()
            for oid, osite in wm.sites.items():
                if oid == sid:
                    continue
                x, y, w, h = osite.rect
                c2[y:y + h, x:x + w] = np.where(c2[y:y + h, x:x + w] > 0, c2[y:y + h, x:x + w] * 4, -1)
            path = self._route((fx, fy), set(near), c2)
            if path:
                self._carve(path, T.DIRT, 1)
                wm.roads.append(path)
        # the road you arrived by: a trail from the Wickering arrival marker to the map edge
        if "wickering.arrival" in wm.spots:
            ax, ay = wm.spots["wickering.arrival"]
            edge_pts = [(BORDER + 2, ay), (self.W - BORDER - 3, ay), (ax, BORDER + 2), (ax, self.H - BORDER - 3)]
            tgt = min(edge_pts, key=lambda c: abs(c[0] - ax) + abs(c[1] - ay))
            path = self._route((ax, ay), tgt, cost)
            if path:
                self._carve(path, T.DIRT, 1)
                wm.arrival_trail = path
        wm.recompute_walk()

    # ------------------------------------------------------------------ crossings (after rivers + roads exist)
    def _crossings(self) -> None:
        """Bridges and a ford across the main river.  Built after roads: roads treat water as expensive, so we
        build the crossings first (see ``_rivers_cross`` call order in ``_classify``)."""

    # ------------------------------------------------------------------ lamps
    def _lamps(self) -> None:
        wm = self.wm
        lamp = T.O["lamp"]
        for (x, y), v in list(np.ndenumerate(wm.obj == lamp)):
            pass
        ys, xs = np.nonzero(wm.obj == lamp)
        for y, x in zip(ys.tolist(), xs.tolist()):
            wm.lamps.append({"x": x, "y": y, "group": self._nearest_site(x, y)})
        # road lamps near every settlement gate
        for road in wm.roads:
            if len(road) < 20:
                continue
            for end in (road[:34], road[-34:]):
                for i in range(6, len(end), 7):
                    x, y = end[i]
                    for dx, dy in ((2, 0), (-1, 0), (0, 2), (0, -1)):
                        xx, yy = x + dx, y + dy
                        if (0 <= xx < self.W and 0 <= yy < self.H and wm.ground[yy, xx] in (T.GRASS, T.FOREST, T.MOOR)
                                and wm.obj[yy, xx] == 0 and not wm.bmask[yy, xx]):
                            wm.obj[yy, xx] = lamp
                            wm.lamps.append({"x": xx, "y": yy, "group": "road"})
                            break

    def _nearest_site(self, x: int, y: int) -> str:
        best, bd = "road", 1e9
        for sid, c in self.centers.items():
            if self.wm.sites[sid].kind != "settlement":
                continue
            d = (c[0] - x) ** 2 + (c[1] - y) ** 2
            if d < bd:
                best, bd = sid, d
        return best

    # ------------------------------------------------------------------ decoration
    def _decorate(self) -> None:
        wm, W, H = self.wm, self.W, self.H
        r = self.np_rng("deco")
        ground, obj, region = wm.ground, wm.obj, wm.region
        free = (obj == 0) & ~wm.bmask & T.GROUND_WALK[ground]
        road_m = np.isin(ground, (T.ROAD, T.DIRT, T.COBBLE, T.BRIDGE, T.PLANK, T.FLAG))
        keep_clear = dilate(road_m, 1)
        for sid, site in wm.sites.items():
            x, y, w, h = site.rect
            keep_clear[max(0, y - 1):y + h + 1, max(0, x - 1):x + w + 1] = True
        for pos in wm.spots.values():
            keep_clear[max(0, pos[1] - 1):pos[1] + 2, max(0, pos[0] - 1):pos[0] + 2] = True
        free &= ~keep_clear
        free[:BORDER + 1] = free[-BORDER - 1:] = False
        free[:, :BORDER + 1] = free[:, -BORDER - 1:] = False
        clear_n = self.noise("clearing", 17, 3)
        grove_n = self.noise("grove", 21, 3)
        flower_n = self.noise("flower", 8, 2)
        near_water = dilate(np.isin(ground, (T.DEEP, T.SHALLOW, T.BOG)), 2)
        rnd = r.random((H, W))
        rnd2 = r.random((H, W))
        reg = region
        forest = (reg == T.R["forest"]) & free
        meadow = (reg == T.R["meadow"]) & free & (ground == T.GRASS)
        moor = (reg == T.R["highmoor"]) & free
        marsh = (reg == T.R["marsh"]) & free
        coast = (reg == T.R["coast"]) & free

        def put(mask, ids, p, rr=None):
            rr = rnd if rr is None else rr
            sel = mask & (rr < p) & (obj == 0)
            if isinstance(ids, int):
                obj[sel] = ids
            else:
                pick = (rnd2[sel] * len(ids)).astype(int)
                obj[sel] = np.array(ids, dtype=np.uint8)[pick]

        glade = clear_n < 0.30
        put(forest & glade, [T.O["oak"]] * 3 + [T.O["pine"]], 0.04)
        put(forest & ~glade, [T.O["oak"]] * 3 + [T.O["pine"]] * 2, 0.34)
        put(meadow, T.O["oak"], 0.012)
        put(meadow & (grove_n > 0.68), T.O["oak"], 0.20)
        put(moor, [T.O["pine"], T.O["dead"]], 0.011)
        put(marsh & ~near_water, [T.O["willow"], T.O["dead"], T.O["willow"]], 0.035)
        put(forest | meadow, T.O["bush"], 0.022, rnd2)
        put((meadow | forest) & (grove_n < 0.35), T.O["berry"], 0.006, rnd2)
        put(moor & (ground == T.ROCK), T.O["boulder"], 0.08)
        put(moor, T.O["boulder"], 0.014, rnd2)
        put(moor, T.O["stones"], 0.03, 1 - rnd)
        put(moor & (ground == T.MOOR), T.O["heather"], 0.012, 1 - rnd2)
        put(moor, T.O["ore"], 0.0025, rnd * 0.9 + 0.05 * rnd2)
        put((marsh | coast) & near_water, T.O["reeds"], 0.30)
        put(marsh, T.O["cattail"], 0.07, rnd2)
        put(marsh & near_water, T.O["reedmint"], 0.04, 1 - rnd)
        put(meadow & (flower_n > 0.52), T.O["flowers"], 0.22, rnd2)
        put(meadow, T.O["tuft"], 0.13, 1 - rnd)
        put(forest, T.O["tuft"], 0.06, 1 - rnd2)
        put(forest, T.O["mushroom"], 0.007, rnd2 * 0.8 + 0.2 * rnd)
        put(meadow & (grove_n < 0.4), T.O["flax"], 0.006, 1 - rnd)
        put(coast & (ground == T.SAND), T.O["stones"], 0.02, rnd2)
        # river banks get a few reeds as well
        put(dilate(np.isin(ground, (T.SHALLOW,)), 1) & free & (reg != T.R["highmoor"]), T.O["reeds"], 0.12, rnd2)
        wm.recompute_walk()

    # ------------------------------------------------------------------ crossings
    def build_crossings(self) -> None:
        wm = self.wm
        pts = self.river_pts
        n = len(pts)
        if n < 30:
            return
        sites = [("ford", 0.30), ("kestrel_bridge", 0.52), ("stone_bridge", 0.76)]
        taken: list[tuple[float, float]] = []
        for name, t in sites:
            i0 = int(n * t)
            best = None
            for j in range(max(6, i0 - int(n * 0.08)), min(n - 6, i0 + int(n * 0.08))):
                px, py = pts[j]
                if not (BORDER + 8 < px < self.W - BORDER - 8 and BORDER + 8 < py < self.H - BORDER - 8):
                    continue
                if any(math.hypot(px - q[0], py - q[1]) < 30 for q in taken):
                    continue
                if self.sea[int(py), int(px)] or any(self.sea[min(self.H - 1, int(py + dy)), min(self.W - 1, int(px + dx))]
                                                    for dx in (-6, 6) for dy in (-6, 6)):
                    continue
                # prefer straight, narrow places
                tx, ty = pts[min(n - 1, j + 4)] - pts[max(0, j - 4)]
                va, vb = pts[min(n - 1, j + 8)] - pts[j], pts[j] - pts[max(0, j - 8)]
                curve = abs(float(va[0] * vb[1] - va[1] * vb[0]))
                score = curve + self.rng.random() * 0.5
                if best is None or score < best[0]:
                    best = (score, j)
            if best is None:
                continue
            taken.append(tuple(pts[best[1]]))
            self._build_crossing(name, best[1])

    def _build_crossing(self, name: str, j: int) -> None:
        wm = self.wm
        pts = self.river_pts
        n = len(pts)
        c = pts[j]
        tvec = pts[min(n - 1, j + 4)] - pts[max(0, j - 4)]
        tvec = tvec / (np.hypot(*tvec) or 1.0)
        perp = np.array([-tvec[1], tvec[0]])
        water = (wm.ground == T.DEEP) | (wm.ground == T.SHALLOW)

        def wet(s: float, off: float = 0.0) -> bool:
            x, y = int(round(c[0] + perp[0] * s + tvec[0] * off)), int(round(c[1] + perp[1] * s + tvec[1] * off))
            return 0 <= x < self.W and 0 <= y < self.H and bool(water[y, x])
        half = 0
        for s in range(0, 14):
            if wet(s) or wet(-s):
                half = s
        half += 2
        deck: list[tuple[int, int]] = []
        for s in range(-half, half + 1):
            for off in (0.0, 1.0) if name != "ford" else (-1.0, 0.0, 1.0, 2.0):
                x, y = int(round(c[0] + perp[0] * s + tvec[0] * off)), int(round(c[1] + perp[1] * s + tvec[1] * off))
                if 0 <= x < self.W and 0 <= y < self.H and (x, y) not in deck:
                    deck.append((x, y))
        orig = {d: int(wm.ground[d[1], d[0]]) for d in deck}
        if name == "ford":
            for (x, y) in deck:
                if orig[(x, y)] in (T.DEEP, T.SHALLOW):
                    wm.ground[y, x] = T.SHALLOW
                    wm.obj[y, x] = T.O["stones"] if (x * 7 + y * 3) % 4 == 0 else 0
                elif orig[(x, y)] not in (T.CLIFF,):
                    wm.ground[y, x] = T.DIRT
                    wm.obj[y, x] = 0
            wm.features["ford"] = Feature("ford", [], {"normal": []}, "normal", "Old ford")
            wm.spots["ford.west"] = (int(round(c[0] - perp[0] * (half + 1))), int(round(c[1] - perp[1] * (half + 1))))
            wm.spots["ford.east"] = (int(round(c[0] + perp[0] * (half + 1))), int(round(c[1] + perp[1] * (half + 1))))
            return
        cells, built, broken = [], [], []
        for (x, y) in deck:
            og = orig[(x, y)]
            if og in (T.DEEP, T.SHALLOW):
                wm.ground[y, x] = T.BRIDGE
                wm.obj[y, x] = 0
                cells.append((x, y))
                built.append((T.BRIDGE, 0))
            elif og not in (T.CLIFF,):
                wm.ground[y, x] = T.DIRT if wm.ground[y, x] != T.ROAD else T.ROAD
                wm.obj[y, x] = 0
        if name == "kestrel_bridge" and len(cells) >= 8:
            # stub planks stay at each bank; the middle of the span is gone until repaired
            order = sorted(range(len(cells)), key=lambda k: (cells[k][0] - c[0]) * perp[0] + (cells[k][1] - c[1]) * perp[1])
            keep = set(order[:4] + order[-4:])
            broken = []
            for k, (x, y) in enumerate(cells):
                if k in keep:
                    broken.append((T.BRIDGE, T.O["brokenplank"] if k in (order[3], order[-4]) else 0))
                else:
                    broken.append((T.DEEP if orig[(x, y)] == T.DEEP or (x + y) % 2 == 0 else T.SHALLOW, 0))
            # the shallow bank cells under the gap must not make the gap walkable
            broken = [(T.DEEP, o) if g == T.SHALLOW else (g, o) for g, o in broken]
            wm.features["kestrel_bridge"] = Feature("kestrel_bridge", cells, {"built": built, "broken": broken}, "broken",
                                                    "Kestrel Bridge")
            wm.apply_feature("kestrel_bridge", "broken")
        wm.spots[f"{name}.west"] = (int(round(c[0] - perp[0] * (half + 2))), int(round(c[1] - perp[1] * (half + 2))))
        wm.spots[f"{name}.east"] = (int(round(c[0] + perp[0] * (half + 2))), int(round(c[1] + perp[1] * (half + 2))))

    # ------------------------------------------------------------------ caches
    def _free_cell(self, mask: np.ndarray, rng_label: str, min_dist_road: int = 6, tries: int = 400
                   ) -> tuple[int, int] | None:
        wm = self.wm
        r = self.rng.child(rng_label)
        road_m = np.isin(wm.ground, (T.ROAD, T.DIRT, T.COBBLE, T.BRIDGE, T.PLANK))
        near_road = dilate(road_m, min_dist_road)
        ok = mask & ~near_road & wm.walk
        for sid, site in wm.sites.items():
            x, y, w, h = site.rect
            ok[max(0, y - 6):y + h + 6, max(0, x - 6):x + w + 6] = False
        ok[:BORDER + 6] = ok[-BORDER - 6:] = False
        ok[:, :BORDER + 6] = ok[:, -BORDER - 6:] = False
        cells = np.argwhere(ok)
        if len(cells) == 0:
            return None
        y, x = cells[r.randrange(len(cells))]
        return int(x), int(y)

    def _caches(self) -> None:
        wm = self.wm
        m = self.masks
        plans = [("tree_ring", "forest", 2), ("chime_door", "moor", 1), ("chime_door", "forest", 1),
                 ("cairn", "moor", 2), ("dig", "marsh", 1), ("tree_ring", "meadow", 1)]
        n = 0
        free_forest = (wm.region == T.R["forest"])
        free_moor = (wm.region == T.R["highmoor"]) & (wm.ground != T.CLIFF)
        free_marsh = (wm.region == T.R["marsh"]) & (wm.ground == T.MUD)
        free_meadow = (wm.region == T.R["meadow"]) & (wm.ground == T.GRASS)
        masks = {"forest": free_forest, "moor": free_moor, "marsh": free_marsh, "meadow": free_meadow}
        for kind, biome, count in plans:
            for k in range(count):
                cell = self._free_cell(masks[biome], f"cache-{kind}-{biome}-{k}")
                if cell is None:
                    continue
                x, y = cell
                cid = f"cache_{n}"
                n += 1
                self._make_cache(cid, kind, x, y, biome)

    def _clear_box(self, x0: int, y0: int, x1: int, y1: int, ground: int | None = None) -> None:
        wm = self.wm
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if 0 <= x < self.W and 0 <= y < self.H:
                    wm.obj[y, x] = 0
                    if ground is not None:
                        wm.ground[y, x] = ground

    def _make_cache(self, cid: str, kind: str, x: int, y: int, biome: str) -> None:
        wm = self.wm
        chest = T.O["chest"]
        loot = {"tree_ring": "cache_woods", "chime_door": "cache_hidden", "cairn": "cache_moor", "dig": "cache_marsh"}[kind]
        if kind == "tree_ring":
            self._clear_box(x - 3, y - 3, x + 3, y + 3)
            ring = [(-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2), (-2, -1), (2, -1), (-2, 0), (2, 0), (-2, 1), (2, 1),
                    (-2, 2), (-1, 2), (1, 2), (2, 2)]   # the gap is at (0, 2)
            for dx, dy in ring:
                wm.obj[y + dy, x + dx] = T.O["ringtree"]
            wm.obj[y, x] = chest
            wm.obj[y + 1, x - 1] = T.O["mushroom"] if (x + y) % 2 else T.O["flowers"]
            for dx in (-1, 0, 1):
                wm.ground[y + 3, x + dx] = wm.ground[y + 3, x + dx]
            entry = (x, y + 3)
        elif kind == "chime_door":
            self._clear_box(x - 3, y - 3, x + 3, y + 2, T.ROCK)
            for dx in range(-3, 4):
                wm.ground[y - 2, x + dx] = T.CLIFF
                wm.ground[y - 3, x + dx] = T.CLIFF
            for dy in (-1, 0):
                wm.ground[y + dy, x - 2] = T.CLIFF
                wm.ground[y + dy, x + 2] = T.CLIFF
            wm.obj[y - 1, x] = chest
            wm.ground[y - 1, x] = T.CRYPT
            wm.ground[y, x] = T.ROCK
            wm.obj[y, x] = T.O["hiddendoor"]
            wm.ground[y - 1, x - 1] = T.CRYPT
            wm.ground[y - 1, x + 1] = T.CRYPT
            for dx in (-1, 1):
                wm.ground[y, x + dx] = T.CLIFF
            entry = (x, y + 2)
            wm.obj[y + 1, x] = 0
            wm.obj[y + 1, x - 2] = T.O["stones"]
        elif kind == "cairn":
            self._clear_box(x - 1, y - 1, x + 1, y + 1)
            wm.obj[y, x] = T.O["cairn"]
            wm.obj[y + 1, x - 1] = T.O["stones"]
            entry = (x, y + 1)
        else:  # dig
            self._clear_box(x - 1, y - 1, x + 1, y + 1)
            wm.obj[y, x] = T.O["dig"]
            wm.obj[y - 1, x + 1] = T.O["reeds"]
            entry = (x, y + 1)
        wm.walk[y, x] = bool(T.GROUND_WALK[wm.ground[y, x]] and not T.OBJ_BLOCKS[wm.obj[y, x]])
        wm.caches.append({"id": cid, "kind": kind, "x": x, "y": y, "loot": loot, "biome": biome, "entry": entry,
                          "landmark": self._landmark_label(x, y)})
        wm.recompute_walk(max(0, x - 5), max(0, y - 5), min(self.W, x + 6), min(self.H, y + 6))

    def _landmark_label(self, x: int, y: int) -> str:
        wm = self.wm
        best, bd = "", 1e18
        for sid, s in wm.sites.items():
            if s.hidden:
                continue
            cx, cy = s.rect[0] + s.rect[2] / 2, s.rect[1] + s.rect[3] / 2
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d < bd:
                best, bd = sid, d
        return best

    # ------------------------------------------------------------------ spawns
    def _spawns(self) -> None:
        wm = self.wm
        for m in wm.markers:
            if m.kind == "spawn":
                wm.spawns.append({"id": f"{m.site}.{len(wm.spawns)}", "enemy": m.data.get("enemy", "wolf"),
                                  "count": int(m.data.get("count", 1)), "x": m.x, "y": m.y,
                                  "radius": int(m.data.get("radius", 5)), "area": "overworld",
                                  "unique": bool(m.data.get("unique", False)), "site": m.site})
        bog = np.argwhere((wm.ground == T.BOG) & wm.walk)
        r = self.rng.child("bogwights")
        if len(bog):
            chosen: list[tuple[int, int]] = []
            for _ in range(60):
                y, x = bog[r.randrange(len(bog))]
                if all(math.hypot(x - cx, y - cy) > 22 for cx, cy in chosen):
                    chosen.append((int(x), int(y)))
                if len(chosen) >= 7:
                    break
            for i, (x, y) in enumerate(chosen):
                wm.spawns.append({"id": f"bog.{i}", "enemy": "bogwight", "count": 1, "x": x, "y": y, "radius": 3,
                                  "area": "overworld", "unique": False, "site": ""})
        # roaming wolf packs deep in the greywood
        f = self._free_cell((wm.region == T.R["forest"]), "wolfpack-a", 10)
        for i, lab in enumerate(("wolfpack-a", "wolfpack-b", "wolfpack-c")):
            cell = self._free_cell((wm.region == T.R["forest"]) | (wm.region == T.R["highmoor"]), lab, 12)
            if cell:
                wm.spawns.append({"id": f"pack.{i}", "enemy": "wolf", "count": 3, "x": cell[0], "y": cell[1],
                                  "radius": 6, "area": "overworld", "unique": False, "site": ""})
        cell = self._free_cell((wm.region == T.R["meadow"]) | (wm.region == T.R["forest"]), "roadside", 4)
        if cell:
            wm.spawns.append({"id": "roadside.0", "enemy": "bandit", "count": 2, "x": cell[0], "y": cell[1], "radius": 4,
                              "area": "overworld", "unique": False, "site": ""})

    def _finish(self) -> None:
        wm = self.wm
        wm.recompute_walk()
        wm.index_doors()
        wm.names = {sid: s.name for sid, s in wm.sites.items()}


def _build_attempt(seed: int, templates: dict[str, dict], attempt: int, size: int) -> WorldMap:
    g = Generator(seed, templates, size, attempt)
    # crossings must exist before roads route over them, so build up to roads manually
    g._fields()
    g._rivers()
    g._classify()
    g._border()
    g.build_crossings()
    g.wm.recompute_walk()
    g._place_landmarks()
    g._roads()
    g._lamps()
    g._decorate()
    g._caches()
    g._spawns()
    g._finish()
    g.wm.generator_info = {"flip": g.flip}
    return g.wm


# ------------------------------------------------------------------------------------------------ validation
def key_targets(wm: WorldMap) -> dict[str, tuple[int, int]]:
    """Everything the player must be able to reach: settlement spots, site fronts, entrances, caches, markers."""
    t: dict[str, tuple[int, int]] = {}
    for sid, s in wm.sites.items():
        t[f"site:{sid}"] = s.front
    for name, pos in wm.spots.items():
        if name.split(".")[0] in wm.sites and not name.endswith(".door") or name.endswith(".door"):
            t[f"spot:{name}"] = pos
    for c in wm.caches:
        t[f"cache:{c['id']}"] = tuple(c["entry"])
    for m in wm.markers:
        if m.kind in ("entrance", "chest", "npc", "quest"):
            t[f"marker:{m.site}:{m.kind}:{m.x},{m.y}"] = (m.x, m.y + 1) if not wm.is_walk(m.x, m.y) else (m.x, m.y)
    return t


def validate(wm: WorldMap, variants: tuple[tuple[str, str], ...] = (("kestrel_bridge", "broken"),
                                                                    ("kestrel_bridge", "built"))) -> list[str]:
    """Return problems: targets unreachable from the start cell under each feature variant."""
    problems: list[str] = []
    saved = {fid: _current_variant(wm, fid) for fid in {v[0] for v in variants} if fid in wm.features}
    for fid, var in variants:
        if fid not in wm.features:
            continue
        wm.apply_feature(fid, var)
        if not wm.is_walk(*wm.start):
            problems.append(f"[{fid}={var}] start cell {wm.start} not walkable")
            continue
        reach = flood(wm.walk, wm.start)
        for name, (x, y) in key_targets(wm).items():
            if not (0 <= x < wm.W and 0 <= y < wm.H) or not reach[y, x]:
                problems.append(f"[{fid}={var}] unreachable {name} at {(x, y)}")
    for fid, var in saved.items():
        wm.apply_feature(fid, var)
    return problems


def _current_variant(wm: WorldMap, fid: str) -> str:
    f = wm.features[fid]
    for name, states in f.variants.items():
        if all(wm.ground[y, x] == g or g < 0 for (x, y), (g, o) in zip(f.cells, states)):
            return name
    return f.default


def repair(wm: WorldMap, problems: list[str]) -> int:
    """Carve a corridor from each unreachable target to the reachable region (deterministic Dijkstra)."""
    fixed = 0
    W, H = wm.W, wm.H
    for fid, var in (("kestrel_bridge", "broken"),):
        if fid in wm.features:
            wm.apply_feature(fid, var)
    reach = flood(wm.walk, wm.start)
    names = []
    for p in problems:
        if "unreachable" in p:
            names.append(p.split("unreachable ")[1].split(" at ")[0])
    targets = key_targets(wm)
    for nm in sorted(set(names)):
        if nm not in targets:
            continue
        x, y = targets[nm]
        if reach[y, x]:
            continue
        cost = np.full((H, W), 6.0)
        cost[wm.bmask] = -1
        cost[wm.ground == T.DEEP] = 22.0
        cost[wm.ground == T.CLIFF] = 14.0
        cost[wm.ground == T.VOID] = -1
        cost[np.arange(H)[:, None].repeat(W, 1) < 2] = -1
        cost[(wm.walk)] = 1.0
        flat = cost.ravel().tolist()
        goal = {int(i) for i in np.flatnonzero(reach.ravel())}
        flat[y * W + x] = max(flat[y * W + x], 1.0)
        path = astar4(flat, W, H, y * W + x, goal, hw=1.0)
        if not path:
            continue
        for c in path:
            cx, cy = c % W, c // W
            g = wm.ground[cy, cx]
            if g in (T.DEEP,):
                wm.ground[cy, cx] = T.BRIDGE
            elif g == T.CLIFF:
                wm.ground[cy, cx] = T.DIRT
            elif g in (T.SHALLOW, T.BOG):
                pass
            wm.obj[cy, cx] = 0
        wm.recompute_walk()
        reach = flood(wm.walk, wm.start)
        fixed += 1
    return fixed


def generate(seed: int, templates: dict[str, dict], size: int = SIZE, max_attempts: int = 6) -> WorldMap:
    """Deterministic world for ``seed``.  Tries repair, then successive attempts, then returns the best effort."""
    best: tuple[int, WorldMap] | None = None
    for attempt in range(max_attempts):
        wm = _build_attempt(seed, templates, attempt, size)
        problems = validate(wm)
        if problems:
            repair(wm, problems)
            problems = validate(wm)
        wm.problems = problems
        if not problems:
            return wm
        LOG.warning("seed %s attempt %d: %d problems (%s)", seed, attempt, len(problems), problems[:2])
        if best is None or len(problems) < best[0]:
            best = (len(problems), wm)
    assert best is not None
    return best[1]
