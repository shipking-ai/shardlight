"""Hit-shape and tile-collision maths.  Pure functions, no pygame dependency, easy to unit test.

Angles are radians, 0 = +x (east), positive = clockwise on screen (y grows downward).
"""
from __future__ import annotations

import math
from typing import Callable

TAU = math.tau
TILE = 16


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def angle_to(ax: float, ay: float, bx: float, by: float) -> float:
    return math.atan2(by - ay, bx - ax)


def angle_diff(a: float, b: float) -> float:
    """Signed smallest difference a - b in (-pi, pi]."""
    return (a - b + math.pi) % TAU - math.pi


def turn_toward(cur: float, target: float, max_step: float) -> float:
    d = angle_diff(target, cur)
    if abs(d) <= max_step:
        return target
    return cur + math.copysign(max_step, d)


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def circle_hit(x1: float, y1: float, r1: float, x2: float, y2: float, r2: float) -> bool:
    dx, dy = x2 - x1, y2 - y1
    rr = r1 + r2
    return dx * dx + dy * dy <= rr * rr


def arc_hit(ox: float, oy: float, facing: float, reach: float, arc_deg: float,
            tx: float, ty: float, tr: float, inner: float = 0.0) -> bool:
    """Circular sector (annulus when ``inner`` > 0) of radius ``reach`` and opening ``arc_deg``."""
    dx, dy = tx - ox, ty - oy
    d = math.hypot(dx, dy)
    if d - tr > reach or d + tr < inner:
        return False
    if arc_deg >= 359.0 or d <= tr:
        return True
    half = math.radians(arc_deg) / 2
    widen = math.asin(min(1.0, tr / d))
    return abs(angle_diff(math.atan2(dy, dx), facing)) <= half + widen


def rect_hit(ox: float, oy: float, facing: float, length: float, width: float,
             tx: float, ty: float, tr: float, back: float = 0.0) -> bool:
    """Oriented rectangle starting at the origin, extending ``length`` forward and ``width`` across."""
    dx, dy = tx - ox, ty - oy
    c, s = math.cos(facing), math.sin(facing)
    lx = dx * c + dy * s
    ly = -dx * s + dy * c
    cx = clamp(lx, -back, length)
    cy = clamp(ly, -width / 2, width / 2)
    return (lx - cx) ** 2 + (ly - cy) ** 2 <= tr * tr


def ring_hit(ox: float, oy: float, r_in: float, r_out: float, tx: float, ty: float, tr: float) -> bool:
    d = math.hypot(tx - ox, ty - oy)
    return d + tr >= r_in and d - tr <= r_out


def in_shield(shield_facing: float, shield_arc_deg: float, ax: float, ay: float, sx: float, sy: float) -> bool:
    """True if an attack coming from (ax, ay) strikes the shield at (sx, sy) facing ``shield_facing``."""
    ang = math.atan2(ay - sy, ax - sx)
    return abs(angle_diff(ang, shield_facing)) <= math.radians(shield_arc_deg) / 2


def rotate(x: float, y: float, a: float) -> tuple[float, float]:
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


def unit(dx: float, dy: float) -> tuple[float, float]:
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-9 else (0.0, 0.0)


# ------------------------------------------------------------------------------ tile collision
Solid = Callable[[int, int], bool]


def resolve_circle(solid: Solid, x: float, y: float, r: float, tile: int = TILE) -> tuple[float, float, bool]:
    """Push a circle out of solid tiles.  Returns (x, y, touched)."""
    touched = False
    for _ in range(3):
        moved = False
        tx0, tx1 = int((x - r) // tile), int((x + r) // tile)
        ty0, ty1 = int((y - r) // tile), int((y + r) // tile)
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                if not solid(tx, ty):
                    continue
                left, top = tx * tile, ty * tile
                cx = clamp(x, left, left + tile)
                cy = clamp(y, top, top + tile)
                dx, dy = x - cx, y - cy
                d2 = dx * dx + dy * dy
                if d2 >= r * r:
                    continue
                touched = moved = True
                if d2 > 1e-9:
                    d = math.sqrt(d2)
                    x += dx / d * (r - d)
                    y += dy / d * (r - d)
                else:   # centre inside the tile: shove along the shallowest axis
                    pl, pr = x - left, left + tile - x
                    pt, pb = y - top, top + tile - y
                    m = min(pl, pr, pt, pb)
                    if m == pl:
                        x = left - r
                    elif m == pr:
                        x = left + tile + r
                    elif m == pt:
                        y = top - r
                    else:
                        y = top + tile + r
        if not moved:
            break
    return x, y, touched


def move_and_collide(solid: Solid, x: float, y: float, dx: float, dy: float, r: float,
                     tile: int = TILE) -> tuple[float, float, bool, bool]:
    """Move by (dx, dy) one axis at a time.  Returns (x, y, hit_x, hit_y)."""
    hit_x = hit_y = False
    steps = max(1, int(max(abs(dx), abs(dy)) // (tile * 0.4)) + 1)
    sx, sy = dx / steps, dy / steps
    for _ in range(steps):
        if sx:
            nx, _, t = resolve_circle(solid, x + sx, y, r, tile)
            if t and abs(nx - (x + sx)) > 1e-6:
                hit_x = True
            x = nx
        if sy:
            _, ny, t = resolve_circle(solid, x, y + sy, r, tile)
            if t and abs(ny - (y + sy)) > 1e-6:
                hit_y = True
            y = ny
    return x, y, hit_x, hit_y


def segment_blocked(solid: Solid, x0: float, y0: float, x1: float, y1: float, tile: int = TILE) -> bool:
    """True if the straight segment passes through a solid tile (sampled every quarter tile)."""
    d = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(d / (tile * 0.25)))
    for i in range(n + 1):
        t = i / n
        if solid(int((x0 + (x1 - x0) * t) // tile), int((y0 + (y1 - y0) * t) // tile)):
            return True
    return False


def raycast(solid: Solid, x: float, y: float, angle: float, max_len: float, tile: int = TILE) -> float:
    """Distance along a ray until a solid tile (or ``max_len``)."""
    c, s = math.cos(angle), math.sin(angle)
    step = tile * 0.25
    d = 0.0
    while d < max_len:
        if solid(int((x + c * d) // tile), int((y + s * d) // tile)):
            return max(0.0, d - step)
        d += step
    return max_len
