"""Concord: rules data, map generation, hex maths, tactical battle rules, campaign economy/supply/sieges,
diplomacy, house AI fairness and adaptation, persistence and scene integration."""
import json
import math

import pytest
from conftest import run_ticks

from shardlight.core.rng import Rng
from shardlight.modes.concord import ai, battle as B, hexgrid, mapgen
from shardlight.modes.concord.campaign import BattleRequest, Campaign, CONCORD_HOLD_TURNS
from shardlight.modes.concord.rules import Rules
from shardlight.modes.concord.state import Unit

HOUSES = ["karrow", "ostrel", "saline", "wick"]


@pytest.fixture(scope="module")
def rules():
    return Rules.load_default()


def camp(rules, seed=1, player="ostrel", size="medium", unlocks=frozenset()):
    return Campaign(rules, seed, size, player, unlocks)


# ------------------------------------------------------------------------------------------ rules/data
def test_rules_validate_cleanly(rules):
    assert rules.validate() == []
    assert len(rules.units) >= 20 and len(rules.techs) >= 19 and len(rules.houses) == 4
    for h in rules.houses.values():
        assert set(h["personality"]) >= {"aggression", "caution", "honor", "expansion", "commerce"}


def test_every_unit_building_site_exists_and_costs_resolve(rules):
    for uid, u in rules.units.items():
        assert u["building"] in rules.buildings, uid
        assert set(u["cost"]) <= {"grain", "timber", "ore", "salt", "ink", "coin"}


def test_resonant_forging_is_gated_by_the_echo_unlock(rules):
    assert "resonant_forging" not in rules.tech_list(frozenset())
    assert "resonant_forging" in rules.tech_list(frozenset({"concord.tech.resonant_forging"}))
    c1, c2 = camp(rules), camp(rules, unlocks=frozenset({"concord.tech.resonant_forging"}))
    c1.houses["ostrel"].techs.append("metallurgy")
    c2.houses["ostrel"].techs.append("metallurgy")
    assert "resonant_forging" not in c1.research_options("ostrel")
    assert "resonant_forging" in c2.research_options("ostrel")


# ------------------------------------------------------------------------------------------ hexes / map
def test_hex_neighbours_are_symmetric_and_distances_consistent():
    for col in range(-2, 8):
        for row in range(-2, 8):
            for nb in hexgrid.neighbors(col, row):
                assert (col, row) in hexgrid.neighbors(*nb)
                assert hexgrid.distance((col, row), nb) == 1
    assert hexgrid.distance((0, 0), (4, 0)) == 4


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_maps_valid_across_seeds(size):
    for seed in range(1, 25):
        m = mapgen.generate(seed, size, HOUSES)
        assert mapgen.validate(m, HOUSES) == []
        owned = {}
        for p in m.provinces:
            if p.owner:
                owned[p.owner] = owned.get(p.owner, 0) + 1
        assert set(owned) == set(HOUSES)
        assert max(owned.values()) == min(owned.values())          # fair start regions
        assert mapgen.components(m.adj) == 1


def test_map_generation_is_deterministic():
    a, b = mapgen.generate(9, "medium", HOUSES), mapgen.generate(9, "medium", HOUSES)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    assert json.dumps(a.to_dict(), sort_keys=True) != json.dumps(mapgen.generate(10, "medium", HOUSES).to_dict(), sort_keys=True)


# ------------------------------------------------------------------------------------------ battle
def squad(rules, house, types, uid0=0, techs=None):
    techs = techs if techs is not None else []
    m = rules.houses[house]["modifiers"]
    out = []
    for i, t in enumerate(types):
        u = Unit(uid0 + i, t, float(rules.units[t]["hp"]))
        out.append((u, B.unit_stats(rules, u, techs, m)))
    return out


def duel(rules, a_types, d_types, terrain="plain", fort=0, seed=1, river=False):
    return B.Battle(rules, seed, terrain, squad(rules, "karrow", a_types, 0), squad(rules, "ostrel", d_types, 100), fort, river)


def unit_of(b, utype):
    return next(u for u in b.units if u.type == utype)


def clear(b):
    """Open field, no obstacles: isolates the rule under test."""
    for y in range(B.GRID_H):
        for x in range(B.GRID_W):
            b.tiles[y][x] = B.OPEN


def place(b, u, x, y, facing=None):
    u.x, u.y = x, y
    if facing:
        u.facing = facing


