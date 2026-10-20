"""House AI for Concord.

One planner per AI house per turn, issuing orders through the same ``Campaign`` API the player uses.  Each house
has a personality (``concord.house`` data) that weights research, building, recruitment, war and diplomacy.

Fairness rules (tested): the planner reads only ``visible`` provinces and the house's remembered snapshots - it
cannot see unscouted armies - and it never receives resource bonuses.  Adaptation to the player's habits goes
through ``core.ai.AdaptiveController`` (bounded, cooled down, scaled by ``difficulty.adaptive_ai``).
"""
from __future__ import annotations

from ...core.ai import Adaptation, AdaptiveController, PlayerModel
from ...core.rng import Rng
from .campaign import Campaign
from .rules import STACK_LIMIT

# how each archetype likes its research, building and army
RESEARCH_PREF = {
    "expansionist": {"martial": 1.5, "civic": 0.8, "lore": 0.6},
    "mercantile": {"martial": 0.6, "civic": 1.6, "lore": 0.8},
    "defensive": {"martial": 1.0, "civic": 1.3, "lore": 0.7},
    "scholar": {"martial": 0.5, "civic": 0.9, "lore": 1.7},
}
ARMY_MIX = {
    "expansionist": {"cavalry": 3, "infantry": 3, "archer": 1, "banner": 1, "siege": 1, "skirmisher": 1, "pike": 1, "healer": 0.5},
    "mercantile": {"archer": 3, "skirmisher": 2, "infantry": 1.5, "pike": 1.5, "healer": 1, "siege": 1, "cavalry": 0.5, "banner": 0.5},
    "defensive": {"pike": 3, "infantry": 3, "archer": 2, "healer": 1, "banner": 1, "siege": 1, "cavalry": 0.3, "skirmisher": 0.3},
    "scholar": {"archer": 3, "cavalry": 1.5, "infantry": 1.5, "healer": 1.2, "pike": 1, "siege": 1.5, "skirmisher": 1, "banner": 0.5},
}
PLAN_EVERY = 1


class Intel:
    """What a house believes about the world: visible provinces are exact, the rest is last-seen memory."""

    def __init__(self, camp: Campaign, hid: str):
        self.c = camp
        self.hid = hid
        self.vis = camp.visible(hid)
        self.mem = camp.houses[hid].memory

    def enemy_strength(self, pid: int, vs: str) -> float:
        c = self.c
        if pid in self.vis:
            s = sum(c.army_strength(a) for a in c.armies_at(pid) if a.owner != self.hid and not c.dp.friendly(self.hid, a.owner))
            return s
        m = self.mem.get(pid)
        if not m:
            return 1.5                                           # unknown: assume something is there
        return sum(st for (o, st, n) in m["armies"] if o != self.hid and not c.dp.friendly(self.hid, o)) * 0.9

    def owner(self, pid: int) -> str | None:
        if pid in self.vis:
            return self.c.map.provinces[pid].owner
        m = self.mem.get(pid)
        return m["owner"] if m else None

    def fort(self, pid: int) -> int:
        if pid in self.vis:
            return self.c.fort_level(self.c.map.provinces[pid])
        m = self.mem.get(pid)
        return m["fort"] if m else 0


# ------------------------------------------------------------------------------------------- adaptation
def _controller(camp: Campaign, hid: str):
    store = camp.__dict__.setdefault("_adapt", {})
    if hid not in store:
        model = PlayerModel(half_life=30.0)
        ctl = AdaptiveController(model, [
            Adaptation("anti_cavalry", "recruit_cavalry", ("recruit_cavalry", "recruit_archer", "recruit_infantry", "recruit_pike"),
                       0.40, 3.0, 0.5),
            Adaptation("anti_ranged", "recruit_archer", ("recruit_cavalry", "recruit_archer", "recruit_infantry", "recruit_pike"),
                       0.40, 3.0, 0.5),
            Adaptation("anti_turtle", "build_fort", ("build_fort", "build_barracks", "build_farmstead", "build_market", "attack"),
                       0.30, 3.0, 0.5),
        ], strength=camp.adapt, cooldown=6.0)
        store[hid] = [model, ctl, {}]
    return store[hid]


