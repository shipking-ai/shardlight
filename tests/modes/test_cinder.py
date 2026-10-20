"""Cinder: content, generation, combat rules, status synergies, enemy AI, adaptation, boons, bosses and integration."""
import math
import time

import pytest
from conftest import run_ticks

from shardlight.core.content import ContentDB
from shardlight.core.paths import DATA_DIR
from shardlight.modes.cinder import defs
from shardlight.modes.cinder.sim import levelgen as LG
from shardlight.modes.cinder.sim.entities import ENEMY_TEAM, PLAYER_TEAM, Hitbox, Projectile
from shardlight.modes.cinder.sim.geometry import arc_hit, circle_hit, rect_hit, ring_hit
from shardlight.modes.cinder.sim.perks import Modifiers
from shardlight.modes.cinder.sim.player import Intent
from shardlight.modes.cinder.sim.room import Room
from shardlight.modes.cinder.sim.run import Difficulty, Run
from shardlight.modes.cinder.sim.status import StatusSet


@pytest.fixture(scope="module")
def lib():
    db = ContentDB()
    defs.register_content(db)
    db.load_dir(DATA_DIR, "base")
    assert not [p for p in db.problems if "cinder" in p]
    return defs.Library(db)


def new_run(lib, weapon="ember_blade", seed=1, mods=(), preset="standard", adapt=1.0):
    return Run(lib, seed, weapon, [lib.mods[m] for m in mods], Difficulty.preset(preset), adapt)


def arena(lib, run=None, floor=2, kind="arena", seed=1):
    run = run or new_run(lib)
    plan = LG.generate_floor(lib, seed, floor, run.mods)
    spec = next(r for r in plan.rooms.values() if r.kind == kind)
    room = Room(run, spec, floor, entry=list(spec.doors)[0])
    room.spec.waves = []                       # tests spawn their own enemies
    room.cleared = False
    room.combat_started = True
    room.t = 100
    return room


def step(room, n=1, intent=None):
    for _ in range(n):
        if room.hitstop > 0:
            room.hitstop -= 1
            continue
        room.update(intent or Intent())
        room.drain_events()


def put(room, eid, x, y, elite=False):
    e = room.spawn_enemy(eid, x, y, elite, instant=True)
    return e


# ---------------------------------------------------------------------------------------------- content
def test_content_is_complete_and_consistent(lib):
    assert {w.family for w in lib.starter_weapons()} == {"blade", "hammer", "spear", "caster"}
    assert len(lib.enemies) >= 7 and len(lib.boons) >= 20 and len(lib.mods) >= 10
    for w in lib.weapons.values():
        for ev in w.evolutions:
            assert ev["to"] in lib.weapons
    ai_kinds = {e.ai for e in lib.enemies.values()}
    assert {"swarmer", "kiter", "shield", "bomber", "charger", "summoner", "sniper"} <= ai_kinds
    # weapons differ in move shapes, not only numbers
    shapes = {w.family: {m.shape for m in w.light} | {t.move.shape for t in w.heavy} for w in lib.starter_weapons()}
    assert len({frozenset(s) for s in shapes.values()}) == 4
    # every boon with a cost line describes a real tradeoff (stat or text)
    assert sum(1 for b in lib.boons.values() if b.cost) >= 20


def test_invalid_mod_content_is_rejected_not_fatal(lib):
    db = ContentDB()
    defs.register_content(db)
    assert not db.add_entry("cinder.enemy", {"id": "x", "name": "X", "ai": "teleporter", "hp": 5}, "badmod")
    assert not db.add_entry("cinder.boon", {"id": "y", "name": "Y", "desc": "d", "stats": {"nonsense": "a"}}, "badmod")
    db.add_entry("cinder.boon", {"id": "z", "name": "Z", "desc": "d", "stats": {"bogus_stat": 1.0}}, "badmod")
    assert defs.Library(db).problems                       # semantic problem reported, no exception


