"""Verdant: content integrity, world generation (validity/determinism), interiors and dungeons, NPC schedules, combat and
bosses, quests (including the full main chain and the echo hand-offs), economy, persistence, rendering and scene flow."""
import copy
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import run_ticks

from shardlight.core.content import ContentDB
from shardlight.core.paths import DATA_DIR
from shardlight.modes.verdant import art, combat, interiors, npcs, worldgen
from shardlight.modes.verdant import tiles as T
from shardlight.modes.verdant.catalog import Catalog, register_content
from shardlight.modes.verdant.landmarks import template_problems
from shardlight.modes.verdant.sim import Game, Intent, skill_level

DT = 1 / 60


@pytest.fixture(scope="module")
def cat():
    return Catalog.load_default()


@pytest.fixture(scope="module")
def world7(cat):
    return worldgen.generate(7, cat.templates)


@pytest.fixture
def game(cat, world7):
    g = Game(cat, 7, world=copy.deepcopy(world7))
    g.p.x, g.p.y = g.over.start[0] + 0.5, g.over.start[1] + 0.5
    g.respawn_point = (g.p.x, g.p.y, "overworld")
    g.p.hp = g.max_hp()
    g.p.inv["rusty_sword"] = 1
    g.refresh_unlocks()
    from shardlight.modes.verdant import npcs as N
    N.place_all(g)
    return g


def step(g, secs=1.0, **kw):
    it = Intent(**kw)
    for _ in range(int(secs * 60)):
        g.update(DT, it)
        it = Intent(**{k: v for k, v in kw.items() if k in ("dx", "dy")})


def tp(g, x, y, area=None):
    if area and g.area != area:
        g.enter_area(area, (x, y))
    g.p.x, g.p.y = x, y


def spot(g, name):
    x, y = g.over.spots[name]
    return x + 0.5, y + 0.5


def spawn(g, kind, dx=2.0, dy=0.0):
    e = combat.Enemy(g, kind, g.p.x + dx, g.p.y + dy, "t", 0, 1)
    e.aggro = 10
    g.enemies.append(e)
    return e


def clear_around(g, r=6):
    wm = g.wm
    for y in range(int(g.p.y) - r, int(g.p.y) + r + 1):
        for x in range(int(g.p.x) - r, int(g.p.x) + r + 1):
            if 0 <= x < wm.W and 0 <= y < wm.H:
                if wm.obj[y, x] and T.OBJ_BLOCKS[wm.obj[y, x]]:
                    wm.obj[y, x] = 0
                if wm.ground[y, x] in (T.DEEP, T.CLIFF, T.VOID):
                    wm.ground[y, x] = T.GRASS
                g.cell_changed(g.area, x, y)


def god(g):
    g.p.hp = 1e9


# ------------------------------------------------------------------------------------------ content
def test_content_loads_without_problems(cat):
    assert cat.db.problems == []
    for kind in ("verdant.template", "verdant.item", "verdant.enemy", "verdant.npc", "verdant.quest", "verdant.shop", "verdant.recipe", "verdant.loot"):
        assert cat.db.ids(kind), kind


def test_templates_are_structurally_valid(cat):
    for tid, t in cat.templates.items():
        assert template_problems(t) == [], tid
    need = {p["template"] for p in worldgen.SETTLEMENT_PLAN + worldgen.SITE_PLAN}
    assert need <= set(cat.templates)


def test_content_cross_references(cat, world7):
    items = set(cat.db.ids("verdant.item"))
    for s in cat.db.all("verdant.shop"):
        assert {e["item"] for e in s["stock"]} <= items, s["id"]
        assert set(s.get("caravan", [])) <= items
    for r in cat.db.all("verdant.recipe"):
        assert set(r["inputs"]) <= items and r["out"] in items, r["id"]
    for l in cat.db.all("verdant.loot"):
        assert {e["item"] for e in l["entries"]} <= items, l["id"]
    for e in cat.db.all("verdant.enemy"):
        assert {d["item"] for d in e.get("drops", [])} <= items, e["id"]
    npc_ids = set(cat.db.ids("verdant.npc"))
    sites = set(world7.sites) | {"cairn_of_debts", "listening_stones"}
    for q in cat.db.all("verdant.quest"):
        assert q["giver"] in npc_ids, q["id"]
        for st in q["stages"]:
            if st["kind"] == "talk":
                assert st["target"] in npc_ids, q["id"]
                assert set(st.get("give", {})) <= items
            if st["kind"] == "have":
                assert st["target"] in items
            if st["kind"] == "kill":
                assert cat.db.get("verdant.enemy", st["target"]) is not None
            if st["kind"] == "visit":
                assert st["target"] in sites
            assert set(st.get("grant", {})) <= items
        assert set((q.get("reward") or {}).get("items", {})) <= items
        if q.get("requires", {}).get("quest"):
            assert cat.quest(q["requires"]["quest"]) is not None
    bids = {b.id: b for b in world7.buildings}
    for n in cat.db.all("verdant.npc"):
        if n.get("home"):
            assert n["home"] in bids, (n["id"], n["home"])
        if n.get("shop"):
            assert cat.shop(n["shop"]) is not None
        for e in n["schedule"]:
            kind, _, key = e["at"].partition(":")
            if kind == "in":
                assert key in bids, (n["id"], e["at"])
            elif kind == "at":
                assert key in world7.spots, (n["id"], e["at"])
            elif kind == "m":
                assert any(m.data.get("npc") == key for m in world7.markers), (n["id"], e["at"])
        # schedule covers the whole day without gaps
        hrs = [h / 2 for h in range(48)]
        assert all(any((e["from"] <= h < e["to"]) or (e["from"] > e["to"] and (h >= e["from"] or h < e["to"])) for e in n["schedule"]) for h in hrs), n["id"]
    for b in world7.buildings:
        if b.shop:
            assert cat.shop(b.shop) is not None, b.id
        if b.enter:
            assert b.enter in interiors.KIND_OF, b.enter


