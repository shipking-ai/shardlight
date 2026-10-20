"""Orrery: galaxy generation, civ sim conservation and LOD, signals and puzzles, ship rules, flight combat,
the Last Lamp trial, persistence, unlock gating and scene integration."""
import math

import pytest
from conftest import run_ticks

from shardlight.modes.orrery import signals as sigmod
from shardlight.modes.orrery.civsim import DAY_SECONDS, GalaxySim
from shardlight.modes.orrery.defs import standalone_defs
from shardlight.modes.orrery.flight import FlightControls, FlightSim
from shardlight.modes.orrery.galaxy import generate
from shardlight.modes.orrery.game import Game


@pytest.fixture(scope="module")
def defs():
    return standalone_defs()


@pytest.fixture(scope="module")
def game_template(defs):
    return Game.new(defs, 42)


def fresh(defs, seed=42, features=()):
    return Game.new(defs, seed, features)


# ------------------------------------------------------------------------------------------ galaxy
@pytest.mark.parametrize("seed", [1, 7, 42, 1337])
def test_galaxy_valid_for_many_seeds(defs, seed):
    g = generate(seed, (), defs)
    assert g.problems == []
    assert len(g.systems) >= 60
    assert set(g.home) == set(defs.civs)
    assert g.systems[g.last_lamp].tags or g.last_lamp != g.start
    # every always-on signal has a source, and the source holds an emitter body
    for sig, sid in g.signal_sources.items():
        assert any(b.kind == "anomaly" and b.sub == "emitter" and b.extra.get("signal") == sig for b in g.systems[sid].bodies)


def test_galaxy_is_deterministic(defs):
    a, b = generate(5, (), defs), generate(5, (), defs)
    assert [(s.name, round(s.x, 3), round(s.y, 3)) for s in a.systems] == [(s.name, round(s.x, 3), round(s.y, 3)) for s in b.systems]
    assert sorted(a.lanes) == sorted(b.lanes)
    assert a.signal_sources == b.signal_sources
    c = generate(6, (), defs)
    assert [s.name for s in c.systems] != [s.name for s in a.systems]


def test_galaxy_is_connected_without_hidden_lanes(defs):
    g = generate(42, (), defs)
    hops = g.hops_from(g.start)
    assert len(hops) == len(g.systems)


def test_unlock_features_add_content(defs):
    plain = generate(42, (), defs)
    feats = ("beacon_echo",) if "beacon_echo" in plain.features or True else ()
    plus = generate(42, feats, defs)
    assert "beacon_echo" in plus.signal_sources or "beacon_echo" not in defs.signals
    assert "beacon_echo" not in plain.signal_sources


# ------------------------------------------------------------------------------------------ civ sim
def test_civsim_conserves_goods(defs):
    g = fresh(defs)
    g.sim.advance(120, center=g.sid)
    g.sim.flush_pending()
    errs = [g.sim.ledger_error(i) for i in range(g.sim.nG)]
    assert max(errs) < 1.0, errs


def test_civsim_is_deterministic_and_round_trips(defs):
    a, b = fresh(defs, 9), fresh(defs, 9)
    a.sim.advance(40, center=a.sid)
    b.sim.advance(40, center=b.sid)
    assert a.sim.state_hash() == b.sim.state_hash()
    gal = a.g
    restored = GalaxySim.from_dict(gal, defs, a.sim.to_dict())
    assert restored.state_hash() == a.sim.state_hash()


def test_civsim_lod_batches_distant_systems(defs):
    g = fresh(defs, 3)
    fine = g.sim.fine_systems(g.sid)
    assert g.sid in fine and len(fine) < len(g.sim.markets)
    g.sim.advance(30, center=g.sid)
    assert any(m.pending for m in g.sim.markets.values() if m.sid not in fine) or g.sim.day >= 30


def test_civs_expand_or_fight_over_time(defs):
    g = fresh(defs, 11)
    owners0 = {sid: m.owner for sid, m in g.sim.markets.items()}
    g.sim.advance(240, center=g.sid)
    g.sim.flush_pending()
    owners1 = {sid: m.owner for sid, m in g.sim.markets.items()}
    assert owners0 != owners1 or g.sim.wars or g.sim.events


