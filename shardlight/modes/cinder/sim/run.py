"""Run state for one climb of the Spire: weapon, boons, counters, health and the meta ledger hooks."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..defs import Library, ModDef, WeaponDef
from . import adaptive
from .perks import Modifiers, Perks

BASE_MAX_HP = 100.0
MAX_WEAPON_LEVEL = 3


@dataclass(frozen=True)
class Difficulty:
    name: str
    tokens: int               # simultaneous melee attackers
    parry_bonus: int          # extra parry window frames
    enemy_damage: float
    enemy_hp: float
    reaction_add: int         # frames added to enemy reaction times
    heal: float

    @staticmethod
    def preset(name: str) -> "Difficulty":
        return {"story": Difficulty("story", 2, 3, 0.7, 0.85, 6, 1.3),
                "standard": Difficulty("standard", 3, 0, 1.0, 1.0, 0, 1.0),
                "hard": Difficulty("hard", 4, -1, 1.2, 1.1, -2, 0.85)}.get(name, Difficulty("standard", 3, 0, 1, 1, 0, 1))


class Run:
    """Everything that persists from room to room within a single climb."""

    def __init__(self, lib: Library, seed: int, weapon_id: str, mods: list[ModDef], difficulty: Difficulty,
                 adapt_strength: float = 1.0) -> None:
        self.lib = lib
        self.seed = seed
        self.weapon: WeaponDef = lib.weapons[weapon_id]
        self.start_weapon = weapon_id
        self.perks = Perks(lib.boons)
        self.mods = Modifiers(mods)
        self.difficulty = difficulty
        self.adapt = adaptive.AdaptView(adaptive.build(adapt_strength))
        self.floor = 1
        self.room_no = 0
        self.slag = 0
        self.soot = 0                        # meta currency earned this run
        self.flare = 0.0
        self.revive_used = False
        self.weapon_level = 0
        self.kill_streak = 0
        self.streak_t = 0
        self.counters: dict[str, int] = {}
        self.hp = self.max_hp()
        self.time = 0                        # frames of room time
        self.kills = 0
        self.evolved_from: str | None = None
        self.log: list[str] = []
        self.boss_kills: list[str] = []
        self.secrets = 0
        self.rooms_cleared = 0
        self.damage_taken = 0.0

    # -- stats ---------------------------------------------------------------------------------------
    def max_hp(self) -> float:
        p = self.perks
        return max(20.0, (BASE_MAX_HP * self.mods["player_hp"] + p.get("max_hp_add")) * p.get("max_hp_mul"))

    def weapon_level_mult(self) -> float:
        return 1.0 + 0.1 * self.weapon_level

    def kill_streak_mult(self) -> float:
        return 1.0 + min(10, self.kill_streak) * self.perks.get("kill_streak_dmg")

    def heal_amount(self, base: float) -> float:
        return base * self.perks.get("heal_mul") * self.mods["heal_mul"] * self.difficulty.heal

    # -- bookkeeping hooks called by the player / room -------------------------------------------------
    def note_attack(self, weapon: WeaponDef) -> None:
        self.add_counter("attacks")

    def on_attack(self, move, weapon: WeaponDef) -> None:
        heavy = "heavy" in move.tags
        self.adapt.model.record("atk_heavy" if heavy else "atk_light", self.time / 60)
        self.adapt.model.record("atk_ranged" if move.shape == "proj" else "atk_melee", self.time / 60)

    def on_charge_release(self, tier: int, tiers: int) -> None:
        self.add_counter("charges")
        if tier == tiers - 1:
            self.add_counter("full_charges")

    def add_counter(self, name: str, n: int = 1) -> int:
        self.counters[name] = self.counters.get(name, 0) + n
        return self.counters[name]

    def register_kill(self) -> None:
        self.kills += 1
        self.kill_streak += 1
        self.streak_t = 150

    def tick(self) -> None:
        self.time += 1
        self.perks.tick()
        if self.streak_t > 0:
            self.streak_t -= 1
            if self.streak_t == 0:
                self.kill_streak = 0

    # -- weapon evolution ----------------------------------------------------------------------------
    def evolution_ready(self) -> dict | None:
        for ev in self.weapon.evolutions:
            ok = True
            for cond in ev["when"]:
                if "counter" in cond and self.counters.get(cond["counter"], 0) < int(cond.get("count", 1)):
                    ok = False
                if "boon" in cond and self.perks.stacks(cond["boon"]) <= 0:
                    ok = False
            if ok and ev["to"] in self.lib.weapons:
                return ev
        return None

    def evolve(self, ev: dict) -> WeaponDef:
        self.evolved_from = self.weapon.id
        self.weapon = self.lib.weapons[ev["to"]]
        self.log.append(f"evolved into {self.weapon.name}")
        return self.weapon

    # -- boon rewards --------------------------------------------------------------------------------
    def boon_pool(self, unlocked: set[str]) -> list[str]:
        out = []
        for b in self.lib.boons.values():
            if b.unlock_cost and b.id not in unlocked:
                continue
            if self.perks.stacks(b.id) >= b.max_stacks:
                continue
            if b.families and self.weapon.family not in b.families:
                continue
            if any(self.perks.stacks(n) <= 0 for n in b.needs_boons):
                continue
            out.append(b.id)
        return out

    def offer(self, rng, unlocked: set[str], n: int = 3) -> list[str]:
        pool = self.boon_pool(unlocked)
        picks: list[str] = []
        while pool and len(picks) < n:
            weights = [self.lib.boons[b].weight * (2.0 if self.lib.boons[b].needs_boons else 1.0) for b in pool]
            b = rng.weighted(pool, weights)
            picks.append(b)
            pool.remove(b)
        return picks

    def snapshot(self) -> dict:
        """JSON-able state (for resuming a run)."""
        return {"seed": self.seed, "weapon": self.weapon.id, "start_weapon": self.start_weapon, "floor": self.floor,
                "room_no": self.room_no, "slag": self.slag, "hp": self.hp, "boons": dict(self.perks.owned),
                "counters": dict(self.counters), "level": self.weapon_level, "mods": [m.id for m in self.mods.active],
                "revive": self.revive_used, "kills": self.kills, "soot": self.soot}
