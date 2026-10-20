"""Vectorised value-noise fBm and small numpy helpers for terrain generation (deterministic per seed)."""
from __future__ import annotations

import numpy as np

from ...core.rng import derive_seed


def fbm(w: int, h: int, seed: int | str, scale: float, octaves: int = 4, persistence: float = 0.5,
        lacunarity: float = 2.0) -> np.ndarray:
    """Fractal value noise in [0, 1], shape (h, w)."""
    total = np.zeros((h, w), dtype=np.float64)
    amp, norm = 1.0, 0.0
    xs0 = np.arange(w, dtype=np.float64)
    ys0 = np.arange(h, dtype=np.float64)
    for o in range(octaves):
        s = max(1.0, scale / (lacunarity ** o))
        gw, gh = int(w / s) + 3, int(h / s) + 3
        grid = np.random.default_rng(derive_seed(seed, "fbm", o) & 0xFFFFFFFF).random((gh, gw))
        xs, ys = xs0 / s, ys0 / s
        x0, y0 = xs.astype(np.intp), ys.astype(np.intp)
        fx, fy = xs - x0, ys - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = grid[y0][:, x0] * (1 - fx) + grid[y0][:, x0 + 1] * fx
        bot = grid[y0 + 1][:, x0] * (1 - fx) + grid[y0 + 1][:, x0 + 1] * fx
        layer = top * (1 - fy)[:, None] + bot * fy[:, None]
        total += layer * amp
        norm += amp
        amp *= persistence
    return (total / norm).astype(np.float32)


def box_sums(mask: np.ndarray, bw: int, bh: int) -> np.ndarray:
    """Sum of ``mask`` over every bw x bh window; result[y, x] is the window whose top-left is (x, y)."""
    m = mask.astype(np.int32)
    c = np.zeros((m.shape[0] + 1, m.shape[1] + 1), dtype=np.int32)
    c[1:, 1:] = m.cumsum(0).cumsum(1)
    return c[bh:, bw:] - c[:-bh, bw:] - c[bh:, :-bw] + c[:-bh, :-bw]


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Chebyshev dilation of a boolean mask by ``r`` cells."""
    out = mask.copy()
    for _ in range(r):
        p = out.copy()
        p[1:] |= out[:-1]
        p[:-1] |= out[1:]
        q = p.copy()
        q[:, 1:] |= p[:, :-1]
        q[:, :-1] |= p[:, 1:]
        out = q
    return out


def gradient_mag(a: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(a.astype(np.float32))
    return np.hypot(gx, gy)