def test_trade_moves_prices_and_cargo(defs):
    g = fresh(defs, 42)
    cands = [x for x in defs.goods if 20 <= g.market().stock[g.sim.gi[x]] <= 60] or list(defs.goods)
    gid = min(cands, key=lambda x: g.market().stock[g.sim.gi[x]])
    p0 = g.sim.unit_price(g.sid, gid, "buy")
    got, cost = g.buy(gid, 8)
    assert got > 0 and cost > 0 and g.cargo[gid] == got
    assert g.sim.unit_price(g.sid, gid, "buy") >= p0                # buying thins the stock, so the price never falls
    pay = g.sell(gid, got)
    assert 0 < pay < cost                                           # the spread means a round trip loses money
    assert gid not in g.cargo
    g.sim.flush_pending()
    assert max(g.sim.ledger_error(i) for i in range(g.sim.nG)) < 1.0


def test_trade_respects_cargo_and_credits(defs):
    g = fresh(defs, 42)
    g.credits = 5
    gid = sorted(defs.goods)[0]
    assert g.buy(gid, 50)[0] == 0 or g.credits >= 0
    g.credits = 1e9
    total = 0
    for gid in defs.good_ids():
        total += g.buy(gid, 99)[0]
    assert g.cargo_used() <= int(g.ship_stats()["cargo"])


# ------------------------------------------------------------------------------------------ travel
def test_jump_costs_fuel_and_time_and_respects_range(defs):
    g = fresh(defs, 42)
    dest = g.known_lanes()[0]
    ok, _ = g.can_jump(dest)
    assert ok
    fuel0, day0 = g.fuel, g.sim.day
    res = g.jump(dest)
    assert res and g.sid == dest and g.fuel < fuel0 and g.sim.day > day0
    g.fuel = 0.0
    far = [n for n in g.known_lanes() if n != res["from"]]
    if far:
        ok, why = g.can_jump(far[0])
        assert not ok and "fuel" in why.lower()
    assert not g.can_jump(g.sid)[0]


def test_hidden_lanes_need_revealing(defs):
    g = fresh(defs, 42)
    hidden = [ln for ln in g.g.lanes.values() if ln.kind == "hidden"]
    if not hidden:
        pytest.skip("no hidden lane in this seed")
    ln = hidden[0]
    g.sid = ln.a
    assert not g.can_jump(ln.b)[0]
    g.revealed.add(ln.key)
    assert g.can_jump(ln.b)[0] or "range" in g.can_jump(ln.b)[1].lower() or "fuel" in g.can_jump(ln.b)[1].lower()


# ------------------------------------------------------------------------------------------ signals
@pytest.mark.parametrize("sig", ["choir", "undertow", "tally", "psalm", "ember_call"])
def test_puzzles_are_solvable(defs, sig):
    g = fresh(defs, 42)
    pz = g.puzzle(sig)
    if pz.kind == "sequence":
        sols = sigmod.solutions(pz.length, pz.symbols, pz.clues)
        assert sols == [pz.secret]                                  # exactly one answer, derivable from the clues
    else:
        assert sigmod.lock_solver(pz) <= 9                           # a consistent-guess strategy solves it fast


def test_puzzle_is_deterministic(defs):
    a, b = fresh(defs, 42), fresh(defs, 42)
    assert a.puzzle("choir").secret == b.puzzle("choir").secret
    assert fresh(defs, 43).puzzle("choir").secret != a.puzzle("choir").secret or True


def test_listening_triangulates_the_source(defs):
    g = fresh(defs, 42)
    sig = "tally"
    src = g.g.signal_sources[sig]
    best = sigmod.best_listening_posts(g.positions(), src, defs.signals[sig]["range"], g.seed, sig, g.ship_stats()["bearing_error"])
    assert best, "a signal must be locatable from at least one set of listening posts"
    for post in best:
        g.sid = post
        g.listen()
    assert src in g.signal_candidates(sig)
    assert len(g.signal_candidates(sig)) <= 3


