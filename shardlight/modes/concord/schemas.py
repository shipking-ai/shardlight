"""Content schemas for the ``concord.*`` kinds (see core/content.py for the schema format)."""
from __future__ import annotations

RESOURCES = ("grain", "timber", "ore", "salt", "ink", "coin")
ROLES = ("pike", "infantry", "archer", "skirmisher", "cavalry", "siege", "healer", "banner")
ABILITY_KINDS = ("empowered_attack", "splash_attack", "self_buff", "aura_buff", "heal", "rally", "purge",
                 "reposition")
STATUSES = ("slow", "marked", "shielded", "braced", "inspired", "enraged", "stagger")
TERRAINS = ("plain", "forest", "hill", "mountain", "marsh")
TRAITS = ("skirmish", "pike_wall", "rage", "charge_plus", "flanker", "steady", "resonant_line")
BUILDING_SITES = ("barracks", "stable", "workshop")

_RES_DICT = {"type": "dict", "values": {"type": "float", "min": -500, "max": 500}}

ABILITY_FIELDS = {
    "name": {"type": "str", "required": True},
    "kind": {"type": "str", "required": True, "choices": list(ABILITY_KINDS)},
    "cd": {"type": "int", "min": 0, "max": 12},
    "mult": {"type": "float", "min": 0, "max": 4},
    "range": {"type": "int", "min": 0, "max": 8},
    "splash": {"type": "float", "min": 0, "max": 1},
    "status": {"type": "str", "choices": list(STATUSES)},
    "turns": {"type": "int", "min": 1, "max": 6},
    "amount": {"type": "float", "min": 0, "max": 60},
    "morale": {"type": "float", "min": 0, "max": 60},
    "radius": {"type": "int", "min": 0, "max": 6},
    "desc": {"type": "str"},
}

UNIT_SCHEMA = {
    "name": {"type": "str", "required": True},
    "role": {"type": "str", "required": True, "choices": list(ROLES)},
    "house": {"type": "str", "ref": "concord.house"},
    "building": {"type": "str", "required": True, "choices": list(BUILDING_SITES)},
    "tech": {"type": "str", "ref": "concord.tech"},
    "hp": {"type": "int", "required": True, "min": 8, "max": 120},
    "atk": {"type": "float", "required": True, "min": 1, "max": 40},
    "arm": {"type": "float", "required": True, "min": 0, "max": 20},
    "move": {"type": "int", "required": True, "min": 1, "max": 10},
    "range": {"type": "int", "required": True, "min": 1, "max": 8},
    "morale": {"type": "int", "min": 20, "max": 120},
    "cost": dict(_RES_DICT, required=True),
    "upkeep": {"type": "float", "min": 0, "max": 10},
    "traits": {"type": "list", "items": {"type": "str", "choices": list(TRAITS)}},
    "ability": {"type": "dict", "fields": ABILITY_FIELDS},
    "desc": {"type": "str"},
}

EFFECT_ITEM = {"type": "dict", "values": {"type": "any"}}

TECH_SCHEMA = {
    "name": {"type": "str", "required": True},
    "branch": {"type": "str", "required": True, "choices": ["martial", "civic", "lore"]},
    "tier": {"type": "int", "required": True, "min": 1, "max": 4},
    "cost": {"type": "int", "required": True, "min": 1, "max": 200},
    "requires": {"type": "list", "items": {"type": "str", "ref": "concord.tech"}},
    "requires_unlock": {"type": "str"},          # world unlock id that must be present for the tech to exist
    "player_only": {"type": "bool"},
    "effects": {"type": "list", "required": True, "items": EFFECT_ITEM},
    "desc": {"type": "str", "required": True},
}

BUILDING_SCHEMA = {
    "name": {"type": "str", "required": True},
    "cost": dict(_RES_DICT, required=True),
    "upkeep": {"type": "float", "min": 0, "max": 20},
    "turns": {"type": "int", "min": 1, "max": 6},
    "terrain": {"type": "list", "items": {"type": "str", "choices": list(TERRAINS)}},
    "max_level": {"type": "int", "min": 1, "max": 4},
    "tech": {"type": "str", "ref": "concord.tech"},
    "effects": {"type": "dict", "values": {"type": "any"}},
    "desc": {"type": "str", "required": True},
    "trade_off": {"type": "str"},
    "glyph": {"type": "str"},
}

HOUSE_SCHEMA = {
    "name": {"type": "str", "required": True},
    "epithet": {"type": "str", "required": True},
    "color": {"type": "color", "required": True},
    "goal": {"type": "str", "required": True},
    "archetype": {"type": "str", "required": True, "choices": ["expansionist", "mercantile", "defensive", "scholar"]},
    "personality": {"type": "dict", "required": True, "values": {"type": "float", "min": 0, "max": 1}},
    "modifiers": {"type": "dict", "values": {"type": "float", "min": -50, "max": 50}},
    "start": dict(_RES_DICT, required=True),
    "start_units": {"type": "list", "required": True, "items": {"type": "str", "ref": "concord.unit"}},
    "start_techs": {"type": "list", "items": {"type": "str", "ref": "concord.tech"}},
    "calendar": {"type": "dict", "required": True, "fields": {
        "fmt": {"type": "str", "required": True},
        "year0": {"type": "int"},
        "per_year": {"type": "int", "min": 1, "max": 12},
        "seasons": {"type": "list", "items": {"type": "str"}},
    }},
    "blurb": {"type": "str", "required": True},
}

EVENT_SCHEMA = {
    "title": {"type": "str", "required": True},
    "text": {"type": "str", "required": True},
    "weight": {"type": "float", "min": 0, "max": 20},
    "min_turn": {"type": "int", "min": 0, "max": 200},
    "scope": {"type": "str", "choices": ["house", "province"]},
    "terrain": {"type": "list", "items": {"type": "str", "choices": list(TERRAINS)}},
    "needs": {"type": "list", "items": {"type": "str"}},        # tags: river, army, market, war, peace, neighbour
    "options": {"type": "list", "required": True, "items": {"type": "dict", "fields": {
        "label": {"type": "str", "required": True},
        "hint": {"type": "str"},
        "ai": {"type": "float"},                                 # AI preference weight
        "effects": {"type": "list", "required": True, "items": EFFECT_ITEM},
    }}},
}

KINDS = {
    "concord.unit": UNIT_SCHEMA,
    "concord.tech": TECH_SCHEMA,
    "concord.building": BUILDING_SCHEMA,
    "concord.house": HOUSE_SCHEMA,
    "concord.event": EVENT_SCHEMA,
}
