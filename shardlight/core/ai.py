"""Reusable AI building blocks: behaviour trees, utility selection, perception with memory, hearing,
and a bounded player-adaptation controller.  No pygame dependency; everything is deterministic given
the RNG passed in, which keeps AI behaviour unit-testable.

Fairness rules baked in: agents only know what perception gave them (``Memory``), reaction delays are
explicit, and adaptation changes are *bounded* and *cooled down* - never hidden damage multipliers.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence


# ------------------------------------------------------------------------------- behaviour tree
class Status(Enum):
    SUCCESS = 1
    FAILURE = 2
    RUNNING = 3


class Node:
    def tick(self, bb: dict) -> Status:   # bb = blackboard
        raise NotImplementedError


class Sequence(Node):
    """Runs children in order; remembers the running child between ticks."""

    def __init__(self, *children: Node):
        self.children = children
        self._i = 0

    def tick(self, bb: dict) -> Status:
        while self._i < len(self.children):
            s = self.children[self._i].tick(bb)
            if s is Status.RUNNING:
                return s
            if s is Status.FAILURE:
                self._i = 0
                return s
            self._i += 1
        self._i = 0
        return Status.SUCCESS


class Selector(Node):
    def __init__(self, *children: Node):
        self.children = children

    def tick(self, bb: dict) -> Status:
        for c in self.children:
            s = c.tick(bb)
            if s is not Status.FAILURE:
                return s
        return Status.FAILURE


class Condition(Node):
    def __init__(self, fn: Callable[[dict], bool]):
        self.fn = fn

    def tick(self, bb: dict) -> Status:
        return Status.SUCCESS if self.fn(bb) else Status.FAILURE


class Action(Node):
    def __init__(self, fn: Callable[[dict], Status]):
        self.fn = fn

    def tick(self, bb: dict) -> Status:
        return self.fn(bb)


class Inverter(Node):
    def __init__(self, child: Node):
        self.child = child

    def tick(self, bb: dict) -> Status:
        s = self.child.tick(bb)
        return {Status.SUCCESS: Status.FAILURE, Status.FAILURE: Status.SUCCESS}.get(s, s)


class Cooldown(Node):
    """Fails while cooling down after the child succeeded. Time is read from bb['time']."""

    def __init__(self, child: Node, seconds: float):
        self.child = child
        self.seconds = seconds
        self._ready_at = -1e9

    def tick(self, bb: dict) -> Status:
        if bb.get("time", 0.0) < self._ready_at:
            return Status.FAILURE
        s = self.child.tick(bb)
        if s is Status.SUCCESS:
            self._ready_at = bb.get("time", 0.0) + self.seconds
        return s


# ------------------------------------------------------------------------------------ utility AI
@dataclass
class UtilityOption:
    name: str
    score: Callable[[dict], float]
    act: Callable[[dict], Any] | None = None
    commit: float = 0.0          # seconds the option stays selected once chosen (anti-flicker)


class UtilitySelector:
    """Pick the highest scoring option with commitment time and hysteresis bonus for the current one."""

    def __init__(self, options: Sequence[UtilityOption], hysteresis: float = 0.1):
        self.options = list(options)
        self.hysteresis = hysteresis
        self.current: UtilityOption | None = None
        self._commit_until = 0.0
        self.last_scores: dict[str, float] = {}

    def choose(self, bb: dict) -> UtilityOption:
        now = bb.get("time", 0.0)
        if self.current and now < self._commit_until:
            return self.current
        best, best_s = None, -1e9
        self.last_scores = {}
        for o in self.options:
            s = o.score(bb)
            self.last_scores[o.name] = s
            if o is self.current:
                s += self.hysteresis
            if s > best_s:
                best, best_s = o, s
        if best is not self.current:
            self._commit_until = now + best.commit
        self.current = best
        return best

    def run(self, bb: dict) -> UtilityOption:
        o = self.choose(bb)
        if o.act:
            o.act(bb)
        return o


# ------------------------------------------------------------------------ perception and memory
@dataclass
class Evidence:
    kind: str                    # "seen" | "heard" | "found" (a body, an open door, a moved object...)
    pos: tuple[float, float]
    time: float
    confidence: float
    source: str = ""


class Memory:
    """What an agent believes about a target, decaying with time.  Agents act on this, not on truth."""

    def __init__(self, decay_per_s: float = 0.15, forget_below: float = 0.05):
        self.decay = decay_per_s
        self.forget_below = forget_below
        self.best: Evidence | None = None
        self.history: deque[Evidence] = deque(maxlen=12)

    def observe(self, ev: Evidence) -> None:
        self.history.append(ev)
        if self.best is None or ev.confidence >= self.best.confidence * 0.8 or ev.time - self.best.time > 1.0:
            self.best = ev

    def update(self, dt: float) -> None:
        if self.best:
            self.best.confidence -= self.decay * dt
            if self.best.confidence < self.forget_below:
                self.best = None

    @property
    def confidence(self) -> float:
        return self.best.confidence if self.best else 0.0

    def last_known(self) -> tuple[float, float] | None:
        return self.best.pos if self.best else None


@dataclass
class VisionCone:
    range: float = 160.0
    fov_deg: float = 100.0
    peripheral_range: float = 40.0     # notice very close targets regardless of facing
    needs_light: bool = False

    def sees(self, pos, facing_deg: float, target, los: Callable[[Any, Any], bool] | None = None,
             visibility: float = 1.0) -> bool:
        dx, dy = target[0] - pos[0], target[1] - pos[1]
        d = math.hypot(dx, dy)
        eff = self.range * max(0.0, visibility)
        if d > eff:
            return False
        if d > self.peripheral_range * visibility:
            ang = math.degrees(math.atan2(dy, dx))
            diff = abs((ang - facing_deg + 180) % 360 - 180)
            if diff > self.fov_deg / 2:
                return False
        return los(pos, target) if los else True


@dataclass
class Noise:
    pos: tuple[float, float]
    loudness: float              # radius in world units at which it is still audible
    kind: str = "step"
    source: str = ""
    time: float = 0.0


class NoiseBus:
    """Sound propagation: listeners hear a noise if within ``loudness * hearing`` after occlusion."""

    def __init__(self, occlusion: Callable[[Any, Any], float] | None = None):
        self.listeners: list[tuple[Any, Callable[[Noise, float], None], Callable[[], tuple]]] = []
        self.occlusion = occlusion          # returns extra distance penalty (e.g. walls in between)
        self.recent: deque[Noise] = deque(maxlen=64)

    def listen(self, owner: Any, pos_fn: Callable[[], tuple], callback: Callable[[Noise, float], None],
               hearing: float = 1.0) -> None:
        self.listeners.append((owner, callback, pos_fn))
        owner._hearing = hearing

    def unlisten(self, owner: Any) -> None:
        self.listeners = [t for t in self.listeners if t[0] is not owner]

    def emit(self, noise: Noise) -> int:
        self.recent.append(noise)
        heard = 0
        for owner, cb, pos_fn in self.listeners:
            p = pos_fn()
            d = math.hypot(p[0] - noise.pos[0], p[1] - noise.pos[1])
            if self.occlusion:
                d += self.occlusion(noise.pos, p)
            reach = noise.loudness * getattr(owner, "_hearing", 1.0)
            if d <= reach:
                cb(noise, 1.0 - d / reach)      # intensity 0..1
                heard += 1
        return heard


# ------------------------------------------------------------------------------ adaptation model
class PlayerModel:
    """Exponentially-decayed frequencies of what the player does (e.g. 'dodge_left', 'melee')."""

    def __init__(self, half_life: float = 20.0):
        self.half_life = half_life
        self.weights: dict[str, float] = defaultdict(float)
        self.t = 0.0
        self.samples = 0

    def record(self, key: str, now: float, weight: float = 1.0) -> None:
        self._decay_to(now)
        self.weights[key] += weight
        self.samples += 1

    def _decay_to(self, now: float) -> None:
        dt = now - self.t
        if dt > 0:
            k = 0.5 ** (dt / self.half_life)
            for key in self.weights:
                self.weights[key] *= k
            self.t = now

    def share(self, key: str, group: Sequence[str], now: float) -> tuple[float, float]:
        """Return (probability of ``key`` within ``group``, total effective sample weight)."""
        self._decay_to(now)
        total = sum(self.weights.get(k, 0.0) for k in group)
        if total <= 0:
            return 0.0, 0.0
        return self.weights.get(key, 0.0) / total, total


@dataclass
class Adaptation:
    """A bounded counter-strategy: when the player over-uses ``key`` we raise ``strength`` of a counter."""
    name: str
    key: str
    group: tuple[str, ...]
    threshold: float = 0.6        # share needed
    min_weight: float = 4.0       # confidence: minimum effective samples
    max_bonus: float = 0.35       # hard bound on how far the counter can go
    active: bool = False
    level: float = 0.0


class AdaptiveController:
    """Turns observed player habits into small, explicit, cooled-down counter measures.

    ``strength`` (settings.difficulty.adaptive_ai) scales the effect; 0 disables adaptation.
    A counter can only change every ``cooldown`` seconds (no strategy flip-flopping), and
    ``level`` moves gradually toward its target (fairness: the player sees it coming).
    """

    def __init__(self, model: PlayerModel, adaptations: Sequence[Adaptation], strength: float = 1.0,
                 cooldown: float = 8.0):
        self.model = model
        self.adaptations = list(adaptations)
        self.strength = strength
        self.cooldown = cooldown
        self._last_change: dict[str, float] = defaultdict(lambda: -1e9)
        self.log: list[tuple[float, str, bool]] = []

    def update(self, now: float, dt: float) -> None:
        for a in self.adaptations:
            share, weight = self.model.share(a.key, a.group, now)
            want = self.strength > 0 and weight >= a.min_weight and share >= a.threshold
            if want != a.active and now - self._last_change[a.name] >= self.cooldown:
                a.active = want
                self._last_change[a.name] = now
                self.log.append((now, a.name, want))
            target = 0.0
            if a.active:
                over = (share - a.threshold) / max(1e-6, 1 - a.threshold)
                target = min(1.0, 0.4 + over) * a.max_bonus * min(self.strength, 1.5)
                target = min(target, a.max_bonus * 1.5)
            a.level += max(-0.15 * dt, min(0.15 * dt, target - a.level))   # slew-limited

    def level(self, name: str) -> float:
        for a in self.adaptations:
            if a.name == name:
                return a.level
        return 0.0