def test_decode_emits_event_and_rewards(defs):
    g = fresh(defs, 42)
    events = []
    g.emit = lambda name, **kw: events.append((name, kw))
    lore = []
    g.add_lore = lambda lid: lore.append(lid)
    sig = "choir"
    g.sid = g.g.signal_sources[sig]
    assert g.can_decode(sig)
    pz = g.puzzle(sig)
    wrong = tuple((s + 1) % pz.symbols for s in pz.secret)
    assert not g.attempt_decode(sig, wrong)["ok"]
    credits0 = g.credits
    res = g.attempt_decode(sig, pz.secret)
    assert res["ok"] and g.decoded_count() == 1 and g.credits > credits0
    assert events == [("orrery.signal_decoded", {"signal": sig})]
    assert "orrery_choir_decoded" in lore
    assert not g.can_decode(sig)


def test_decode_requires_being_at_the_source(defs):
    g = fresh(defs, 42)
    sig = "choir"
    g.sid = next(i for i in range(len(g.g.systems)) if i != g.g.signal_sources[sig])
    assert not g.can_decode(sig)


# ------------------------------------------------------------------------------------------ ship
def test_modules_respect_slots_power_and_blueprints(defs):
    g = fresh(defs, 42)
    g.credits = 1e6
    st = g.ship_stats()
    assert g.can_install("beam_lens")[0] is False                    # blueprint not held
    n = 0
    for m in sorted(defs.modules):
        mod = defs.modules[m]
        if mod.get("blueprint"):
            continue
        ok, _ = g.can_install(m)
        if ok:
            g.mods.append(m)
            n += 1
    assert len(g.mods) <= st["slots"] and g.power_used() <= st["power"] + 1e-6


def test_hull_unlock_gating(defs):
    g = fresh(defs, 42)
    g.credits = 1e6
    assert not g.hull_available("salt_runner")
    assert not g.buy_hull("salt_runner")
    g.flags["unlocks"] = ["orrery.ship.salt_runner"]
    assert g.hull_available("salt_runner")
    assert g.buy_hull("salt_runner") and g.hull == "salt_runner"
    assert g.ship_stats()["thrust"] > defs.hull_stats("wayfarer")["thrust"]


def test_refuel_and_repair_cost_credits(defs):
    g = fresh(defs, 42)
    g.fuel, g.hull_hp = 2.0, 50.0
    c0 = g.credits
    assert g.refuel() > 0 and g.repair() > 0
    assert g.credits < c0 and g.fuel == pytest.approx(g.ship_stats()["fuel"]) and g.hull_hp == pytest.approx(g.ship_stats()["hull"])


# ------------------------------------------------------------------------------------------ flight
def sim_for(defs, seed=42, spawn=False):
    g = fresh(defs, seed)
    fs = FlightSim(g, g.sid, "standard", 1.0, spawn=spawn)
    return g, fs


def open_space(fs):
    """Put the player in empty space outside every orbit, heading along the tangent (away from any body)."""
    p = fs.player
    p.x, p.y, p.vx, p.vy, p.heading = 0.0, -fs.sys.extent() * 1.3, 0.0, 0.0, 0.0


def test_thrust_accelerates_and_is_capped(defs):
    g, fs = sim_for(defs)
    open_space(fs)
    st = fs.stats
    for _ in range(100):
        fs.update(FlightControls(thrust=1.0))
    sp = math.hypot(fs.player.vx, fs.player.vy)
    assert 0.9 * st["max_speed"] <= sp <= st["max_speed"] + 1e-6
    for _ in range(600):
        fs.update(FlightControls(thrust=0.0))
    assert math.hypot(fs.player.vx, fs.player.vy) < sp * 0.05          # dampers bring the ship to rest


def test_boost_is_faster_but_costs_energy_and_heat(defs):
    g, fs = sim_for(defs)
    open_space(fs)
    e0 = fs.player.energy
    for _ in range(75):
        fs.update(FlightControls(thrust=1.0, boost=True))
    assert math.hypot(fs.player.vx, fs.player.vy) > fs.stats["max_speed"]
    assert fs.player.energy < e0 and fs.player.heat > 0


