"""Plain data objects the room simulates: entities, hit volumes, projectiles, hazards, pickups, props."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from .status import StatusSet

PLAYER_TEAM = 0
ENEMY_TEAM = 1


class Entity:
    """A circle that lives in the room: the player, an enemy or a boss."""

    kind = "entity"

    def __init__(self, x: float, y: float, r: float, hp: float, team: int):
        self.id = 0
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.kx = 0.0                 # knockback velocity (decays)
        self.ky = 0.0
        self.r = r
        self.hp = hp
        self.max_hp = hp
        self.team = team
        self.facing = 0.0
        self.poise = 0.0
        self.max_poise = 0.0
        self.poise_wait = 0           # frames before poise starts regenerating
        self.stun = 0                 # frames of stagger (cannot act)
        self.iframes = 0
        self.flash = 0                # hit-flash frames
        self.alive = True
        self.dead_t = 0
        self.status = StatusSet()
        self.age = 0
        self.last_hit_by = ""

    @property
    def pos(self) -> tuple[float, float]:
        return self.x, self.y

    def add_knock(self, ang: float, force: float) -> None:
        self.kx += math.cos(ang) * force
        self.ky += math.sin(ang) * force


@dataclass
class Hitbox:
    """A damaging volume.  While ``t < windup`` it is only a *telegraph* (drawn, harmless); afterwards
    it is active for ``active`` frames.  Using one object for both guarantees the telegraph matches the hit."""
    owner: Entity | None
    team: int
    shape: str                      # arc | thrust | circle | ring
    x: float
    y: float
    facing: float
    reach: float = 30.0
    arc: float = 120.0
    width: float = 14.0
    inner: float = 0.0
    damage: float = 5.0
    poise: float = 10.0
    knock: float = 2.0
    stop: int = 3
    shake: float = 0.15
    windup: int = 0
    active: int = 4
    apply: tuple = ()
    parryable: bool = True
    unblockable: bool = False       # ignores shields
    follow: bool = False            # re-anchor to the owner every frame
    follow_offset: float = 0.0
    track: int = 0                  # windup frames during which facing keeps tracking ``track_fn``
    track_fn: Callable[[], float] | None = None
    ring_from: float = 0.0          # ring: starts at this radius and grows to ``reach`` over the active time
    friendly: bool = False          # also harms the owner's team (explosions)
    multi: int = 0                  # re-hit interval for lingering volumes (0 = hit once per target)
    style: str = "normal"           # telegraph colour: normal | parry | heavy
    tags: tuple = ()
    lob_from: tuple | None = None   # for thrown explosives: draw an arcing missile during the windup
    on_active: Callable[["Hitbox"], None] | None = None
    t: int = 0
    done: bool = False
    hit: dict = field(default_factory=dict)       # entity id -> frame last hit
    id: int = 0
    move_name: str = ""
    crit: bool = False
    source: str = ""                # label for stats / death cause
    reflected: bool = False

    @property
    def is_active(self) -> bool:
        return self.windup <= self.t < self.windup + self.active

    @property
    def telegraphing(self) -> bool:
        return self.t < self.windup

    @property
    def cur_reach(self) -> float:
        if self.shape != "ring":
            return self.reach
        k = min(1.0, max(0.0, (self.t - self.windup + 1) / max(1, self.active)))
        return self.ring_from + (self.reach - self.ring_from) * k


@dataclass
class Projectile:
    x: float
    y: float
    vx: float
    vy: float
    r: float
    damage: float
    team: int
    owner: Entity | None = None
    life: int = 120
    kind: str = "bolt"              # bolt | arrow | shard | ember | orb | needle | note | arc
    pierce: int = 0
    ricochet: int = 0
    parryable: bool = True
    apply: tuple = ()
    poise: float = 6.0
    knock: float = 1.5
    homing: float = 0.0
    chain: int = 0
    hit_ids: set = field(default_factory=set)
    reflected: bool = False
    color: tuple = (255, 190, 90)
    alive: bool = True
    id: int = 0
    source: str = ""
    trail: list = field(default_factory=list)
    bounces: int = 0
    stop: int = 2
    charged: bool = False
    gravity_to: tuple | None = None

    @property
    def angle(self) -> float:
        return math.atan2(self.vy, self.vx)


@dataclass
class Hazard:
    """A lingering ground area (ember puddle, flame trail, vent)."""
    x: float
    y: float
    r: float
    life: int
    dps: float = 4.0                # damage per second to those standing in it
    team: int = PLAYER_TEAM         # team that is *harmed*? no: the team that CREATED it (harms the other)
    kind: str = "ember"             # ember | trail | vent | fire
    warmup: int = 0                 # telegraph frames before it hurts
    apply: tuple = ()
    harms_all: bool = False
    t: int = 0
    id: int = 0
    tick_t: int = 0
    period: int = 0                 # vents: full cycle length (0 = not cyclic)
    on_frames: int = 30
    warn: int = 40
    phase: int = 0

    @property
    def armed(self) -> bool:
        if self.period:
            return (self.t + self.phase) % self.period >= self.period - self.on_frames
        return self.t >= self.warmup

    @property
    def warning(self) -> bool:
        if self.period:
            c = (self.t + self.phase) % self.period
            return self.period - self.on_frames - self.warn <= c < self.period - self.on_frames
        return self.t < self.warmup


@dataclass
class Pickup:
    kind: str                       # slag | heart | soot | flare
    x: float
    y: float
    value: int = 1
    vx: float = 0.0
    vy: float = 0.0
    age: int = 0
    alive: bool = True
    magnet: bool = False


@dataclass
class Prop:
    """Interactable or decorative object."""
    kind: str                       # chest | altar | anvil | campfire | stair | dummy | rack | stall | crack | brazier | pillar | ledger | choir_door
    x: float
    y: float
    r: float = 8.0
    data: dict = field(default_factory=dict)
    used: bool = False
    hp: int = 0
    age: int = 0
    prompt: str = ""

    @property
    def interactable(self) -> bool:
        return self.kind in ("chest", "altar", "anvil", "campfire", "stair", "rack", "stall", "ledger", "setup",
                             "choir_door", "well") and not self.used


@dataclass
class Door:
    side: str                       # n | e | s | w
    cells: list                     # tile cells forming the opening
    target: int                     # room id on the other side (-1 = none)
    locked: bool = False
    hidden: bool = False            # secret door, a cracked wall until struck
    kind: str = "normal"            # normal | stair | boss | choir | secret
    hits: int = 0


@dataclass
class Ev:
    """Simulation event consumed by the scene for audio/visual feedback."""
    kind: str
    x: float = 0.0
    y: float = 0.0
    data: dict = field(default_factory=dict)
