"""Content registry: block/item/recipe/structure/creature definitions loaded from JSON via the ContentDB.

Numeric block ids (``n``) are stable data: they are what chunk arrays store.  Saves additionally store a
palette (n -> string id) so that content changes by mods never silently reinterpret old worlds.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ...core.content import ContentDB
from ...core.paths import DATA_DIR

_COLOR = {"type": "color"}
_DROP = {"type": "dict", "fields": {"item": {"type": "str", "required": True, "ref": "terrace.item"},
                                    "min": {"type": "int", "min": 0}, "max": {"type": "int", "min": 0},
                                    "p": {"type": "float", "min": 0, "max": 1}}}

BLOCK_SCHEMA = {
    "n": {"type": "int", "min": 0, "max": 255, "required": True},
    "name": {"type": "str", "required": True}, "style": {"type": "str", "required": True},
    "color": {**_COLOR, "required": True}, "accent": _COLOR,
    "solid": {"type": "bool"}, "opaque": {"type": "bool"}, "hardness": {"type": "float"},
    "tool": {"type": "str", "choices": ["hand", "pick", "axe", "shovel", "hoe", "sword"]},
    "tier": {"type": "int", "min": 0}, "drops": {"type": "list", "items": _DROP},
    "light": {"type": "int", "min": 0, "max": 15},
    "support": {"type": "str", "choices": ["none", "below", "adjacent", "soil"]},
    "refund": {"type": "float", "min": 0, "max": 1}, "station": {"type": "str"}, "interact": {"type": "str"},
    "plant": {"type": "bool"}, "fragile": {"type": "bool"}, "climb": {"type": "bool"},
    "replaceable": {"type": "bool"}, "sound": {"type": "str"}, "damage": {"type": "float", "min": 0},
    "crop": {"type": "dict", "fields": {"kind": {"type": "str"}, "stage": {"type": "int"}, "stages": {"type": "int"}}},
}

ITEM_SCHEMA = {
    "name": {"type": "str", "required": True},
    "kind": {"type": "str", "required": True,
             "choices": ["block", "material", "tool", "weapon", "armor", "food", "seed", "misc"]},
    "stack": {"type": "int", "min": 1, "max": 999}, "color": {**_COLOR, "required": True}, "accent": _COLOR,
    "icon": {"type": "str"}, "place": {"type": "str", "ref": "terrace.block"},
    "tool": {"type": "dict", "fields": {"type": {"type": "str"}, "tier": {"type": "int"},
                                        "power": {"type": "float"}, "damage": {"type": "float"}}},
    "armor": {"type": "dict", "fields": {"slot": {"type": "str", "choices": ["head", "chest", "legs"]},
                                         "defense": {"type": "int"}, "lava": {"type": "float"}}},
    "food": {"type": "dict", "fields": {"hunger": {"type": "float"}, "heal": {"type": "float"}}},
    "fuel": {"type": "float"}, "desc": {"type": "str"}, "unlock": {"type": "str"}, "liquid": {"type": "str"},
}

RECIPE_SCHEMA = {
    "station": {"type": "str", "required": True, "choices": ["hand", "workbench", "furnace", "forge", "loom"]},
    "inputs": {"type": "dict", "required": True, "values": {"type": "int", "min": 1}},
    "outputs": {"type": "dict", "required": True, "values": {"type": "int", "min": 1}},
    "heat": {"type": "float", "min": 0}, "unlock": {"type": "str"}, "hint": {"type": "str"},
    "group": {"type": "str"},
}

STRUCTURE_SCHEMA = {
    "name": {"type": "str", "required": True}, "kind": {"type": "str", "required": True},
    "pattern": {"type": "list", "required": True, "items": {"type": "str"}},
    "legend": {"type": "dict", "required": True, "values": {"type": "str"}},
    "emit": {"type": "bool"}, "plinth": {"type": "bool"}, "desc": {"type": "str"},
}

CREATURE_SCHEMA = {
    "name": {"type": "str", "required": True},
    "role": {"type": "str", "required": True,
             "choices": ["herbivore", "predator", "pollinator", "cave", "scavenger", "night"]},
    "habitat": {"type": "str", "choices": ["surface", "cave", "air"]},
    "biomes": {"type": "list", "items": {"type": "str"}},
    "size": {"type": "list", "items": {"type": "int"}}, "hp": {"type": "float"}, "speed": {"type": "float"},
    "jump": {"type": "int", "min": 0}, "hunger_rate": {"type": "float"}, "lifespan_days": {"type": "float"},
    "maturity_days": {"type": "float"}, "repro_cooldown_days": {"type": "float"},
    "litter": {"type": "list", "items": {"type": "int"}}, "food_min": {"type": "float"},
    "patch_cap": {"type": "float"}, "perception": {"type": "float"},
    "flee": {"type": "list", "items": {"type": "str"}}, "diet": {"type": "list", "items": {"type": "str"}},
    "tame_food": {"type": "list", "items": {"type": "str"}}, "damage": {"type": "float"},
    "attack_rate": {"type": "float"}, "light_averse": {"type": "bool"}, "burns": {"type": "bool"},
    "drops": {"type": "list", "items": _DROP}, "color": _COLOR, "accent": _COLOR, "call": {"type": "str"},
}

KINDS = {"terrace.block": BLOCK_SCHEMA, "terrace.item": ITEM_SCHEMA, "terrace.recipe": RECIPE_SCHEMA,
         "terrace.structure": STRUCTURE_SCHEMA, "terrace.creature": CREATURE_SCHEMA}


def register_kinds(db: ContentDB) -> None:
    for name, schema in KINDS.items():
        db.register_kind(name, schema)


@dataclass
class Registry:
    """Indexed view of the Terrace content."""
    blocks: dict[str, dict] = field(default_factory=dict)
    block_by_n: list = field(default_factory=lambda: [None] * 256)
    items: dict[str, dict] = field(default_factory=dict)
    recipes: dict[str, dict] = field(default_factory=dict)
    structures: dict[str, dict] = field(default_factory=dict)
    creatures: dict[str, dict] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.solid = np.zeros(256, dtype=bool)
        self.opaque = np.zeros(256, dtype=bool)
        self.light = np.zeros(256, dtype=np.uint8)
        self.plant = np.zeros(256, dtype=bool)
        self.n_of: dict[str, int] = {}

    # ------------------------------------------------------------------ build
    @classmethod
    def from_content(cls, db: ContentDB) -> "Registry":
        reg = cls()
        for b in db.all("terrace.block"):
            n = b["n"]
            if reg.block_by_n[n] is not None:
                reg.problems.append(f"block {b['id']}: numeric id {n} already used by {reg.block_by_n[n]['id']}")
                continue
            d = dict(b)
            d.setdefault("solid", True)
            d.setdefault("opaque", d["solid"])
            d.setdefault("hardness", 1.0)
            d.setdefault("tool", "hand")
            d.setdefault("tier", 0)
            d.setdefault("light", 0)
            d.setdefault("support", "none")
            d.setdefault("refund", 1.0)
            d.setdefault("drops", [{"item": b["id"], "min": 1, "max": 1}])
            reg.blocks[d["id"]] = d
            reg.block_by_n[n] = d
            reg.n_of[d["id"]] = n
            reg.solid[n] = d["solid"]
            reg.opaque[n] = d["opaque"]
            reg.light[n] = d["light"]
            reg.plant[n] = bool(d.get("plant"))
        for kind, store in (("terrace.item", reg.items), ("terrace.recipe", reg.recipes),
                            ("terrace.structure", reg.structures), ("terrace.creature", reg.creatures)):
            for e in db.all(kind):
                store[e["id"]] = dict(e)
        reg._check_refs()
        return reg

    def _check_refs(self) -> None:
        P = self.problems
        for it in self.items.values():
            if "place" in it and it["place"] not in self.blocks:
                P.append(f"item {it['id']}: unknown block {it['place']}")
        for b in self.blocks.values():
            for d in b["drops"]:
                if d["item"] not in self.items:
                    P.append(f"block {b['id']}: drop of unknown item {d['item']}")
        for r in self.recipes.values():
            for k in list(r["inputs"]) + list(r["outputs"]):
                if k not in self.items:
                    P.append(f"recipe {r['id']}: unknown item {k}")
        for s in self.structures.values():
            for ch, bid in s["legend"].items():
                if bid not in self.blocks:
                    P.append(f"structure {s['id']}: legend {ch} -> unknown block {bid}")
        for c in self.creatures.values():
            for d in c.get("drops", []):
                if d["item"] not in self.items:
                    P.append(f"creature {c['id']}: drop of unknown item {d['item']}")

    # ------------------------------------------------------------------ queries
    def bid(self, name: str) -> int:
        return self.n_of[name]

    def block(self, n: int) -> dict:
        b = self.block_by_n[n] if 0 <= n < 256 else None
        return b if b is not None else self.block_by_n[0]

    def item_dormant(self, item_id: str, world) -> bool:
        """True if the item is gated behind an unlock the profile does not have."""
        it = self.items.get(item_id)
        if it is None:
            return True
        need = it.get("unlock")
        return bool(need) and not (world is not None and world.has_unlock(need))

    def recipe_available(self, rec: dict, world) -> bool:
        need = rec.get("unlock")
        return not need or (world is not None and world.has_unlock(need))


_CACHE: dict[str, Registry] = {}


def default_registry() -> Registry:
    """Registry loaded straight from ``data/`` (used by pure-logic code and tests, no App needed)."""
    key = str(DATA_DIR)
    if key not in _CACHE:
        db = ContentDB()
        register_kinds(db)
        db.load_dir(DATA_DIR, "base")
        reg = Registry.from_content(db)
        reg.problems += db.problems
        _CACHE[key] = reg
    return _CACHE[key]
