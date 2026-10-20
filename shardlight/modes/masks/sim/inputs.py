"""Per-player input buffer and motion recognition (pure, integer-only, facing-relative).

The buffer stores one bitmask per simulation frame.  Moves are matched against the history:
 * buttons need a press edge within ``BUFFER_FRAMES`` (6) frames; multi-button presses need all edges within
   ``SIMUL_FRAMES`` of each other;
 * motions (quarter circle, dragon punch, half circle, double quarter circle, charge, taps) must finish within
   ``MOTION_FRAMES`` and end near the button press, with diagonal leniency (a 6 is satisfied by 9/3, etc.);
 * negative edge (release of a held button) can optionally trigger specials.
"""
from __future__ import annotations

from .consts import (BUFFER_FRAMES, CHARGE_FRAMES, CHARGE_GRACE, DOWN, HISTORY, LEFT, MOTION_FRAMES, RIGHT,
                     SIMUL_FRAMES, UP, ATTACKS, LP, MP, HP, PAR, DASHF, DASHB)

BUTTON_BITS = (LP, MP, HP, PAR, DASHF, DASHB)

# numpad directions that satisfy a required numpad direction
_SAT = {1: {1}, 2: {1, 2, 3}, 3: {3}, 4: {1, 4, 7}, 5: {5}, 6: {3, 6, 9}, 7: {7}, 8: {7, 8, 9}, 9: {9}}
_CHARGE_DIR = {4: "b", 6: "f", 2: "d", 8: "u"}


def numpad(mask: int, facing: int) -> int:
    """Facing-relative numpad direction (1-9, 5 = neutral); 6 is always toward the opponent.

    Opposing directions cancel to neutral, except that up beats down (jump priority)."""
    left, right = bool(mask & LEFT), bool(mask & RIGHT)
    if left and right:
        left = right = False
    up, down = bool(mask & UP), bool(mask & DOWN)
    if up and down:
        down = False
    fwd = right if facing > 0 else left
    back = left if facing > 0 else right
    x = 1 if fwd else -1 if back else 0
    y = 1 if up else -1 if down else 0
    return {(-1, -1): 1, (0, -1): 2, (1, -1): 3, (-1, 0): 4, (0, 0): 5, (1, 0): 6, (-1, 1): 7, (0, 1): 8,
            (1, 1): 9}[(x, y)]


