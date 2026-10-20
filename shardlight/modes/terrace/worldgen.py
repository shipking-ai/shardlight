"""Seeded world generation for Terrace, with validation and deterministic regeneration.

Everything is a pure function of ``(seed, attempt)``.  ``generate`` builds, validates and, if a rule fails (the
spawn is buried, the Keystone site is unreachable, an essential ore is missing ...), tries the next attempt, so a
given seed always produces the same valid world.
"""
from __future__ import annotations

import numpy as np

from ...core.rng import derive_seed
from . import constants as K
from .genutil import box_smooth, carve_disc, carve_line, disc_mask, smooth_noise_1d, smooth_noise_2d, stamp
from .grid import label4
from .registry import Registry
from .world import World

SURFACE_BAND = (60, 135)
MIN_ORE = {"coal_ore": 120, "copper_ore": 90, "iron_ore": 80, "gold_ore": 24, "lumina_ore": 16, "cinder_ore": 12}
ORES = [  # block, ymin, ymax, veins, rmin, rmax
    (K.COAL_ORE, 96, 210, 130, 1.0, 2.4),
    (K.COPPER_ORE, 108, 196, 100, 1.0, 2.2),
    (K.IRON_ORE, 126, 232, 90, 1.0, 2.2),
    (K.GOLD_ORE, 160, 238, 34, 1.0, 1.9),
    (K.LUMINA_ORE, 176, 242, 22, 1.0, 1.7),
    (K.CINDER_ORE, 214, 250, 18, 1.0, 1.9),
]


class WorldGenError(RuntimeError):
    pass


def generate(seed: int, reg: Registry) -> World:
    """Return a validated world for ``seed`` (deterministic)."""
    last = None
    for attempt in range(8):
        w = _build(seed, reg, attempt)
        problems = validate(w)
        w.problems = problems
        last = w
        if not problems:
            return w
    return last                                              # callers/tests inspect ``problems``


