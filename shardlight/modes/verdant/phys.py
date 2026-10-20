"""Tiny tile-grid collision helpers shared by the player, NPCs and enemies (positions are float tile coordinates)."""
from __future__ import annotations

import math


def fits(walk: bytearray, W: int, H: int, x: float, y: float, r: float) -> bool:
    x0, x1 = math.floor(x - r), math.floor(x + r)
    y0, y1 = math.floor(y - r), math.floor(y + r)
    if x0 < 0 or y0 < 0 or x1 >= W or y1 >= H:
        return False
    for yy in (y0, y1):
        base = yy * W
        if not walk[base + x0] or not walk[base + x1]:
            return False
    return True


def move(walk: bytearray, W: int, H: int, x: float, y: float, dx: float, dy: float, r: float) -> tuple[float, float, bool]:
    """Axis-separated slide.  Returns (x, y, blocked)."""
    blocked = False
    if dx:
        if fits(walk, W, H, x + dx, y, r):
            x += dx
        else:
            blocked = True
    if dy:
        if fits(walk, W, H, x, y + dy, r):
            y += dy
        else:
            blocked = True
    return x, y, blocked


def line_clear(walk: bytearray, W: int, H: int, ax: float, ay: float, bx: float, by: float, step: float = 0.5) -> bool:
    d = math.hypot(bx - ax, by - ay)
    n = max(1, int(d / step))
    for i in range(1, n):
        t = i / n
        x, y = int(ax + (bx - ax) * t), int(ay + (by - ay) * t)
        if x < 0 or y < 0 or x >= W or y >= H or not walk[y * W + x]:
            return False
    return True
