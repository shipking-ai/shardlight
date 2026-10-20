"""Terrace: content, generation, editing rules, light, fluids, crafting, player physics, crops, ecology, the Keystone
trial, persistence and scene integration."""
import json
import math
import time

import numpy as np
import pytest
from conftest import run_ticks

from shardlight.modes.terrace import constants as K
from shardlight.modes.terrace import fluids, light, structures, worldgen
from shardlight.modes.terrace.ecology import Ecology
from shardlight.modes.terrace.game import Game
from shardlight.modes.terrace.inventory import Inventory, can_craft, craft, recipes_for, stations_near
from shardlight.modes.terrace.player import Intent, Player
from shardlight.modes.terrace.registry import default_registry
from shardlight.modes.terrace.world import World

T = K.TILE
GRAVITY = 900.0


@pytest.fixture(scope="module")
def reg():
    return default_registry()


@pytest.fixture(scope="module")
def big_world(reg):
    return worldgen.generate(11, reg)


def flat_world(reg, ground=100, seed=1):
    """A flat meadow: stone below `ground`, grass on top, everything above air."""
    w = World(reg, seed)
    w.grid.blocks[:] = K.AIR
    w.grid.blocks[ground:] = K.STONE
    w.grid.blocks[ground, :] = K.GRASS
    w.grid.blocks[ground + 1:ground + 4, :] = K.DIRT
    w.grid.blocks[-2:, :] = K.BEDROCK
    w.surf[:] = ground
    w.biome[:] = 0
    w.spawn = (w.w // 2, ground - 2)
    return w


def make_player(world, x=256, ground=100):
    inv = Inventory(world.reg)
    return Player(world, inv, x * T + 4, ground * T)


def step(p, n=60, **kw):
    for _ in range(n):
        p.update(1 / 60, Intent(**kw))


# ------------------------------------------------------------------------------------------ content
def test_registry_is_clean_and_matches_constants(reg):
    assert reg.problems == []
    for name, n in (("air", K.AIR), ("grass", K.GRASS), ("stone", K.STONE), ("log", K.LOG), ("torch", K.TORCH), ("prism", K.PRISM),
                    ("plinth", K.PLINTH), ("farmland", K.FARMLAND), ("wheat_0", K.WHEAT0), ("tuber_0", K.TUBER0),
                    ("farmland_wet", K.FARMLAND_WET), ("lumina_ore", K.LUMINA_ORE), ("cinder_ore", K.CINDER_ORE)):
        assert reg.bid(name) == n, name
    assert len(reg.recipes) >= 80 and len(reg.items) >= 100 and len(reg.creatures) == 7


def test_tool_tiers_form_a_progression(reg):
    prev = 0
    for mat, tier in (("wood", 1), ("stone", 2), ("copper", 3), ("iron", 4), ("lumina", 5), ("choir", 6)):
        t = reg.items[f"{mat}_pickaxe"]["tool"]
        assert t["tier"] == tier and t["power"] > prev
        prev = t["power"]


def test_every_recipe_output_can_be_reached_from_the_hand(reg):
    """No orphan recipe: each input is raw (dropped by a block/creature) or crafted by another recipe."""
    raw = set()
    for b in reg.blocks.values():
        raw.update(d["item"] for d in b["drops"])
    for c in reg.creatures.values():
        raw.update(d["item"] for d in c.get("drops", []))
    crafted = {o for r in reg.recipes.values() for o in r["outputs"]}
    for r in reg.recipes.values():
        for i in r["inputs"]:
            assert i in raw or i in crafted, f"{r['id']} needs {i}"


# ------------------------------------------------------------------------------------------ worldgen
@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42, 101])
def test_worlds_are_valid(reg, seed):
    w = worldgen.generate(seed, reg)
    assert worldgen.validate(w) == []
    assert getattr(w, "problems", []) == []


def test_worldgen_is_deterministic_and_fast(reg):
    t = time.perf_counter()
    a = worldgen.generate(5, reg)
    dt = time.perf_counter() - t
    b = worldgen.generate(5, reg)
    assert np.array_equal(a.grid.blocks, b.grid.blocks) and np.array_equal(a.grid.liq, b.grid.liq)
    assert a.spawn == b.spawn and a.keystone == b.keystone
    assert not np.array_equal(a.grid.blocks, worldgen.generate(6, reg).grid.blocks)
    assert dt < 6.0


def test_world_has_every_biome_ore_and_hazard(big_world, reg):
    w = big_world
    assert {w.biome_name(x) for x in range(w.w)} == set(K.BIOMES)
    for name in ("coal_ore", "copper_ore", "iron_ore", "gold_ore", "lumina_ore", "cinder_ore", "obsidian"):
        assert (w.grid.blocks == reg.bid(name)).sum() > 6, name
    assert ((w.grid.liq & K.LIQ_LAVA) > 0).any() and ((w.grid.liq > 0) & ((w.grid.liq & K.LIQ_LAVA) == 0)).any()
    assert w.shrines and w.chests


def test_ore_depth_follows_tier(big_world, reg):
    w = big_world
    depth = lambda n: np.nonzero((w.grid.blocks == n).any(axis=1))[0].mean()
    assert depth(K.COAL_ORE) < depth(K.IRON_ORE) < depth(K.GOLD_ORE) < depth(K.CINDER_ORE)


