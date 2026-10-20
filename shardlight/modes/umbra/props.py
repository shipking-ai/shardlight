"""Static definitions of ward props: footprint, collision, line-of-sight blocking, hiding and container rules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropDef:
    kind: str
    name: str
    w: int = 1
    h: int = 1
    solid: bool = True
    opaque: bool = False        # tall objects cast shadows and block sight
    hide: str = ""              # hiding spot type: locker | bed | table
    container: bool = False     # can be searched for items
    deco: bool = False          # floor decoration, no interaction
    reads: bool = False         # carries a readable note


PROP_DEFS: dict[str, PropDef] = {p.kind: p for p in (
    PropDef("bed", "Bed", 2, 1, hide="bed"),
    PropDef("cot", "Cot", 2, 1),
    PropDef("locker", "Locker", opaque=True, hide="locker", container=True),
    PropDef("wardrobe", "Wardrobe", opaque=True, hide="locker", container=True),
    PropDef("table", "Table", 2, 1, hide="table"),
    PropDef("desk", "Desk", 2, 1, container=True),
    PropDef("shelf", "Shelf", opaque=True, container=True),
    PropDef("bookshelf", "Bookshelf", opaque=True, container=True),
    PropDef("crate", "Crate", container=True),
    PropDef("barrel", "Barrel"),
    PropDef("cabinet", "Cabinet", opaque=True, hide="locker", container=True),
    PropDef("bench", "Bench", 2, 1),
    PropDef("sofa", "Sofa", 2, 1),
    PropDef("rack", "Rack", opaque=True, container=True),
    PropDef("coffin", "Coffin", 2, 1, hide="locker", container=True),
    PropDef("counter", "Counter", 2, 1, container=True),
    PropDef("pillar", "Pillar", opaque=True),
    PropDef("chair", "Chair"),
    PropDef("wheelchair", "Wheelchair"),
    PropDef("mirror", "Covered Mirror", opaque=True),
    PropDef("clock", "Stopped Clock", opaque=True),
    PropDef("generator", "Generator", 2, 2),
    PropDef("fuse_box", "Fuse Box", opaque=True),
    PropDef("lever", "Lever"),
    PropDef("winch", "Gate Winch", 1, 1),
    PropDef("stairs", "Stairs", 2, 1, solid=False),
    PropDef("barricade", "Barricade"),
    PropDef("rug", "Rug", 2, 2, solid=False, deco=True),
    PropDef("bloodstain", "Stain", solid=False, deco=True),
    PropDef("papers", "Papers", solid=False, reads=True),
    PropDef("drawing", "Drawing", solid=False, reads=True),
    PropDef("sign", "Sign", solid=False, reads=True),
    PropDef("candle", "Candle", solid=False),
    PropDef("tally", "Tally Marks", solid=False, reads=True),
)}

# hiding spot rules: chance an enemy that is searching the room checks it, and the player's entry time
HIDE_RULES = {
    "locker": {"check": 0.45, "enter": 0.45, "noise": 5.0, "label": "Hide in locker"},
    "bed": {"check": 0.30, "enter": 0.55, "noise": 2.5, "label": "Hide under bed"},
    "table": {"check": 0.50, "enter": 0.40, "noise": 2.0, "label": "Hide under table"},
}


def footprint(kind: str, cell: tuple[int, int], rot: bool = False) -> list[tuple[int, int]]:
    d = PROP_DEFS[kind]
    w, h = (d.h, d.w) if rot else (d.w, d.h)
    return [(cell[0] + dx, cell[1] + dy) for dy in range(h) for dx in range(w)]
