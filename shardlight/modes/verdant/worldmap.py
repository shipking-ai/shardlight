"""The generated overworld (and interior areas) as plain numpy layers plus lists of landmarks.

``WorldMap`` is the data model shared by generation, simulation and rendering.  It contains no pygame.
Dynamic changes (a bridge repaired, a gate barricaded) are *features*: named groups of cells whose full
state is listed per variant, so switching variants is idempotent and cheap to persist (one string).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import tiles as T


@dataclass
class Building:
    id: str
    settlement: str
    x: int
    y: int
    w: int
    h: int
    style: str
    door: tuple[int, int]            # door tile (inside the footprint, bottom row)
    front: tuple[int, int]           # walkable cell in front of the door
    shop: str = ""
    enter: str = ""                  # interior area id reached through the door
    label: str = ""
    lit: bool = True                 # windows glow at night when occupied

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


@dataclass
class Marker:
    kind: str
    x: int
    y: int
    site: str
    data: dict = field(default_factory=dict)


@dataclass
class Feature:
    id: str
    cells: list[tuple[int, int]]
    variants: dict[str, list[tuple[int, int]]]    # variant -> [(ground, obj)] aligned with cells (-1 = keep)
    default: str
    label: str = ""


@dataclass
class Site:
    id: str
    kind: str                          # settlement | ruin | dungeon | camp | den | farm | hut | stones
    name: str
    template: str
    rect: tuple[int, int, int, int]
    front: tuple[int, int]             # where a visitor stands to approach it
    interior: str = ""                 # area id of the interior reachable from here
    hidden: bool = False               # not shown on the map until discovered / unlocked
    unlock: str = ""
    faction: str = ""


class WorldMap:
    """One walkable area: the overworld (256x256) or a small interior."""

    def __init__(self, w: int, h: int, seed: int | str = 0, name: str = "area"):
        self.W, self.H = w, h
        self.seed = seed
        self.name = name
        self.ground = np.full((h, w), T.GRASS, dtype=np.uint8)
        self.obj = np.zeros((h, w), dtype=np.uint8)
        self.region = np.zeros((h, w), dtype=np.uint8)
        self.bmask = np.zeros((h, w), dtype=bool)
        self.walk = np.zeros((h, w), dtype=bool)
        self.elev = np.zeros((h, w), dtype=np.float32)
        self.buildings: list[Building] = []
        self.spots: dict[str, tuple[int, int]] = {}
        self.markers: list[Marker] = []
        self.sites: dict[str, Site] = {}
        self.roads: list[list[tuple[int, int]]] = []
        self.features: dict[str, Feature] = {}
        self.spawns: list[dict] = []
        self.caches: list[dict] = []
        self.lamps: list[dict] = []
        self.start: tuple[int, int] = (w // 2, h // 2)
        self.attempt = 0
        self.problems: list[str] = []
        self.dark = False                  # interiors: no daylight
        self.exits: dict[str, tuple[int, int]] = {}   # interior: exit name -> cell
        self.rooms: list[tuple[int, int, int, int]] = []
        self._doors: dict[tuple[int, int], Building] = {}

    # ------------------------------------------------------------------------ queries
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.W and 0 <= y < self.H

    def is_walk(self, x: int, y: int) -> bool:
        return 0 <= x < self.W and 0 <= y < self.H and bool(self.walk[y, x])

    def building_at_door(self, x: int, y: int) -> Building | None:
        return self._doors.get((x, y))

    def spot(self, name: str) -> tuple[int, int] | None:
        return self.spots.get(name)

    def recompute_walk(self, x0: int = 0, y0: int = 0, x1: int | None = None, y1: int | None = None) -> None:
        x1 = self.W if x1 is None else x1
        y1 = self.H if y1 is None else y1
        g = self.ground[y0:y1, x0:x1]
        o = self.obj[y0:y1, x0:x1]
        self.walk[y0:y1, x0:x1] = T.GROUND_WALK[g] & ~T.OBJ_BLOCKS[o] & ~self.bmask[y0:y1, x0:x1]

    def index_doors(self) -> None:
        self._doors = {b.door: b for b in self.buildings}

    def speed_at(self, x: int, y: int) -> float:
        if not (0 <= x < self.W and 0 <= y < self.H):
            return 0.0
        return float(T.GROUND_SPEED_ARR[self.ground[y, x]])

    # ------------------------------------------------------------------------ features
    def apply_feature(self, fid: str, variant: str) -> bool:
        f = self.features.get(fid)
        if f is None or variant not in f.variants:
            return False
        for (x, y), (g, o) in zip(f.cells, f.variants[variant]):
            if g >= 0:
                self.ground[y, x] = g
            if o >= 0:
                self.obj[y, x] = o
            self.walk[y, x] = bool(T.GROUND_WALK[self.ground[y, x]] and not T.OBJ_BLOCKS[self.obj[y, x]]
                                   and not self.bmask[y, x])
        return True

    def feature_bounds(self, fid: str) -> tuple[int, int, int, int] | None:
        f = self.features.get(fid)
        if not f or not f.cells:
            return None
        xs = [c[0] for c in f.cells]
        ys = [c[1] for c in f.cells]
        return min(xs), min(ys), max(xs), max(ys)

    # ------------------------------------------------------------------------ digest for determinism tests
    def digest(self) -> str:
        import hashlib
        h = hashlib.blake2b(digest_size=12)
        h.update(self.ground.tobytes())
        h.update(self.obj.tobytes())
        h.update(repr(sorted(self.spots.items())).encode())
        h.update(repr([(b.id, b.x, b.y) for b in self.buildings]).encode())
        h.update(repr(sorted((k, v.rect) for k, v in self.sites.items())).encode())
        h.update(repr([(c["id"], c["x"], c["y"]) for c in self.caches]).encode())
        return h.hexdigest()