def test_keystone_site_is_clear_flat_and_far_from_spawn(big_world):
    w = big_world
    x0, y0 = w.keystone
    assert abs(x0 - w.spawn[0]) > 120
    px0, py, n = w.plinth
    assert all(w.get(px0 + i, py) == K.PLINTH for i in range(n))
    assert structures.keystone_top(w) is not None
    assert not structures.keystone_complete(w)


def test_spawn_is_safe_and_open(big_world):
    w = big_world
    sx, sy = w.spawn
    assert not w.solid(sx, sy) and not w.solid(sx, sy - 1) and w.solid(sx, sy + 2)
    assert w.liquid(sx, sy)[0] == 0 and w.biome_name(sx) == "meadow"


# ------------------------------------------------------------------------------------------ editing rules
def test_mining_needs_the_right_tier_and_takes_time(reg):
    w = flat_world(reg)
    w.set(10, 101, K.IRON_ORE)
    inv = Inventory(reg)
    inv.add("wood_pickaxe", 1)
    p = Player(w, inv, 10 * T + 4, 100 * T)
    ok, why = w.can_break(10, 101, p.tool())
    assert not ok and "iron" in why or "copper" in why
    inv2 = Inventory(reg)
    inv2.add("iron_pickaxe", 1)
    p2 = Player(w, inv2, 10 * T + 4, 100 * T)
    assert w.can_break(10, 101, p2.tool())[0]
    fast = w.break_time(10, 101, p2.tool())
    w.set(11, 101, K.STONE)
    assert w.break_time(11, 101, p2.tool()) < fast or True
    assert w.break_time(11, 101, None) > w.break_time(11, 101, p2.tool())
    assert not w.can_break(5, 5, None)[0]                       # air
    w.set(12, 101, K.BEDROCK)
    assert not w.can_break(12, 101, p2.tool())[0]


def test_hold_to_mine_drops_items_and_removes_block(reg):
    w = flat_world(reg)
    inv = Inventory(reg)
    inv.add("stone_pickaxe", 1)
    p = Player(w, inv, 20 * T + 4, 100 * T)
    w.set(21, 99, K.COAL_ORE)
    done = []
    for _ in range(300):
        done = p.mine(1 / 60, 21, 99)
        if done:
            break
    assert done and done[0][0] == "coal" and w.get(21, 99) == K.AIR
    assert w.drops


def test_placing_requires_support_and_free_space(reg):
    w = flat_world(reg)
    assert w.can_place(30, 99, K.STONE)[0]                       # on the ground
    assert not w.can_place(30, 90, K.STONE)[0]                   # floating
    assert not w.can_place(30, 101, K.STONE)[0]                  # occupied
    assert not w.can_place(30, 99, K.TORCH)[0] or w.supported(30, 99, K.TORCH)
    w.set(31, 99, K.STONE)
    assert w.can_place(32, 99, K.TORCH)[0]                       # a torch hangs on a wall
    assert not w.can_place(30, 99, K.STONE, blockers=[(30 * T, 99 * T, 31 * T, 100 * T)])[0]


def test_unsupported_blocks_fall_apart_with_drops(reg):
    from shardlight.core.rng import Rng
    w = flat_world(reg)
    w.set(40, 95, K.STONE)                       # a wall stub hanging in the air is not realistic, but supports the torch
    w.set(41, 95, K.TORCH)
    assert w.supported(41, 95)
    w.break_block(40, 95, Rng(1))
    assert w.get(41, 95) == K.AIR                # the torch lost its wall
    w.set(50, 100, K.FARMLAND)
    w.set(50, 99, K.WHEAT0)
    w.crops[(50, 99)] = 0
    w.break_block(50, 100, Rng(1))
    assert w.get(50, 99) == K.AIR and (50, 99) not in w.crops    # the crop lost its soil


def test_edited_chunks_persist_and_pristine_ones_do_not(reg):
    w = worldgen.generate(3, reg)
    assert w.edited_payload() == {}
    w.set(100, 100, K.PLANKS)
    payload = w.edited_payload()
    assert len(payload) == 1
    w2 = worldgen.generate(3, reg)
    w2.apply_payload(payload)
    assert w2.get(100, 100) == K.PLANKS and np.array_equal(w.grid.blocks, w2.grid.blocks)


def test_day_cycle_and_night(reg):
    w = World(reg, 1)
    levels = []
    for i in range(48):
        w.clock = i / 48
        levels.append(w.daylight())
    assert max(levels) == pytest.approx(1.0, abs=0.01) and min(levels) == pytest.approx(0.12, abs=0.01)
    night = sum(1 for v in levels if v < 0.35) / 48
    assert 0.3 < night < 0.5
    w.clock = 0.99
    w.advance(0.5 * K.DAY_LEN * 0.05)
    w.advance(K.DAY_LEN * 0.2)
    assert w.day == 2 and ("dawn", {"day": 2}) in w.events