def test_every_sound_the_mode_plays_is_registered():
    from shardlight.core import audio
    from shardlight.modes.verdant import sfx  # noqa: F401
    src = ""
    for f in Path("shardlight/modes/verdant").glob("*.py"):
        src += f.read_text(encoding="utf-8")
    used = set(re.findall(r"sfx\(\"(verdant_[a-z_]+)\"\)", src)) | set(re.findall(r"self\.sfx\(\"(verdant_[a-z_]+)\"\)", src))
    used |= set(re.findall(r"audio\.play\(\"(verdant_[a-z_]+)\"", src))
    missing = [n for n in used if n not in audio._SFX_RECIPES]
    assert not missing, missing
    assert len(used) >= 20
    for n in sorted(used)[:6]:
        buf = audio._SFX_RECIPES[n]()
        assert len(buf) > 100 and np.isfinite(buf).all() and abs(buf).max() <= 1.0 + 1e-6


# ------------------------------------------------------------------------------------------ world generation
@pytest.mark.parametrize("seed", [1, 2, 3, 5, 8, 13, 21, 99])
def test_worlds_are_valid_for_many_seeds(cat, seed):
    wm = worldgen.generate(seed, cat.templates)
    assert wm.problems == [], wm.problems[:3]
    assert len(wm.sites) == len(worldgen.SETTLEMENT_PLAN) + len(worldgen.SITE_PLAN)
    assert wm.walk[wm.start[1], wm.start[0]]
    assert len(wm.caches) >= 4 and len(wm.spawns) >= 15 and len(wm.lamps) >= 20
    # kestrel bridge: broken at start, reachable after repair, key places reachable in both states
    assert worldgen.validate(wm) == []


def test_generation_is_deterministic_and_seed_dependent(cat):
    a = worldgen.generate(11, cat.templates)
    b = worldgen.generate(11, cat.templates)
    c = worldgen.generate(12, cat.templates)
    assert a.digest() == b.digest() != c.digest()


def test_settlements_have_doors_gates_and_entrances(world7):
    for sid in ("wickering", "tidewick", "harrow_cairn", "reedholm"):
        assert f"{sid}.front" in world7.spots and any(k.startswith(f"{sid}.gate") for k in world7.spots)
    assert world7.buildings and all(b.enter for b in world7.buildings)
    assert sum(1 for m in world7.markers if m.kind == "entrance") == 4


def test_interiors_and_dungeons(cat):
    for enter in interiors.KIND_OF:
        wm = interiors.build_interior(enter, 3)
        assert wm.walk[wm.start[1], wm.start[0]] and wm.exits["door"]
    for area in interiors.DUNGEONS:
        for seed in (1, 2, 3, 4, 5, 6):
            wm = interiors.build_dungeon(area, seed)
            assert wm.walk[wm.start[1], wm.start[0]]
            reach = interiors._flood(wm.walk, wm.start)
            for sp in wm.spawns:
                assert reach[sp["y"], sp["x"]]
            if interiors.DUNGEONS[area]["boss"]:
                assert any(sp["unique"] for sp in wm.spawns)
    a = interiors.build_dungeon("hollow_roots", 5)
    b = interiors.build_dungeon("hollow_roots", 5)
    assert np.array_equal(a.ground, b.ground) and np.array_equal(a.obj, b.obj)


def test_hidden_stones_reveal_with_unlock(game):
    st = game.over.sites["listening_stones"]
    assert st.hidden and not any(m.kind == "entrance" and m.data.get("area") == "listening_stones" and game.over.obj[m.y, m.x] == T.O["stairdown"]
                                 for m in game.over.markers)
    game.unlocks = lambda u: u == "verdant.site.listening_stones"
    game.refresh_unlocks()
    assert not st.hidden
    m = next(m for m in game.over.markers if m.data.get("area") == "listening_stones")
    assert game.over.obj[m.y, m.x] == T.O["stairdown"]


# ------------------------------------------------------------------------------------------ rendering
def test_all_art_renders(cat):
    import pygame
    for oid in range(T.OBJ_COUNT):
        s = art.obj_sprite(oid, 3)
        assert s.get_width() == 16 and s.get_height() == 16 * T.OBJ_LIST[oid].height, T.OBJ_LIST[oid].name
    for gid in range(len(T.GROUND_NAMES)):
        assert art.ground_tile(gid, 1).get_size() == (16, 16)
        assert art.edge_overlay(gid, 2, 1).get_size() == (16, 16)
    for e in cat.db.all("verdant.enemy"):
        for fi in range(4):
            assert art.creature(e["id"], fi, 1, int(e.get("size", 1) * 10)).get_width() > 8
    for style in art.STYLE_COLORS:
        assert art.building_sprite(style, 8, 5, 3, True, True, 5).get_width() == 128


# ------------------------------------------------------------------------------------------ time, NPCs
def test_day_night_cycle_and_lamps(game):
    game.clock = 12.0
    assert game.daylight() == 1.0 and not game.is_night()
    game.clock = 23.0
    assert game.is_night()
    # lighting a lamp needs a taper and persists until dawn
    lamp = game.over.lamps[0]
    tp(game, lamp["x"] + 0.5, lamp["y"] + 1.5)
    game.clock = 20.0
    assert game._act_obj("lamp", lamp["x"], lamp["y"]) is None
    assert game.count("taper") == 0 and (lamp["x"], lamp["y"]) not in game.lit
    game.give("taper", 2)
    game._act_obj("lamp", lamp["x"], lamp["y"])
    assert (lamp["x"], lamp["y"]) in game.lit and game.count("taper") == 1
    assert game.over.obj[lamp["y"], lamp["x"]] == T.O["lamp_lit"]
    game.clock = 5.9
    step(game, 6.0)
    assert not game.lit and game.over.obj[lamp["y"], lamp["x"]] == T.O["lamp"]


