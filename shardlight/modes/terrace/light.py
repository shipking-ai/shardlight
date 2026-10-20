"""Tile lighting for Terrace: sunlight falls straight down and spreads sideways, torches and glowing blocks add
their own light, opaque blocks stop it.  Pure numpy, computed for a window around the camera."""
from __future__ import annotations

import numpy as np

from . import constants as K
from .world import World

LAVA_LIGHT = 12
MAX_LIGHT = 15


def column_cover(world: World) -> np.ndarray:
    """Row of the first opaque block in every column (``h`` if none): everything above it sees the sky."""
    key = world.grid.version
    cached = getattr(world, "_cover_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    op = world.reg.opaque[world.grid.blocks]
    first = np.where(op.any(axis=0), np.argmax(op, axis=0), world.h)
    world._cover_cache = (key, first)
    return first


def compute(world: World, x0: int, y0: int, w: int, h: int, daylight: float | None = None, lamps=()) -> np.ndarray:
    """Light levels (0..15) for the tile window ``[x0, x0+w) x [y0, y0+h)`` (clamped to the world).
    ``lamps``: extra (tile_x, tile_y, level) sources, e.g. the faint glow around the player."""
    daylight = world.daylight() if daylight is None else daylight
    x1, y1 = min(world.w, x0 + w), min(world.h, y0 + h)
    x0, y0 = max(0, x0), max(0, y0)
    blocks = world.grid.blocks[y0:y1, x0:x1]
    liq = world.grid.liq[y0:y1, x0:x1]
    opaque = world.reg.opaque[blocks]
    light = world.reg.light[blocks].astype(np.int16)
    lava = (liq & K.LIQ_LAVA) > 0
    light = np.maximum(light, np.where(lava & ((liq & K.LIQ_AMOUNT_MASK) > 0), LAVA_LIGHT, 0))
    for lx, ly, lv in lamps:
        if x0 <= lx < x1 and y0 <= ly < y1:
            light[ly - y0, lx - x0] = max(light[ly - y0, lx - x0], lv)
    cover = column_cover(world)[x0:x1]
    sky = int(round(MAX_LIGHT * daylight))
    rows = np.arange(y0, y1)[:, None]
    light = np.maximum(light, np.where(rows < cover[None, :], sky, 0))
    for _ in range(MAX_LIGHT):
        trans = np.where(opaque, 0, light)
        nb = np.zeros_like(light)
        nb[1:] = np.maximum(nb[1:], trans[:-1])
        nb[:-1] = np.maximum(nb[:-1], trans[1:])
        nb[:, 1:] = np.maximum(nb[:, 1:], trans[:, :-1])
        nb[:, :-1] = np.maximum(nb[:, :-1], trans[:, 1:])
        new = np.maximum(light, nb - 1)
        if (new == light).all():
            break
        light = new
    return light.astype(np.uint8)


def at(world: World, x: int, y: int, daylight: float | None = None) -> int:
    """Light level of a single tile (computes a small window; use ``compute`` for many lookups)."""
    r = MAX_LIGHT
    win = compute(world, x - r, y - r, 2 * r + 1, 2 * r + 1, daylight)
    xx, yy = x - max(0, x - r), y - max(0, y - r)
    return int(win[yy, xx])