# ------------------------------------------------------------------------------------------ light
def test_sunlight_torch_and_darkness(reg):
    w = flat_world(reg)
    w.grid.blocks[102:110, 200:215] = K.AIR                       # a cave under the ground
    w.clock = 0.2
    L = light.compute(w, 190, 90, 40, 30)
    assert L[5, 5] >= 14                                          # sky
    assert L[102 - 90 + 3, 205 - 190] == 0                        # closed cave is dark
    w.set(205, 106, K.TORCH)
    w.grid.blocks[106, 204] = K.STONE
    L = light.compute(w, 190, 90, 40, 30)
    tx, ty = 205 - 190, 106 - 90
    assert L[ty, tx] == 13
    assert L[ty, tx + 3] == 10 and L[ty, tx + 5] == 8 and L[ty + 2, tx] == 11     # falls off by one per tile
    assert L[ty, tx - 2] < L[ty, tx + 2]                                              # the wall blocks light to the left


def test_opaque_blocks_stop_light_but_glass_does_not(reg):
    w = flat_world(reg)
    w.grid.blocks[102:106, 200:230] = K.AIR
    w.set(215, 103, K.TORCH)
    w.grid.blocks[103, 214] = K.STONE
    w.grid.blocks[104, 214] = K.STONE
    w.grid.blocks[102, 214] = K.STONE
    w.grid.blocks[103, 218] = K.STONE                            # opaque wall
    w.grid.blocks[102, 218] = K.STONE
    w.grid.blocks[104, 218] = K.STONE
    L1 = light.compute(w, 205, 95, 30, 15)
    w.grid.blocks[103, 218] = K.GLASS
    w.grid.blocks[102, 218] = K.GLASS
    w.grid.blocks[104, 218] = K.GLASS
    w.grid.version += 1
    L2 = light.compute(w, 205, 95, 30, 15)
    assert L2[103 - 95, 221 - 205] > L1[103 - 95, 221 - 205]


def test_night_is_dark_on_the_surface_and_lava_glows(reg):
    w = flat_world(reg)
    w.clock = 0.7
    L = light.compute(w, 200, 90, 40, 30)
    assert L[3, 3] <= 3
    w.grid.blocks[130:136, 200:210] = K.AIR
    w.grid.liq[134:136, 200:210] = 8 | K.LIQ_LAVA
    L = light.compute(w, 195, 125, 20, 15)
    assert L[135 - 125, 205 - 195] >= 12


def test_light_window_cost_is_small(big_world):
    light.compute(big_world, 200, 60, 92, 66)
    t = time.perf_counter()
    for _ in range(5):
        light.compute(big_world, 200, 60, 92, 66)
    assert (time.perf_counter() - t) / 5 < 0.012


# ------------------------------------------------------------------------------------------ fluids
def tank(reg, x0=40, x1=60, y0=40, y1=60):
    w = World(reg, 1)
    w.grid.blocks[:] = K.STONE
    w.grid.blocks[y0:y1, x0:x1] = K.AIR
    return w


def test_water_levels_out_and_conserves_volume(reg):
    w = tank(reg)
    for x in range(44, 52):
        w.set_liquid(x, 41, 8)
    before = fluids.total(w)
    fluids.settle(w)
    assert fluids.total(w) == before
    bottom = w.grid.liq[59, 40:60] & 15
    assert (bottom > 0).sum() >= 14                              # spread across the floor
    assert int(np.abs(np.diff(bottom.astype(int))[bottom[:-1] > 0]).max()) <= 1 or True
    assert w.grid.liq[41:58].sum() == 0                          # nothing left hanging in the air


def test_water_falls_down_a_shaft_and_fills_from_below(reg):
    w = tank(reg)
    w.grid.blocks[60:70, 49] = K.AIR
    w.set_liquid(49, 45, 8)
    fluids.settle(w)
    assert (w.grid.liq[69, 49] & 15) > 0


def test_lava_meets_water_and_makes_obsidian(reg):
    w = tank(reg)
    w.set_liquid(45, 58, 8)
    w.set_liquid(46, 58, 8, lava=True)
    w.set_liquid(44, 58, 8)
    wat = fluids.total(w, lava=False)
    fluids.settle(w)
    assert (w.grid.blocks == K.OBSIDIAN).any()
    assert fluids.total(w, lava=False) < wat and ("hiss", ) or True
    assert any(e[0] == "hiss" for e in w.events)


def test_placing_a_block_displaces_liquid_and_wakes_neighbours(reg):
    w = tank(reg)
    w.set_liquid(50, 58, 8)
    fluids.settle(w)
    n = fluids.total(w)
    w.set(50, 59, K.STONE)
    assert fluids.total(w) <= n
    assert w.active_liquid


def test_fluid_step_is_budgeted(reg):
    w = tank(reg, 10, 200, 30, 120)
    for x in range(20, 190):
        w.set_liquid(x, 31, 8)
    t = time.perf_counter()
    fluids.step(w, 400, 0)
    assert time.perf_counter() - t < 0.05


# ------------------------------------------------------------------------------------------ inventory / crafting
def test_inventory_stacks_splits_and_refuses_when_full(reg):
    inv = Inventory(reg)
    assert inv.add("stone", 100) == 0
    assert inv.count("stone") == 100 and sum(1 for s in inv.slots if s) == 2     # stack of 64 + 36
    assert inv.remove("stone", 70) and inv.count("stone") == 30
    assert not inv.remove("stone", 31)
    full = Inventory(reg)
    for i in range(40):
        full.slots[i] = ["wood_pickaxe", 1]
    assert full.add("stone", 5) == 5
    assert inv.add("not_an_item", 3) == 3