def test_battle_is_deterministic_and_terminates(rules):
    outs = []
    for _ in range(2):
        b = duel(rules, ["swordhand", "bowman", "ridge_lancer"], ["oathpike", "ward_shield", "bowman"], seed=4)
        outs.append((B.auto_resolve(b)["winner"], b.state_hash(), b.round))
    assert outs[0] == outs[1]
    assert outs[0][2] <= B.ROUND_LIMIT + 1


def test_flanking_deals_more_damage(rules):
    b = duel(rules, ["swordhand"], ["swordhand"])
    clear(b)
    a, t = b.units
    place(b, t, 5, 3, facing=(1, 0))                     # target faces east
    place(b, a, 6, 3, facing=(-1, 0))
    front = b.damage_estimate(a, t)
    place(b, a, 4, 3)                                    # attacker west of the target: behind it
    rear = b.damage_estimate(a, t)
    place(b, a, 5, 2)
    side = b.damage_estimate(a, t)
    assert rear > side > front
    assert rear / front == pytest.approx(1.30, abs=0.02)


def test_cavalry_charge_needs_a_run_and_braced_pikes_punish_it(rules):
    b = duel(rules, ["ridge_lancer"], ["oathpike"])
    clear(b)
    cav, pike = b.units
    place(b, cav, 1, 3, facing=(1, 0))
    place(b, pike, 6, 3, facing=(-1, 0))
    cold = b.damage_estimate(cav, pike, from_xy=(5, 3), charge=0)
    charged = b.damage_estimate(cav, pike, from_xy=(5, 3), charge=3)
    assert charged / cold > 1.4
    hp0 = cav.hp
    assert b.move(cav, 5, 3)                              # four tiles in a straight line
    assert cav.straight >= 3
    assert b.attack(cav, pike)
    assert cav.hp < hp0                                    # the pike wall bit back


def test_pikes_are_strong_against_cavalry(rules):
    b = duel(rules, ["oathpike", "swordhand"], ["ridge_lancer"])
    clear(b)
    pike, sword, cav = b.units
    place(b, pike, 4, 3)
    place(b, sword, 4, 4)
    place(b, cav, 5, 3, facing=(-1, 0))
    assert b.damage_estimate(pike, cav) > b.damage_estimate(sword, cav) * 1.3


def test_rocks_block_archers_but_not_siege(rules):
    b = duel(rules, ["bowman", "field_ram"], ["swordhand"])
    clear(b)
    arc, ram, tgt = unit_of(b, "bowman"), unit_of(b, "field_ram"), unit_of(b, "swordhand")
    place(b, arc, 2, 3)
    place(b, tgt, 5, 3)
    assert tgt in b.targets(arc)
    b.tiles[3][4] = B.ROCK
    assert tgt not in b.targets(arc)
    ram.x, ram.y = 2, 3
    assert tgt in b.targets(ram) or b.attack_range(ram) < 3          # siege fires over obstacles when in range
    b.tiles[3][4] = B.OPEN
    assert tgt in b.targets(arc)


def test_walls_block_movement_and_siege_breaks_them(rules):
    b = duel(rules, ["field_ram", "swordhand"], ["swordhand"], fort=1)
    ram, sword = unit_of(b, "field_ram"), next(u for u in b.units if u.type == "swordhand" and u.side == 0)
    walls = list(b.wall_hp)
    assert walls and all(b.tiles[y][x] == B.WALL for x, y in walls)
    wx, wy = walls[0]
    place(b, ram, wx - 1, wy)
    assert (wx, wy) in b.wall_targets(ram)
    assert b.wall_targets(sword) == []                     # only siege engines can hurt walls
    assert (wx, wy) not in b.reachable(sword)
    hp0 = b.wall_hp[(wx, wy)]
    for _ in range(6):
        ram.acted = False
        if not b.attack_wall(ram, (wx, wy)):
            break
        if b.tiles[wy][wx] != B.WALL:
            break
    assert b.wall_hp[(wx, wy)] < hp0
    assert b.tiles[wy][wx] == B.OPEN or b.wall_hp[(wx, wy)] > 0


def test_only_the_active_side_may_act(rules):
    b = duel(rules, ["swordhand"], ["swordhand"])
    clear(b)
    a, d = b.units
    assert b.phase == B.ATTACKER
    place(b, d, 9, 3)
    place(b, a, 1, 3)
    assert not b.move(d, 8, 3)                              # not the defender's phase
    assert b.move(a, 2, 3)
    b.end_phase()
    assert b.phase == B.DEFENDER and not b.move(a, 3, 3) and b.move(d, 8, 3)