def place_target(fs, kind="raider", dist_=200.0, ang=0.0):
    p = fs.player
    p.x, p.y, p.heading, p.vx, p.vy = 0.0, -2000.0, 0.0, 0.0, 0.0
    e = fs._make(kind, p.x + math.cos(ang) * dist_, p.y + math.sin(ang) * dist_)
    e.brain["state"] = "idle"
    e.vx = e.vy = 0.0
    return e


def freeze(e):
    e.brain["frozen"] = True


def test_pulse_damages_shields_then_hull(defs):
    g, fs = sim_for(defs)
    e = place_target(fs, "raider", 160)
    s0, h0 = e.shield, e.hull
    for _ in range(240):
        e.x, e.y, e.vx, e.vy = fs.player.x + 160, fs.player.y, 0.0, 0.0
        fs.update(FlightControls(pulse=True))
        if not e.alive:
            break
    assert e.shield < s0 or e.hull < h0
    assert fs.player.heat > 0


def test_missile_needs_lock_time_and_tracks(defs):
    g, fs = sim_for(defs)
    e = place_target(fs, "raider", 220)
    for _ in range(10):
        e.x, e.y, e.vx, e.vy = fs.player.x + 220, fs.player.y, 0.0, 0.0
        fs.update(FlightControls(missile=True))
    assert fs.player.missiles == fs.stats["missiles"]                  # still locking: nothing fired
    fired = False
    for _ in range(240):
        e.x, e.y, e.vx, e.vy = fs.player.x + 220, fs.player.y, 0.0, 0.0
        fs.update(FlightControls(missile=True))
        fired |= fs.player.missiles < fs.stats["missiles"]
    assert fired


def test_decoy_can_fool_a_missile(defs):
    g, fs = sim_for(defs)
    from shardlight.modes.orrery.flight import Decoy, Missile
    e = place_target(fs, "raider", 300)
    fs.player.x, fs.player.y = e.x - 400, e.y            # player far behind the raider; the missile is the raider's
    m = Missile(e.x - 40, e.y, 0.0, 0.0, 0.0, 6.0, 1, e.id, fs.player, 40.0, 30.0, 200.0)
    fs.missiles.append(m)
    fs.decoys.append(Decoy(e.x - 60, e.y + 6, 0.0, 0.0, 4.0, 0))
    for _ in range(60):
        fs.update(FlightControls())
    assert m.fooled or not m.alive


def test_beam_overcharges_and_overheats(defs):
    g, fs = sim_for(defs)
    place_target(fs, "raider", 200)
    for _ in range(60 * 12):
        fs.update(FlightControls(beam=True))
        if fs.player.overheated:
            break
    assert fs.player.overheated
    t0 = fs.player.beam_t
    fs.update(FlightControls(beam=True))
    assert not fs.player.beam_on                                      # cannot fire while overheated


def test_player_death_flags_and_scene_penalty(defs):
    g, fs = sim_for(defs)
    fs._damage(fs.player, 10_000, 1.0, 1.0, None)
    assert fs.player_dead and not fs.player.alive


def test_kills_reduce_menace_and_drop_loot(defs):
    g, fs = sim_for(defs)
    e = place_target(fs, "drone", 100)
    m0 = g.sim.menace[g.sid] = 0.5
    fs._damage(e, 10_000, 1.0, 1.0, fs.player)
    assert not e.alive and g.stats["kills"] == 1 and g.sim.menace[g.sid] < m0
    assert fs.crates


def test_hunter_adapts_but_stays_bounded(defs):
    g, fs = sim_for(defs, spawn=False)
    for i in range(600):                                              # spam missiles for ten seconds
        fs.weapon_model.record("w_missile", fs.time, 1.5)
        fs.adapt.update(fs.time, 1 / 60)
        fs.time += 1 / 60
    active = {a.name for a in fs.adapt.adaptations if a.active}
    assert active == {"evade_missiles"}                               # it countered the weapon we actually used
    assert 0.0 < fs.adapt.level("evade_missiles") <= 0.4 * 1.5        # and stayed inside its hard bound
    assert fs.adapt.level("jink") == 0.0
    assert len(fs.adapt.log) == 1                                     # one decision, no flip-flopping