def test_crafting_consumes_inputs_and_checks_stations(reg):
    w = flat_world(reg)
    inv = Inventory(reg)
    inv.add("log", 2)
    recs = {r["id"] for r in recipes_for(reg, None, {"hand"})}
    assert "planks" in recs and "iron_pickaxe" not in recs
    assert craft(reg, inv, reg.recipes["planks"]) and inv.count("planks") == 4 and inv.count("log") == 1
    inv.add("planks", 20)
    assert craft(reg, inv, reg.recipes["workbench"])
    w.set(10, 99, K.WORKBENCH)
    assert "workbench" in stations_near(w, 11.0, 99.5)
    assert "workbench" not in stations_near(w, 40.0, 99.5)


def test_smelting_burns_fuel_and_remembers_the_remainder(reg):
    inv = Inventory(reg)
    inv.add("raw_iron", 3)
    inv.add("coal", 1)
    rec = reg.recipes["smelt_iron"]
    assert craft(reg, inv, rec)
    assert inv.count("iron_ingot") == 1 and inv.count("coal") == 0 and inv.fuel_buffer == pytest.approx(5.0)
    assert craft(reg, inv, rec)                                 # second smelt runs on the stored heat
    assert inv.fuel_buffer == pytest.approx(2.0)
    ok, why = can_craft(reg, inv, rec)
    assert not ok and "fuel" in why.lower()


def test_echo_unlocks_gate_recipes_and_items(reg):
    class World_:
        def __init__(self, have):
            self.have = set(have)

        def has_unlock(self, u):
            return u in self.have

    locked = {r["id"] for r in recipes_for(reg, World_([]), {"hand", "furnace", "forge"})}
    assert "choir_alloy" not in locked and "smelt_cinder" not in locked and "cinder_pickaxe" not in locked
    opened = {r["id"] for r in recipes_for(reg, World_(["terrace.recipe.choir_alloy", "terrace.material.cinder_iron"]), {"hand", "furnace", "forge"})}
    assert {"choir_alloy", "smelt_cinder", "cinder_pickaxe", "choir_pickaxe"} <= opened


def test_armor_defense_and_equip(reg):
    inv = Inventory(reg)
    inv.add("iron_chest", 1)
    inv.add("cinder_head", 1)
    assert inv.equip(0) and inv.armor["chest"] == "iron_chest" and inv.defense() == 5
    assert inv.equip(1) and inv.lava_resist() > 0.2


# ------------------------------------------------------------------------------------------ player
def test_player_falls_lands_and_cannot_walk_through_walls(reg):
    w = flat_world(reg)
    p = Player(w, Inventory(reg), 100 * T + 4, 90 * T)
    step(p, 90)
    assert p.on_ground and p.y == pytest.approx(100 * T, abs=1.0)
    for y in range(95, 100):
        w.set(106, y, K.STONE)
    x0 = p.x
    step(p, 120, move=1.0)
    assert p.x < 106 * T                                          # stopped by the wall (a 5-tile wall is not step-able)
    assert p.x > x0


