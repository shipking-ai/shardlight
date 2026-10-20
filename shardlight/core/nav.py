"""Grid navigation: A*, line of sight, flow fields, path smoothing and a spatial hash.

Pure Python (no pygame dependency) so it is fast to test and usable by any mode.  Coordinates are
integer cells ``(x, y)``.  A grid stores walkability and an optional per-cell movement cost.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque
from typing import Callable, Iterable, Iterator

Cell = tuple[int, int]

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAG = ((1, 1), (1, -1), (-1, 1), (-1, -1))
SQRT2 = math.sqrt(2)


class Grid:
    def __init__(self, width: int, height: int, walkable: bool = True):
        self.w = width
        self.h = height
        self.blocked = [bytearray(0 if walkable else 1 for _ in range(width)) for _ in range(height)]
        self.cost = [[1.0] * width for _ in range(height)]

    @classmethod
    def from_rows(cls, rows: list[str], wall: str = "#") -> "Grid":
        g = cls(len(rows[0]), len(rows))
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                g.blocked[y][x] = 1 if ch == wall else 0
        return g

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def walkable(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and not self.blocked[y][x]

    def set_blocked(self, x: int, y: int, value: bool = True) -> None:
        if self.in_bounds(x, y):
            self.blocked[y][x] = 1 if value else 0

    def neighbors(self, c: Cell, diagonal: bool = True) -> Iterator[tuple[Cell, float]]:
        x, y = c
        for dx, dy in _ORTHO:
            nx, ny = x + dx, y + dy
            if self.walkable(nx, ny):
                yield (nx, ny), self.cost[ny][nx]
        if diagonal:
            for dx, dy in _DIAG:
                nx, ny = x + dx, y + dy
                # forbid cutting corners through walls
                if self.walkable(nx, ny) and self.walkable(x + dx, y) and self.walkable(x, y + dy):
                    yield (nx, ny), self.cost[ny][nx] * SQRT2

    def walkable_cells(self) -> list[Cell]:
        return [(x, y) for y in range(self.h) for x in range(self.w) if not self.blocked[y][x]]

    def nearest_walkable(self, c: Cell, max_r: int = 8) -> Cell | None:
        if self.walkable(*c):
            return c
        for r in range(1, max_r + 1):
            for dx in range(-r, r + 1):
                for dy in (-r, r):
                    for cand in ((c[0] + dx, c[1] + dy), (c[0] + dy, c[1] + dx)):
                        if self.walkable(*cand):
                            return cand
        return None


def _heuristic(a: Cell, b: Cell, diagonal: bool) -> float:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    if diagonal:
        return (dx + dy) + (SQRT2 - 2) * min(dx, dy)
    return dx + dy


def astar(grid: Grid, start: Cell, goal: Cell, diagonal: bool = True, max_nodes: int = 20000,
          extra_cost: Callable[[Cell], float] | None = None) -> list[Cell] | None:
    """Return a list of cells from start to goal inclusive, or None if unreachable."""
    if not grid.walkable(*start) or not grid.walkable(*goal):
        return None
    if start == goal:
        return [start]
    open_heap: list[tuple[float, int, Cell]] = [(0.0, 0, start)]
    g: dict[Cell, float] = {start: 0.0}
    came: dict[Cell, Cell] = {}
    counter = 0
    expanded = 0
    closed: set[Cell] = set()
    while open_heap:
        _, _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path
        closed.add(cur)
        expanded += 1
        if expanded > max_nodes:
            return None
        for nxt, step in grid.neighbors(cur, diagonal):
            if nxt in closed:
                continue
            if extra_cost:
                step += extra_cost(nxt)
            ng = g[cur] + step
            if ng < g.get(nxt, 1e18):
                g[nxt] = ng
                came[nxt] = cur
                counter += 1
                heapq.heappush(open_heap, (ng + _heuristic(nxt, goal, diagonal), counter, nxt))
    return None


def line_cells(a: Cell, b: Cell) -> Iterator[Cell]:
    """Bresenham line, inclusive of both ends."""
    x0, y0 = a
    x1, y1 = b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        yield (x0, y0)
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def line_of_sight(grid: Grid, a: Cell, b: Cell) -> bool:
    for c in line_cells(a, b):
        if not grid.walkable(*c):
            return False
    return True


def smooth_path(grid: Grid, path: list[Cell]) -> list[Cell]:
    """String-pulling: drop waypoints that have direct line of sight."""
    if len(path) < 3:
        return path
    out = [path[0]]
    anchor = 0
    i = 2
    while i < len(path):
        if not line_of_sight(grid, path[anchor], path[i]):
            out.append(path[i - 1])
            anchor = i - 1
        i += 1
    out.append(path[-1])
    return out


class FlowField:
    """Distance-to-goal map for many agents sharing a goal (swarms, crowds)."""

    def __init__(self, grid: Grid, goals: Iterable[Cell], diagonal: bool = True):
        self.grid = grid
        self.dist: dict[Cell, float] = {}
        heap: list[tuple[float, Cell]] = []
        for gcell in goals:
            if grid.walkable(*gcell):
                self.dist[gcell] = 0.0
                heap.append((0.0, gcell))
        heapq.heapify(heap)
        while heap:
            d, c = heapq.heappop(heap)
            if d > self.dist.get(c, 1e18):
                continue
            for n, step in grid.neighbors(c, diagonal):
                nd = d + step
                if nd < self.dist.get(n, 1e18):
                    self.dist[n] = nd
                    heapq.heappush(heap, (nd, n))

    def next_step(self, c: Cell, diagonal: bool = True) -> Cell | None:
        best, best_d = None, self.dist.get(c, 1e18)
        for n, _ in self.grid.neighbors(c, diagonal):
            d = self.dist.get(n, 1e18)
            if d < best_d:
                best, best_d = n, d
        return best

    def reachable(self, c: Cell) -> bool:
        return c in self.dist


def reachable_set(grid: Grid, start: Cell, diagonal: bool = False) -> set[Cell]:
    seen = {start}
    dq = deque([start])
    while dq:
        c = dq.popleft()
        for n, _ in grid.neighbors(c, diagonal):
            if n not in seen:
                seen.add(n)
                dq.append(n)
    return seen


def connected(grid: Grid, a: Cell, b: Cell) -> bool:
    return b in reachable_set(grid, a)


class SpatialHash:
    """Uniform-grid broad phase for circles/points. Rebuild each frame or update incrementally."""

    def __init__(self, cell: float = 32):
        self.cell = cell
        self.buckets: dict[Cell, list] = defaultdict(list)

    def clear(self) -> None:
        self.buckets.clear()

    def _key(self, x: float, y: float) -> Cell:
        return int(x // self.cell), int(y // self.cell)

    def insert(self, obj, x: float, y: float) -> None:
        self.buckets[self._key(x, y)].append((obj, x, y))

    def query(self, x: float, y: float, r: float) -> list:
        x0, y0 = self._key(x - r, y - r)
        x1, y1 = self._key(x + r, y + r)
        r2 = r * r
        out = []
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for obj, ox, oy in self.buckets.get((cx, cy), ()):
                    if (ox - x) ** 2 + (oy - y) ** 2 <= r2:
                        out.append(obj)
        return out
