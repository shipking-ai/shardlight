"""The campaign layer of Concord: provinces, economy, supply, armies, sieges, research, events and victory.

``Campaign`` owns all mutable state and exposes an order API used identically by the player's UI and by the AI
planner (``ai.py``): build, recruit, set_research, order_move, diplomacy actions.  ``end_turn`` is a generator: it
yields a :class:`BattleRequest` whenever a battle involves the player (so the scene can run it tactically) and
resolves every other battle with the same rules via ``battle.auto_resolve``.

Pure logic: no pygame.  Everything round-trips through JSON (``to_dict`` / ``from_dict``).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any, Generator

from ...core.rng import Rng, derive_seed
from . import battle as B
from . import hexgrid, mapgen
from .diplomacy import Diplomacy, TREATIES, assess
from .rules import (ARMY_MOVE_FOOT, ARMY_MOVE_MOUNTED, ARMY_MOVE_SIEGE, BASE_RESEARCH_RATE, BASE_STORAGE, CAPITAL_SUPPLY,
                    STACK_LIMIT, TERRAIN_ATTRITION, TERRAIN_MOVE, TERRAIN_POP, TERRAIN_SLOTS, TERRAIN_SUPPLY_COST, Rules,
                    house_mods)
from .schemas import RESOURCES
from .state import Army, House, MapData, Province, Unit, empty_stock, pair

SAVE_VERSION = 1
GRAIN_PER_POP = 0.5
GRAIN_PER_UNIT = 0.3
BASE_COIN_PER_POP = 0.8
CAPITAL_BONUS = {"coin": 4.0, "grain": 1.0}
UNREST_REVOLT = 100.0
UNREST_PENALTY = 50.0
RECRUITS_PER_LEVEL = 2
HEAL_BASE = 0.10
CONCORD_HOLD_TURNS = 3
TECH_COST_MULT = 1.9
EVENT_CHANCE = 0.22
PRESETS = {"story": {"ai_bonus": 0.0, "ai_aggr": 0.8}, "standard": {"ai_bonus": 0.0, "ai_aggr": 1.0},
           "hard": {"ai_bonus": 0.0, "ai_aggr": 1.2}}


@dataclass
class BattleRequest:
    pid: int
    attacker: int                      # army id
    defenders: list[int]               # army ids (may be empty: attackers storm an empty fort)
    att_house: str
    def_house: str
    terrain: str
    fort: int
    river: bool
    seed: int
    player_side: int | None            # 0 attacker, 1 defender, None for AI-only (auto-resolved)

    def describe(self, camp: "Campaign") -> str:
        p = camp.map.provinces[self.pid]
        return f"{p.name} ({p.terrain})"


@dataclass
class Note:
    turn: int
    kind: str
    text: str
    house: str | None = None
    pid: int | None = None


class Campaign:
    def __init__(self, rules: Rules, seed: int, size: str, player: str, unlocks: frozenset[str] = frozenset(),
                 preset: str = "standard", adapt: float = 1.0, _map: MapData | None = None):
        self.rules = rules
        self.seed = seed
        self.size = size
        self.player = player
        self.unlocks = frozenset(unlocks)
        self.preset = preset if preset in PRESETS else "standard"
        self.adapt = adapt
        self.turn = 1
        self.rng = Rng(seed).child("campaign")
        house_ids = rules.house_ids()
        self.map: MapData = _map or mapgen.generate(seed, size, house_ids)
        self.houses: dict[str, House] = {}
        self.armies: dict[int, Army] = {}
        self.dp = Diplomacy(house_ids)
        self.notes: list[Note] = []
        self.hooks: list[tuple[str, dict]] = []             # cross-mode events drained by the scene
        self.pending: list[dict] = []                       # undecided events for the player
        self.next_uid = 1
        self.next_army = 1
        self.winner: str | None = None
        self.victory: str | None = None
        self.concord_turns = 0
        self.stats = {"battles": 0, "battles_won": 0, "provinces_taken": 0, "provinces_lost": 0, "treaties": 0}
        self.habits: dict[str, float] = {}                  # what the player does (read by the AI's adaptive controller)
        self.ai_state: dict[str, dict] = {}
        self._vis_cache: dict[tuple[str, int], set[int]] = {}
        self._new_game()

    # ============================================================================================ setup
    def _new_game(self) -> None:
        r = self.rules
        for hid in r.house_ids():
            hd = r.houses[hid]
            h = House(hid)
            h.stock = empty_stock()
            h.stock.update({k: float(v) for k, v in hd["start"].items()})
            h.techs = list(hd.get("start_techs", []))
            h.is_player = hid == self.player
            h.capital = self.map.capitals[hid]
            self.houses[hid] = h
            army = self._new_army(hid, h.capital)
            for t in hd["start_units"]:
                army.units.append(self._new_unit(t))
            self._initial_buildings(hid)
        for hid, h in self.houses.items():
            self.refresh_memory(hid)
        self.note("start", f"The campaign begins. You lead {r.houses[self.player]['name']}.", self.player)

    def _initial_buildings(self, hid: str) -> None:
        h = self.houses[hid]
        cap = self.map.provinces[h.capital]
        cap.buildings.update({"barracks": 1, "market": 1, "farmstead": 1} if cap.terrain in ("plain", "hill") else
                             {"barracks": 1, "market": 1})
        for p in self.provinces_of(hid):
            if p.id == h.capital:
                continue
            if p.terrain in ("hill", "mountain") and "mine" in self.rules.buildings:
                p.buildings["mine"] = 1
            elif p.terrain == "forest":
                p.buildings["sawmill"] = 1
            elif p.terrain in ("plain", "marsh"):
                p.buildings["farmstead"] = 1

    def _new_unit(self, utype: str) -> Unit:
        u = Unit(self.next_uid, utype, float(self.rules.units[utype]["hp"]))
        self.next_uid += 1
        return u

    def _new_army(self, hid: str, pid: int) -> Army:
        a = Army(self.next_army, hid, pid, name=f"{self.next_army}")
        self.armies[a.id] = a
        self.next_army += 1
        return a

    def note(self, kind: str, text: str, house: str | None = None, pid: int | None = None) -> None:
        self.notes.append(Note(self.turn, kind, text, house, pid))
        if len(self.notes) > 400:
            del self.notes[:100]

    # ============================================================================================ queries
    def provinces_of(self, hid: str) -> list[Province]:
        return [p for p in self.map.provinces if p.owner == hid]

    def alive(self) -> list[str]:
        return [h for h, x in self.houses.items() if x.alive]

    def armies_of(self, hid: str) -> list[Army]:
        return [a for a in self.armies.values() if a.owner == hid]

    def armies_at(self, pid: int) -> list[Army]:
        return [a for a in self.armies.values() if a.pid == pid]

    def mods(self, hid: str) -> dict[str, float]:
        return house_mods(self.rules, hid, self.houses[hid].techs)

    def mod(self, hid: str, key: str, default: float = 0.0) -> float:
        return self.mods(hid).get(key, default)

    def fort_level(self, p: Province) -> int:
        lvl = p.buildings.get("fort", 0)
        if p.owner:
            lvl += int(self.mod(p.owner, "fort_level")) if lvl else 0
            if p.id == self.houses[p.owner].capital:
                lvl = max(lvl, 0)
        return lvl

    def name_of(self, hid: str) -> str:
        return self.rules.houses[hid]["name"]

    def short(self, hid: str) -> str:
        return self.rules.houses[hid]["name"].replace("House ", "")

    def date_text(self, hid: str | None = None) -> str:
        cal = self.rules.houses[hid or self.player]["calendar"]
        n = self.turn - 1
        per = cal.get("per_year", 4)
        seasons = cal.get("seasons") or []
        season = seasons[n % per] if seasons and per <= len(seasons) else ""
        return cal["fmt"].format(year=cal.get("year0", 1) + n // per, season=season, n=self.turn, leaf=n % per + 1)

    def army_strength(self, a: Army, hid: str | None = None) -> float:
        """Rough fighting value of an army (hp times attack, armour-adjusted) used by AI and UI."""
        s = 0.0
        techs = self.houses[a.owner].techs
        m = self.mods(a.owner)
        for u in a.units:
            st = B.unit_stats(self.rules, u, techs, m)
            s += min(u.hp, st["hp"]) * st["atk"] * (1 + 0.05 * st["arm"]) / 60.0
        return s

    def house_power(self, hid: str) -> float:
        h = self.houses[hid]
        return sum(self.army_strength(a) for a in self.armies_of(hid)) + 4.0 * len(self.provinces_of(hid)) + 0.2 * sum(
            h.stock.get(r, 0) for r in ("coin", "ore"))

    # ---------------------------------------------------------------------------- vision / fog
    def vision_radius(self, hid: str) -> int:
        return 1 + int(self.mod(hid, "vision"))

    def visible(self, hid: str) -> set[int]:
        key = (hid, self.turn * 100000 + sum(len(a.path) + a.pid for a in self.armies.values()) % 99991 +
               len(self.armies) * 7 + sum(1 for p in self.map.provinces if p.owner == hid) * 131)
        got = self._vis_cache.get(key)
        if got is not None:
            return got
        out: set[int] = set()
        rad = self.vision_radius(hid)
        sources: list[tuple[int, int]] = []
        for friend in [hid] + self.dp.allies_of(hid):
            for p in self.provinces_of(friend):
                sources.append((p.id, rad + (2 if p.buildings.get("watchtower") else 0)))
            for a in self.armies_of(friend):
                sources.append((a.pid, rad))
        for pid, r in sources:
            out |= self._ball(pid, r)
        for pid, until in self.houses[hid].scouted.items():
            if until >= self.turn:
                out |= self._ball(pid, 1)
        if len(self._vis_cache) > 64:
            self._vis_cache.clear()
        self._vis_cache[key] = out
        return out

    def _ball(self, pid: int, r: int) -> set[int]:
        seen = {pid}
        frontier = [pid]
        for _ in range(r):
            nxt = []
            for x in frontier:
                for n in self.map.adj[x]:
                    if n not in seen:
                        seen.add(n)
                        nxt.append(n)
            frontier = nxt
        return seen

    def refresh_memory(self, hid: str) -> None:
        h = self.houses[hid]
        vis = self.visible(hid)
        for pid in vis:
            p = self.map.provinces[pid]
            h.explored.add(pid)
            h.memory[pid] = {"owner": p.owner, "turn": self.turn, "terrain": p.terrain,
                             "armies": [(a.owner, round(self.army_strength(a), 1), len(a.units)) for a in self.armies_at(pid)],
                             "fort": self.fort_level(p), "buildings": sum(p.buildings.values())}

    # ============================================================================================ economy
    def province_yield(self, p: Province) -> dict[str, float]:
        out = {r: 0.0 for r in RESOURCES}
        if p.owner is None:
            return out
        hid = p.owner
        m = self.mods(hid)
        for r, v in p.base.items():
            out[r] += v
        pop = TERRAIN_POP[p.terrain] + p.buildings.get("farmstead", 0) * 0.5
        out["coin"] += pop * BASE_COIN_PER_POP
        if p.id == self.houses[hid].capital:
            for r, v in CAPITAL_BONUS.items():
                out[r] += v
        for bid, lvl in p.buildings.items():
            eff = self.rules.buildings[bid].get("effects", {})
            for res, table in eff.get("prod", {}).items():
                out[res] += table.get(p.terrain, table.get("default", 0)) * lvl
            if p.feature and p.feature in eff.get("feature_bonus", {}):
                for res, v in eff["feature_bonus"][p.feature].items():
                    out[res] += v * lvl
        for r in RESOURCES:
            out[r] *= 1.0 + m.get(f"prod.{r}", 0.0)
            out[r] *= 1.0 - min(0.8, p.devastation)
        if p.unrest >= UNREST_PENALTY:
            for r in RESOURCES:
                out[r] *= 0.7
        if p.owner != p.home and p.home is not None and p.conquered > 0:
            for r in RESOURCES:
                out[r] *= 0.6
        return out

    def trade_bonus(self, hid: str) -> float:
        partners = [o for o in self.dp.trade_partners(hid) + self.dp.allies_of(hid) if self.houses[o].alive]
        return (1.0 if self.player == hid else 1.0) * len(set(partners)) * (0.10 + self.mod(hid, "trade_income") * 0.5)

    def house_flow(self, hid: str) -> dict[str, dict[str, float]]:
        """Per-turn income and upkeep by resource for ``hid``: the numbers the ledger shows."""
        m = self.mods(hid)
        inc = {r: 0.0 for r in RESOURCES}
        upkeep = {r: 0.0 for r in RESOURCES}
        provs = self.provinces_of(hid)
        for p in provs:
            for r, v in self.province_yield(p).items():
                inc[r] += v
            for bid, lvl in p.buildings.items():
                upkeep["coin"] += self.rules.buildings[bid].get("upkeep", 0) * lvl * 0.5
            upkeep["grain"] += TERRAIN_POP[p.terrain] * GRAIN_PER_POP
        n_units = 0
        for a in self.armies_of(hid):
            for u in a.units:
                upkeep["coin"] += self.rules.units[u.type].get("upkeep", 1.0) * 0.45
                upkeep["grain"] += GRAIN_PER_UNIT
                n_units += 1
        upkeep["coin"] += 0.18 * len(provs) ** 1.45               # administration: big realms are costly to run
        upkeep["coin"] *= 1.0 + m.get("upkeep", 0.0)
        inc["coin"] *= 1.0 + self.trade_bonus(hid)
        return {"income": inc, "upkeep": upkeep, "net": {r: inc[r] - upkeep[r] for r in RESOURCES}}

    def storage_cap(self, hid: str) -> float:
        cap = BASE_STORAGE + self.mod(hid, "storage")
        for p in self.provinces_of(hid):
            cap += self.rules.buildings.get("granary", {}).get("effects", {}).get("storage", 0) * p.buildings.get("granary", 0)
        return cap

    def research_rate(self, hid: str) -> float:
        rate = BASE_RESEARCH_RATE + self.mod(hid, "research_rate")
        for p in self.provinces_of(hid):
            rate += p.buildings.get("scriptorium", 0) * 1.5
        return rate * (1.0 - min(0.5, self.houses[hid].exhaustion / 200.0))

    def research_options(self, hid: str) -> list[str]:
        h = self.houses[hid]
        out = []
        for tid in self.rules.tech_list(self.unlocks):
            t = self.rules.techs[tid]
            if tid in h.techs:
                continue
            if t.get("player_only") and not h.is_player:
                continue
            if all(r in h.techs for r in t.get("requires", [])):
                out.append(tid)
        return out

    def tech_cost(self, tid: str) -> float:
        return float(self.rules.techs[tid]["cost"]) * TECH_COST_MULT

    def set_research(self, hid: str, tid: str | None) -> bool:
        if tid is not None and tid not in self.research_options(hid):
            return False
        h = self.houses[hid]
        if h.research != tid:
            h.progress = h.progress * 0.5 if h.research else 0.0         # switching wastes half the progress
        h.research = tid
        if hid == self.player and tid:
            self.habits["research_" + self.rules.techs[tid]["branch"]] = self.habits.get("research_" + self.rules.techs[tid]["branch"], 0) + 1
        return True

    # ---------------------------------------------------------------------------- construction
    def building_cost(self, hid: str, bid: str, level: int) -> dict[str, float]:
        b = self.rules.buildings[bid]
        mult = 1.0 + 0.8 * (level - 1)
        return {r: round(v * mult) for r, v in b["cost"].items()}

    def can_build(self, hid: str, pid: int, bid: str) -> tuple[bool, str]:
        p = self.map.provinces[pid]
        b = self.rules.buildings.get(bid)
        h = self.houses[hid]
        if b is None:
            return False, "Unknown building."
        if p.owner != hid:
            return False, "You do not hold this province."
        if any(q["b"] == bid for q in p.queue) or len(p.queue) >= 2:
            return False, "Already under construction."
        if b.get("tech") and b["tech"] not in h.techs:
            return False, f"Requires {self.rules.techs[b['tech']]['name']}."
        terr = b.get("terrain")
        if terr and p.terrain not in terr:
            return False, "Cannot be built on this terrain."
        cur = p.buildings.get(bid, 0)
        if cur >= b.get("max_level", 1):
            return False, "Already at maximum level."
        if cur == 0 and len(p.buildings) + len([q for q in p.queue if q["b"] not in p.buildings]) >= TERRAIN_SLOTS[p.terrain]:
            return False, "No free building slot."
        if p.conquered > 0 and p.conquered < 3:
            return False, "Province is still in turmoil."
        cost = self.building_cost(hid, bid, cur + 1)
        if not h.can_afford(cost):
            return False, "Cannot afford it."
        return True, "OK"

    def build(self, hid: str, pid: int, bid: str) -> bool:
        ok, _ = self.can_build(hid, pid, bid)
        if not ok:
            return False
        p = self.map.provinces[pid]
        cur = p.buildings.get(bid, 0)
        self.houses[hid].pay(self.building_cost(hid, bid, cur + 1))
        p.queue.append({"b": bid, "left": self.rules.buildings[bid].get("turns", 2), "lvl": cur + 1})
        if hid == self.player:
            self.habits["build_" + bid] = self.habits.get("build_" + bid, 0) + 1
        return True

    def cancel_build(self, hid: str, pid: int, idx: int) -> bool:
        p = self.map.provinces[pid]
        if p.owner != hid or idx >= len(p.queue):
            return False
        q = p.queue.pop(idx)
        self.houses[hid].gain({r: v * 0.6 for r, v in self.building_cost(hid, q["b"], q["lvl"]).items()})
        return True

    # ---------------------------------------------------------------------------- recruitment
    def unit_cost(self, hid: str, utype: str) -> dict[str, float]:
        c = self.rules.units[utype]["cost"]
        mult = 1.0 + self.mod(hid, "recruit_cost")
        return {r: max(1, round(v * mult)) for r, v in c.items()}

    def recruitable(self, hid: str, pid: int) -> list[str]:
        p = self.map.provinces[pid]
        if p.owner != hid or p.conquered > 0 and p.conquered < 3:
            return []
        h = self.houses[hid]
        out = []
        for uid in self.rules.house_units(hid):
            u = self.rules.units[uid]
            if p.buildings.get(u["building"], 0) <= 0:
                continue
            if u.get("tech") and u["tech"] not in h.techs:
                continue
            out.append(uid)
        return out

    def recruits_left(self, pid: int) -> int:
        p = self.map.provinces[pid]
        used = p.__dict__.get("_recruited", (0, 0))
        n = used[1] if used[0] == self.turn else 0
        cap = sum(p.buildings.get(b, 0) for b in ("barracks", "stable", "workshop")) * RECRUITS_PER_LEVEL
        return max(0, cap - n)

    def can_recruit(self, hid: str, pid: int, utype: str) -> tuple[bool, str]:
        if utype not in self.recruitable(hid, pid):
            return False, "Cannot recruit that here."
        if self.recruits_left(pid) <= 0:
            return False, "Barracks are busy this turn."
        if not self.houses[hid].can_afford(self.unit_cost(hid, utype)):
            return False, "Cannot afford it."
        garrison = [a for a in self.armies_at(pid) if a.owner == hid and len(a.units) < STACK_LIMIT]
        if not garrison and len([a for a in self.armies_at(pid) if a.owner == hid]) >= 3:
            return False, "Too many armies here."
        return True, "OK"

    def recruit(self, hid: str, pid: int, utype: str) -> Unit | None:
        ok, _ = self.can_recruit(hid, pid, utype)
        if not ok:
            return None
        p = self.map.provinces[pid]
        self.houses[hid].pay(self.unit_cost(hid, utype))
        u = self._new_unit(utype)
        stationary = [a for a in self.armies_at(pid) if a.owner == hid and not a.path and len(a.units) < STACK_LIMIT]
        army = stationary[0] if stationary else self._new_army(hid, pid)
        army.units.append(u)
        used = p.__dict__.get("_recruited", (0, 0))
        p.__dict__["_recruited"] = (self.turn, (used[1] if used[0] == self.turn else 0) + 1)
        if hid == self.player:
            role = self.rules.units[utype]["role"]
            self.habits["recruit_" + role] = self.habits.get("recruit_" + role, 0) + 1
        return u

    def merge(self, hid: str, a_id: int, b_id: int) -> bool:
        a, b = self.armies.get(a_id), self.armies.get(b_id)
        if not a or not b or a.owner != hid or b.owner != hid or a.pid != b.pid or a.id == b.id:
            return False
        take = STACK_LIMIT - len(a.units)
        if take <= 0:
            return False
        a.units.extend(b.units[:take])
        b.units = b.units[take:]
        if not b.units:
            del self.armies[b.id]
        return True

    def split(self, hid: str, army_id: int, uids: list[int]) -> Army | None:
        a = self.armies.get(army_id)
        if not a or a.owner != hid:
            return None
        moving = [u for u in a.units if u.uid in uids]
        if not moving or len(moving) == len(a.units):
            return None
        a.units = [u for u in a.units if u.uid not in uids]
        n = self._new_army(hid, a.pid)
        n.units = moving
        return n

    # ---------------------------------------------------------------------------- armies / movement
    def army_speed(self, a: Army) -> int:
        roles = {self.rules.units[u.type]["role"] for u in a.units}
        base = ARMY_MOVE_FOOT
        if "siege" in roles:
            base = ARMY_MOVE_SIEGE
        elif roles <= {"cavalry", "skirmisher", "banner", "healer"} and "cavalry" in roles:
            base = ARMY_MOVE_MOUNTED
        return max(1, base + int(self.mod(a.owner, "army_move")))

    def step_cost(self, hid: str, frm: int, to: int) -> float:
        p = self.map.provinces[to]
        c = float(TERRAIN_MOVE[p.terrain])
        if self.map.road(frm, to):
            c = max(0.5, c * (0.5 + self.mod(hid, "road_cost")))
        elif self.map.river(frm, to):
            c += 1.0
        return c

    def can_enter(self, hid: str, pid: int) -> bool:
        p = self.map.provinces[pid]
        if p.owner is None or p.owner == hid:
            return True
        return self.dp.can_pass(hid, p.owner)

    def find_path(self, hid: str, src: int, dst: int) -> list[int] | None:
        """Cheapest legal route (provinces to enter, excluding the start) or None."""
        if src == dst:
            return []
        if not self.can_enter(hid, dst):
            return None
        dist = {src: 0.0}
        prev: dict[int, int] = {}
        pq = [(0.0, src)]
        while pq:
            d, x = heapq.heappop(pq)
            if x == dst:
                break
            if d > dist.get(x, 1e9):
                continue
            for n in self.map.adj[x]:
                if not self.can_enter(hid, n):
                    continue
                nd = d + self.step_cost(hid, x, n)
                if nd < dist.get(n, 1e9):
                    dist[n] = nd
                    prev[n] = x
                    heapq.heappush(pq, (nd, n))
        if dst not in prev:
            return None
        path = [dst]
        while path[-1] in prev and prev[path[-1]] != src:
            path.append(prev[path[-1]])
        path.reverse()
        return path

    def path_turns(self, a: Army, path: list[int]) -> int:
        pts, turns, cur, frm = self.army_speed(a), 1, 0.0, a.pid
        for pid in path:
            c = self.step_cost(a.owner, frm, pid)
            if cur > 0 and cur + c > pts:
                turns += 1
                cur = 0.0
            cur += c
            frm = pid
        return turns if path else 0

    def order_move(self, hid: str, army_id: int, dst: int) -> bool:
        a = self.armies.get(army_id)
        if not a or a.owner != hid:
            return False
        path = self.find_path(hid, a.pid, dst)
        if path is None:
            return False
        a.path = path
        if hid == self.player and path:
            tgt = self.map.provinces[dst]
            if tgt.owner and tgt.owner != hid:
                self.habits["attack"] = self.habits.get("attack", 0) + 1
        return True

    def set_stance(self, hid: str, army_id: int, stance: str) -> bool:
        a = self.armies.get(army_id)
        if not a or a.owner != hid or stance not in ("march", "raid", "pillage"):
            return False
        a.stance = stance
        return True

    # ---------------------------------------------------------------------------- supply
    def depots(self, hid: str) -> list[tuple[int, float]]:
        out = []
        sr = self.mod(hid, "supply_range")
        for p in self.provinces_of(hid):
            r = 0.0
            if p.id == self.houses[hid].capital:
                r = CAPITAL_SUPPLY
            gran = self.rules.buildings.get("granary", {}).get("effects", {}).get("supply_depot", 0) * p.buildings.get("granary", 0) / max(1, 1)
            fort = self.rules.buildings.get("fort", {}).get("effects", {}).get("supply_depot", 0) * (1 if p.buildings.get("fort") else 0)
            r = max(r, gran, fort)
            if r > 0:
                out.append((p.id, r + sr))
        return out

    def supply_map(self, hid: str) -> dict[int, float]:
        """Province -> remaining supply range (>= 0 means supplied).  Flows through friendly and neutral land."""
        best: dict[int, float] = {}
        pq: list[tuple[float, int]] = []
        for pid, r in self.depots(hid):
            best[pid] = r
            heapq.heappush(pq, (-r, pid))
        while pq:
            nr, x = heapq.heappop(pq)
            r = -nr
            if r < best.get(x, -1):
                continue
            for n in self.map.adj[x]:
                p = self.map.provinces[n]
                if p.owner not in (None, hid) and not self.dp.allied(hid, p.owner):
                    continue                                         # enemy land breaks the chain
                cost = TERRAIN_SUPPLY_COST[p.terrain] * (0.5 if self.map.road(x, n) else 1.0)
                nr2 = r - cost
                if nr2 >= 0 and nr2 > best.get(n, -1):
                    best[n] = nr2
                    heapq.heappush(pq, (-nr2, n))
        return best

    def supplied(self, a: Army, smap: dict[int, float] | None = None) -> bool:
        smap = smap if smap is not None else self.supply_map(a.owner)
        return a.pid in smap

    # ============================================================================================ events
    def _fire_events(self, hid: str) -> None:
        r = self.rng.child("event", self.turn, hid)
        if not r.chance(EVENT_CHANCE) or not self.provinces_of(hid):
            return
        pool = []
        for eid, e in self.rules.events.items():
            if self.turn < e.get("min_turn", 0):
                continue
            needs = e.get("needs") or []
            if "army" in needs and not self.armies_of(hid):
                continue
            if "neighbour" in needs and not self._neighbour_houses(hid):
                continue
            pool.append((eid, e.get("weight", 1.0)))
        if not pool:
            return
        pool.sort()
        eid = r.weighted([p[0] for p in pool], [p[1] for p in pool])
        e = self.rules.events[eid]
        provs = self.provinces_of(hid)
        if e.get("scope") == "province":
            cand = [p for p in provs if not e.get("terrain") or p.terrain in e["terrain"]]
            if "river" in (e.get("needs") or []):
                cand = [p for p in provs if any(self.map.river(p.id, n) for n in self.map.adj[p.id])]
            if not cand:
                return
            pid = r.pick(sorted(cand, key=lambda p: p.id)).id
        else:
            pid = None
        other = None
        if "neighbour" in (e.get("needs") or []):
            others = self._neighbour_houses(hid)
            other = r.pick(sorted(others)) if others else None
        ev = {"event": eid, "house": hid, "pid": pid, "other": other, "turn": self.turn}
        if hid == self.player:
            self.pending.append(ev)
        else:
            opts = e["options"]
            pick = max(range(len(opts)), key=lambda i: opts[i].get("ai", 0.0) + 0.01 * r.random())
            self.resolve_event(ev, pick)

    def _neighbour_houses(self, hid: str) -> list[str]:
        out = set()
        for p in self.provinces_of(hid):
            for n in self.map.adj[p.id]:
                o = self.map.provinces[n].owner
                if o and o != hid and self.houses[o].alive:
                    out.add(o)
        return sorted(out)

    def resolve_event(self, ev: dict, option: int) -> list[str]:
        e = self.rules.events[ev["event"]]
        hid, pid = ev["house"], ev["pid"]
        h = self.houses[hid]
        lines: list[str] = []
        opt = e["options"][option]
        for eff in opt["effects"]:
            if "res" in eff:
                amt = float(eff["amt"])
                if amt < 0 and h.stock.get(eff["res"], 0) < -amt:
                    amt = -h.stock.get(eff["res"], 0)             # cannot pay more than you have: the rest is forgiven
                h.stock[eff["res"]] = h.stock.get(eff["res"], 0) + amt
                lines.append(f"{amt:+.0f} {eff['res']}")
            elif "unrest" in eff and pid is not None:
                self.map.provinces[pid].unrest += eff["unrest"]
                lines.append(f"unrest {eff['unrest']:+.0f}")
            elif "devastate" in eff and pid is not None:
                p = self.map.provinces[pid]
                p.devastation = min(0.8, p.devastation + eff["devastate"])
                lines.append("province devastated")
            elif "unrest_all" in eff:
                for p in self.provinces_of(hid):
                    p.unrest = max(0.0, p.unrest + eff["unrest_all"])
                lines.append(f"unrest {eff['unrest_all']:+.0f} everywhere")
            elif "lose_unit" in eff:
                armies = [a for a in self.armies_of(hid) if a.units]
                if armies:
                    a = self.rng.child("lose", self.turn, hid).pick(sorted(armies, key=lambda x: x.id))
                    a.units.pop()
                    if not a.units:
                        del self.armies[a.id]
                    lines.append("a unit deserts")
            elif "gain_unit" in eff:
                cap = self.map.provinces[h.capital]
                army = next((a for a in self.armies_at(cap.id) if a.owner == hid and len(a.units) < STACK_LIMIT), None) or \
                    self._new_army(hid, cap.id)
                army.units.append(self._new_unit(eff["gain_unit"]))
                lines.append(f"a {self.rules.units[eff['gain_unit']]['name']} company joins")
            elif "opinion_other" in eff and ev.get("other"):
                self.dp.shift(ev["other"], hid, eff["opinion_other"])
                lines.append(f"{self.short(ev['other'])} opinion {eff['opinion_other']:+.0f}")
        if ev in self.pending:
            self.pending.remove(ev)
        if hid == self.player:
            self.note("event", f"{e['title']}: {opt['label']}.", hid, pid)
        return lines

    # ============================================================================================ diplomacy API
    def power_ratio(self, a: str, b: str) -> float:
        return max(0.05, self.house_power(a)) / max(0.05, self.house_power(b))

    def can_declare_war(self, a: str, b: str) -> tuple[bool, str]:
        if a == b or not self.houses[b].alive:
            return False, "No such house."
        if self.dp.at_war(a, b):
            return False, "Already at war."
        if self.dp.allied(a, b):
            return False, "Break the alliance first."
        return True, "OK"

    def war_justified(self, a: str, b: str) -> bool:
        return self.dp.grievance.get((a, b), 0) >= 0.2 or self.houses[a].claims.get(b, 0) >= self.turn

    def fabricate_claim(self, hid: str, target: str) -> bool:
        h = self.houses[hid]
        if h.stock.get("ink", 0) < 3 or target == hid or h.claims.get(target, 0) >= self.turn:
            return False
        h.stock["ink"] -= 3
        h.claims[target] = self.turn + 12
        return True

    def declare_war(self, a: str, b: str) -> bool:
        ok, _ = self.can_declare_war(a, b)
        if not ok:
            return False
        ha = self.houses[a]
        breaking = [k for k in ("pact", "trade") if self.dp.treaty(a, b, k)]
        for k in breaking:
            ha.oath = min(100.0, ha.oath + self.dp.break_treaty(a, b, k, self.turn) * (1.0 + self.mod(a, "betrayal_cost")))
        just = self.war_justified(a, b)
        self.dp.declare_war(a, b, self.turn)
        if not just:
            ha.unjust_until = self.turn + 8
            for o in self.houses:
                if o not in (a, b):
                    self.dp.shift(o, a, -4)
        self.note("war", f"{self.short(a)} declares war on {self.short(b)}" + ("" if just else " without cause") + ".", a)
        if b == self.player or a == self.player:
            self.note("war_you", f"{self.short(a)} is at war with {self.short(b)}.", a)
        # armies in now-hostile land are not teleported: they simply become enemies
        return True

    def assess_for(self, proposer: str, target: str, kind: str):
        """Transparent acceptance estimate for a proposal (also used by the diplomacy screen)."""
        tgt = self.houses[target]
        prop = self.houses[proposer]
        personality = self.rules.houses[target]["personality"]
        shared = sum(1 for e in self.dp.enemies_of(proposer) if self.dp.at_war(target, e))
        ratio = self.power_ratio(proposer, target)
        losing = self.dp.at_war(target, proposer) and self.house_power(target) < self.house_power(proposer) * 0.8
        return assess(self.dp, proposer, target, kind, personality, prop.oath, ratio, shared,
                      self.mod(proposer, "diplo_bonus"), losing, tgt.exhaustion)

    def propose(self, proposer: str, target: str, kind: str) -> tuple[bool, str]:
        """Propose ``peace`` / ``trade`` / ``pact`` / ``alliance``.  Returns (accepted, explanation)."""
        if not self.houses[target].alive or proposer == target:
            return False, "No such house."
        if kind == "peace":
            if not self.dp.at_war(proposer, target):
                return False, "You are not at war."
        else:
            if self.dp.at_war(proposer, target):
                return False, "Not while at war."
            if self.dp.treaty(proposer, target, kind):
                return False, "Already in force."
            if kind == "alliance" and not self.dp.has_pact(proposer, target) and not self.dp.treaty(proposer, target, "trade"):
                return False, "Build trust first: sign a trade pact or non-aggression pact."
        a = self.assess_for(proposer, target, kind)
        if proposer == self.player:
            self.habits["diplomacy"] = self.habits.get("diplomacy", 0) + 1
        if not a.accept:
            self.dp.shift(target, proposer, -1)
            return False, f"{self.short(target)} declines ({a.text()})."
        if kind == "peace":
            self.dp.make_peace(proposer, target, self.turn)
            self.houses[proposer].exhaustion *= 0.7
            self.houses[target].exhaustion *= 0.7
            self.note("peace", f"{self.short(proposer)} and {self.short(target)} make peace.", proposer)
        else:
            self.dp.sign(proposer, target, kind, self.turn)
            self.stats["treaties"] += 1
            self.note("treaty", f"{self.short(proposer)} and {self.short(target)} sign a {kind}.", proposer)
            for x, y in ((proposer, target), (target, proposer)):
                if x == self.player:
                    self.hooks.append(("concord.treaty_signed", {"faction": y}))
        return True, f"{self.short(target)} agrees."

    def break_treaty(self, hid: str, other: str, kind: str) -> bool:
        if not self.dp.treaty(hid, other, kind):
            return False
        h = self.houses[hid]
        h.oath = min(100.0, h.oath + self.dp.break_treaty(hid, other, kind, self.turn) * (1.0 + self.mod(hid, "betrayal_cost")))
        for o in self.houses:
            if o not in (hid, other):
                self.dp.shift(o, hid, -3)
        self.note("break", f"{self.short(hid)} breaks its {kind} with {self.short(other)}.", hid)
        return True

    def gift(self, hid: str, target: str, res: str, amt: int) -> bool:
        h = self.houses[hid]
        if h.stock.get(res, 0) < amt or amt <= 0 or hid == target:
            return False
        h.stock[res] -= amt
        self.houses[target].stock[res] = self.houses[target].stock.get(res, 0) + amt
        worth = amt * {"coin": 1.0, "ink": 4.0, "salt": 2.5, "ore": 1.6, "grain": 0.8, "timber": 1.0}[res]
        self.dp.shift(target, hid, min(25.0, worth * 0.5))
        return True

    def scout(self, hid: str, pid: int) -> bool:
        h = self.houses[hid]
        if h.stock.get("ink", 0) < 1:
            return False
        h.stock["ink"] -= 1
        h.scouted[pid] = self.turn + 3
        self._vis_cache.clear()
        self.refresh_memory(hid)
        return True

    # ============================================================================================ turn
    def end_turn(self, ai_planner=None, include_player: bool = False) -> Generator[BattleRequest, dict | None, None]:
        """Run the whole turn.  ``ai_planner(campaign, house_id)`` issues orders for every non-player house first."""
        if self.winner:
            return
        if self.pending:
            raise RuntimeError("resolve pending events before ending the turn")
        order = [h for h in self.rules.house_ids() if self.houses[h].alive]
        rot = self.turn % max(1, len(order))
        order = order[rot:] + order[:rot]
        if ai_planner:
            for hid in order:
                if hid != self.player or include_player:
                    ai_planner(self, hid)
        yield from self._movement(order)
        self._resolve_sieges()
        self._economy(order)
        self._supply_and_heal(order)
        self._diplomacy_tick()
        self._check_victory()
        self.turn += 1
        self._vis_cache.clear()
        for hid in self.rules.house_ids():
            if self.houses[hid].alive:
                self.refresh_memory(hid)
        for hid in order:
            if self.houses[hid].alive:
                self._fire_events(hid)

    def run_turn(self, ai_planner=None, player_battle=None, include_player: bool = False) -> None:
        """Convenience: drive ``end_turn``; ``player_battle(req)->result`` decides player battles (default: auto)."""
        gen = self.end_turn(ai_planner, include_player)
        res = None
        try:
            req = next(gen)
            while True:
                res = player_battle(req) if player_battle else self.auto_battle(req)
                req = gen.send(res)
        except StopIteration:
            pass

    # ---------------------------------------------------------------------------- movement
    def _movement(self, order: list[str]) -> Generator[BattleRequest, dict | None, None]:
        pts: dict[int, float] = {a.id: float(self.army_speed(a)) for a in self.armies.values()}
        for hid in order:
            for a in sorted(self.armies_of(hid), key=lambda x: x.id):
                if a.id not in self.armies or not a.path:
                    continue
                left = pts.get(a.id, float(self.army_speed(a)))
                first = True
                while a.path and a.id in self.armies:
                    nxt = a.path[0]
                    cost = self.step_cost(hid, a.pid, nxt)
                    if cost > left and not first:
                        break
                    if not self.can_enter(hid, nxt):
                        a.path = []
                        break
                    first = False
                    left -= cost
                    blocked = yield from self._enter(a, nxt)
                    if blocked:
                        a.path = []
                        break
                    if a.path and a.path[0] == a.pid:
                        a.path.pop(0)
                    if left <= 0:
                        break

    def _enter(self, a: Army, dst: int) -> Generator[BattleRequest, dict | None, bool]:
        """Move army ``a`` into ``dst``.  Returns True if it stopped (battle, occupation)."""
        p = self.map.provinces[dst]
        hid = a.owner
        defenders = [d for d in self.armies_at(dst) if d.owner != hid and self.dp.at_war(hid, d.owner)]
        prev = a.pid
        river = self.map.river(prev, dst) and not self.map.road(prev, dst)
        a.prev = prev
        if a.path and a.path[0] == dst:
            a.path.pop(0)
        if defenders:
            a.pid = prev                                   # fights from the border; moves in only if it wins
            req = BattleRequest(dst, a.id, [d.id for d in defenders], hid, defenders[0].owner, p.terrain,
                                self.fort_level(p) if p.owner == defenders[0].owner else 0, river,
                                derive_seed(self.seed, "battle", self.turn, a.id, dst),
                                0 if hid == self.player else (1 if any(d.owner == self.player for d in defenders) else None))
            result = None
            if req.player_side is not None:
                result = yield req
            if result is None:
                result = self.auto_battle(req)
            won = self.apply_battle(req, result)
            if won and a.id in self.armies:
                a.pid = dst
                self._after_arrival(a, p)
            return True
        # no resistance
        a.pid = dst
        self._after_arrival(a, p)
        return bool(p.owner and p.owner != hid and self.dp.at_war(hid, p.owner))

    def _after_arrival(self, a: Army, p: Province) -> None:
        hid = a.owner
        if p.owner and p.owner != hid and self.dp.at_war(hid, p.owner):
            if self.fort_level(p) <= 0 and not [d for d in self.armies_at(p.id) if d.owner == p.owner]:
                self._capture(p, hid, a)
        elif p.owner is None:
            pass

    def auto_battle(self, req: BattleRequest) -> dict:
        b = self.build_battle(req)
        att_h, def_h = self.rules.houses[req.att_house]["personality"], self.rules.houses[req.def_house]["personality"]
        preset = PRESETS[self.preset]
        ai_a = B.BattleAI(b, B.ATTACKER, att_h["aggression"] * (preset["ai_aggr"] if req.att_house != self.player else 1.0),
                          att_h["caution"], b.rng.child("a"))
        ai_d = B.BattleAI(b, B.DEFENDER, def_h["aggression"] * (preset["ai_aggr"] if req.def_house != self.player else 1.0),
                          def_h["caution"], b.rng.child("d"))
        return B.auto_resolve(b, ai_a, ai_d)

    def build_battle(self, req: BattleRequest) -> B.Battle:
        att = self.armies[req.attacker]
        defs = [self.armies[i] for i in req.defenders if i in self.armies]
        a_units = self._battle_units(att.owner, att.units)
        d_units = self._battle_units(req.def_house, [u for d in defs for u in d.units])
        return B.Battle(self.rules, req.seed, req.terrain, a_units, d_units, req.fort, req.river,
                        (self.short(req.att_house), self.short(req.def_house)), (req.att_house, req.def_house))

    def _battle_units(self, hid: str, units: list[Unit]) -> list[tuple[Unit, dict]]:
        techs, m = self.houses[hid].techs, self.mods(hid)
        scored = []
        for u in units:
            st = B.unit_stats(self.rules, u, techs, m)
            scored.append((u, st))
        scored.sort(key=lambda p: -(p[0].hp * p[1]["atk"]))
        return scored[:8]

    def apply_battle(self, req: BattleRequest, result: dict) -> bool:
        """Write a battle result back into the campaign.  Returns True if the attacker won."""
        self.stats["battles"] += 1
        att = self.armies[req.attacker]
        defs = [self.armies[i] for i in req.defenders if i in self.armies]
        winner_att = result["winner"] == B.ATTACKER
        for army in [att] + defs:
            keep = []
            for u in army.units:
                info = result["units"].get(u.uid)
                if info is None:
                    keep.append(u)
                    continue
                if info["dead"]:
                    continue
                u.hp = max(1.0, info["hp"])
                won_side = (info["side"] == B.ATTACKER) == winner_att
                if won_side:
                    u.xp += 1 + (1 if info["kills"] else 0)
                keep.append(u)
            army.units = keep
        p = self.map.provinces[req.pid]
        for who in (req.att_house, req.def_house):
            self.houses[who].exhaustion += 3.0
        loser_house = req.def_house if winner_att else req.att_house
        winner_house = req.att_house if winner_att else req.def_house
        self.dp.shift(loser_house, winner_house, -4)
        if req.att_house == self.player or req.def_house == self.player:
            self.note("battle", f"Battle at {p.name}: {self.short(winner_house)} prevails "
                                f"(losses {result['losses'][0]} / {result['losses'][1]}).", winner_house, req.pid)
        if req.att_house == self.player and winner_att or req.def_house == self.player and not winner_att:
            self.stats["battles_won"] += 1
        # remove empty armies, retreat the loser
        losers = defs if winner_att else [att]
        for army in losers:
            if army.units:
                self._retreat(army, req.pid)
        for army in [att] + defs:
            if not army.units and army.id in self.armies:
                del self.armies[army.id]
        if winner_att and p.owner and p.owner == req.def_house and not any(d.units for d in defs):
            pass
        return winner_att

    def _retreat(self, army: Army, from_pid: int) -> None:
        options = []
        for n in self.map.adj[army.pid if army.pid != from_pid else from_pid]:
            if n == from_pid:
                continue
            o = self.map.provinces[n].owner
            if o is not None and o != army.owner and not self.dp.friendly(army.owner, o):
                continue
            if any(x.owner != army.owner and self.dp.at_war(army.owner, x.owner) for x in self.armies_at(n)):
                continue
            options.append(n)
        if army.pid == from_pid and army.prev is not None and army.prev in options:
            dest = army.prev
        elif army.pid != from_pid:
            dest = army.pid                                   # attacker fought from the border province: it stays
            options = []
        elif options:
            dest = sorted(options, key=lambda n: (self.map.provinces[n].owner != army.owner, n))[0]
        else:
            # cornered: the army is broken and scattered
            army.units = army.units[: len(army.units) // 2]
            return
        army.pid = dest
        army.path = []
        for u in army.units:
            u.hp = max(1.0, u.hp * 0.9)

    # ---------------------------------------------------------------------------- conquest and sieges
    def _capture(self, p: Province, by: str, army: Army | None = None) -> None:
        old = p.owner
        p.owner = by
        p.conquered = 1
        p.unrest = min(95.0, p.unrest + 25.0 + (15.0 if p.home != by else 0.0))
        p.wall_damage = 0.0
        p.queue = []
        for bid in list(p.buildings):
            if self.rules.buildings[bid].get("effects", {}).get("fort") is None and self.rng.child("loot", self.turn, p.id, bid).chance(0.4):
                p.buildings[bid] -= 1
                if p.buildings[bid] <= 0:
                    del p.buildings[bid]
        stance = army.stance if army else "march"
        if stance == "pillage":
            p.devastation = min(0.8, p.devastation + 0.3)
            self.houses[by].gain({"coin": 6, "grain": 4})
        if old:
            oh = self.houses[old]
            self.houses[by].gain({"coin": round(oh.stock.get("coin", 0) * 0.08)})
            oh.stock["coin"] = oh.stock.get("coin", 0) * 0.92
            self.dp.add_grievance(old, by, 0.45)
            if by == self.player:
                self.stats["provinces_taken"] += 1
            if old == self.player:
                self.stats["provinces_lost"] += 1
            self.note("capture", f"{self.short(by)} takes {p.name} from {self.short(old)}.", by, p.id)
            if p.id == oh.capital:
                self._relocate_capital(old)
            self._check_elimination(old)
        self._vis_cache.clear()

    def _relocate_capital(self, hid: str) -> None:
        h = self.houses[hid]
        left = self.provinces_of(hid)
        if left:
            h.capital = max(left, key=lambda p: (sum(p.buildings.values()), -p.id)).id
            h.exhaustion += 10
            self.note("capital", f"{self.short(hid)} moves its seat to {self.map.provinces[h.capital].name}.", hid, h.capital)

    def _check_elimination(self, hid: str) -> None:
        h = self.houses[hid]
        if h.alive and not self.provinces_of(hid):
            h.alive = False
            h.eliminated_turn = self.turn
            for a in list(self.armies_of(hid)):
                del self.armies[a.id]
            for k in list(self.dp.wars):
                if hid in k:
                    del self.dp.wars[k]
            self.note("eliminated", f"House {self.short(hid)} has fallen.", hid)

    def _resolve_sieges(self) -> None:
        for p in self.map.provinces:
            if p.owner is None:
                p.wall_damage = max(0.0, p.wall_damage - 0.5)
                continue
            besiegers = [a for a in self.armies_at(p.id) if a.owner != p.owner and self.dp.at_war(a.owner, p.owner) and a.units]
            defenders = [a for a in self.armies_at(p.id) if a.owner == p.owner and a.units]
            lvl = self.fort_level(p)
            if besiegers and not defenders:
                if lvl <= 0:
                    self._capture(p, besiegers[0].owner, besiegers[0])
                else:
                    sieges = sum(1 for a in besiegers for u in a.units if self.rules.units[u.type]["role"] == "siege")
                    p.wall_damage += 1.0 + 1.6 * sieges
                    if p.wall_damage >= 2.0 * lvl:
                        self._capture(p, besiegers[0].owner, besiegers[0])
                    elif p.owner == self.player or besiegers[0].owner == self.player:
                        self.note("siege", f"{p.name} is under siege ({p.wall_damage:.0f}/{2 * lvl}).", p.owner, p.id)
            else:
                p.wall_damage = max(0.0, p.wall_damage - 0.7)

    # ---------------------------------------------------------------------------- economy phase
    def _economy(self, order: list[str]) -> None:
        for hid in order:
            h = self.houses[hid]
            if not h.alive:
                continue
            flow = self.house_flow(hid)
            m = self.mods(hid)
            for r in RESOURCES:
                h.stock[r] = h.stock.get(r, 0) + flow["net"][r]
            # shortages bite
            if h.stock["coin"] < 0:
                self._unpaid(hid)
                h.stock["coin"] = 0.0
            if h.stock["grain"] < 0:
                self._famine(hid)
                h.stock["grain"] = 0.0
            cap = self.storage_cap(hid)
            excess = h.stock["coin"] - cap * 2.0
            if excess > 0:
                h.stock["coin"] -= excess * 0.10                  # treasuries leak: idle coin is lost to graft and waste
            for r in RESOURCES:
                if r != "coin" and h.stock[r] > cap:
                    h.stock[r] = cap
                if r == "grain":
                    h.stock[r] *= 1.0 - max(0.0, 0.03 + m.get("spoilage", 0.0))
                    for p in self.provinces_of(hid):
                        h.stock[r] *= 1.0 + self.rules.buildings.get("granary", {}).get("effects", {}).get("spoil", 0) * p.buildings.get("granary", 0) * 0.2
            self._research(hid)
            self._construction(hid)
            self._unrest(hid)
            h.exhaustion = max(0.0, h.exhaustion - (1.5 if not self.dp.enemies_of(hid) else 0.3))
            h.oath = max(0.0, h.oath - 0.8)
            if hid == self.player:
                self.stats["peak_provinces"] = max(self.stats.get("peak_provinces", 0), len(self.provinces_of(hid)))

    def _unpaid(self, hid: str) -> None:
        for a in self.armies_of(hid):
            if a.units and self.rng.child("unpaid", self.turn, a.id).chance(0.3):
                gone = a.units.pop()
                if hid == self.player:
                    self.note("deserter", f"A {self.rules.units[gone.type]['name']} deserts: wages unpaid.", hid, a.pid)
            if not a.units:
                self.armies.pop(a.id, None)
        for p in self.provinces_of(hid):
            p.unrest += 3

    def _famine(self, hid: str) -> None:
        for p in self.provinces_of(hid):
            p.unrest += 6
        for a in self.armies_of(hid):
            for u in a.units:
                u.hp = max(1.0, u.hp * 0.93)

    def _research(self, hid: str) -> None:
        h = self.houses[hid]
        if not h.research:
            return
        rate = self.research_rate(hid)
        if h.stock.get("ink", 0) >= 1:
            h.stock["ink"] -= 1
            rate += 2
        h.progress += rate
        cost = self.tech_cost(h.research)
        if h.progress >= cost:
            tid = h.research
            h.techs.append(tid)
            h.progress -= cost
            h.research = None
            self.note("tech", f"{self.short(hid)} masters {self.rules.techs[tid]['name']}.", hid)
            if hid == self.player:
                self.hooks.append(("concord.tech_researched", {"tech": tid}))
            self._vis_cache.clear()

    def _construction(self, hid: str) -> None:
        for p in self.provinces_of(hid):
            if p.conquered:
                p.conquered += 1
                if p.conquered > 8:
                    p.conquered = 0
            p.devastation = max(0.0, p.devastation - 0.02)
            if not p.queue:
                continue
            q = p.queue[0]
            q["left"] -= 1
            if q["left"] <= 0:
                p.buildings[q["b"]] = q["lvl"]
                p.queue.pop(0)
                if hid == self.player:
                    self.note("built", f"{self.rules.buildings[q['b']]['name']} completed at {p.name}.", hid, p.id)

    def _unrest(self, hid: str) -> None:
        h = self.houses[hid]
        m = self.mods(hid)
        relief = m.get("unrest_relief", 0.0)
        provs = self.provinces_of(hid)
        hall_adj: set[int] = set()
        for p in provs:
            if p.buildings.get("hall_of_hours"):
                hall_adj.update(self.map.adj[p.id])
        for p in provs:
            delta = -1.0 - relief
            for bid, lvl in p.buildings.items():
                delta += self.rules.buildings[bid].get("effects", {}).get("unrest", 0) * lvl
            if p.id in hall_adj:
                delta += self.rules.buildings["hall_of_hours"]["effects"].get("unrest_adjacent", -1)
            if p.home is not None and p.home != hid:
                delta += 1.0 + m.get("conquest_unrest", 0.0) * 3
            delta += h.exhaustion / 40.0
            if h.unjust_until >= self.turn:
                delta += 1.5
            if self.armies_at(p.id) and any(a.owner == hid for a in self.armies_at(p.id)):
                delta -= 0.8
            p.unrest = max(0.0, min(110.0, p.unrest + delta))
            if p.unrest >= UNREST_REVOLT and p.id != h.capital:
                self._revolt(p, hid)

    def _revolt(self, p: Province, hid: str) -> None:
        p.owner = None
        p.unrest = 45.0
        p.queue = []
        for a in self.armies_at(p.id):
            if a.owner == hid:
                a.pid = self._nearest_owned(hid, p.id) or a.pid
        self.note("revolt", f"{p.name} throws off {self.short(hid)} rule.", hid, p.id)
        self._check_elimination(hid)

    def _nearest_owned(self, hid: str, pid: int) -> int | None:
        for n in self.map.adj[pid]:
            if self.map.provinces[n].owner == hid:
                return n
        return None

    def claim_neutral(self, hid: str, pid: int) -> bool:
        """Annex an unowned province next to your land (costs coin; cheap, sends a message about expansion)."""
        p = self.map.provinces[pid]
        h = self.houses[hid]
        if p.owner is not None or not any(self.map.provinces[n].owner == hid for n in self.map.adj[pid]):
            return False
        if any(a.owner != hid and self.dp.at_war(hid, a.owner) for a in self.armies_at(pid)):
            return False
        cost = 12 + 3 * len(self.provinces_of(hid))
        if h.stock.get("coin", 0) < cost:
            return False
        h.stock["coin"] -= cost
        p.owner = hid
        p.home = p.home or hid
        p.unrest = 15.0
        p.conquered = 1
        self._vis_cache.clear()
        return True

    def claim_cost(self, hid: str) -> int:
        return 12 + 3 * len(self.provinces_of(hid))

    # ---------------------------------------------------------------------------- supply / heal
    def _supply_and_heal(self, order: list[str]) -> None:
        for hid in order:
            if not self.houses[hid].alive:
                continue
            smap = self.supply_map(hid)
            m = self.mods(hid)
            heal = HEAL_BASE * 0.5 + m.get("heal_rate", 0.0)
            for a in list(self.armies_of(hid)):
                p = self.map.provinces[a.pid]
                st = B_stats_cache(self, a)
                if a.pid in smap:
                    healers = sum(1 for u in a.units if self.rules.units[u.type]["role"] == "healer")
                    rate = heal * (1.5 if p.owner == hid else 0.7) * (1.0 + 0.25 * healers)
                    if a.path:
                        rate *= 0.3
                    for u in a.units:
                        mx = st.get(u.uid, u.hp)
                        u.hp = min(mx, u.hp + mx * rate)
                else:
                    att = 0.06 * TERRAIN_ATTRITION[p.terrain] * (1.0 + m.get("attrition", 0.0))
                    for u in a.units:
                        u.hp = max(1.0, u.hp - st.get(u.uid, u.hp) * att)
                    if hid == self.player and not a.path:
                        self.note("supply", f"Army {a.name} at {p.name} is out of supply.", hid, a.pid)
                if p.owner is not None and p.owner != hid and self.dp.at_war(hid, p.owner) and a.stance in ("raid", "pillage"):
                    p.devastation = min(0.8, p.devastation + (0.08 if a.stance == "raid" else 0.15))
                    self.houses[hid].gain({"coin": 1.5, "grain": 1.0})

    def _diplomacy_tick(self) -> None:
        for n in self.dp.tick(self.turn):
            if self.player in (n["a"], n["b"]):
                self.note("treaty_end", f"The {n['treaty']} between {self.short(n['a'])} and {self.short(n['b'])} has expired.", n["a"])
        # war weariness scales with battles; here: ongoing wars slowly drain
        for hid in self.alive():
            if self.dp.enemies_of(hid):
                self.houses[hid].exhaustion += 0.6

    # ---------------------------------------------------------------------------- victory
    def _check_victory(self) -> None:
        alive = self.alive()
        if self.player not in alive:
            self.winner = alive[0] if alive else None
            self.victory = "defeat"
            return
        if len(alive) == 1:
            self.winner = self.player
            self.victory = "conquest"
            return
        others = [h for h in alive if h != self.player]
        if others and all(self.dp.allied(self.player, o) for o in others):
            self.concord_turns += 1
            if self.concord_turns >= CONCORD_HOLD_TURNS:
                self.winner = self.player
                self.victory = "concord"
        else:
            self.concord_turns = 0
        total = len(self.map.provinces)
        if len(self.provinces_of(self.player)) >= math.ceil(total * 0.6):
            self.winner = self.player
            self.victory = "dominion"

    # ============================================================================================ persistence
    def to_dict(self) -> dict:
        provs = []
        for p in self.map.provinces:
            d = p.to_dict()
            provs.append(d)
        md = self.map.to_dict()
        return {"v": SAVE_VERSION, "seed": self.seed, "size": self.size, "player": self.player, "turn": self.turn,
                "preset": self.preset, "adapt": self.adapt, "unlocks": sorted(self.unlocks), "map": md,
                "houses": {k: h.to_dict() for k, h in self.houses.items()},
                "armies": [a.to_dict() for a in self.armies.values()], "dp": self.dp.to_dict(),
                "notes": [[n.turn, n.kind, n.text, n.house, n.pid] for n in self.notes[-80:]], "pending": list(self.pending),
                "next_uid": self.next_uid, "next_army": self.next_army, "winner": self.winner, "victory": self.victory,
                "concord_turns": self.concord_turns, "stats": dict(self.stats), "habits": dict(self.habits),
                "ai_state": _jsonable_ai(self.ai_state), "adapt_state": _adapt_export(self), "hooks": [[k, v] for k, v in self.hooks]}

    @classmethod
    def from_dict(cls, rules: Rules, d: dict) -> "Campaign | None":
        try:
            if d.get("v") != SAVE_VERSION:
                return None
            m = MapData.from_dict(d["map"])
            c = cls.__new__(cls)
            c.rules = rules
            c.seed, c.size, c.player, c.turn = d["seed"], d["size"], d["player"], d["turn"]
            c.unlocks = frozenset(d.get("unlocks", []))
            c.preset, c.adapt = d.get("preset", "standard"), d.get("adapt", 1.0)
            c.rng = Rng(c.seed).child("campaign")
            c.map = m
            c.houses = {k: House.from_dict(v) for k, v in d["houses"].items()}
            c.armies = {a["id"]: Army.from_dict(a) for a in d["armies"]}
            c.dp = Diplomacy.from_dict(d["dp"])
            c.notes = [Note(*n) for n in d.get("notes", [])]
            c.hooks = [(k, v) for k, v in d.get("hooks", [])]
            c.pending = list(d.get("pending", []))
            c.next_uid, c.next_army = d["next_uid"], d["next_army"]
            c.winner, c.victory, c.concord_turns = d.get("winner"), d.get("victory"), d.get("concord_turns", 0)
            c.stats, c.habits = dict(d["stats"]), dict(d.get("habits", {}))
            c.ai_state = _unjson_ai(d.get("ai_state", {}))
            c._vis_cache = {}
            _adapt_import(c, d.get("adapt_state", {}))
            if set(c.houses) != set(rules.house_ids()):
                return None
            for a in c.armies.values():
                for u in a.units:
                    if u.type not in rules.units:
                        return None
            return c
        except (KeyError, TypeError, ValueError):
            return None

    def state_hash(self) -> str:
        import hashlib
        import json
        d = self.to_dict()
        d.pop("notes", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def B_stats_cache(c: Campaign, a: Army) -> dict[int, float]:
    techs, m = c.houses[a.owner].techs, c.mods(a.owner)
    return {u.uid: B.unit_stats(c.rules, u, techs, m)["hp"] for u in a.units}


def _jsonable_ai(v: Any) -> Any:
    from .state import _jsonable
    return _jsonable(v)


def _unjson_ai(v: Any) -> Any:
    from .state import _unjson
    return _unjson(v)


def _adapt_export(c: "Campaign") -> dict:
    from . import ai
    return ai.export_adapt(c)


def _adapt_import(c: "Campaign", data: dict) -> None:
    from . import ai
    ai.import_adapt(c, data)
