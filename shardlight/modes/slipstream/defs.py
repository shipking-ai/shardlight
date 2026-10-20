"""Content kinds for Slipstream: vehicles and championship cups (moddable JSON)."""
from __future__ import annotations

from ...core import log
from .vehicle import FALLBACK_VEHICLE, UPGRADE_SLOTS, VehicleSpec, spec_from_dict

LOG = log.get("slipstream")
K_VEHICLE = "slipstream.vehicle"
K_CUP = "slipstream.cup"

_NUM = {"type": "float"}
VEHICLE_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 24},
    "tagline": {"type": "str", "max_len": 80},
    "class": {"type": "str", "choices": ["grip", "drift", "heavy", "boost", "balanced", "time"]},
    "power": {"type": "float", "min": 50, "max": 160}, "top_speed": {"type": "float", "min": 180, "max": 360},
    "brake": {"type": "float", "min": 250, "max": 800}, "grip": {"type": "float", "min": 0.5, "max": 1.8},
    "steer": {"type": "float", "min": 0.25, "max": 0.8}, "agility": {"type": "float", "min": 0.8, "max": 1.8},
    "slide": {"type": "float", "min": 0.08, "max": 0.9}, "mass": {"type": "float", "min": 0.5, "max": 2.5},
    "boost_cap": {"type": "float", "min": 40, "max": 220}, "boost_power": {"type": "float", "min": 0.5, "max": 2.0},
    "drift_charge": {"type": "float", "min": 0.3, "max": 2.5}, "draft": {"type": "float", "min": 0.0, "max": 2.5},
    "front_weight": {"type": "float", "min": 0.3, "max": 0.7},
    "length": {"type": "float", "min": 16, "max": 34}, "width": {"type": "float", "min": 8, "max": 18},
    "body": {"type": "dict", "values": {"type": "any"}},
    "color": {"type": "color"}, "price": {"type": "int", "min": 0, "max": 99999},
    "special": {"type": "str", "choices": ["", "rewind"]},
    "requires_unlock": {"type": "str", "max_len": 64},
    "upgrades": {"type": "dict", "values": {"type": "dict", "fields": {
        "name": {"type": "str", "max_len": 28}, "desc": {"type": "str", "max_len": 100},
        "effects": {"type": "dict", "values": {"type": "float"}},
        "cost": {"type": "list", "items": {"type": "int"}, "max_items": 3}}}},
}
CUP_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 28},
    "blurb": {"type": "str", "max_len": 160},
    "tracks": {"type": "list", "required": True, "max_items": 12, "items": {"type": "dict", "fields": {
        "seed": {"type": "int", "required": True, "min": 0, "max": 99999999},
        "laps": {"type": "int", "min": 1, "max": 8}, "name": {"type": "str", "max_len": 28}}}},
    "points": {"type": "list", "items": {"type": "int"}, "max_items": 8},
    "rival_skill": {"type": "float", "min": 0.3, "max": 1.0},
    "prize": {"type": "int", "min": 0, "max": 5000},
}


def register_content(db) -> None:
    db.register_kind(K_VEHICLE, VEHICLE_SCHEMA)
    db.register_kind(K_CUP, CUP_SCHEMA)


class Garage:
    """Typed vehicles available to the player (honours unlock gating)."""

    def __init__(self, db, world=None):
        self.raw: dict[str, dict] = {}
        for d in db.all(K_VEHICLE):
            self.raw[d["id"]] = d
        if not self.raw:
            LOG.warning("no vehicles in content; using fallback")
            self.raw[FALLBACK_VEHICLE["id"]] = FALLBACK_VEHICLE
        self.world = world

    def ids(self) -> list[str]:
        return list(self.raw)

    def available(self, vid: str) -> bool:
        need = self.raw[vid].get("requires_unlock", "")
        return not need or (self.world is not None and self.world.has_unlock(need))

    def spec(self, vid: str, levels: dict | None = None) -> VehicleSpec:
        return spec_from_dict(self.raw[vid], levels)