def export_adapt(camp: Campaign) -> dict:
    """Adaptive-controller state of every AI house as plain JSON (so a loaded game continues identically)."""
    out = {}
    for hid, (model, ctl, seen) in camp.__dict__.get("_adapt", {}).items():
        out[hid] = {"w": dict(model.weights), "t": model.t, "n": model.samples, "seen": {k: float(v) for k, v in seen.items()},
                    "ctl": {a.name: [a.active, a.level] for a in ctl.adaptations},
                    "last": {k: v for k, v in ctl._last_change.items() if v > -1e8}, "log": [list(x) for x in ctl.log[-20:]]}
    return out


def import_adapt(camp: Campaign, data: dict) -> None:
    for hid, d in data.items():
        model, ctl, seen = _controller(camp, hid)
        model.weights.update({k: float(v) for k, v in d["w"].items()})
        model.t, model.samples = float(d["t"]), int(d["n"])
        seen.update({k: float(v) for k, v in d["seen"].items()})
        for a in ctl.adaptations:
            if a.name in d["ctl"]:
                a.active, a.level = bool(d["ctl"][a.name][0]), float(d["ctl"][a.name][1])
        for k, v in d["last"].items():
            ctl._last_change[k] = float(v)
        ctl.log = [tuple(x) for x in d.get("log", [])]


def adaptation_levels(camp: Campaign, hid: str) -> dict[str, float]:
    model, ctl, seen = _controller(camp, hid)
    for k, v in camp.habits.items():
        d = v - seen.get(k, 0)
        if d > 0:
            model.record(k, float(camp.turn), float(d))
            seen[k] = float(v)
    ctl.update(float(camp.turn), 1.0)
    return {a.name: a.level for a in ctl.adaptations}


# -------------------------------------------------------------------------------------------------- plan
def plan(camp: Campaign, hid: str) -> None:
    h = camp.houses[hid]
    if not h.alive:
        return
    personality = camp.rules.houses[hid]["personality"]
    arch = camp.rules.houses[hid]["archetype"]
    st = camp.ai_state.setdefault(hid, {})
    st.setdefault("cool", {})
    adapt = adaptation_levels(camp, hid)
    intel = Intel(camp, hid)
    rng = Rng(camp.seed).child("ai", hid, camp.turn)
    _research(camp, hid, arch, personality, rng)
    _diplomacy(camp, hid, personality, arch, rng, st)
    _economy(camp, hid, arch, personality, rng)
    _recruit(camp, hid, arch, personality, adapt, intel, rng)
    _military(camp, hid, personality, intel, rng, st)
    _expand(camp, hid, personality, rng)


# ----------------------------------------------------------------------------------------------- research
def _research(camp: Campaign, hid: str, arch: str, pers: dict, rng: Rng) -> None:
    h = camp.houses[hid]
    if h.research:
        return
    opts = camp.research_options(hid)
    if not opts:
        return
    pref = RESEARCH_PREF[arch]
    best, bs = None, -1e9
    for tid in opts:
        t = camp.rules.techs[tid]
        s = pref[t["branch"]] * 10 - t["cost"] * 0.18 + rng.random() * 1.5
        if t["tier"] >= 2:
            s += 1.0
        for e in t["effects"]:
            if e.get("kind") == "mod":
                k = e["key"]
                if k == "research_rate":
                    s += 2.5 * pers.get("scholarship", 0.5)
                if k.startswith("prod.") or k in ("storage", "trade_income"):
                    s += 1.5 * pers.get("commerce", 0.5)
                if k in ("morale", "army_move") or e.get("kind") == "unit_mod":
                    s += 1.5 * pers.get("aggression", 0.5)
                if k == "fort_level":
                    s += 2.0 * pers.get("caution", 0.5)
        if s > bs:
            best, bs = tid, s
    camp.set_research(hid, best)


