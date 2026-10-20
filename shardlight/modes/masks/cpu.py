"""CPU opponent: fair, frame-data-aware and adaptive.

* It sees the opponent through a *delayed* view (reaction frames depend on the level), so it cannot block a 4-frame
  jab on reaction but can block a slow overhead - like a human.
* It reads the real frame data of both characters to pick punishes (a move that finishes startup before the opponent's
  recovery ends) and to classify moves by role (projectile, reversal, gap closer, grab, counter stance, super).
* Habits of the opponent (jump-ins, standing vs crouching blocks, throws, projectiles) are modelled by
  ``core.ai.PlayerModel`` and turned into small, cooled-down counters by ``core.ai.AdaptiveController``.
* Deterministic: its randomness comes from a seeded ``Rng``, so replays reproduce CPU behaviour exactly.
"""
from __future__ import annotations

from collections import deque

from ...core.ai import Adaptation, AdaptiveController, PlayerModel
from ...core.rng import Rng
from .sim import consts as C
from .sim.fight import Match
from .sim.moves import Move

LEVELS = {1: {"react": 22, "block": 0.45, "punish": 0.35, "aggr": 0.35, "mix": 0.2},
          2: {"react": 15, "block": 0.65, "punish": 0.6, "aggr": 0.5, "mix": 0.35},
          3: {"react": 10, "block": 0.82, "punish": 0.82, "aggr": 0.6, "mix": 0.5},
          4: {"react": 7, "block": 0.92, "punish": 0.94, "aggr": 0.7, "mix": 0.65}}

DIRBITS = {1: C.DOWN | C.LEFT, 2: C.DOWN, 3: C.DOWN | C.RIGHT, 4: C.LEFT, 6: C.RIGHT, 7: C.UP | C.LEFT, 8: C.UP,
           9: C.UP | C.RIGHT}


def digit_mask(d: int, facing: int) -> int:
    m = DIRBITS[d]
    if facing < 0:                       # mirror horizontal bits
        h = (C.LEFT if m & C.RIGHT else 0) | (C.RIGHT if m & C.LEFT else 0)
        m = (m & ~(C.LEFT | C.RIGHT)) | h
    return m


def motion_masks(mv: Move, facing: int) -> list[int] | None:
    """Input frames that perform ``mv`` (None for charge moves the CPU does not attempt)."""
    kind, arg = mv.motion
    if kind == "charge":
        return None
    seq: list[int] = []
    if kind == "seq":
        seq = [digit_mask(d, facing) for d in arg]
    elif kind == "hold":
        seq = [digit_mask(int(arg), facing)] if arg != 5 else []
    if seq:
        seq[-1] |= mv.buttons
    else:
        seq = [mv.buttons]
    out: list[int] = []
    for i, m in enumerate(seq):
        out.append(m)
        if i < len(seq) - 1:
            out.append(m)
    return out + [0]


