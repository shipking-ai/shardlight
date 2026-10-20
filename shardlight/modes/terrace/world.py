"""The Terrace world: tiles, liquids, per-tile state and the rules for editing them.

``World`` is pure data + rules (no pygame).  Generation lives in ``worldgen``; light, fluids, creatures and the
player each have their own module and operate on a ``World``.
"""
from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from ...core.rng import Rng
from . import constants as K
from .grid import ChunkedGrid
from .registry import Registry

SOIL = ("dirt", "grass", "farmland", "farmland_wet", "moss")


@dataclass
class Drop:
    """An item lying in the world."""
    x: float
    y: float
    item: str
    count: int
    vx: float = 0.0
    vy: float = 0.0
    age: float = 0.0


class World:
    def __init__(self, reg: Registry, seed: int):
        self.reg = reg
        self.seed = seed
        self.w, self.h = K.WORLD_W, K.WORLD_H
        self.grid = ChunkedGrid(self.w, self.h)
        self.biome = np.zeros(self.w, dtype=np.uint8)          # index into K.BIOMES
        self.surf = np.zeros(self.w, dtype=np.int16)           # surface row (first non-air row from the top)
        self.spawn = (self.w // 2, 80)
        self.keystone: tuple[int, int] | None = None           # top-left tile of the Keystone stencil
        self.keystone_state = "unbuilt"                         # unbuilt | assembled | vigil | done
        self.shrines: list[tuple[int, int]] = []
        self.chests: dict[tuple[int, int], list] = {}
        self.crops: dict[tuple[int, int], float] = {}           # growing plants -> accumulated growth seconds
        self.drops: list[Drop] = []
        self.clock = K.START_CLOCK                              # fraction of the day
        self.day = 1
        self.time = 0.0
        self.built: set[str] = set()                            # structure kinds built (beacon, keystone)
        self.rng = Rng(seed).child("world")
        self.active_liquid: set[tuple[int, int]] = set()
        self.events: list[tuple[str, dict]] = []

    # ------------------------------------------------------------------ tile access
    @property
    def blocks(self) -> np.ndarray:
        return self.grid.blocks

    @property
    def liq(self) -> np.ndarray:
        return self.grid.liq

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.w and 0 <= y < self.h:
            return int(self.grid.blocks[y, x])
        return K.BEDROCK if y >= self.h or y < 0 else K.BEDROCK

    def name(self, x: int, y: int) -> str:
        return self.reg.block(self.get(x, y))["id"]

    def solid(self, x: int, y: int) -> bool:
        return bool(self.reg.solid[self.get(x, y)])

    def opaque(self, x: int, y: int) -> bool:
        return bool(self.reg.opaque[self.get(x, y)])

    def liquid(self, x: int, y: int) -> tuple[int, bool]:
        """(amount 0..8, is_lava)"""
        if not self.inside(x, y):
            return 0, False
        v = int(self.grid.liq[y, x])
        return v & K.LIQ_AMOUNT_MASK, bool(v & K.LIQ_LAVA)

    def set_liquid(self, x: int, y: int, amount: int, lava: bool = False) -> None:
        if not self.inside(x, y):
            return
        amount = max(0, min(K.LIQ_MAX, amount))
        self.grid.liq[y, x] = (amount | (K.LIQ_LAVA if lava and amount else 0)) if amount else 0
        self.grid.mark(x, y)
        self.active_liquid.add((x, y))

    def set(self, x: int, y: int, n: int, mark: bool = True) -> None:
        if not self.inside(x, y):
            return
        self.grid.blocks[y, x] = n
        if self.reg.solid[n] and self.grid.liq[y, x]:
            self.grid.liq[y, x] = 0                              # a solid block displaces liquid
        if mark:
            self.grid.mark(x, y)
        self.wake_liquid(x, y)

    def wake_liquid(self, x: int, y: int) -> None:
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            if self.inside(x + dx, y + dy) and self.grid.liq[y + dy, x + dx]:
                self.active_liquid.add((x + dx, y + dy))

    def biome_name(self, x: int) -> str:
        return K.BIOMES[int(self.biome[max(0, min(self.w - 1, x))])]

    # ------------------------------------------------------------------ time
    def daylight(self) -> float:
        """0.12 (night) .. 1.0 (day).  The clock starts just after dawn; night is c in [0.54, 0.94]."""
        c = (self.clock + 0.06) % 1.0

        def ss(a: float, b: float, v: float) -> float:
            t = max(0.0, min(1.0, (v - a) / (b - a)))
            return t * t * (3 - 2 * t)

        day = ss(0.0, 0.12, c) * (1.0 - ss(0.50, 0.60, c))
        return 0.12 + 0.88 * day

    def is_night(self) -> bool:
        return self.daylight() < 0.35

    def advance(self, dt: float) -> None:
        self.time += dt
        self.clock += dt / K.DAY_LEN
        if self.clock >= 1.0:
            self.clock -= 1.0
            self.day += 1
            self.events.append(("dawn", {"day": self.day}))

    # ------------------------------------------------------------------ editing rules
    def supported(self, x: int, y: int, n: int | None = None) -> bool:
        b = self.reg.block(self.get(x, y) if n is None else n)
        s = b.get("support", "none")
        if s == "none":
            return True
        if s == "below":
            return self.solid(x, y + 1)
        if s == "adjacent":
            return self.solid(x - 1, y) or self.solid(x + 1, y) or self.solid(x, y + 1)
        if s == "soil":
            return self.name(x, y + 1) in SOIL
        return True

    def roll_drops(self, block_id: str, rng: Rng) -> list[tuple[str, int]]:
        out = []
        for d in self.reg.blocks[block_id].get("drops", []):
            if rng.random() <= d.get("p", 1.0):
                n = rng.randint(d.get("min", 1), max(d.get("min", 1), d.get("max", 1)))
                if n > 0:
                    out.append((d["item"], n))
        return out

    def can_break(self, x: int, y: int, tool: dict | None) -> tuple[bool, str]:
        b = self.reg.block(self.get(x, y))
        if b["id"] == "air":
            return False, "Nothing there."
        if b["hardness"] < 0:
            return False, "It will not yield."
        tier = b.get("tier", 0)
        have = tool.get("tier", 0) if tool and b["tool"] in (tool.get("type"), "hand") else (tool.get("tier", 0) if tool and tool.get("type") == "pick" and b["tool"] == "pick" else 0)
        if b["tool"] != "hand" and tool and tool.get("type") == b["tool"]:
            have = tool.get("tier", 0)
        elif b["tool"] != "hand":
            have = 0
        else:
            have = 99
        if tier > have:
            need = {1: "wood", 2: "stone", 3: "copper", 4: "iron", 5: "lumina or cinder", 6: "choir alloy"}.get(tier, "a better")
            return False, f"Needs a {need} {b['tool']} or better."
        return True, "OK"

    def break_time(self, x: int, y: int, tool: dict | None) -> float:
        b = self.reg.block(self.get(x, y))
        if b["hardness"] <= 0:
            return 0.0
        speed = 1.0
        if tool and tool.get("type") == b["tool"]:
            speed = tool.get("power", 1.0)
        elif tool and b["tool"] == "hand":
            speed = 1.0
        elif b["tool"] != "hand":
            speed = 0.6
        return b["hardness"] / speed * 0.55

    def break_block(self, x: int, y: int, rng: Rng, drop: bool = True) -> list[tuple[str, int]]:
        """Remove a block, cascading support losses; returns the items that dropped."""
        out: list[tuple[str, int]] = []
        stack = [(x, y)]
        first = True
        while stack:
            cx, cy = stack.pop()
            n = self.get(cx, cy)
            b = self.reg.block(n)
            if n == K.AIR or b["hardness"] < 0 or (not first and not b.get("fragile")):
                continue
            if b["id"] in ("door_open",) or b["id"] == "door_closed":
                other = self._door_partner(cx, cy)
            else:
                other = None
            if b.get("crop"):
                self.crops.pop((cx, cy), None)
            if b["id"] == "chest" and (cx, cy) in self.chests:
                for slot in self.chests.pop((cx, cy)):
                    if slot:
                        self.drops.append(Drop(cx + 0.5, cy + 0.5, slot[0], slot[1]))
            if drop:
                for item, cnt in self.roll_drops(b["id"], rng):
                    out.append((item, cnt))
            self.set(cx, cy, K.AIR)
            if other is not None:
                self.set(other[0], other[1], K.AIR)
            first = False
            for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                nx, ny = cx + dx, cy + dy
                nb = self.reg.block(self.get(nx, ny))
                if nb.get("fragile") and not self.supported(nx, ny):
                    stack.append((nx, ny))
        return out

    def _door_partner(self, x: int, y: int) -> tuple[int, int] | None:
        return None

    def can_place(self, x: int, y: int, n: int, blockers: Iterable[tuple[int, int, int, int]] = ()) -> tuple[bool, str]:
        """``blockers``: pixel AABBs (x0, y0, x1, y1) of entities that a solid block must not overlap."""
        if not self.inside(x, y):
            return False, "Out of the world."
        cur = self.reg.block(self.get(x, y))
        if cur["id"] != "air" and not cur.get("replaceable") and self.grid.liq[y, x] == 0:
            return False, "Occupied."
        b = self.reg.block(n)
        if not self.supported(x, y, n):
            return False, "Nothing to rest it on."
        if b["solid"]:
            px0, py0 = x * K.TILE, y * K.TILE
            for (a0, b0, a1, b1) in blockers:
                if a0 < px0 + K.TILE and a1 > px0 and b0 < py0 + K.TILE and b1 > py0:
                    return False, "Something is in the way."
        if not self._has_neighbour(x, y) and b["solid"]:
            return False, "Needs something to attach to."
        return True, "OK"

    def _has_neighbour(self, x: int, y: int) -> bool:
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            if self.get(x + dx, y + dy) != K.AIR or self.liquid(x + dx, y + dy)[0]:
                return True
        return False

    def place_block(self, x: int, y: int, n: int, blockers=()) -> bool:
        ok, _ = self.can_place(x, y, n, blockers)
        if not ok:
            return False
        self.set(x, y, n)
        b = self.reg.block(n)
        if b.get("crop"):
            self.crops[(x, y)] = 0.0
        if b["id"] == "sapling":
            self.crops[(x, y)] = 0.0
        return True

    # ------------------------------------------------------------------ queries
    def surface_y(self, x: int) -> int:
        """First solid row from the top (ignoring plants and leaves)."""
        col = self.grid.blocks[:, max(0, min(self.w - 1, x))]
        for y in range(self.h):
            if self.reg.solid[col[y]] and col[y] != K.LEAVES and col[y] != K.PINE_LEAVES:
                return y
        return self.h - 1

    _GROUND = np.zeros(256, dtype=bool)
    for _n in (K.DIRT, K.GRASS, K.STONE, K.SLATE, K.SAND, K.SANDSTONE, K.SALT, K.SNOW, K.ICE, K.PLINTH,
               K.OBSIDIAN, K.BEDROCK, K.COAL_ORE, K.COPPER_ORE, K.IRON_ORE, K.GOLD_ORE, K.LUMINA_ORE, K.CINDER_ORE,
               K.FARMLAND, K.FARMLAND_WET):
        _GROUND[_n] = True

    def terrain_top(self) -> np.ndarray:
        """First natural-ground row of every column (ignores trees, cacti, plants and buildings on top)."""
        g = self._GROUND[self.grid.blocks]
        return np.argmax(g, axis=0).astype(np.int32)

    def walk_top(self) -> np.ndarray:
        """First row a walker meets in each column: natural ground or (non-lava) liquid surface."""
        g = self._GROUND[self.grid.blocks] | (((self.grid.liq & K.LIQ_LAVA) == 0) & (self.grid.liq > 0))
        return np.argmax(g, axis=0).astype(np.int32)

    def sky_exposed(self, x: int, y: int) -> bool:
        col = self.grid.blocks[:y + 1, x]
        return not bool(self.reg.opaque[col].any())

    # ------------------------------------------------------------------ persistence
    def edited_payload(self) -> dict[str, str]:
        out = {}
        for cx, cy in sorted(self.grid.edited):
            raw = self.grid.pack_chunk(cx, cy)
            out[f"{cx},{cy}"] = base64.b64encode(zlib.compress(raw, 6)).decode("ascii")
        return out

    def apply_payload(self, payload: dict[str, str]) -> None:
        for k, v in payload.items():
            cx, cy = (int(p) for p in k.split(","))
            self.grid.unpack_chunk(cx, cy, zlib.decompress(base64.b64decode(v)))