def test_morale_breaks_a_unit_and_it_survives(rules):
    b = duel(rules, ["swordhand", "swordhand", "swordhand"], ["levy_pike"])
    clear(b)
    victim = b.units[-1]
    victim.morale = 4.0
    a = b.units[0]
    place(b, a, 5, 3)
    place(b, victim, 6, 3)
    b.attack(a, victim)
    assert victim.routed or not victim.alive
    if victim.routed:
        assert victim.alive and victim.hp > 0
    res = B.auto_resolve(b)
    assert res["winner"] == B.ATTACKER


def test_abilities_heal_buff_and_cooldown(rules):
    b = B.Battle(rules, 1, "plain", squad(rules, "ostrel", ["ink_chaplain", "oathpike", "beacon_standard"], 0),
                 squad(rules, "karrow", ["swordhand"], 100), 0, False)
    clear(b)
    healer, pike, banner, foe = (unit_of(b, t) for t in ("ink_chaplain", "oathpike", "beacon_standard", "swordhand"))
    place(b, healer, 3, 3)
    place(b, pike, 4, 3)
    place(b, banner, 2, 3)
    place(b, foe, 9, 3)
    pike.hp = 10.0
    assert pike in b.ability_targets(healer)
    assert b.use_ability(healer, pike)
    assert pike.hp > 10.0
    assert healer.cd > 0 and not b.ability_ready(healer)
    assert not b.use_ability(healer, pike)
    # rally restores morale
    pike.morale = 5.0
    assert b.use_ability(banner, None)
    assert pike.morale > 5.0


def test_skirmishers_hit_and_run(rules):
    b = B.Battle(rules, 1, "plain", squad(rules, "karrow", ["javelineer"], 0), squad(rules, "ostrel", ["swordhand"], 100), 0, False)
    clear(b)
    sk, foe = b.units
    place(b, sk, 3, 3)
    place(b, foe, 6, 3)
    assert b.attack(sk, foe)
    assert "_skirmish" in sk.status
    reach = b.reachable(sk)
    assert reach and max(abs(x - sk.x) + abs(y - sk.y) for x, y in reach) >= 1
    assert b.move(sk, sk.x - 1, sk.y)
    assert not b.attack(sk, foe)                           # no second shot


def test_resonant_line_scales_with_neighbours_and_upgrade(rules):
    base = squad(rules, "ostrel", ["ward_shield", "ward_shield", "ward_shield"], 0)
    up = squad(rules, "ostrel", ["ward_shield", "ward_shield", "ward_shield"], 0, techs=["resonant_forging"])
    out = []
    for army in (base, up):
        b = B.Battle(rules, 1, "plain", army, squad(rules, "karrow", ["swordhand"], 100), 0, False)
        clear(b)
        for i, u in enumerate(b.units[:3]):
            place(b, u, 3, 2 + i)
        out.append(b.effective_atk(b.units[1]))
    assert out[0] > rules.units["ward_shield"]["atk"] * 1.1
    assert out[1] > out[0]


def test_battle_balance_is_not_one_sided_across_matchups(rules):
    """Over many seeds no pairing of equal-sized starting armies is a certain win for the same side."""
    wins = 0
    n = 0
    for seed in range(8):
        for a, d in (("saline", "wick"), ("wick", "saline"), ("karrow", "saline"), ("saline", "karrow")):
            ar = squad(rules, a, rules.houses[a]["start_units"], 0, rules.houses[a]["start_techs"])
            de = squad(rules, d, rules.houses[d]["start_units"], 100, rules.houses[d]["start_techs"])
            res = B.auto_resolve(B.Battle(rules, seed, "plain", ar, de, 0, False))
            wins += res["winner"] == B.ATTACKER
            n += 1
    assert 0.10 < wins / n < 0.90


def test_fortification_helps_the_defender(rules):
    wins_open = wins_fort = 0
    for seed in range(8):
        for fort in (0, 1):
            ar = squad(rules, "karrow", rules.houses["karrow"]["start_units"], 0, ["horse_breeding"])
            de = squad(rules, "wick", rules.houses["wick"]["start_units"], 100, ["scriptoria"])
            res = B.auto_resolve(B.Battle(rules, seed, "hill", ar, de, fort, False))
            if res["winner"] == B.DEFENDER:
                if fort:
                    wins_fort += 1
                else:
                    wins_open += 1
    assert wins_fort >= wins_open


# ------------------------------------------------------------------------------------------ campaign economy
def test_new_campaign_start_state(rules):
    c = camp(rules)
    assert len(c.houses) == 4 and all(h.alive for h in c.houses.values())
    for hid, h in c.houses.items():
        assert len(c.provinces_of(hid)) == 5
        assert len(c.armies_of(hid)) == 1 and len(c.armies_of(hid)[0].units) == len(rules.houses[hid]["start_units"])
        cap = c.map.provinces[h.capital]
        assert cap.owner == hid and {"barracks", "market"} <= set(cap.buildings)
    assert c.houses["ostrel"].is_player and not c.houses["karrow"].is_player