class CpuBrain:
    def __init__(self, level: int = 2, seed: int = 1, adapt: float = 1.0, idx: int = 1):
        self.cfg = dict(LEVELS[max(1, min(4, level))])
        self.level = level
        self.rng = Rng(seed).child("cpu", idx)
        self.idx = idx
        self.queue: list[int] = []
        self.view: deque = deque(maxlen=40)
        self.model = PlayerModel(half_life=18.0)
        self.adapt = AdaptiveController(self.model, [
            Adaptation("anti_air", "jump_in", ("jump_in", "ground_approach"), threshold=0.5, min_weight=2.5, max_bonus=0.45),
            Adaptation("mix_low", "stand_block", ("stand_block", "crouch_block"), threshold=0.6, min_weight=2.5,
                       max_bonus=0.4),
            Adaptation("mix_high", "crouch_block", ("stand_block", "crouch_block"), threshold=0.6, min_weight=2.5,
                       max_bonus=0.4),
            Adaptation("zone_pressure", "throw_try", ("throw_try", "other_attack"), threshold=0.5, min_weight=2.0,
                       max_bonus=0.3),
        ], strength=adapt, cooldown=6.0)
        self._prev_opp_state = ""
        self._last_decide = -99
        self.decisions: list[str] = []
        self.roles: dict[str, list[Move]] | None = None
        self.last_hp = None

    # -- move roles --------------------------------------------------------------------------------
    def classify(self, ch) -> dict[str, list[Move]]:
        roles: dict[str, list[Move]] = {k: [] for k in
                                        ("projectile", "reversal", "closer", "grab", "counter", "zone", "super",
                                         "echo", "armor", "overhead", "low", "normal")}
        for mv in ch.moves.values():
            if not mv.notation:
                continue
            if mv.kind == "super":
                roles["super"].append(mv)
            elif mv.projectile:
                roles["projectile"].append(mv)
            elif mv.counter:
                roles["counter"].append(mv)
            elif mv.zone and not mv.boxes:
                roles["zone"].append(mv)
            elif mv.throw and mv.kind != "throw":
                roles["grab"].append(mv)
            elif mv.echo:
                roles["echo"].append(mv)
            elif mv.armor:
                roles["armor"].append(mv)
            elif mv.invuln and mv.kind == "special" and mv.boxes:
                roles["reversal"].append(mv)
            elif mv.steps and mv.kind == "special" and mv.boxes and mv.hit.height != "low":
                roles["closer"].append(mv)
            elif mv.kind == "normal" and not mv.air:
                roles["normal"].append(mv)
            if mv.hit.height == "high" and not mv.air and mv.kind != "normal":
                roles["overhead"].append(mv)
            if mv.hit.height == "low" and mv.kind != "normal":
                roles["low"].append(mv)
        return roles

    # -- per frame ---------------------------------------------------------------------------------
    def act(self, m: Match) -> int:
        me, opp = m.fighters[self.idx], m.fighters[1 - self.idx]
        if self.roles is None:
            self.roles = self.classify(me.char)
        dist = abs(opp.x - me.x) // C.SUB
        self.view.append({"st": opp.state, "key": opp.move.key if opp.move else "", "mf": opp.mf,
                          "su": opp.move.startup if opp.move else 0, "la": opp.move.last_active if opp.move else 0,
                          "tot": opp.move.total if opp.move else 0, "h": opp.move.hit.height if opp.move else "mid",
                          "air": opp.y > 0, "dist": dist, "proj": any(p.owner != self.idx for p in m.projs),
                          "projd": min((abs(p.x - me.x) // C.SUB for p in m.projs if p.owner != self.idx), default=999),
                          "vy": opp.vy, "contact": opp.contact})
        self._observe(m, opp)
        self.adapt.update(m.frame / C.FPS, 1 / C.FPS)
        if self.queue:
            return self.queue.pop(0)
        if m.phase != "fight":
            return 0
        lag = min(self.cfg["react"], len(self.view) - 1)
        v = self.view[-1 - lag]
        face = me.facing
        fwd = C.RIGHT if face > 0 else C.LEFT
        back = C.LEFT if face > 0 else C.RIGHT
        r = self.rng
        # ---- not actionable: keep guarding while stunned in block
        if me.state == "block":
            return back | (C.DOWN if me.crouch_block else 0)
        if me.state not in C.ACTIONABLE and me.state != "air":
            return 0
        if me.state == "air":
            return 0
        cfg = self.cfg
        # ---- projectile defence
        if v["proj"] and v["projd"] < 120 and r.chance(cfg["block"]) and not me.char.moves.get("noop"):
            return back
        # ---- defence against a visible attack
        if v["st"] == "attack" and v["mf"] <= v["la"] and v["dist"] < 120:
            if r.chance(cfg["block"] * (0.5 if v["mf"] > v["su"] else 1.0)):
                if self.level >= 3 and v["tot"] > 24 and r.chance(0.12):
                    self.queue = [C.PAR, 0]
                    return 0
                low = v["h"] == "low"
                return back | (C.DOWN if low or (v["h"] != "high" and r.chance(0.4)) else 0)
        # ---- punish recovery with a move that is fast enough
        if v["st"] == "attack" and v["mf"] > v["la"] and v["dist"] < 70 and r.chance(cfg["punish"]):
            rec_left = v["tot"] - v["mf"]
            mv = self._best_punish(me, rec_left, v["dist"])
            if mv:
                return self._perform(mv, face)
        # ---- anti-air
        if v["air"] and v["dist"] < 70 and v["vy"] < 40 and r.chance(0.55 + self.adapt.level("anti_air")):
            rev = self.roles["reversal"]
            if rev:
                return self._perform(rev[0], face)
            up = me.char.moves.get("2H")
            if up:
                return self._perform(up, face)
        # ---- wake-up / hit-stun escape: nothing
        if opp.state in ("down", "wake", "ko"):
            return fwd if dist > 36 else 0
        # ---- spacing by archetype
        return self._neutral(m, me, opp, v, dist, face, fwd, back)

    def _observe(self, m: Match, opp) -> None:
        now = m.frame / C.FPS
        st = opp.state
        if st != self._prev_opp_state:
            if st == "air" or st == "prejump":
                self.model.record("jump_in", now)
            elif st in ("walkf", "dashf"):
                self.model.record("ground_approach", now)
            elif st == "attack" and opp.move is not None:
                self.model.record("throw_try" if opp.move.throw else "other_attack", now)
            elif st == "block":
                self.model.record("crouch_block" if opp.crouch_block else "stand_block", now)
        self._prev_opp_state = st

    def _best_punish(self, me, rec_left: int, dist: int) -> Move | None:
        best = None
        for mv in me.char.moves.values():
            if not mv.notation or mv.air or mv.kind not in ("normal", "special"):
                continue
            if mv.startup + 2 > rec_left or not mv.boxes:
                continue
            reach = max((b.rect[0] + b.rect[2]) for b in mv.boxes) // C.SUB + me.char.push_half // C.SUB
            if reach + 4 < dist:
                continue
            if mv.motion[0] == "charge":
                continue
            score = mv.hit.damage - mv.startup
            if best is None or score > best[0]:
                best = (score, mv)
        return best[1] if best else None

    def _perform(self, mv: Move, face: int) -> int:
        seq = motion_masks(mv, face)
        if not seq:
            return 0
        self.queue = seq[1:]
        self.decisions.append(mv.key)
        return seq[0]

    def _neutral(self, m, me, opp, v, dist, face, fwd, back) -> int:
        cfg, r, roles = self.cfg, self.rng, self.roles
        arch = me.char.archetype
        acted = lambda mv: self._perform(mv, face)
        normals = {mv.key: mv for mv in roles["normal"]}
        if r.chance(0.04):
            return 0
        meter_ok = me.meter >= C.SUPER_COST
        if meter_ok and roles["super"] and dist < 110 and opp.state in ("hit", "hitair", "block") and r.chance(0.5):
            return acted(roles["super"][0])
        if arch in ("zoner",):
            if roles["projectile"] and dist > 90 and not any(p.owner == self.idx for p in m.projs) and r.chance(0.5):
                return acted(r.pick(roles["projectile"]))
            if dist < 55:
                bs = me.char.moves.get("hop")
                if bs and r.chance(0.35):
                    return acted(bs)
                return acted(normals["5M"]) if "5M" in normals and r.chance(0.5) else back
            return fwd if dist > 160 else (back if dist < 110 else 0)
        if arch in ("grappler",):
            if dist > 40:
                return fwd
            if roles["grab"] and r.chance(0.28 + self.adapt.level("zone_pressure")):
                return acted(roles["grab"][0])
            if "throw" in me.char.moves and r.chance(0.18):
                return acted(me.char.moves["throw"])
            if r.chance(cfg["mix"]) and roles["armor"]:
                return acted(roles["armor"][0])
            return acted(r.pick(list(normals.values())))
        if arch in ("counter",):
            if 40 < dist < 110 and roles["counter"] and r.chance(0.12) and opp.state in ("walkf", "dashf", "idle"):
                return acted(r.pick(roles["counter"]))
            if dist > 60:
                return fwd if r.chance(0.6) else 0
            return acted(r.pick(list(normals.values()))) if r.chance(0.5) else 0
        if arch in ("time",):
            if roles["zone"] and not m.zones and dist > 60 and r.chance(0.3):
                return acted(roles["zone"][0])
            if roles["echo"] and 40 < dist < 70 and r.chance(0.3):
                return acted(roles["echo"][0])
        # rushdown / boss / default: close in, pressure with a mixup
        if dist > 90 and roles["closer"] and r.chance(0.3):
            return acted(r.pick(roles["closer"]))
        if arch == "boss" and roles["projectile"] and dist > 110 and r.chance(0.3):
            return acted(roles["projectile"][0])
        if dist > 44:
            if r.chance(0.12):
                self.queue = [fwd, 0, fwd, 0]
            return fwd
        roll = r.random()
        if roll < 0.18 + self.adapt.level("mix_low") * 0.6 and "2M" in normals:
            return acted(normals["2M"])
        if roll < 0.32 + self.adapt.level("mix_high") * 0.5 and roles["overhead"]:
            return acted(r.pick(roles["overhead"]))
        if roll < 0.42 and "throw" in me.char.moves:
            return acted(me.char.moves["throw"])
        key = r.pick(["5L", "5L", "5M", "2L", "5H"])
        if key in normals:
            return acted(normals[key])
        return 0
