"""Vehicle specifications: JSON dict -> immutable :class:`VehicleSpec`, with tradeoff upgrades applied.

Stat meanings (all in world pixels / seconds):

* ``power``        peak drive acceleration in the top gear (px/s^2)
* ``top_speed``    tarmac speed without boost (px/s); drag is calibrated so the car really settles here
* ``brake``        peak braking deceleration (px/s^2), limited by tyre grip
* ``grip``         lateral grip multiplier (1.0 = 440 px/s^2 on tarmac)
* ``steer``        steering lock at standstill (radians)
* ``agility``      how far past the grip limit the steering may be pushed (higher = sharper turn-in, more push)
* ``slide``        rear grip kept while the handbrake is held (lower = drifts more readily)
* ``mass``         relative mass for collisions
* ``boost_cap``    boost meter size; ``boost_power`` boost thrust multiplier
* ``drift_charge`` boost gained per drifted second; ``draft`` strength of the slipstream effect
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

UPGRADE_SLOTS = ("engine", "tires", "brakes", "aero", "boost")
MAX_LEVEL = 3
# stats an upgrade is allowed to modify (multiplicatively, per level)
UPGRADE_STATS = ("power", "top_speed", "brake", "grip", "steer", "agility", "slide", "mass",
                 "boost_cap", "boost_power", "drift_charge", "draft")

DEFAULT_COLOR = (239, 75, 51)


@dataclass(frozen=True)
class VehicleSpec:
    id: str
    name: str
    tagline: str = ""
    kind: str = "balanced"
    power: float = 95.0
    top_speed: float = 260.0
    brake: float = 460.0
    grip: float = 1.0
    steer: float = 0.50
    agility: float = 1.2
    slide: float = 0.30
    mass: float = 1.0
    boost_cap: float = 100.0
    boost_power: float = 1.0
    drift_charge: float = 1.0
    draft: float = 1.0
    wf: float = 0.50                      # front weight fraction
    length: float = 22.0
    width: float = 11.0
    body: dict = field(default_factory=dict)      # silhouette parameters, see art.py
    accent: tuple[int, int, int] = DEFAULT_COLOR
    price: int = 0
    special: str = ""                     # "" | "rewind"
    levels: dict = field(default_factory=dict)    # slot -> level currently applied

    @property
    def wheelbase(self) -> float:
        return self.length * 0.64

    def rating(self) -> dict[str, float]:
        """0..1 bars for the vehicle-select screen (relative to the stock field)."""
        return {
            "Speed": min(1.0, (self.top_speed - 220) / 90),
            "Accel": min(1.0, (self.power - 70) / 70),
            "Grip": min(1.0, (self.grip - 0.7) / 0.6),
            "Drift": min(1.0, (1.1 - self.slide - 0.0) / 0.9),
            "Boost": min(1.0, (self.boost_cap * self.boost_power - 70) / 110),
        }


_LIMITS = {"slide": (0.08, 0.9), "grip": (0.5, 1.8), "steer": (0.25, 0.8), "agility": (0.8, 1.8),
           "mass": (0.5, 2.5)}


def _clamped(stat: str, value: float) -> float:
    lo, hi = _LIMITS.get(stat, (0.0, 1e9))
    return max(lo, min(hi, value))


def spec_from_dict(d: dict[str, Any], levels: dict[str, int] | None = None) -> VehicleSpec:
    """Build a spec from a ``slipstream.vehicle`` entry, applying upgrade ``levels`` (slot -> 0..3)."""
    stats = {k: d[k] for k in ("power", "top_speed", "brake", "grip", "steer", "agility", "slide", "mass",
                               "boost_cap", "boost_power", "drift_charge", "draft") if k in d}
    levels = {s: max(0, min(MAX_LEVEL, int(v))) for s, v in (levels or {}).items() if s in UPGRADE_SLOTS}
    for slot, lvl in levels.items():
        up = d.get("upgrades", {}).get(slot)
        if not up or lvl <= 0:
            continue
        for stat, per_level in up.get("effects", {}).items():
            if stat in stats:
                stats[stat] = _clamped(stat, stats[stat] * (1.0 + per_level * lvl))
    accent = tuple(d.get("color", DEFAULT_COLOR))
    return VehicleSpec(
        id=d["id"], name=d.get("name", d["id"]), tagline=d.get("tagline", ""), kind=d.get("class", "balanced"),
        wf=float(d.get("front_weight", 0.5)), length=float(d.get("length", 22)), width=float(d.get("width", 11)),
        body=dict(d.get("body", {})), accent=accent, price=int(d.get("price", 0)),
        special=str(d.get("special", "")), levels=dict(levels), **stats)


def upgrade_cost(d: dict[str, Any], slot: str, level: int) -> int:
    """Cost of buying ``level`` (1-based) of ``slot``; 0 when the vehicle has no such upgrade."""
    up = d.get("upgrades", {}).get(slot)
    costs = up.get("cost", []) if up else []
    return int(costs[level - 1]) if 1 <= level <= len(costs) else 0


def with_stats(spec: VehicleSpec, **changes: float) -> VehicleSpec:
    return replace(spec, **changes)


# Fallbacks used only if the content database has lost every vehicle (e.g. a mod removed them all).
FALLBACK_VEHICLE: dict[str, Any] = {
    "id": "kestrel", "name": "Kestrel", "tagline": "Grippy all-rounder", "class": "grip",
    "power": 95, "top_speed": 260, "brake": 470, "grip": 1.08, "steer": 0.5, "agility": 1.2,
    "slide": 0.32, "mass": 1.0, "boost_cap": 100, "boost_power": 1.0, "drift_charge": 1.0, "draft": 1.0,
    "color": [239, 75, 51], "upgrades": {},
}