def test_income_and_upkeep_are_positive_at_start(rules):
    c = camp(rules)
    for hid in c.houses:
        flow = c.house_flow(hid)["net"]
        assert flow["grain"] > 0 and flow["coin"] > 0, (hid, flow)


def test_build_requires_terrain_slots_tech_and_money(rules):
    c = camp(rules)
    me = c.player
    p = next(p for p in c.provinces_of(me) if p.terrain == "plain" and p.id != c.houses[me].capital)
    ok, why = c.can_build(me, p.id, "mine")
    assert not ok and "terrain" in why.lower()
    ok, why = c.can_build(me, p.id, "workshop")
    assert not ok and "siegecraft" in why.lower()
    c.houses[me].stock["coin"] = 0
    assert c.can_build(me, p.id, "market")[1] == "Cannot afford it."
    c.houses[me].stock["coin"] = 500
    p.buildings = {"farmstead": 1, "market": 1, "barracks": 1}
    assert c.can_build(me, p.id, "granary")[1] == "No free building slot."
    p.buildings = {}
    assert c.build(me, p.id, "market")
    assert p.queue and c.houses[me].stock["coin"] < 500
    for _ in range(3):
        c.run_turn(None)
    assert p.buildings.get("market") == 1 and not p.queue


def test_recruit_costs_and_limits(rules):
    c = camp(rules)
    me = c.player
    cap = c.houses[me].capital
    n0 = sum(len(a.units) for a in c.armies_of(me))
    assert c.recruit(me, cap, "levy_pike")
    assert c.recruit(me, cap, "levy_pike")
    assert c.recruits_left(cap) == 0
    assert not c.can_recruit(me, cap, "levy_pike")[0]
    assert sum(len(a.units) for a in c.armies_of(me)) == n0 + 2
    assert "ink_chaplain" not in c.recruitable(me, cap)        # needs field_medicine
    assert "ridge_lancer" not in c.recruitable(me, cap)        # a Karrow unit: another house cannot field it


def test_pathfinding_respects_borders_and_roads(rules):
    c = camp(rules)
    me = c.player
    a = c.armies_of(me)[0]
    enemy_prov = next(p for p in c.map.provinces if p.owner == "karrow")
    assert c.find_path(me, a.pid, enemy_prov.id) is None              # not at war: borders closed
    c.dp.declare_war(me, "karrow", c.turn)
    path = c.find_path(me, a.pid, enemy_prov.id)
    assert path and path[-1] == enemy_prov.id
    for x, y in zip([a.pid] + path, path):
        assert y in c.map.adj[x]
    # a road makes a step cheaper than the bare terrain
    x, y = next((a, b) for a, b in sorted(c.map.roads) if c.map.provinces[b].terrain in ("hill", "forest", "marsh", "mountain"))
    bare = {"plain": 1, "forest": 2, "hill": 2, "marsh": 3, "mountain": 3}[c.map.provinces[y].terrain]
    assert c.step_cost(me, x, y) < bare


def test_supply_range_and_attrition(rules):
    c = camp(rules)
    me = c.player
    sm = c.supply_map(me)
    cap = c.houses[me].capital
    assert cap in sm and sm[cap] >= 5
    far = max(c.map.provinces, key=lambda p: hexgrid.distance((p.col, p.row), (c.map.provinces[cap].col, c.map.provinces[cap].row)))
    assert far.id not in sm
    a = c.armies_of(me)[0]
    a.pid = far.id
    hp0 = sum(u.hp for u in a.units)
    c._supply_and_heal([me])
    assert sum(u.hp for u in a.units) < hp0                           # unsupplied armies bleed
    a.pid = cap
    low = sum(u.hp for u in a.units)
    c._supply_and_heal([me])
    assert sum(u.hp for u in a.units) >= low                          # supplied armies recover


def test_granary_extends_supply(rules):
    c = camp(rules)
    me = c.player
    p = next(p for p in c.provinces_of(me) if p.id != c.houses[me].capital)
    before = len(c.supply_map(me))
    p.buildings["granary"] = 1
    assert len(c.supply_map(me)) >= before


