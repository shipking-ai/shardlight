"""Status effects and their interactions (pure logic, tick based).

Statuses
    burn   damage over time, up to 3 stacks
    ash    slows and makes the victim brittle (takes extra direct damage)
    shock  direct hits on a shocked victim arc to nearby enemies (handled by the room)
    rend   bleed-like, stacks to 5; heavy "rend burst" hits consume it for extra damage

Interactions (either order of application)
    ash + burn   -> Flashover: both consumed, radial explosion
    ash + shock  -> Chain nova: both consumed, radial lightning nova that shocks everything it touches
    rend + burn  -> Sear: rend consumed for instant damage, burn still applies
"""
from __future__ import annotations

from dataclasses import dataclass, field

FPS = 60

FLASHOVER_BASE = 16.0
FLASHOVER_PER_BURN = 5.0
FLASHOVER_RADIUS = 46.0
NOVA_DAMAGE = 14.0
NOVA_RADIUS = 66.0
SEAR_PER_REND = 3.0
LOCK_FRAMES = 18         # per-victim cooldown between interaction triggers (stops infinite loops)


@dataclass(frozen=True)
class StatusDef:
    name: str
    max_stacks: int
    duration: int           # frames
    tick: int = 0           # frames between damage ticks (0 = none)
    dmg: float = 0.0        # damage per stack per tick
    slow: float = 0.0       # movement slow fraction
    brittle: float = 0.0    # extra damage taken fraction


STATUS_DEFS: dict[str, StatusDef] = {
    "burn": StatusDef("burn", 3, 180, tick=30, dmg=2.0),
    "ash": StatusDef("ash", 1, 270, slow=0.3, brittle=0.25),
    "shock": StatusDef("shock", 1, 150),
    "rend": StatusDef("rend", 5, 300, tick=45, dmg=1.5),
}

STATUS_COLORS = {"burn": (255, 134, 52), "ash": (176, 168, 186), "shock": (255, 236, 120), "rend": (214, 62, 82)}


@dataclass
class StatusEvent:
    kind: str                 # "flashover" | "nova" | "sear" | "dot"
    amount: float = 0.0
    radius: float = 0.0
    status: str = ""


@dataclass
class _Active:
    stacks: int
    time: int
    tick_t: int = 0
    power: float = 1.0


class StatusSet:
    """The statuses on one entity."""

    def __init__(self) -> None:
        self.active: dict[str, _Active] = {}
        self.lock = 0
        self.flags_this_tick: list[str] = []

    # queries ------------------------------------------------------------------------------
    def has(self, name: str) -> bool:
        return name in self.active

    def stacks(self, name: str) -> int:
        a = self.active.get(name)
        return a.stacks if a else 0

    def time_left(self, name: str) -> int:
        a = self.active.get(name)
        return a.time if a else 0

    def names(self) -> list[str]:
        return list(self.active)

    def slow_mult(self) -> float:
        return 1.0 - max((STATUS_DEFS[n].slow for n in self.active), default=0.0)

    def brittle_mult(self) -> float:
        return 1.0 + sum(STATUS_DEFS[n].brittle for n in self.active)

    # mutation -----------------------------------------------------------------------------
    def clear(self, name: str | None = None) -> None:
        if name is None:
            self.active.clear()
        else:
            self.active.pop(name, None)

    def apply(self, name: str, stacks: int = 1, duration: int | None = None, power: float = 1.0) -> list[StatusEvent]:
        """Apply ``stacks`` of a status and return interaction events the room must realise."""
        d = STATUS_DEFS.get(name)
        if d is None:
            return []
        events: list[StatusEvent] = []
        a = self.active
        if self.lock <= 0:
            if (name == "burn" and "ash" in a) or (name == "ash" and "burn" in a):
                burn = (a["burn"].stacks if "burn" in a else 0) + (stacks if name == "burn" else 0)
                a.pop("ash", None)
                a.pop("burn", None)
                self.lock = LOCK_FRAMES
                return [StatusEvent("flashover", (FLASHOVER_BASE + FLASHOVER_PER_BURN * burn) * power,
                                    FLASHOVER_RADIUS, "burn")]
            if (name == "shock" and "ash" in a) or (name == "ash" and "shock" in a):
                a.pop("ash", None)
                a.pop("shock", None)
                self.lock = LOCK_FRAMES
                return [StatusEvent("nova", NOVA_DAMAGE * power, NOVA_RADIUS, "shock")]
            if name == "burn" and "rend" in a:
                n = a.pop("rend").stacks
                self.lock = LOCK_FRAMES // 2
                events.append(StatusEvent("sear", SEAR_PER_REND * n * power, 0.0, "rend"))
        cur = a.get(name)
        dur = duration if duration is not None else d.duration
        if cur is None:
            a[name] = _Active(min(stacks, d.max_stacks), dur, d.tick, power)
        else:
            cur.stacks = min(d.max_stacks, cur.stacks + stacks)
            cur.time = max(cur.time, dur)
            cur.power = max(cur.power, power)
        return events

    def tick(self) -> list[StatusEvent]:
        """Advance one frame; returns DoT damage events."""
        if self.lock > 0:
            self.lock -= 1
        out: list[StatusEvent] = []
        expired = []
        for n, a in self.active.items():
            a.time -= 1
            d = STATUS_DEFS[n]
            if d.tick:
                a.tick_t -= 1
                if a.tick_t <= 0:
                    a.tick_t = d.tick
                    out.append(StatusEvent("dot", d.dmg * a.stacks * a.power, 0.0, n))
            if a.time <= 0:
                expired.append(n)
        for n in expired:
            del self.active[n]
        return out

    def to_list(self) -> list[tuple[str, int, int]]:
        return [(n, a.stacks, a.time) for n, a in sorted(self.active.items())]
