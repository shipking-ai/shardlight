"""Content kinds (``umbra.*``), their schemas, and the :class:`Catalog` accessor used by the pure simulation.

Everything the ward is made of - items, notes, enemy tuning, room templates, story dressings, nights and recipes -
is JSON so mods can extend or override it.  The simulation never hard-codes id lists; it asks the catalog and
degrades gracefully (with a log warning) when an id is missing.
"""
from __future__ import annotations

from ...core import log
from ...core.content import ContentDB
from ...core.paths import DATA_DIR

LOG = log.get("umbra")

ITEM_KINDS = ["tool", "consumable", "throwable", "key", "objective", "story", "scrap", "ward"]

ITEM_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 40},
    "kind": {"type": "str", "required": True, "choices": ITEM_KINDS},
    "desc": {"type": "str", "max_len": 160},
    "stack": {"type": "int", "min": 1, "max": 20},
    "color": {"type": "color"},
    "pocket": {"type": "bool"},                      # keys / objective items do not use an inventory slot
    "use": {"type": "dict", "values": {"type": "float"}},          # battery, oil, heal, ward_seconds, ward_radius
    "throw": {"type": "dict", "values": {"type": "float"}},        # noise (tiles), range (tiles), breaks (0/1)
    "noise": {"type": "float", "min": 0, "max": 30},
    "unlock": {"type": "str"},                       # world unlock id required for this item to exist
    "icon": {"type": "str"},
    "spawn_weight": {"type": "float", "min": 0, "max": 100},
}

NOTE_SCHEMA = {
    "title": {"type": "str", "required": True, "max_len": 48},
    "text": {"type": "str", "required": True, "max_len": 400},
    "kind": {"type": "str", "choices": ["note", "log", "sign", "drawing"]},
    "nights": {"type": "list", "items": {"type": "int", "min": 1, "max": 9}},
    "tags": {"type": "list", "items": {"type": "str"}},       # room template ids / story ids that may host it
    "series": {"type": "str"},                       # ordered series id (diary pages)
    "order": {"type": "int", "min": 0, "max": 99},
    "weight": {"type": "float", "min": 0, "max": 100},
    "speaker": {"type": "str", "max_len": 24},       # audio logs
}

ENEMY_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "kind": {"type": "str", "required": True, "choices": ["listener", "watcher", "wanderer"]},
    "stats": {"type": "dict", "required": True, "values": {"type": "float"}},
    "facts": {"type": "list", "items": {"type": "dict", "values": {"type": "any"}}},   # journal habit lines
    "blurb": {"type": "str", "max_len": 200},
}

ROOM_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "role": {"type": "str", "choices": ["any", "safe", "generator", "archive", "gate", "exit", "clock", "hall"]},
    "min_w": {"type": "int", "min": 2, "max": 30},
    "min_h": {"type": "int", "min": 2, "max": 30},
    "max_w": {"type": "int", "min": 2, "max": 64},
    "max_h": {"type": "int", "min": 2, "max": 64},
    "weight": {"type": "float", "min": 0, "max": 100},
    "nights": {"type": "list", "items": {"type": "int", "min": 1, "max": 9}},
    "surface": {"type": "str", "choices": ["wood", "tile", "stone", "carpet", "gravel", "water"]},
    "props": {"type": "list", "items": {"type": "dict", "values": {"type": "any"}}},
    "tags": {"type": "list", "items": {"type": "str"}},
    "lamp": {"type": "float", "min": 0, "max": 1},   # chance of a wall lamp
    "window": {"type": "float", "min": 0, "max": 1}, # chance of moonlight from outside
    "loot": {"type": "float", "min": 0, "max": 3},   # loot weight multiplier
    "hall": {"type": "bool"},
    "unique": {"type": "bool"},
}

STORY_SCHEMA = {
    "title": {"type": "str", "required": True, "max_len": 40},
    "kind": {"type": "str", "required": True, "choices": [
        "barricade_inside", "child_drawing", "candle_room", "dinner_table", "wheelchair", "covered_mirror",
        "strapped_cot", "ransacked", "chalk_tally", "stopped_clock"]},
    "rooms": {"type": "list", "items": {"type": "str"}},      # room template ids or tags it may dress
    "nights": {"type": "list", "items": {"type": "int", "min": 1, "max": 9}},
    "weight": {"type": "float", "min": 0, "max": 100},
    "note": {"type": "str"},                                   # note id or series id to attach
    "params": {"type": "dict", "values": {"type": "any"}},
}