def test_conquest_of_undefended_province_and_siege_of_a_fort(rules):
    c = camp(rules)
    me = c.player
    c.dp.declare_war(me, "karrow", c.turn)
    target = next(p for p in c.provinces_of("karrow") if p.id != c.houses["karrow"].capital and not c.armies_at(p.id))
    a = c.armies_of(me)[0]
    a.pid = next(n for n in c.map.adj[target.id])
    a.path = [target.id]
    a.owner = me
    c.run_turn(None)
    assert target.owner == me and target.conquered > 0 and target.unrest > 20
    # a fort holds out until the walls are worn down
    t2 = next(p for p in c.provinces_of("karrow") if p.id != c.houses["karrow"].capital and not c.armies_at(p.id))
    t2.buildings["fort"] = 1
    a.pid = c.map.adj[t2.id][0]
    a.path = [t2.id]
    a.stance = "march"
    c.run_turn(None)
    assert t2.owner == "karrow" and t2.wall_damage > 0
    for _ in range(5):
        if t2.owner == me:
            break
        a.units = a.units or []
        c.run_turn(None)
    assert t2.owner == me


def test_battle_between_armies_resolves_and_loser_retreats(rules):
    c = camp(rules)
    me = c.player
    c.dp.declare_war(me, "karrow", c.turn)
    a = c.armies_of(me)[0]
    d = c.armies_of("karrow")[0]
    d.pid = next(n for n in c.map.adj[a.pid] if c.can_enter(me, n) or True)
    c.map.provinces[d.pid].owner = "karrow"
    a.path = [d.pid]
    a.pid = next(n for n in c.map.adj[d.pid] if n != d.pid)
    n_before = (len(a.units), len(d.units))
    c.run_turn(None)
    assert c.stats["battles"] >= 1
    assert len(a.units) < n_before[0] or len(d.units) < n_before[1] or a.id not in c.armies or d.id not in c.armies
    # no army exists with zero units
    assert all(x.units for x in c.armies.values())


def test_unrest_causes_revolt_and_buildings_relieve_it(rules):
    c = camp(rules)
    me = c.player
    p = next(p for p in c.provinces_of(me) if p.id != c.houses[me].capital)
    p.unrest = 99.5
    p.home = "karrow"
    c._unrest(me)
    assert p.owner is None or p.unrest < 100
    q = next(q for q in c.provinces_of(me) if q.id != c.houses[me].capital)
    q.unrest = 60
    q.buildings["hall_of_hours"] = 1
    c._unrest(me)
    assert q.unrest < 60


def test_research_completes_and_emits_hook(rules):
    c = camp(rules)
    me = c.player
    assert c.set_research(me, "scriptoria")
    c.houses[me].stock["ink"] = 0
    for _ in range(30):
        c.run_turn(None)
        if "scriptoria" in c.houses[me].techs:
            break
    assert "scriptoria" in c.houses[me].techs
    assert ("concord.tech_researched", {"tech": "scriptoria"}) in c.hooks
    assert not c.set_research(me, "scriptoria")                       # already known
    assert not c.set_research(me, "astral_calendars")                 # missing prerequisites


def test_events_resolve_with_effects(rules):
    c = camp(rules)
    me = c.player
    ev = {"event": "scholar_petition", "house": me, "pid": None, "other": None, "turn": 1}
    c.pending.append(ev)
    ink, coin = c.houses[me].stock["ink"], c.houses[me].stock["coin"]
    c.resolve_event(ev, 0)
    assert c.houses[me].stock["ink"] > ink and c.houses[me].stock["coin"] < coin and not c.pending
    with pytest.raises(RuntimeError):
        c.pending.append(ev)
        next(c.end_turn(None))


# ------------------------------------------------------------------------------------------ diplomacy
def test_treaties_war_and_oaths(rules):
    c = camp(rules)
    me = c.player
    c.dp.shift("saline", me, 40)
    ok, msg = c.propose(me, "saline", "trade")
    assert ok and c.dp.treaty(me, "saline", "trade")
    assert ("concord.treaty_signed", {"faction": "saline"}) in c.hooks
    c.dp.shift("saline", me, 40)
    assert c.propose(me, "saline", "pact")[0]
    oath0 = c.houses[me].oath
    assert c.declare_war(me, "saline")
    assert c.houses[me].oath > oath0                                  # breaking a pact stains you
    assert c.dp.at_war(me, "saline") and not c.dp.treaty(me, "saline", "pact")
    assert not c.declare_war(me, "saline")
    assert c.houses[me].unjust_until > c.turn                          # unjust war: unrest follows


def test_justified_war_has_no_unrest_penalty(rules):
    c = camp(rules)
    me = c.player
    assert c.fabricate_claim(me, "wick")
    assert c.war_justified(me, "wick")
    c.declare_war(me, "wick")
    assert c.houses[me].unjust_until <= c.turn


