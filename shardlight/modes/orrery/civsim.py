"""Civilisation and economy simulation on a coarse daily timestep, with level of detail.

One *day* is the unit.  Every colony has a market (stock, price, production, consumption, industry).  Surplus is
shipped by convoys along hyperlanes to deficit markets (price driven), civs research, expand, quarrel, wage war
with fleets and blockades, and sign peace.  Everything is deterministic from ``(galaxy seed, day, ids)``.

Level of detail: markets inside the *fine* set (near the player) tick every day; the rest accumulate days and tick
in batches of ``BATCH`` days with the very same function (rates scaled by the batch length) and expected-value
pirate losses, so far-away systems are cheap but statistically equivalent.

Ledger identity (checked by tests), per good ``g``::

    sum(stock) + in-transit + player cargo moved in  ==  initial + produced - consumed - lost + player net

"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from ...core.rng import Rng, derive_seed
from .defs import Defs
from .galaxy import Galaxy

DAY_SECONDS = 24.0
BATCH = 6                    # days per batch for distant markets
FINE_HOPS = 2                # systems within this many lanes of the player are simulated daily
PROD_PER_POINT = 1.4
CONVOY_SPEED = 42.0          # lane length units per day
MAX_CONVOYS = 160
CONS_PER_POP = {"food": 0.7, "water": 0.4, "fuel": 0.3, "alloy": 0.07, "gearwork": 0.03, "lumen": 0.025}
PRICE_LO, PRICE_HI = 0.4, 4.5
SPREAD = 0.05

REL_STATES = (("alliance", 70), ("friendly", 25), ("neutral", -25), ("hostile", -9999))


def _pair(a: str, b: str) -> str:
    return f"{a}|{b}" if a < b else f"{b}|{a}"


@dataclass
class Market:
    sid: int
    owner: str | None
    size: float
    cap: float
    base_prod: list[float]               # richness points per good (raw only)
    stock: list[float]
    price: list[float]
    industry: list[float]                # capacity per day per good (made goods)
    pending: int = 0                     # days owed (LOD batch)
    defense: float = 1.0
    blockaded_by: str | None = None
    siege: int = 0
    shortage: float = 0.0                # 0..1 how starved the colony is right now
    need: list[float] = field(default_factory=list)
    founded: int = 0
    efficiency: float = 1.0

    def to_dict(self) -> dict:
        return {"sid": self.sid, "owner": self.owner, "size": self.size, "cap": self.cap, "stock": self.stock,
                "price": self.price, "industry": self.industry, "pending": self.pending, "defense": self.defense,
                "blockaded_by": self.blockaded_by, "siege": self.siege, "shortage": self.shortage,
                "founded": self.founded, "efficiency": self.efficiency}


@dataclass
class Convoy:
    id: int
    owner: str | None
    gi: int
    amt: float
    path: list[int]
    leg: int                 # index into path of the node currently travelled TO
    t_depart: float
    t_arrive: float
    hold: int = 0

    def to_dict(self) -> dict:
        return {"id": self.id, "owner": self.owner, "gi": self.gi, "amt": self.amt, "path": self.path,
                "leg": self.leg, "t_depart": self.t_depart, "t_arrive": self.t_arrive, "hold": self.hold}

    @property
    def src(self) -> int:
        return self.path[0]

    @property
    def dst(self) -> int:
        return self.path[-1]


@dataclass
class Fleet:
    id: int
    civ: str
    strength: float
    sid: int
    dest: int | None = None
    eta: float = 0.0
    task: str = "garrison"

    def to_dict(self) -> dict:
        return {"id": self.id, "civ": self.civ, "strength": self.strength, "sid": self.sid, "dest": self.dest,
                "eta": self.eta, "task": self.task}


@dataclass
class CivState:
    id: str
    techs: list[str]
    research: float
    exhaustion: float = 0.0
    fleets_built: int = 0
    expansions: int = 0
    treasury: float = 0.0
    bonus: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "techs": self.techs, "research": self.research, "exhaustion": self.exhaustion,
                "fleets_built": self.fleets_built, "expansions": self.expansions, "treasury": self.treasury}


class GalaxySim:
    """The whole living economy and politics of the galaxy."""

    def __init__(self, galaxy: Galaxy, defs: Defs, seed: int | None = None):
        self.g = galaxy
        self.defs = defs
        self.seed = galaxy.seed if seed is None else seed
        self.goods = defs.good_ids()
        self.gi = {g: i for i, g in enumerate(self.goods)}
        self.nG = len(self.goods)
        self.base = [float(defs.goods[g]["base"]) for g in self.goods]
        self.made = [i for i, g in enumerate(self.goods) if defs.goods[g].get("recipe")]
        self.recipe = {i: [(self.gi[k], float(v)) for k, v in defs.goods[self.goods[i]]["recipe"].items()
                           if k in self.gi] for i in self.made}
        self.cons_rate = [CONS_PER_POP.get(g, 0.0) for g in self.goods]
        self.day = 0
        self.markets: dict[int, Market] = {}
        self.civs: dict[str, CivState] = {}
        self.convoys: dict[int, Convoy] = {}
        self.fleets: dict[int, Fleet] = {}
        self.rel: dict[str, float] = {}
        self.wars: dict[str, int] = {}           # pair -> start day
        self.alliances: set[str] = set()
        self.truce: dict[str, int] = {}          # pair -> day the truce ends
        self.embargo: dict[str, int] = {}        # "a>b" -> start day (a refuses b's trade)
        self.menace: list[float] = []
        self.player_rep: dict[str, float] = {c: 0.0 for c in defs.civs}
        self.raided: dict[int, int] = {}         # sid -> day of last convoy raid by the player
        self.next_id = 1
        self.events: list[dict] = []
        self.version = 0                         # graph version (bumped by ownership/war/blockade changes)
        # ledger
        self.produced = [0.0] * self.nG
        self.consumed = [0.0] * self.nG
        self.lost = [0.0] * self.nG
        self.player_net = [0.0] * self.nG        # goods the player took out (+) / put in (-) of the economy
        self.initial = [0.0] * self.nG
        self.fine_set: set[int] = set()
        self.stats = {"fine_ticks": 0, "batch_ticks": 0, "convoys_made": 0, "convoys_lost": 0, "delivered": 0.0}
        self._dist_cache: dict[tuple, tuple[dict, dict]] = {}
        self._dist_ver = -1
        self._tech_order: dict[str, list[str]] = {}

    # ================================================================ construction
    @classmethod
    def new(cls, galaxy: Galaxy, defs: Defs, warmup_days: int = 36) -> "GalaxySim":
        sim = cls(galaxy, defs)
        sim.menace = [0.0] * len(galaxy.systems)
        rng = Rng(derive_seed(sim.seed, "sim.init"))
        for sid, s in enumerate(galaxy.systems):
            if s.has_port():
                sim.markets[sid] = sim._make_market(sid, None, rng.uniform(0.7, 1.5), 0)
        for civ in defs.civs:
            techs = [defs.civs[civ]["techs"][0]] if defs.civs[civ].get("techs") else []
            st = CivState(civ, techs, 0.0)
            sim.civs[civ] = st
            sim._recalc_bonus(st)
        ids = list(defs.civs)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                base = 0.0
                if b in defs.civs[a].get("likes", []) or a in defs.civs[b].get("likes", []):
                    base += 18
                if b in defs.civs[a].get("dislikes", []) or a in defs.civs[b].get("dislikes", []):
                    base -= 22
                sim.rel[_pair(a, b)] = base + rng.uniform(-6, 6)
        for civ, sid in galaxy.home.items():
            m = sim.markets.get(sid)
            if m is None:
                m = sim._make_market(sid, None, 6.0, 0)
                sim.markets[sid] = m
            sim._found(m, civ, 6.0, home=True)
        # first colonies: nearest free ports around each home
        for civ in ids:
            hops = galaxy.hops_from(galaxy.home[civ])
            near = sorted((h, sid) for sid, h in hops.items() if sid in sim.markets and sim.markets[sid].owner is None
                          and galaxy.region.get(sid) == civ)
            for _, sid in near[:3]:
                sim._found(sim.markets[sid], civ, 2.0)
        sim._recalc_all_targets()
        for m in sim.markets.values():
            for gi in range(sim.nG):
                m.stock[gi] = sim._target(m, gi) * rng.uniform(0.9, 1.5)
        sim.initial = [sum(m.stock[gi] for m in sim.markets.values()) for gi in range(sim.nG)]
        sim.version += 1
        for _ in range(warmup_days):
            sim.step_day(set(sim.markets))
        # the warm-up history is part of the world, not of the ledger window
        sim.initial = [sum(m.stock[gi] for m in sim.markets.values()) + sim.in_transit(gi) for gi in range(sim.nG)]
        sim.produced = [0.0] * sim.nG
        sim.consumed = [0.0] * sim.nG
        sim.lost = [0.0] * sim.nG
        sim.player_net = [0.0] * sim.nG
        sim.events.clear()
        return sim

    def _make_market(self, sid: int, owner: str | None, size: float, day: int) -> Market:
        s = self.g.systems[sid]
        base = [0.0] * self.nG
        for b in s.bodies:
            for gid, v in b.res.items():
                if gid in self.gi:
                    base[self.gi[gid]] += v
        cap = 2.0 + 8.0 * max([b.hab for b in s.bodies] + [0.0])
        m = Market(sid, owner, size, max(cap, size), base, [0.0] * self.nG, list(self.base), [0.0] * self.nG,
                   founded=day)
        m.need = [0.0] * self.nG
        return m

    def _found(self, m: Market, civ: str, size: float, home: bool = False) -> None:
        m.owner = civ
        m.size = max(m.size, size)
        m.cap = max(m.cap, m.size + (3.0 if home else 0.0))
        m.defense = 2.0 + (3.0 if home else 0.0)
        c = self.defs.civs[civ]
        rng = Rng(derive_seed(self.seed, "industry", m.sid))
        hub = home or rng.chance(0.5)
        m.industry = [0.0] * self.nG
        for i in self.made:
            gid = self.goods[i]
            if gid == c.get("lack"):
                continue
            factor = 0.6 if gid == c.get("specialty") else 0.18
            if hub:
                m.industry[i] = factor * (1.6 if (home or gid == c.get("specialty")) else 1.0) * max(m.size, 2.0)
        self.version += 1

    # ================================================================ queries
    def owner(self, sid: int) -> str | None:
        m = self.markets.get(sid)
        return m.owner if m else None

    def blockade(self, sid: int) -> str | None:
        m = self.markets.get(sid)
        return m.blockaded_by if m else None

    def colonies_of(self, civ: str) -> list[int]:
        return sorted(sid for sid, m in self.markets.items() if m.owner == civ)

    def rel_between(self, a: str, b: str) -> float:
        return self.rel.get(_pair(a, b), 0.0)

    def at_war(self, a: str | None, b: str | None) -> bool:
        return bool(a and b and a != b and _pair(a, b) in self.wars)

    def allied(self, a: str | None, b: str | None) -> bool:
        return bool(a and b and a != b and _pair(a, b) in self.alliances)

    def embargoes(self, a: str, b: str) -> bool:
        return f"{a}>{b}" in self.embargo

    def state_between(self, a: str, b: str) -> str:
        k = _pair(a, b)
        if k in self.wars:
            return "war"
        if k in self.alliances:
            return "alliance"
        if self.embargoes(a, b) or self.embargoes(b, a):
            return "embargo"
        r = self.rel.get(k, 0.0)
        for name, lo in REL_STATES:
            if r >= lo:
                return name
        return "hostile"

    def civ_power(self, civ: str) -> float:
        fl = sum(f.strength for f in self.fleets.values() if f.civ == civ)
        return fl + sum(m.size for m in self.markets.values() if m.owner == civ) * 0.4

    def patrol_level(self, sid: int) -> float:
        m = self.markets.get(sid)
        base = m.defense if m and m.owner else 0.0
        return base + sum(f.strength for f in self.fleets.values() if f.sid == sid and f.dest is None)

    def in_transit(self, gi: int) -> float:
        return sum(c.amt for c in self.convoys.values() if c.gi == gi)

    def total_stock(self, gi: int) -> float:
        return sum(m.stock[gi] for m in self.markets.values())

    def fine_systems(self, center: int, hops: int = FINE_HOPS) -> set[int]:
        return set(self.g.hops_from(center, include_hidden=True).keys() if hops >= 99 else
                   {s for s, h in self.g.hops_from(center, include_hidden=True).items() if h <= hops})

    def tech_bonus(self, civ: str | None, key: str) -> float:
        c = self.civs.get(civ) if civ else None
        return c.bonus.get(key, 0.0) if c else 0.0

    def _recalc_bonus(self, st: CivState) -> None:
        b: dict[str, float] = {}
        for t in st.techs:
            for k, v in self.defs.techs.get(t, {}).get("effects", {}).items():
                b[k] = b.get(k, 0.0) + v
        st.bonus = b

    # ================================================================ markets
    def _industry_input_rate(self, m: Market, gi: int) -> float:
        tot = 0.0
        for i in self.made:
            cap = m.industry[i]
            if cap > 0:
                for inp, ratio in self.recipe[i]:
                    if inp == gi:
                        tot += cap * ratio
        return tot

    def _target(self, m: Market, gi: int) -> float:
        return max(8.0, self.cons_rate[gi] * m.size * 14.0 + self._industry_input_rate(m, gi) * 6.0)

    def _recalc_all_targets(self) -> None:
        pass

    def price_multiplier(self, m: Market, gi: int, stock: float | None = None) -> float:
        r = (m.stock[gi] if stock is None else stock) / self._target(m, gi)
        return min(PRICE_HI, max(PRICE_LO, (max(r, 0.02)) ** -0.9))

    def _tick_market(self, m: Market, n: int) -> None:
        """Advance one market by ``n`` days (n=1 in fine mode, BATCH in batched mode)."""
        civ = self.civs.get(m.owner) if m.owner else None
        bonus = civ.bonus if civ else {}
        exploit = min(1.5, 0.35 + m.size / 6.0) * m.efficiency
        stock, nG, goods = m.stock, self.nG, self.goods
        prod_ledger, cons_ledger = self.produced, self.consumed
        war_mult = 1.0 + (1.5 if (m.owner and any(m.owner in k.split("|") for k in self.wars)) else 0.0)
        for gi in range(nG):
            bp = m.base_prod[gi]
            if bp > 0:
                amt = bp * PROD_PER_POINT * exploit * (1.0 + bonus.get("prod_" + goods[gi], 0.0)) * n
                stock[gi] += amt
                prod_ledger[gi] += amt
        sat_food = sat_water = sat_fuel = 1.0
        for gi in range(nG):
            per = self.cons_rate[gi]
            if per <= 0:
                continue
            want = per * m.size * n * (war_mult if goods[gi] in ("alloy", "fuel") else 1.0)
            got = want if stock[gi] >= want else max(0.0, stock[gi])
            stock[gi] -= got
            cons_ledger[gi] += got
            s = got / want if want > 0 else 1.0
            gid = goods[gi]
            if gid == "food":
                sat_food = s
            elif gid == "water":
                sat_water = s
            elif gid == "fuel":
                sat_fuel = s
        # industry
        for i in self.made:
            cap = m.industry[i] * n * m.efficiency
            if cap <= 0:
                continue
            for inp, ratio in self.recipe[i]:
                cap = min(cap, stock[inp] / ratio)
            if cap > 1e-9:
                for inp, ratio in self.recipe[i]:
                    stock[inp] -= cap * ratio
                    cons_ledger[inp] += cap * ratio
                stock[i] += cap
                prod_ledger[i] += cap
        # growth / decline
        starve = 1.0 - min(sat_food, sat_water)
        m.shortage += (starve - m.shortage) * min(1.0, 0.35 * n)
        if starve < 0.02 and sat_fuel > 0.9:
            m.size += 0.012 * m.size * (1.0 - m.size / m.cap) * n * (1.0 + (civ.bonus.get("growth", 0.0) if civ else 0.0))
        elif starve > 0.3:
            m.size = max(0.5, m.size - 0.02 * m.size * n * starve)
        m.efficiency = 1.0 if m.blockaded_by is None else 0.7
        # spoilage keeps stocks bounded (counted as lost)
        lost_l = self.lost
        for gi in range(nG):
            tg = self._target(m, gi)
            cap_s = tg * 6.0
            if stock[gi] > cap_s:
                ex = (stock[gi] - cap_s) * (1.0 - 0.95 ** n)
                stock[gi] -= ex
                lost_l[gi] += ex
            tp = self.base[gi] * min(PRICE_HI, max(PRICE_LO, (max(stock[gi] / tg, 0.02)) ** -0.9))
            m.price[gi] += (tp - m.price[gi]) * (1.0 - 0.65 ** n)
            m.need[gi] = max(0.0, tg - stock[gi])
        self._plan_exports(m, n)

    # ================================================================ trade & convoys
    def _hostile_to(self, owner: str | None, node_owner: str | None) -> bool:
        if not owner or not node_owner or owner == node_owner:
            return False
        return self.at_war(owner, node_owner) or self.embargoes(node_owner, owner)

    def _lane_days(self, a: int, b: int) -> int:
        return max(1, math.ceil(self.g.lane(a, b).length / CONVOY_SPEED))

    def _dist_map(self, owner: str | None, src: int) -> tuple[dict, dict]:
        """Dijkstra days-from-src over lanes open to ``owner``'s convoys (cached per graph version)."""
        if self._dist_ver != self.version:
            self._dist_cache.clear()
            self._dist_ver = self.version
        key = (owner, src)
        hit = self._dist_cache.get(key)
        if hit is not None:
            return hit
        import heapq
        dist = {src: 0}
        prev: dict[int, int] = {}
        heap = [(0, src)]
        g = self.g
        markets = self.markets
        while heap:
            d, cur = heapq.heappop(heap)
            if d > dist.get(cur, 1 << 30) or d > 18:
                continue
            for n in g.adj[cur]:
                ln = g.lane(cur, n)
                if ln.kind != "normal":
                    continue
                m = markets.get(n)
                if m is not None and (m.blockaded_by is not None and m.blockaded_by != owner) and n != src:
                    continue
                if m is not None and self._hostile_to(owner, m.owner):
                    continue
                cm = markets.get(cur)
                if cm is not None and cm.blockaded_by is not None and cur != src:
                    continue
                nd = d + max(1, math.ceil(ln.length / CONVOY_SPEED))
                if nd < dist.get(n, 1 << 30):
                    dist[n] = nd
                    prev[n] = cur
                    heapq.heappush(heap, (nd, n))
        self._dist_cache[key] = (dist, prev)
        return dist, prev

    def route_days(self, owner: str | None, a: int, b: int) -> int | None:
        dist, _ = self._dist_map(owner, a)
        return dist.get(b)

    def _inbound(self) -> dict[tuple[int, int], float]:
        out: dict[tuple[int, int], float] = {}
        for c in self.convoys.values():
            k = (c.dst, c.gi)
            out[k] = out.get(k, 0.0) + c.amt
        return out

    def _plan_exports(self, m: Market, n: int) -> None:
        """Ship surplus goods from ``m`` to the best deficit market (profit / need driven)."""
        if m.blockaded_by is not None or len(self.convoys) >= MAX_CONVOYS:
            return
        civ = self.civs.get(m.owner) if m.owner else None
        cap_mult = 1.0 + (civ.bonus.get("convoy", 0.0) if civ else 0.0)
        capacity = (18.0 + 4.0 * m.size) * cap_mult * (1.0 + 0.6 * (n - 1) ** 0.5)
        inbound = self._inb_cache
        for gi in range(self.nG):
            tg = self._target(m, gi)
            surplus = m.stock[gi] - tg * 1.15
            if surplus < 4.0:
                continue
            dist, prev = self._dist_map(m.owner, m.sid)
            best, best_score = None, 0.0
            for sid2, d in dist.items():
                if sid2 == m.sid:
                    continue
                m2 = self.markets.get(sid2)
                if m2 is None or m2.blockaded_by is not None and m2.blockaded_by != m.owner:
                    continue
                if self._hostile_to(m.owner, m2.owner) or self._hostile_to(m2.owner, m.owner):
                    continue
                need = self._target(m2, gi) * 1.0 - m2.stock[gi] - inbound.get((sid2, gi), 0.0)
                if need < 3.0:
                    continue
                gain = m2.price[gi] - 0.9 * m.price[gi]
                if gain <= 0:
                    continue
                score = min(surplus, need, capacity) * gain / (3.0 + d)
                if score > best_score:
                    best, best_score = sid2, score
            if best is None:
                continue
            m2 = self.markets[best]
            need = self._target(m2, gi) - m2.stock[gi] - inbound.get((best, gi), 0.0)
            amt = min(surplus, need, capacity)
            if amt < 3.0:
                continue
            path = [best]
            while path[-1] != m.sid:
                path.append(prev[path[-1]])
            path.reverse()
            m.stock[gi] -= amt
            cid = self.next_id
            self.next_id += 1
            t0 = float(self.day + 1)
            self.convoys[cid] = Convoy(cid, m.owner, gi, amt, path, 1, t0, t0 + self._lane_days(path[0], path[1]))
            inbound[(best, gi)] = inbound.get((best, gi), 0.0) + amt
            self.stats["convoys_made"] += 1
            if len(self.convoys) >= MAX_CONVOYS:
                return

    def _move_convoys(self) -> None:
        day = float(self.day)
        arrived = [c for c in self.convoys.values() if c.t_arrive <= day]
        for c in sorted(arrived, key=lambda c: c.id):
            node = c.path[c.leg]
            m = self.markets.get(node)
            if c.leg == len(c.path) - 1:
                self._deliver(c, m)
                continue
            nxt = c.path[c.leg + 1]
            ln = self.g.lane(node, nxt)
            nm = self.markets.get(nxt)
            blocked = (m is not None and m.blockaded_by is not None and m.blockaded_by != c.owner) or \
                      (nm is not None and (nm.blockaded_by is not None and nm.blockaded_by != c.owner or
                                           self._hostile_to(c.owner, nm.owner)))
            if blocked:
                c.hold += 1
                c.t_arrive = day + 1.0
                if c.hold > 4:              # give up: sell the cargo where we are
                    self._deliver(c, m, fallback=True)
                continue
            if self._pirate_check(c, node, nxt, fine=node in self.fine_set or nxt in self.fine_set):
                continue
            c.leg += 1
            c.hold = 0
            c.t_depart = day + 1.0
            c.t_arrive = day + 1.0 + max(1, math.ceil(ln.length / CONVOY_SPEED))
            _ = nm

    def _pirate_check(self, c: Convoy, a: int, b: int, fine: bool) -> bool:
        """Maybe lose (or, in batched mode, shave) a convoy to pirates on lane a-b; True if it was destroyed."""
        danger = max(self.menace[a], self.menace[b])
        prot = min(0.7, (self.patrol_level(a) + self.patrol_level(b)) * 0.07)
        p = max(0.0, danger * (1.0 - prot) - 0.04)
        if p <= 0:
            return False
        gi = c.gi
        if fine:
            roll = Rng(derive_seed(self.seed, "raid", c.id, c.leg)).random()
            if roll < p:
                self._destroy_convoy(c, "pirates", at=a)
                return True
            return False
        loss = c.amt * p * 0.6
        c.amt -= loss
        self.lost[gi] += loss
        return False

    def _destroy_convoy(self, c: Convoy, cause: str, at: int | None = None) -> None:
        self.lost[c.gi] += c.amt
        self.stats["convoys_lost"] += 1
        self.convoys.pop(c.id, None)
        if at is not None:
            self.menace[at] = min(1.0, self.menace[at] + 0.03)
        dst = self.markets.get(c.dst)
        self.log("convoy_lost", f"A {self.goods[c.gi]} convoy bound for {self.g.systems[c.dst].name} was lost to {cause}.",
                 sid=c.dst, civ=c.owner, good=self.goods[c.gi])
        _ = dst

    def _deliver(self, c: Convoy, m: Market | None, fallback: bool = False) -> None:
        self.convoys.pop(c.id, None)
        if m is None:
            self.lost[c.gi] += c.amt
            return
        m.stock[c.gi] += c.amt
        self.stats["delivered"] += c.amt
        if c.owner and m.owner and c.owner != m.owner:
            k = _pair(c.owner, m.owner)
            self.rel[k] = min(100.0, self.rel.get(k, 0.0) + 0.15)

    def raid_convoy(self, cid: int, by_player: bool = True) -> float:
        """The player destroyed a convoy: its cargo leaves the economy (the caller may loot part of it)."""
        c = self.convoys.get(cid)
        if c is None:
            return 0.0
        amt = c.amt
        self.convoys.pop(cid)
        self.player_net[c.gi] += amt
        self.stats["convoys_lost"] += 1
        if by_player:
            self.raided[c.dst] = self.day
            if c.owner:
                self.add_rep(c.owner, -9.0)
            self.log("convoy_raided", f"A {self.goods[c.gi]} convoy for {self.g.systems[c.dst].name} was raided.",
                     sid=c.dst, civ=c.owner, good=self.goods[c.gi])
        return amt

    def convoys_in_system(self, sid: int, window: float = 1.0) -> list[Convoy]:
        """Convoys that are at ``sid`` right now (just arrived, or about to depart onward)."""
        out = []
        for c in self.convoys.values():
            node = c.path[c.leg]
            prev_node = c.path[c.leg - 1]
            if node == sid and self.day - c.t_arrive >= -0.0 and self.day - c.t_arrive < window:
                out.append(c)
            elif prev_node == sid and c.t_depart - window <= self.day <= c.t_depart + window * 0.5 and c.leg == 1 \
                    and False:
                out.append(c)
        return sorted(out, key=lambda c: c.id)

    # ================================================================ civs
    def log(self, kind: str, text: str, **kw) -> None:
        ev = {"day": self.day, "kind": kind, "text": text}
        ev.update({k: v for k, v in kw.items() if v is not None})
        self.events.append(ev)
        if len(self.events) > 80:
            del self.events[:20]

    def add_rep(self, civ: str, delta: float) -> float:
        v = max(-100.0, min(100.0, self.player_rep.get(civ, 0.0) + delta))
        self.player_rep[civ] = v
        return v

    def _research(self, civ: CivState, days: int) -> None:
        pts = sum(m.size for m in self.markets.values() if m.owner == civ.id) * 0.1
        pts *= 1.0 + civ.bonus.get("research", 0.0)
        civ.research += pts * days
        order = self._tech_pref(civ.id)
        for t in order:
            if t in civ.techs:
                continue
            tdef = self.defs.techs[t]
            if any(r not in civ.techs for r in tdef.get("requires", [])):
                continue
            if civ.research >= tdef["cost"]:
                civ.research -= tdef["cost"]
                civ.techs.append(t)
                self._recalc_bonus(civ)
                self.version += 1
                self.log("tech", f"{self.defs.civs[civ.id]['short']} learned {tdef['name']}.", civ=civ.id, tech=t)
            break

    def _tech_pref(self, civ: str) -> list[str]:
        if civ not in self._tech_order:
            pref = list(self.defs.civs[civ].get("techs", []))
            rest = sorted(t for t in self.defs.techs if t not in pref)
            self._tech_order[civ] = pref + rest
        return self._tech_order[civ]

    def _expand(self, civ: str) -> None:
        cdef = self.defs.civs[civ]
        mine = self.colonies_of(civ)
        tr = cdef.get("traits", {})
        if len(mine) >= 12 + int(5 * tr.get("expansion", 0.5)):
            return
        reach = 1 + int(self.civs[civ].bonus.get("expansion_range", 0))
        cand: dict[int, float] = {}
        for sid in mine:
            for sid2, h in self.g.hops_from(sid, max_range=232.0).items():
                if h == 0 or h > reach:
                    continue
                m2 = self.markets.get(sid2)
                if m2 is None or (m2.owner is not None) or self.g.systems[sid2].hidden:
                    continue
                if h > 1 and not all(self.g.lane(a, b) for a, b in zip([sid], [sid2])):
                    pass
                val = 1.0 + sum(v for v in m2.base_prod) * 0.1 + m2.size * 0.4
                lack = cdef.get("lack")
                if lack and m2.base_prod[self.gi[lack]] > 0:
                    val += 2.5
                if any(self.at_war(civ, o) for o in {self.owner(x) for x in self.g.neighbors(sid2)} if o):
                    val -= 1.0
                cand[sid2] = max(cand.get(sid2, 0.0), val / (0.6 + h * 0.5))
        if not cand:
            return
        target = max(sorted(cand), key=lambda s: (cand[s], -s))
        # pay from the nearest owned colony that can afford it
        costs = {"alloy": 10.0, "food": 8.0, "fuel": 4.0}
        payer = None
        for sid in sorted(mine, key=lambda s: self.g.dist(s, target)):
            m = self.markets[sid]
            if all(m.stock[self.gi[k]] >= v * 1.5 for k, v in costs.items() if k in self.gi):
                payer = m
                break
        if payer is None:
            return
        for k, v in costs.items():
            if k in self.gi:
                payer.stock[self.gi[k]] -= v
                self.consumed[self.gi[k]] += v
        m2 = self.markets[target]
        self._found(m2, civ, 1.2)
        m2.founded = self.day
        self.civs[civ].expansions += 1
        self.log("colony", f"{cdef['short']} settled {self.g.systems[target].name}.", sid=target, civ=civ)

    def _diplomacy(self, civ_ids: list[str]) -> None:
        """Relations drift, wars start and end, alliances form."""
        day = self.day
        for i, a in enumerate(civ_ids):
            for b in civ_ids[i + 1:]:
                k = _pair(a, b)
                r = self.rel.get(k, 0.0)
                da, db = self.defs.civs[a], self.defs.civs[b]
                d = -r * 0.008
                if b in da.get("likes", []) or a in db.get("likes", []):
                    d += 0.06
                if b in da.get("dislikes", []) or a in db.get("dislikes", []):
                    d -= 0.07
                border = self._border_count(a, b)
                if border:
                    d -= 0.06 * min(border, 4) * (da["traits"].get("aggression", 0.3) + db["traits"].get("aggression", 0.3))
                if k in self.wars:
                    d -= 0.25
                if k in self.alliances:
                    d += 0.15
                if self.embargoes(a, b) or self.embargoes(b, a):
                    d -= 0.1
                r = max(-100.0, min(100.0, r + d))
                self.rel[k] = r
                self._war_logic(a, b, k, r, border)

    def _border_count(self, a: str, b: str) -> int:
        n = 0
        for sid, m in self.markets.items():
            if m.owner == a:
                for nb in self.g.adj[sid]:
                    if self.owner(nb) == b:
                        n += 1
        return n

    def _war_logic(self, a: str, b: str, k: str, r: float, border: int) -> None:
        day = self.day
        if k in self.wars:
            ex = (self.civs[a].exhaustion + self.civs[b].exhaustion) / 2
            if ex > 58 or (day - self.wars[k] > 160 and ex > 30):
                self._make_peace(a, b, "exhaustion")
            return
        if k in self.alliances:
            if r < 20:
                self.alliances.discard(k)
                self.log("alliance_end", f"The {self.defs.civs[a]['short']}-{self.defs.civs[b]['short']} alliance lapsed.", civ=a)
            return
        if self.truce.get(k, 0) > day or border == 0:
            return
        rng = Rng(derive_seed(self.seed, "war", day, k))
        aggr = max(self.defs.civs[a]["traits"].get("aggression", 0.3), self.defs.civs[b]["traits"].get("aggression", 0.3))
        if r < -48 and rng.random() < 0.05 * aggr:
            self.wars[k] = day
            self.version += 1
            ids = sorted(self.defs.civs)
            self.log("war", f"{self.defs.civs[a]['short']} and {self.defs.civs[b]['short']} are at war.", civ=a, other=b)
            _ = ids
        elif r > 62 and rng.random() < 0.02:
            self.alliances.add(k)
            self.log("alliance", f"{self.defs.civs[a]['short']} and {self.defs.civs[b]['short']} formed an alliance.", civ=a, other=b)

    def _make_peace(self, a: str, b: str, why: str, duration: int = 90) -> None:
        k = _pair(a, b)
        self.wars.pop(k, None)
        self.truce[k] = self.day + duration
        self.rel[k] = max(self.rel.get(k, 0.0), -20.0)
        for civ in (a, b):
            self.civs[civ].exhaustion *= 0.4
        for m in self.markets.values():
            if m.blockaded_by in (a, b) and m.owner in (a, b):
                m.blockaded_by = None
                m.siege = 0
        for f in self.fleets.values():
            if f.civ in (a, b) and f.task != "garrison":
                f.task, f.dest = "garrison", None
        self.version += 1
        self.log("peace", f"{self.defs.civs[a]['short']} and {self.defs.civs[b]['short']} made peace ({why}).", civ=a, other=b)

    def _fleets_and_war(self, civ_ids: list[str]) -> None:
        day = self.day
        # build
        for civ in civ_ids:
            st = self.civs[civ]
            mine = self.colonies_of(civ)
            if not mine:
                continue
            nf = sum(1 for f in self.fleets.values() if f.civ == civ)
            cap = 2 + len(mine) // 3
            at_war = any(civ in k.split("|") for k in self.wars)
            interval = 8 if at_war else 20
            if nf < cap and (day + civ.__hash__() % 7) % interval == 0 or (nf == 0 and day % 10 == 0):
                rich = max(mine, key=lambda s: (self.markets[s].stock[self.gi["alloy"]] if "alloy" in self.gi else 0.0, -s))
                m = self.markets[rich]
                if "alloy" in self.gi and m.stock[self.gi["alloy"]] >= 14 and m.stock[self.gi["fuel"]] >= 6:
                    m.stock[self.gi["alloy"]] -= 10
                    m.stock[self.gi["fuel"]] -= 5
                    self.consumed[self.gi["alloy"]] += 10
                    self.consumed[self.gi["fuel"]] += 5
                    fid = self.next_id
                    self.next_id += 1
                    s = 1.0 * (1.0 + st.bonus.get("fleet", 0.0))
                    self.fleets[fid] = Fleet(fid, civ, s, rich)
                    st.fleets_built += 1
        # move & fight
        for fid in sorted(self.fleets):
            f = self.fleets[fid]
            if f.dest is not None and f.eta <= day:
                f.sid, f.dest = f.dest, None
                self._arrive_fleet(f)
            if f.dest is None and f.task != "blockade":
                self._assign_fleet(f)
        # sieges
        for sid in sorted(self.markets):
            m = self.markets[sid]
            if m.blockaded_by is None:
                continue
            att = [f for f in self.fleets.values() if f.sid == sid and f.civ == m.blockaded_by and f.dest is None]
            if not att or not self.at_war(m.blockaded_by, m.owner):
                m.blockaded_by = None
                m.siege = 0
                self.version += 1
                continue
            m.siege += 1
            self.civs[m.owner].exhaustion += 0.35 if m.owner in self.civs else 0
            if m.siege >= 9 and m.owner != m.blockaded_by and m.owner in self.civs:
                self._conquer(m, m.blockaded_by)
        for civ in civ_ids:
            st = self.civs[civ]
            at_war = any(civ in k.split("|") for k in self.wars)
            st.exhaustion = max(0.0, st.exhaustion + (0.12 if at_war else -0.4))
            if at_war:
                starved = sum(1 for s in self.colonies_of(civ) if self.markets[s].shortage > 0.25)
                st.exhaustion += 0.15 * starved

    def _assign_fleet(self, f: Fleet) -> None:
        enemies = [o for o in self.civs if self.at_war(f.civ, o)]
        if not enemies:
            f.task = "garrison"
            return
        cur = f.sid
        hops = self.g.hops_from(cur, max_range=232.0)
        best, bs = None, -1e9
        for sid, h in hops.items():
            m = self.markets.get(sid)
            if h == 0 or h > 3 or m is None or m.owner not in enemies:
                continue
            defend = m.defense + sum(x.strength for x in self.fleets.values() if x.sid == sid)
            score = -h * 0.6 - defend + (0.5 if m.blockaded_by is None else -2.0)
            if score > bs:
                best, bs = sid, score
        if best is None:
            f.task = "garrison"
            return
        route = self.g.route(cur, best, 232.0)
        if not route or len(route) < 2:
            return
        nxt = route[1]
        f.dest = nxt
        f.eta = float(self.day + max(1, math.ceil(self.g.lane(cur, nxt).length / 70.0)))
        f.task = "attack"

    def _arrive_fleet(self, f: Fleet) -> None:
        m = self.markets.get(f.sid)
        if m is None or m.owner is None or not self.at_war(f.civ, m.owner):
            return
        defenders = [x for x in self.fleets.values() if x.sid == f.sid and x.civ == m.owner and x.dest is None]
        d = (m.defense * (1.0 + self.tech_bonus(m.owner, "defense")) +
             sum(x.strength for x in defenders))
        a = f.strength
        p = a * a / (a * a + d * d + 1e-9)
        roll = Rng(derive_seed(self.seed, "battle", self.day, f.id)).random()
        if roll < p:
            for x in defenders:
                self.fleets.pop(x.id, None)
            self.civs[m.owner].exhaustion += 4.0
            f.strength *= max(0.4, 1.0 - 0.7 * d / max(a, 0.1) * 0.4)
            f.task = "blockade"
            m.blockaded_by = f.civ
            m.siege = 0
            self.version += 1
            self.log("blockade", f"{self.defs.civs[f.civ]['short']} blockades {self.g.systems[f.sid].name}.",
                     sid=f.sid, civ=f.civ, other=m.owner)
        else:
            self.civs[f.civ].exhaustion += 3.0
            f.strength *= 0.45
            if f.strength < 0.35:
                self.fleets.pop(f.id, None)
            else:
                f.task = "garrison"
            for x in defenders:
                x.strength *= 0.85

    def _conquer(self, m: Market, by: str) -> None:
        old = m.owner
        m.owner = by
        m.size = max(0.8, m.size * 0.7)
        m.blockaded_by = None
        m.siege = 0
        for gi in range(self.nG):
            lost = m.stock[gi] * 0.4
            m.stock[gi] -= lost
            self.lost[gi] += lost
        self._found(m, by, m.size)
        self.version += 1
        for f in self.fleets.values():
            if f.sid == m.sid and f.civ == by:
                f.task = "garrison"
        self.log("conquest", f"{self.defs.civs[by]['short']} took {self.g.systems[m.sid].name} from "
                             f"{self.defs.civs[old]['short']}.", sid=m.sid, civ=by, other=old)

    def _menace_step(self, days: int = 1) -> None:
        for sid, s in enumerate(self.g.systems):
            m = self.markets.get(sid)
            owned = m is not None and m.owner is not None
            base = 0.05 if owned else 0.22
            if m is not None and m.blockaded_by is not None:
                base += 0.1
            if self.raided.get(sid, -999) > self.day - 30:
                base += 0.1
            base -= min(0.03, self.patrol_level(sid) * 0.004)
            cur = self.menace[sid]
            self.menace[sid] = max(0.0, min(0.95, cur + (base - cur) * 0.04 * days))

    # ================================================================ stepping
    def step_day(self, fine: set[int] | None = None) -> None:
        """Advance one day.  ``fine`` = systems simulated at full detail (others are batched)."""
        if fine is not None:
            self.fine_set = fine
        fine_set = self.fine_set
        self.day += 1
        day = self.day
        self._inb_cache = self._inbound()
        for sid in sorted(self.markets):
            m = self.markets[sid]
            if sid in fine_set:
                self._tick_market(m, m.pending + 1)
                m.pending = 0
                self.stats["fine_ticks"] += 1
            else:
                m.pending += 1
                if (day + sid) % BATCH == 0:
                    self._tick_market(m, m.pending)
                    m.pending = 0
                    self.stats["batch_ticks"] += 1
        self._move_convoys()
        ids = sorted(self.civs)
        for civ in ids:
            self._research(self.civs[civ], 1)
        for civ in ids:
            cd = self.defs.civs[civ]["traits"].get("expansion", 0.5)
            if (day + hash(civ) % 11) % max(6, int(20 / (0.4 + cd))) == 0:
                self._expand(civ)
        self._diplomacy(ids)
        self._fleets_and_war(ids)
        if day % 3 == 0:
            self._menace_step(3)

    def advance(self, days: int, center: int | None = None) -> None:
        """Advance ``days`` days with the fine set centred on system ``center`` (None = everything batched)."""
        fine = self.fine_systems(center) if center is not None else set()
        for _ in range(int(days)):
            self.step_day(fine)

    def flush_pending(self) -> None:
        """Settle every market's owed batch days (call before saving or inspecting exact numbers)."""
        for sid in sorted(self.markets):
            m = self.markets[sid]
            if m.pending:
                self._tick_market(m, m.pending)
                m.pending = 0

    # ================================================================ player trade API
    def good_index(self, good: str) -> int:
        return self.gi[good]

    def rep_price_mod(self, civ: str | None, buying: bool) -> float:
        if not civ:
            return 1.0
        r = self.player_rep.get(civ, 0.0)
        if r >= 0:
            adj = -0.12 * min(r, 80) / 80.0
        else:
            adj = 0.2 * min(-r, 80) / 80.0
        return 1.0 + adj if buying else 1.0 - adj

    def will_trade(self, sid: int) -> bool:
        m = self.markets.get(sid)
        if m is None:
            return False
        if m.owner and self.player_rep.get(m.owner, 0.0) <= -60:
            return False
        return m.blockaded_by is None or True

    def unit_price(self, sid: int, good: str, side: str, qty: float = 1.0) -> float:
        """Price per unit the player pays (side='buy') or receives (side='sell') for ``qty`` units."""
        m = self.markets[sid]
        gi = self.gi[good]
        tg = self._target(m, gi)
        if side == "buy":
            mid_stock = max(0.0, m.stock[gi] - qty / 2.0)
            mult = min(PRICE_HI, max(PRICE_LO, max(mid_stock / tg, 0.02) ** -0.9))
            local = 0.5 * m.price[gi] / self.base[gi] + 0.5 * mult
            return self.base[gi] * local * (1 + SPREAD) * self.rep_price_mod(m.owner, True)
        mid_stock = m.stock[gi] + qty / 2.0
        mult = min(PRICE_HI, max(PRICE_LO, max(mid_stock / tg, 0.02) ** -0.9))
        local = 0.5 * m.price[gi] / self.base[gi] + 0.5 * mult
        return self.base[gi] * local * (1 - SPREAD) * self.rep_price_mod(m.owner, False)

    def buy(self, sid: int, good: str, qty: int) -> tuple[int, float]:
        """Take up to ``qty`` units from the market; returns (units, total cost)."""
        m = self.markets[sid]
        gi = self.gi[good]
        qty = int(min(qty, math.floor(m.stock[gi])))
        if qty <= 0:
            return 0, 0.0
        cost = self.unit_price(sid, good, "buy", qty) * qty
        m.stock[gi] -= qty
        self.player_net[gi] += qty
        # price impact comes from the stock change itself (unit_price reads it), so a round trip can never profit
        return qty, cost

    def sell(self, sid: int, good: str, qty: int) -> float:
        """Put ``qty`` units into the market; returns the payment."""
        m = self.markets[sid]
        gi = self.gi[good]
        qty = int(qty)
        if qty <= 0:
            return 0.0
        pay = self.unit_price(sid, good, "sell", qty) * qty
        m.stock[gi] += qty
        self.player_net[gi] -= qty
        return pay

    def supply_effect(self, sid: int, good: str, qty: int) -> None:
        """Delivered relief supplies: reputation, and the colony recovers (shortage eases)."""
        m = self.markets[sid]
        gi = self.gi[good]
        if m.owner:
            self.add_rep(m.owner, min(8.0, 1.0 + qty * 0.25))
        m.shortage = max(0.0, m.shortage - 0.1 * qty / max(1.0, m.size))
        _ = gi

    # -- diplomacy actions by the player ---------------------------------------------------------
    def can_broker_peace(self, a: str, b: str) -> tuple[bool, str]:
        k = _pair(a, b)
        if k not in self.wars:
            return False, "They are not at war."
        ra, rb = self.player_rep.get(a, 0.0), self.player_rep.get(b, 0.0)
        if min(ra, rb) < 10:
            return False, "Both sides must trust you (reputation 10+ with each)."
        ex = (self.civs[a].exhaustion + self.civs[b].exhaustion) / 2
        if ex < 18 and self.day - self.wars[k] < 25:
            return False, "Neither side is tired of the war yet."
        return True, "Both sides will listen."

    def broker_peace(self, a: str, b: str) -> bool:
        ok, _ = self.can_broker_peace(a, b)
        if not ok:
            return False
        self._make_peace(a, b, "brokered by you", duration=120)
        self.add_rep(a, 10)
        self.add_rep(b, 10)
        return True

    def can_ally(self, a: str, b: str) -> tuple[bool, str]:
        k = _pair(a, b)
        if k in self.wars:
            return False, "They are at war."
        if k in self.alliances:
            return False, "Already allied."
        if self.rel.get(k, 0.0) < 25:
            return False, "They do not like each other enough (relations 25+)."
        if min(self.player_rep.get(a, 0.0), self.player_rep.get(b, 0.0)) < 30:
            return False, "You need reputation 30+ with both."
        return True, "An alliance is possible."

    def broker_alliance(self, a: str, b: str) -> bool:
        ok, _ = self.can_ally(a, b)
        if not ok:
            return False
        self.alliances.add(_pair(a, b))
        self.rel[_pair(a, b)] = max(self.rel[_pair(a, b)], 65.0)
        self.add_rep(a, 6)
        self.add_rep(b, 6)
        self.version += 1
        self.log("alliance", f"With your help {self.defs.civs[a]['short']} and {self.defs.civs[b]['short']} allied.", civ=a, other=b)
        return True

    def can_embargo(self, a: str, b: str) -> tuple[bool, str]:
        if self.embargoes(a, b):
            return False, "Already embargoed."
        if self.player_rep.get(a, 0.0) < 25:
            return False, "You need reputation 25+ with the civ that would impose it."
        if a == b:
            return False, "Pick two different civs."
        return True, "They will close their ports to the other."

    def push_embargo(self, a: str, b: str) -> bool:
        """The player persuades civ ``a`` to refuse ``b``'s ships and goods."""
        ok, _ = self.can_embargo(a, b)
        if not ok:
            return False
        self.embargo[f"{a}>{b}"] = self.day
        self.add_rep(b, -10)
        self.add_rep(a, 4)
        self.version += 1
        self.log("embargo", f"{self.defs.civs[a]['short']} embargoes {self.defs.civs[b]['short']}.", civ=a, other=b)
        return True

    def lift_embargo(self, a: str, b: str) -> bool:
        if f"{a}>{b}" not in self.embargo:
            return False
        del self.embargo[f"{a}>{b}"]
        self.version += 1
        self.add_rep(b, 3)
        self.log("embargo_end", f"{self.defs.civs[a]['short']} lifted its embargo on {self.defs.civs[b]['short']}.", civ=a, other=b)
        return True

    # ================================================================ simulation-need queries (missions)
    def shortages(self, min_severity: float = 0.5) -> list[dict]:
        """Markets badly short of an essential good, worst first."""
        out = []
        for sid in sorted(self.markets):
            m = self.markets[sid]
            for g in ("food", "water", "fuel", "alloy"):
                if g not in self.gi:
                    continue
                gi = self.gi[g]
                tg = self._target(m, gi)
                ratio = m.stock[gi] / tg
                if m.size >= 1.0 and ratio < 1.0 - min_severity * 0.8 and self.cons_rate[gi] > 0:
                    out.append({"sid": sid, "good": g, "ratio": ratio, "need": max(4, int(tg - m.stock[gi])),
                                "owner": m.owner, "blockaded": m.blockaded_by})
        out.sort(key=lambda d: (d["ratio"], d["sid"], d["good"]))
        return out

    def blockades(self) -> list[tuple[int, str, str | None]]:
        return [(sid, m.blockaded_by, m.owner) for sid, m in sorted(self.markets.items()) if m.blockaded_by]

    # ================================================================ conservation check
    def ledger_error(self, gi: int) -> float:
        """Absolute drift of the conservation identity for one good (should be ~0)."""
        have = self.total_stock(gi) + self.in_transit(gi)
        want = self.initial[gi] + self.produced[gi] - self.consumed[gi] - self.lost[gi] - self.player_net[gi]
        return abs(have - want)

    # ================================================================ persistence
    def to_dict(self) -> dict:
        return {
            "v": 1, "day": self.day, "next_id": self.next_id, "version": self.version,
            "markets": [self.markets[s].to_dict() for s in sorted(self.markets)],
            "civs": [self.civs[c].to_dict() for c in sorted(self.civs)],
            "convoys": [self.convoys[c].to_dict() for c in sorted(self.convoys)],
            "fleets": [self.fleets[f].to_dict() for f in sorted(self.fleets)],
            "rel": {k: self.rel[k] for k in sorted(self.rel)},
            "wars": {k: self.wars[k] for k in sorted(self.wars)},
            "alliances": sorted(self.alliances),
            "truce": {k: self.truce[k] for k in sorted(self.truce)},
            "embargo": {k: self.embargo[k] for k in sorted(self.embargo)},
            "menace": self.menace, "player_rep": {k: self.player_rep[k] for k in sorted(self.player_rep)},
            "raided": {str(k): v for k, v in sorted(self.raided.items())},
            "events": self.events[-40:],
            "produced": self.produced, "consumed": self.consumed, "lost": self.lost, "player_net": self.player_net,
            "initial": self.initial, "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, galaxy: Galaxy, defs: Defs, d: dict) -> "GalaxySim":
        sim = cls(galaxy, defs)
        sim.day = d["day"]
        sim.next_id = d["next_id"]
        sim.version = d.get("version", 0) + 1
        for md in d["markets"]:
            m = sim._make_market(md["sid"], md["owner"], md["size"], md["founded"])
            m.cap = md["cap"]
            m.stock = list(md["stock"])
            m.price = list(md["price"])
            m.industry = list(md["industry"])
            m.pending = md["pending"]
            m.defense = md["defense"]
            m.blockaded_by = md["blockaded_by"]
            m.siege = md["siege"]
            m.shortage = md["shortage"]
            m.efficiency = md["efficiency"]
            sim.markets[m.sid] = m
        for cd in d["civs"]:
            st = CivState(cd["id"], list(cd["techs"]), cd["research"], cd["exhaustion"], cd["fleets_built"],
                          cd["expansions"], cd["treasury"])
            sim._recalc_bonus(st)
            sim.civs[st.id] = st
        for c in d["convoys"]:
            sim.convoys[c["id"]] = Convoy(c["id"], c["owner"], c["gi"], c["amt"], list(c["path"]), c["leg"],
                                          c["t_depart"], c["t_arrive"], c["hold"])
        for f in d["fleets"]:
            sim.fleets[f["id"]] = Fleet(f["id"], f["civ"], f["strength"], f["sid"], f["dest"], f["eta"], f["task"])
        sim.rel = dict(d["rel"])
        sim.wars = dict(d["wars"])
        sim.alliances = set(d["alliances"])
        sim.truce = dict(d["truce"])
        sim.embargo = dict(d["embargo"])
        sim.menace = list(d["menace"])
        sim.player_rep = dict(d["player_rep"])
        sim.raided = {int(k): v for k, v in d["raided"].items()}
        sim.events = list(d["events"])
        sim.produced, sim.consumed, sim.lost = list(d["produced"]), list(d["consumed"]), list(d["lost"])
        sim.player_net, sim.initial = list(d["player_net"]), list(d["initial"])
        sim.stats = dict(d["stats"])
        for m in sim.markets.values():
            m.need = [0.0] * sim.nG
        return sim

    def state_hash(self) -> str:
        d = self.to_dict()
        d.pop("version", None)                      # cache-invalidation counter, not simulation state
        blob = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()