# ----------------------------------------------------------------------------------------------- economy
def _economy(camp: Campaign, hid: str, arch: str, pers: dict, rng: Rng) -> None:
    h = camp.houses[hid]
    flow = camp.house_flow(hid)
    net = flow["net"]
    reserve = 12 + 4 * len(camp.armies_of(hid))
    built = 0
    max_builds = 2 + (1 if h.stock.get("coin", 0) > 150 else 0) + (1 if h.stock.get("coin", 0) > 400 else 0)
    provs = sorted(camp.provinces_of(hid), key=lambda p: p.id)
    threatened = {p.id for p in provs if any(camp.map.provinces[n].owner and camp.dp.at_war(hid, camp.map.provinces[n].owner)
                                            for n in camp.map.adj[p.id])}
    for p in sorted(provs, key=lambda p: (p.id != h.capital, p.id)):
        if built >= max_builds or h.stock.get("coin", 0) < reserve:
            break
        if p.queue:
            continue
        wants: list[tuple[float, str]] = []
        has = p.buildings
        for bid in camp.rules.buildings:
            ok, _ = camp.can_build(hid, p.id, bid)
            if not ok:
                continue
            s = _building_score(camp, hid, p, bid, net, pers, arch, p.id in threatened)
            if s > 0:
                wants.append((s + rng.random() * 0.2, bid))
        if wants:
            wants.sort(reverse=True)
            if wants[0][0] >= 1.0 and camp.build(hid, p.id, wants[0][1]):
                built += 1


def _building_score(camp: Campaign, hid: str, p, bid: str, net: dict, pers: dict, arch: str, threatened: bool) -> float:
    lvl = p.buildings.get(bid, 0)
    n_units = sum(len(a.units) for a in camp.armies_of(hid))
    s = 0.0
    eff = camp.rules.buildings[bid].get("effects", {})
    for res, table in eff.get("prod", {}).items():
        yield_ = table.get(p.terrain, table.get("default", 0))
        feat = eff.get("feature_bonus", {}).get(p.feature or "", {}).get(res, 0)
        v = yield_ + feat
        if v <= 0:
            continue
        need = {"grain": 2.4 if net["grain"] < 1.5 else 0.6, "coin": 1.4 + pers["commerce"], "ore": 1.0 + (0.8 if net["ore"] < 0.5 else 0),
                "timber": 1.2 if net["timber"] < 1 else 0.5, "salt": 0.5, "ink": 0.7 + pers["scholarship"] * 1.5}[res]
        s += v * need * (0.8 if lvl else 1.0)
    if bid in ("barracks",) and not p.buildings.get("barracks") and p.id != camp.houses[hid].capital:
        s += 0.5 + pers["aggression"] * 1.5 - (2.0 if sum(1 for q in camp.provinces_of(hid) if q.buildings.get("barracks")) >= 2 else 0)
    if bid == "stable":
        s += (pers["aggression"] * 2.0 if arch in ("expansionist",) else 0.2) - (3 if lvl == 0 and not p.buildings.get("barracks") else 0)
    if bid == "workshop":
        s += 1.5 * pers["aggression"] if "siegecraft" in camp.houses[hid].techs else -9
    if bid == "granary":
        s += 1.0 + (2.0 if net["grain"] < 0.5 else 0.0) * 1.0
    if bid == "fort":
        s += (2.5 if threatened else 0.0) + pers["caution"] * (1.5 if p.choke or threatened else 0.3) - (2.0 if lvl else 0.0)
    if bid == "watchtower":
        s += 1.0 if threatened else 0.0
    if bid == "hall_of_hours":
        s += (p.unrest - 30) / 12.0
    if bid == "market":
        s += 0.8 * pers["commerce"] + 0.3
    if bid == "scriptorium":
        s += pers["scholarship"] * 2.2
    if bid == "mine" and p.terrain in ("hill", "mountain"):
        s += 0.6 + (p.unrest > 40) * -2
    if p.unrest > 40 and camp.rules.buildings[bid].get("effects", {}).get("unrest", 0) > 0:
        s -= 2
    cost = sum(camp.building_cost(hid, bid, lvl + 1).values())
    s -= cost * 0.05
    if n_units > 12 and bid in ("barracks", "stable"):
        s -= 1.5
    return s