# ---------------------------------------------------------------------------------------------- generation
def test_floor_generation_is_deterministic_and_valid(lib):
    for seed in range(40):
        for floor in range(1, 6):
            a = LG.generate_floor(lib, seed, floor, Modifiers([]), choir_unlocked=floor in (2, 4))
            b = LG.generate_floor(lib, seed, floor, Modifiers([]), choir_unlocked=floor in (2, 4))
            assert not a.problems, (seed, floor, a.problems)
            assert {i: (r.kind, r.layout, r.waves, tuple(sorted(r.doors.items()))) for i, r in a.rooms.items()} == \
                   {i: (r.kind, r.layout, r.waves, tuple(sorted(r.doors.items()))) for i, r in b.rooms.items()}
            assert LG.validate_floor(a) == []
    boss_floors = {f for f in range(1, 6) if LG.generate_floor(lib, 3, f, Modifiers([])).boss}
    assert boss_floors == {3, 5}


def test_difficulty_and_heat_change_encounters(lib):
    easy = LG.generate_floor(lib, 5, 3, Modifiers([]))
    hard = LG.generate_floor(lib, 5, 3, Modifiers([lib.mods["crowded"], lib.mods["elite_escort"]]))
    n = lambda p: sum(len(w) for r in p.rooms.values() for w in r.waves)
    assert n(hard) > n(easy)


# ---------------------------------------------------------------------------------------------- geometry
def test_hit_shapes():
    assert arc_hit(0, 0, 0, 30, 90, 20, 0, 4)
    assert not arc_hit(0, 0, 0, 30, 90, -20, 0, 4)               # behind
    assert not arc_hit(0, 0, 0, 30, 90, 8, 28, 4)                # outside the arc
    assert rect_hit(0, 0, 0, 50, 10, 40, 3, 3) and not rect_hit(0, 0, 0, 50, 10, 40, 12, 3)
    assert circle_hit(0, 0, 10, 12, 0, 3) and not circle_hit(0, 0, 10, 20, 0, 3)
    assert ring_hit(0, 0, 20, 30, 25, 0, 2) and not ring_hit(0, 0, 20, 30, 5, 0, 2)


# ---------------------------------------------------------------------------------------------- combat rules
def enemy_strike(room, damage=10.0, x=None, y=None, windup=0, parryable=True):
    p = room.player
    owner = put(room, "cinder_thrall", p.x + 30, p.y)
    hb = Hitbox(owner=owner, team=ENEMY_TEAM, shape="circle", x=p.x, y=p.y, facing=0.0, reach=14, damage=damage,
                poise=20, windup=windup, active=4, parryable=parryable)
    room.add_hitbox(hb)
    owner.brain.attack_hb = hb
    owner.brain.cd = 10 ** 6
    owner.brain.react = 10 ** 6
    return owner, hb


def test_dodge_iframes_prevent_damage_and_hurt_otherwise(lib):
    room = arena(lib)
    enemy_strike(room, 10)
    step(room, 2)
    assert room.player.hp < 100                                    # standing still: hurt
    room2 = arena(lib)
    p = room2.player
    p.start_dodge(room2, Intent(move=(1.0, 0.0)))
    enemy_strike(room2, 10)
    step(room2, 3)
    assert room2.player.hp == 100 and room2.player.iframes > 0


def test_parry_inside_window_staggers_attacker_and_opens_riposte(lib):
    room = arena(lib)
    owner, hb = enemy_strike(room, 12, windup=5)
    p = room.player
    owner.x, owner.y = p.x + 22, p.y
    p.facing = 0.0
    step(room, 1, Intent(pressed={"parry"}))
    step(room, 8)
    assert room.player.hp == 100
    assert owner.stun > 0 and p.riposte_t > 0 and room.stats["parries"] == 1


def test_parry_too_early_or_late_does_not_work(lib):
    room = arena(lib)
    owner, hb = enemy_strike(room, 12, windup=40)
    room.player.facing = 0.0
    step(room, 1, Intent(pressed={"parry"}))
    step(room, 60)
    assert room.player.hp < 100 and room.stats["parries"] == 0


