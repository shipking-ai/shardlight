"""Content kinds (``verdant.*``) and the :class:`Catalog` accessor.  Everything Hollowmere is made of is JSON."""
from __future__ import annotations

from ...core import log
from ...core.content import ContentDB
from ...core.paths import DATA_DIR

LOG = log.get("verdant")

TEMPLATE_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 48},
    "rows": {"type": "list", "required": True, "items": {"type": "str", "max_len": 120}, "max_items": 120},
    "w": {"type": "int", "min": 3, "max": 120}, "h": {"type": "int", "min": 3, "max": 120},
    "legend": {"type": "dict", "values": {"type": "str"}},
    "default_ground": {"type": "str"},
    "spots": {"type": "dict", "values": {"type": "str"}},
    "markers": {"type": "dict", "values": {"type": "dict", "values": {"type": "any"}}},
    "buildings": {"type": "list", "items": {"type": "dict", "values": {"type": "any"}}},
    "variants": {"type": "dict", "values": {"type": "any"}},
    "meta": {"type": "dict", "values": {"type": "any"}},
    "mirror": {"type": "bool"},
}

ITEM_KINDS = ["weapon", "armor", "consumable", "material", "ammo", "key", "quest", "tool", "trade"]
ITEM_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "kind": {"type": "str", "required": True, "choices": ITEM_KINDS},
    "desc": {"type": "str", "max_len": 140},
    "value": {"type": "int", "min": 0, "max": 5000},
    "stack": {"type": "int", "min": 1, "max": 99},
    "color": {"type": "color"},
    "dmg": {"type": "float", "min": 0, "max": 80},
    "reach": {"type": "float", "min": 0, "max": 16},
    "swing": {"type": "float", "min": 0.1, "max": 3},
    "slot": {"type": "str", "choices": ["weapon", "body", "bow"]},
    "armor": {"type": "float", "min": 0, "max": 30},
    "heal": {"type": "float", "min": 0, "max": 200},
    "stamina": {"type": "float", "min": 0, "max": 100},
    "cure": {"type": "str"},
    "unlock": {"type": "str"},
    "tags": {"type": "list", "items": {"type": "str"}},
}

DROP = {"type": "dict", "fields": {"item": {"type": "str", "required": True}, "chance": {"type": "float", "min": 0, "max": 1},
                                    "min": {"type": "int", "min": 0, "max": 20}, "max": {"type": "int", "min": 0, "max": 20}}}
ENEMY_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "ai": {"type": "str", "required": True, "choices": ["melee", "ranged", "pack", "lurker", "boss"]},
    "hp": {"type": "float", "required": True, "min": 1, "max": 1000},
    "dmg": {"type": "float", "min": 0, "max": 100},
    "speed": {"type": "float", "min": 0.2, "max": 9},
    "sight": {"type": "float", "min": 1, "max": 30},
    "xp": {"type": "int", "min": 0, "max": 500},
    "color": {"type": "color"},
    "size": {"type": "float", "min": 0.3, "max": 3},
    "flee": {"type": "float", "min": 0, "max": 1},
    "night": {"type": "bool"},
    "drops": {"type": "list", "items": DROP},
    "blurb": {"type": "str", "max_len": 160},
}

NPC_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "role": {"type": "str", "max_len": 40},
    "color": {"type": "color"},
    "hair": {"type": "color"},
    "faction": {"type": "str"},
    "home": {"type": "str"},
    "schedule": {"type": "list", "required": True, "items": {"type": "dict", "fields": {
        "from": {"type": "float", "required": True, "min": 0, "max": 24}, "to": {"type": "float", "required": True, "min": 0, "max": 24},
        "at": {"type": "str", "required": True}}}},
    "shop": {"type": "str"},
    "lines": {"type": "dict", "values": {"type": "list", "items": {"type": "str", "max_len": 220}}},
    "topics": {"type": "list", "items": {"type": "dict", "fields": {
        "label": {"type": "str", "required": True, "max_len": 28}, "text": {"type": "str", "required": True, "max_len": 420},
        "need": {"type": "str"}, "set": {"type": "str"}}}},
    "bed": {"type": "bool"},
}

STAGE = {"type": "dict", "fields": {
    "id": {"type": "str"}, "text": {"type": "str", "required": True, "max_len": 160},
    "kind": {"type": "str", "required": True, "choices": ["talk", "kill", "have", "visit", "lamps", "flag", "use"]},
    "target": {"type": "str"}, "count": {"type": "int", "min": 1, "max": 99}, "consume": {"type": "bool"},
    "say": {"type": "str", "max_len": 400}, "give": {"type": "dict", "values": {"type": "int"}},
    "grant": {"type": "dict", "values": {"type": "int"}}}}