def test_lamplighters_return_after_the_debt_is_repaid(game):
    game.flags["debt_repaid"] = True
    game.clock = 18.4
    step(game, 3.0)
    assert len(game.lit) == len(game.over.lamps) > 20


def test_npcs_follow_schedules(game):
    game.clock = 12.0
    npcs.update(game, 0.0, teleport=True)
    s = game.npcs["wen_pell"]
    assert s.area == "b:wickering.store"
    game.clock = 23.0
    npcs.update(game, 0.0, teleport=True)
    assert game.npcs["wen_pell"].area == "b:wickering.cottage_a"
    sleepers = [n for n in game.npcs.values() if n.sleeping]
    assert sleepers
    for st in game.npcs.values():
        wm = game.area_map(st.area)
        assert wm.is_walk(int(st.x), int(st.y)), (st.id, st.area, st.x, st.y)


def test_visible_npc_walks_out_of_a_building_to_its_post(game):
    g = game
    g.clock = 16.9
    npcs.update(g, 0.0, teleport=True)
    st = g.npcs["marrow_pell"]
    assert st.area == "b:wickering.lamp_house"
    x, y = spot(g, "wickering.front")
    tp(g, x, y + 1)
    g.clock = 17.1                      # schedule says: go to the front
    for _ in range(60 * 30):
        npcs.update(g, DT)
        if st.area == "overworld" and math.hypot(st.x - x, st.y - y) < 0.6:
            break
    assert st.area == "overworld" and math.hypot(st.x - x, st.y - y) < 1.5


# ------------------------------------------------------------------------------------------ combat
def test_melee_kills_and_drops(game):
    clear_around(game)
    god(game)
    w = spawn(game, "wolf", 1.0, 0.0)
    w.stun = 99.0
    game.p.facing = 0
    n0 = game.kills.get("wolf", 0)
    for _ in range(12):
        w.x, w.y = game.p.x + 1.0, game.p.y            # knock-back moves it out of reach; stand it back up
        step(game, 0.6, attack=True)
        if w.dead:
            break
    assert w.dead and game.kills["wolf"] == n0 + 1
    assert game.drops or game.p.gold > 20
    assert game.skill("blade") >= 0 and game.p.xp["blade"] > 0


def test_bow_needs_arrows_and_hits(game):
    clear_around(game)
    god(game)
    game.p.equip["bow"] = "hunting_bow"
    game.p.facing = 0
    e = spawn(game, "bandit", 6.0, 0.0)
    e.aggro = 0
    e.st = "idle"
    step(game, 0.2, shoot=True)
    assert game.count("arrow") == 0 and not game.projectiles
    game.give("arrow", 6)
    for _ in range(6):
        step(game, 0.5, shoot=True)
    assert e.dead or e.hp < e.maxhp
    assert game.count("arrow") < 6


def test_enemies_attack_with_telegraph_and_roll_dodges(game):
    clear_around(game)
    e = spawn(game, "bandit", 1.1, 0.0)
    hp0 = game.p.hp
    seen_windup = False
    for _ in range(120):
        game.update(DT, Intent())
        seen_windup |= e.st == "windup"
        if game.p.hp < hp0:
            break
    assert seen_windup and game.p.hp < hp0
    # a roll through the strike avoids it (i-frames)
    game.p.hp = game.max_hp()
    game.p.inv_t = 0
    game.p.stamina = 100
    e.st, e.t, e.cd = "windup", 0.05, 0
    e.x, e.y = game.p.x + 0.8, game.p.y
    game.update(DT, Intent(roll=True, dx=0, dy=1))
    hp1 = game.p.hp
    step(game, 0.3)
    assert game.p.hp == hp1