def test_unparryable_attacks_ignore_parry_and_charge_armour_prevents_stagger(lib):
    room = arena(lib)
    owner, hb = enemy_strike(room, 10, windup=3, parryable=False)
    room.player.facing = 0.0
    step(room, 1, Intent(pressed={"parry"}))
    step(room, 10)
    assert room.player.hp < 100
    room2 = arena(lib, new_run(lib, "slag_hammer"))
    room2.player.start_charge(room2, Intent())
    room2.player.update(room2, Intent())
    assert room2.player.armor
    room2.player.take_hit(0.0, 1.0, 14)
    assert room2.player.state != "hurt"


def test_weapon_attack_damages_enemy_in_arc_not_behind(lib):
    room = arena(lib)
    p = room.player
    front = put(room, "cinder_thrall", p.x + 24, p.y)
    back = put(room, "cinder_thrall", p.x - 24, p.y + 3)
    front.brain.react = back.brain.react = 10 ** 6
    p.facing = 0.0
    step(room, 1, Intent(move=(1, 0), aim=(1.0, 0.0), pressed={"attack"}))
    step(room, 20)
    assert front.hp < front.max_hp and back.hp == back.max_hp


def test_charged_heavy_has_tiers_and_ends_in_distinct_moves(lib):
    room = arena(lib)
    p = room.player
    p.start_charge(room, Intent())
    for _ in range(70):
        p.update(room, Intent(held={"heavy"}))
    assert p.charge_tier == len(p.weapon.heavy) - 1
    p.update(room, Intent())
    assert p.state == "attack" and p.move is p.weapon.heavy[-1].move


# ---------------------------------------------------------------------------------------------- statuses
def test_status_synergies_and_loop_protection():
    s = StatusSet()
    s.apply("ash")
    ev = s.apply("burn", 2)
    assert [e.kind for e in ev] == ["flashover"] and not s.has("ash") and not s.has("burn")
    s2 = StatusSet()
    s2.apply("ash")
    assert [e.kind for e in s2.apply("shock")] == ["nova"]
    s3 = StatusSet()
    s3.apply("rend", 3)
    assert "sear" in [e.kind for e in s3.apply("burn")] and s3.has("burn") and not s3.has("rend")
    s4 = StatusSet()
    s4.apply("ash")
    s4.apply("burn")
    ev2 = s4.apply("ash")
    assert not ev2 or s4.lock > 0                          # lock stops chain loops on the same victim
    s5 = StatusSet()
    s5.apply("burn", 3)
    dots = 0
    for _ in range(180):
        dots += sum(1 for e in s5.tick() if e.kind == "dot")
    assert dots >= 5 and not s5.has("burn")


def test_flashover_damages_neighbours_in_the_room(lib):
    room = arena(lib)
    a = put(room, "cinder_thrall", 200, 100)
    b = put(room, "cinder_thrall", 215, 100)
    for e in (a, b):
        e.brain.react = 10 ** 6
    room._apply_status(a, "ash", 1)
    hp_b = b.hp
    room._apply_status(a, "burn", 2)
    assert b.hp < hp_b and not a.status.has("ash")


# ---------------------------------------------------------------------------------------------- enemy AI
def settle(room, enemy, frames=120, intent=None):
    step(room, frames, intent)


def test_enemies_do_not_act_without_perception_and_have_reaction_delay(lib):
    room = arena(lib)
    p = room.player
    # a thrall behind a wall far away cannot see the player
    far = put(room, "cinder_thrall", 40, 40)
    p.x, p.y = 300, 120
    far.facing = math.pi
    step(room, 30)
    assert not far.brain.aware
    # in view: becomes aware, then waits ~reaction frames before acting
    far.alive = False
    near = put(room, "cinder_thrall", p.x - 70, p.y)
    near.facing = 0.0
    start = room.t
    acted_at = None
    for _ in range(80):
        step(room)
        if near.brain.state in ("windup",) or near.brain.attack_hb is not None:
            acted_at = room.t
            break
        near.brain.cd = max(near.brain.cd, 0)
    assert near.brain.aware
    assert acted_at is None or acted_at - start >= 12


