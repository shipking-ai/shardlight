"""Plain data model of a campaign: map, provinces, armies, houses.  Everything serialises to JSON dicts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schemas import RESOURCES


def pair(a: Any, b: Any) -> tuple:
    """Canonical unordered pair key."""
    return (a, b) if a <= b else (b, a)


# ------------------------------------------------------------------------------------------------- map
@dataclass
class Province:
    id: int
    col: int
    row: int
    terrain: str
    name: str
    base: dict[str, int] = field(default_factory=dict)       # raw yields per turn
    feature: str | None = None                                # inkwell | saltpan | None
    choke: bool = False
    owner: str | None = None
    home: str | None = None                                   # culture: the house that first held it
    buildings: dict[str, int] = field(default_factory=dict)  # building id -> level
    queue: list[dict] = field(default_factory=list)          # [{"b": id, "left": turns, "lvl": level}]
    unrest: float = 0.0
    devastation: float = 0.0
    conquered: int = 0                                        # turns since last conquest (0 = none recent)
    wall_damage: float = 0.0                                  # recovers slowly after a siege

    def to_dict(self) -> dict:
        return {"id": self.id, "col": self.col, "row": self.row, "terrain": self.terrain, "name": self.name,
                "base": dict(self.base), "feature": self.feature, "choke": self.choke, "owner": self.owner,
                "home": self.home, "buildings": dict(self.buildings), "queue": [dict(q) for q in self.queue],
                "unrest": self.unrest, "devastation": self.devastation,
                "conquered": self.conquered, "wall_damage": self.wall_damage}

    @classmethod
    def from_dict(cls, d: dict) -> "Province":
        return cls(d["id"], d["col"], d["row"], d["terrain"], d["name"], dict(d.get("base", {})), d.get("feature"),
                   bool(d.get("choke")), d.get("owner"), d.get("home"), dict(d.get("buildings", {})),
                   [dict(q) for q in d.get("queue", [])], float(d.get("unrest", 0)), float(d.get("devastation", 0)),
                   int(d.get("conquered", 0)), float(d.get("wall_damage", 0)))


@dataclass
class MapData:
    cols: int
    rows: int
    provinces: list[Province]
    adj: list[list[int]]                                      # neighbour province ids, hex direction order
    adj_dir: list[dict[int, int]]                             # province -> {neighbour: direction index}
    roads: set[tuple[int, int]] = field(default_factory=set)
    rivers: set[tuple[int, int]] = field(default_factory=set)
    capitals: dict[str, int] = field(default_factory=dict)

    def road(self, a: int, b: int) -> bool:
        return pair(a, b) in self.roads

    def river(self, a: int, b: int) -> bool:
        return pair(a, b) in self.rivers

    def to_dict(self) -> dict:
        return {"cols": self.cols, "rows": self.rows, "provinces": [p.to_dict() for p in self.provinces],
                "roads": sorted([list(e) for e in self.roads]), "rivers": sorted([list(e) for e in self.rivers]),
                "capitals": dict(self.capitals)}

    @classmethod
    def from_dict(cls, d: dict) -> "MapData":
        from . import hexgrid
        provs = [Province.from_dict(p) for p in d["provinces"]]
        index = {(p.col, p.row): p.id for p in provs}
        adj: list[list[int]] = []
        adj_dir: list[dict[int, int]] = []
        for p in provs:
            ns, dirs = [], {}
            for i, (c, r) in enumerate(hexgrid.neighbors(p.col, p.row)):
                nid = index.get((c, r))
                if nid is not None:
                    ns.append(nid)
                    dirs[nid] = i
            adj.append(ns)
            adj_dir.append(dirs)
        return cls(d["cols"], d["rows"], provs, adj, adj_dir, {tuple(e) for e in d["roads"]},
                   {tuple(e) for e in d["rivers"]}, dict(d["capitals"]))


# ------------------------------------------------------------------------------------------------ armies
@dataclass
class Unit:
    uid: int
    type: str
    hp: float
    xp: int = 0

    @property
    def rank(self) -> int:
        return min(3, self.xp // 3)

    def to_dict(self) -> dict:
        return {"uid": self.uid, "type": self.type, "hp": self.hp, "xp": self.xp}

    @classmethod
    def from_dict(cls, d: dict) -> "Unit":
        return cls(d["uid"], d["type"], float(d["hp"]), int(d.get("xp", 0)))


@dataclass
class Army:
    id: int
    owner: str
    pid: int
    units: list[Unit] = field(default_factory=list)
    path: list[int] = field(default_factory=list)             # remaining provinces to enter, in order
    stance: str = "march"                                     # march | raid | pillage
    prev: int | None = None                                   # province it came from (retreat target)
    name: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "owner": self.owner, "pid": self.pid, "units": [u.to_dict() for u in self.units],
                "path": list(self.path), "stance": self.stance, "prev": self.prev, "name": self.name}

    @classmethod
    def from_dict(cls, d: dict) -> "Army":
        return cls(d["id"], d["owner"], d["pid"], [Unit.from_dict(u) for u in d["units"]], list(d.get("path", [])),
                   d.get("stance", "march"), d.get("prev"), d.get("name", ""))


# ------------------------------------------------------------------------------------------------ houses
@dataclass
class House:
    id: str
    stock: dict[str, float] = field(default_factory=dict)
    techs: list[str] = field(default_factory=list)
    research: str | None = None
    progress: float = 0.0
    alive: bool = True
    is_player: bool = False
    capital: int = -1
    exhaustion: float = 0.0
    oath: float = 0.0                                         # oathbreaker reputation (0..100), decays
    explored: set[int] = field(default_factory=set)           # provinces whose terrain this house has seen
    memory: dict[int, dict] = field(default_factory=dict)     # last seen state of provinces (fog of war)
    scouted: dict[int, int] = field(default_factory=dict)     # province -> turn the scouting reveal expires
    claims: dict[str, int] = field(default_factory=dict)      # target house -> turn the fabricated claim expires
    unjust_until: int = 0                                     # unrest from an unjust war lasts until this turn
    eliminated_turn: int | None = None
    ai: dict[str, Any] = field(default_factory=dict)          # planner memory (posture, targets, cooldowns)
    stats: dict[str, float] = field(default_factory=dict)     # lifetime counters for summaries

    def to_dict(self) -> dict:
        return {"id": self.id, "stock": {k: v for k, v in self.stock.items()}, "techs": list(self.techs),
                "research": self.research, "progress": self.progress, "alive": self.alive,
                "is_player": self.is_player, "capital": self.capital, "exhaustion": self.exhaustion,
                "oath": self.oath, "explored": sorted(self.explored),
                "memory": {str(k): v for k, v in self.memory.items()},
                "scouted": {str(k): v for k, v in self.scouted.items()}, "claims": dict(self.claims),
                "unjust_until": self.unjust_until, "eliminated_turn": self.eliminated_turn,
                "ai": _jsonable(self.ai), "stats": dict(self.stats)}

    @classmethod
    def from_dict(cls, d: dict) -> "House":
        h = cls(d["id"], {k: float(v) for k, v in d["stock"].items()}, list(d.get("techs", [])), d.get("research"),
                float(d.get("progress", 0)), bool(d.get("alive", True)), bool(d.get("is_player")),
                int(d.get("capital", -1)), float(d.get("exhaustion", 0)), float(d.get("oath", 0)))
        h.explored = set(d.get("explored", []))
        h.memory = {int(k): v for k, v in d.get("memory", {}).items()}
        h.scouted = {int(k): int(v) for k, v in d.get("scouted", {}).items()}
        h.claims = {k: int(v) for k, v in d.get("claims", {}).items()}
        h.unjust_until = int(d.get("unjust_until", 0))
        h.eliminated_turn = d.get("eliminated_turn")
        h.ai = _unjson(d.get("ai", {}))
        h.stats = {k: float(v) for k, v in d.get("stats", {}).items()}
        return h

    def can_afford(self, cost: dict[str, float]) -> bool:
        return all(self.stock.get(r, 0) + 1e-9 >= c for r, c in cost.items())

    def pay(self, cost: dict[str, float]) -> None:
        for r, c in cost.items():
            self.stock[r] = self.stock.get(r, 0) - c

    def gain(self, amounts: dict[str, float]) -> None:
        for r, c in amounts.items():
            self.stock[r] = self.stock.get(r, 0) + c


def empty_stock() -> dict[str, float]:
    return {r: 0.0 for r in RESOURCES}


def _jsonable(v: Any) -> Any:
    """Convert sets/tuples and int-keyed dicts to JSON-safe structures (tagged so they round-trip)."""
    if isinstance(v, dict):
        return {"__d": [[_jsonable(k), _jsonable(x)] for k, x in v.items()]}
    if isinstance(v, (set, frozenset)):
        return {"__s": [_jsonable(x) for x in sorted(v, key=str)]}
    if isinstance(v, tuple):
        return {"__t": [_jsonable(x) for x in v]}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _unjson(v: Any) -> Any:
    if isinstance(v, dict):
        if "__d" in v:
            return {_unjson(k): _unjson(x) for k, x in v["__d"]}
        if "__s" in v:
            return {_unjson(x) for x in v["__s"]}
        if "__t" in v:
            return tuple(_unjson(x) for x in v["__t"])
        return {k: _unjson(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unjson(x) for x in v]
    return v
