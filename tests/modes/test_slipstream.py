"""Slipstream: tracks, physics, race rules, rivals, adaptation, ghosts and the scene (1P and split-screen 2P)."""
import json
import math
from pathlib import Path

import pytest
from conftest import run_ticks

from shardlight.core.paths import DATA_DIR
from shardlight.modes.slipstream import track as T
from shardlight.modes.slipstream.ai import Driver, LineModel, classify_pass, make_adaptation
from shardlight.modes.slipstream.physics import Car, Controls, Env, SALT, TARMAC, SURFACE_MU, resolve_cars
from shardlight.modes.slipstream.race import (DT, Race, ghost_pose, pack_ghost, unpack_ghost)
from shardlight.modes.slipstream.vehicle import spec_from_dict

VEH = {e["id"]: e for e in json.loads((DATA_DIR / "slipstream.vehicle" / "slipstream_vehicles.json").read_text())["entries"]}


def spec(vid, levels=None):
    return spec_from_dict(VEH[vid], levels)


def ai_race(seed, laps=2, n=4, personalities=("clean", "aggressive", "erratic", "clean", "aggressive", "clean")):
    tr = T.generate(seed)
    race = Race(tr, laps, seed)
    ids = ["kestrel", "mantis", "anvil", "lance", "kestrel", "mantis"]
    for k in range(n):
        sp = spec(ids[k])
        race.add(f"ai{k}", sp, driver=Driver(LineModel(tr, sp), personalities[k], 0.9, seed + k))
    return tr, race


# --------------------------------------------------------------------------------------- tracks
def test_tracks_are_deterministic_and_valid_over_many_seeds():
    for seed in range(120):
        a, b = T.generate(seed), T.generate(seed)
        assert a.pts == b.pts and a.width == b.width and a.gates == b.gates
        assert T.validate(a) == [], (seed, T.validate(a))
    assert T.generate(1).pts != T.generate(2).pts


def test_track_geometry_properties():
    t = T.generate(12)
    assert T.MIN_LEN <= t.length <= T.MAX_LEN
    assert all(66 <= w <= 110 for w in t.width)
    assert len(t.gates) >= 4 and t.gates == sorted(set(t.gates), key=lambda g: (g - t.start) % t.n)
    zone, i, d, surf = t.probe(*t.pts[40])
    assert zone == "track" and abs(d) < 1
    nx, ny = t.norm[40]
    far = (t.pts[40][0] + nx * (t.width[40] * 0.5 + T.SHOULDER + 12), t.pts[40][1] + ny * (t.width[40] * 0.5 + T.SHOULDER + 12))
    assert t.probe(*far)[0] in ("wall", "cut")


def test_shortcut_rejoins_and_has_no_required_gate_inside():
    found = 0
    for seed in range(60):
        t = T.generate(seed)
        if t.cut:
            found += 1
            assert t.cut.length() < ((t.cut.ib - t.cut.ia) % t.n) * T.SPACING * 0.82
            x, y = (t.cut.ax + t.cut.bx) / 2, (t.cut.ay + t.cut.by) / 2
            assert t.probe(x, y)[0] == "cut"
    assert found >= 20


# --------------------------------------------------------------------------------------- physics
def test_top_speed_matches_spec_and_brakes_stop_the_car():
    for vid in VEH:
        sp = spec(vid)
        c = Car(sp, 0, 0, 0)
        env = Env(mu=1.0, surface=TARMAC)
        for _ in range(60 * 14):
            c.step(Controls(throttle=1.0), env, DT)
        assert abs(c.speed - sp.top_speed) / sp.top_speed < 0.04, vid
        d0 = c.x
        n = 0
        while c.speed > 4 and n < 600:
            c.step(Controls(brake=1.0), env, DT)
            n += 1
        assert n < 120 and c.x - d0 < 130


def test_salt_has_less_grip_than_tarmac_and_oil_is_slippery():
    def turned(surface):
        c = Car(spec("kestrel"), 0, 0, 0)
        c.vx = 200
        env = Env(mu=SURFACE_MU[surface], surface=surface)
        for _ in range(60):
            c.step(Controls(throttle=0.6, steer=1.0), env, DT)
        return abs(c.heading), c.speed
    tarmac, _ = turned(TARMAC)
    salt, _ = turned(SALT)
    from shardlight.modes.slipstream.physics import OIL
    oil, _ = turned(OIL)
    assert tarmac > salt > oil                      # less grip, less turning at the same speed and lock


