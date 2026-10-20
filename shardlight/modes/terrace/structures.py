"""Stencil structures: the buildable Beacon and the Keystone (the Facet Trial), plus crop growth.

A structure is a stencil from ``data/terrace.structure``: each legend letter names a block, ``.`` must be air and a
space is ignored.  ``match`` tests a stencil at an offset; ``detect_near`` finds any stencil a freshly placed block
completes.  The Keystone additionally needs its plinth row and, once raised and lit, a vigil that lasts one full
night.
"""
from __future__ import annotations

from . import constants as K
from .world import World

T = K.TILE
STAGE_SECONDS = 70.0
SAPLING_SECONDS = 260.0


def cells(reg, kind: str):
    """(dx, dy, block_n or None for 'must be air') for every non-blank cell of a stencil."""
    s = reg.structures[kind]
    out = []
    for dy, row in enumerate(s["pattern"]):
        for dx, ch in enumerate(row):
            if ch == " ":
                continue
            out.append((dx, dy, None if ch == "." else reg.bid(s["legend"][ch])))
    return out


def match(world: World, kind: str, x0: int, y0: int) -> bool:
    for dx, dy, n in cells(world.reg, kind):
        got = world.get(x0 + dx, y0 + dy)
        if n is None:
            if world.reg.solid[got]:
                return False
        elif got != n:
            return False
    return True


def detect_near(world: World, x: int, y: int) -> list[tuple[str, int, int]]:
    """Structures completed by a block just placed at (x, y): [(kind, x0, y0), ...]."""
    found = []
    for kind, s in world.reg.structures.items():
        cl = cells(world.reg, kind)
        placed = world.get(x, y)
        for dx, dy, n in cl:
            if n == placed:
                x0, y0 = x - dx, y - dy
                if kind == "keystone":
                    if world.keystone is None or (x0, y0) != world.keystone:
                        continue
                if match(world, kind, x0, y0) and (kind, x0, y0) not in found:
                    found.append((kind, x0, y0))
    return found


def keystone_complete(world: World) -> bool:
    return world.keystone is not None and match(world, "keystone", *world.keystone)


def keystone_top(world: World) -> tuple[int, int] | None:
    """Tile of the Prism that crowns the Keystone (the thing the player lights)."""
    if world.keystone is None:
        return None
    s = world.reg.structures["keystone"]["pattern"]
    for dy, row in enumerate(s):
        if "P" in row:
            return world.keystone[0] + row.index("P"), world.keystone[1] + dy
    return None


class Vigil:
    """State machine for the Keystone trial, updated by the game each second."""

    def __init__(self, world: World):
        self.world = world
        self.night_seen = False
        self.lit_clock = 0.0

    def light(self) -> bool:
        w = self.world
        if w.keystone_state != "assembled":
            return False
        w.keystone_state = "vigil"
        self.night_seen = w.is_night()
        self.lit_clock = w.time
        w.events.append(("vigil_started", {}))
        return True

    def update(self, player_alive: bool) -> str | None:
        """Returns 'done' or 'failed' when the vigil ends."""
        w = self.world
        if w.keystone_state != "vigil":
            return None
        if not keystone_complete(w):
            w.keystone_state = "unbuilt"
            return "failed"
        if not player_alive:
            w.keystone_state = "assembled"
            return "failed"
        if w.is_night():
            self.night_seen = True
        return None

    def on_dawn(self) -> str | None:
        w = self.world
        if w.keystone_state == "vigil" and self.night_seen and keystone_complete(w):
            w.keystone_state = "done"
            return "done"
        return None


# ---------------------------------------------------------------------------------------------- crops
def crop_block(reg, kind: str, stage: int) -> int | None:
    for b in reg.blocks.values():
        c = b.get("crop")
        if c and c["kind"] == kind and c["stage"] == stage:
            return b["n"]
    return None


def grow(world: World, dt: float, light_ok, pollination=None) -> list[tuple[int, int, int]]:
    """Advance planted crops and saplings.  ``light_ok(x, y)`` says whether the tile gets enough light;
    ``pollination(x, y)`` gives a growth multiplier from nearby bumblets.  Returns [(x, y, new_block)] changes."""
    reg = world.reg
    changes = []
    for (x, y), prog in list(world.crops.items()):
        n = world.get(x, y)
        b = reg.block(n)
        crop = b.get("crop")
        soil = world.name(x, y + 1)
        if crop is None and b["id"] != "sapling":
            world.crops.pop((x, y), None)
            continue
        speed = {"farmland_wet": 1.8, "farmland": 1.0}.get(soil, 0.7)
        if not light_ok(x, y):
            speed *= 0.15
        if pollination is not None:
            speed *= pollination(x, y)
        prog += dt * speed
        world.crops[(x, y)] = prog
        if crop is not None:
            stage = min(crop["stages"] - 1, int(prog / STAGE_SECONDS))
            if stage != crop["stage"]:
                nb = crop_block(reg, crop["kind"], stage)
                if nb is not None:
                    world.set(x, y, nb)
                    changes.append((x, y, nb))
        elif prog >= SAPLING_SECONDS:
            if grow_tree(world, x, y):
                world.crops.pop((x, y), None)
                changes.append((x, y, K.LOG))
    return changes


def grow_tree(world: World, x: int, y: int) -> bool:
    h = 5 + (x * 7 + y) % 3
    for i in range(0, h + 2):
        if world.solid(x, y - i) or (i and world.get(x, y - i) not in (K.AIR, K.TALLGRASS, K.SAPLING)):
            return False
    for i in range(h):
        world.set(x, y - i, K.LOG)
    cy = y - h
    for dy in range(-2, 2):
        for dx in range(-2 + (1 if abs(dy) == 2 else 0), 3 - (1 if abs(dy) == 2 else 0)):
            xx, yy = x + dx, cy + dy
            if world.get(xx, yy) in (K.AIR, K.TALLGRASS):
                world.set(xx, yy, K.LEAVES)
    return True


def hydrate(world: World, radius: int = 4) -> int:
    """Farmland near water becomes wet (grows faster); dry again when the water is gone.  Returns tiles changed."""
    changed = 0
    for (x, y) in list(world.crops):
        soil = world.get(x, y + 1)
        if soil not in (K.FARMLAND, K.FARMLAND_WET):
            continue
        wet = False
        for dx in range(-radius, radius + 1):
            for dy in (0, 1, 2):
                a, lava = world.liquid(x + dx, y + 1 + dy - 1 + 0)
                if a > 0 and not lava:
                    wet = True
                    break
            if wet:
                break
        want = K.FARMLAND_WET if wet else K.FARMLAND
        if soil != want:
            world.set(x, y + 1, want)
            changed += 1
    return changed