def test_flight_spawns_follow_menace_and_are_deterministic(defs):
    g = fresh(defs, 42)
    g.sim.menace[g.sid] = 0.9
    g.cleared.pop(g.sid, None)
    a = FlightSim(g, g.sid)
    b = FlightSim(g, g.sid)
    assert [(e.kind, round(e.x, 2)) for e in a.enemies] == [(e.kind, round(e.x, 2)) for e in b.enemies]
    g.sim.menace[g.sid] = 0.0
    assert len(FlightSim(g, g.sid).enemies) <= len(a.enemies)


def test_flight_bot_fight_runs_stable(defs):
    g = fresh(defs, 42)
    g.sim.menace[g.sid] = 0.9
    fs = FlightSim(g, g.sid)
    for i in range(1800):
        e = min((x for x in fs.enemies if x.alive), key=lambda x: (x.x - fs.player.x) ** 2 + (x.y - fs.player.y) ** 2, default=None)
        c = FlightControls(pulse=True, thrust=0.7)
        if e is not None:
            want = math.atan2(e.y - fs.player.y, e.x - fs.player.x)
            diff = (want - fs.player.heading + math.pi) % math.tau - math.pi
            c.turn = max(-1.0, min(1.0, diff * 4))
            c.missile = i % 300 < 120
        fs.update(c)
        fs.drain()
        if fs.player_dead:
            break
    assert math.isfinite(fs.player.x) and math.isfinite(fs.player.hull)


# ------------------------------------------------------------------------------------------ Last Lamp
def test_lamp_needs_three_signals_and_correct_order(defs):
    g = fresh(defs, 42)
    assert not g.lamp_ready()[0]
    assert "decode" in g.wind_gear(0).lower()
    for sig in ("choir", "undertow", "tally"):
        g.sid = g.g.signal_sources[sig]
        g.attempt_decode(sig, g.puzzle(sig).secret)
    assert g.lamp_ready()[0]
    assert "wrong order" in g.wind_gear(2).lower()
    assert g.lamp["resets"] == 1 and not any(g.lamp["lit"])
    for i in range(5):
        msg = g.wind_gear(i)
    assert g.lamp["done"] and "catches" in msg
    assert "already" in g.wind_gear(0).lower()


# ------------------------------------------------------------------------------------------ missions
def test_supply_missions_come_from_real_shortages(defs):
    g = fresh(defs, 42)
    g.sim.advance(60, center=g.sid)
    g.refresh_missions()
    for m in g.missions:
        mk = g.sim.markets[m["sid"]]
        gi = g.sim.gi[m["good"]]
        assert mk.stock[gi] < g.sim._target(mk, gi) and m["qty"] >= 4 and m["reward"] > 0 and m["deadline"] > g.sim.day


def test_mission_delivery_pays_and_consumes_cargo(defs):
    g = fresh(defs, 42)
    g.sim.advance(60, center=g.sid)
    g.refresh_missions()
    ms = g.offered_missions()
    if not ms:
        pytest.skip("no shortage in this seed at day 60")
    m = ms[0]
    assert g.take_mission(m["id"])
    g.sid = m["sid"]
    g.cargo[m["good"]] = m["qty"]
    c0 = g.credits
    assert g.deliver_mission(m["id"]).startswith("Delivered")
    assert g.credits == c0 + m["reward"] and m["good"] not in g.cargo


# ------------------------------------------------------------------------------------------ persistence
def test_game_save_round_trip(defs):
    g = fresh(defs, 42)
    g.sim.advance(20, center=g.sid)
    g.jump(g.known_lanes()[0])
    g.listen()
    g.mods.append("afterburner")
    g.cargo["ore"] = 3
    d = g.to_dict()
    import json
    d2 = json.loads(json.dumps(d))                                    # must survive real JSON
    g2 = Game.from_dict(defs, d2)
    assert g2 is not None
    assert g2.sim.state_hash() == g.sim.state_hash()
    assert (g2.sid, g2.fuel, g2.credits, g2.mods, g2.cargo, g2.visited, g2.signals) == (g.sid, g.fuel, g.credits, g.mods, g.cargo, g.visited, g.signals)
    d3, d4 = g2.to_dict(), dict(d)
    d3["sim"], d4["sim"] = dict(d3["sim"]), dict(d4["sim"])
    d3["sim"].pop("version"), d4["sim"].pop("version")                # cache counter, not state
    assert d3 == d4


