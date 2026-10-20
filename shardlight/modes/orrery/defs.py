"""Content schemas and the ``Defs`` accessor for the Orrery.

All tunable game data (goods, civilisations, techs, hulls, modules, weapons, signals) is JSON content of kinds
``orrery.*`` so mods can extend it.  Simulation code never hard-codes id lists; it asks ``Defs``.
"""
from __future__ import annotations

from ...core.content import ContentDB
from ...core.paths import DATA_DIR

_NUM = {"type": "float"}
_STR = {"type": "str"}

GOOD_SCHEMA = {
    "name": {"type": "str", "required": True}, "short": _STR,
    "base": {"type": "float", "required": True, "min": 1}, "tier": {"type": "str", "choices": ["raw", "made"]},
    "color": {"type": "color"}, "desc": _STR,
    "recipe": {"type": "dict", "values": _NUM},
}
CIV_SCHEMA = {
    "name": {"type": "str", "required": True}, "short": _STR, "color": {"type": "color", "required": True},
    "style": _STR, "specialty": {"type": "str", "ref": "orrery.good"}, "lack": {"type": "str", "ref": "orrery.good"},
    "likes": {"type": "list", "items": {"type": "str", "ref": "orrery.civ"}},
    "dislikes": {"type": "list", "items": {"type": "str", "ref": "orrery.civ"}},
    "traits": {"type": "dict", "values": _NUM},
    "techs": {"type": "list", "items": {"type": "str", "ref": "orrery.tech"}}, "blurb": _STR,
}
TECH_SCHEMA = {
    "name": {"type": "str", "required": True}, "branch": _STR, "cost": {"type": "float", "required": True, "min": 1},
    "requires": {"type": "list", "items": {"type": "str", "ref": "orrery.tech"}},
    "effects": {"type": "dict", "values": _NUM}, "unlocks_module": {"type": "str", "ref": "orrery.module"},
    "text": _STR,
}
HULL_SCHEMA = {
    "name": {"type": "str", "required": True}, "style": _STR, "price": {"type": "float", "min": 0}, "desc": _STR,
    "unlock": _STR, "ability": _STR, "stats": {"type": "dict", "values": _NUM, "required": True},
}
MODULE_SCHEMA = {
    "name": {"type": "str", "required": True}, "price": {"type": "float", "min": 0}, "power": {"type": "float", "min": 0},
    "heat": {"type": "float", "min": 0}, "basic": {"type": "bool"}, "tech": {"type": "str", "ref": "orrery.tech"},
    "blueprint": {"type": "bool"}, "add": {"type": "dict", "values": _NUM}, "mul": {"type": "dict", "values": _NUM},
    "desc": _STR,
}
WEAPON_SCHEMA = {
    "name": {"type": "str", "required": True},
    "kind": {"type": "str", "required": True, "choices": ["pulse", "missile", "beam"]}, "desc": _STR,
    **{k: _NUM for k in ("damage", "speed", "rate", "energy", "heat", "life", "spread", "shield_mul", "hull_mul",
                         "turn", "blast", "lock_time", "lock_cone", "range", "overcharge_after", "overcharge_mul",
                         "overcharge_heat")},
}
SIGNAL_SCHEMA = {
    "name": {"type": "str", "required": True}, "always": {"type": "bool"}, "unlock": _STR,
    "range": {"type": "float", "required": True, "min": 10}, "puzzle": {"type": "str", "choices": ["sequence", "lock"]},
    "length": {"type": "int", "min": 3, "max": 6}, "symbols": {"type": "int", "min": 4, "max": 8}, "emitter": _STR,
    "heard": _STR, "text": {"type": "str", "max_len": 380}, "reward": {"type": "dict", "values": {"type": "any"}},
}

KINDS = {
    "orrery.good": GOOD_SCHEMA, "orrery.civ": CIV_SCHEMA, "orrery.tech": TECH_SCHEMA, "orrery.hull": HULL_SCHEMA,
    "orrery.module": MODULE_SCHEMA, "orrery.weapon": WEAPON_SCHEMA, "orrery.signal": SIGNAL_SCHEMA,
}

# Default values so a mod-supplied entry that omits optional numbers still works.
HULL_DEFAULTS = {"hull": 100, "shield": 60, "shield_regen": 8, "shield_delay": 3.0, "energy": 100, "energy_regen": 20,
                 "thrust": 240, "max_speed": 220, "boost": 1.7, "rot": 180, "strafe": 0.5, "mass": 10, "power": 10,
                 "slots": 5, "cooling": 18, "heat_cap": 100, "cargo": 20, "fuel": 14, "range": 160, "missiles": 3,
                 "decoys": 2, "scan_range": 150, "scan_band": 0.16, "bearing_error": 7.0, "lock_time": 1.0,
                 "beam_overcharge": 0.0, "beam_heat": 1.0}


def register_content(db: ContentDB) -> None:
    for kind, schema in KINDS.items():
        db.register_kind(kind, schema)


class Defs:
    """Read-only view over the content database for the Orrery's kinds."""

    def __init__(self, db: ContentDB):
        self.db = db
        self.goods = self._load("orrery.good")
        self.civs = self._load("orrery.civ")
        self.techs = self._load("orrery.tech")
        self.hulls = self._load("orrery.hull")
        self.modules = self._load("orrery.module")
        self.weapons = self._load("orrery.weapon")
        self.signals = self._load("orrery.signal")

    def _load(self, kind: str) -> dict[str, dict]:
        return {e["id"]: e for e in sorted(self.db.all(kind), key=lambda d: d["id"])}

    # -- helpers ---------------------------------------------------------------------------
    def hull_stats(self, hull_id: str) -> dict[str, float]:
        h = self.hulls.get(hull_id) or self.hulls["wayfarer"]
        out = dict(HULL_DEFAULTS)
        out.update(h["stats"])
        return out

    def good_ids(self) -> list[str]:
        """Goods in dependency order (raw first, then made goods by id)."""
        return sorted(self.goods, key=lambda g: (self.goods[g].get("tier", "raw") != "raw", g))

    def civ_ids(self) -> list[str]:
        return list(self.civs)

    def enabled_signals(self, has_unlock) -> list[str]:
        """Signal ids that exist in this run (always-on ones plus those whose unlock id is held)."""
        out = []
        for sid, s in self.signals.items():
            if s.get("always") or (s.get("unlock") and has_unlock(s["unlock"])):
                out.append(sid)
        return out


_STANDALONE: Defs | None = None


def standalone_defs() -> Defs:
    """Defs built from the base data directory without an App (used by pure-logic tests and tools)."""
    global _STANDALONE
    if _STANDALONE is None:
        db = ContentDB()
        register_content(db)
        db.load_dir(DATA_DIR, "base")
        _STANDALONE = Defs(db)
    return _STANDALONE