def test_drift_builds_boost_commits_when_clean_and_crash_cancels_it():
    sp = spec("mantis")
    env = Env(mu=0.6, surface=SALT)
    c = Car(sp, 0, 0, 0)
    c.vx = 220
    for _ in range(40):
        c.step(Controls(throttle=1.0), env, DT)
    for _ in range(44):
        c.step(Controls(throttle=1.0, steer=1.0, handbrake=True), env, DT)
    assert c.drifting and c.bank > 3
    for _ in range(120):
        c.step(Controls(throttle=1.0, steer=-0.2), env, DT)
    assert c.boost > 3 and c.bank == 0               # committed after the drift ended cleanly
    c2 = Car(sp, 0, 0, 0)
    c2.vx = 220
    for _ in range(30):
        c2.step(Controls(throttle=1.0), env, DT)
    for _ in range(44):
        c2.step(Controls(throttle=1.0, steer=1.0, handbrake=True), env, DT)
    banked = c2.bank
    assert c2.lose_drift() == banked and c2.bank == 0 and c2.boost == 0


def test_boost_raises_speed_above_top_speed_and_draft_refills_meter():
    sp = spec("lance")
    c = Car(sp, 0, 0, 0)
    env = Env(mu=1.0, surface=TARMAC)
    for _ in range(60 * 10):
        c.step(Controls(throttle=1.0), env, DT)
    base = c.speed
    c.boost = 100
    for _ in range(90):
        c.step(Controls(throttle=1.0, boost=True), env, DT)
    assert c.speed > base * 1.08
    c.boost = 0
    env.draft = 1.0
    for _ in range(120):
        c.step(Controls(throttle=1.0), env, DT)
    assert c.boost > 5


def test_car_collision_is_symmetric_and_stable():
    a, b = Car(spec("kestrel"), 0, 0, 0), Car(spec("anvil"), 14, 2, math.pi)
    a.vx, b.vx = 120, -80
    for _ in range(60):
        resolve_cars(a, b)
        a.x += a.vx * DT
        b.x += b.vx * DT
        assert all(math.isfinite(v) for v in (a.x, a.vx, b.x, b.vx, a.yaw, b.yaw))
    assert a.vx < 120 and b.vx > -80              # both were slowed by the contact
    assert abs(a.vx) < abs(b.vx) or a.spec.mass < b.spec.mass


def test_upgrades_change_stats_with_tradeoffs():
    base = spec("kestrel")
    up = spec("kestrel", {"tires": 3})
    assert up.grip > base.grip and up.slide > base.slide      # more grip but harder to start a slide
    up2 = spec("kestrel", {"aero": 3})
    assert up2.top_speed > base.top_speed and up2.grip < base.grip


# --------------------------------------------------------------------------------------- race rules
def test_ai_field_completes_laps_without_cheating_speed():
    for seed in (12, 28, 7):
        tr, race = ai_race(seed, 2, 4)
        while race.state != "finished" and race.frame < 60 * 220:
            race.step()
        assert race.state == "finished"
        assert all(r.finished for r in race.racers), seed
        fastest = min(r.best_lap for r in race.racers)
        assert fastest > tr.length / (max(r.spec.top_speed for r in race.racers) * 1.5)   # no teleporting
        for r in race.racers:
            assert r.car.speed <= r.spec.top_speed * 1.6   # boost only, nobody exceeds the physical limits
            assert r.wall_hits < 25
        assert [r.position for r in race.results] == list(range(1, len(race.racers) + 1))


def test_rivals_use_the_same_limits_as_the_player():
    tr, race = ai_race(12, 1, 2)
    ai_car = race.racers[0]
    human = race.add("p", spec("kestrel"), human=0)
    assert ai_car.car.spec.top_speed == spec("kestrel").top_speed == human.car.spec.top_speed
    assert not hasattr(ai_car.driver, "speed_bonus")


def test_skipping_checkpoints_does_not_count_a_lap():
    tr = T.generate(12)
    race = Race(tr, 3, 1)
    r = race.add("p", spec("kestrel"), human=0)
    race.state = "racing"
    race.t = 0.1
    for k in range(4):                                  # teleport across the start line repeatedly
        i = (tr.start - 3) % tr.n
        r.car.place(*tr.pts[i], 0.0)
        r.hint = r.prev_i = i
        for _ in range(3):
            r.car.place(tr.pts[(tr.start + 2) % tr.n][0], tr.pts[(tr.start + 2) % tr.n][1], 0.0)
            race.step()
    assert r.laps_done == 0