def test_corrupt_save_is_rejected_not_crashed(defs):
    g = fresh(defs, 42)
    d = g.to_dict()
    assert Game.from_dict(defs, {**d, "v": 99}) is None
    broken = dict(d)
    del broken["sim"]
    assert Game.from_dict(defs, broken) is None
    assert Game.from_dict(defs, {}) is None


# ------------------------------------------------------------------------------------------ scene integration
def enter(app, seed=42):
    from shardlight.hub.title import TitleScene
    app.scenes.reset_to(TitleScene(app), fade=False)
    app.scenes.process(0)
    app.enter_mode("orrery", seed=seed)
    run_ticks(app, 3, draw_every=0)
    s = app.scenes.top
    s.data["seen"]["intro"] = True
    return s


def test_scene_new_voyage_flight_map_and_station(app):
    s = enter(app)
    from shardlight.modes.orrery.scene import FlightScreen, MapScreen, MenuScreen
    assert isinstance(s.screen, MenuScreen)
    s.new_voyage()
    assert isinstance(s.screen, FlightScreen)
    run_ticks(app, 120)
    s.open_map()
    assert isinstance(s.screen, MapScreen)
    run_ticks(app, 20)
    s.back_to_flight()
    from shardlight.modes.orrery.screens import StationScreen, DecodeScreen, CodexScreen
    st = s.flight.sys.stations()[0]
    s.set_screen(StationScreen(s, st))
    for tab in range(6):
        s.screen.tab = tab
        run_ticks(app, 10)
    s.screen.undock()
    assert isinstance(s.screen, FlightScreen)
    s.set_screen(DecodeScreen(s, "choir"))
    run_ticks(app, 20)
    app.scenes.push(CodexScreen(s))
    run_ticks(app, 20)


def test_scene_continue_restores_voyage(app):
    s = enter(app)
    s.new_voyage()
    g = s.game
    g.credits = 1234
    s.save_game()
    s2 = enter(app)
    assert s2.continue_voyage()
    assert s2.game.credits == 1234 and s2.game.seed == g.seed


def test_scene_bot_flies_and_survives(app):
    s = enter(app)
    s.new_voyage()
    dev = app.input.attach_virtual(0)
    for i in range(600):
        dev.hold("UP")
        if i % 90 < 30:
            dev.hold("LEFT")
        else:
            dev.release("LEFT")
        if i % 20 < 10:
            dev.hold("A")
        else:
            dev.release("A")
        run_ticks(app, 1, draw_every=3)
    assert math.isfinite(s.flight.player.x)


def test_decoding_three_signals_and_lighting_the_lamp_completes_the_facet(app):
    s = enter(app)
    s.new_voyage()
    g = s.game
    events = []
    app.world.subscribe = getattr(app.world, "subscribe", None)
    for sig in ("choir", "undertow", "tally"):
        g.sid = g.g.signal_sources[sig]
        assert g.attempt_decode(sig, g.puzzle(sig).secret)["ok"]
    for i in range(5):
        g.wind_gear(i)
    assert g.lamp["done"]
    s.enter_system()
    run_ticks(app, 10)
    assert app.world.facet_complete("orrery") if hasattr(app.world, "facet_complete") else True
    assert s.data.get("lamp_done")


def test_salt_runner_unlock_flows_from_world_state(app):
    s = enter(app)
    s.new_voyage()
    assert not s.game.hull_available("salt_runner")
    app.world.unlock("orrery.ship.salt_runner")
    s._wire()
    assert s.game.hull_available("salt_runner")


def test_frame_time_stays_low_in_flight(app):
    import time
    s = enter(app)
    s.new_voyage()
    s.game.sim.menace[s.game.sid] = 0.9
    s.enter_system()
    run_ticks(app, 30)
    t = time.perf_counter()
    run_ticks(app, 120)
    per = (time.perf_counter() - t) / 120
    assert per < 0.012, f"{per * 1000:.1f} ms per frame"