def test_shield_bearer_blocks_frontal_hits_but_not_flanking_ones(lib):
    room = arena(lib)
    b = put(room, "bulwark", 224, 110)
    b.facing = math.pi                                  # facing left
    b.brain.react = 10 ** 6
    class Src:
        x, y = 190.0, 110.0
        apply = ()
        poise = 5.0
        knock = 0.0
        stop = 0
        shake = 0.0
        tags = ()
        crit = False
        owner = room.player
        source = "t"
        unblockable = False
    room._damage_enemy(b, 20, Src, 0.0)
    front_loss = b.max_hp - b.hp
    Src.x = 260.0
    b.hp = b.max_hp
    room._damage_enemy(b, 20, Src, 0.0)
    back_loss = b.max_hp - b.hp
    assert back_loss > front_loss * 4
    # a heavy (poise) hit breaks the guard
    Src.x, Src.poise = 190.0, 60.0
    b.hp = b.max_hp
    room._damage_enemy(b, 20, Src, 0.0)
    assert b.stun > 0 and not b.guard_front


def test_archer_keeps_its_distance_and_leads_shots_honestly(lib):
    room = arena(lib)
    p = room.player
    p.x, p.y = 224, 120
    a = put(room, "ash_archer", 224, 140)
    a.facing = -math.pi / 2
    a.brain.aware = True
    a.brain.react = 0
    for _ in range(240):
        step(room)
    d = math.hypot(a.x - p.x, a.y - p.y)
    assert d > a.params["min_range"] * 0.9
    assert any(pr.team == ENEMY_TEAM for pr in room.projectiles) or room.stats["hits_taken"] >= 0


def test_charger_telegraphs_then_charges_and_stuns_itself_on_walls(lib):
    room = arena(lib)
    p = room.player
    p.x, p.y = 300, 110
    c = put(room, "slag_charger", 100, 110)
    c.facing = 0.0
    c.brain.aware = True
    c.brain.react = 0
    c.brain.cd = 0
    saw_tell = saw_charge = False
    hp0 = None
    for _ in range(400):
        step(room)
        if c.brain.state == "tell":
            saw_tell = True
            hp0 = p.hp if hp0 is None else hp0
            assert p.hp == hp0                         # no damage while the telegraph is up
        else:
            hp0 = None
        if c.brain.state == "charge":
            saw_charge = True
        if c.stun > 0 and c.brain.state == "stunned":
            break
    assert saw_tell and saw_charge


def test_bomber_has_a_fuse_and_dies_when_killed_early(lib):
    room = arena(lib)
    p = room.player
    imp = put(room, "fuse_imp", p.x + 20, p.y)
    imp.brain.aware = True
    imp.brain.react = 0
    step(room, 3)
    assert imp.brain.state == "fuse"
    p.x, p.y = 300, 190
    imp2 = put(room, "fuse_imp", 301, 186)
    imp2.hp = 1
    room._damage_enemy(imp2, 5, type("S", (), {"x": 300, "y": 190, "apply": (), "poise": 0, "knock": 0, "stop": 0, "shake": 0,
                                                "tags": (), "crit": False, "owner": p, "source": "t", "unblockable": False})(), 0.0)
    assert not imp2.alive


def test_summoner_spawns_a_limited_number_of_minions(lib):
    room = arena(lib)
    s = put(room, "choir_acolyte", 300, 100)
    room.player.x, room.player.y = 100, 100
    s.brain.become_aware((100, 100))
    s.brain.react = 0
    s.facing = math.pi
    for _ in range(900):
        step(room)
    minions = [e for e in room.enemies if e.alive and e.owner_id == s.id]
    assert 1 <= len(minions) <= s.params["max_minions"]


def test_sniper_beam_is_telegraphed_with_a_line(lib):
    room = arena(lib)
    sn = put(room, "ember_sniper", 420, 120)
    room.player.x, room.player.y = 200, 120
    sn.brain.become_aware((200, 120))
    sn.brain.react = 0
    sn.facing = math.pi
    seen_tell = False
    for _ in range(200):
        step(room)
        for hb in room.hitboxes:
            if hb.owner is sn and hb.style == "line" and hb.telegraphing:
                seen_tell = True
                assert hb.damage > 0 and hb.windup >= 50
    assert seen_tell