def test_wolf_packs_surround_and_lunge(game):
    clear_around(game, 8)
    ws = [spawn(game, "wolf", 5.0 * math.cos(a), 5.0 * math.sin(a)) for a in (0.0, 2.1, 4.2)]
    for w in ws:
        w.zone = "pack"
    hp0 = game.p.hp
    angles = set()
    for _ in range(60 * 14):
        game.update(DT, Intent())
        for w in ws:
            if not w.dead and math.hypot(w.x - game.p.x, w.y - game.p.y) < 5.0:
                angles.add(int(math.degrees(math.atan2(w.y - game.p.y, w.x - game.p.x)) // 90) % 4)
        if game.p.hp < hp0 - 4 and len(angles) >= 3:
            break
    assert game.p.hp < hp0 and len(angles) >= 3


def test_adaptation_is_visible_bounded_and_can_be_disabled(game):
    # a melee-only habit produces shielded bandits, never beyond the bound
    for i in range(40):
        game.model.record("melee", game.t + i * 0.1)
    for _ in range(60):
        game.adapt.update(game.t + 40 + _ * 1.0, 1.0)
    lvl = game.adapt.level("guard")
    assert 0 < lvl <= 0.6 * 1.5
    guards = 0
    for i in range(200):
        e = combat.Enemy(game, "bandit", game.p.x + 5, game.p.y, "g", i, 200)
        guards += e.guard
    assert 0 < guards < 200
    # guarded bandits take reduced frontal damage with a visible "Guarded" message
    e = combat.Enemy(game, "bandit", game.p.x + 1, game.p.y, "g", 0, 1)
    e.guard = True
    e.facing = 180
    hp = e.hp
    combat.damage_enemy(game, e, 10.0, 1, 0, "melee")
    assert hp - e.hp == pytest.approx(3.0, abs=0.01)
    assert any(t["t"] == "Guarded" for t in game.texts)
    # strength 0 disables adaptation entirely
    g2 = Game(game.cat, 7, world=copy.deepcopy(game.over), adapt_strength=0.0)
    for i in range(60):
        g2.model.record("melee", i * 0.1)
    for k in range(40):
        g2.adapt.update(10 + k, 1.0)
    assert g2.adapt.level("guard") == 0.0


@pytest.mark.parametrize("boss", ["rook_captain", "debt_collector", "bell_warden", "root_mother"])
def test_bosses_use_telegraphed_patterns_and_drop_their_prize(game, boss):
    clear_around(game, 8)
    e = spawn(game, boss, 3.0, 0.0)
    game.p.facing = 0
    saw_hazard = saw_hit = False
    hp0 = game.p.hp = 1e9
    atk = set()
    for _ in range(60 * 40):
        game.p.hp = 1e9
        game.p.stamina = 100
        game.update(DT, Intent())
        saw_hazard |= bool(game.hazards) or bool(game.projectiles)
        if e.st == "windup":
            atk.add(e.aux.get("atk"))
        if e.dead:
            break
        if math.hypot(e.x - game.p.x, e.y - game.p.y) < 2.0:
            combat.damage_enemy(game, e, e.maxhp * 0.012, 1, 0, "melee")
    assert atk, "boss never wound up an attack"
    assert saw_hazard or "charge" in atk or "slash" in atk or "swing" in atk
    e.hp = 1.0
    combat.damage_enemy(game, e, 5.0, 1, 0, "melee")
    assert e.dead and game.flags.get(f"killed.{boss}")
    got = {d["item"] for d in game.drops}
    prize = {"rook_captain": "rook_cleaver", "debt_collector": "tallow_ledger", "bell_warden": "chapel_bell", "root_mother": "hollow_ember"}[boss]
    assert prize in got


def test_death_and_respawn(game):
    game.p.gold = 100
    game.p.hp = 1
    game.hurt_player(50, game.p.x + 1, game.p.y)
    game.update(DT, Intent())
    assert game.dead
    game.respawn()
    assert not game.dead and game.p.gold == 90 and game.p.hp > 0 and game.area == "overworld"


# ------------------------------------------------------------------------------------------ interaction
def test_chests_open_once_and_loot_is_deterministic(game):
    m = next(m for m in game.over.markers if m.kind == "chest")
    tp(game, m.x + 0.5, m.y + 1.5)
    g0 = game.p.gold
    r = game._open_chest("overworld", m.x, m.y)
    assert r and r["items"]
    assert game._open_chest("overworld", m.x, m.y) is None
    again = game.roll_loot(game.chests[("overworld", m.x, m.y)]["loot"], game.chests[("overworld", m.x, m.y)]["id"])
    assert dict(again) == dict(r["items"])
    assert game.p.gold > g0 or game.p.inv


def test_gathering_depletes_and_regrows(game):
    ys, xs = np.nonzero(game.over.obj == T.O["mushroom"])
    x, y = int(xs[0]), int(ys[0])
    tp(game, x + 0.5, y + 1.2)
    game._act_obj("mushroom", x, y)
    assert game.p.gather
    step(game, 2.0)
    assert game.count("bellcap") >= 1 and game.over.obj[y, x] == 0
    tp(game, x + 10.5, y + 10.5)
    game.clock = 12.0
    game.day += 6
    step(game, 1.2)
    assert game.over.obj[y, x] == T.O["mushroom"] and not game.depleted


def test_hidden_door_needs_three_knocks(game):
    c = next(c for c in game.over.caches if c["kind"] == "chime_door")
    x, y = c["x"], c["y"]
    assert game.over.obj[y, x] == T.O["hiddendoor"]
    tp(game, x + 0.5, y + 1.5)
    game._knock(x, y); game._knock(x, y)
    assert game.over.obj[y, x] == T.O["hiddendoor"]
    game._knock(x, y)
    assert game.over.obj[y, x] == 0


def test_buildings_stairs_and_leaving(game):
    b = next(b for b in game.over.buildings if b.id == "wickering.inn")
    tp(game, b.front[0] + 0.5, b.front[1] + 0.5)
    tg = game.interact_target()
    assert tg and tg["kind"] == "door"
    game.do_interact()
    assert game.area == "b:wickering.inn"
    ex = game.wm.exits["door"]
    tp(game, ex[0] + 0.5, ex[1] - 0.6)
    step(game, 1.0, dy=1.0)
    assert game.area == "overworld" and abs(game.p.x - (b.front[0] + 0.5)) < 0.1
    m = next(m for m in game.over.markers if m.data.get("area") == "hollow_roots")
    tp(game, m.x + 0.5, m.y + 0.6)
    game._stairs_down(m.x, m.y)
    assert game.area == "d:hollow_roots" and game.enemies is not None
    game.leave_area()
    assert game.area == "overworld"


def test_inn_rest_costs_gold_and_skips_to_morning(game):
    game.enter_area("b:wickering.inn")
    game.clock = 21.0
    game.p.hp = 10
    game.p.fever = True
    g0 = game.p.gold
    game.rest()
    assert game.p.gold == g0 - 10 and game.p.hp == game.max_hp() and not game.p.fever and 5.9 <= game.clock < 7.0


def test_signs_and_notices_describe_the_world(game):
    assert "Tidewick" in game.sign_text()
    assert "Wolves at the Gate" in game.notice_text() or "First Light" in game.notice_text()


# ------------------------------------------------------------------------------------------ economy
def test_shops_have_no_arbitrage_and_restock(game):
    sh = game.cat.shop("general")
    for it in {e["item"] for e in sh["stock"]}:
        assert game.sell_price(it, sh) <= game.buy_price(it, sh) * 0.6 or game.sell_price(it, sh) == 0
    game.p.gold = 500
    assert "Bought" in game.buy("general", "bandage")
    n = game.count("bandage")
    stock0 = dict((i, q) for i, q, _ in game.shop_items("general"))["bandage"]
    for _ in range(20):
        game.buy("general", "bandage")
    assert game.shop_items("general") and dict((i, q) for i, q, _ in game.shop_items("general"))["bandage"] == 0
    assert game.buy("general", "bandage") == "Sold out."
    game.on_new_day()
    assert dict((i, q) for i, q, _ in game.shop_items("general"))["bandage"] > 0
    game.p.gold = 1
    assert game.buy("general", "hunting_bow") == "Not enough gold."
    # selling quest items or things the shop does not buy is refused
    game.give("tallow_ledger")
    assert game.sell("general", "tallow_ledger") == "They will not buy that."
    gold = game.p.gold
    game.give("flax", 3)
    assert "Sold" in game.sell("general", "flax") and game.p.gold > gold
    assert game.sell("general", "iron_sword") in ("You have none.", "They will not buy that.")


def test_beacon_caravans_unlock_new_goods(game):
    before = {i for i, _, _ in game.shop_items("general")}
    assert "star_salt" not in before
    game.unlocks = lambda u: u == "verdant.trade.beacon_caravans"
    game.refresh_unlocks()
    after = {i for i, _, _ in game.shop_items("general")}
    assert {"star_salt", "beacon_lens"} <= after


def test_crafting_chain_and_skill_gates(game):
    game.give("iron_ore", 8)
    for _ in range(4):
        assert "Made" in game.craft("smelt")
    assert game.count("iron_ingot") == 4
    game.give("plank", 2)
    assert "Made" in game.craft("iron_sword") or game.craft_level() < 1
    assert game.craft("harrow_mail") == "Needs skill level 6."
    assert game.craft("stew") == "Missing materials."


def test_consumables_and_equipment(game):
    game.p.hp = 20
    game.give("bandage", 2)
    assert "Used" in game.use_item("bandage") and game.p.hp > 20
    game.p.hp = game.max_hp()
    assert "already" in game.use_item("bandage")
    game.give("iron_sword")
    assert "Equipped" in game.use_item("iron_sword") and game.weapon()["id"] == "iron_sword"
    game.give("studded_coat")
    game.use_item("studded_coat")
    assert game.armor() == 4
    hp = game.p.hp
    game.p.inv_t = 0
    game.hurt_player(10, 0, 0)
    assert hp - game.p.hp == pytest.approx(10 * (1 - 4 * 0.055), abs=0.01)


# ------------------------------------------------------------------------------------------ quests
def talk(g, npc):
    return g.finish_talk(npc)


def test_first_light_and_lamplighters_debt_chain(game):
    q = game.quests
    assert "first_light" in q.offerable(game, "marrow_pell")
    assert "lamplighters_debt" not in q.offerable(game, "marrow_pell")       # gated behind the first quest
    assert game.accept_quest("first_light")
    assert game.count("taper") == 6
    for lamp in game.over.lamps[:3]:
        tp(game, lamp["x"] + 0.5, lamp["y"] + 1.5)
        game._act_obj("lamp", lamp["x"], lamp["y"])
    assert q.stage("first_light")["kind"] == "talk"
    ok, msg = talk(game, "marrow_pell")
    assert ok and q.is_done("first_light") and game.flags["first_light"]
    assert "lamplighters_debt" in q.offerable(game, "marrow_pell")
    assert game.accept_quest("lamplighters_debt")
    for lamp in game.over.lamps[3:11]:
        tp(game, lamp["x"] + 0.5, lamp["y"] + 1.5)
        game._act_obj("lamp", lamp["x"], lamp["y"])
    assert q.stage("lamplighters_debt")["kind"] == "visit"
    fx, fy = game.over.sites["cairn_of_debts"].front
    tp(game, fx + 0.5, fy + 0.5)
    game.quests.on_visit_tick(game)
    assert q.stage("lamplighters_debt")["kind"] == "have"
    ok, msg = talk(game, "marrow_pell")
    assert not ok                                                              # no ledger yet
    game.give("tallow_ledger")
    assert q.stage("lamplighters_debt")["kind"] == "talk"
    gold = game.p.gold
    ok, msg = talk(game, "marrow_pell")
    assert ok and q.is_done("lamplighters_debt") and game.flags["debt_repaid"] and game.p.gold == gold + 90
    assert ("verdant.quest_completed", {"quest": "lamplighters_debt"}) in game.hooks
    assert ("lore", {"id": "debt_repaid"}) in game.hooks
    assert game.count("tallow_ledger") == 0


def test_full_great_quest_ends_in_the_great_lamp(game):
    game.flags["first_light"] = True
    game.quests.state["first_light"] = {"stage": 2, "progress": 0, "done": True}
    game.quests.state["lamplighters_debt"] = {"stage": 4, "progress": 0, "done": True}
    assert game.accept_quest("kindle_the_hollow")
    game.enter_area("b:hollow_hall.hall")
    gx, gy = game.wm.spots["greatlamp"]
    tp(game, gx + 0.5, gy + 0.5)
    game._act_obj("greatlamp", gx, gy - 1)                                     # cold without the ingredients
    assert game.quests.is_active("kindle_the_hollow")
    game.give("lamp_oil", 3)
    game.give("hollow_ember")
    assert game.quests.stage("kindle_the_hollow")["kind"] == "use"
    game._act_obj("greatlamp", gx, gy - 1)
    assert game.quests.is_done("kindle_the_hollow") and game.flags["hollow_kindled"]
    assert game.wm.obj[gy - 1, gx] == T.O["greatlamp_lit"]
    assert ("verdant.quest_completed", {"quest": "kindle_the_hollow"}) in game.hooks


def test_bridge_quest_repairs_the_kestrel_crossing(game):
    f = game.over.features["kestrel_bridge"]
    flat_before = [game.over.walk[y, x] for (x, y) in f.cells]
    assert not all(flat_before)
    assert game.accept_quest("kestrel_bridge")
    assert talk(game, "brisk") == (False, "You still need: 12 x Plank, 4 x Iron Ingot.")
    game.give("plank", 12)
    game.give("iron_ingot", 4)
    ok, msg = talk(game, "brisk")
    assert ok and game.flags["bridge_built"]
    assert all(game.over.walk[y, x] for (x, y) in f.cells)
    assert game.count("plank") == 0
    reach = worldgen.flood(game.over.walk, game.over.start)
    assert reach[f.cells[0][1], f.cells[0][0]] and reach[f.cells[-1][1], f.cells[-1][0]]


def test_kill_quests_count_only_after_acceptance(game):
    clear_around(game)
    god(game)
    game.kills["wolf"] = 3
    assert game.accept_quest("wolves_at_the_gate")
    for _ in range(5):
        e = spawn(game, "wolf", 1.0, 0.0)
        combat.damage_enemy(game, e, 999, 1, 0, "melee")
    assert game.quests.stage("wolves_at_the_gate")["kind"] == "talk"
    ok, msg = talk(game, "captain_vey")
    assert ok and game.count("iron_sword") == 1 and "the_rooks" in game.quests.offerable(game, "captain_vey")


def test_quest_target_pos_resolves_every_stage(game):
    """Each quest stage maps to a world point the guidance chevron can point at."""
    q = game.quests
    seen = 0
    for quest in game.cat.db.all("verdant.quest"):
        for si, st in enumerate(quest["stages"]):
            game.quests.state[quest["id"]] = {"stage": si, "progress": 0, "done": False}
            pos = q.target_pos(game, quest["id"])
            assert pos is not None, f"{quest['id']}#{si} {st['kind']} {st.get('target')} unresolvable"
            area, x, y = pos
            if area == "overworld":
                wm = game.over
            else:
                wm = game.area_map(area)
            assert 0 <= x < wm.W and 0 <= y < wm.H, (quest["id"], si, pos)
            seen += 1
    assert seen >= 20


def test_quest_target_crosses_areas(game):
    q = game.quests
    game.quests.state["kindle_the_hollow"] = {"stage": 2, "progress": 0, "done": False}       # use greatlamp
    b = next(b for b in game.over.buildings if b.id.startswith("hollow_hall"))
    pos = q.target_pos(game, "kindle_the_hollow")
    assert pos[0] == "overworld" and abs(pos[1] - (b.front[0] + 0.5)) < 0.01 and abs(pos[2] - (b.front[1] + 0.5)) < 0.01
    game.enter_area("b:hollow_hall.hall")                                                     # inside: snaps onto the lamp
    gx, gy = game.wm.spots["greatlamp"]
    pos = q.target_pos(game, "kindle_the_hollow")
    assert pos[0] == "b:hollow_hall.hall"
    assert abs(pos[1] - (gx + 0.5)) < 0.01 and abs(pos[2] - gy) <= 1.5
    game.enter_area("overworld", (b.front[0] + 0.5, b.front[1] + 1.5))                        # and back out again
    pos = q.target_pos(game, "kindle_the_hollow")
    assert pos[0] == "overworld"


def test_quest_target_snaps_onto_woken_foes(game):
    clear_around(game)
    god(game)
    game.quests.state["the_rooks"] = {"stage": 0, "progress": 0, "done": False}               # flag killed.rook_captain
    pos = game.quests.target_pos(game, "the_rooks")
    e = spawn(game, "rook_captain", 2.5, 1.0)
    pos2 = game.quests.target_pos(game, "the_rooks")
    assert pos2[0] == "overworld"
    assert abs(pos2[1] - e.x) < 0.01 and abs(pos2[2] - e.y) < 0.01
    assert pos is None or pos != pos2


def test_echo_gated_quest_and_topics(game):
    assert "choir_stones" not in game.quests.offerable(game, "edda_cairnkeeper")
    d = game.npc_dialogue("edda_cairnkeeper")
    assert [t["label"] for t in d["topics"]] == ["The Cairn of Debts"]
    game.unlocks = lambda u: u == "verdant.site.listening_stones"
    game.refresh_unlocks()
    assert "choir_stones" in game.quests.offerable(game, "edda_cairnkeeper")
    assert "The Stones" in [t["label"] for t in game.npc_dialogue("edda_cairnkeeper")["topics"]]
    assert game.accept_quest("choir_stones")
    m = next(m for m in game.over.markers if m.data.get("area") == "listening_stones")
    tp(game, m.x + 0.5, m.y + 0.6)
    game.quests.on_visit_tick(game)
    game._stairs_down(m.x, m.y)
    assert game.area == "d:listening_stones"
    tx, ty = game.wm.spots["tablet"]
    tp(game, tx + 0.5, ty + 0.5)
    game._act_obj("tablet", tx, ty - 1)
    assert ("verdant.site_explored", {"site": "listening_stones"}) in game.hooks and game.count("stone_rubbing") == 1


def test_shop_is_closed_when_the_keeper_is_away(game):
    game.clock = 12.0
    npcs.update(game, 0.0, teleport=True)
    game.enter_area("b:wickering.store")
    d = game.npc_dialogue("wen_pell")
    assert d["shop"] == "general"
    game.leave_area()
    d = game.npc_dialogue("wen_pell")
    assert d["shop"] == "" and d["shop_closed"]


# ------------------------------------------------------------------------------------------ persistence
def test_save_round_trip_preserves_state(cat, game):
    clear_around(game)
    game.accept_quest("first_light")
    game.give("iron_ore", 3)
    game.p.gold = 333
    game.flags["x"] = 1
    m = next(m for m in game.over.markers if m.kind == "chest")
    tp(game, m.x + 0.5, m.y + 1.5)
    game._open_chest("overworld", m.x, m.y)
    lamp = game.over.lamps[0]
    game.give("taper", 1)
    tp(game, lamp["x"] + 0.5, lamp["y"] + 1.5)
    game._act_obj("lamp", lamp["x"], lamp["y"])
    game.flags["bridge_built"] = True
    game.apply_flags()
    for i in range(30):
        game.model.record("melee", i)
    step(game, 3.0)
    raw = json.loads(json.dumps(game.to_dict()))
    g2 = Game.from_dict(cat, raw)
    assert g2 is not None
    raw2 = json.loads(json.dumps(g2.to_dict()))
    for k in raw:
        assert raw[k] == raw2[k], (k, raw[k], raw2[k]) if k != "disc" else k
    assert g2.over.obj[lamp["y"], lamp["x"]] == T.O["lamp_lit"] and (lamp["x"], lamp["y"]) in g2.lit
    f = g2.over.features["kestrel_bridge"]
    assert all(g2.over.walk[y, x] for (x, y) in f.cells)


def test_save_inside_a_dungeon_restores_the_area(cat, game):
    game.enter_area("d:cairn_of_debts")
    tp(game, game.wm.start[0] + 0.5, game.wm.start[1] + 0.5)
    raw = json.loads(json.dumps(game.to_dict()))
    g2 = Game.from_dict(cat, raw)
    assert g2.area == "d:cairn_of_debts" and abs(g2.p.x - game.p.x) < 1e-6
    g2.leave_area()
    assert g2.area == "overworld" and g2.p.x == pytest.approx(game.ret[0])


def test_bad_saves_are_rejected(cat):
    assert Game.from_dict(cat, {"v": 99}) is None
    assert Game.from_dict(cat, {"v": 1, "seed": 1}) is None


def test_long_simulation_is_stable_and_fast(game):
    clear_around(game)
    god(game)
    t0 = time.perf_counter()
    rnd = np.random.default_rng(3)
    for i in range(60 * 90):
        if i % 40 == 0:
            dx, dy = rnd.uniform(-1, 1, 2)
        game.update(DT, Intent(dx=float(dx), dy=float(dy), attack=(i % 50 == 0), roll=(i % 130 == 0)))
        assert math.isfinite(game.p.x) and math.isfinite(game.p.y) and 0 <= game.p.x < 256
    per = (time.perf_counter() - t0) / (60 * 90)
    assert per < 0.004, f"{per * 1000:.2f} ms per tick"


# ------------------------------------------------------------------------------------------ scene
def test_scene_flow_menu_to_world_dialogue_shop_journal_save(app):
    assert app.enter_mode("verdant", seed=7)
    run_ticks(app, 20)
    vs = app.scenes.top
    vs.new_world()
    run_ticks(app, 10)
    g = vs.game
    assert vs.screen.__class__.__name__ == "GameScreen"
    while app.scenes.top is not vs:                                           # dismiss the intro card
        app.input.attach_virtual(0).tap("CONFIRM")
        run_ticks(app, 8)
    dev = app.input.attach_virtual(0)
    for i in range(600):
        if i % 30 == 0:
            dev.release_all()
            dev.hold(*(["RIGHT"] if i % 60 == 0 else ["DOWN", "A"]))
        run_ticks(app, 1, draw_every=3)
    dev.release_all()
    # dialogue with the nearest NPC via the real screens
    from shardlight.modes.verdant.screens import CraftScreen, DialogueScreen, JournalScreen, ShopScreen
    g.clock = 12.0
    npcs.update(g, 0.0, teleport=True)
    g.enter_area("b:wickering.store")
    g.p.x, g.p.y = g.npcs["wen_pell"].x + 1.0, g.npcs["wen_pell"].y + 1.2
    run_ticks(app, 5)
    app.scenes.push(DialogueScreen(vs, g, "wen_pell"))
    run_ticks(app, 20)
    d = app.scenes.top
    assert isinstance(d, DialogueScreen) and any(i.label == "Trade" for i in d.menu.items)
    app.scenes.push(ShopScreen(vs, g, "general"))
    run_ticks(app, 20)
    dev.tap("L")
    run_ticks(app, 5)
    dev.tap("CONFIRM")
    run_ticks(app, 5)
    app.scenes.pop(); app.scenes.pop()
    run_ticks(app, 3)
    app.scenes.push(CraftScreen(vs, g, "bench"))
    run_ticks(app, 10)
    app.scenes.pop()
    for tab in range(5):
        j = JournalScreen(vs, g)
        j.tab = tab
        app.scenes.push(j)
        run_ticks(app, 8)
        app.scenes.pop()
        run_ticks(app, 2)
    vs.save_game()
    app.return_to_hub()
    run_ticks(app, 10)
    assert app.enter_mode("verdant")
    run_ticks(app, 10)
    vs2 = app.scenes.top
    assert vs2.continue_world()
    run_ticks(app, 20)
    assert vs2.game.seed == g.seed and vs2.game.area == g.area


def test_world_events_reach_the_echo_system(app):
    assert app.enter_mode("verdant", seed=7)
    run_ticks(app, 10)
    vs = app.scenes.top
    vs.new_world()
    run_ticks(app, 5)
    g, w = vs.game, app.world
    g.hook("lore", id="debt_repaid")
    g.hook("verdant.quest_completed", quest="lamplighters_debt")
    vs.drain_hooks()
    assert w.has_unlock("umbra.item.lantern_ward")
    g.hook("verdant.quest_completed", quest="kindle_the_hollow")
    vs.drain_hooks()
    assert w.facet_repaired("verdant")
    # the Choir Signal path: an Orrery decode unlocks the stones, which then appear in this world
    w.unlock("verdant.site.listening_stones")
    g.refresh_unlocks()
    assert not g.over.sites["listening_stones"].hidden
    g.hook("verdant.site_explored", site="listening_stones")
    vs.drain_hooks()
    assert w.has_unlock("cinder.boss.choir_warden")


def test_frame_budget_town_and_forest(app):
    assert app.enter_mode("verdant", seed=7)
    run_ticks(app, 10)
    vs = app.scenes.top
    vs.new_world()
    run_ticks(app, 5)
    while app.scenes.top is not vs:
        app.scenes.pop()
        run_ticks(app, 2)
    g = vs.game
    g.clock = 12.0
    for where in ("wickering.front",):
        x, y = spot(g, where)
        tp(g, x, y)
        vs.screen.snap_camera()
        run_ticks(app, 10)
        t0 = time.perf_counter()
        for _ in range(60):
            app.tick(DT)
            app.render()
        per = (time.perf_counter() - t0) / 60
        assert per < 0.03, f"{per * 1000:.1f} ms/frame in town"
    fx, fy = g.over.sites["hollow_roots"].front
    tp(g, fx + 0.5, fy + 0.5)
    vs.screen.snap_camera()
    run_ticks(app, 10)
    t0 = time.perf_counter()
    for _ in range(60):
        app.tick(DT)
        app.render()
    per = (time.perf_counter() - t0) / 60
    assert per < 0.03, f"{per * 1000:.1f} ms/frame in forest"


def test_menu_and_all_screens_render_at_large_text_scale(app):
    app.settings.set("access.text_scale", 2) if hasattr(app.settings, "set") else None
    app.apply_settings()
    assert app.enter_mode("verdant", seed=3)
    run_ticks(app, 12)
    vs = app.scenes.top
    vs.new_world()
    run_ticks(app, 6)
    g = vs.game
    from shardlight.modes.verdant.screens import DeathOverlay, JournalScreen, RestOverlay, TextOverlay
    for sc in (TextOverlay(app, "T", "Hello " * 40), RestOverlay(vs, g), DeathOverlay(vs, g), JournalScreen(vs, g)):
        app.scenes.push(sc)
        run_ticks(app, 6)
        app.scenes.pop()
        run_ticks(app, 2)


def test_a_data_only_mod_adds_an_npc_quest_item_and_recipe(cat, world7):
    """The shipped sample mod extends Verdant without code: a new NPC offers a quest that uses base-game enemies."""
    from shardlight.core.mods import ModManager
    from shardlight.core.paths import EXAMPLES_DIR as MODS_DIR
    db = ContentDB()
    register_content(db)
    db.load_dir(DATA_DIR, "base")
    mm = ModManager(MODS_DIR)
    mm.discover()
    mm.apply(db)
    assert "sample_pack" in mm.loaded
    c2 = Catalog(db)
    g = Game(c2, 7, world=copy.deepcopy(world7))
    from shardlight.modes.verdant import npcs as N
    N.place_all(g)
    assert "sample_pack_traveller" in g.npcs and g.npcs["sample_pack_traveller"].area == "overworld"
    assert "sample_pack_errand" in g.quests.offerable(g, "sample_pack_traveller")
    assert g.accept_quest("sample_pack_errand")
    clear_around(g)
    for _ in range(2):
        e = spawn(g, "wolf", 1.0, 0.0)
        combat.damage_enemy(g, e, 999, 1, 0, "melee")
    ok, msg = g.finish_talk("sample_pack_traveller")
    assert ok and g.count("sample_pack_charm") == 1 and g.count("sample_pack_tea") == 2
    g.give("heather_sprig"); g.give("reedmint")
    assert "Made" in g.craft("sample_pack_tea")


def test_leaving_through_the_pause_menu_keeps_the_journey(app):
    from shardlight.core.ui import PauseMenu
    assert app.enter_mode("verdant", seed=5)
    run_ticks(app, 10)
    vs = app.scenes.top
    vs.new_world()
    run_ticks(app, 5)
    while app.scenes.top is not vs:
        app.scenes.pop()
        run_ticks(app, 2)
    vs.game.p.gold = 777
    vs.game.flags["marker"] = True
    pm = PauseMenu(app, vs)
    app.scenes.push(pm)
    run_ticks(app, 5)
    pm._leave()
    run_ticks(app, 10)
    assert app.scenes.top.__class__.__name__ == "HubScene"
    assert app.enter_mode("verdant")
    run_ticks(app, 10)
    vs2 = app.scenes.top
    assert vs2.continue_world() and vs2.game.p.gold == 777 and vs2.game.flags["marker"]