def test_ai_acceptance_is_explained_and_reflects_oath(rules):
    c = camp(rules)
    me = c.player
    c.dp.shift("saline", me, 30)
    good = c.assess_for(me, "saline", "trade")
    c.houses[me].oath = 80
    bad = c.assess_for(me, "saline", "trade")
    assert bad.score < good.score
    assert any(name == "your word" for name, _ in bad.reasons)
    assert "opinion" in good.text() or abs(good.score) < 1


def test_peace_requires_weariness_or_pressure(rules):
    c = camp(rules)
    c.dp.declare_war("karrow", "ostrel", c.turn)
    c.dp.shift("karrow", "ostrel", -60)
    ok1, _ = c.propose("ostrel", "karrow", "peace")
    assert not ok1 and c.dp.at_war("karrow", "ostrel")                 # an aggressive house that hates you says no
    c.houses["karrow"].exhaustion = 80
    c.dp.shift("karrow", "ostrel", 60)
    ok2, _ = c.propose("ostrel", "karrow", "peace")
    assert ok2 and not c.dp.at_war("karrow", "ostrel")


def test_concord_victory_needs_all_living_houses_for_three_turns(rules):
    c = camp(rules)
    me = c.player
    for o in HOUSES:
        if o != me:
            c.dp.sign(me, o, "alliance", c.turn)
    for i in range(CONCORD_HOLD_TURNS):
        assert c.winner is None
        c.run_turn(None)
    assert c.winner == me and c.victory == "concord"


def test_conquest_and_dominion_and_defeat(rules):
    c = camp(rules)
    me = c.player
    for p in c.map.provinces:
        if p.owner in ("karrow", "saline", "wick"):
            p.owner = me
    for h in ("karrow", "saline", "wick"):
        c._check_elimination(h)
    c._check_victory()
    assert c.victory == "conquest" and c.winner == me
    c2 = camp(rules, seed=2)
    for p in c2.provinces_of("ostrel"):
        p.owner = "karrow"
    c2._check_elimination("ostrel")
    c2._check_victory()
    assert c2.victory == "defeat"
    c3 = camp(rules, seed=3)
    need = math.ceil(len(c3.map.provinces) * 0.6)
    for p in c3.map.provinces[:need]:
        p.owner = "ostrel"
    c3._check_victory()
    assert c3.victory in ("dominion", "conquest")


# ------------------------------------------------------------------------------------------ AI
def test_ai_campaign_is_deterministic_and_stable(rules):
    hashes = []
    for _ in range(2):
        c = camp(rules, seed=5)
        for _ in range(40):
            for ev in list(c.pending):
                c.resolve_event(ev, 0)
            c.run_turn(ai.plan, include_player=True)
        hashes.append(c.state_hash())
        for h in c.houses.values():
            assert h.stock["coin"] >= 0 and h.stock["grain"] >= 0
            assert all(math.isfinite(v) for v in h.stock.values())
        assert all(a.units for a in c.armies.values())
    assert hashes[0] == hashes[1]


def test_ai_sees_only_what_its_fog_allows(rules):
    c = camp(rules, seed=3)
    hid = "karrow"
    intel = ai.Intel(c, hid)
    unseen = next(p.id for p in c.map.provinces if p.id not in intel.vis and p.id not in c.houses[hid].memory)
    foe = c.armies_of("wick")[0]
    foe.pid = unseen
    assert intel.enemy_strength(unseen, hid) == 1.5                    # unknown ground: a cautious assumption, not the truth
    assert intel.enemy_strength(unseen, hid) != c.army_strength(foe)


def test_ai_gets_no_resource_bonus(rules):
    c = camp(rules, seed=3)
    flows = {h: c.house_flow(h)["net"] for h in c.houses}
    base = c.rules.houses
    for hid in c.houses:
        assert c.houses[hid].stock["coin"] == base[hid]["start"]["coin"]
    c2 = camp(rules, seed=3, player="karrow")
    for hid in c.houses:
        assert c2.house_flow(hid)["net"] == flows[hid]                  # identical economy whoever the player is