# ---------------------------------------------------------------------------------------------- recruiting
def _recruit(camp: Campaign, hid: str, arch: str, pers: dict, adapt: dict, intel: Intel, rng: Rng) -> None:
    h = camp.houses[hid]
    flow = camp.house_flow(hid)
    net_coin = flow["net"]["coin"]
    n_units = sum(len(a.units) for a in camp.armies_of(hid))
    n_prov = len(camp.provinces_of(hid))
    at_war = bool(camp.dp.enemies_of(hid))
    cap = 4 + n_prov * (1.4 + pers["aggression"] * 1.2) + (4 if at_war else 0) + min(18, h.stock.get("coin", 0) / 60.0)
    if n_units >= cap:
        return
    reserve = 8 + (0 if at_war else 10) - int(pers["aggression"] * 6)
    mix = dict(ARMY_MIX[arch])
    # counters to the player's observed habits (bounded by AdaptiveController levels)
    if adapt.get("anti_cavalry", 0) > 0.02:
        mix["pike"] = mix.get("pike", 1) * (1 + 3 * adapt["anti_cavalry"])
    if adapt.get("anti_ranged", 0) > 0.02:
        mix["cavalry"] = mix.get("cavalry", 1) * (1 + 3 * adapt["anti_ranged"])
        mix["skirmisher"] = mix.get("skirmisher", 1) * (1 + 2 * adapt["anti_ranged"])
    if adapt.get("anti_turtle", 0) > 0.02:
        mix["siege"] = mix.get("siege", 1) * (1 + 4 * adapt["anti_turtle"])
    have: dict[str, int] = {}
    for a in camp.armies_of(hid):
        for u in a.units:
            r = camp.rules.units[u.type]["role"]
            have[r] = have.get(r, 0) + 1
    made = 0
    sites = sorted([p for p in camp.provinces_of(hid) if camp.recruits_left(p.id) > 0], key=lambda p: (p.id != h.capital, p.id))
    for p in sites:
        while made < 3 and camp.recruits_left(p.id) > 0 and n_units + made < cap:
            if h.stock.get("coin", 0) < reserve:
                return
            if net_coin < -2.0 and n_units > 4 and not at_war:
                return
            cands = camp.recruitable(hid, p.id)
            if not cands:
                break
            best, bs = None, -1e9
            for uid in cands:
                u = camp.rules.units[uid]
                role = u["role"]
                cost = camp.unit_cost(hid, uid)
                if not h.can_afford(cost):
                    continue
                w = mix.get(role, 0.5)
                s = w / (1.0 + have.get(role, 0) * 0.9) + (0.4 if u.get("house") == hid else 0.0) + rng.random() * 0.15
                s -= sum(cost.values()) * 0.012
                if s > bs:
                    best, bs = uid, s
            if best is None or camp.recruit(hid, p.id, best) is None:
                break
            have[camp.rules.units[best]["role"]] = have.get(camp.rules.units[best]["role"], 0) + 1
            made += 1
        if made >= 3:
            break


# ----------------------------------------------------------------------------------------------- military
def _prov_value(camp: Campaign, p) -> float:
    v = 3.0 + sum(p.base.values()) * 0.8 + sum(p.buildings.values()) * 1.2
    if p.feature:
        v += 2.0
    if p.id in {h.capital for h in camp.houses.values()}:
        v += 8.0
    return v


