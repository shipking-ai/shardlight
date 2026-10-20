"""Move and character data model: parsing from validated JSON into integer-only frame data.

A move is *data*: startup / active / recovery frames, per-frame hitboxes and hurtboxes (rectangles in
character space), hit properties, cancel windows, invulnerability and special properties.  Rectangles
in JSON are ``[forward_offset, bottom_height, width, height]`` in pixels; here they are sub-pixel ints.

Frame convention: ``startup`` is the number of the first active frame (startup 5 -> first hit on frame 5).
Active frames are ``startup .. startup+active-1``; recovery follows; ``total = startup+active+recovery-1``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .consts import (ATTACKS, BUTTON_NAMES, FRICTION, HEIGHT_MID, PUSHBLOCK_FRAMES, SUB, px_to_speed)

Rect = tuple[int, int, int, int]


def rect_px(r: list[int]) -> Rect:
    return (int(r[0]) * SUB, int(r[1]) * SUB, int(r[2]) * SUB, int(r[3]) * SUB)


@dataclass
class Hit:
    damage: int = 30
    hitstun: int = 16
    blockstun: int = 10
    hitstop: int = 8
    push_hit: int = 0            # initial sub-px/frame velocity pushed onto the victim (from px)
    push_block: int = 0
    launch: tuple[int, int] | None = None     # (forward vx, vy) sub-px/frame -> airborne hit
    knockdown: bool = False
    height: str = HEIGHT_MID
    meter_hit: int = 20
    meter_block: int = 8
    juggle: int = 1
    starter: int = 100           # proration percent applied to the rest of the combo when this starts it
    chip: int = 0                # percent of damage dealt on block
    spark: str = "light"         # light | med | heavy | slash
    unblockable: bool = False
    slow_zone: bool = False
    pull: int = 0                # attacker velocity pulled toward victim on hit (for grabs)


def build_hit(d: dict, base: Hit | None = None) -> Hit:
    h = Hit(**{k: getattr(base, k) for k in Hit.__dataclass_fields__}) if base else Hit()
    for k, v in d.items():
        if k == "push_hit":
            h.push_hit = px_to_speed(int(v))
        elif k == "push_block":
            h.push_block = px_to_speed(int(v))
        elif k == "launch":
            h.launch = (int(v[0]), int(v[1]))
        elif hasattr(h, k):
            setattr(h, k, v)
    return h


@dataclass
class Box:
    rect: Rect
    f0: int
    f1: int
    group: int = 0
    hit: Hit | None = None

    def active_on(self, frame: int) -> bool:
        return self.f0 <= frame <= self.f1


@dataclass
class Cancel:
    on: str                      # hit | block | contact | whiff | always
    into: tuple[str, ...]        # move keys or tags: special, super, normal, heavy, dash, jump
    f0: int = 1
    f1: int = 999


@dataclass
class Invuln:
    f0: int
    f1: int
    kind: str = "all"            # strike | throw | projectile | all


@dataclass
class Armor:
    f0: int
    f1: int
    hits: int = 1


@dataclass
class Counter:
    f0: int
    f1: int
    height: str                  # high | mid | low | any
    into: str


@dataclass
class Step:
    f0: int
    f1: int
    vx: int = 0
    vy: int = 0


@dataclass
class ProjSpec:
    frame: int
    rect: Rect
    offset: tuple[int, int]
    vx: int
    vy: int
    life: int
    hit: Hit
    hits: int = 1
    gravity: int = 0
    kind: str = "projectile"     # projectile | talisman (stationary trap) | wave
    limit: int = 1               # max alive from this owner (all kinds)
    destroy_on_hit: bool = True


@dataclass
class ThrowSpec:
    reach: int
    hit: Hit
    tech: bool = True
    grab_frames: int = 22
    air: bool = False
    release_vx: int = 0          # velocity applied to victim on release (forward relative to thrower)
    swap: bool = False


@dataclass
class ZoneSpec:
    frame: int
    rect: Rect
    offset: int                  # forward offset of zone centre from user (sub-px)
    life: int
    slow: int = 3                # every Nth frame the victim's move timers do not advance


@dataclass
class Move:
    key: str
    name: str
    notation: str
    kind: str                    # normal | special | super | throw | follow | system
    startup: int
    active: int
    recovery: int
    air: bool = False
    stance: str = "stand"        # stand | crouch | air (base hurtbox)
    boxes: list[Box] = field(default_factory=list)
    hurt: list[Box] = field(default_factory=list)
    cancels: list[Cancel] = field(default_factory=list)
    invuln: list[Invuln] = field(default_factory=list)
    armor: Armor | None = None
    counter: Counter | None = None
    steps: list[Step] = field(default_factory=list)
    projectile: ProjSpec | None = None
    throw: ThrowSpec | None = None
    zone: ZoneSpec | None = None
    echo: bool = False
    cost: int = 0
    pose: str = ""
    tags: tuple[str, ...] = ()
    land_recovery: int = 6
    hit: Hit = field(default_factory=Hit)
    motion: tuple[str, Any] = ("none", None)       # none | hold | seq | charge
    buttons: int = 0
    desc: str = ""
    superflash: int = 0
    hold_move: bool = False

    @property
    def total(self) -> int:
        return self.startup + self.active + self.recovery - 1

    @property
    def last_active(self) -> int:
        return self.startup + self.active - 1

    def adv_on(self, hit: bool, frame: int | None = None) -> int | None:
        """Frame advantage if this move connects on ``frame`` (default: first active frame)."""
        if self.throw is None and not self.boxes and self.projectile is None:
            return None
        f = self.startup if frame is None else frame
        h = self.hit
        stun = h.hitstun if hit else h.blockstun
        return stun - (self.total - f)


_NOTE = re.compile(r"^(?P<air>j\.)?(?P<motion>\[[1-9]\][1-9]|[1-9]+)?(?P<btn>[LMHP](?:\+[LMHP])*)?$")


def parse_notation(note: str) -> tuple[tuple[str, Any], int, bool]:
    """Return (motion, button mask, air) from notation such as ``236L``, ``[4]6H``, ``j.M``, ``L+M``."""
    m = _NOTE.match(note)
    if not m or not (m.group("btn") or m.group("motion")):
        raise ValueError(f"bad notation {note!r}")
    air = bool(m.group("air"))
    mot = m.group("motion") or ""
    btn = 0
    for ch in (m.group("btn") or "").replace("+", ""):
        btn |= BUTTON_NAMES[ch]
    if not mot or mot == "5":
        motion = ("none", None)
    elif mot.startswith("["):
        motion = ("charge", (int(mot[1]), int(mot[3])))
    elif len(mot) == 1:
        motion = ("hold", int(mot))
    else:
        motion = ("seq", tuple(int(c) for c in mot))
    return motion, btn, air


def _boxes(raw: list[dict], default_f0: int, default_f1: int, move_hit: Hit) -> list[Box]:
    out = []
    for i, b in enumerate(raw):
        h = build_hit(b["hit"], move_hit) if "hit" in b else None
        out.append(Box(rect_px(b["rect"]), int(b.get("from", default_f0)), int(b.get("to", default_f1)),
                       int(b.get("group", 0)), h))
    return out


def build_move(key: str, d: dict) -> Move:
    motion, btn, air = parse_notation(d["input"]) if d.get("input") else (("none", None), 0, False)
    air = bool(d.get("air", air))
    mv = Move(key=key, name=d.get("name", key), notation=d.get("input", ""), kind=d.get("kind", "normal"),
              startup=int(d["startup"]), active=int(d["active"]), recovery=int(d["recovery"]), air=air,
              stance=d.get("stance", "air" if air else "stand"), motion=motion, buttons=btn,
              pose=d.get("pose", key), tags=tuple(d.get("tags", ())), cost=int(d.get("cost", 0)),
              land_recovery=int(d.get("land_recovery", 6)), echo=bool(d.get("echo", False)),
              desc=d.get("desc", ""), superflash=int(d.get("superflash", 0)),
              hold_move=bool(d.get("hold_move", False)))
    mv.hit = build_hit(d.get("hit", {}))
    mv.boxes = _boxes(d.get("hitboxes", []), mv.startup, mv.last_active, mv.hit)
    mv.hurt = _boxes(d.get("hurt", []), 1, mv.total, mv.hit)
    mv.cancels = [Cancel(c["on"], tuple(c["into"]), int(c.get("from", 1)), int(c.get("to", 999)))
                  for c in d.get("cancels", [])]
    mv.invuln = [Invuln(int(i["from"]), int(i["to"]), i.get("kind", "all")) for i in d.get("invuln", [])]
    if "armor" in d:
        a = d["armor"]
        mv.armor = Armor(int(a["from"]), int(a["to"]), int(a.get("hits", 1)))
    if "counter" in d:
        c = d["counter"]
        mv.counter = Counter(int(c["from"]), int(c["to"]), c.get("height", "any"), c["into"])
    mv.steps = [Step(int(s["from"]), int(s["to"]), int(s.get("vx", 0)), int(s.get("vy", 0)))
                for s in d.get("move", [])]
    if "projectile" in d:
        p = d["projectile"]
        mv.projectile = ProjSpec(int(p["frame"]), rect_px(p["rect"]),
                                 (int(p["offset"][0]) * SUB, int(p["offset"][1]) * SUB),
                                 int(p.get("vx", 0)), int(p.get("vy", 0)), int(p["life"]),
                                 build_hit(p.get("hit", {}), mv.hit), int(p.get("hits", 1)),
                                 int(p.get("gravity", 0)), p.get("kind", "projectile"),
                                 int(p.get("limit", 1)), bool(p.get("destroy_on_hit", True)))
    if "throw" in d:
        t = d["throw"]
        mv.throw = ThrowSpec(int(t["reach"]) * SUB, build_hit(t.get("hit", {}), mv.hit), bool(t.get("tech", True)),
                             int(t.get("grab_frames", 22)), bool(t.get("air", False)),
                             int(t.get("release_vx", 0)), bool(t.get("swap", False)))
    if "zone" in d:
        z = d["zone"]
        mv.zone = ZoneSpec(int(z["frame"]), rect_px(z["rect"]), int(z.get("offset", 0)) * SUB, int(z["life"]),
                           int(z.get("slow", 3)))
    return mv


@dataclass
class Character:
    id: str
    name: str
    title: str
    feeling: str
    archetype: str
    desc: str
    color: tuple[int, int, int]
    accent: tuple[int, int, int]
    health: int
    walk_f: int
    walk_b: int
    jump_pre: int
    jump_vy: int
    jump_vx: int
    gravity: int
    dash_f: tuple[int, int, int]       # frames, vx, cancelable-after frame
    dash_b: tuple[int, int, int, int]  # frames, vx, invuln frames, extra recovery
    push_half: int
    hurt: dict[str, Rect]
    moves: dict[str, Move]
    mech: str = ""
    boss: bool = False
    selectable: bool = True
    requires_unlock: str = ""
    build: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def move_for_input(self) -> list[Move]:
        return [m for m in self.moves.values() if m.notation]


def build_character(d: dict) -> Character:
    hurt = {k: rect_px(v) for k, v in d["hurt"].items()}
    moves = {k: build_move(k, m) for k, m in d["moves"].items()}
    jump = d["jump"]
    df, db = d["dash_f"], d["dash_b"]
    return Character(
        id=d["id"], name=d["name"], title=d.get("title", ""), feeling=d.get("feeling", ""),
        archetype=d.get("archetype", "all"), desc=d.get("desc", ""), color=tuple(d["color"]),
        accent=tuple(d["accent"]), health=int(d.get("health", 1000)), walk_f=int(d["walk_f"]),
        walk_b=int(d["walk_b"]), jump_pre=int(jump.get("pre", 4)), jump_vy=int(jump["vy"]),
        jump_vx=int(jump["vx"]), gravity=int(jump.get("gravity", 8)),
        dash_f=(int(df["frames"]), int(df["vx"]), int(df.get("cancel", df["frames"]))),
        dash_b=(int(db["frames"]), int(db["vx"]), int(db.get("invuln", 0)), int(db.get("recovery", 0))),
        push_half=int(d.get("push_half", 11)) * SUB, hurt=hurt, moves=moves, mech=d.get("mech", ""),
        boss=bool(d.get("boss", False)), selectable=bool(d.get("selectable", True)),
        requires_unlock=d.get("requires_unlock", ""), build=d.get("build", {}), raw=d)
