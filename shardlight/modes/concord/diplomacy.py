"""Diplomacy between houses: relations, treaties, opinion, claims and the price of breaking your word.

Every house (player or AI) is bound by the same rules.  Whether an AI accepts a proposal is a transparent score
the player can read (``assess``): opinion, shared enemies, relative strength, the proposer's oath record and the
AI's own personality all contribute and each term is reported back as a reason.

Pure logic: no pygame.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .state import pair

STATUSES = ("peace", "war")
TREATIES = ("trade", "pact", "alliance")
TREATY_LABEL = {"trade": "Trade pact", "pact": "Non-aggression pact", "alliance": "Alliance"}
PEACE_TRUCE = 6                      # turns after a peace during which neither side can declare war without penalty
TREATY_LENGTH = {"trade": 24, "pact": 20, "alliance": 40}


@dataclass
class Diplomacy:
    houses: list[str]
    wars: dict[tuple, int] = field(default_factory=dict)             # pair -> turn the war began
    treaties: dict[tuple, dict] = field(default_factory=dict)        # pair -> {"kind": {"since": t, "until": t}}
    opinion: dict[str, dict[str, float]] = field(default_factory=dict)
    truce: dict[tuple, int] = field(default_factory=dict)            # pair -> turn the truce ends
    grievance: dict[tuple, float] = field(default_factory=dict)      # (wronged, wrongdoer) -> strength 0..1
    history: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        for h in self.houses:
            self.opinion.setdefault(h, {})
            for o in self.houses:
                if o != h:
                    self.opinion[h].setdefault(o, 0.0)

    # ------------------------------------------------------------------ queries
    def at_war(self, a: str, b: str) -> bool:
        return a != b and pair(a, b) in self.wars

    def treaty(self, a: str, b: str, kind: str) -> bool:
        return kind in self.treaties.get(pair(a, b), {})

    def allied(self, a: str, b: str) -> bool:
        return self.treaty(a, b, "alliance")

    def has_pact(self, a: str, b: str) -> bool:
        return self.treaty(a, b, "pact") or self.treaty(a, b, "alliance")

    def trade_partners(self, h: str) -> list[str]:
        return [o for o in self.houses if o != h and self.treaty(h, o, "trade")]

    def enemies_of(self, h: str) -> list[str]:
        return [o for o in self.houses if self.at_war(h, o)]

    def allies_of(self, h: str) -> list[str]:
        return [o for o in self.houses if self.allied(h, o)]

    def friendly(self, a: str, b: str) -> bool:
        return a == b or self.allied(a, b)

    def can_pass(self, mover: str, owner: str | None) -> bool:
        """May ``mover`` armies enter provinces owned by ``owner``?"""
        if owner is None or owner == mover:
            return True
        return self.at_war(mover, owner) or self.allied(mover, owner)

    def opinion_of(self, a: str, b: str) -> float:
        return self.opinion.get(a, {}).get(b, 0.0)

    def shift(self, a: str, b: str, delta: float) -> None:
        """``a``'s opinion of ``b`` changes by ``delta`` (clamped to +-100)."""
        o = self.opinion.setdefault(a, {})
        o[b] = max(-100.0, min(100.0, o.get(b, 0.0) + delta))

    def state_text(self, a: str, b: str) -> str:
        if self.at_war(a, b):
            return "War"
        for k in ("alliance", "pact", "trade"):
            if self.treaty(a, b, k):
                return TREATY_LABEL[k]
        if self.truce.get(pair(a, b), 0) > 0:
            return "Truce"
        return "Peace"

    # ------------------------------------------------------------------ war and peace
    def declare_war(self, a: str, b: str, turn: int) -> None:
        k = pair(a, b)
        self.wars[k] = turn
        for t in list(self.treaties.get(k, {})):
            del self.treaties[k][t]
        self.treaties.pop(k, None)
        self.shift(b, a, -25)
        self.shift(a, b, -10)
        for o in self.houses:                                         # allies of the victim sour on the aggressor
            if o not in (a, b) and self.allied(o, b):
                self.shift(o, a, -12)
        self.history.append({"turn": turn, "kind": "war", "a": a, "b": b})

    def make_peace(self, a: str, b: str, turn: int) -> None:
        k = pair(a, b)
        self.wars.pop(k, None)
        self.truce[k] = turn + PEACE_TRUCE
        self.shift(a, b, 8)
        self.shift(b, a, 8)
        self.history.append({"turn": turn, "kind": "peace", "a": a, "b": b})

    def sign(self, a: str, b: str, kind: str, turn: int) -> None:
        k = pair(a, b)
        t = self.treaties.setdefault(k, {})
        if kind == "alliance":
            t.pop("pact", None)
        t[kind] = {"since": turn, "until": turn + TREATY_LENGTH[kind]}
        self.shift(a, b, 6)
        self.shift(b, a, 6)
        self.history.append({"turn": turn, "kind": kind, "a": a, "b": b})

    def break_treaty(self, breaker: str, other: str, kind: str, turn: int) -> float:
        """Tear up a treaty.  Returns the oath penalty the breaker suffers (the caller applies it to the house)."""
        k = pair(breaker, other)
        t = self.treaties.get(k, {})
        if kind not in t:
            return 0.0
        del t[kind]
        if not t:
            self.treaties.pop(k, None)
        self.shift(other, breaker, -35 if kind != "trade" else -10)
        self.history.append({"turn": turn, "kind": "break_" + kind, "a": breaker, "b": other})
        return {"trade": 6.0, "pact": 22.0, "alliance": 30.0}[kind]

    def tick(self, turn: int) -> list[dict]:
        """Per-turn upkeep: treaties expire, opinions drift to neutral, truces end.  Returns expiry notices."""
        notes = []
        for k in list(self.treaties):
            for kind in list(self.treaties[k]):
                if self.treaties[k][kind]["until"] <= turn:
                    del self.treaties[k][kind]
                    notes.append({"kind": "expired", "treaty": kind, "a": k[0], "b": k[1]})
            if not self.treaties[k]:
                del self.treaties[k]
        for k in list(self.truce):
            if self.truce[k] <= turn:
                del self.truce[k]
        for a in self.houses:
            for b in self.houses:
                if a == b:
                    continue
                v = self.opinion[a][b]
                drift = 0.6 if abs(v) > 1 else 0.0
                v -= drift if v > 0 else -drift
                if self.at_war(a, b):
                    v -= 1.0
                if self.allied(a, b):
                    v += 0.8
                elif self.treaty(a, b, "trade"):
                    v += 0.4
                self.opinion[a][b] = max(-100.0, min(100.0, v))
        for k in list(self.grievance):
            self.grievance[k] = max(0.0, self.grievance[k] - 0.04)
            if self.grievance[k] <= 0:
                del self.grievance[k]
        return notes

    def add_grievance(self, wronged: str, wrongdoer: str, amount: float) -> None:
        k = (wronged, wrongdoer)
        self.grievance[k] = min(1.0, self.grievance.get(k, 0.0) + amount)

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"houses": list(self.houses), "wars": [[list(k), v] for k, v in sorted(self.wars.items())],
                "treaties": [[list(k), {t: dict(v) for t, v in tr.items()}] for k, tr in sorted(self.treaties.items())],
                "opinion": {a: {b: v for b, v in d.items()} for a, d in self.opinion.items()},
                "truce": [[list(k), v] for k, v in sorted(self.truce.items())],
                "grievance": [[list(k), v] for k, v in sorted(self.grievance.items())],
                "history": self.history[-60:]}

    @classmethod
    def from_dict(cls, d: dict) -> "Diplomacy":
        dp = cls(list(d["houses"]))
        dp.wars = {tuple(k): int(v) for k, v in d["wars"]}
        dp.treaties = {tuple(k): {t: dict(v) for t, v in tr.items()} for k, tr in d["treaties"]}
        dp.opinion = {a: {b: float(v) for b, v in x.items()} for a, x in d["opinion"].items()}
        dp.truce = {tuple(k): int(v) for k, v in d["truce"]}
        dp.grievance = {tuple(k): float(v) for k, v in d["grievance"]}
        dp.history = list(d.get("history", []))
        return dp