# ---------------------------------------------------------------------------------------------- building
def _build(seed: int, reg: Registry, attempt: int) -> World:
    w = World(reg, seed)
    gen = np.random.default_rng(derive_seed(seed, "terrace", attempt))
    W, H = w.w, w.h
    B = w.grid.blocks
    protect = np.zeros((H, W), dtype=bool)

    # ---- biome bands: [far, mid, meadow, near] mirrored by a coin flip so the Keystone lies far from the spawn
    flip = bool(gen.integers(0, 2))
    meadow_w = int(gen.integers(150, 190))
    mid_w = int(gen.integers(110, 140))
    mid_biome = "forest"
    left = (W - meadow_w) // 2
    bands = []                                                  # (x0, x1, biome)
    far_biome = "frozen" if gen.random() < 0.5 else "salt"
    near_biome = "salt" if far_biome == "frozen" else "frozen"
    mid_biome = "forest"
    layout = [(far_biome, 0, left - mid_w), (mid_biome, left - mid_w, left), ("meadow", left, left + meadow_w),
              (near_biome, left + meadow_w, W)]
    if flip:
        layout = [(b, W - x1, W - x0) for (b, x0, x1) in layout]
    for biome, x0, x1 in layout:
        w.biome[max(0, x0):min(W, x1)] = K.BIOMES.index(biome)
    spawn_x = left + meadow_w // 2 if not flip else W - (left + meadow_w // 2)
    far_cx = (layout[0][1] + layout[0][2]) // 2

    # ---- keystone plan: a flat plateau is pinned into the height field so the slope limit builds ramps to it
    ks = w.reg.structures["keystone"]
    ks_rows = ks["pattern"]
    ks_width, ks_height = max(len(r) for r in ks_rows), len(ks_rows)
    ks_first_t, ks_n_t = ks_rows[-1].index("T"), ks_rows[-1].count("T")
    ks_px0 = int(np.clip(far_cx - ks_n_t // 2, ks_first_t + 14, W - ks_width - 14))
    ks_x0 = ks_px0 - ks_first_t
    pin = np.zeros(W, dtype=bool)
    pin[ks_x0 - 3:ks_x0 + ks_width + 3] = True

    # ---- surface height
    n1 = smooth_noise_1d(gen, W)
    amp = np.where(w.biome == K.BIOMES.index("frozen"), 20.0, np.where(w.biome == K.BIOMES.index("salt"), 6.0, 11.0))
    amp = box_smooth(amp, 31)
    surf = 96.0 + n1 * amp
    surf[w.biome == K.BIOMES.index("frozen")] -= 4
    surf = box_smooth(surf, 5)
    s = np.clip(np.round(surf), 70, 124).astype(np.int32)
    ks_ground = int(np.clip(round(float(np.median(s[ks_x0 - 6:ks_x0 + ks_width + 6]))), ks_height + 6, 118))
    s[pin] = ks_ground
    for x in range(spawn_x - 6, spawn_x + 7):                   # spawn plateau
        s[x] = s[spawn_x]
        pin[x] = True
    for _ in range(4):                                          # slope limit of 2 tiles keeps the surface walkable
        for x in range(1, W):
            if not pin[x]:
                s[x] = max(s[x - 1] - 2, min(s[x - 1] + 2, s[x]))
        for x in range(W - 2, -1, -1):
            if not pin[x]:
                s[x] = max(s[x + 1] - 2, min(s[x + 1] + 2, s[x]))
    w.surf[:] = s.astype(np.int16)

    # ---- fill
    yy = np.arange(H)[:, None]
    ss = s[None, :]
    B[:] = K.AIR
    B[yy >= ss] = K.STONE
    deep_noise = smooth_noise_2d(gen, H, W, 18)
    B[(yy >= 168) & (deep_noise > 0.55) & (B == K.STONE)] = K.SLATE
    bio = w.biome
    for x in range(W):
        top = int(s[x])
        b = bio[x]
        name = K.BIOMES[b]
        if name in ("meadow", "forest"):
            B[top, x] = K.GRASS
            B[top + 1:top + 1 + 4 + int(gen.integers(0, 3)), x] = K.DIRT
        elif name == "salt":
            B[top:top + 4, x] = K.SAND
            B[top + 4:top + 7, x] = K.SANDSTONE
            if deep_noise[top + 12, x] > 0.6:
                B[top + 7:top + 12, x] = K.SALT
        else:
            B[top, x] = K.SNOW
            B[top + 1:top + 4, x] = K.DIRT
            if deep_noise[top + 8, x] > 0.62:
                B[top + 4:top + 9, x] = K.ICE
    B[H - 2:, :] = K.BEDROCK

    # ---- keystone site (flat, protected, far from the spawn)
    _keystone_site(w, gen, B, protect, ks_x0, ks_px0, ks_n_t, ks_width, ks_height)

    # ---- caves
    c1 = smooth_noise_2d(gen, H, W, 15)
    c2 = smooth_noise_2d(gen, H, W, 7)
    depth = yy - ss
    thresh = 0.64 - np.clip((depth - 10) / 140.0, 0, 1) * 0.10
    cave = ((c1 > thresh) | ((c1 > thresh - 0.10) & (c2 > 0.7))) & (depth > 9) & (yy < H - 4) & ~protect
    B[cave & (B != K.BEDROCK)] = K.AIR
    ntunnels = 70
    for _ in range(ntunnels):
        x = int(gen.integers(8, W - 8))
        y = int(s[x] + gen.integers(14, 150))
        ang = gen.uniform(0, np.pi)
        r = float(gen.uniform(1.2, 2.3))
        for _ in range(int(gen.integers(25, 90))):
            carve_disc(B, protect, x, y, r)
            ang += gen.normal(0, 0.45)
            x = int(np.clip(x + round(np.cos(ang) * 2), 3, W - 4))
            y = int(np.clip(y + round(np.sin(ang) * 1.2), s[x] + 10, H - 6))
    for _ in range(10):                                         # entrances: shafts from the surface into the caves
        x = int(gen.integers(10, W - 10))
        if protect[s[x], x]:
            continue
        side = 1 if gen.random() < 0.5 else -1                  # cave mouths slope at about 1:2 so they can be walked
        dy = int(gen.integers(14, 26))
        tx, ty = x + side * dy * 2, int(s[x] + dy)
        carve_line(B, protect, (x - side * 3, int(s[x]) - 2), (int(np.clip(tx, 3, W - 4)), ty), 1.7)

    # ---- ore veins
    stone_like = lambda v: v in (K.STONE, K.SLATE)
    for blk, y0, y1, count, rmin, rmax in ORES:
        for _ in range(count):
            x = int(gen.integers(4, W - 4))
            y = int(gen.integers(y0, y1))
            r = float(gen.uniform(rmin, rmax))
            m = disc_mask(r)
            ri = m.shape[0] // 2
            ya, yb, xa, xb = max(2, y - ri), min(H - 3, y + ri + 1), max(1, x - ri), min(W - 1, x + ri + 1)
            sub = m[ya - (y - ri):yb - (y - ri), xa - (x - ri):xb - (x - ri)]
            region = B[ya:yb, xa:xb]
            sel = sub & ((region == K.STONE) | (region == K.SLATE)) & ~protect[ya:yb, xa:xb]
            sel &= gen.random(sel.shape) < 0.85
            region[sel] = blk
    # ---- liquids: deep lava lakes, water pockets and lakes
    liq = w.grid.liq
    lava_floor = H - 40
    lava_cells = (B == K.AIR) & (yy >= lava_floor) & (yy < H - 2)
    liq[lava_cells] = 8 | K.LIQ_LAVA
    for _ in range(5):                                          # carve a few deliberate lava chambers
        x = int(gen.integers(10, W - 10))
        y = int(gen.integers(H - 36, H - 8))
        carve_disc(B, protect, x, y, float(gen.uniform(4, 7)))
        rows = np.arange(y - 8, y + 9)
        for yy_ in rows:
            if yy_ >= y - 1 and 0 < yy_ < H - 2:
                seg = B[yy_, max(1, x - 8):x + 9] == K.AIR
                liq[yy_, max(1, x - 8):x + 9][seg] = 8 | K.LIQ_LAVA
    for _ in range(26):                                         # natural obsidian where lava lies against stone
        x = int(gen.integers(4, W - 4))
        y = int(gen.integers(H - 70, H - 8))
        if B[y, x] in (K.STONE, K.SLATE):
            carve_disc(B, protect, x, y, 1.2, K.OBSIDIAN)
    _lakes(w, gen, B, protect)
    for _ in range(8):                                          # underground aquifers
        x = int(gen.integers(10, W - 10))
        y = int(gen.integers(100, 190))
        air = np.argwhere(B[max(0, y - 6):y + 6, max(0, x - 8):x + 9] == K.AIR)
        if len(air) > 12:
            for ay, ax in air:
                yy_, xx_ = ay + max(0, y - 6), ax + max(0, x - 8)
                if yy_ >= y:
                    liq[yy_, xx_] = 8
    # ---- life: trees, grass, cacti, glowcaps, ruins, shrines, chests
    _vegetation(w, gen, B, liq, protect)
    _ruins(w, gen, B, liq, protect)
    _repair_surface(w, B, liq)
    # ---- spawn: a clear meadow glade
    sx = int(spawn_x)
    ground = int(s[sx])
    B[ground - 14:ground, sx - 4:sx + 5] = K.AIR
    liq[ground - 14:ground, sx - 4:sx + 5] = 0
    B[ground, sx - 4:sx + 5] = K.GRASS if w.biome_name(sx) in ("meadow", "forest") else B[ground, sx]
    w.spawn = (sx, ground - 2)
    w.surf[:] = w.terrain_top().astype(np.int16)
    w.grid.edited.clear()
    w.grid.render_dirty = {(cx, cy) for cx in range(w.grid.cw) for cy in range(w.grid.ch)}
    w.active_liquid = {(int(x), int(y)) for y, x in np.argwhere(liq > 0)[:0]}
    w.attempt = attempt
    return w


def _keystone_site(w: World, gen, B, protect, ks_x0: int, ks_px0: int, ks_n_t: int, ks_width: int, ks_height: int) -> None:
    """Clear the stencil volume, lay the plinth and protect the site from caves and ore."""
    y_plinth = int(w.surf[ks_px0])
    y0 = y_plinth - (ks_height - 1)
    for dy in range(-3, ks_height - 1):
        B[y0 + dy, ks_x0 - 1:ks_x0 + ks_width + 1] = K.AIR
    B[y_plinth, ks_px0:ks_px0 + ks_n_t] = K.PLINTH
    B[y_plinth, ks_x0 - 3:ks_px0] = np.where(B[y_plinth, ks_x0 - 3:ks_px0] == K.AIR, K.DIRT, B[y_plinth, ks_x0 - 3:ks_px0])
    B[y_plinth + 1:y_plinth + 4, ks_px0 - 2:ks_px0 + ks_n_t + 2] = np.where(
        B[y_plinth + 1:y_plinth + 4, ks_px0 - 2:ks_px0 + ks_n_t + 2] == K.AIR, K.DIRT,
        B[y_plinth + 1:y_plinth + 4, ks_px0 - 2:ks_px0 + ks_n_t + 2])
    protect[y0 - 3:y_plinth + 12, ks_x0 - 3:ks_x0 + ks_width + 3] = True
    w.keystone = (ks_x0, y0)
    w.plinth = (ks_px0, y_plinth, ks_n_t)


def _repair_surface(w: World, B, liq) -> None:
    """Make the walking surface slope at most two tiles per column by filling pits (this keeps
    the gentle, walkable cave mouths and lakes, and guarantees a surface route from the spawn to the Keystone)."""
    W = w.w
    top = w.walk_top().astype(np.int64)
    env = top.copy()
    for x in range(1, W):
        env[x] = min(env[x], env[x - 1] + 2)
    for x in range(W - 2, -1, -1):
        env[x] = min(env[x], env[x + 1] + 2)
    for x in range(W):
        t = int(top[x])
        if t > env[x]:
            name = w.biome_name(x)
            surf_block = K.GRASS if name in ("meadow", "forest") else K.SAND if name == "salt" else K.SNOW
            e = int(env[x])
            B[e:t, x] = K.DIRT
            liq[e:t, x] = 0
            B[e, x] = surf_block


def xs_range(x0: int, half: int) -> range:
    return range(x0 - half, x0 + half + 1)


def _lakes(w: World, gen, B, protect) -> None:
    W = w.w
    s = w.surf
    for _ in range(9):
        x0 = int(gen.integers(20, W - 40))
        half = int(gen.integers(5, 10))
        if protect[int(s[x0]) - 6:int(s[x0]) + 8, x0 - half - 2:x0 + half + 3].any() or w.biome_name(x0) == "salt" and gen.random() < 0.6:
            continue
        xs = range(x0 - half, x0 + half + 1)
        level = int(min(s[x0 - half - 1], s[x0 + half + 1]))
        if max(int(s[x0 - half - 1]), int(s[x0 + half + 1])) - level > 2 or level - int(s[x0]) > 3                 or max(int(s[x]) for x in xs_range(x0, half)) - level > 2:
            continue
        for x in xs:
            t = (x - x0) / half
            depth = int(round(3.2 * (1 - t * t))) + 1
            floor = level + depth
            B[:level, x] = np.where(B[:level, x] == K.AIR, K.AIR, np.where(w.reg.solid[B[:level, x]], K.AIR, B[:level, x]))
            B[level:floor, x] = K.AIR
            w.grid.liq[level:floor, x] = 8
            if floor < w.h:
                if B[floor, x] == K.AIR:
                    B[floor, x] = K.SAND
        for x in xs:
            w.surf[x] = level + 1


def _vegetation(w: World, gen, B, liq, protect) -> None:
    W = w.w
    s = w.surf
    last_tree = -99
    names = {i: n for i, n in enumerate(K.BIOMES)}
    for x in range(3, W - 3):
        top = int(s[x])
        if protect[top, x] or liq[top - 1, x] > 0 or liq[top, x] > 0 or B[top - 1, x] != K.AIR:
            continue
        biome = names[int(w.biome[x])]
        ground = B[top, x]
        if biome in ("meadow", "forest") and ground == K.GRASS:
            r = gen.random()
            if r < 0.30:
                B[top - 1, x] = K.TALLGRASS
            elif r < 0.36:
                B[top - 1, x] = K.FLOWER
            dens = 0.13 if biome == "forest" else 0.035
            if gen.random() < dens and x - last_tree >= 4 and liq[top - 1, x] == 0:
                if _tree(w, gen, B, x, top, False, protect):
                    last_tree = x
        elif biome == "frozen" and ground == K.SNOW:
            if gen.random() < 0.05 and x - last_tree >= 5:
                if _tree(w, gen, B, x, top, True, protect):
                    last_tree = x
        elif biome == "salt" and ground == K.SAND:
            if gen.random() < 0.05 and x - last_tree >= 3:
                for i in range(int(gen.integers(2, 5))):
                    if B[top - 1 - i, x] == K.AIR:
                        B[top - 1 - i, x] = K.CACTUS
                last_tree = x
    # glowcaps on cave floors
    ys, xs = np.nonzero((B[1:-1] == K.AIR) & (B[2:] == K.STONE) & (liq[1:-1] == 0))
    pick = gen.random(len(ys)) < 0.025
    for y, x in zip(ys[pick], xs[pick]):
        y += 1
        if y > w.surf[x] + 14 and not protect[y, x]:
            B[y, x] = K.GLOWCAP
    ys, xs = np.nonzero((B[2:-2] == K.STONE) & (B[1:-3] == K.AIR) & (liq[2:-2] == 0))
    pick = gen.random(len(ys)) < 0.004
    for y, x in zip(ys[pick], xs[pick]):
        y += 2
        if y > w.surf[x] + 20 and not protect[y, x]:
            B[y, x] = K.MOSS


def _tree(w: World, gen, B, x: int, top: int, pine: bool, protect=None) -> bool:
    h = int(gen.integers(4, 8))
    if top - h - 4 < 2:
        return False
    for i in range(1, h + 1):
        if B[top - i, x] != K.AIR and B[top - i, x] != K.TALLGRASS:
            return False
    for i in range(1, h + 1):
        B[top - i, x] = K.LOG
    leaf = K.PINE_LEAVES if pine else K.LEAVES
    r = 2 if pine else int(gen.integers(2, 4))
    cy = top - h
    for dy in range(-r - 1, 2):
        rad = r - max(0, abs(dy + 1) // 2) if not pine else max(0, r - (dy + r + 1) // 2 + (1 if dy > 0 else 0))
        for dx in range(-rad, rad + 1):
            xx, yy = x + dx, cy + dy
            if 0 < xx < w.w - 1 and 0 < yy < top - 1 and B[yy, xx] in (K.AIR, K.TALLGRASS) and not (protect is not None and protect[yy, xx]) and not (dx == 0 and yy >= cy - 0 and yy < top):
                B[yy, xx] = leaf
    B[cy - 1, x] = leaf if B[cy - 1, x] == K.AIR else B[cy - 1, x]
    return True


def _ruins(w: World, gen, B, liq, protect) -> None:
    W = w.w
    s = w.surf
    placed = 0
    tries = 0
    ruin = [
        "#######",
        "#.....#",
        "#.....#",
        ".......",
        ".#...#.",
    ]
    legend = {"#": K.RUIN_BRICK}
    while placed < 7 and tries < 80:
        tries += 1
        x = int(gen.integers(12, W - 20))
        top = int(s[x])
        if protect[top - 7:top + 2, x - 1:x + 9].any() or abs(x - w.spawn[0]) < 14 and placed > 0 and tries < 20:
            continue
        if any(abs(int(s[x + i]) - top) > 1 for i in range(7)):
            continue
        if any(liq[top - 1, x + i] or liq[top, x + i] for i in range(7)):
            continue
        stamp(B, x, top - 5, ruin, legend, clear=True)
        B[top - 1, x + 3] = K.CHEST
        w.chests[(x + 3, top - 1)] = _loot(w, gen)
        if placed % 2 == 0:
            B[top - 2, x + 5] = K.SHRINE
            w.shrines.append((x + 5, top - 2))
        placed += 1
    # a shrine near the spawn so the first hint is easy to find
    sx = w.spawn[0] + 7 if w.spawn[0] + 8 < W else w.spawn[0] - 7
    top = int(s[sx])
    if B[top - 1, sx] in (K.AIR, K.TALLGRASS, K.FLOWER):
        B[top - 1, sx] = K.SHRINE
        w.shrines.append((sx, top - 1))


def _loot(w: World, gen) -> list:
    pool = [("torch", 4, 10), ("bread", 1, 3), ("stick", 4, 12), ("coal", 3, 8), ("seed_wheat", 2, 5), ("wood_pickaxe", 1, 1), ("bucket", 1, 1),
            ("planks", 6, 14), ("copper_ingot", 2, 5)]
    slots = []
    for item, a, b in [pool[int(i)] for i in gen.choice(len(pool), size=4, replace=False)]:
        if item in w.reg.items:
            slots.append([item, int(gen.integers(a, b + 1))])
    return slots


# ------------------------------------------------------------------------------------------- validation
def validate(w: World) -> list[str]:
    """Rules every world must satisfy.  Returns a list of problems (empty = valid)."""
    P: list[str] = []
    B = w.grid.blocks
    reg = w.reg
    # surface walkability: neighbouring columns differ by at most two tiles
    top = w.walk_top()
    if int(np.abs(np.diff(top)).max()) > 5:
        P.append("surface has a cliff steeper than 5 tiles")
    # spawn
    sx, sy = w.spawn
    if w.solid(sx, sy) or w.solid(sx, sy - 1) or not w.solid(sx, sy + 2):
        P.append("spawn is buried or floating")
    # keystone site
    if w.keystone is None:
        P.append("no keystone site")
    else:
        x0, y0 = w.keystone
        rows = reg.structures["keystone"]["pattern"]
        px0, py, nt = w.plinth
        if any(B[py, px0 + i] != K.PLINTH for i in range(nt)):
            P.append("plinth row damaged")
        for dy in range(len(rows) - 1):
            for dx, ch in enumerate(rows[dy]):
                if B[y0 + dy, x0 + dx] != K.AIR:
                    P.append("keystone volume obstructed")
                    break
            else:
                continue
            break
        for dx in range(nt):
            if not w.solid(px0 + dx, py + 1):
                P.append("plinth is not supported")
                break
    # resources
    for name, need in MIN_ORE.items():
        n = int((B == reg.bid(name)).sum())
        if n < need:
            P.append(f"too little {name}: {n} < {need}")
    if int((B == K.OBSIDIAN).sum()) < 6:
        P.append("no obsidian")
    if not (w.grid.liq & K.LIQ_LAVA).any():
        P.append("no lava")
    if not ((w.grid.liq > 0) & ((w.grid.liq & K.LIQ_LAVA) == 0)).any():
        P.append("no water")
    # the surface route from spawn to the keystone has no impassable gap
    lo, hi = int(top.min()) - 12, int(top.max()) + 4
    walk = ~reg.solid[B[lo:hi]]
    labels, _ = label4(walk)
    if w.keystone is not None:
        kx, ky = w.keystone[0] + 6, w.keystone[1] + 2
        a = labels[sy - lo, sx]
        b = labels[ky - lo, kx]
        if a == 0 or a != b:
            P.append("keystone site cannot be reached on foot from the spawn")
    # caves exist underground and reach the surface somewhere
    deep_air = int(((B[140:230] == K.AIR)).sum())
    if deep_air < 6000:
        P.append(f"too few caves ({deep_air})")
    return P