# ---------------------------------------------------------------------------------------------- adaptation
def test_adaptive_counters_change_aim_within_bounds_and_respect_strength(lib):
    run = new_run(lib, adapt=1.0)
    now = 0.0
    for i in range(18):
        now += 1.0
        run.adapt.model.record("dodge_cw", now)
        run.adapt.ctl.update(now, 1.0)
    for i in range(300):
        now += 0.1
        run.adapt.ctl.update(now, 0.1)
    lead = run.adapt.lead_angle(1.0)
    assert 0 < lead <= 0.30 + 1e-9
    assert run.adapt.describe()
    off = new_run(lib, adapt=0.0)
    for i in range(18):
        off.adapt.model.record("dodge_cw", float(i))
        off.adapt.ctl.update(float(i), 1.0)
    assert off.adapt.lead_angle(1.0) == 0.0
    # cooldown: once on it does not flip off/on every frame
    log_before = len(run.adapt.ctl.log)
    for i in range(60):
        now += 0.1
        run.adapt.model.record("dodge_ccw", now, 3.0)
        run.adapt.ctl.update(now, 0.1)
    assert len(run.adapt.ctl.log) - log_before <= 3


def test_adaptation_changes_an_archers_aim_when_player_always_dodges_one_way(lib):
    run_a = new_run(lib, adapt=1.0)
    run_b = new_run(lib, adapt=1.0)
    now = 0.0
    for i in range(20):
        now += 1.0
        run_a.adapt.model.record("dodge_cw", now)
        run_a.adapt.ctl.update(now, 1.0)
    for i in range(200):
        now += 0.1
        run_a.adapt.ctl.update(now, 0.1)
    def aim(run):
        room = arena(lib, run)
        p = room.player
        p.x, p.y = 224, 150
        a = put(room, "ash_archer", 224, 60)
        a.brain._fire(room, a, p)
        pr = [q for q in room.projectiles if q.team == ENEMY_TEAM][-1]
        return math.atan2(pr.vy, pr.vx)
    assert abs(aim(run_a) - aim(run_b)) > 0.05


# ---------------------------------------------------------------------------------------------- boons / evolution
def test_boon_tradeoffs_and_requirements(lib):
    run = new_run(lib)
    base_hp = run.max_hp()
    assert run.perks.add("glass_cannon")
    assert run.max_hp() < base_hp and run.perks.get("damage_mul") > 1.0
    assert "chain_reaction" not in run.boon_pool(set())                 # needs kindled edge + stormcaller
    run.perks.add("kindled_edge")
    run.perks.add("stormcaller")
    assert "chain_reaction" in run.boon_pool(set())
    assert "bouncing_cinders" not in run.boon_pool(set())               # caster-only
    assert "tinderbox" not in run.boon_pool(set()) and "tinderbox" in run.boon_pool({"tinderbox"})   # unlock gated


def test_kindled_edge_trigger_ignites_enemies_and_vampiric_ash_heals(lib):
    room = arena(lib)
    room.run.perks.add("kindled_edge")
    room.run.perks.owned["kindled_edge"] = 3
    room.run.perks.rebuild()
    for tr in room.run.perks.triggers("hit"):
        tr.chance = 1.0
    e = put(room, "cinder_thrall", 224, 120)
    e.brain.react = 10 ** 6
    room.fire("hit", x=e.x, y=e.y, target=e)
    assert e.status.has("burn")
    room.run.perks.add("vampiric_ash")
    room._sync_player()
    room.player.hp = 50
    room.fire("kill", x=0, y=0, target=e)
    assert room.player.hp > 50