# --------------------------------------------------------------------------------------------- assessment
@dataclass
class Assessment:
    score: float
    accept: bool
    reasons: list[tuple[str, float]]

    def text(self) -> str:
        return ", ".join(f"{n} {v:+.0f}" for n, v in self.reasons if abs(v) >= 1)


def assess(dp: Diplomacy, proposer: str, target: str, kind: str, personality: dict[str, float], proposer_oath: float,
           power_ratio: float, shared_enemies: int, diplo_bonus: float = 0.0, target_is_losing: bool = False,
           target_exhaustion: float = 0.0) -> Assessment:
    """Would ``target`` (an AI house with ``personality``) accept ``kind`` from ``proposer``?

    ``kind`` is ``peace``, ``trade``, ``pact`` or ``alliance``.  ``power_ratio`` is proposer power / target power.
    """
    reasons: list[tuple[str, float]] = []
    op = dp.opinion_of(target, proposer)
    reasons.append(("opinion", op * 0.6))
    reasons.append(("your word", -proposer_oath * (0.9 if kind in ("pact", "alliance") else 0.5)))
    if diplo_bonus:
        reasons.append(("envoys", diplo_bonus))
    honor = personality.get("honor", 0.5)
    reasons.append(("their honor", (honor - 0.5) * 10))
    if kind == "peace":
        reasons.append(("war weariness", target_exhaustion * 0.9))
        reasons.append(("pressure", 8 * (power_ratio - 1.0)))
        if target_is_losing:
            reasons.append(("losing", 12))
        reasons.append(("their aggression", -(personality.get("aggression", 0.5) - 0.5) * 24))
        if dp.grievance.get((target, proposer), 0) > 0:
            reasons.append(("grievance", -dp.grievance[(target, proposer)] * 30))
        need = 4
    elif kind == "trade":
        reasons.append(("their commerce", (personality.get("commerce", 0.5) - 0.4) * 28))
        need = 5
    elif kind == "pact":
        reasons.append(("their caution", (personality.get("caution", 0.5) - 0.4) * 18))
        reasons.append(("their expansion", -(personality.get("expansion", 0.5) - 0.5) * 12))
        reasons.append(("strength", 4 * (power_ratio - 1.0)))
        need = 14
    else:
        reasons.append(("shared enemies", 7.0 * shared_enemies))
        reasons.append(("their grudge", -(personality.get("grudge", 0.5) - 0.4) * 8))
        reasons.append(("their ambition", -(personality.get("expansion", 0.5) - 0.5) * 14))
        need = 30
    score = sum(v for _, v in reasons)
    return Assessment(score, score >= need, reasons)
