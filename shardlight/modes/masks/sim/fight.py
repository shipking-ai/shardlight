"""Deterministic fighting-game core: fighters, hit resolution and the round/match flow.

Integer-only (positions in 1/16 px), no wall-clock, no global random.  One call to :meth:`Match.step` advances
exactly one 60 Hz frame given both players' input bitmasks, so the same input log always yields the same
state hash (used by replays and tests).

Rect convention: ``(forward_offset, bottom, width, height)`` relative to the owner's feet, mirrored by facing.
y grows upward (ground = 0).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .consts import (BUFFER_FRAMES, ACTIONABLE, AIR_FRICTION, ATTACKS, BLOCK_PUSH_PX, COMBO_DAMAGE_CAP, DASHB, DASHF, DIRS, DOWN,
                     FPS, FRICTION, HEIGHT_HIGH, HEIGHT_LOW, HITSTUN_DECAY, HITSTUN_DECAY_START, INTRO_FRAMES,
                     JUGGLE_LIMIT, KO_FRAMES, LEFT, LP, MAX_HEALTH, MAX_METER, MAX_SEP, MIN_DAMAGE_PERCENT, MP,
                     PAR, PARRY_ADV, PARRY_HITSTOP, PARRY_MEMORY, PARRY_PENALTY, PARRY_RECOVERY,
                     PARRY_SUCCESS_RECOVERY, PARRY_WINDOW, PRORATION, PUSH_HALF, RIGHT, ROUND_END_FRAMES,
                     ROUND_FRAMES, ROUNDS_TO_WIN, S_AIR, S_ATTACK, S_BLOCK, S_CROUCH, S_DASHB, S_DASHF, S_DOWN,
                     S_HIT, S_HITAIR, S_IDLE, S_KO, S_LAND, S_PARRY, S_PREJUMP, S_THROWN, S_WAKE, S_WALKB,
                     S_WALKF, STAGE_HALF, SUB, THROW_TECH_WINDOW, UP, WAKEUP_INVULN, HP)
from .inputs import InputBuffer, numpad
from .moves import Character, Hit, Move

Rect = tuple[int, int, int, int]
LYING = (-30 * SUB, 0, 60 * SUB, 16 * SUB)
THROW_HOLD = 18
DOWN_FRAMES = 30
HEAD_PUSH_H = 70 * SUB


def world_rect(x: int, y: int, facing: int, r: Rect) -> tuple[int, int, int, int]:
    ox, by, w, h = r
    x0 = x + ox if facing > 0 else x - ox - w
    return x0, y + by, x0 + w, y + by + h


def overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@dataclass
class Proj:
    owner: int
    x: int
    y: int
    vx: int
    vy: int
    facing: int
    rect: Rect
    hit: Hit
    life: int
    hits: int
    gravity: int
    kind: str
    destroy: bool
    mkey: str
    age: int = 0
    last_hit: int = -99


@dataclass
class Zone:
    owner: int
    x: int
    y: int
    facing: int
    rect: Rect
    life: int
    slow: int


@dataclass
class EchoVol:
    owner: int
    x: int
    y: int
    facing: int
    move: Move
    delay: int
    t: int = 0


class Fighter:
    def __init__(self, idx: int, char: Character, x: int, facing: int):
        self.idx = idx
        self.char = char
        self.x = x * SUB
        self.y = 0
        self.vx = 0
        self.vy = 0
        self.facing = facing
        self.hp = char.health
        self.meter = 0
        self.state = S_IDLE
        self.state_t = 0
        self.move: Move | None = None
        self.mf = 0
        self.stun = 0
        self.hitstop = 0
        self.invuln = 0
        self.buf = InputBuffer()
        self.combo_hits = 0
        self.combo_dmg = 0
        self.combo_scale = 100
        self.juggle = 0
        self.contact = ""            # "", "hit", "block" for the current move (cancel conditions)
        self.hit_groups: set[int] = set()
        self.armor_left = 0
        self.parry_ok = False
        self.parry_tries = 0
        self.parry_last = -999
        self.crouch_block = False
        self.jump_dx = 0
        self.thrown_by: Fighter | None = None
        self.throw_info: tuple | None = None
        self.knockdown = False
        self.last_move_key = ""
        self.moves_seen: dict[str, int] = {}     # for training mode frame data
        self.combo_best = 0
        self.pending_counter: str = ""
        self.slowed = False
        self.dash_cancelled = False
        self.air_dashed = False
        self.landed_flag = False
        self.credit = 0              # buffer slack earned while frozen in hit-stop (inputs do not expire during it)

    # -- helpers ----------------------------------------------------------------------------
    @property
    def px(self) -> int:
        return self.x // SUB

    @property
    def grounded(self) -> bool:
        return self.y <= 0 and self.vy <= 0

    def hurt_rects(self) -> list[Rect]:
        mv = self.move
        if self.state == S_ATTACK and mv and mv.hurt:
            out = [b.rect for b in mv.hurt if b.active_on(self.mf)]
            if out:
                return out
        if self.state in (S_DOWN, S_KO):
            return [LYING]
        if self.state in (S_AIR, S_HITAIR) or (mv and mv.air and self.state == S_ATTACK):
            return [self.char.hurt["air"]]
        if self.state == S_CROUCH or (mv and mv.stance == "crouch" and self.state == S_ATTACK) or \
                (self.state in (S_BLOCK, S_HIT) and self.crouch_block):
            return [self.char.hurt["crouch"]]
        return [self.char.hurt["stand"]]

    def invulnerable_to(self, kind: str) -> bool:
        if self.invuln > 0 or self.state in (S_DOWN, S_KO, S_WAKE):
            return True
        if self.state == S_DASHB and self.state_t <= self.char.dash_b[2]:
            return True
        mv = self.move
        if self.state == S_ATTACK and mv:
            for iv in mv.invuln:
                if iv.f0 <= self.mf <= iv.f1 and iv.kind in ("all", kind):
                    return True
        return False

    def snapshot(self) -> tuple:
        return (self.x, self.y, self.vx, self.vy, self.facing, self.state, self.state_t,
                self.move.key if self.move else "", self.mf, self.hp, self.meter, self.stun, self.hitstop,
                self.invuln, self.combo_hits, self.combo_dmg, self.combo_scale, self.juggle, self.contact,
                self.armor_left, self.parry_tries, self.buf.snapshot())


class Match:
    """Two fighters, projectiles, zones and the round flow."""

    def __init__(self, chars: tuple[Character, Character], seed: int = 1, rounds: int = ROUNDS_TO_WIN,
                 round_frames: int = ROUND_FRAMES, training: bool = False):
        self.chars = chars
        self.seed = seed
        self.rounds_to_win = rounds
        self.round_frames = round_frames
        self.training = training
        self.frame = 0
        self.wins = [0, 0]
        self.round_no = 1
        self.phase = "intro"          # intro | fight | ko | roundend | over
        self.phase_t = 0
        self.timer = round_frames
        self.winner: int | None = None     # match winner (0/1) or -1 draw
        self.round_winner: int | None = None
        self.freeze = 0               # super flash freeze (both frozen)
        self.freeze_owner = -1
        self.projs: list[Proj] = []
        self.zones: list[Zone] = []
        self.echoes: list[EchoVol] = []
        self.events: list[tuple] = []    # (kind, x_px, y_px, data) consumed by the scene for fx/sfx
        self.fighters: list[Fighter] = []
        self.infinite_health = False
        self.infinite_meter = False
        self.log: list[tuple[int, int]] = []
        self.record = False
        self.last_move_info: dict[int, dict] = {0: {}, 1: {}}
        self._reset_round()

    # ------------------------------------------------------------------ round flow
    def _reset_round(self) -> None:
        keep_meter = [f.meter for f in self.fighters] if self.fighters else [0, 0]
        self.fighters = [Fighter(0, self.chars[0], -80, 1), Fighter(1, self.chars[1], 80, -1)]
        if self.training:
            for f, m in zip(self.fighters, keep_meter):
                f.meter = m
        self.projs.clear()
        self.zones.clear()
        self.echoes.clear()
        self.freeze = 0
        self.timer = self.round_frames
        self.phase = "intro"
        self.phase_t = 0
        self.round_winner = None

    def _end_round(self, winner: int | None) -> None:
        self.round_winner = winner
        if winner is not None and winner >= 0:
            self.wins[winner] += 1
        elif winner == -1:
            self.wins[0] += 1
            self.wins[1] += 1
        self.phase = "ko"
        self.phase_t = 0
        self.events.append(("ko", 0, 0, {"winner": winner}))

    def step(self, inputs: tuple[int, int]) -> None:
        self.events = []
        self.frame += 1
        if self.record:
            self.log.append((inputs[0], inputs[1]))
        f0, f1 = self.fighters
        self.phase_t += 1
        if self.phase == "intro":
            self._push_inputs((0, 0))
            if self.phase_t >= INTRO_FRAMES:
                self.phase = "fight"
                self.phase_t = 0
                self.events.append(("fight", 0, 0, {}))
            return
        if self.phase in ("ko", "roundend", "over"):
            self._push_inputs((0, 0))
            self._tick_passive()
            limit = KO_FRAMES if self.phase == "ko" else ROUND_END_FRAMES
            if self.phase_t >= limit:
                if self.phase == "ko":
                    self.phase = "roundend"
                    self.phase_t = 0
                    if max(self.wins) >= self.rounds_to_win:
                        w0, w1 = self.wins
                        self.winner = -1 if w0 == w1 else (0 if w0 > w1 else 1)
                elif self.phase == "roundend":
                    if self.winner is not None:
                        self.phase = "over"
                        self.phase_t = 0
                    else:
                        self.round_no += 1
                        self._reset_round()
            return
        self._push_inputs(inputs)
        if self.freeze > 0:
            self.freeze -= 1
            return
        for f in self.fighters:
            f.slowed = False
        for z in self.zones:
            for f in self.fighters:
                if f.idx != z.owner and overlap(world_rect(z.x, z.y, z.facing, z.rect), self._body(f)):
                    if self.frame % z.slow == 0:
                        f.slowed = True
        for f in self.fighters:
            if f.hitstop > 0:
                f.hitstop -= 1
                f.credit = min(12, f.credit + 1)
                continue
            if f.slowed:
                continue
            if f.credit and f.state_t % 2 == 0:
                f.credit -= 1
            self._update(f)
        self._update_objects()
        self._separate()
        self._detect_hits()
        self._after()

    def _push_inputs(self, inputs) -> None:
        for f, m in zip(self.fighters, inputs):
            f.buf.push(m, f.facing)

    def _tick_passive(self) -> None:
        for f in self.fighters:
            if f.hitstop > 0:
                f.hitstop -= 1
                continue
            self._physics(f)
            if f.state not in (S_KO, S_DOWN, S_HITAIR) and f.hp > 0:
                f.state = S_IDLE if f.state in (S_ATTACK, S_BLOCK, S_HIT, S_PARRY) else f.state
            if f.state == S_HITAIR and f.grounded:
                f.state = S_DOWN
                f.state_t = 0

    def _body(self, f: Fighter) -> tuple[int, int, int, int]:
        return world_rect(f.x, f.y, f.facing, f.hurt_rects()[0])

    # ------------------------------------------------------------------ per fighter update
    def _opp(self, f: Fighter) -> Fighter:
        return self.fighters[1 - f.idx]

    def _update(self, f: Fighter) -> None:
        opp = self._opp(f)
        ch = f.char
        f.state_t += 1
        if f.invuln > 0:
            f.invuln -= 1
        if f.parry_tries and self.frame - f.parry_last > PARRY_MEMORY:
            f.parry_tries = 0
        st = f.state
        if st in ACTIONABLE or st == S_LAND and f.state_t > 2:
            if st == S_LAND:
                f.state = S_IDLE
            self._face(f, opp)
            self._actionable(f, opp)
        elif st == S_ATTACK:
            self._run_move(f, opp)
        elif st == S_PREJUMP:
            if f.state_t >= ch.jump_pre:
                f.state = S_AIR
                f.state_t = 0
                f.vy = ch.jump_vy
                f.vx = f.jump_dx * ch.jump_vx
                f.air_dashed = False
        elif st == S_AIR:
            self._air_actions(f, opp)
        elif st in (S_DASHF, S_DASHB):
            frames = ch.dash_f[0] if st == S_DASHF else ch.dash_b[0]
            spd = ch.dash_f[1] if st == S_DASHF else -ch.dash_b[1]
            f.vx = spd * f.facing
            sp = self._pick_move(f, [m for m in ch.moves.values() if m.kind in ("special", "super")], air=False)
            if sp is not None:                      # specials cancel a dash at any time
                self._start_move(f, sp)
                return
            if st == S_DASHF and f.state_t >= ch.dash_f[2]:
                self._try_cancel_dash(f, opp)
            if f.state_t >= frames + (ch.dash_b[3] if st == S_DASHB else 0):
                f.state = S_IDLE
                f.state_t = 0
                f.vx = 0
        elif st in (S_HIT, S_BLOCK):
            f.stun -= 1
            if f.stun <= 0:
                f.state = S_CROUCH if f.crouch_block and f.buf.hist and numpad(f.buf.hist[-1], f.facing) in (1, 2, 3) \
                    else S_IDLE
                f.state_t = 0
                f.combo_hits = 0 if st == S_HIT else f.combo_hits
        elif st == S_HITAIR:
            if f.grounded and f.state_t > 1:
                f.state = S_DOWN
                f.state_t = 0
                f.vx = f.vx // 2
                self.events.append(("land_hard", f.x // SUB, 0, {"idx": f.idx}))
        elif st == S_DOWN:
            if f.state_t >= DOWN_FRAMES and f.hp > 0:
                f.state = S_WAKE
                f.state_t = 0
                f.invuln = WAKEUP_INVULN
                f.combo_hits = 0
        elif st == S_WAKE:
            if f.state_t >= WAKEUP_INVULN:
                f.state = S_IDLE
                f.state_t = 0
        elif st == S_PARRY:
            self._run_parry(f)
        elif st == S_THROWN:
            self._run_thrown(f)
        self._physics(f)

    def _face(self, f: Fighter, opp: Fighter) -> None:
        if f.grounded:
            if opp.x > f.x:
                f.facing = 1
            elif opp.x < f.x:
                f.facing = -1

    # -- actionable ---------------------------------------------------------------------------
    def _actionable(self, f: Fighter, opp: Fighter) -> None:
        ch = f.char
        buf = f.buf
        mask = buf.hist[-1] if buf.hist else 0
        n = numpad(mask, f.facing)
        mv = self._pick_move(f, list(ch.moves.values()), air=False)
        if mv is not None:
            self._start_move(f, mv)
            return
        if buf.button_age(PAR) is not None and f.state in ACTIONABLE:
            buf.consume(PAR)
            f.parry_tries += 1
            f.parry_last = self.frame
            f.state = S_PARRY
            f.state_t = 0
            f.parry_ok = False
            f.vx = 0
            return
        if buf.button_age(DASHF) is not None or buf.double_tap(True, f.facing):
            buf.consume(DASHF)
            buf.consume_dir(True, f.facing)
            f.state, f.state_t = S_DASHF, 0
            return
        if buf.button_age(DASHB) is not None or buf.double_tap(False, f.facing):
            buf.consume(DASHB)
            buf.consume_dir(False, f.facing)
            f.state, f.state_t = S_DASHB, 0
            return
        if n in (7, 8, 9):
            f.state, f.state_t = S_PREJUMP, 0
            f.jump_dx = 0 if n == 8 else (1 if n == 9 else -1) * f.facing
            f.vx = 0
            return
        if n in (1, 2, 3):
            f.state = S_CROUCH
            f.vx = 0
            f.crouch_block = True
            return
        f.crouch_block = False
        if n in (6, 3):
            f.state = S_WALKF
            f.vx = ch.walk_f * f.facing
        elif n in (4, 1):
            f.state = S_WALKB
            f.vx = -ch.walk_b * f.facing
        else:
            f.state = S_IDLE
            f.vx = 0

    def _try_cancel_dash(self, f: Fighter, opp: Fighter) -> None:
        mv = self._pick_move(f, [m for m in f.char.moves.values() if m.kind in ("normal", "special", "super", "throw")],
                             air=False)
        if mv is not None:
            self._start_move(f, mv)

    def _air_actions(self, f: Fighter, opp: Fighter) -> None:
        if f.grounded and f.state_t > 1:
            f.state, f.state_t = S_LAND, 0
            f.vx = 0
            f.y = 0
            f.vy = 0
            return
        mv = self._pick_move(f, list(f.char.moves.values()), air=True)
        if mv is not None:
            self._start_move(f, mv)

    # -- move selection -------------------------------------------------------------------------
    def _spec(self, mv: Move) -> tuple:
        mot = {"seq": 3, "charge": 2, "hold": 1, "none": 0}[mv.motion[0]]
        if mot == 3:
            mot += len(mv.motion[1]) / 10
        return ({"super": 4, "special": 3, "throw": 2, "normal": 1}.get(mv.kind, 0), mot,
                bin(mv.buttons).count("1"))

    def _pick_move(self, f: Fighter, cands: list[Move], air: bool) -> Move | None:
        buf = f.buf
        best = None
        best_key = None
        for mv in cands:
            if not mv.notation or mv.air != air:
                continue
            if mv.kind == "super" and f.meter < mv.cost and not self.infinite_meter:
                continue
            if mv.cost and mv.kind != "super" and f.meter < mv.cost and not self.infinite_meter:
                continue
            age = buf.button_age(mv.buttons, within=BUFFER_FRAMES + f.credit) if mv.buttons else 0
            if age is None:
                continue
            if mv.buttons == 0 and mv.motion[0] != "none":
                continue
            if not buf.motion_ok(mv.motion, f.facing, age):
                continue
            key = self._spec(mv)
            if best is None or key > best_key:
                best, best_key = mv, key
        return best

    def _start_move(self, f: Fighter, mv: Move) -> None:
        f.buf.consume(mv.buttons)
        if mv.motion[0] == "charge":
            f.buf.use_charge({4: "b", 6: "f", 2: "d", 8: "u"}[mv.motion[1][0]])
        f.state = S_ATTACK
        f.state_t = 0
        f.move = mv
        f.mf = 0
        f.contact = ""
        f.hit_groups = set()
        f.armor_left = mv.armor.hits if mv.armor else 0
        f.last_move_key = mv.key
        if not mv.air:
            f.vx = 0
        if mv.kind == "super" and not self.infinite_meter:
            f.meter -= mv.cost
        elif mv.cost and not self.infinite_meter:
            f.meter -= mv.cost
        if mv.superflash:
            self.freeze = mv.superflash
            self.freeze_owner = f.idx
            f.invuln = max(f.invuln, 2)
            self.events.append(("superflash", f.px, 40, {"idx": f.idx, "move": mv.key}))
        if mv.echo:
            self.echoes.append(EchoVol(f.idx, f.x, f.y, f.facing, mv, 34))
        self.last_move_info[f.idx] = {"key": mv.key, "startup": mv.startup, "active": mv.active,
                                      "recovery": mv.recovery, "frame": self.frame, "adv_hit": None, "adv_block": None}
        f.moves_seen[mv.key] = f.moves_seen.get(mv.key, 0) + 1
        self.events.append(("move", f.px, f.y // SUB, {"idx": f.idx, "key": mv.key}))
        self._run_move(f, self._opp(f))          # the press frame is frame 1 of the move

    def _run_move(self, f: Fighter, opp: Fighter) -> None:
        mv = f.move
        f.mf += 1
        mf = f.mf
        if mf > mv.total:
            self._end_move(f)
            return
        # movement steps
        for s in mv.steps:
            if s.f0 <= mf <= s.f1:
                f.vx = s.vx * f.facing
                if s.vy and f.grounded:
                    f.vy = s.vy
                elif s.vy:
                    f.vy = s.vy
        if mv.projectile and mf == mv.projectile.frame:
            self._spawn_proj(f, mv)
        if mv.zone and mf == mv.zone.frame:
            z = mv.zone
            self.zones = [q for q in self.zones if q.owner != f.idx]
            self.zones.append(Zone(f.idx, f.x + z.offset * f.facing, 0, f.facing, z.rect, z.life, z.slow))
        if mv.throw and mf == mv.startup:
            self._try_throw(f, opp, mv)
        # counter windows are resolved on hit; cancels:
        self._check_cancels(f, opp, mv)
        if mv.air and f.grounded and mf > 2:
            f.state, f.state_t = S_LAND, 0
            f.move = None
            f.vx = 0
            f.y = 0
            f.vy = 0

    def _end_move(self, f: Fighter) -> None:
        f.move = None
        f.state_t = 0
        f.state = S_AIR if not f.grounded else S_IDLE
        if f.state == S_IDLE:
            f.vx = 0

    def _check_cancels(self, f: Fighter, opp: Fighter, mv: Move) -> None:
        for c in mv.cancels:
            if not c.f0 <= f.mf <= c.f1:
                continue
            ok = {"hit": f.contact == "hit", "block": f.contact == "block", "contact": f.contact in ("hit", "block"),
                  "whiff": f.contact == "" and f.mf >= mv.last_active, "always": True}[c.on]
            if not ok:
                continue
            nxt = self._cancel_target(f, c.into, mv)
            if nxt is not None:
                self._start_move(f, nxt)
                return

    def _cancel_target(self, f: Fighter, into: tuple[str, ...], cur: Move) -> Move | None:
        ch = f.char
        for entry in into:
            if entry in ch.moves:
                m = ch.moves[entry]
                if m.notation:
                    p = self._pick_move(f, [m], air=m.air)
                    if p:
                        return p
                elif f.buf.button_age(ATTACKS, within=BUFFER_FRAMES + f.credit) is not None:
                    f.buf.consume(ATTACKS)
                    return m
                continue
            if entry == "dash":
                if f.buf.button_age(DASHF) is not None or f.buf.double_tap(True, f.facing):
                    f.buf.consume(DASHF)
                    f.buf.consume_dir(True, f.facing)
                    f.move = None
                    f.state, f.state_t = S_DASHF, 0
                    return None
                continue
            if entry == "jump":
                n = numpad(f.buf.hist[-1], f.facing) if f.buf.hist else 5
                if n in (7, 8, 9) and f.grounded:
                    f.move = None
                    f.state, f.state_t = S_PREJUMP, 0
                    f.jump_dx = 0 if n == 8 else (1 if n == 9 else -1) * f.facing
                    return None
                continue
            kinds = {"special": ("special",), "super": ("super",), "normal": ("normal", "throw"),
                     "heavy": ("normal",), "light": ("normal",), "any": ("normal", "special", "super", "throw")}[entry]
            cands = [m for m in ch.moves.values() if m.kind in kinds and m.notation and m is not cur
                     and m.air == cur.air]
            if entry == "heavy":
                cands = [m for m in cands if m.buttons & HP]
            elif entry == "light":
                cands = [m for m in cands if m.buttons == LP]
            p = self._pick_move(f, cands, air=cur.air)
            if p:
                return p
        return None

    # -- parry ----------------------------------------------------------------------------------
    def _run_parry(self, f: Fighter) -> None:
        f.vx = 0
        extra = max(0, f.parry_tries - 1) * PARRY_PENALTY
        if f.parry_ok:
            if f.state_t > PARRY_SUCCESS_RECOVERY:
                f.state, f.state_t = S_IDLE, 0
        elif f.state_t > PARRY_WINDOW + PARRY_RECOVERY + extra:
            f.state, f.state_t = S_IDLE, 0

    # -- throw ----------------------------------------------------------------------------------
    def _try_throw(self, f: Fighter, opp: Fighter, mv: Move) -> None:
        t = mv.throw
        dx = abs(opp.x - f.x)
        if dx > t.reach + f.char.push_half + opp.char.push_half or abs(opp.y - f.y) > 20 * SUB and not t.air:
            return
        if (not t.air and not opp.grounded) or opp.invulnerable_to("throw"):
            return
        if opp.state in (S_HIT, S_HITAIR, S_THROWN, S_AIR, S_PREJUMP, S_KO):
            return
        if opp.state == S_ATTACK and opp.move and opp.mf > opp.move.startup:
            return
        both_throwing = opp.state == S_ATTACK and opp.move is not None and opp.move.throw is not None             and opp.mf <= opp.move.startup + 2
        if t.tech and (both_throwing or opp.buf.button_age(LP | MP, within=THROW_TECH_WINDOW) is not None):
            for a, b in ((f, opp), (opp, f)):
                a.vx = -b.facing * 36
                a.hitstop = 6
            f.state, f.state_t = S_IDLE, 0
            f.move = None
            opp.move = None
            opp.state, opp.state_t = S_IDLE, 0
            self.events.append(("tech", (f.px + opp.px) // 2, 30, {}))
            return
        opp.state, opp.state_t = S_THROWN, 0
        opp.move = None
        opp.thrown_by = f
        opp.throw_info = (t, mv)
        opp.vx = 0
        f.contact = "hit"
        f.hitstop = 8
        opp.hitstop = 8
        self.last_move_info[f.idx]["adv_hit"] = None
        self.events.append(("grab", f.px, 30, {"idx": f.idx}))

    def _run_thrown(self, f: Fighter) -> None:
        a = f.thrown_by
        t, mv = f.throw_info
        f.x = a.x + a.facing * 22 * SUB
        f.y = 0
        f.vx = 0
        f.vy = 0
        if f.state_t >= max(8, t.grab_frames // 2):
            h = t.hit
            f.thrown_by = None
            self._apply_hit(a, f, h, mv, thrown=True)

    # -- projectiles ----------------------------------------------------------------------------
    def _spawn_proj(self, f: Fighter, mv: Move) -> None:
        ps = mv.projectile
        mine = [p for p in self.projs if p.owner == f.idx and p.mkey == mv.key]
        if len(mine) >= ps.limit:
            return
        ox, oy = ps.offset
        self.projs.append(Proj(f.idx, f.x + ox * f.facing, f.y + oy, ps.vx * f.facing, ps.vy, f.facing, ps.rect,
                               ps.hit, ps.life, ps.hits, ps.gravity, ps.kind, ps.destroy_on_hit, mv.key))
        self.events.append(("proj", f.px, oy // SUB, {"idx": f.idx, "key": mv.key}))

    def _update_objects(self) -> None:
        for p in self.projs:
            p.age += 1
            p.life -= 1
            p.vy -= p.gravity
            p.x += p.vx
            p.y += p.vy
            if p.y < 0 and p.gravity:
                p.life = 0
            if abs(p.x) > STAGE_HALF + 40 * SUB:
                p.life = 0
        for i, p in enumerate(self.projs):
            for q in self.projs[i + 1:]:
                if p.owner != q.owner and p.life > 0 and q.life > 0 and \
                        overlap(world_rect(p.x, p.y, p.facing, p.rect), world_rect(q.x, q.y, q.facing, q.rect)):
                    p.life = q.life = 0
                    self.events.append(("clash", p.x // SUB, p.y // SUB, {}))
        self.projs = [p for p in self.projs if p.life > 0]
        for z in self.zones:
            z.life -= 1
        self.zones = [z for z in self.zones if z.life > 0]
        for e in self.echoes:
            e.t += 1
        # echoes replay the recorded move's hitboxes at the original place
        keep = []
        for e in self.echoes:
            if e.t < e.delay:
                keep.append(e)
            elif e.t < e.delay + e.move.active + 2:
                keep.append(e)
        self.echoes = keep

    def _separate(self) -> None:
        a, b = self.fighters
        for f in (a, b):
            f.x = max(-STAGE_HALF, min(STAGE_HALF, f.x))
        if a.y < HEAD_PUSH_H and b.y < HEAD_PUSH_H:
            need = a.char.push_half + b.char.push_half
            dx = b.x - a.x
            if abs(dx) < need:
                push = need - abs(dx)
                d = 1 if dx >= 0 else (-1 if dx < 0 else 1)
                if dx == 0:
                    d = 1 if a.facing > 0 else -1
                half = (push + 1) // 2
                a.x -= d * half
                b.x += d * (push - half)
                for f in (a, b):          # wall pushes back on the pair
                    if f.x > STAGE_HALF:
                        over = f.x - STAGE_HALF
                        f.x = STAGE_HALF
                        o = b if f is a else a
                        o.x -= over
                    elif f.x < -STAGE_HALF:
                        over = -STAGE_HALF - f.x
                        f.x = -STAGE_HALF
                        o = b if f is a else a
                        o.x += over
        if abs(a.x - b.x) > MAX_SEP:                 # camera limit: the one moving apart is stopped
            mid = (a.x + b.x) // 2
            a.x = mid - MAX_SEP // 2 if a.x < b.x else mid + MAX_SEP // 2
            b.x = mid + MAX_SEP // 2 if a.x < b.x else mid - MAX_SEP // 2

    def _physics(self, f: Fighter) -> None:
        mv = f.move
        airborne = f.state in (S_AIR, S_HITAIR) or (f.state == S_ATTACK and mv and mv.air) or f.y > 0 or f.vy > 0
        if airborne:
            if f.state == S_HITAIR:
                f.vy -= 6
            else:
                f.vy -= f.char.gravity
            f.x += f.vx
            f.y += f.vy
            if f.y <= 0 and f.vy < 0:
                f.y = 0
                f.vy = 0
        else:
            f.x += f.vx
            if f.state in (S_HIT, S_BLOCK, S_DOWN, S_KO, S_ATTACK, S_AIR, S_WAKE) and not (
                    f.state == S_ATTACK and mv and any(s.f0 <= f.mf <= s.f1 and s.vx for s in mv.steps)):
                if f.vx > 0:
                    f.vx = max(0, f.vx - FRICTION)
                elif f.vx < 0:
                    f.vx = min(0, f.vx + FRICTION)
        f.x = max(-STAGE_HALF, min(STAGE_HALF, f.x))

    # ------------------------------------------------------------------ hit detection
    def _detect_hits(self) -> None:
        for a in self.fighters:
            d = self.fighters[1 - a.idx]
            if a.hitstop > 0 and a.state != S_ATTACK:
                continue
            mv = a.move
            if a.state == S_ATTACK and mv and mv.boxes and a.hitstop == 0:
                body = [world_rect(d.x, d.y, d.facing, r) for r in d.hurt_rects()]
                for i, box in enumerate(mv.boxes):
                    gid = ("g", box.group) if box.group else ("b", i)
                    if not box.active_on(a.mf) or gid in a.hit_groups:
                        continue
                    wr = world_rect(a.x, a.y, a.facing, box.rect)
                    if any(overlap(wr, b) for b in body):
                        h = box.hit or mv.hit
                        if self._attempt(a, d, h, mv):
                            a.hit_groups.add(gid)
                            break
        for p in self.projs:
            a = self.fighters[p.owner]
            d = self.fighters[1 - p.owner]
            if self.frame - p.last_hit < 8:
                continue
            body = [world_rect(d.x, d.y, d.facing, r) for r in d.hurt_rects()]
            wr = world_rect(p.x, p.y, p.facing, p.rect)
            if any(overlap(wr, b) for b in body):
                if self._attempt(a, d, p.hit, None, proj=p):
                    p.last_hit = self.frame
                    p.hits -= 1
                    if p.hits <= 0 or p.destroy:
                        p.life = 0
        for e in self.echoes:
            if e.delay <= e.t < e.delay + e.move.active:
                a = self.fighters[e.owner]
                d = self.fighters[1 - e.owner]
                body = [world_rect(d.x, d.y, d.facing, r) for r in d.hurt_rects()]
                for box in e.move.boxes:
                    wr = world_rect(e.x, e.y, e.facing, box.rect)
                    if any(overlap(wr, b) for b in body) and e.t == e.delay + 1:
                        self._attempt(a, d, box.hit or e.move.hit, None)
                        break

    def _attempt(self, a: Fighter, d: Fighter, h: Hit, mv: Move | None, proj: Proj | None = None) -> bool:
        """Resolve one box touching the defender.  Returns True if it counted as a hit/block/parry."""
        if d.invulnerable_to("projectile" if proj else "strike"):
            return False
        if d.state == S_PARRY and d.state_t <= PARRY_WINDOW and not h.unblockable and not d.parry_ok:
            self._parry(a, d, mv, proj)
            return True
        dm = d.move
        if d.state == S_ATTACK and dm:
            if dm.counter and dm.counter.f0 <= d.mf <= dm.counter.f1 and dm.counter.height in ("any", h.height) \
                    and proj is None:
                self._counter(a, d, dm)
                return True
            if dm.armor and dm.armor.f0 <= d.mf <= dm.armor.f1 and d.armor_left > 0 and not h.unblockable:
                d.armor_left -= 1
                d.hp = max(1, d.hp - h.damage // 3)
                a.hitstop = d.hitstop = max(h.hitstop, 6)
                a.contact = "block" if proj is None else a.contact
                self.events.append(("armor", d.px, 40, {"idx": d.idx}))
                return True
        if self._can_block(d, h):
            self._block(a, d, h, mv, proj)
        else:
            self._apply_hit(a, d, h, mv, proj=proj)
        return True

    def _can_block(self, d: Fighter, h: Hit) -> bool:
        if h.unblockable:
            return False
        if d.state not in ACTIONABLE and d.state not in (S_BLOCK, S_DASHB, S_AIR):
            return False
        mask = d.buf.hist[-1] if d.buf.hist else 0
        n = numpad(mask, d.facing)
        if n not in (1, 4, 7):
            return False
        if d.state == S_AIR:
            return h.height != HEIGHT_LOW or True
        crouching = n == 1
        if h.height == HEIGHT_LOW:
            return crouching
        if h.height == HEIGHT_HIGH:
            return not crouching
        return True

    def _parry(self, a: Fighter, d: Fighter, mv: Move | None, proj: Proj | None) -> None:
        d.parry_ok = True
        d.state_t = 0
        d.parry_tries = 0
        d.meter = min(MAX_METER, d.meter + 60)
        a.hitstop = d.hitstop = PARRY_HITSTOP
        if mv is not None:
            rem = max(0, mv.total - a.mf)
            a.state, a.state_t = S_BLOCK, 0
            a.stun = rem + PARRY_ADV
            a.move = None
            a.vx = 0
        if proj is not None:
            proj.life = 0
        self.events.append(("parry", d.px, 45, {"idx": d.idx}))

    def _counter(self, a: Fighter, d: Fighter, dm: Move) -> None:
        nxt = d.char.moves[dm.counter.into]
        a.hitstop = d.hitstop = 8
        self._start_move(d, nxt)
        self.events.append(("counter", d.px, 45, {"idx": d.idx}))

    def _block(self, a: Fighter, d: Fighter, h: Hit, mv: Move | None, proj: Proj | None) -> None:
        mask = d.buf.hist[-1] if d.buf.hist else 0
        d.crouch_block = numpad(mask, d.facing) == 1
        if d.state != S_AIR:
            d.state = S_BLOCK
            d.state_t = 0
            d.stun = h.blockstun
        else:
            d.stun = h.blockstun
        d.move = None
        push = h.push_block
        if abs(d.x) >= STAGE_HALF - 6 * SUB:
            a.vx = -a.facing * push
        else:
            d.vx = a.facing * push
        d.hitstop = a.hitstop = min(h.hitstop, 8)
        chip = h.damage * h.chip // 100
        if chip:
            d.hp = max(1, d.hp - chip)
        a.meter = min(MAX_METER, a.meter + h.meter_block)
        d.meter = min(MAX_METER, d.meter + h.meter_block // 2)
        if mv is not None:
            a.contact = "block"
            self.last_move_info[a.idx]["adv_block"] = h.blockstun - max(0, mv.total - a.mf)
        self.events.append(("block", d.px, 40, {"idx": d.idx, "spark": h.spark}))

    def _apply_hit(self, a: Fighter, d: Fighter, h: Hit, mv: Move | None, proj: Proj | None = None,
                   thrown: bool = False) -> None:
        in_combo = d.state in (S_HIT, S_HITAIR) or (d.state == S_DOWN and d.state_t < 4)
        if not in_combo:
            d.combo_hits = 0
            d.combo_dmg = 0
            d.combo_scale = h.starter
            d.juggle = 0
        idx = min(d.combo_hits, len(PRORATION) - 1)
        dmg = h.damage * PRORATION[idx] // 100 * d.combo_scale // 100
        dmg = max(dmg, h.damage * MIN_DAMAGE_PERCENT // 100) if h.damage else 0
        dmg = min(dmg, max(0, COMBO_DAMAGE_CAP - d.combo_dmg))
        if self.infinite_health:
            dmg = 0
        d.hp = max(0, d.hp - dmg)
        d.combo_dmg += dmg
        d.combo_hits += 1
        a.combo_best = max(a.combo_best, d.combo_hits)
        airborne = not d.grounded or d.state == S_HITAIR
        d.juggle += h.juggle if airborne else 0
        stun = h.hitstun
        if d.combo_hits > HITSTUN_DECAY_START:
            stun = max(6, stun - HITSTUN_DECAY * (d.combo_hits - HITSTUN_DECAY_START))
        d.move = None
        d.crouch_block = d.crouch_block and not airborne
        if d.hp <= 0:
            d.state, d.state_t = S_KO, 0
            d.vy = 130
            d.vx = a.facing * 40
            d.y = max(d.y, 1)
        elif h.launch or h.knockdown or airborne:
            d.state, d.state_t = S_HITAIR, 0
            lx, ly = h.launch if h.launch else (30, 80)
            if d.juggle > JUGGLE_LIMIT:
                lx, ly = 10, 20
            d.vx = a.facing * lx
            d.vy = max(ly, 20) if not airborne else ly
            d.y = max(d.y, 1)
            d.knockdown = True
        else:
            d.state, d.state_t = S_HIT, 0
            d.stun = stun
            if abs(d.x) >= STAGE_HALF - 6 * SUB:
                a.vx = -a.facing * h.push_hit
                d.vx = 0
            else:
                d.vx = a.facing * h.push_hit
        stop = h.hitstop
        a.hitstop = d.hitstop = stop
        a.meter = min(MAX_METER, a.meter + h.meter_hit)
        d.meter = min(MAX_METER, d.meter + h.meter_hit // 2)
        if mv is not None:
            a.contact = "hit"
            self.last_move_info[a.idx]["adv_hit"] = stun - max(0, mv.total - a.mf)
        self.events.append(("hit", d.px, 45 + (d.y // SUB), {"idx": d.idx, "spark": h.spark, "damage": dmg,
                                                           "combo": d.combo_hits, "heavy": h.damage >= 60}))

    # ------------------------------------------------------------------ after-step bookkeeping
    def _after(self) -> None:
        for f in self.fighters:
            if self.training and f.hp < f.char.health and self.infinite_health:
                f.hp = f.char.health
            if self.infinite_meter:
                f.meter = MAX_METER
        a, b = self.fighters
        if self.phase == "fight":
            if a.hp <= 0 or b.hp <= 0:
                if a.hp <= 0 and b.hp <= 0:
                    self._end_round(-1)
                else:
                    self._end_round(1 if a.hp <= 0 else 0)
            elif not self.training:
                if a.hitstop == 0 and b.hitstop == 0:
                    self.timer -= 1
                if self.timer <= 0:
                    pa, pb = a.hp * 1000 // a.char.health, b.hp * 1000 // b.char.health
                    self._end_round(-1 if pa == pb else (0 if pa > pb else 1))
        # combo counters reset when the victim recovers
        for f in self.fighters:
            if f.state not in (S_HIT, S_HITAIR, S_DOWN) and f.combo_hits and f.state != S_BLOCK:
                f.combo_hits = 0 if f.state in ACTIONABLE else f.combo_hits
        # training: auto-heal when idle
        if self.training:
            for f in self.fighters:
                if f.state in ACTIONABLE and f.hp < f.char.health and self.infinite_health:
                    f.hp = f.char.health

    # ------------------------------------------------------------------ queries / hashing
    def state_hash(self) -> str:
        h = hashlib.blake2b(digest_size=8)
        h.update(repr((self.frame, self.phase, self.wins, self.timer, [f.snapshot() for f in self.fighters],
                       [(p.owner, p.x, p.y, p.life) for p in self.projs],
                       [(z.owner, z.x, z.life) for z in self.zones])).encode())
        return h.hexdigest()

    def hit_confirm(self, idx: int) -> bool:
        return self.fighters[idx].contact == "hit"