def test_chronograph_rewinds_once_per_lap():
    tr = T.generate(12)
    race = Race(tr, 3, 1)
    sp = spec("chronograph")
    assert sp.special == "rewind"
    r = race.add("p", sp, human=0)
    race.state = "racing"
    race.t = 0.0
    for _ in range(150):
        r.ctl = Controls(throttle=1.0)
        race.step()
    before = (r.car.x, r.car.y)
    r.ctl = Controls(throttle=1.0, rewind=True)
    race.step()
    after = (r.car.x, r.car.y)
    assert math.hypot(before[0] - after[0], before[1] - after[1]) > 60       # jumped back ~1.5 s
    assert not r.rewind_ready
    for _ in range(100):
        r.ctl = Controls(throttle=1.0)
        race.step()
    pos = (r.car.x, r.car.y)
    r.ctl = Controls(throttle=1.0, rewind=True)
    race.step()
    assert math.hypot(r.car.x - pos[0], r.car.y - pos[1]) < 12               # second rewind is refused


def test_rivals_overtake_and_recover_from_spins():
    changes = 0
    for seed in (3, 12, 24):
        tr, race = ai_race(seed, 2, 6)
        last = {}
        for _ in range(60 * 70):
            race.step()
            for r in race.racers:
                if r.idx in last and last[r.idx] != r.position and race.state == "racing":
                    changes += 1
                last[r.idx] = r.position
    assert changes >= 6
    tr, race = ai_race(12, 1, 1)
    r = race.racers[0]
    race.state = "racing"
    race.t = 0.2
    for _ in range(120):
        race.step()
    r.car.yaw = 9.0                                      # violent spin
    r.car.heading += 2.5
    for _ in range(60 * 45):
        race.step()
        if r.laps_done >= 1:
            break
    assert r.laps_done >= 1                              # it recovered and finished a lap


def test_adaptation_is_bounded_scaled_and_observable():
    tr = T.generate(12)
    model, ctl = make_adaptation(1.0)
    for i in range(12):
        model.record("pass_inside", 100 + i)
        ctl.update(100 + i, 1.0)
    for k in range(500):
        ctl.update(120 + k * 0.1, 0.1)
    lvl = ctl.level("block_inside")
    assert 0.0 < lvl <= 0.3 * 1.5 + 1e-9
    m2, c2 = make_adaptation(0.0)
    for i in range(12):
        m2.record("pass_inside", i)
        c2.update(i, 1.0)
    assert c2.level("block_inside") == 0.0
    # effect: with adaptation active a defending rival shifts its lane toward the apex when the human is close behind
    sp = spec("kestrel")
    race = Race(tr, 2, 1)
    drv = Driver(LineModel(tr, sp), "clean", 0.9, 1, ctl)
    rival = race.add("ai", sp, driver=drv)
    human = race.add("p", sp, human=0)
    i = tr.start + 40
    x, y = tr.pts[i]
    h = math.atan2(tr.tang[i][1], tr.tang[i][0])
    rival.car.place(x, y, h, 150)
    rival.hint = i
    human.car.place(x - math.cos(h) * 30, y - math.sin(h) * 30, h, 150)
    race.t = 5.0
    drv.lane_until = 0
    drv._lanes(race, rival, i, 5.0)
    assert abs(drv.lane_shift) > 0 if abs(tr.kappa[i]) > 1e-9 else True


def test_ghost_pack_roundtrip_and_pose():
    samples = [(100.0 + k * 3.25, -50.5 + k * 1.75, (k * 0.01) % 3) for k in range(200)]
    back = unpack_ghost(pack_ghost(samples))
    assert len(back) == 200
    assert max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(samples, back)) < 0.6
    p = ghost_pose(back, 1.0)
    assert p is not None and abs(p[0] - samples[30][0]) < 2
    assert unpack_ghost("not base64!!") == []


# --------------------------------------------------------------------------------------- scene
def enter(app, **opts):
    assert app.enter_mode("slipstream", **opts)
    run_ticks(app, 3)
    ss = app.scenes.top
    ss.data["seen"]["race"] = True
    return ss


def test_single_player_scene_with_bot_driver_completes_a_lap(app):
    from shardlight.modes.slipstream.scene import RaceScreen
    ss = enter(app, seed=12)
    ss.set_screen(RaceScreen(ss, "race", ["kestrel", None]))
    rs = ss.screen
    me = rs.player_racers[0]
    bot = Driver(LineModel(rs.track, me.spec), "clean", 0.9, 4)
    dev = app.input.attach_virtual(0)
    for _ in range(60 * 75):
        c = bot.control(rs.race, me) if rs.race.state != "countdown" else Controls()
        dev.release_all()
        if c.throttle > 0.5:
            dev.hold("UP")
        if c.brake > 0.5:
            dev.hold("DOWN")
        dev.set_stick(c.steer, 0.0)
        if c.handbrake:
            dev.hold("X")
        run_ticks(app, 1, draw_every=6)
        if me.laps_done >= 1:
            break
    assert me.laps_done >= 1 and me.lap_times[0] > 15