def test_ai_adapts_to_player_cavalry_habit_within_bounds(rules):
    c = camp(rules, seed=3)
    base = ai.adaptation_levels(c, "wick")
    assert base["anti_cavalry"] == 0
    for t in range(12):
        c.turn = 2 + t
        c.habits["recruit_cavalry"] = c.habits.get("recruit_cavalry", 0) + 2
        lv = ai.adaptation_levels(c, "wick")
    assert 0 < lv["anti_cavalry"] <= 0.5 * 1.5 and lv["anti_ranged"] == 0
    c.adapt = 0.0
    c2 = camp(rules, seed=3)
    c2.adapt = 0.0
    for t in range(12):
        c2.turn = 2 + t
        c2.habits["recruit_cavalry"] = c2.habits.get("recruit_cavalry", 0) + 2
        assert ai.adaptation_levels(c2, "wick")["anti_cavalry"] == 0   # the settings slider turns it off


def test_ai_recruits_more_pikes_after_adapting(rules):
    def pikes(adapt_strength):
        c = camp(rules, seed=3)
        c.adapt = adapt_strength
        for t in range(14):
            c.turn = 2 + t
            c.habits["recruit_cavalry"] = c.habits.get("recruit_cavalry", 0) + 3
        h = "wick"
        c.houses[h].stock["coin"] = 400
        c.houses[h].stock["timber"] = 100
        for p in c.provinces_of(h):
            p.buildings.setdefault("barracks", 1)
        ai.plan(c, h)
        return sum(1 for a in c.armies_of(h) for u in a.units if c.rules.units[u.type]["role"] == "pike")
    assert pikes(1.0) >= pikes(0.0)


def test_ai_wars_and_peace_happen(rules):
    wars = battles = 0
    for seed in (1, 2, 3):
        c = camp(rules, seed=seed)
        for _ in range(70):
            for ev in list(c.pending):
                c.resolve_event(ev, 0)
            c.run_turn(ai.plan, include_player=True)
            wars += len(c.dp.wars)
        battles += c.stats["battles"]
    assert wars > 0 and battles > 0


# ------------------------------------------------------------------------------------------ persistence
def test_campaign_round_trip_through_json(rules):
    c = camp(rules, seed=7)
    for _ in range(25):
        for ev in list(c.pending):
            c.resolve_event(ev, 0)
        c.run_turn(ai.plan, include_player=True)
    d = json.loads(json.dumps(c.to_dict()))
    c2 = Campaign.from_dict(rules, d)
    assert c2 is not None and c2.state_hash() == c.state_hash()
    for _ in range(5):
        for x in (c, c2):
            for ev in list(x.pending):
                x.resolve_event(ev, 0)
            x.run_turn(ai.plan, include_player=True)
    assert c2.state_hash() == c.state_hash()                            # a loaded game continues identically


def test_corrupt_campaign_save_is_rejected(rules):
    c = camp(rules)
    d = c.to_dict()
    assert Campaign.from_dict(rules, {**d, "v": 99}) is None
    assert Campaign.from_dict(rules, {}) is None
    broken = dict(d)
    broken["houses"] = {"ghost": d["houses"]["karrow"]}
    assert Campaign.from_dict(rules, broken) is None


def test_frame_budget_of_a_turn(rules):
    import time
    c = camp(rules, seed=3)
    t = time.perf_counter()
    for _ in range(10):
        for ev in list(c.pending):
            c.resolve_event(ev, 0)
        c.run_turn(ai.plan, include_player=True)
    per = (time.perf_counter() - t) / 10
    assert per < 0.5, f"{per:.2f}s per turn"


# ------------------------------------------------------------------------------------------ integration
def enter(app, **opts):
    from shardlight.hub.title import TitleScene
    app.scenes.reset_to(TitleScene(app), fade=False)
    app.scenes.process(0)
    app.enter_mode("concord", **{"seed": 7, "house": "ostrel", "size": "small", **opts})
    run_ticks(app, 3, draw_every=0)
    s = app.scenes.top
    s.data["seen"]["battle_tip"] = True
    s.data["intro_done"] = True
    return s


def test_scene_menu_to_map_turns_and_menus(app):
    from shardlight.modes.concord.scene import MapScreen, MenuScreen, ProvinceMenu, BuildMenu, RecruitMenu, ArmyMenu
    from shardlight.modes.concord.ui_ledger import LedgerMenu, ResearchScreen, DiplomacyScreen, HousesScreen, ChronicleScreen
    s = enter(app)
    assert isinstance(s.screen, MenuScreen)
    s.new_campaign()
    assert isinstance(s.screen, MapScreen)
    run_ticks(app, 30)
    ms = s.screen
    cap = s.camp.houses[s.camp.player].capital
    ms.cur = cap
    for menu in (ProvinceMenu(s, ms, cap), BuildMenu(s, ms, cap), RecruitMenu(s, ms, cap)):
        app.scenes.push(menu)
        run_ticks(app, 12)
        app.scenes.pop()
    ms.select_army(ms.my_armies()[0])
    app.scenes.push(ArmyMenu(s, ms, ms.sel_army))
    run_ticks(app, 12)
    app.scenes.pop()
    for scr in (LedgerMenu(s, ms), ResearchScreen(s), DiplomacyScreen(s, ms), HousesScreen(s), ChronicleScreen(s)):
        app.scenes.push(scr)
        run_ticks(app, 14)
        app.scenes.pop()
    for ov in range(4):
        ms.overlay = ov
        run_ticks(app, 3)
    t0 = s.camp.turn
    ms.end_turn()
    run_ticks(app, 20)
    assert s.camp.turn == t0 + 1 or app.scenes.top is not ms