def _military(camp: Campaign, hid: str, pers: dict, intel: Intel, rng: Rng, st: dict) -> None:
    h = camp.houses[hid]
    armies = [a for a in camp.armies_of(hid) if a.units]
    if not armies:
        return
    smap = camp.supply_map(hid)
    # merge stationary stacks sharing a province
    by_pid: dict[int, list] = {}
    for a in armies:
        if not a.path:
            by_pid.setdefault(a.pid, []).append(a)
    for pid, group in by_pid.items():
        group.sort(key=lambda a: a.id)
        base = group[0]
        for other in group[1:]:
            if len(base.units) < STACK_LIMIT:
                camp.merge(hid, base.id, other.id)
    armies = [a for a in camp.armies_of(hid) if a.units]
    enemies = camp.dp.enemies_of(hid)
    threats = _threats(camp, hid, intel, enemies)
    myprov = {p.id for p in camp.provinces_of(hid)}
    for a in sorted(armies, key=lambda x: -camp.army_strength(x)):
        if a.path:
            # re-check: abort a march into a province that has since become too strong
            tgt = a.path[-1]
            if tgt in myprov or camp.map.provinces[tgt].owner is None:
                continue
            if intel.enemy_strength(tgt, hid) > camp.army_strength(a) * 1.6:
                a.path = []
            else:
                continue
        mx = _army_max_hp(camp, a)
        hp_frac = sum(u.hp for u in a.units) / max(1.0, mx)
        s_me = camp.army_strength(a)
        # 1. damaged or unsupplied: go heal at the nearest supplied depot province
        if hp_frac < 0.55 or a.pid not in smap:
            dest = _nearest(camp, hid, a, lambda p: p.owner == hid and p.id in smap)
            if dest is not None and dest != a.pid:
                camp.order_move(hid, a.id, dest)
            continue
        if not enemies:
            _station(camp, hid, a, myprov, intel, st)
            continue
        # 2. defend a threatened province if the enemy outweighs the garrison
        threatened = sorted(threats.items(), key=lambda kv: -kv[1][0])
        defended = False
        for pid, (val, strength) in threatened:
            local = sum(camp.army_strength(x) for x in camp.armies_at(pid) if x.owner == hid)
            if strength > local * 0.8 and a.pid != pid and camp.find_path(hid, a.pid, pid) is not None:
                if len(camp.find_path(hid, a.pid, pid)) <= 3 and s_me + local > strength * 0.7:
                    camp.order_move(hid, a.id, pid)
                    defended = True
                    break
        if defended:
            continue
        # 3. attack the most attractive enemy province we can take
        best, bs = None, 0.0
        for p in camp.map.provinces:
            owner = intel.owner(p.id)
            if owner is None or owner not in enemies:
                continue
            path = camp.find_path(hid, a.pid, p.id)
            if path is None or len(path) > 6:
                continue
            defense = intel.enemy_strength(p.id, hid) + intel.fort(p.id) * 1.8
            need = (1.25 - 0.45 * pers["aggression"] + 0.25 * pers["caution"])
            if s_me < max(0.5, defense) * need:
                continue
            turns = camp.path_turns(a, path)
            score = _prov_value(camp, p) / (1.0 + defense * 0.5) - turns * 0.9
            if score > bs:
                best, bs = p.id, score
        if best is not None:
            camp.order_move(hid, a.id, best)
            camp.set_stance(hid, a.id, "pillage" if pers["aggression"] > 0.75 and rng.chance(0.3) else "march")
            continue
        _station(camp, hid, a, myprov, intel, st)


def _army_max_hp(camp: Campaign, a) -> float:
    from . import battle as B
    techs, m = camp.houses[a.owner].techs, camp.mods(a.owner)
    return sum(B.unit_stats(camp.rules, u, techs, m)["hp"] for u in a.units)


def _threats(camp: Campaign, hid: str, intel: Intel, enemies: list[str]) -> dict[int, tuple[float, float]]:
    """Own provinces an enemy army can reach within two moves -> (value, enemy strength)."""
    out: dict[int, tuple[float, float]] = {}
    mine = {p.id for p in camp.provinces_of(hid)}
    for pid in intel.vis:
        for a in camp.armies_at(pid):
            if a.owner in enemies:
                for q in camp._ball(pid, 2):
                    if q in mine:
                        val, s = out.get(q, (0.0, 0.0))
                        out[q] = (_prov_value(camp, camp.map.provinces[q]), s + camp.army_strength(a))
    return out


def _nearest(camp: Campaign, hid: str, a, pred) -> int | None:
    best, bd = None, 1e9
    for p in camp.map.provinces:
        if not pred(p):
            continue
        path = camp.find_path(hid, a.pid, p.id)
        if path is None:
            continue
        d = camp.path_turns(a, path)
        if d < bd:
            best, bd = p.id, d
    return best


def _station(camp: Campaign, hid: str, a, myprov: set[int], intel: Intel, st: dict) -> None:
    """No war to fight: sit on the most exposed border (or the capital) so garrisons are spread sensibly."""
    h = camp.houses[hid]
    best, bs = None, -1e9
    for pid in myprov:
        p = camp.map.provinces[pid]
        border = sum(1 for n in camp.map.adj[pid] if camp.map.provinces[n].owner not in (None, hid))
        garrison = sum(camp.army_strength(x) for x in camp.armies_at(pid) if x.owner == hid and x.id != a.id)
        s = border * 1.5 + (3 if pid == h.capital else 0) - garrison * 0.6 - 0.2 * _hex_dist(camp, a.pid, pid)
        if s > bs:
            best, bs = pid, s
    if best is not None and best != a.pid and not a.path:
        camp.order_move(hid, a.id, best)


def _hex_dist(camp: Campaign, a: int, b: int) -> int:
    from . import hexgrid
    pa, pb = camp.map.provinces[a], camp.map.provinces[b]
    return hexgrid.distance((pa.col, pa.row), (pb.col, pb.row))