def test_split_screen_two_players_have_separate_viewports_and_inputs(app):
    from shardlight.modes.slipstream.scene import RaceScreen
    ss = enter(app, seed=12, players=2)
    app.input.assign_local(2)
    d0 = app.input.attach_virtual(0)
    d1 = app.input.attach_virtual(1)
    ss.set_screen(RaceScreen(ss, "versus", ["kestrel", "mantis"]))
    rs = ss.screen
    assert len(rs.views) == 2 and rs.views[0].rect.right <= rs.views[1].rect.left
    assert rs.views[0].racer is not rs.views[1].racer
    run_ticks(app, 60 * 4 + 10, draw_every=0)               # countdown
    d0.hold("UP")
    d1.hold("DOWN")                                          # P2 only reverses/brakes
    x0 = [(v.racer.car.x, v.racer.car.y) for v in rs.views]
    run_ticks(app, 120)
    d0.release_all()
    d1.release_all()
    p1, p2 = rs.player_racers
    assert p1.car.speed > 80 and p2.car.forward_speed < 5      # P2 only braked/reversed
    assert rs.views[0].cam != rs.views[1].cam


def test_controller_loss_pauses_and_race_resumes(app):
    from shardlight.modes.slipstream.scene import RacePause, RaceScreen
    ss = enter(app, seed=12, players=2)
    app.input.assign_local(2)
    ss.set_screen(RaceScreen(ss, "versus", ["kestrel", "mantis"]))
    run_ticks(app, 30)
    app.input.slots[1].lost_pad = True
    app.input.notices.append(("pad_lost", 1))
    run_ticks(app, 3)
    assert isinstance(app.scenes.top, RacePause) and "disconnected" in app.scenes.top.reason
    frame = ss.screen.race.frame
    run_ticks(app, 20)
    assert ss.screen.race.frame == frame
    app.scenes.top._keyboard()
    app.scenes.pop()
    run_ticks(app, 5)
    assert ss.screen.race.frame > frame


def test_championship_win_emits_cup_event_and_repairs_facet(app):
    from shardlight.modes.slipstream.scene import RaceScreen, ResultsScreen
    ss = enter(app, seed=12)
    cup = ss.cups[0]
    assert cup["id"] == "salt_cup" and len(cup["tracks"]) == 4
    state = {"round": 0, "points": {}, "vehicle": "kestrel", "results": []}
    for rnd in range(4):
        ss.set_screen(RaceScreen(ss, "cup", ["kestrel", None], cup, state))
        rs = ss.screen
        for r in rs.race.racers:                      # make the player win every round deterministically
            r.finished = r.human >= 0
        rs.race.results = [rs.player_racers[0]] + [r for r in rs.race.racers if r.human < 0]
        for pos, r in enumerate(rs.race.results, 1):
            r.position = pos
            r.finish_time = 60 + pos
        rs._cup_points(rs.race.results)
        res = ResultsScreen(ss, rs)
        if rnd < 3:
            assert not res.cup_done
    assert res.cup_done and res.cup_win and res.facet
    assert app.world.facet_repaired("slipstream")
    assert "slipstream.championship_won" in [e for e, _ in app.world.event_log]
    assert app.world.has_lore("slipstream_origin")


def test_chronograph_gated_by_unlock_and_garage_purchases(app):
    ss = enter(app, seed=12)
    assert "chronograph" not in ss.owned_ids()
    app.world.unlock("slipstream.vehicle.chronograph")
    app.return_to_hub()
    run_ticks(app, 2)
    ss = enter(app, seed=12)
    assert "chronograph" in ss.owned_ids()
    ss.data["credits"] = 500
    from shardlight.modes.slipstream.vehicle import upgrade_cost
    raw = ss.garage.raw["kestrel"]
    cost = upgrade_cost(raw, "engine", 1)
    ss.data["levels"].setdefault("kestrel", {})["engine"] = 1
    assert ss.spec("kestrel").power > spec("kestrel").power
    assert cost > 0


def test_save_roundtrip_of_bests_and_credits(app):
    ss = enter(app, seed=12)
    ss.data["credits"] = 77
    ss.data["bests"]["12"] = {"time": 41.2, "vehicle": "kestrel", "ghost": pack_ghost([(1, 2, 0.5)] * 10)}
    app.save_now()
    prof = app.saves.read(app.slot)
    assert prof["modes"]["slipstream"]["credits"] == 77
    assert len(unpack_ghost(prof["modes"]["slipstream"]["bests"]["12"]["ghost"])) == 10