NIGHT_SCHEMA = {
    "title": {"type": "str", "required": True, "max_len": 40},
    "place": {"type": "str", "max_len": 40},
    "objective": {"type": "str", "required": True, "choices": ["power", "keys", "escape"]},
    "style": {"type": "str", "choices": ["infirmary", "manor", "cellar"]},
    "size": {"type": "vec2"},
    "enemies": {"type": "list", "items": {"type": "str"}},
    "keys": {"type": "int", "min": 0, "max": 5},
    "fuses": {"type": "int", "min": 0, "max": 5},
    "safe_rooms": {"type": "int", "min": 1, "max": 3},
    "supplies": {"type": "dict", "values": {"type": "float"}},        # item id -> total count to scatter
    "start": {"type": "dict", "values": {"type": "float"}},           # starting inventory
    "need": {"type": "dict", "values": {"type": "float"}},            # minimum resources the validator demands
    "director": {"type": "dict", "values": {"type": "float"}},        # calm_min, relax_min, build_min, max_peaks...
    "intro": {"type": "str", "max_len": 300},
    "outro": {"type": "str", "max_len": 300},
    "brief": {"type": "str", "max_len": 120},
}

RECIPE_SCHEMA = {
    "a": {"type": "str", "required": True},
    "b": {"type": "str", "required": True},
    "out": {"type": "str", "required": True},
    "count": {"type": "int", "min": 1, "max": 9},
    "hint": {"type": "str", "max_len": 80},
}

KINDS = {
    "umbra.item": ITEM_SCHEMA, "umbra.note": NOTE_SCHEMA, "umbra.enemy": ENEMY_SCHEMA,
    "umbra.room": ROOM_SCHEMA, "umbra.story": STORY_SCHEMA, "umbra.night": NIGHT_SCHEMA,
    "umbra.recipe": RECIPE_SCHEMA,
}


def register_content(db: ContentDB) -> None:
    for kind, schema in KINDS.items():
        db.register_kind(kind, schema)


class Catalog:
    """Read-only view of umbra content with defensive accessors.

    ``unlocks`` is a predicate ``(unlock_id) -> bool`` supplied by the game (``world.has_unlock``); items whose
    ``unlock`` field is not satisfied are filtered out of random placement and crafting.
    """

    def __init__(self, db: ContentDB, unlocks=None):
        self.db = db
        self.has_unlock = unlocks or (lambda _u: False)

    # --- construction helpers
    @classmethod
    def load_default(cls, unlocks=None) -> "Catalog":
        """Catalog straight from ``data/`` (used by tests and tools; the game uses the shared ContentDB)."""
        db = ContentDB()
        register_content(db)
        db.load_dir(DATA_DIR, "base")
        if db.problems:
            LOG.warning("umbra content problems: %s", db.problems[:5])
        return cls(db, unlocks)

    # --- accessors
    def item(self, iid: str) -> dict:
        d = self.db.get("umbra.item", iid)
        if d is None:
            LOG.warning("unknown item %r", iid)
            return {"name": iid, "kind": "scrap", "stack": 1}
        return d

    def items(self) -> list[dict]:
        return [d for d in self.db.all("umbra.item") if self.item_available(d)]

    def item_available(self, d: dict) -> bool:
        u = d.get("unlock")
        return not u or self.has_unlock(u)

    def item_ids(self) -> list[str]:
        return [d["id"] for d in self.items()]

    def notes(self) -> list[dict]:
        return sorted(self.db.all("umbra.note"), key=lambda d: d["id"])

    def note(self, nid: str) -> dict | None:
        return self.db.get("umbra.note", nid)

    def enemy(self, eid: str) -> dict | None:
        return self.db.get("umbra.enemy", eid)

    def enemy_stat(self, eid: str, key: str, default: float) -> float:
        e = self.enemy(eid)
        return float(e["stats"].get(key, default)) if e else default

    def rooms(self) -> list[dict]:
        return sorted(self.db.all("umbra.room"), key=lambda d: d["id"])

    def stories(self) -> list[dict]:
        return sorted(self.db.all("umbra.story"), key=lambda d: d["id"])

    def night(self, n: int) -> dict:
        d = self.db.get("umbra.night", f"night_{n}") or self.db.get("umbra.night", "night_3")
        if d is None:
            raise KeyError("umbra.night content missing")
        return d

    # TODO(#15): three nights only; more nights/building styles are mostly data.
    def night_count(self) -> int:
        return len([i for i in self.db.ids("umbra.night") if i.startswith("night_")])

    def recipes(self) -> list[dict]:
        out = []
        for r in self.db.all("umbra.recipe"):
            if all(self.item_available(self.item(x)) for x in (r["a"], r["b"], r["out"])):
                out.append(r)
        return sorted(out, key=lambda d: d["id"])

    def find_recipe(self, a: str, b: str) -> dict | None:
        for r in self.recipes():
            if (r["a"], r["b"]) in ((a, b), (b, a)):
                return r
        return None