class InputBuffer:
    """Everything about one player's recent input.  ``frame`` counts pushes (age 0 = most recent frame)."""

    def __init__(self) -> None:
        self.hist: list[int] = []
        self.frame = 0
        self.press: dict[int, list[int]] = {b: [] for b in BUTTON_BITS}
        self.release: dict[int, list[int]] = {b: [] for b in BUTTON_BITS}
        self.consumed: dict[int, int] = {b: -1 for b in BUTTON_BITS}
        self.dir_press: dict[int, list[int]] = {LEFT: [], RIGHT: [], DOWN: [], UP: []}
        self.charge = {"b": 0, "f": 0, "d": 0, "u": 0}
        self.ready_until = {"b": -1, "f": -1, "d": -1, "u": -1}
        self.neg_edge = False

    # -- feeding ---------------------------------------------------------------------------
    def push(self, mask: int, facing: int) -> None:
        prev = self.hist[-1] if self.hist else 0
        self.hist.append(mask)
        if len(self.hist) > HISTORY:
            del self.hist[0]
        self.frame += 1
        for b in BUTTON_BITS:
            if mask & b and not prev & b:
                self.press[b].append(self.frame)
                del self.press[b][:-8]
            elif prev & b and not mask & b:
                self.release[b].append(self.frame)
                del self.release[b][:-8]
        for d in self.dir_press:
            if mask & d and not prev & d:
                self.dir_press[d].append(self.frame)
                del self.dir_press[d][:-6]
        n = numpad(mask, facing)
        held = {"b": n in (1, 4, 7), "f": n in (3, 6, 9), "d": n in (1, 2, 3), "u": n in (7, 8, 9)}
        for k, on in held.items():
            if on:
                self.charge[k] += 1
                if self.charge[k] >= CHARGE_FRAMES:
                    self.ready_until[k] = self.frame + BUFFER_FRAMES + CHARGE_GRACE
            elif self.frame > self.ready_until[k] and self.charge[k] and self.frame - self._last_held(k) > CHARGE_GRACE:
                self.charge[k] = 0
        self._held_frame = getattr(self, "_held_frame", {})
        for k, on in held.items():
            if on:
                self._held_frame[k] = self.frame

    def _last_held(self, k: str) -> int:
        return getattr(self, "_held_frame", {}).get(k, -999)

    # -- queries ---------------------------------------------------------------------------
    def dir_at(self, age: int, facing: int) -> int:
        if age >= len(self.hist):
            return 5
        return numpad(self.hist[-1 - age], facing)

    def _events(self, bit: int, within: int, neg: bool) -> list[int]:
        """Frames-ago of unconsumed press (and optionally release) events of ``bit`` within ``within``."""
        out = []
        for f in self.press[bit]:
            if f > self.consumed[bit] and self.frame - f <= within:
                out.append(self.frame - f)
        if neg:
            for f in self.release[bit]:
                if f > self.consumed[bit] and self.frame - f <= within:
                    out.append(self.frame - f)
        return out

    def button_age(self, bits: int, neg: bool = False, within: int = BUFFER_FRAMES) -> int | None:
        """Age (frames ago) of the latest press of the button combination ``bits`` or None."""
        ages = []
        for b in BUTTON_BITS:
            if not bits & b:
                continue
            ev = self._events(b, within + SIMUL_FRAMES, neg)
            if not ev:
                return None
            ages.append(ev)
        if not ages:
            return None
        if len(ages) == 1:
            best = min(ages[0])
            return best if best <= within else None
        # all buttons must have an event within SIMUL_FRAMES of each other
        for a0 in sorted(ages[0]):
            pick = [a0]
            for other in ages[1:]:
                near = [a for a in other if abs(a - a0) <= SIMUL_FRAMES]
                if not near:
                    break
                pick.append(min(near, key=lambda a: abs(a - a0)))
            else:
                latest = min(pick)
                if latest <= within:
                    return latest
        return None

    def held(self, bit: int) -> bool:
        return bool(self.hist and self.hist[-1] & bit)

    def consume(self, bits: int) -> None:
        for b in BUTTON_BITS:
            if bits & b:
                self.consumed[b] = self.frame

    def motion_ok(self, motion: tuple[str, object], facing: int, age: int) -> bool:
        """Does the history contain ``motion`` finishing at the button press ``age`` frames ago?"""
        kind, arg = motion
        if kind == "none":
            return True
        if kind == "hold":
            d = self.dir_at(age, facing)
            if arg == 5:
                return d == 5
            return d in _SAT[int(arg)]
        if kind == "charge":
            back_key, press_dir = _CHARGE_DIR[arg[0]], arg[1]
            if self.ready_until[back_key] < self.frame - age:
                return False
            d = self.dir_at(age, facing)
            return d in _SAT[press_dir] or self.dir_at(max(0, age - 1), facing) in _SAT[press_dir]
        seq = list(arg)
        if seq == [6, 2, 3]:      # dragon punch accepts the 6-3 shortcut
            return self._seq(seq, facing, age) or self._seq([6, 3], facing, age)
        return self._seq(seq, facing, age)

    def _seq(self, seq: list[int], facing: int, age: int) -> bool:
        start = max(0, age - 2)          # the final direction may land up to 2 frames after the button
        limit = min(len(self.hist) - 1, age + MOTION_FRAMES)
        pos = start
        first_age = None
        for want in reversed(seq):
            a = pos
            while a <= limit and self.dir_at(a, facing) not in _SAT[want]:
                a += 1
            if a > limit:
                return False
            if first_age is None:
                first_age = a
            pos = a + 1
        return pos - 1 - (first_age or 0) <= MOTION_FRAMES

    def double_tap(self, forward: bool, facing: int) -> bool:
        """Was the forward (or back) direction tapped twice, the second tap within the buffer window?"""
        bit = (RIGHT if facing > 0 else LEFT) if forward else (LEFT if facing > 0 else RIGHT)
        pr = [f for f in self.dir_press[bit] if f > self.consumed_dir(bit)]
        if len(pr) < 2:
            return False
        last, prev = pr[-1], pr[-2]
        if not (self.frame - last <= BUFFER_FRAMES - 2 and 2 <= last - prev <= 14):
            return False
        # both taps must be plain horizontal taps: a 2-3-6 motion contains forward presses that are not a dash
        for fr in (last, prev):
            idx = len(self.hist) - 1 - (self.frame - fr)
            if 0 <= idx < len(self.hist) and self.hist[idx] & (UP | DOWN):
                return False
        return True

    def consumed_dir(self, bit: int) -> int:
        return getattr(self, "_dir_consumed", {}).get(bit, -1)

    def consume_dir(self, forward: bool, facing: int) -> None:
        bit = (RIGHT if facing > 0 else LEFT) if forward else (LEFT if facing > 0 else RIGHT)
        if not hasattr(self, "_dir_consumed"):
            self._dir_consumed = {}
        self._dir_consumed[bit] = self.frame

    def use_charge(self, key: str) -> None:
        self.charge[key] = 0
        self.ready_until[key] = -1

    def snapshot(self) -> tuple:
        """Tuple of ints for state hashing."""
        return (self.frame, tuple(self.hist[-12:]), tuple(self.charge.values()))