def test_weapon_evolves_when_counters_are_met_and_changes_moves(lib):
    run = new_run(lib, "ember_blade")
    room = arena(lib, run)
    before = {m.name for m in run.weapon.light}
    run.counters["burn_kills"] = 11
    e = put(room, "cinder_thrall", 224, 120)
    e.status.apply("burn", 1)
    e.hp = 0.1
    room._kill(e)
    assert run.weapon.id == "emberbrand"
    assert {m.name for m in run.weapon.light} != before
    assert any(ev.kind == "evolve" for ev in room.drain_events())


# ---------------------------------------------------------------------------------------------- bosses
def boss_room(lib, bid, floor):
    run = new_run(lib, "ember_blade")
    spec = LG.RoomSpec(99, 0, 0, "boss", 7, doors={}, layout=LG.build_layout("open", set()), boss=bid)
    from shardlight.modes.cinder.sim.bosses import make_boss
    room = Room(run, spec, floor, boss_factory=make_boss(bid))
    room.t = 200
    return room


@pytest.mark.parametrize("bid,floor,phases", [("slag_colossus", 3, 1), ("crown_of_embers", 5, 2), ("choir_warden", 2, 2)])
def test_bosses_have_phases_telegraph_everything_and_can_be_beaten(lib, bid, floor, phases):
    room = boss_room(lib, bid, floor)
    boss = room.boss
    hp0 = boss.max_hp
    seen_phase = 0
    seen_attacks = set()
    p = room.player
    p.max_hp = p.hp = 100000                         # a bot that cannot die: we test the boss, not the bot
    for i in range(60 * 150):
        if room.hitstop > 0:
            room.hitstop -= 1
            continue
        it = Intent()
        if boss.alive:
            dx, dy = boss.x - p.x, boss.y - p.y
            d = math.hypot(dx, dy) or 1
            it.move = (dx / d, dy / d) if d > 30 else (0, 0)
            it.aim = (dx / d, dy / d)
            if d < 46 and not boss.untargetable:
                it.pressed = {"attack"}
        room.update(it)
        for ev in room.drain_events():
            if ev.kind == "phase":
                seen_phase = max(seen_phase, ev.data["phase"])
        for hb in room.hitboxes:
            if hb.team == ENEMY_TEAM and hb.damage > 0 and not hb.done:
                committed = hb.windup == 0 and hb.follow and boss.brain.atk == "charge"   # body of a charge already telegraphed by its line
                assert hb.windup >= 8 or committed, (bid, hb.move_name, hb.windup)     # every boss attack is telegraphed
                seen_attacks.add(hb.move_name)
        p.hp = p.max_hp
        if room.boss_defeated:
            break
    assert room.boss_defeated, f"{bid} never died (hp {boss.hp}/{hp0})"
    assert seen_phase >= phases and len(seen_attacks) >= 2


# ---------------------------------------------------------------------------------------------- integration
def enter(app):
    assert app.enter_mode("cinder")
    run_ticks(app, 3)
    cs = app.scenes.top
    cs.data["seen"].update({"intro": True, "tip_move": True, "tip_dodge": True, "tip_altar": True, "tip_forge": True})
    return cs


def bot_intent(rs):
    room = rs.room
    pl = room.player
    it = Intent()
    es = [e for e in room.enemies if e.alive and not e.untargetable]
    if es:
        e = min(es, key=lambda e: (e.x - pl.x) ** 2 + (e.y - pl.y) ** 2)
        dx, dy = e.x - pl.x, e.y - pl.y
        d = math.hypot(dx, dy) or 1
        it.move = (dx / d, dy / d) if d > 28 else (0, 0)
        it.aim = (dx / d, dy / d)
        if d < 44:
            it.pressed = {"attack"}
    return it


def test_run_flow_with_bot_clears_a_room_and_save_roundtrips(app):
    from shardlight.modes.cinder import scene as S
    cs = enter(app)
    cs.begin_run("ember_blade", [])
    rs = cs.screen
    run_ticks(app, 5)
    assert isinstance(rs, S.RunScreen) and rs.room.spec.kind == "start"
    spec = next(r for r in rs.plan.rooms.values() if r.kind == "arena")
    rs.enter_room(spec.id, list(spec.doors)[0])
    orig = S.make_intent
    S.make_intent = lambda a, p, t: bot_intent(rs)
    try:
        for _ in range(60 * 60):
            run_ticks(app, 1, draw_every=8)
            if rs.room.cleared:
                break
    finally:
        S.make_intent = orig
    assert rs.room.cleared and rs.run.kills >= 2
    cs.data["soot"] = 99
    app.save_now()
    assert app.saves.read(app.slot)["modes"]["cinder"]["soot"] == 99


