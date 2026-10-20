"""Content schemas and typed views over the data files (kinds ``cinder.weapon/enemy/boon/modifier``).

The ContentDB validates structure; :class:`Library` then builds typed objects and applies *semantic*
checks (known stat keys, known AI kinds, resolvable evolution targets).  Anything invalid is skipped
with a log warning - a broken mod entry must never crash the game.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...core import log

LOG = log.get("cinder")

K_WEAPON = "cinder.weapon"
K_ENEMY = "cinder.enemy"
K_BOON = "cinder.boon"
K_MOD = "cinder.modifier"

AI_KINDS = ("swarmer", "kiter", "shield", "bomber", "charger", "summoner", "sniper", "dummy")
SHAPES = ("arc", "thrust", "circle", "ring", "proj", "none")
RARITIES = ("common", "rare", "epic")

# ------------------------------------------------------------------------------ schemas
_APPLY = {"type": "list", "max_items": 6, "items": {"type": "dict", "fields": {
    "status": {"type": "str", "required": True, "choices": ["burn", "ash", "shock", "rend"]},
    "stacks": {"type": "int", "min": 1, "max": 5},
    "chance": {"type": "float", "min": 0, "max": 1},
}}}

_PROJ = {"type": "dict", "fields": {
    "speed": {"type": "float", "min": 0.5, "max": 12},
    "radius": {"type": "float", "min": 1, "max": 24},
    "life": {"type": "int", "min": 1, "max": 600},
    "pierce": {"type": "int", "min": 0, "max": 20},
    "ricochet": {"type": "int", "min": 0, "max": 8},
    "count": {"type": "int", "min": 1, "max": 16},
    "spread": {"type": "float", "min": 0, "max": 180},
    "homing": {"type": "float", "min": 0, "max": 1},
    "kind": {"type": "str", "choices": ["bolt", "arc", "needle", "orb"]},
    "chain": {"type": "int", "min": 0, "max": 6},
}}

MOVE_FIELDS: dict[str, dict] = {
    "name": {"type": "str", "required": True, "max_len": 32},
    "windup": {"type": "int", "min": 0, "max": 120},
    "active": {"type": "int", "min": 1, "max": 120},
    "recover": {"type": "int", "min": 0, "max": 120},
    "cancel": {"type": "int", "min": 0, "max": 120},
    "shape": {"type": "str", "choices": list(SHAPES)},
    "reach": {"type": "float", "min": 0, "max": 400},
    "arc": {"type": "float", "min": 1, "max": 360},
    "width": {"type": "float", "min": 1, "max": 200},
    "offset": {"type": "float", "min": -40, "max": 120},
    "inner": {"type": "float", "min": 0, "max": 300},
    "damage": {"type": "float", "min": 0, "max": 20},
    "poise": {"type": "float", "min": 0, "max": 20},
    "knock": {"type": "float", "min": 0, "max": 20},
    "stop": {"type": "int", "min": 0, "max": 20},
    "shake": {"type": "float", "min": 0, "max": 1},
    "lunge": {"type": "float", "min": 0, "max": 12},
    "lunge_frames": {"type": "int", "min": 0, "max": 40},
    "move_mult": {"type": "float", "min": 0, "max": 1.5},
    "apply": _APPLY,
    "proj": _PROJ,
    "sfx": {"type": "str", "max_len": 40},
    "fx": {"type": "str", "max_len": 24},
    "hits": {"type": "int", "min": 1, "max": 8},
    "interval": {"type": "int", "min": 1, "max": 60},
    "armor": {"type": "bool"},
    "tags": {"type": "list", "max_items": 8, "items": {"type": "str", "max_len": 20}},
}
_MOVE = {"type": "dict", "fields": MOVE_FIELDS}

WEAPON_SCHEMA: dict[str, dict] = {
    "name": {"type": "str", "required": True, "max_len": 28},
    "family": {"type": "str", "required": True, "max_len": 20},
    "desc": {"type": "str", "max_len": 160},
    "damage": {"type": "float", "required": True, "min": 1, "max": 400},
    "color": {"type": "color"},
    "light": {"type": "list", "required": True, "max_items": 6, "items": _MOVE},
    "heavy": {"type": "list", "required": True, "max_items": 5, "items": {"type": "dict", "fields": {
        "hold": {"type": "int", "required": True, "min": 0, "max": 240},
        "move": {"type": "dict", "required": True, "fields": MOVE_FIELDS},
    }}},
    "charge_speed": {"type": "float", "min": 0, "max": 1.5},
    "charge_armor": {"type": "bool"},
    "dash_attack": _MOVE,
    "riposte": _MOVE,
    "dodge": {"type": "dict", "fields": {
        "kind": {"type": "str", "choices": ["roll", "vault"]},
        "dist": {"type": "float", "min": 10, "max": 160},
        "frames": {"type": "int", "min": 6, "max": 40},
        "iframes": {"type": "int", "min": 2, "max": 36},
        "recover": {"type": "int", "min": 0, "max": 30},
    }},
    "parry": {"type": "dict", "fields": {
        "window": {"type": "int", "min": 4, "max": 14},
        "recover": {"type": "int", "min": 6, "max": 40},
        "riposte_frames": {"type": "int", "min": 0, "max": 60},
        "reflect": {"type": "float", "min": 1, "max": 6},
        "shockwave": {"type": "float", "min": 0, "max": 200},
    }},
    "evolutions": {"type": "list", "max_items": 3, "items": {"type": "dict", "fields": {
        "to": {"type": "str", "required": True, "ref": K_WEAPON},
        "when": {"type": "list", "required": True, "max_items": 4, "items": {"type": "dict", "fields": {
            "counter": {"type": "str"},
            "count": {"type": "int", "min": 1, "max": 999},
            "boon": {"type": "str", "ref": K_BOON},
        }}},
        "text": {"type": "str", "max_len": 120},
    }}},
    "unlock": {"type": "dict", "fields": {"cost": {"type": "int", "min": 0, "max": 9999}}},
    "tier": {"type": "int", "min": 1, "max": 3},
    "evolved": {"type": "bool"},
}

ENEMY_SCHEMA: dict[str, dict] = {
    "name": {"type": "str", "required": True, "max_len": 28},
    "ai": {"type": "str", "required": True, "choices": list(AI_KINDS)},
    "hp": {"type": "float", "required": True, "min": 1, "max": 5000},
    "speed": {"type": "float", "min": 0, "max": 4},
    "radius": {"type": "float", "min": 3, "max": 24},
    "damage": {"type": "float", "min": 0, "max": 100},
    "poise": {"type": "float", "min": 0, "max": 500},
    "cost": {"type": "float", "min": 0.5, "max": 40},
    "min_floor": {"type": "int", "min": 1, "max": 8},
    "weight": {"type": "float", "min": 0, "max": 100},
    "role": {"type": "str", "max_len": 16},
    "vision": {"type": "dict", "fields": {
        "range": {"type": "float", "min": 20, "max": 600},
        "fov": {"type": "float", "min": 30, "max": 360},
        "peripheral": {"type": "float", "min": 0, "max": 200},
    }},
    "reaction": {"type": "int", "min": 0, "max": 60},
    "retreat": {"type": "float", "min": 0, "max": 0.6},
    "params": {"type": "dict", "values": {"type": "any"}},
    "elite": {"type": "dict", "fields": {
        "name": {"type": "str", "required": True, "max_len": 28},
        "trait": {"type": "str", "required": True, "max_len": 24},
        "hp_mul": {"type": "float", "min": 1, "max": 6},
        "cost": {"type": "float", "min": 1, "max": 60},
        "min_floor": {"type": "int", "min": 1, "max": 8},
        "params": {"type": "dict", "values": {"type": "any"}},
    }},
    "art": {"type": "dict", "values": {"type": "any"}},
    "desc": {"type": "str", "max_len": 120},
}

STAT_KEYS = (
    "damage_mul", "move_speed_mul", "max_hp_add", "max_hp_mul", "attack_speed_mul", "dodge_iframes_add",
    "dodge_recover_mul", "dodge_dist_mul", "parry_window_add", "parry_recover_mul", "burn_taken_mul",
    "damage_taken_mul", "status_power_mul", "heal_mul", "slag_mul", "crit_chance", "poise_mul",
    "flashover_radius_mul", "flashover_self", "chain_nova_heal", "ricochet_add", "pierce_add", "reach_mul",
    "charge_speed_mul", "flare_gain_mul", "shop_price_mul", "ash_move_penalty", "shock_self",
    "kill_streak_dmg", "revive", "reflect_mul", "trail_burn_taken",
)

BOON_ACTIONS = (
    "flame_trail", "apply_status_near", "heal", "gold", "nova", "refresh_dodge", "buff", "shield",
    "burst_bolts", "flare_charge", "explode_target", "ash_cloud",
)
BOON_EVENTS = ("dodge", "hit", "kill", "parry", "damaged", "room_clear", "perfect_dodge", "flashover",
               "chain_nova", "charge_release", "poise_break")

BOON_SCHEMA: dict[str, dict] = {
    "name": {"type": "str", "required": True, "max_len": 28},
    "desc": {"type": "str", "required": True, "max_len": 120},
    "cost": {"type": "str", "max_len": 100},          # the tradeoff, shown in warning colour
    "rarity": {"type": "str", "choices": list(RARITIES)},
    "tags": {"type": "list", "max_items": 6, "items": {"type": "str", "max_len": 16}},
    "stats": {"type": "dict", "values": {"type": "float"}},
    "triggers": {"type": "list", "max_items": 4, "items": {"type": "dict", "fields": {
        "on": {"type": "str", "required": True, "choices": list(BOON_EVENTS)},
        "do": {"type": "str", "required": True, "choices": list(BOON_ACTIONS)},
        "chance": {"type": "float", "min": 0, "max": 1},
        "cooldown": {"type": "int", "min": 0, "max": 1200},
        "args": {"type": "dict", "values": {"type": "any"}},
        "needs_status": {"type": "str"},
    }}},
    "max_stacks": {"type": "int", "min": 1, "max": 5},
    "weight": {"type": "float", "min": 0, "max": 100},
    "requires": {"type": "dict", "fields": {
        "family": {"type": "list", "items": {"type": "str"}},
        "boons": {"type": "list", "items": {"type": "str", "ref": K_BOON}},
    }},
    "unlock": {"type": "dict", "fields": {"cost": {"type": "int", "min": 0, "max": 9999}}},
}

MOD_KEYS = (
    "enemy_hp", "enemy_damage", "enemy_speed", "elite_chance", "extra_budget", "reaction_cut", "player_hp",
    "heal_mul", "slag_mul", "parry_window", "fire_floor", "death_burst", "dim_light", "fewer_rewards",
    "boss_hp",
)
MOD_SCHEMA: dict[str, dict] = {
    "name": {"type": "str", "required": True, "max_len": 28},
    "desc": {"type": "str", "required": True, "max_len": 120},
    "heat": {"type": "int", "required": True, "min": 1, "max": 10},
    "effects": {"type": "dict", "required": True, "values": {"type": "float"}},
    "unlock": {"type": "dict", "fields": {"cost": {"type": "int", "min": 0, "max": 9999}}},
    "tags": {"type": "list", "max_items": 4, "items": {"type": "str"}},
}


def register_content(db) -> None:
    db.register_kind(K_WEAPON, WEAPON_SCHEMA)
    db.register_kind(K_ENEMY, ENEMY_SCHEMA)
    db.register_kind(K_BOON, BOON_SCHEMA)
    db.register_kind(K_MOD, MOD_SCHEMA)


# ------------------------------------------------------------------------------ typed views
@dataclass
class MoveDef:
    name: str
    windup: int = 4
    active: int = 3
    recover: int = 10
    cancel: int = 0
    shape: str = "arc"
    reach: float = 30.0
    arc: float = 120.0
    width: float = 14.0
    offset: float = 0.0
    inner: float = 0.0
    damage: float = 1.0
    poise: float = 1.0
    knock: float = 2.0
    stop: int = 3
    shake: float = 0.12
    lunge: float = 0.0
    lunge_frames: int = 0
    move_mult: float = 0.25
    apply: tuple = ()
    proj: dict = field(default_factory=dict)
    sfx: str = "cinder_slash"
    fx: str = "slash"
    hits: int = 1
    interval: int = 4
    armor: bool = False
    tags: tuple = ()

    @classmethod
    def from_dict(cls, d: dict) -> "MoveDef":
        kw = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        kw["apply"] = tuple((a["status"], int(a.get("stacks", 1)), float(a.get("chance", 1.0)))
                            for a in d.get("apply", ()))
        kw["tags"] = tuple(d.get("tags", ()))
        kw["proj"] = dict(d.get("proj", {}))
        if kw.get("cancel", 0) == 0:
            kw["cancel"] = max(2, int(kw.get("recover", 10)) // 2)
        return cls(**kw)

    @property
    def total(self) -> int:
        return self.windup + self.active + self.recover


@dataclass
class HeavyTier:
    hold: int
    move: MoveDef


@dataclass
class WeaponDef:
    id: str
    name: str
    family: str
    desc: str
    damage: float
    color: tuple
    light: list[MoveDef]
    heavy: list[HeavyTier]
    charge_speed: float = 0.5
    charge_armor: bool = False
    dash_attack: MoveDef | None = None
    riposte: MoveDef | None = None
    dodge: dict = field(default_factory=lambda: {"kind": "roll", "dist": 56.0, "frames": 13, "iframes": 12, "recover": 7})
    parry: dict = field(default_factory=lambda: {"window": 8, "recover": 18, "riposte_frames": 24, "reflect": 2.0,
                                                 "shockwave": 0.0})
    evolutions: list[dict] = field(default_factory=list)
    unlock_cost: int = 0
    tier: int = 1
    evolved: bool = False

    @property
    def locked_by_default(self) -> bool:
        return self.unlock_cost > 0


@dataclass
class EnemyDef:
    id: str
    name: str
    ai: str
    hp: float
    speed: float = 1.0
    radius: float = 6.0
    damage: float = 8.0
    poise: float = 20.0
    cost: float = 1.0
    min_floor: int = 1
    weight: float = 10.0
    role: str = "melee"
    vision: dict = field(default_factory=lambda: {"range": 150.0, "fov": 140.0, "peripheral": 40.0})
    reaction: int = 14
    retreat: float = 0.0
    params: dict = field(default_factory=dict)
    elite: dict | None = None
    art: dict = field(default_factory=dict)
    desc: str = ""


@dataclass
class BoonDef:
    id: str
    name: str
    desc: str
    cost: str = ""
    rarity: str = "common"
    tags: tuple = ()
    stats: dict = field(default_factory=dict)
    triggers: tuple = ()
    max_stacks: int = 1
    weight: float = 10.0
    families: tuple = ()
    needs_boons: tuple = ()
    unlock_cost: int = 0


@dataclass
class ModDef:
    id: str
    name: str
    desc: str
    heat: int
    effects: dict
    unlock_cost: int = 0


class Library:
    """Typed, validated snapshot of the cinder content kinds."""

    def __init__(self, db) -> None:
        self.weapons: dict[str, WeaponDef] = {}
        self.enemies: dict[str, EnemyDef] = {}
        self.boons: dict[str, BoonDef] = {}
        self.mods: dict[str, ModDef] = {}
        self.problems: list[str] = []
        self._load(db)

    def warn(self, msg: str) -> None:
        self.problems.append(msg)
        LOG.warning("cinder content: %s", msg)

    def _load(self, db) -> None:
        for d in db.all(K_WEAPON):
            try:
                w = self._weapon(d)
                self.weapons[w.id] = w
            except Exception as exc:        # noqa: BLE001 - a bad entry must not kill the game
                self.warn(f"weapon {d.get('id')}: skipped ({exc})")
        for w in list(self.weapons.values()):
            ok = []
            for e in w.evolutions:
                if e["to"] in self.weapons:
                    ok.append(e)
                else:
                    self.warn(f"weapon {w.id}: evolution target {e['to']} missing, ignored")
            w.evolutions = ok
        for d in db.all(K_BOON):
            try:
                b = self._boon(d)
                self.boons[b.id] = b
            except Exception as exc:        # noqa: BLE001
                self.warn(f"boon {d.get('id')}: skipped ({exc})")
        for d in db.all(K_ENEMY):
            try:
                e = self._enemy(d)
                self.enemies[e.id] = e
            except Exception as exc:        # noqa: BLE001
                self.warn(f"enemy {d.get('id')}: skipped ({exc})")
        for d in db.all(K_MOD):
            try:
                m = self._mod(d)
                self.mods[m.id] = m
            except Exception as exc:        # noqa: BLE001
                self.warn(f"modifier {d.get('id')}: skipped ({exc})")

    # -- builders ---------------------------------------------------------------------------
    def _weapon(self, d: dict) -> WeaponDef:
        light = [MoveDef.from_dict(m) for m in d["light"]]
        if not light:
            raise ValueError("needs at least one light move")
        heavy = sorted((HeavyTier(int(t["hold"]), MoveDef.from_dict(t["move"])) for t in d["heavy"]),
                       key=lambda t: t.hold)
        if not heavy or heavy[0].hold != 0:
            raise ValueError("heavy needs a tier with hold 0")
        w = WeaponDef(
            id=d["id"], name=d["name"], family=d["family"], desc=d.get("desc", ""), damage=float(d["damage"]),
            color=tuple(d.get("color", (255, 180, 90))), light=light, heavy=heavy,
            charge_speed=float(d.get("charge_speed", 0.5)), charge_armor=bool(d.get("charge_armor", False)),
            dash_attack=MoveDef.from_dict(d["dash_attack"]) if "dash_attack" in d else None,
            riposte=MoveDef.from_dict(d["riposte"]) if "riposte" in d else None,
            evolutions=list(d.get("evolutions", [])), unlock_cost=int(d.get("unlock", {}).get("cost", 0)),
            tier=int(d.get("tier", 1)), evolved=bool(d.get("evolved", False)))
        if "dodge" in d:
            w.dodge = {**w.dodge, **d["dodge"]}
        if "parry" in d:
            w.parry = {**w.parry, **d["parry"]}
        return w

    def _boon(self, d: dict) -> BoonDef:
        stats = {}
        for k, v in d.get("stats", {}).items():
            if k not in STAT_KEYS:
                raise ValueError(f"unknown stat {k!r}")
            stats[k] = float(v)
        triggers = tuple(d.get("triggers", ()))
        if not stats and not triggers:
            raise ValueError("boon has neither stats nor triggers")
        req = d.get("requires", {})
        return BoonDef(
            id=d["id"], name=d["name"], desc=d["desc"], cost=d.get("cost", ""), rarity=d.get("rarity", "common"),
            tags=tuple(d.get("tags", ())), stats=stats, triggers=triggers, max_stacks=int(d.get("max_stacks", 1)),
            weight=float(d.get("weight", 10)), families=tuple(req.get("family", ())),
            needs_boons=tuple(req.get("boons", ())), unlock_cost=int(d.get("unlock", {}).get("cost", 0)))

    def _enemy(self, d: dict) -> EnemyDef:
        e = EnemyDef(id=d["id"], name=d["name"], ai=d["ai"], hp=float(d["hp"]))
        for k in ("speed", "radius", "damage", "poise", "cost", "weight", "retreat"):
            if k in d:
                setattr(e, k, float(d[k]))
        for k in ("min_floor", "reaction"):
            if k in d:
                setattr(e, k, int(d[k]))
        for k in ("role", "desc"):
            if k in d:
                setattr(e, k, d[k])
        if "vision" in d:
            e.vision = {**e.vision, **d["vision"]}
        e.params = dict(d.get("params", {}))
        e.elite = dict(d["elite"]) if "elite" in d else None
        e.art = dict(d.get("art", {}))
        return e

    def _mod(self, d: dict) -> ModDef:
        eff = {}
        for k, v in d["effects"].items():
            if k not in MOD_KEYS:
                raise ValueError(f"unknown modifier effect {k!r}")
            eff[k] = float(v)
        return ModDef(d["id"], d["name"], d["desc"], int(d["heat"]), eff, int(d.get("unlock", {}).get("cost", 0)))

    # -- queries ----------------------------------------------------------------------------
    def starter_weapons(self) -> list[WeaponDef]:
        return [w for w in self.weapons.values() if not w.evolved and w.tier == 1]

    def families(self) -> list[str]:
        out: list[str] = []
        for w in self.starter_weapons():
            if w.family not in out:
                out.append(w.family)
        return out

    def unlockables(self) -> list[tuple[str, str, str, int]]:
        """(kind, id, name, cost) for everything purchasable at the Ledger."""
        out: list[tuple[str, str, str, int]] = []
        for w in self.starter_weapons():
            if w.unlock_cost:
                out.append(("weapon", w.id, w.name, w.unlock_cost))
        for b in self.boons.values():
            if b.unlock_cost:
                out.append(("boon", b.id, b.name, b.unlock_cost))
        for m in self.mods.values():
            if m.unlock_cost:
                out.append(("mod", m.id, m.name, m.unlock_cost))
        return sorted(out, key=lambda t: (t[3], t[1]))