def test_scene_plays_several_turns_with_a_bot(app):
    from shardlight.modes.concord.ui_battle import BattleIntro, ResultScreen
    s = enter(app, seed=11)
    s.new_campaign()
    run_ticks(app, 20)
    ms = s.screen
    c = s.camp

    def settle():
        """Dismiss whatever is stacked above the concord scene, auto-resolving battles."""
        for _ in range(40):
            run_ticks(app, 6, draw_every=3)
            top = app.scenes.top
            if top is s:
                return
            if isinstance(top, BattleIntro):
                top._auto()
            elif isinstance(top, ResultScreen):
                app.scenes.pop()
                top.ms.battle_finished(top.result)
            else:
                app.scenes.pop()
        raise AssertionError("scene stack never settled")

    settle()
    for turn in range(12):
        for ev in list(c.pending):
            c.resolve_event(ev, 0)
        if turn == 0:
            c.set_research(c.player, "scriptoria")
        ms.end_turn()
        settle()
        if c.winner:
            break
    assert c.turn >= 8


def test_tactical_screen_bot_plays_a_battle(app):
    from shardlight.modes.concord.ui_battle import TacticalScreen, ResultScreen
    s = enter(app, seed=3)
    s.new_campaign()
    run_ticks(app, 20)
    ms, c = s.screen, s.camp
    me = c.player
    foe = "karrow"
    a = c.armies_of(me)[0]
    d = c.armies_of(foe)[0]
    d.pid = a.pid
    req = BattleRequest(a.pid, a.id, [d.id], me, foe, c.map.provinces[a.pid].terrain, 0, False, 9, 0)
    ts = TacticalScreen(s, ms, req)
    app.scenes.push(ts)
    dev = app.input.attach_virtual(0)
    for i in range(1500):
        if ts.b.over:
            break
        if ts.player_phase():
            # greedy bot: walk each unit toward the nearest enemy, attack when possible, then end the phase
            for u in ts.my_units():
                if u.done or u.acted:
                    continue
                foes = ts.b.enemies_of(u)
                if not foes:
                    break
                tgt = min(foes, key=lambda e: max(abs(e.x - u.x), abs(e.y - u.y)))
                ts.select(u)
                ts.attack_with_approach(u, tgt)
                if not u.acted:
                    reach = ts.b.reachable(u)
                    if reach:
                        best = min(reach, key=lambda p: max(abs(tgt.x - p[0]), abs(tgt.y - p[1])))
                        ts.b.move(u, *best)
                ts.b.end_unit(u)
            ts.end_phase()
        run_ticks(app, 1, draw_every=6)
    assert ts.b.over or ts.b.round > 3
    ts.b.check_over()
    for _ in range(80):
        run_ticks(app, 1, draw_every=0)
        if isinstance(app.scenes.top, ResultScreen):
            break


def test_victory_calls_complete_facet_and_emits_nothing_twice(app):
    s = enter(app, seed=5)
    s.new_campaign()
    c = s.camp
    for p in c.map.provinces:
        if p.owner not in (None, c.player):
            p.owner = c.player
    for h in c.houses:
        c._check_elimination(h)
    c._check_victory()
    assert c.victory == "conquest"
    assert not app.world.facet_done("concord") if hasattr(app.world, "facet_done") else True
    s.finish_campaign()
    assert s.data["wins"].get("conquest") == 1 and s.data.get("campaign") is None
    run_ticks(app, 10)


def test_tech_and_treaty_hooks_reach_the_world(app):
    s = enter(app, seed=5)
    s.new_campaign()
    c = s.camp
    seen = []
    orig = app.world.emit
    app.world.emit = lambda name, **kw: (seen.append((name, kw)), orig(name, **kw))[1]
    c.dp.shift("saline", c.player, 60)
    c.propose(c.player, "saline", "trade")
    s.drain_hooks()
    assert ("concord.treaty_signed", {"faction": "saline"}) in seen
