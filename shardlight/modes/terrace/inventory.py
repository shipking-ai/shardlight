"""Inventory, crafting and furnace fuel for Terrace.  Pure logic, JSON-serialisable."""
from __future__ import annotations

from dataclasses import dataclass, field

from .registry import Registry

HOTBAR = 10
SLOTS = 40
ARMOR_SLOTS = ("head", "chest", "legs")
STATION_RANGE = 5.5          # tiles


@dataclass
class Inventory:
    reg: Registry
    slots: list = field(default_factory=lambda: [None] * SLOTS)       # each None or [item_id, count]
    armor: dict = field(default_factory=lambda: {s: None for s in ARMOR_SLOTS})
    fuel_buffer: float = 0.0
    selected: int = 0

    # ------------------------------------------------------------------ basics
    def stack_limit(self, item: str) -> int:
        return int(self.reg.items.get(item, {}).get("stack", 64))

    def count(self, item: str) -> int:
        return sum(s[1] for s in self.slots if s and s[0] == item)

    def has(self, needs: dict[str, int]) -> bool:
        return all(self.count(k) >= v for k, v in needs.items())

    def free_space(self, item: str) -> int:
        lim = self.stack_limit(item)
        room = 0
        for s in self.slots:
            if s is None:
                room += lim
            elif s[0] == item:
                room += lim - s[1]
        return room

    def add(self, item: str, n: int = 1) -> int:
        """Add items (stacking first, hotbar first); returns how many did not fit."""
        if item not in self.reg.items or n <= 0:
            return n
        lim = self.stack_limit(item)
        for s in self.slots:
            if s and s[0] == item and s[1] < lim:
                take = min(n, lim - s[1])
                s[1] += take
                n -= take
                if n == 0:
                    return 0
        for i, s in enumerate(self.slots):
            if s is None:
                take = min(n, lim)
                self.slots[i] = [item, take]
                n -= take
                if n == 0:
                    return 0
        return n

    def remove(self, item: str, n: int = 1) -> bool:
        if self.count(item) < n:
            return False
        for i in range(len(self.slots) - 1, -1, -1):
            s = self.slots[i]
            if s and s[0] == item:
                take = min(n, s[1])
                s[1] -= take
                n -= take
                if s[1] == 0:
                    self.slots[i] = None
                if n == 0:
                    break
        return True

    def take_slot(self, i: int, n: int = 1) -> str | None:
        s = self.slots[i]
        if not s or s[1] < n:
            return None
        s[1] -= n
        item = s[0]
        if s[1] == 0:
            self.slots[i] = None
        return item

    def held(self) -> str | None:
        s = self.slots[self.selected]
        return s[0] if s else None

    def swap(self, a: int, b: int) -> None:
        sa, sb = self.slots[a], self.slots[b]
        if sa and sb and sa[0] == sb[0]:
            lim = self.stack_limit(sa[0])
            move = min(sa[1], lim - sb[1])
            sb[1] += move
            sa[1] -= move
            if sa[1] == 0:
                self.slots[a] = None
            return
        self.slots[a], self.slots[b] = sb, sa

    # ------------------------------------------------------------------ armour
    def equip(self, slot_index: int) -> bool:
        s = self.slots[slot_index]
        if not s:
            return False
        a = self.reg.items[s[0]].get("armor")
        if not a:
            return False
        old = self.armor[a["slot"]]
        self.armor[a["slot"]] = s[0]
        self.slots[slot_index] = [old, 1] if old else None
        return True

    def defense(self) -> int:
        return sum(self.reg.items[i]["armor"]["defense"] for i in self.armor.values() if i)

    def lava_resist(self) -> float:
        return min(0.9, sum(self.reg.items[i]["armor"].get("lava", 0.0) for i in self.armor.values() if i) / 3.0)

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"slots": [list(s) if s else None for s in self.slots], "armor": dict(self.armor),
                "fuel": self.fuel_buffer, "sel": self.selected}

    @classmethod
    def from_dict(cls, reg: Registry, d: dict) -> "Inventory":
        inv = cls(reg)
        for i, s in enumerate(d.get("slots", [])[:SLOTS]):
            if s and s[0] in reg.items and s[1] > 0:
                inv.slots[i] = [s[0], int(s[1])]
        for k, v in d.get("armor", {}).items():
            if k in inv.armor and v in reg.items:
                inv.armor[k] = v
        inv.fuel_buffer = float(d.get("fuel", 0.0))
        inv.selected = int(d.get("sel", 0)) % HOTBAR
        return inv


