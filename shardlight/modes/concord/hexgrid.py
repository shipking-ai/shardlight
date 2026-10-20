"""Hex geometry for the campaign map: pointy-top, odd-row offset layout, axial helpers and pixel mapping.

Pure maths, no pygame.  Cells are addressed by ``(col, row)``; the six neighbour directions are numbered
clockwise from east: 0=E 1=SE 2=SW 3=W 4=NW 5=NE.
"""
from __future__ import annotations

import math

SQRT3 = math.sqrt(3.0)

# neighbour offsets for odd-r layout: [even row, odd row] -> (dcol, drow) per direction
_OFFS = (
    ((1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1)),     # even rows
    ((1, 0), (1, 1), (0, 1), (-1, 0), (0, -1), (1, -1)),       # odd rows
)


def neighbors(col: int, row: int) -> list[tuple[int, int]]:
    """The six neighbouring cells in direction order (may lie outside any map)."""
    return [(col + dc, row + dr) for dc, dr in _OFFS[row & 1]]


def to_axial(col: int, row: int) -> tuple[int, int]:
    return col - (row - (row & 1)) // 2, row


def to_cube(col: int, row: int) -> tuple[int, int, int]:
    q, r = to_axial(col, row)
    return q, -q - r, r


def distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    ax, ay, az = to_cube(*a)
    bx, by, bz = to_cube(*b)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


def center(col: int, row: int, size: float) -> tuple[float, float]:
    """Pixel centre of a cell for hexes of circumradius ``size`` (origin = centre of cell (0, 0))."""
    x = size * SQRT3 * (col + 0.5 * (row & 1))
    y = size * 1.5 * row
    return x, y


def corners(cx: float, cy: float, size: float) -> list[tuple[float, float]]:
    """Six corner points, starting at the lower-right (angle 30 degrees), clockwise on screen."""
    return [(cx + size * math.cos(math.radians(30 + 60 * i)), cy + size * math.sin(math.radians(30 + 60 * i)))
            for i in range(6)]


def shared_edge(ca: tuple[float, float], cb: tuple[float, float], size: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """End points of the hex edge shared by two adjacent cells given their pixel centres."""
    mx, my = (ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2
    dx, dy = cb[0] - ca[0], cb[1] - ca[1]
    d = math.hypot(dx, dy) or 1.0
    px, py = -dy / d, dx / d
    h = size / 2
    return (mx - px * h, my - py * h), (mx + px * h, my + py * h)


def direction_between(ca: tuple[float, float], cb: tuple[float, float]) -> int:
    """Hex direction index (0..5) from pixel centre ``ca`` towards ``cb``."""
    ang = math.degrees(math.atan2(cb[1] - ca[1], cb[0] - ca[0])) % 360
    return int(((ang + 30) % 360) // 60)
