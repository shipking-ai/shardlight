"""Static rules derived from the ``concord.*`` content kinds.

``Rules`` is the read-only data every pure-logic module consults: units, techs, buildings, houses, events,
plus numeric constants.  It is built from the ContentDB (so mods can add or override entries) or, in tests,
from the JSON files shipped in ``data/``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...core.content import ContentDB
from ...core.paths import DATA_DIR
from .schemas import KINDS, RESOURCES

# ------------------------------------------------------------------------------------------ constants
TERRAIN_MOVE = {"plain": 1, "forest": 2, "hill": 2, "marsh": 3, "mountain": 3}
TERRAIN_SLOTS = {"plain": 3, "forest": 2, "hill": 3, "marsh": 2, "mountain": 2}
TERRAIN_POP = {"plain": 2, "forest": 1, "hill": 1, "marsh": 1, "mountain": 0}
TERRAIN_BASE = {
    "plain": {"grain": 2, "coin": 1},
    "forest": {"timber": 2, "grain": 0},
    "hill": {"ore": 1, "grain": 1},
    "mountain": {"ore": 2},
    "marsh": {"salt": 1, "grain": 1},
}
TERRAIN_SUPPLY_COST = {"plain": 1.0, "forest": 1.0, "hill": 1.0, "marsh": 1.5, "mountain": 1.5}
TERRAIN_ATTRITION = {"plain": 1.0, "forest": 1.0, "hill": 1.0, "marsh": 1.5, "mountain": 1.5}
TERRAIN_NAMES = {"plain": "Plain", "forest": "Forest", "hill": "Hills", "marsh": "Marsh", "mountain": "Mountain"}
RES_LABEL = {"grain": "Grain", "timber": "Timber", "ore": "Ore", "salt": "Salt", "ink": "Ink", "coin": "Coin"}

STACK_LIMIT = 8                  # units per army
BASE_STORAGE = 80
BASE_RESEARCH_RATE = 4
CAPITAL_SUPPLY = 5
ARMY_MOVE_FOOT = 2
ARMY_MOVE_MOUNTED = 3
ARMY_MOVE_SIEGE = 1
RANK_NAMES = ("Green", "Blooded", "Veteran", "Elite")


@dataclass
class Rules:
    units: dict[str, dict] = field(default_factory=dict)
    techs: dict[str, dict] = field(default_factory=dict)
    buildings: dict[str, dict] = field(default_factory=dict)
    houses: dict[str, dict] = field(default_factory=dict)
    events: dict[str, dict] = field(default_factory=dict)

    # ---------------------------------------------------------------------- construction
    @classmethod
    def from_db(cls, db: ContentDB) -> "Rules":
        def grab(kind: str) -> dict[str, dict]:
            return {e["id"]: e for e in db.all(kind)}

        return cls(grab("concord.unit"), grab("concord.tech"), grab("concord.building"),
                   grab("concord.house"), grab("concord.event"))

    @classmethod
    def load_default(cls) -> "Rules":
        """Load and validate the shipped data without an App (used by tests and tools)."""
        db = ContentDB()
        for kind, schema in KINDS.items():
            db.register_kind(kind, schema)
        db.load_dir(DATA_DIR, "base")
        problems = [p for p in db.problems + db.check_refs() if "concord" in p]
        if problems:
            raise ValueError("concord content problems: " + "; ".join(problems[:8]))
        return cls.from_db(db)

    # ---------------------------------------------------------------------- queries
    def house_ids(self) -> list[str]:
        return sorted(self.houses)

    def house_units(self, house: str) -> list[str]:
        """Unit ids a house can ever recruit: all generic units plus its own."""
        return sorted(uid for uid, u in self.units.items() if u.get("house") in (None, house))

    def tech_exists(self, tid: str, unlocks: frozenset[str] | set[str]) -> bool:
        t = self.techs.get(tid)
        if t is None:
            return False
        need = t.get("requires_unlock")
        return not need or need in unlocks

    def tech_list(self, unlocks: frozenset[str] | set[str]) -> list[str]:
        order = {"martial": 0, "civic": 1, "lore": 2}
        ids = [t for t in self.techs if self.tech_exists(t, unlocks)]
        return sorted(ids, key=lambda t: (order[self.techs[t]["branch"]], self.techs[t]["tier"], t))

    def validate(self) -> list[str]:
        """Cross-reference sanity checks used by tests."""
        errs: list[str] = []
        for uid, u in self.units.items():
            if u.get("house") and u["house"] not in self.houses:
                errs.append(f"unit {uid}: unknown house")
            if u.get("tech") and u["tech"] not in self.techs:
                errs.append(f"unit {uid}: unknown tech")
            for r in u["cost"]:
                if r not in RESOURCES:
                    errs.append(f"unit {uid}: bad resource {r}")
        for tid, t in self.techs.items():
            for r in t.get("requires", []):
                if r not in self.techs:
                    errs.append(f"tech {tid}: unknown prerequisite {r}")
        for hid, h in self.houses.items():
            for uid in h["start_units"]:
                if uid not in self.units:
                    errs.append(f"house {hid}: unknown unit {uid}")
        return errs


def mounted(unit_def: dict[str, Any]) -> bool:
    return unit_def["role"] == "cavalry"


# ----------------------------------------------------------------------------------- modifier aggregation
def house_mods(rules: Rules, house_id: str, techs: list[str]) -> dict[str, float]:
    """Sum of a house's innate modifiers and the ``mod`` effects of every researched tech."""
    out: dict[str, float] = dict(rules.houses.get(house_id, {}).get("modifiers", {}))
    for tid in techs:
        for eff in rules.techs.get(tid, {}).get("effects", []):
            if eff.get("kind") == "mod":
                out[eff["key"]] = out.get(eff["key"], 0.0) + float(eff["value"])
    return out


def tech_unit_effects(rules: Rules, techs: list[str]) -> list[dict]:
    """The ``unit_mod`` and ``upgrade`` effects of researched techs."""
    out = []
    for tid in techs:
        for eff in rules.techs.get(tid, {}).get("effects", []):
            if eff.get("kind") in ("unit_mod", "upgrade"):
                out.append(eff)
    return out