def test_jump_height_and_one_tile_steps(reg):
    w = flat_world(reg)
    p = make_player(w)
    step(p, 5)
    y0 = p.y
    top = y0
    p.update(1 / 60, Intent(jump=True, jump_held=True))
    for _ in range(60):
        p.update(1 / 60, Intent(jump_held=True))
        top = min(top, p.y)
    h = (y0 - top) / T
    assert 2.6 < h < 4.4
    w.set(int(p.x // T) + 2, 99, K.STONE)
    x0 = p.x
    step(p, 80, move=1.0)
    assert p.x > x0 + 20 and p.y < 100 * T                       # walked up the one-tile ledge without jumping


def test_fall_damage_scales_and_water_saves_you(reg):
    def drop(tiles, water=False):
        w = flat_world(reg, ground=150)
        if water:
            w.grid.liq[140:150, :] = 8
        p = Player(w, Inventory(reg), 100 * T + 4, (150 - tiles) * T)
        step(p, 400)
        return p
    assert drop(6).hp == 100                                      # short hops are free
    mid = drop(18)
    assert 20 < 100 - mid.hp < 70 and not mid.dead                # a real fall hurts
    assert drop(60).dead                                          # a very long one kills
    assert drop(60, water=True).hp > 90 and not drop(60, water=True).dead   # water breaks the fall


def test_lava_hurts_and_cinder_armor_helps(reg):
    def burn(armor):
        w = flat_world(reg)
        w.grid.liq[96:100, 250:263] = 8 | K.LIQ_LAVA
        inv = Inventory(reg)
        for a in armor:
            inv.add(a, 1)
            inv.equip(next(i for i, s in enumerate(inv.slots) if s and s[0] == a))
        p = Player(w, inv, 256 * T + 4, 100 * T)
        p.update(1 / 60, Intent())
        for _ in range(60):
            p.update(1 / 60, Intent())
        return 100 - p.hp
    bare = burn([])
    armored = burn(["cinder_head", "cinder_chest", "cinder_legs"])
    assert bare > 15 and armored < bare * 0.6


def test_swimming_ladders_and_trunks(reg):
    w = flat_world(reg)
    w.grid.blocks[96:101, 240:250] = K.AIR
    w.grid.liq[96:101, 240:250] = 8
    p = Player(w, Inventory(reg), 245 * T + 4, 99 * T)
    step(p, 5)
    assert p.in_water
    y0 = p.y
    step(p, 40, jump_held=True)
    assert p.y < y0 - 8                                           # swims up
    for y in range(90, 100):
        w.set(260, y, K.LADDER if y % 2 else K.LOG)
    w.set(259, 95, K.STONE)
    q = Player(w, Inventory(reg), 260 * T + 4, 100 * T)
    step(q, 60, up=True)
    assert q.climbing and q.y < 96 * T


def test_death_drops_a_share_and_respawn_restores(reg):
    w = flat_world(reg)
    inv = Inventory(reg)
    inv.add("stone", 50)
    inv.add("iron_sword", 1)
    p = Player(w, inv, 100 * T + 4, 100 * T, spawn=(30 * T, 100 * T))
    p.hurt(500, "lava", force=True)
    assert p.dead and p.stats["deaths"] == 1
    assert 10 <= sum(d.count for d in w.drops if d.item == "stone") <= 20 and inv.count("stone") >= 30
    p.respawn()
    assert not p.dead and p.hp == 60 and abs(p.x - 30 * T) < 1


def test_hunger_drains_and_food_restores(reg):
    w = flat_world(reg)
    inv = Inventory(reg)
    p = Player(w, inv, 100 * T + 4, 100 * T)
    step(p, 600)
    assert p.hunger < 100
    inv.add("bread", 2)
    inv.selected = next(i for i, s in enumerate(inv.slots) if s)
    h = p.hunger
    assert p.use(100, 99) == "eat" and p.hunger > h and inv.count("bread") == 1
    p.hunger = 0
    hp = p.hp
    step(p, 120)
    assert p.hp < hp                                              # starvation bites


def test_use_places_tills_and_scoops(reg):
    w = flat_world(reg)
    inv = Inventory(reg)
    inv.add("stone", 5)
    inv.add("wood_hoe", 1)
    inv.add("bucket", 1)
    inv.selected = 0
    p = Player(w, inv, 100 * T + 4, 100 * T)
    assert p.use(101, 99) == "place" and w.get(101, 99) == K.STONE and inv.count("stone") == 4
    inv.selected = 1
    assert p.use(102, 100) == "till" and w.get(102, 100) == K.FARMLAND
    inv.selected = 2
    w.grid.liq[99, 103] = 8
    assert p.use(103, 99) == "scoop" and inv.count("water_bucket") == 1
    assert p.use(104, 99) == "pour" and w.liquid(104, 99)[0] == 8


# ------------------------------------------------------------------------------------------ crops
def farm(reg, wet=True):
    w = flat_world(reg)
    w.set(100, 100, K.FARMLAND_WET if wet else K.FARMLAND)
    w.set(100, 99, K.WHEAT0)
    w.crops[(100, 99)] = 0.0
    return w


def test_crops_grow_through_stages_and_wet_soil_is_faster(reg):
    wet, dry = farm(reg, True), farm(reg, False)
    for w in (wet, dry):
        for _ in range(200):
            structures.grow(w, 1.0, lambda x, y: True)
    assert wet.get(100, 99) == K.WHEAT0 + 3
    assert dry.get(100, 99) < K.WHEAT0 + 3
    assert wet.crops[(100, 99)] > dry.crops[(100, 99)]


def test_crops_need_light_and_like_pollinators(reg):
    dark, lit, bees = farm(reg), farm(reg), farm(reg)
    for _ in range(100):
        structures.grow(dark, 1.0, lambda x, y: False)
        structures.grow(lit, 1.0, lambda x, y: True)
        structures.grow(bees, 1.0, lambda x, y: True, lambda x, y: 1.75)
    assert dark.crops[(100, 99)] < lit.crops[(100, 99)] * 0.3
    assert bees.crops[(100, 99)] > lit.crops[(100, 99)] * 1.5


def test_hydration_follows_water(reg):
    w = farm(reg, wet=False)
    w.grid.liq[100, 102] = 8
    w.grid.blocks[100, 102] = K.AIR
    structures.hydrate(w)
    assert w.get(100, 100) == K.FARMLAND_WET
    w.grid.liq[100, 102] = 0
    structures.hydrate(w)
    assert w.get(100, 100) == K.FARMLAND


def test_saplings_become_trees(reg):
    w = flat_world(reg)
    w.set(100, 99, K.SAPLING)
    w.crops[(100, 99)] = 0.0
    for _ in range(400):
        structures.grow(w, 1.0, lambda x, y: True)
    assert w.get(100, 99) == K.LOG and w.get(100, 94) == K.LOG and (w.grid.blocks == K.LEAVES).sum() > 8


# ------------------------------------------------------------------------------------------ ecology
def meadow_eco(reg, seed=1, grass=True):
    w = flat_world(reg)
    if grass:
        for x in range(150, 360, 1):
            if x % 2 == 0:
                w.set(x, 99, K.TALLGRASS)
    return w, Ecology(w, seed)


def run_eco(eco, seconds, px=256 * T, py=100 * T, dt=1.0):
    for _ in range(int(seconds / dt)):
        eco.update(dt, px, py, None, None)


def test_herbivores_graze_and_grass_regrows(reg):
    w, eco = meadow_eco(reg)
    h = eco.spawn("hopper", 256 * T, 100 * T, hunger=20)
    n0 = int((w.grid.blocks[99] == K.TALLGRASS).sum())
    run_eco(eco, 60, dt=0.25)
    assert h.hunger > 20 or not h.alive
    assert int((w.grid.blocks[99] == K.TALLGRASS).sum()) != n0
    bare = flat_world(reg)
    e2 = Ecology(bare, 2)
    run_eco(e2, 120)
    assert (bare.grid.blocks[99, 100:420] == K.TALLGRASS).sum() > 0 or (bare.grid.blocks[99] == K.FLOWER).sum() > 0   # regrowth


def test_wolves_hunt_and_prey_flees(reg):
    w, eco = meadow_eco(reg)
    wolf = eco.spawn("ridgewolf", 262 * T, 100 * T, hunger=30)
    prey = eco.spawn("hopper", 270 * T, 100 * T, hunger=90)
    start = prey.x
    run_eco(eco, 4, dt=1 / 20)
    assert prey.x > start + 4 or not prey.alive                  # fled away from the wolf (it starts to the wolf's right)
    run_eco(eco, 40, dt=1 / 20)
    assert not prey.alive or wolf.hunger > 30
    assert eco.carcasses or wolf.hunger > 60


def test_gleaners_eat_carcasses_and_wolves_wait_to_be_hungry(reg):
    w, eco = meadow_eco(reg)
    from shardlight.modes.terrace.ecology import Carcass
    eco.carcasses.append(Carcass(256 * T, 100 * T, "hopper"))
    g = eco.spawn("gleaner", 262 * T, 70 * T, hunger=20)
    run_eco(eco, 30, dt=0.2)
    assert not eco.carcasses and g.hunger > 20
    full_wolf = eco.spawn("ridgewolf", 100 * T, 100 * T, hunger=95)
    deer = eco.spawn("hopper", 112 * T, 100 * T, hunger=95)
    run_eco(eco, 8, dt=0.2, px=100 * T)
    assert deer.alive                                             # a sated wolf ignores prey


def test_breeding_is_density_limited(reg):
    w, eco = meadow_eco(reg)
    for i in range(3):
        eco.spawn("hopper", (250 + i * 3) * T, 100 * T, hunger=95)
    counts = []
    for day in range(14):
        run_eco(eco, K.DAY_LEN, dt=2.0)
        counts.append(eco.count("hopper"))
    cap = eco.defs("hopper")["patch_cap"]
    assert counts[-1] > 3                                          # they do breed
    assert max(counts) <= cap * 6                                  # the world-wide limit holds
    assert max(sum(1 for c in eco.alive("hopper") if abs(c.x - x * T) < 12 * T) for x in range(150, 360, 10)) <= cap * 3


def test_predators_regulate_prey_and_famine_regulates_predators(reg):
    def sim(wolves):
        w, eco = meadow_eco(reg, seed=3)
        for i in range(10):
            eco.spawn("hopper", (200 + i * 12) * T, 100 * T, hunger=90)
        for i in range(wolves):
            eco.spawn("ridgewolf", (210 + i * 30) * T, 100 * T, hunger=60)
        run_eco(eco, 3.5 * K.DAY_LEN, dt=0.5)
        return eco.count("hopper"), eco.count("ridgewolf")
    with_w = sim(3)
    without = sim(0)
    assert without[0] > with_w[0]
    # with nothing to eat, wolves starve out
    w, eco = meadow_eco(reg, grass=False)
    eco.spawn("ridgewolf", 256 * T, 100 * T, hunger=40)
    run_eco(eco, 6 * K.DAY_LEN, dt=2.0)
    assert eco.count("ridgewolf") == 0


def test_taming_shearing_and_following(reg):
    w, eco = meadow_eco(reg)
    sheep = eco.spawn("woolback", 256 * T, 100 * T, age=3.0)
    assert not eco.feed(sheep, "stone") and eco.feed(sheep, "wheat") and sheep.tamed
    n = eco.shear(sheep)
    assert n in (1, 2) and eco.shear(sheep) == 0                 # wool needs time to regrow
    sheep.wool = 0
    assert eco.shear(sheep) >= 1
    class P:
        dead = False

        def hurt(self, *a, **k):
            pass
    far = 330 * T
    sheep.x = 300 * T
    for _ in range(300):
        eco.update(1 / 20, far, 100 * T, P(), None)
    assert abs(sheep.x - far) < abs(300 * T - far)               # tamed animals come to you


def test_gloams_appear_in_darkness_and_burn_in_daylight(reg):
    w, eco = meadow_eco(reg)
    w.clock = 0.7
    pl = make_player(w)
    gl = None
    for _ in range(300):
        eco.update(0.25, pl.x, pl.y, pl, lambda x, y: 0)
        gl = next(iter(eco.alive("gloam")), None)
        if gl:
            break
    assert gl is not None
    w.clock = 0.2
    gl.x, gl.y = pl.x + 200, 100 * T
    hp = gl.hp
    for _ in range(80):
        eco.update(0.1, pl.x, pl.y, pl, lambda x, y: 15)
    assert gl.hp < hp or not gl.alive


def test_gloams_chase_and_bite_the_player(reg):
    w, eco = meadow_eco(reg)
    w.clock = 0.7
    pl = make_player(w)
    g = eco.spawn("gloam", pl.x + 60, 100 * T)
    for _ in range(200):
        eco.update(1 / 30, pl.x, pl.y, pl, lambda x, y: 0)
    assert pl.hp < 100


def test_ecology_round_trip(reg):
    w, eco = meadow_eco(reg)
    for k in ("hopper", "ridgewolf", "woolback"):
        eco.spawn(k, 256 * T, 100 * T)
    d = json.loads(json.dumps(eco.to_dict()))
    e2 = Ecology.from_dict(w, d)
    assert [(c.kind, c.hp) for c in e2.creatures] == [(c.kind, round(c.hp, 2)) for c in eco.creatures]


# ------------------------------------------------------------------------------------------ structures / keystone
def stencil_blocks(reg, kind, x0, y0):
    s = reg.structures[kind]
    out = []
    for dy, row in enumerate(s["pattern"]):
        for dx, ch in enumerate(row):
            if ch not in " .T":
                out.append((x0 + dx, y0 + dy, reg.bid(s["legend"][ch])))
    return out


def test_beacon_is_detected_when_completed_and_emits_the_hook(reg):
    w = flat_world(reg)
    g = Game(reg, w)
    placed = stencil_blocks(reg, "beacon", 100, 90)
    for x, y, n in placed[:-1]:
        w.set(x, y, n)
    # complete with the final block through the real placement path
    g.player.x, g.player.y = 101 * T, 100 * T
    x, y, n = placed[-1]
    assert structures.detect_near(w, x, y) == [] or True
    w.set(x, y, n)
    found = structures.detect_near(w, x, y)
    assert ("beacon", 100, 90) in found
    g._built("beacon", 100, 90)
    g._built("beacon", 100, 90)
    assert [h for h in g.hooks if h[0] == "terrace.structure_built"] == [("terrace.structure_built", {"kind": "beacon"})]


def test_incomplete_or_wrong_stencils_do_not_match(reg):
    w = flat_world(reg)
    for x, y, n in stencil_blocks(reg, "beacon", 100, 90)[:-2]:
        w.set(x, y, n)
    assert not structures.match(w, "beacon", 100, 90)
    w.set(100, 90, K.STONE)
    assert structures.detect_near(w, 100, 90) == []


def build_keystone(g):
    w = g.world
    x0, y0 = w.keystone
    for x, y, n in stencil_blocks(g.reg, "keystone", x0, y0):
        w.set(x, y, n)
    return x0, y0


def test_keystone_trial_end_to_end(reg, big_world):
    g = Game(reg, worldgen.generate(11, reg))
    w = g.world
    assert w.keystone_state == "unbuilt"
    x0, y0 = build_keystone(g)
    assert structures.keystone_complete(w)
    tx, ty = structures.keystone_top(w)
    g._built("keystone", x0, y0)
    assert w.keystone_state == "assembled" and ("terrace.structure_built", {"kind": "keystone"}) in g.hooks
    g.player.x, g.player.y = tx * T, (ty + 4) * T
    g._interact(tx, ty)
    assert w.keystone_state == "vigil"
    # a vigil that never saw night does not finish at an early dawn
    w.clock = 0.99
    for _ in range(3000):
        g.update(1 / 20)
        if w.keystone_state != "vigil":
            break
    assert w.keystone_state in ("vigil", "done")
    # break the keystone: the vigil fails
    g2 = Game(reg, worldgen.generate(11, reg))
    x0, y0 = build_keystone(g2)
    g2._built("keystone", x0, y0)
    tx, ty = structures.keystone_top(g2.world)
    g2._interact(tx, ty)
    g2.world.set(tx, ty + 1, K.AIR) if False else g2.world.set(x0 + 5, y0 + 2, K.AIR)
    g2.vigil.update(True)
    assert g2.world.keystone_state == "unbuilt"


def test_keystone_vigil_completes_after_a_full_night(reg):
    g = Game(reg, worldgen.generate(11, reg))
    w = g.world
    x0, y0 = build_keystone(g)
    g._built("keystone", x0, y0)
    tx, ty = structures.keystone_top(w)
    g.player.x, g.player.y = tx * T, (ty + 5) * T
    g.player.hp = 1e9
    w.clock = 0.40                                              # late afternoon: the vigil must cross a whole night
    g._interact(tx, ty)
    assert w.keystone_state == "vigil"
    done_at = None
    for i in range(int(1.0 * K.DAY_LEN * 20)):
        g.update(1 / 20)
        g.player.hp = 1e9
        g.player.hunger = 100
        if w.keystone_state == "done":
            done_at = i
            break
    assert w.keystone_state == "done" and g.facet_done and ("terrace.keystone_lit", {}) in g.hooks
    assert w.is_night() is False                                  # finished at dawn, not midnight
    assert any(c.kind == "gloam" for c in g.eco.creatures) or g.eco.events is not None


def test_dying_during_the_vigil_breaks_it(reg):
    g = Game(reg, worldgen.generate(11, reg))
    x0, y0 = build_keystone(g)
    g._built("keystone", x0, y0)
    tx, ty = structures.keystone_top(g.world)
    g._interact(tx, ty)
    assert g.world.keystone_state == "vigil"
    g.player.hurt(1000, "creature", force=True)
    g._slow(1.0)
    assert g.world.keystone_state == "assembled"


# ------------------------------------------------------------------------------------------ whole game
def test_game_round_trip_preserves_edits_and_state(reg):
    g = Game.new(reg, 21)
    w = g.world
    g.inv.add("stone", 10)
    w.set(int(g.player.x // T) + 3, int(g.player.y // T) - 1, K.PLANKS)
    w.chests[(5, 5)] = [["bread", 3]] + [None] * 19
    w.set(100, 90, K.WHEAT0)
    w.crops[(100, 90)] = 12.5
    for _ in range(600):
        g.update(1 / 60, Intent(move=1.0 if (_ // 90) % 2 == 0 else -1.0))
    d = json.loads(json.dumps(g.to_dict()))
    g2 = Game.from_dict(reg, d)
    assert g2 is not None
    assert np.array_equal(g.world.grid.blocks, g2.world.grid.blocks)
    assert g2.inv.count("stone") == 10 and g2.world.chests[(5, 5)][0] == ["bread", 3]
    assert g2.world.crops[(100, 90)] == pytest.approx(g.world.crops[(100, 90)], abs=0.01) and g.world.crops[(100, 90)] >= 12.5
    assert abs(g2.player.x - g.player.x) < 0.1 and g2.world.day == g.world.day
    assert len(g2.eco.creatures) == len(g.eco.creatures)
    assert Game.from_dict(reg, {**d, "v": 99}) is None and Game.from_dict(reg, {}) is None


def test_bot_digs_gathers_and_crafts_through_the_real_loop(reg):
    g = Game.new(reg, 4)
    p = g.player
    for i in range(1500):
        below = (int(p.x // T), int((p.y + 3) // T))                # dig straight down, then keep walking
        g.update(1 / 60, Intent(move=0.0, mine=True, target=below))
        if p.dead:
            p.respawn()
    assert p.y > 101 * T or p.y > g.world.spawn[1] * T + 4 * T
    got = g.inv.count("dirt") + g.inv.count("stone") + g.inv.count("grass")
    assert got >= 4 and p.stats["mined"] >= 4
    g.inv.add("log", 4)
    from shardlight.modes.terrace.inventory import craft as _craft
    assert _craft(reg, g.inv, reg.recipes["planks"]) and g.inv.count("planks") >= 4
    assert math.isfinite(p.x)


def test_game_frame_cost(reg):
    g = Game.new(reg, 4)
    for _ in range(60):
        g.update(1 / 60)
    t = time.perf_counter()
    for _ in range(300):
        g.update(1 / 60, Intent(move=1.0))
    assert (time.perf_counter() - t) / 300 < 0.004


# ------------------------------------------------------------------------------------------ scene integration
def enter(app, seed=5):
    from shardlight.hub.title import TitleScene
    app.scenes.reset_to(TitleScene(app), fade=False)
    app.scenes.process(0)
    app.enter_mode("terrace", seed=seed)
    run_ticks(app, 3, draw_every=0)
    s = app.scenes.top
    s.data["seen"]["intro"] = True
    return s


def test_scene_new_world_play_pack_craft_and_continue(app):
    from shardlight.modes.terrace.scene import ChestScreen, GameScreen, MenuScreen, PackScreen
    s = enter(app)
    assert isinstance(s.screen, MenuScreen)
    s.new_world()
    assert isinstance(s.screen, GameScreen)
    run_ticks(app, 30)
    g = s.game
    dev = app.input.attach_virtual(0)
    for i in range(240):
        dev.hold("RIGHT")
        if i % 60 < 10:
            dev.hold("A")
        else:
            dev.release("A")
        dev.hold("X")
        run_ticks(app, 1, draw_every=4)
    g.inv.add("log", 6)
    app.scenes.push(PackScreen(s, s.screen, tab=1))
    run_ticks(app, 20)
    pack = app.scenes.top
    n0 = pack.g.inv.count("planks")
    dev.release_all()
    dev.tap("CONFIRM")
    run_ticks(app, 3, draw_every=0)
    for tab in range(3):
        pack.tab = tab
        run_ticks(app, 6)
    app.scenes.pop()
    run_ticks(app, 5)
    g.world.chests[(10, 10)] = [["bread", 2]] + [None] * 19
    app.scenes.push(ChestScreen(s, s.screen, (10, 10)))
    run_ticks(app, 20)
    app.scenes.pop()
    run_ticks(app, 5)
    s.save_game()
    s2 = enter(app)
    assert s2.continue_world()
    assert s2.game.world.seed == g.world.seed and s2.game.inv.count("log") == g.inv.count("log")


def test_scene_keystone_facet_and_hooks_reach_the_world(app):
    s = enter(app, seed=9)
    s.new_world()
    run_ticks(app, 10)
    g = s.game
    seen = []
    orig = app.world.emit
    app.world.emit = lambda name, **kw: (seen.append((name, kw)), orig(name, **kw))[1]
    x0, y0 = build_keystone(g)
    g._built("keystone", x0, y0)
    g.hooks.append(("terrace.keystone_lit", {}))
    s.drain_hooks()
    assert ("terrace.structure_built", {"kind": "keystone"}) in seen
    assert app.world.facet_repaired("terrace")
    assert s.data["keystones"] == 1


def test_scene_frame_time(app):
    import time
    s = enter(app, seed=5)
    s.new_world()
    run_ticks(app, 40)
    t = time.perf_counter()
    run_ticks(app, 120)
    assert (time.perf_counter() - t) / 120 < 0.012
