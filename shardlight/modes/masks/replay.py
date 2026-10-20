"""Replay storage and verification.  A replay is (characters, seed, rules, run-length encoded input log) plus the
final state hash; playback re-simulates and must reproduce the hash exactly (the sim is deterministic)."""
from __future__ import annotations

from .sim.fight import Match
from .sim.moves import Character


def encode(log: list[tuple[int, int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in log:
        if out and out[-1][0] == a and out[-1][1] == b:
            out[-1][2] += 1
        else:
            out.append([a, b, 1])
    return out


def decode(rle: list[list[int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b, n in rle:
        out.extend([(a, b)] * n)
    return out


def make_record(m: Match, ids: tuple[str, str]) -> dict:
    return {"v": 1, "chars": list(ids), "seed": m.seed, "rounds": m.rounds_to_win, "round_frames": m.round_frames,
            "frames": len(m.log), "wins": list(m.wins), "hash": m.state_hash(), "rle": encode(m.log)}


def valid_record(r) -> bool:
    try:
        return (isinstance(r, dict) and r.get("v") == 1 and len(r["chars"]) == 2 and isinstance(r["rle"], list)
                and all(len(x) == 3 and all(isinstance(v, int) for v in x) for x in r["rle"])
                and sum(x[2] for x in r["rle"]) == r["frames"] and r["frames"] < 60 * 60 * 15)
    except (KeyError, TypeError):
        return False


def rebuild(r: dict, roster: dict[str, Character]) -> Match | None:
    if not valid_record(r) or any(c not in roster for c in r["chars"]):
        return None
    return Match((roster[r["chars"][0]], roster[r["chars"][1]]), seed=r["seed"], rounds=r["rounds"],
                 round_frames=r["round_frames"])


def verify(r: dict, roster: dict[str, Character]) -> bool:
    """Re-simulate the whole replay and compare the final state hash."""
    m = rebuild(r, roster)
    if m is None:
        return False
    for pair in decode(r["rle"]):
        m.step(pair)
    return m.state_hash() == r["hash"]
