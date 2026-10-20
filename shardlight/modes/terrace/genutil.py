"""Small numeric helpers for world generation (noise, brushes, stamping)."""
from __future__ import annotations

import math

import numpy as np

from .constants import AIR, BEDROCK


def smooth_noise_1d(gen: np.random.Generator, n: int, periods=(120, 56, 26, 12), amps=(1.0, 0.5, 0.28, 0.12)) -> np.ndarray:
    """Fractal value noise in [-1, 1] along one axis (cosine-interpolated lattice noise)."""
    out = np.zeros(n)
    x = np.arange(n)
    for period, amp in zip(periods, amps):
        pts = gen.uniform(-1, 1, n // period + 3)
        i = x / period
        i0 = i.astype(int)
        t = i - i0
        t = t * t * (3 - 2 * t)
        out += amp * (pts[i0] * (1 - t) + pts[i0 + 1] * t)
    return out / sum(amps)


def smooth_noise_2d(gen: np.random.Generator, h: int, w: int, cell: int) -> np.ndarray:
    """Value noise in [0, 1], bilinear with smoothstep, lattice spacing ``cell`` tiles."""
    gh, gw = h // cell + 3, w // cell + 3
    lat = gen.random((gh, gw))
    ys = np.arange(h) / cell
    xs = np.arange(w) / cell
    y0, x0 = ys.astype(int), xs.astype(int)
    ty, tx = ys - y0, xs - x0
    ty = (ty * ty * (3 - 2 * ty))[:, None]
    tx = (tx * tx * (3 - 2 * tx))[None, :]
    a = lat[y0][:, x0]
    b = lat[y0][:, x0 + 1]
    c = lat[y0 + 1][:, x0]
    d = lat[y0 + 1][:, x0 + 1]
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


def box_smooth(a: np.ndarray, width: int) -> np.ndarray:
    k = np.ones(width) / width
    pad = width // 2
    padded = np.pad(a.astype(float), pad, mode="edge")
    return np.convolve(padded, k, mode="valid")[:len(a)]


_DISCS: dict[int, np.ndarray] = {}


def disc_mask(r: float) -> np.ndarray:
    key = int(round(r * 4))
    m = _DISCS.get(key)
    if m is None:
        ri = int(math.ceil(key / 4))
        yy, xx = np.mgrid[-ri:ri + 1, -ri:ri + 1]
        m = (xx * xx + yy * yy) <= (key / 4) ** 2 + 0.3
        _DISCS[key] = m
    return m


def carve_disc(blocks: np.ndarray, protect: np.ndarray, cx: int, cy: int, r: float, value: int = AIR) -> None:
    """Set a filled disc to ``value`` (default air), never touching bedrock or protected cells."""
    h, w = blocks.shape
    m = disc_mask(r)
    ri = m.shape[0] // 2
    y0, y1 = max(1, cy - ri), min(h - 3, cy + ri + 1)
    x0, x1 = max(1, cx - ri), min(w - 1, cx + ri + 1)
    if y0 >= y1 or x0 >= x1:
        return
    sub = m[y0 - (cy - ri):y1 - (cy - ri), x0 - (cx - ri):x1 - (cx - ri)]
    region = blocks[y0:y1, x0:x1]
    sel = sub & (region != BEDROCK) & ~protect[y0:y1, x0:x1]
    region[sel] = value


def carve_line(blocks: np.ndarray, protect: np.ndarray, a: tuple[int, int], b: tuple[int, int], r: float = 1.4) -> None:
    """Carve a straight tunnel between two cells."""
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    for i in range(n + 1):
        t = i / max(1, n)
        carve_disc(blocks, protect, int(round(a[0] + (b[0] - a[0]) * t)), int(round(a[1] + (b[1] - a[1]) * t)), r)


def stamp(blocks: np.ndarray, x0: int, y0: int, rows: list[str], legend: dict[str, int], clear: bool = True) -> None:
    """Draw ``rows`` (top first) with the top-left corner at (x0, y0).  ' ' keeps the cell, '.' clears it to air."""
    h, w = blocks.shape
    for dy, row in enumerate(rows):
        for dx, ch in enumerate(row):
            x, y = x0 + dx, y0 + dy
            if ch == " " or not (0 <= x < w and 0 <= y < h):
                continue
            if ch == ".":
                if clear:
                    blocks[y, x] = AIR
            else:
                blocks[y, x] = legend[ch]