QUEST_SCHEMA = {
    "title": {"type": "str", "required": True, "max_len": 40},
    "track": {"type": "str", "choices": ["main", "side"]},
    "giver": {"type": "str", "required": True},
    "offer": {"type": "str", "required": True, "max_len": 500},
    "complete": {"type": "str", "max_len": 500},
    "requires": {"type": "dict", "values": {"type": "any"}},
    "stages": {"type": "list", "required": True, "items": STAGE},
    "reward": {"type": "dict", "values": {"type": "any"}},
    "flag": {"type": "str"},
    "lore": {"type": "str"},
}

SHOP_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "stock": {"type": "list", "required": True, "items": {"type": "dict", "fields": {
        "item": {"type": "str", "required": True}, "qty": {"type": "int", "min": 0, "max": 99}}}},
    "buys": {"type": "list", "items": {"type": "str"}},
    "markup": {"type": "float", "min": 0.5, "max": 4},
    "caravan": {"type": "list", "items": {"type": "str"}},
}

RECIPE_SCHEMA = {
    "station": {"type": "str", "required": True, "choices": ["hearth", "forge", "bench"]},
    "inputs": {"type": "dict", "required": True, "values": {"type": "int"}},
    "out": {"type": "str", "required": True},
    "count": {"type": "int", "min": 1, "max": 20},
    "skill": {"type": "int", "min": 0, "max": 10},
    "unlock": {"type": "str"},
}

LOOT_SCHEMA = {"rolls": {"type": "int", "min": 1, "max": 8}, "gold": {"type": "vec2"},
               "entries": {"type": "list", "required": True, "items": DROP}}

KINDS: dict[str, dict] = {"verdant.template": TEMPLATE_SCHEMA, "verdant.item": ITEM_SCHEMA, "verdant.enemy": ENEMY_SCHEMA,
                          "verdant.npc": NPC_SCHEMA, "verdant.quest": QUEST_SCHEMA, "verdant.shop": SHOP_SCHEMA,
                          "verdant.recipe": RECIPE_SCHEMA, "verdant.loot": LOOT_SCHEMA}


def register_content(db: ContentDB) -> None:
    for kind, schema in KINDS.items():
        db.register_kind(kind, schema)


def load_templates(db: ContentDB) -> dict[str, dict]:
    return {e["id"]: e for e in db.all("verdant.template")}




class Catalog:
    """Read-only, defensive view over the ``verdant.*`` content."""

    def __init__(self, db: ContentDB, unlocks=None):
        self.db = db
        self.has_unlock = unlocks or (lambda _u: False)
        self._templates: dict[str, dict] | None = None

    @classmethod
    def load_default(cls, unlocks=None) -> "Catalog":
        db = ContentDB()
        register_content(db)
        db.load_dir(DATA_DIR, "base")
        if db.problems:
            LOG.warning("verdant content problems: %s", db.problems[:5])
        return cls(db, unlocks)

    @property
    def templates(self) -> dict[str, dict]:
        if self._templates is None:
            self._templates = load_templates(self.db)
        return self._templates

    def item(self, iid: str) -> dict:
        d = self.db.get("verdant.item", iid)
        if d is None:
            LOG.warning("unknown item %r", iid)
            return {"id": iid, "name": iid, "kind": "trade", "value": 0, "stack": 1, "color": [200, 200, 200]}
        return d

    def has_item(self, iid: str) -> bool:
        return self.db.get("verdant.item", iid) is not None

    def item_ok(self, iid: str) -> bool:
        u = self.item(iid).get("unlock")
        return not u or self.has_unlock(u)

    def enemy(self, eid: str) -> dict:
        d = self.db.get("verdant.enemy", eid)
        if d is None:
            LOG.warning("unknown enemy %r", eid)
            return self.db.get("verdant.enemy", "wolf") or {"id": eid, "name": eid, "ai": "melee", "hp": 10, "dmg": 2}
        return d

    def npc(self, nid: str) -> dict | None:
        return self.db.get("verdant.npc", nid)

    def npcs(self) -> list[dict]:
        return sorted(self.db.all("verdant.npc"), key=lambda d: d["id"])

    def quest(self, qid: str) -> dict | None:
        return self.db.get("verdant.quest", qid)

    def quests(self) -> list[dict]:
        return sorted(self.db.all("verdant.quest"), key=lambda d: d["id"])

    def shop(self, sid: str) -> dict | None:
        return self.db.get("verdant.shop", sid)

    def recipes(self, station: str | None = None) -> list[dict]:
        rs = [r for r in self.db.all("verdant.recipe") if (station is None or r["station"] == station)]
        rs = [r for r in rs if not r.get("unlock") or self.has_unlock(r["unlock"])]
        return sorted(rs, key=lambda d: (d["station"], d.get("skill", 0), d["id"]))

    def loot(self, lid: str) -> dict | None:
        return self.db.get("verdant.loot", lid)
