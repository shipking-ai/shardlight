"""Boons compile into aggregated stat modifiers plus event triggers (executed by the room)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..defs import BoonDef, ModDef


@dataclass
class Trigger:
    boon: str
    index: int
    on: str
    do: str
    chance: float
    cooldown: int
    args: dict
    needs_status: str
    stacks: int


class Perks:
    """Owned boons -> ``get(stat)`` and ``triggers(event)``.

    Stat conventions: keys ending in ``_mul`` multiply (once per stack); everything else is additive.
    Temporary buffs (``add_buff``) layer on top and expire.
    """

    def __init__(self, boons: dict[str, BoonDef] | None = None, owned: dict[str, int] | None = None) -> None:
        self.defs = boons or {}
        self.owned: dict[str, int] = {}
        self._stats: dict[str, float] = {}
        self._triggers: dict[str, list[Trigger]] = {}
        self.buffs: list[list] = []            # [stat, value, frames_left]
        for bid, n in (owned or {}).items():
            self.owned[bid] = n
        self.rebuild()

    # -- ownership --------------------------------------------------------------------------
    def stacks(self, bid: str) -> int:
        return self.owned.get(bid, 0)

    def add(self, bid: str) -> bool:
        d = self.defs.get(bid)
        if d is None or self.owned.get(bid, 0) >= d.max_stacks:
            return False
        self.owned[bid] = self.owned.get(bid, 0) + 1
        self.rebuild()
        return True

    def rebuild(self) -> None:
        stats: dict[str, float] = {}
        trig: dict[str, list[Trigger]] = {}
        for bid, n in self.owned.items():
            d = self.defs.get(bid)
            if d is None:
                continue
            for k, v in d.stats.items():
                if k.endswith("_mul"):
                    stats[k] = stats.get(k, 1.0) * (v ** n)
                else:
                    stats[k] = stats.get(k, 0.0) + v * n
            for i, t in enumerate(d.triggers):
                trig.setdefault(t["on"], []).append(Trigger(
                    bid, i, t["on"], t["do"], float(t.get("chance", 1.0)), int(t.get("cooldown", 0)),
                    dict(t.get("args", {})), t.get("needs_status", ""), n))
        self._stats = stats
        self._triggers = trig

    # -- queries ----------------------------------------------------------------------------
    def get(self, key: str) -> float:
        base = self._stats.get(key, 1.0 if key.endswith("_mul") else 0.0)
        for stat, val, _ in self.buffs:
            if stat == key:
                base = base * val if key.endswith("_mul") else base + val
        return base

    def triggers(self, event: str) -> list[Trigger]:
        return self._triggers.get(event, [])

    def add_buff(self, stat: str, value: float, frames: int) -> None:
        for b in self.buffs:
            if b[0] == stat and b[1] == value:
                b[2] = max(b[2], frames)
                return
        self.buffs.append([stat, value, frames])

    def tick(self) -> None:
        if self.buffs:
            for b in self.buffs:
                b[2] -= 1
            self.buffs = [b for b in self.buffs if b[2] > 0]

    def tags(self) -> set[str]:
        out: set[str] = set()
        for bid in self.owned:
            d = self.defs.get(bid)
            if d:
                out.update(d.tags)
        return out


class Modifiers:
    """Aggregated run modifiers ("Heat").  Missing keys are neutral."""

    NEUTRAL = {"enemy_hp": 1.0, "enemy_damage": 1.0, "enemy_speed": 1.0, "elite_chance": 0.0, "extra_budget": 0.0,
               "reaction_cut": 0.0, "player_hp": 1.0, "heal_mul": 1.0, "slag_mul": 1.0, "parry_window": 0.0,
               "fire_floor": 0.0, "death_burst": 0.0, "dim_light": 0.0, "fewer_rewards": 0.0, "boss_hp": 1.0}

    def __init__(self, active: Iterable[ModDef] = ()) -> None:
        self.active = list(active)
        self.v = dict(self.NEUTRAL)
        for m in self.active:
            for k, val in m.effects.items():
                if k in ("enemy_hp", "enemy_damage", "enemy_speed", "player_hp", "heal_mul", "slag_mul", "boss_hp"):
                    self.v[k] *= val
                else:
                    self.v[k] += val

    def __getitem__(self, k: str) -> float:
        return self.v[k]

    @property
    def heat(self) -> int:
        return sum(m.heat for m in self.active)