# ------------------------------------------------------------------------------------------------ crafting
def recipes_for(reg: Registry, world_state, stations: set[str]) -> list[dict]:
    """Recipes whose station is in reach and which are not locked behind an echo unlock."""
    out = []
    for r in reg.recipes.values():
        if r["station"] != "hand" and r["station"] not in stations:
            continue
        if not reg.recipe_available(r, world_state):
            continue
        if any(reg.item_dormant(k, world_state) for k in list(r["inputs"]) + list(r["outputs"])):
            continue
        out.append(r)
    return sorted(out, key=lambda r: (["hand", "workbench", "furnace", "loom", "forge"].index(r["station"]), r["id"]))


def fuel_needed(rec: dict, inv: Inventory) -> float:
    return max(0.0, rec.get("heat", 0.0) - inv.fuel_buffer)


def fuel_available(reg: Registry, inv: Inventory) -> float:
    return sum(reg.items[s[0]].get("fuel", 0.0) * s[1] for s in inv.slots if s and reg.items[s[0]].get("fuel"))


def can_craft(reg: Registry, inv: Inventory, rec: dict) -> tuple[bool, str]:
    if not inv.has(rec["inputs"]):
        return False, "Missing materials."
    if rec.get("heat", 0) > 0 and fuel_needed(rec, inv) > fuel_available_after(reg, inv, rec):
        return False, "Needs fuel (coal or sticks)."
    # room for the outputs once the inputs are gone
    probe = Inventory(reg, [list(s) if s else None for s in inv.slots])
    for k, v in rec["inputs"].items():
        probe.remove(k, v)
    for k, v in rec["outputs"].items():
        if probe.add(k, v):
            return False, "Inventory is full."
    return True, "OK"


def fuel_available_after(reg: Registry, inv: Inventory, rec: dict) -> float:
    left = 0.0
    for s in inv.slots:
        if s and reg.items[s[0]].get("fuel"):
            n = s[1] - rec["inputs"].get(s[0], 0)
            left += reg.items[s[0]]["fuel"] * max(0, n)
    return left


def craft(reg: Registry, inv: Inventory, rec: dict) -> bool:
    ok, _ = can_craft(reg, inv, rec)
    if not ok:
        return False
    for k, v in rec["inputs"].items():
        inv.remove(k, v)
    heat = rec.get("heat", 0.0)
    while inv.fuel_buffer + 1e-9 < heat:
        # burn the least valuable fuel first so coal is saved for hot recipes
        fuels = sorted((s for s in inv.slots if s and reg.items[s[0]].get("fuel")), key=lambda s: reg.items[s[0]]["fuel"])
        if not fuels:
            return False
        s = fuels[0]
        inv.fuel_buffer += reg.items[s[0]]["fuel"]
        inv.remove(s[0], 1)
    inv.fuel_buffer -= heat
    for k, v in rec["outputs"].items():
        inv.add(k, v)
    return True


def stations_near(world, px: float, py: float) -> set[str]:
    """Crafting stations (blocks with a ``station`` attribute) within reach of tile position (px, py)."""
    out: set[str] = set()
    reg = world.reg
    r = int(STATION_RANGE) + 1
    x0, y0 = int(px), int(py)
    for y in range(y0 - r, y0 + r + 1):
        for x in range(x0 - r, x0 + r + 1):
            if (x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2 <= STATION_RANGE ** 2:
                st = reg.block(world.get(x, y)).get("station")
                if st:
                    out.add(st)
    return out
