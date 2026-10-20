"""Content schema for kind ``masks.character`` (validated by core.content, so mods can add fighters)."""
from __future__ import annotations

_INT = {"type": "int"}
_RECT = {"type": "list", "items": _INT, "max_items": 4}
_HIT = {"type": "dict", "fields": {
    "damage": {"type": "int", "min": 0, "max": 400},
    "hitstun": {"type": "int", "min": 0, "max": 80},
    "blockstun": {"type": "int", "min": 0, "max": 60},
    "hitstop": {"type": "int", "min": 0, "max": 20},
    "push_hit": {"type": "int", "min": 0, "max": 80},
    "push_block": {"type": "int", "min": 0, "max": 80},
    "launch": {"type": "list", "items": _INT, "max_items": 2},
    "knockdown": {"type": "bool"},
    "height": {"type": "str", "choices": ["high", "mid", "low"]},
    "meter_hit": {"type": "int", "min": 0, "max": 300},
    "meter_block": {"type": "int", "min": 0, "max": 200},
    "juggle": {"type": "int", "min": 0, "max": 6},
    "starter": {"type": "int", "min": 10, "max": 100},
    "chip": {"type": "int", "min": 0, "max": 50},
    "spark": {"type": "str", "choices": ["light", "med", "heavy", "slash", "ring"]},
    "unblockable": {"type": "bool"},
    "slow_zone": {"type": "bool"},
    "pull": {"type": "int", "min": 0, "max": 400},
}}
_BOX = {"type": "dict", "fields": {
    "rect": {"type": "list", "items": _INT, "required": True, "max_items": 4},
    "from": _INT, "to": _INT, "group": _INT, "hit": _HIT,
}}
_MOVE = {"type": "dict", "fields": {
    "name": {"type": "str", "required": True, "max_len": 40},
    "input": {"type": "str", "max_len": 16},
    "kind": {"type": "str", "choices": ["normal", "special", "super", "throw", "follow", "system"]},
    "air": {"type": "bool"},
    "stance": {"type": "str", "choices": ["stand", "crouch", "air"]},
    "startup": {"type": "int", "required": True, "min": 1, "max": 120},
    "active": {"type": "int", "required": True, "min": 1, "max": 120},
    "recovery": {"type": "int", "required": True, "min": 0, "max": 120},
    "hit": _HIT,
    "hitboxes": {"type": "list", "items": _BOX, "max_items": 12},
    "hurt": {"type": "list", "items": _BOX, "max_items": 12},
    "cancels": {"type": "list", "max_items": 12, "items": {"type": "dict", "fields": {
        "on": {"type": "str", "required": True, "choices": ["hit", "block", "contact", "whiff", "always"]},
        "into": {"type": "list", "required": True, "items": {"type": "str"}, "max_items": 12},
        "from": _INT, "to": _INT}}},
    "invuln": {"type": "list", "max_items": 6, "items": {"type": "dict", "fields": {
        "from": {"type": "int", "required": True}, "to": {"type": "int", "required": True},
        "kind": {"type": "str", "choices": ["all", "strike", "throw", "projectile"]}}}},
    "armor": {"type": "dict", "fields": {"from": {"type": "int", "required": True},
                                         "to": {"type": "int", "required": True}, "hits": _INT}},
    "counter": {"type": "dict", "fields": {"from": {"type": "int", "required": True},
                                           "to": {"type": "int", "required": True},
                                           "height": {"type": "str", "choices": ["high", "mid", "low", "any"]},
                                           "into": {"type": "str", "required": True}}},
    "move": {"type": "list", "max_items": 10, "items": {"type": "dict", "fields": {
        "from": {"type": "int", "required": True}, "to": {"type": "int", "required": True},
        "vx": _INT, "vy": _INT}}},
    "projectile": {"type": "dict", "fields": {
        "frame": {"type": "int", "required": True}, "rect": {"type": "list", "items": _INT, "required": True},
        "offset": {"type": "list", "items": _INT, "required": True, "max_items": 2},
        "vx": _INT, "vy": _INT, "life": {"type": "int", "required": True, "min": 1, "max": 600},
        "hit": _HIT, "hits": _INT, "gravity": _INT,
        "kind": {"type": "str", "choices": ["projectile", "talisman", "wave"]},
        "limit": {"type": "int", "min": 1, "max": 4}, "destroy_on_hit": {"type": "bool"}}},
    "throw": {"type": "dict", "fields": {
        "reach": {"type": "int", "required": True, "min": 4, "max": 80}, "hit": _HIT, "tech": {"type": "bool"},
        "grab_frames": {"type": "int", "min": 8, "max": 60}, "air": {"type": "bool"},
        "release_vx": _INT, "swap": {"type": "bool"}}},
    "zone": {"type": "dict", "fields": {
        "frame": {"type": "int", "required": True}, "rect": {"type": "list", "items": _INT, "required": True},
        "offset": _INT, "life": {"type": "int", "required": True, "min": 1, "max": 600},
        "slow": {"type": "int", "min": 2, "max": 6}}},
    "echo": {"type": "bool"},
    "cost": {"type": "int", "min": 0, "max": 1000},
    "pose": {"type": "str", "max_len": 24},
    "tags": {"type": "list", "items": {"type": "str"}, "max_items": 8},
    "land_recovery": {"type": "int", "min": 0, "max": 40},
    "desc": {"type": "str", "max_len": 160},
    "superflash": {"type": "int", "min": 0, "max": 60},
    "hold_move": {"type": "bool"},
}}

CHARACTER_SCHEMA = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "title": {"type": "str", "max_len": 48},
    "feeling": {"type": "str", "max_len": 24},
    "archetype": {"type": "str", "choices": ["rushdown", "zoner", "grappler", "counter", "time", "boss", "all"]},
    "desc": {"type": "str", "max_len": 240},
    "color": {"type": "color", "required": True},
    "accent": {"type": "color", "required": True},
    "health": {"type": "int", "min": 600, "max": 1400},
    "walk_f": {"type": "int", "required": True, "min": 10, "max": 80},
    "walk_b": {"type": "int", "required": True, "min": 10, "max": 80},
    "jump": {"type": "dict", "required": True, "fields": {
        "pre": {"type": "int", "min": 2, "max": 8}, "vy": {"type": "int", "required": True, "min": 80, "max": 300},
        "vx": {"type": "int", "required": True, "min": 10, "max": 80}, "gravity": {"type": "int", "min": 4, "max": 16}}},
    "dash_f": {"type": "dict", "required": True, "fields": {
        "frames": {"type": "int", "required": True, "min": 6, "max": 40},
        "vx": {"type": "int", "required": True, "min": 20, "max": 160}, "cancel": _INT}},
    "dash_b": {"type": "dict", "required": True, "fields": {
        "frames": {"type": "int", "required": True, "min": 8, "max": 40},
        "vx": {"type": "int", "required": True, "min": 20, "max": 160},
        "invuln": {"type": "int", "min": 0, "max": 14}, "recovery": {"type": "int", "min": 0, "max": 12}}},
    "push_half": {"type": "int", "min": 6, "max": 24},
    "hurt": {"type": "dict", "required": True, "fields": {
        "stand": _RECT, "crouch": _RECT, "air": _RECT}},
    "moves": {"type": "dict", "required": True, "values": _MOVE},
    "mech": {"type": "str", "max_len": 200},
    "boss": {"type": "bool"},
    "selectable": {"type": "bool"},
    "requires_unlock": {"type": "str", "max_len": 64},
    "build": {"type": "dict", "values": {"type": "any"}},
}