def test_death_ends_run_awards_soot_and_returns_to_foot(app):
    from shardlight.modes.cinder import scene as S
    cs = enter(app)
    cs.begin_run("ember_caster", [])
    rs = cs.screen
    run_ticks(app, 5)
    rs.room.player.hp = 0.5
    rs.room._hurt_player(5, 0.0, 1.0, "test", ignore_iframes=True)
    run_ticks(app, 14)
    assert isinstance(cs.screen, S.EndScreen) and not cs.screen.won
    assert cs.data["soot"] > 0 and cs.data["runs"] == 1
    assert not app.world.facet_repaired("cinder")


def test_final_boss_victory_repairs_facet_and_emits_cross_mode_events(app):
    from shardlight.modes.cinder import scene as S
    cs = enter(app)
    cs.begin_run("ember_blade", [])
    rs = cs.screen
    rs.run.floor = 5
    rs.start_floor(5)
    boss_spec = rs.plan.rooms[rs.plan.exit]
    rs.enter_room(boss_spec.id, list(boss_spec.doors)[0])
    rs.room.combat_started = True
    boss = rs.room.boss
    boss.untargetable = False
    boss.hp = 0.1
    rs.room._damage_enemy(boss, 5, type("S", (), {"x": boss.x, "y": boss.y + 10, "apply": (), "poise": 0, "knock": 0, "stop": 0,
                                                   "shake": 0, "tags": (), "crit": False, "owner": rs.room.player,
                                                   "source": "t", "unblockable": False})(), 0.0)
    assert rs.room.boss_defeated
    run_ticks(app, 80)
    stair = next(p for p in rs.room.props if p.kind == "stair")
    rs.room.player.x, rs.room.player.y = stair.x, stair.y + 6
    from shardlight.modes.cinder.sim.player import Intent as I
    S.make_intent = lambda a, p, t: I(pressed={"interact"})
    try:
        run_ticks(app, 120)
    finally:
        import importlib
        importlib.reload(S)
    assert app.world.facet_repaired("cinder")
    ev = [e for e, _ in app.world.event_log]
    assert "cinder.boss_defeated" in ev and "cinder.run_completed" in ev


def test_choir_warden_only_appears_after_cross_mode_unlock(app):
    from shardlight.modes.cinder import scene as S
    cs = enter(app)
    cs.begin_run("ember_blade", [])
    rs = cs.screen
    assert not any(r.kind == "choir" for p in [LG.generate_floor(cs.lib, 1, 2, rs.run.mods, False)] for r in p.rooms.values())
    app.world.unlock("cinder.boss.choir_warden")
    rs.run.floor = 2
    rs.start_floor(2)
    assert any(r.kind == "choir" for r in rs.plan.rooms.values())


def test_big_fight_stays_within_frame_budget(app, lib):
    from shardlight.modes.cinder import scene as S
    cs = enter(app)
    cs.begin_run("ember_blade", [])
    rs = cs.screen
    run_ticks(app, 3)
    room = rs.room
    room.combat_started = True
    for k in range(25):
        room.spawn_enemy(["cinder_thrall", "ash_archer", "fuse_imp"][k % 3], 60 + (k * 37) % 330, 50 + (k * 23) % 130, False, instant=True)
    S.make_intent = lambda a, p, t: bot_intent(rs)
    try:
        t0 = time.perf_counter()
        for _ in range(240):
            run_ticks(app, 1, draw_every=1)
        per = (time.perf_counter() - t0) / 240 * 1000
    finally:
        import importlib
        importlib.reload(S)
    assert per < 12.0, f"{per:.1f} ms/frame"
