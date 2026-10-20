"""Signals: detection by bearing, triangulation on the galaxy map, and the decoding deduction puzzles.

Geometry works on a plain list of ``(x, y)`` system positions so the galaxy generator can use it before a
``Galaxy`` object exists.  Puzzles are pure functions of ``(galaxy seed, signal id)``; only the player's progress
(probes, slot choices, hints used) is saved.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from ...core.rng import Rng, derive_seed

BASE_ERR = 7.0          # degrees of bearing error with a stock receiver
TONES = ["Ring", "Gear", "Lens", "Pin", "Spire", "Eye", "Cog", "Bell"]
TONE_CH = ["R", "G", "L", "P", "S", "E", "C", "B"]


# ------------------------------------------------------------------------------------- geometry
def bearing_deg(ax: float, ay: float, bx: float, by: float) -> float:
    return math.degrees(math.atan2(by - ay, bx - ax)) % 360.0


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def make_reading(positions: list[tuple[float, float]], origin: int, src: int, range_: float, seed: int, sig_id: str,
                 err: float = BASE_ERR) -> dict | None:
    """What the dish hears at ``origin``: a noisy bearing and strength, or ``None`` if out of range.

    The noise is deterministic per (seed, signal, origin) and never exceeds 0.8 * err, so the true bearing is
    always inside the displayed wedge ``bearing +/- err``.
    """
    ox, oy = positions[origin]
    sx, sy = positions[src]
    d = math.hypot(sx - ox, sy - oy)
    if d > range_:
        return None
    rng = Rng(derive_seed(seed, "bearing", sig_id, origin))
    if origin == src:
        return {"origin": origin, "bearing": 0.0, "err": 180.0, "strength": 1.0, "here": True}
    b = bearing_deg(ox, oy, sx, sy) + rng.uniform(-0.8, 0.8) * err
    s = max(0.0, min(1.0, 1.0 - d / range_ + rng.uniform(-0.05, 0.05)))
    return {"origin": origin, "bearing": round(b % 360.0, 2), "err": err, "strength": round(s, 3), "here": False}


def candidates(positions: list[tuple[float, float]], readings: list[dict], range_: float) -> list[int]:
    """Systems consistent with every reading (bearing wedge and signal-strength distance band)."""
    out = []
    for c, (cx, cy) in enumerate(positions):
        ok = True
        for r in readings:
            ox, oy = positions[r["origin"]]
            if r.get("here"):
                ok = c == r["origin"]
                if not ok:
                    break
                continue
            if c == r["origin"]:
                ok = False
                break
            d = math.hypot(cx - ox, cy - oy)
            est = (1.0 - r["strength"]) * range_
            if abs(d - est) > 0.16 * range_ or d > range_:
                ok = False
                break
            if angle_diff(bearing_deg(ox, oy, cx, cy), r["bearing"]) > r["err"] + 0.5:
                ok = False
                break
        if ok:
            out.append(c)
    return out


def triangulable(positions: list[tuple[float, float]], src: int, range_: float, seed: int, sig_id: str,
                 err: float = BASE_ERR, max_readings: int = 3) -> bool:
    """Is there a way to pin ``src`` down using at most ``max_readings`` listening posts? (greedy search)"""
    sx, sy = positions[src]
    origins = sorted((i for i in range(len(positions)) if i != src and
                      math.hypot(positions[i][0] - sx, positions[i][1] - sy) <= range_),
                     key=lambda i: math.hypot(positions[i][0] - sx, positions[i][1] - sy))[:30]
    if len(origins) < 2:
        return False
    readings: list[dict] = []
    for _ in range(max_readings):
        best, best_n = None, 10 ** 9
        for o in origins:
            if any(r["origin"] == o for r in readings):
                continue
            rd = make_reading(positions, o, src, range_, seed, sig_id, err)
            if rd is None:
                continue
            n = len(candidates(positions, readings + [rd], range_))
            if n < best_n:
                best, best_n = rd, n
        if best is None:
            return False
        readings.append(best)
        if best_n == 1:
            return True
    return False


def best_listening_posts(positions: list[tuple[float, float]], src: int, range_: float, seed: int, sig_id: str,
                         err: float = BASE_ERR, max_readings: int = 3) -> list[int]:
    """The listening posts the greedy solver uses (also handy as a test/solver oracle)."""
    sx, sy = positions[src]
    origins = sorted((i for i in range(len(positions)) if i != src and
                      math.hypot(positions[i][0] - sx, positions[i][1] - sy) <= range_),
                     key=lambda i: math.hypot(positions[i][0] - sx, positions[i][1] - sy))[:30]
    readings: list[dict] = []
    for _ in range(max_readings):
        best, best_n = None, 10 ** 9
        for o in origins:
            if any(r["origin"] == o for r in readings):
                continue
            rd = make_reading(positions, o, src, range_, seed, sig_id, err)
            if rd is None:
                continue
            n = len(candidates(positions, readings + [rd], range_))
            if n < best_n:
                best, best_n = rd, n
        if best is None:
            break
        readings.append(best)
        if best_n == 1:
            break
    return [r["origin"] for r in readings]


# -------------------------------------------------------------------------------------- puzzles
Clue = tuple


def clue_holds(clue: Clue, seq: tuple[int, ...]) -> bool:
    k = clue[0]
    if k == "eq":
        return seq[clue[1]] == clue[2]
    if k == "ne":
        return seq[clue[1]] != clue[2]
    if k == "lt":
        return seq[clue[1]] < seq[clue[2]]
    if k == "same":
        return seq[clue[1]] == seq[clue[2]]
    if k == "diff":
        return seq[clue[1]] != seq[clue[2]]
    if k == "count":
        return seq.count(clue[1]) == clue[2]
    if k == "first_lowest":
        return seq[0] == min(seq)
    if k == "last_highest":
        return seq[-1] == max(seq)
    raise ValueError(k)


def clue_text(clue: Clue) -> str:
    k = clue[0]
    if k == "eq":
        return f"Tone {clue[1] + 1} is the {TONES[clue[2]]}."
    if k == "ne":
        return f"Tone {clue[1] + 1} is not the {TONES[clue[2]]}."
    if k == "lt":
        return f"Tone {clue[1] + 1} sits lower than tone {clue[2] + 1}."
    if k == "same":
        return f"Tones {clue[1] + 1} and {clue[2] + 1} are the same."
    if k == "diff":
        return f"Tones {clue[1] + 1} and {clue[2] + 1} differ."
    if k == "count":
        c = clue[2]
        return f"The {TONES[clue[1]]} sounds {'never' if c == 0 else 'once' if c == 1 else str(c) + ' times'}."
    if k == "first_lowest":
        return "The first tone is the lowest of all."
    if k == "last_highest":
        return "The last tone is the highest of all."
    return "?"


@dataclass
class Puzzle:
    kind: str                     # "sequence" | "lock"
    length: int
    symbols: int
    secret: tuple[int, ...]
    clues: list[Clue]             # sequence puzzles only

    def check(self, guess: tuple[int, ...]) -> bool:
        return tuple(guess) == self.secret


def _all_clues(secret: tuple[int, ...], k: int) -> list[Clue]:
    n = len(secret)
    pool: list[Clue] = []
    for i in range(n):
        pool.append(("eq", i, secret[i]))
        for s in range(k):
            if s != secret[i]:
                pool.append(("ne", i, s))
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if secret[i] < secret[j]:
                pool.append(("lt", i, j))
        for j in range(i + 1, n):
            pool.append(("same", i, j) if secret[i] == secret[j] else ("diff", i, j))
    for s in range(k):
        pool.append(("count", s, secret.count(s)))
    if secret[0] == min(secret):
        pool.append(("first_lowest",))
    if secret[-1] == max(secret):
        pool.append(("last_highest",))
    return pool


def solutions(length: int, symbols: int, clues: list[Clue]) -> list[tuple[int, ...]]:
    return [s for s in itertools.product(range(symbols), repeat=length) if all(clue_holds(c, s) for c in clues)]


def make_puzzle(seed: int, sig_id: str, kind: str, length: int, symbols: int) -> Puzzle:
    """Deterministic puzzle.  Sequence puzzles are generated so the clue list has exactly one solution."""
    rng = Rng(derive_seed(seed, "puzzle", sig_id))
    if kind == "lock":
        base = list(range(symbols))
        rng.shuffle(base)
        return Puzzle("lock", length, symbols, tuple(base[:length]), [])
    secret = tuple(rng.randrange(symbols) for _ in range(length))
    while len(set(secret)) < 3:                      # keep the puzzle interesting
        secret = tuple(rng.randrange(symbols) for _ in range(length))
    pool = _all_clues(secret, symbols)
    rng.shuffle(pool)
    # prefer relational clues first so the answer is deduced rather than read off
    pool.sort(key=lambda c: 0 if c[0] in ("lt", "same", "diff", "count") else 1)
    pool = pool[:len(pool)]
    sols = list(itertools.product(range(symbols), repeat=length))
    chosen: list[Clue] = []
    for c in pool:
        if len(sols) == 1:
            break
        nxt = [s for s in sols if clue_holds(c, s)]
        if len(nxt) <= len(sols) * 0.8:
            chosen.append(c)
            sols = nxt
    if len(sols) != 1:                                # fall back to adding anything still informative
        for c in pool:
            if len(sols) == 1:
                break
            nxt = [s for s in sols if clue_holds(c, s)]
            if len(nxt) < len(sols):
                chosen.append(c)
                sols = nxt
    # prune clues that are not needed for uniqueness
    for c in list(chosen):
        trial = [x for x in chosen if x is not c]
        if len(solutions(length, symbols, trial)) == 1:
            chosen = trial
    chosen.sort(key=lambda c: (c[0], c[1:]))
    return Puzzle("sequence", length, symbols, secret, chosen)


def lock_feedback(secret: tuple[int, ...], guess: tuple[int, ...]) -> tuple[int, int]:
    """(exact, near): right tone in the right slot; right tone in another slot."""
    exact = sum(1 for a, b in zip(secret, guess) if a == b)
    near = 0
    left_s = [a for a, b in zip(secret, guess) if a != b]
    left_g = [b for a, b in zip(secret, guess) if a != b]
    for g in left_g:
        if g in left_s:
            left_s.remove(g)
            near += 1
    return exact, near


def lock_solver(puzzle: Puzzle, limit: int = 20) -> int:
    """Consistent-guess strategy; returns the number of probes needed (used by tests as a solvability oracle)."""
    cand = [s for s in itertools.permutations(range(puzzle.symbols), puzzle.length)]
    probes = 0
    while probes < limit:
        guess = cand[len(cand) // 2]
        probes += 1
        fb = lock_feedback(puzzle.secret, guess)
        if fb[0] == puzzle.length:
            return probes
        cand = [c for c in cand if lock_feedback(c, guess) == fb]
    return probes