# ---------------------------------------------------------------------------------------------- expansion
def _expand(camp: Campaign, hid: str, pers: dict, rng: Rng) -> None:
    h = camp.houses[hid]
    cost = camp.claim_cost(hid)
    if h.stock.get("coin", 0) < cost + 14 or pers["expansion"] < 0.3:
        return
    cands = []
    for p in camp.provinces_of(hid):
        for n in camp.map.adj[p.id]:
            q = camp.map.provinces[n]
            if q.owner is None and q.terrain != "mountain" or (q.owner is None and rng.chance(0.2)):
                v = _prov_value(camp, q) - (1.5 if q.unrest > 30 else 0)
                cands.append((v + rng.random(), n))
    if cands and rng.chance(0.5 + 0.4 * pers["expansion"]):
        cands.sort(reverse=True)
        camp.claim_neutral(hid, cands[0][1])


# --------------------------------------------------------------------------------------------- diplomacy
def _diplomacy(camp: Campaign, hid: str, pers: dict, arch: str, rng: Rng, st: dict) -> None:
    h = camp.houses[hid]
    cool = st["cool"]
    others = [o for o in camp.alive() if o != hid]
    # peace when it hurts
    for o in list(camp.dp.enemies_of(hid)):
        if cool.get(("peace", o), 0) > camp.turn:
            continue
        ratio = camp.power_ratio(hid, o)
        want = h.exhaustion > 14 + 18 * pers["aggression"] or ratio < 0.75
        if want:
            cool[("peace", o)] = camp.turn + 4
            camp.propose(hid, o, "peace")
    # treaties with neighbours
    nbrs = set(camp._neighbour_houses(hid))
    for o in others:
        if camp.dp.at_war(hid, o):
            continue
        if cool.get(("treaty", o), 0) > camp.turn:
            continue
        cool[("treaty", o)] = camp.turn + 5 + rng.randint(0, 3)
        op = camp.dp.opinion_of(hid, o)
        if not camp.dp.treaty(hid, o, "trade") and rng.chance(0.2 + 0.7 * pers["commerce"]) and op > -10:
            camp.propose(hid, o, "trade")
        elif not camp.dp.has_pact(hid, o) and (o in nbrs) and op > 5 and rng.chance(0.2 + 0.6 * pers["caution"]):
            camp.propose(hid, o, "pact")
        elif camp.dp.has_pact(hid, o) and not camp.dp.allied(hid, o) and op > 25 and \
                any(camp.dp.at_war(o, e) for e in camp.dp.enemies_of(hid)):
            camp.propose(hid, o, "alliance")
    # war
    if camp.turn < 6 or len(camp.dp.enemies_of(hid)) >= 1 + (1 if pers["aggression"] > 0.8 else 0):
        return
    if rng.random() > 0.25 + 0.5 * pers["aggression"] * pers["expansion"] + (0.15 if h.stock.get("coin", 0) > 300 else 0):
        return
    best, bs = None, 0.0
    for o in nbrs:
        if camp.dp.at_war(hid, o) or camp.dp.allied(hid, o):
            continue
        if camp.dp.truce.get((min(hid, o), max(hid, o)), 0) > camp.turn:
            continue
        ratio = camp.power_ratio(hid, o)
        pact = camp.dp.has_pact(hid, o)
        if pact and pers["honor"] > 0.4:
            continue
        s = (ratio - (1.3 - 0.4 * pers["aggression"])) * 4 + pers["grudge"] * 3 * (-camp.dp.opinion_of(hid, o) / 100.0 + 0.2) \
            + 3 * camp.dp.grievance.get((hid, o), 0.0) + (2.0 if pers["opportunism"] > 0.5 and o == camp.player and False else 0.0)
        if pact:
            s -= 3.0
        if camp.dp.trade_partners(hid).count(o):
            s -= 1.5
        if s > bs:
            best, bs = o, s
    if best is None or bs < 1.0:
        return
    if not camp.war_justified(hid, best) and arch == "scholar" and h.stock.get("ink", 0) >= 3:
        camp.fabricate_claim(hid, best)
    if camp.war_justified(hid, best) or pers["honor"] < 0.55:
        camp.declare_war(hid, best)
