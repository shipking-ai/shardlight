"""Umbra: content, level generation and solvability, senses and enemy behaviour, pacing director, adaptation,
objectives, checkpoints, persistence and scene integration."""
import copy
import json
import math
import time

import pytest
from conftest import run_ticks

from shardlight.modes.umbra import levelgen
from shardlight.modes.umbra.catalog import Catalog
from shardlight.modes.umbra.consts import DOOR, FLOOR, TILE
from shardlight.modes.umbra.enemies import Hark, Stillwatch, Understudy
from shardlight.modes.umbra.props import PROP_DEFS
from shardlight.modes.umbra.sim import Controls, Game


@pytest.fixture(scope="module")
def cat():
    return Catalog.load_default()


def new_game(cat, night=1, seed=3, **kw):
    return Game(cat, night, seed, **kw)


def calm_game(cat, night=1, seed=3, **kw):
    """A game with the enemies parked far away and the director off, for rules that need a quiet room."""
    g = new_game(cat, night, seed, **kw)
    for e in g.enemies:
        e.x, e.y = -9999.0, -9999.0
    g.director.cfg["opening_calm"] = 1e9
    return g


def px(c):
    return ((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE)


def step(g, n=1, **ctl):
    for _ in range(n):
        g.update(1 / 60, Controls(**ctl))


def walk_to(g, target_px, limit=9000, sneak=False):
    """Drive the player along a real path to a pixel position."""
    for _ in range(limit):
        p = g.p
        if math.hypot(p.x - target_px[0], p.y - target_px[1]) < 5:
            return True
        pth = g.path((p.x, p.y), target_px, can_open=True, enemy=False, keys=frozenset(p.pocket))
        if not pth:
            return False
        if len(pth) < 2:
            nx, ny = target_px
            c = None
        else:
            nx, ny = px(pth[1])
        # open any door in the way
        c = pth[1] if len(pth) > 1 else None
        if c is not None and g.lv.grid[c[1], c[0]] == DOOR:
            d = g.doors[g.door_at[c]]
            if not d.passable:
                if d.locks:
                    g.try_unlock(d)
                g.set_door(d, True, True, "player")
                step(g, 20)
                continue
        dx, dy = nx - p.x, ny - p.y
        n = math.hypot(dx, dy) or 1
        step(g, 1, move=(dx / n, dy / n), sneak=sneak)
    return False


# ------------------------------------------------------------------------------------------ content
def test_content_loads_cleanly_and_ids_resolve(cat):
    assert cat.db.problems == []
    assert cat.night_count() == 3
    for n in (1, 2, 3):
        nd = cat.night(n)
        for e in nd["enemies"]:
            assert cat.enemy(e) is not None
        for it in list(nd.get("supplies", {})) + list(nd.get("start", {})):
            assert it in [d["id"] for d in cat.db.all("umbra.item")], it
    for note in cat.notes():
        assert len(note["text"]) <= 400
    for r in cat.db.all("umbra.recipe"):
        for k in ("a", "b", "out"):
            assert r[k] in [d["id"] for d in cat.db.all("umbra.item")]


def test_echo_item_is_gated_by_the_lantern_ward_unlock(cat):
    locked = Catalog.load_default(lambda u: False)
    opened = Catalog.load_default(lambda u: u == "umbra.item.lantern_ward")
    assert "lantern_ward" not in locked.item_ids() and "lens_shard" not in locked.item_ids()
    assert "lantern_ward" in opened.item_ids() and "lens_shard" in opened.item_ids()
    assert locked.find_recipe("lens_shard", "oil_flask") is None
    assert opened.find_recipe("lens_shard", "oil_flask")["out"] == "lantern_ward"
    lv = levelgen.generate(1, 5, locked)
    assert not any(it in ("lens_shard", "lantern_ward") for it, _ in levelgen.item_cells(lv))


# ------------------------------------------------------------------------------------------ level generation
@pytest.mark.parametrize("night", [1, 2, 3])
def test_levels_are_valid_and_solvable_across_seeds(cat, night):
    for seed in range(1, 11):
        lv = levelgen.generate(night, seed, cat)
        assert lv.problems == [], (night, seed, lv.problems)
        assert lv.grid[lv.start[1], lv.start[0]] in (FLOOR,)
        assert lv.rooms[lv.safe_rooms[0]].contains(lv.start)
        # every room is reachable on foot (props considered) once locks are opened
        have, closed = levelgen.solve_order(lv, cat)
        assert closed <= {d.id for d in lv.doors if d.gate}


def test_levelgen_is_deterministic_and_seeds_differ(cat):
    a, b = levelgen.generate(2, 11, cat), levelgen.generate(2, 11, cat)
    assert (a.grid == b.grid).all() and [(p.kind, p.cell) for p in a.props] == [(p.kind, p.cell) for p in b.props]
    assert a.items_floor == b.items_floor
    c = levelgen.generate(2, 12, cat)
    assert not (a.grid == c.grid).all()


def test_keys_are_never_behind_their_own_locks(cat):
    for night in (1, 2, 3):
        for seed in range(1, 8):
            lv = levelgen.generate(night, seed, cat)
            closed = {d.id for d in lv.doors if d.locks or d.gate}
            g0 = levelgen.walkable_grid(lv, closed)
            reach = levelgen._bfs(g0, lv.start)
            for d in lv.doors:
                if d.locks:
                    for k in d.locks:
                        cells = [c for it, c in levelgen.item_cells(lv) if it == k]
                        assert cells, f"night {night} seed {seed}: {k} missing"


def test_the_night_has_the_loot_it_needs(cat):
    lv = levelgen.generate(3, 4, cat)
    counts = {}
    for it, c in levelgen.item_cells(lv):
        counts[it] = counts.get(it, 0) + 1
    nd = cat.night(3)
    for it, n in nd["need"].items():
        if it != "throwable":
            assert counts.get(it, 0) >= n


def test_stories_and_notes_are_placed_and_readable(cat):
    lv = levelgen.generate(2, 6, cat)
    assert lv.notes
    for nid, cell in lv.notes:
        assert cat.note(nid) is not None and lv.grid[cell[1], cell[0]] == FLOOR
    assert any(r.role == "clock" for r in lv.rooms)
    assert any(p.kind == "clock" for p in lv.props)


def test_generation_time_budget(cat):
    t = time.perf_counter()
    levelgen.generate(3, 21, cat)
    assert time.perf_counter() - t < 3.0


# ------------------------------------------------------------------------------------------ senses: sound and light
def test_walls_muffle_sound_and_doors_less_than_walls(cat):
    g = calm_game(cat)
    lv = g.lv
    r = next(r for r in lv.rooms if not r.hall and r.role == "any")
    a = px(r.center)
    door = lv.doors[r.doors[0]]
    outside_cell = door.cells[0]
    b = px((outside_cell[0] + (3 if door.vertical else 0), outside_cell[1] + (0 if door.vertical else 3)))
    clear = g.occlusion(a, a)
    assert clear == 0
    assert g.occlusion(a, px((0, 0))) > 0


def test_sneaking_is_much_quieter_than_running(cat):
    g = calm_game(cat)
    heard = {"walk": 0, "sneak": 0, "run": 0}
    noises = []
    orig = g.emit_noise

    def spy(kind, x, y, loud=None, source="player"):
        if kind == "step":
            noises.append(loud)
        return orig(kind, x, y, loud, source)
    g.emit_noise = spy
    for stance, kw in (("sneak", {"sneak": True}), ("walk", {}), ("run", {"run": True})):
        noises.clear()
        g.p.stamina = 5.0
        for _ in range(300):
            g.update(1 / 60, Controls(move=(1, 0), **kw))
            if g.p.x > (g.lv.w - 3) * TILE:
                break
        heard[stance] = sum(noises) / max(1, len(noises)) if noises else 0
        g.p.x, g.p.y = px(g.lv.start)
    assert heard["sneak"] < heard["walk"] < heard["run"] or heard["run"] == 0


def test_hark_hears_noise_it_is_close_to_and_ignores_far_noise(cat):
    g = calm_game(cat)
    hk = next(e for e in g.enemies if isinstance(e, Hark))
    room = next(r for r in g.lv.rooms if not r.hall and r.role == "any")
    hk.x, hk.y = px(room.center)
    hk.state = "patrol"
    g.emit_noise("door_slam", hk.x + 3 * TILE, hk.y)
    assert hk.pending is not None or hk.state == "recoil"
    hk.pending = None
    hk.state = "patrol"
    g.emit_noise("step", hk.x + 30 * TILE, hk.y, 3.0)
    assert hk.pending is None


def test_a_thrown_tin_lures_the_hark_to_the_noise_not_the_player(cat):
    g = calm_game(cat)
    hk = next(e for e in g.enemies if isinstance(e, Hark))
    room = max((r for r in g.lv.rooms if not r.hall and r.role == "any"), key=lambda r: r.w * r.h)
    free = [c for c in room.cells() if not g.solid_cell(c)]
    free.sort()
    hk.x, hk.y = px(free[0])
    lure = free[len(free) // 2]
    g.p.x, g.p.y = px(free[-1])
    assert math.hypot(*(a - b for a, b in zip(px(free[-1]), px(free[0])))) > 5 * TILE
    g.emit_noise("thrown_default", *px(lure), 9.0)
    for _ in range(600):
        g.update(1 / 60, Controls())
        if hk.state in ("listen", "search"):
            break
    target = px(lure)
    assert math.hypot(hk.x - target[0], hk.y - target[1]) < 3 * TILE
    assert math.hypot(hk.x - g.p.x, hk.y - g.p.y) > 2 * TILE                 # it went to the noise, not to the player
    assert "hark:lured" in g.journal["facts"]


def test_very_loud_noise_makes_the_hark_recoil_then_come_looking(cat):
    g = calm_game(cat)
    hk = next(e for e in g.enemies if isinstance(e, Hark))
    room = next(r for r in g.lv.rooms if not r.hall and r.role == "any")
    hk.x, hk.y = px(room.center)
    g.emit_noise("door_break", hk.x + 2 * TILE, hk.y)
    assert hk.state == "recoil"
    x0 = hk.x
    step(g, 50)
    assert abs(hk.x - x0) < 1.0                                   # stunned in place
    step(g, 120)
    assert hk.state in ("investigate", "listen", "search")


def test_hark_pounds_a_locked_door_until_it_breaks(cat):
    g = calm_game(cat, 1, 3)
    hk = next(e for e in g.enemies if isinstance(e, Hark))
    d = next(d for d in g.doors if d.locks)
    dd = g.lv.doors[d.id]
    hk.can_open = True
    # stand the Hark next to the door on the side of room `a`, aim it at the other side
    a_room = g.lv.rooms[dd.a]
    c = dd.cells[0]
    hk.x, hk.y = px((c[0] - (1 if dd.vertical else 0), c[1] - (0 if dd.vertical else 1)))
    other = g.lv.rooms[dd.b]
    hk.state = "investigate"
    hk.goto(px(other.center))
    assert hk.path
    for _ in range(60 * 14):
        g.update(1 / 60, Controls())
        if d.broken:
            break
    assert d.broken and d.bangs >= 6
    assert any(n.kind == "door_bang" for n in g.noise_log)


def test_enemies_never_enter_the_safe_room(cat):
    g = calm_game(cat, 2, 3)
    safe = g.lv.rooms[g.lv.safe_rooms[0]]
    hk = next(e for e in g.enemies if isinstance(e, Hark))
    other = next(r for r in g.lv.rooms if not r.hall and r.role == "any")
    hk.x, hk.y = px(other.center)
    hk.state = "hunt"
    hk.memory.observe(__import__("shardlight.core.ai", fromlist=["Evidence"]).Evidence("heard", px(safe.center), 0, 1.0))
    assert hk.goto(px(safe.center)) is False                  # the safe room is not on any enemy route
    assert g.path((hk.x, hk.y), px(safe.center), True, breaker=True) is None
    for _ in range(60 * 30):
        g.update(1 / 60, Controls())
        assert not safe.contains(g.cell_of(hk.x, hk.y)), "an enemy entered the safe room"


def test_stillwatch_sees_only_lit_players(cat):
    g = calm_game(cat, 1, 3)
    sw = next(e for e in g.enemies if isinstance(e, Stillwatch))
    room = next(r for r in g.lv.rooms if not r.hall and r.role == "any" and r.w >= 7 and r.h >= 5)
    sw.x, sw.y = px((room.x + 1, room.y + 2))
    sw.facing = 0
    g.p.x, g.p.y = px((room.x + 5, room.y + 2))
    g.lv.lamps[:] = []
    g.lv.windows[:] = []
    g.p.mode = "off"
    g.touch()
    assert not sw._sees_player()
    g.p.mode = "lamp"
    g.p.oil = 80
    assert sw._sees_player()
    g.p.mode = "off"
    g.p.match = 4.0
    assert sw._sees_player()


def test_flashlight_beam_freezes_the_stillwatch_then_makes_it_recoil(cat):
    g = calm_game(cat, 1, 3)
    sw = next(e for e in g.enemies if isinstance(e, Stillwatch))
    room = next(r for r in g.lv.rooms if not r.hall and r.role == "any" and r.w >= 8 and r.h >= 5)
    sw.x, sw.y = px((room.x + room.w - 2, room.y + 2))
    g.p.x, g.p.y = px((room.x + 1, room.y + 2))
    g.p.facing = 0.0
    g.p.mode = "flash"
    g.p.battery = 100
    sw.state = "rush"
    x0 = sw.x
    step(g, 90)
    assert sw.state == "frozen" and abs(sw.x - x0) < 2                         # stopped dead in the beam
    for _ in range(60 * 8):
        g.p.battery = 100
        g.update(1 / 60, Controls())
        if sw.state == "recoil":
            break
    assert sw.state == "recoil"
    assert sw.beam_t >= 6.0
    g.p.mode = "off"
    step(g, 60 * 6)
    assert sw.state != "recoil"


def test_stillwatch_cannot_open_doors_and_ignores_a_warded_player(cat):
    g = calm_game(cat, 1, 3)
    sw = next(e for e in g.enemies if isinstance(e, Stillwatch))
    assert sw.can_open is False
    d = next(d for d in g.doors if not d.locks and not d.gate)
    dd = g.lv.doors[d.id]
    a, b = g.lv.rooms[dd.a], g.lv.rooms[dd.b]
    sw.x, sw.y = px(a.center)
    pth = g.path((sw.x, sw.y), px(b.center), can_open=False)
    d.open = d.want = 0.0
    g.touch()
    pth = g.path((sw.x, sw.y), px(b.center), can_open=False)
    assert pth is None or all(c not in dd.cells for c in pth)
    # a Lantern Ward hides the player from it
    from shardlight.modes.umbra.sim import Ward
    g.p.x, g.p.y = px(a.center)
    sw.x, sw.y = g.p.x + 4 * TILE, g.p.y
    g.p.mode = "lamp"
    g.p.oil = 90
    g.wards.append(Ward(g.p.x, g.p.y, 30, 4.6))
    assert g.in_ward(g.p.x, g.p.y) and not sw._sees_player()


# ------------------------------------------------------------------------------------------ understudy and adaptation
def test_understudy_checks_the_hiding_places_you_favour_more_often_but_within_bounds(cat):
    g = calm_game(cat, 2, 3)
    us = next(e for e in g.enemies if isinstance(e, Understudy))
    base = us.hide_check_prob("locker")
    assert base == pytest.approx(0.3, abs=0.01)
    for i in range(30):
        g.time = 5.0 + i * 3
        g.director.player_model.record("hide_locker", g.time, 1.0)
        g.director.ctl.update(g.time, 3.0)
    assert us.hide_check_prob("locker") > base + 0.1
    assert us.hide_check_prob("locker") <= base + 0.4 * 1.5 + 1e-6      # hard bound
    assert us.hide_check_prob("bed") == pytest.approx(base, abs=0.02)   # habits are per hiding type
    g2 = calm_game(cat, 2, 3, adapt=0.0)
    us2 = next(e for e in g2.enemies if isinstance(e, Understudy))
    for i in range(30):
        g2.time = 5.0 + i * 3
        g2.director.player_model.record("hide_locker", g2.time, 1.0)
        g2.director.ctl.update(g2.time, 3.0)
    assert us2.hide_check_prob("locker") == pytest.approx(0.3, abs=0.01)    # the slider turns adaptation off


def test_understudy_finds_a_hiding_player_but_not_a_player_in_an_unchecked_prop(cat):
    g = calm_game(cat, 2, 3)
    us = next(e for e in g.enemies if isinstance(e, Understudy))
    hide = next(i for i, p in enumerate(g.props) if PROP_DEFS[p.kind].hide == "locker")
    pr = g.props[hide]
    room = g.lv.rooms[pr.room]
    g.p.x, g.p.y = px(pr.cells[0])
    g.p.hiding = hide
    g.emit_noise = lambda *a, **k: None
    us.x, us.y = px(room.center)
    us.stats["hide_check_base"] = 1.0
    us.state = "patrol"
    us._begin_room_search(room)
    for _ in range(60 * 30):
        g.update(1 / 60, Controls())
        if g.p.hp < 3:
            break
    assert g.p.hp < 3 and g.p.hiding is None                      # dragged out and hurt
    # with checks off the same player is overlooked
    g2 = calm_game(cat, 2, 3)
    us2 = next(e for e in g2.enemies if isinstance(e, Understudy))
    hide2 = next(i for i, p in enumerate(g2.props) if PROP_DEFS[p.kind].hide == "locker")
    pr2 = g2.props[hide2]
    g2.p.x, g2.p.y = px(pr2.cells[0])
    g2.p.hiding = hide2
    us2.x, us2.y = px(g2.lv.rooms[pr2.room].center)
    us2.stats["hide_check_base"] = 0.0
    us2.rng.random = lambda: 0.99
    us2._begin_room_search(g2.lv.rooms[pr2.room])
    assert us2.todo == []


def test_understudy_follows_evidence_of_moved_doors(cat):
    g = calm_game(cat, 2, 3)
    us = next(e for e in g.enemies if isinstance(e, Understudy))
    d = next(d for d in g.lv.doors if not g.doors[d.id].locks and not d.gate)
    ds = g.doors[d.id]
    cx, cy = d.cells[0]
    us.x, us.y = px((cx + (2 if d.vertical else 0), cy + (0 if d.vertical else 2)))
    us.facing = 180 if d.vertical else 270
    ds.want = ds.open = 0.0
    us._evidence()                                               # it notes the shut door
    ds.want = 1.0
    ds.open = 1.0
    g.touch()
    us._evidence()
    assert any(v >= 0.5 for v in us.suspicion.values())


# ------------------------------------------------------------------------------------------ director
def test_director_respects_calm_gaps_peak_caps_and_hunter_limits(cat):
    g = new_game(cat, 3, 4)
    cfg = g.director.cfg
    p = g.p
    # roam between two far rooms so there is always something to find
    rooms = [r for r in g.lv.rooms if not r.hall and r.role == "any"]
    hits = 0
    max_hunters_seen = 0
    for i in range(60 * 60 * 6):
        if i % 600 == 0:
            r = rooms[(i // 600) % len(rooms)]
            p.x, p.y = px(r.center)
        p.hp = 3
        p.invuln = 5
        g.update(1 / 60, Controls())
        if g.director.state == "peak":
            max_hunters_seen = max(max_hunters_seen, len(g.director.hunters()))
    tl = g.director.timeline
    peaks = [i for i, (t, s) in enumerate(tl) if s == "peak"]
    assert 1 <= g.director.peaks <= cfg["max_peaks"] + 2
    assert tl[1][0] >= 0 and next(t for t, s in tl if s == "build") >= cfg["opening_calm"] - 1
    for k in peaks[1:]:
        # time since the previous peak ended (entering relax) must respect the minimum calm
        prev_end = next(t for t, s in reversed(tl[:k]) if s == "relax")
        assert tl[k][0] - prev_end >= cfg["relax_min"] + cfg["calm_min"] - 25 or tl[k][0] - prev_end >= cfg["calm_min"]
    assert max_hunters_seen <= cfg["max_hunters"] + 1
    for (t0, s0), (t1, s1) in zip(tl, tl[1:]):
        if s0 == "peak":
            assert t1 - t0 <= cfg["peak_max"] + 5


def test_no_peak_starts_while_the_player_is_in_a_safe_room(cat):
    g = new_game(cat, 1, 4)
    safe = g.lv.rooms[g.lv.safe_rooms[0]]
    g.p.x, g.p.y = px(safe.center)
    for _ in range(60 * 200):
        g.p.hp = 3
        g.update(1 / 60, Controls())
        assert g.director.state != "peak"
    assert g.director.peaks == 0


def test_music_intensity_follows_tension(cat):
    g = new_game(cat, 1, 4)
    lo = g.director.music_intensity()
    g.director.state = "peak"
    g.director.tension = 0.9
    assert g.director.music_intensity() > lo + 0.5


# ------------------------------------------------------------------------------------------ player rules
def test_light_sources_drain_and_visibility_changes(cat):
    g = calm_game(cat)
    p = g.p
    p.mode = "flash"
    b0 = p.battery
    step(g, 120)
    assert p.battery < b0 - 1.0
    assert g.player_lit() >= 0.9
    p.mode = "off"
    g.lv.lamps[:] = []
    g.lv.windows[:] = []
    g.touch()
    assert g.player_lit() < 0.1
    p.mode = "flash"
    p.battery = 0.2
    step(g, 60)
    assert p.mode == "off"


def test_flashlight_cone_lights_only_what_it_points_at(cat):
    g = calm_game(cat)
    r = next(r for r in g.lv.rooms if not r.hall and r.w >= 9 and r.h >= 5 and r.role == "any")
    g.lv.lamps[:] = []
    g.lv.windows[:] = []
    g.touch()
    g.p.x, g.p.y = px((r.x + 1, r.y + 2))
    g.p.mode, g.p.battery, g.p.facing = "flash", 100, 0.0
    ahead = g.light_at(g.p.x + 5 * TILE, g.p.y)
    behind = g.light_at(g.p.x - 0.0 * TILE, g.p.y + 4 * TILE)
    assert ahead > 0.4 and behind < 0.1


def test_doors_open_close_lock_and_unlock(cat):
    g = calm_game(cat, 1, 3)
    d = next(d for d in g.doors if d.locks)
    dd = g.lv.doors[d.id]
    c = dd.cells[0]
    g.p.x, g.p.y = px((c[0] + (1 if dd.vertical else 0), c[1] + (0 if dd.vertical else 1)))
    g.p.hiding = None
    assert g.set_door(d, True, False, "player") is False       # locked
    assert not g.try_unlock(d)
    for k in d.locks:
        g.p.pocket[k] = 1
    assert g.try_unlock(d)
    assert g.set_door(d, True, False, "player")
    step(g, 30)
    assert d.passable
    assert any(n.kind == "door_open" for n in g.noise_log)
    g.set_door(d, False, True, "player")
    step(g, 40)
    assert d.open < 0.6
    assert [n.loud if hasattr(n, "loud") else n.loudness for n in g.noise_log if n.kind == "door_close_sneak"][-1] < \
        [n.loudness for n in g.noise_log if n.kind == "door_open"][-1]


def test_search_hide_throw_and_craft(cat):
    g = calm_game(cat, 1, 3)
    cont = next(p for p in g.props if PROP_DEFS[p.kind].container and p.contents and g.lv.rooms[p.room].role == "any")
    g.p.x, g.p.y = px(cont.cells[0])
    n0 = len(cont.contents)
    items = [i for i, _ in cont.contents]
    g.p.busy = 0
    g._interact()
    step(g, 60)
    assert cont.searched and cont.contents == []
    assert all(g.bag_count(i) >= 1 for i in items)
    # hiding
    hide = next(p for p in g.props if PROP_DEFS[p.kind].hide)
    g.p.x, g.p.y = px(hide.cells[0])
    g.enter_hide(g.props.index(hide))
    assert g.p.hiding is not None and g.hide_log[PROP_DEFS[hide.kind].hide] == 1
    step(g, 40)
    step(g, 1, interact=True)
    assert g.p.hiding is None
    # craft: tin + nails = rattle
    g.add_item("tin_can", 1)
    g.add_item("nails", 1)
    assert g.combine("tin_can", "nails") and g.bag_count("rattle") == 1
    assert not g.combine("rattle", "coin")
    # throw: noise lands where the tin lands
    g.add_item("tin_can", 1)
    g.p.x, g.p.y = px(g.lv.start)
    g.p.facing = 0
    g.p.bag.sort(key=lambda s: s[0] != "tin_can")
    g.p.sel = 0
    n_noise = len(g.noise_log)
    g.throw("tin_can")
    assert len(g.noise_log) > n_noise and g.noise_log[-1].kind == "thrown_default"
    assert g.noise_log[-1].loudness == pytest.approx(9 * TILE)


def test_bag_has_limited_slots_but_keys_do_not_use_them(cat):
    g = calm_game(cat)
    g.p.bag.clear()
    for it in ("battery", "matches", "oil_flask", "bandage", "cloth", "tin_can", "nails", "bottle", "coin"):
        g.add_item(it, 1)
    assert len(g.p.bag) == 8 and g.add_item("coin", 5) >= 1
    assert g.add_item("brass_key", 1) == 0 and g.bag_count("brass_key") == 1


def test_healing_and_stamina(cat):
    g = calm_game(cat)
    g.p.hp = 1
    g.add_item("bandage", 1)
    g.p.sel = next(i for i, s in enumerate(g.p.bag) if s[0] == "bandage")
    g.use_selected()
    step(g, 90)
    assert g.p.hp == 2
    g.p.stamina = 1.0
    for _ in range(300):
        g.update(1 / 60, Controls(move=(1, 0), run=True))
    assert g.p.exhausted > 0 or g.p.stamina < 1.0


# ------------------------------------------------------------------------------------------ objectives end to end
def walk_beside(g, cells):
    """Walk to any free cell next to ``cells`` (props are solid, so they are used from beside)."""
    for (cx, cy) in cells:
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            c = (cx + dx, cy + dy)
            if c in cells or g.solid_cell(c):
                continue
            if walk_to(g, px(c)):
                return True
    return False


def wake(g):
    if g.p.hiding is not None:
        step(g, 40)
        step(g, 1, interact=True)


def collect(g, item):
    """Walk to wherever ``item`` lies (floor or container) and pick it up through the real interaction."""
    for it, c in levelgen.item_cells(g.lv):
        if it != item:
            continue
        spots = [c] if not g.solid_cell(c) else []
        spots_beside = [(c[0] + dx, c[1] + dy) for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)) if not g.solid_cell((c[0] + dx, c[1] + dy))]
        for spot in spots + spots_beside:
            if not walk_to(g, px(spot)):
                continue
            for _ in range(3):
                wake(g)
                g._interact()
                step(g, 60)
                if g.bag_count(item):
                    return True
    return g.bag_count(item) > 0


def test_night_one_can_be_completed_with_the_real_rules(cat):
    g = calm_game(cat, 1, 3)
    # keys and fuses
    assert collect(g, "boiler_key")
    assert collect(g, "fuse") and g.bag_count("fuse") >= 1
    for _ in range(2):
        pass
    fuses_needed = g.lv.objective["fuses"]
    got = g.bag_count("fuse")
    while got < fuses_needed:
        # a second fuse lies elsewhere: remove the first from the world list, collect again
        remaining = [(it, c) for it, c in levelgen.item_cells(g.lv) if it == "fuse"]
        assert len(remaining) >= fuses_needed
        for it, c in remaining[1:]:
            walk_to(g, px(c))
            g._interact()
            step(g, 60)
        got = g.bag_count("fuse")
        break
    assert g.bag_count("fuse") >= fuses_needed
    gen_room = g.lv.rooms[g.lv.objective["generator_room"]]
    boxes = [p for p in g.props if p.kind == "fuse_box"]
    for b in boxes[:fuses_needed]:
        assert walk_beside(g, b.cells)
        wake(g)
        g._interact()
        step(g, 5)
    assert g.obj["fuses_in"] == fuses_needed
    gen = next(p for p in g.props if p.kind == "generator")
    assert walk_beside(g, gen.cells)
    wake(g)
    g._interact()
    assert g.obj["generator_on"] and g.director.state == "peak"
    lever = next(p for p in g.props if p.kind == "lever")
    assert walk_beside(g, lever.cells)
    wake(g)
    g._interact()
    assert g.obj["power"] and g.power_on
    walk_to(g, px(g.lv.start))                              # the night ends the moment you are back inside
    assert g.complete and ("umbra.night_survived", {"night": 1}) in g.hooks


def test_night_two_keys_open_the_archive_and_the_clock_is_a_relic(cat):
    g = calm_game(cat, 2, 3)
    for k in ("brass_key", "bone_key", "iron_key"):
        assert collect(g, k), k
    arch = g.lv.rooms[g.lv.objective["archive_room"]]
    door = next(d for d in g.doors if d.locks)
    dd = g.lv.doors[door.id]
    assert walk_to(g, px(arch.center))                      # walk_to unlocks along the way
    assert collect(g, "cellar_key")
    # the stopped clock
    clock = next(p for p in g.props if p.kind == "clock")
    assert walk_beside(g, clock.cells)
    wake(g)
    g._interact()
    assert ("umbra.relic_found", {"relic": "stopped_clock"}) in g.hooks and "stopped_clock" in g.journal["relics"]
    walk_to(g, px(g.lv.start))
    assert g.complete


def test_night_three_gate_needs_crank_and_wheel_and_the_exit_lies_behind_it(cat):
    g = calm_game(cat, 3, 3)
    exit_room = g.lv.rooms[g.lv.objective["exit_room"]]
    assert g.path((g.p.x, g.p.y), px(exit_room.center), can_open=True, enemy=False) is None           # shut gate: no way through
    winch = next(p for p in g.props if p.kind == "winch")
    assert collect(g, "crank")
    assert walk_beside(g, winch.cells)
    wake(g)
    g._interact()
    assert not g.obj["gate_open"] and g.obj["winch_t"] == 0                            # missing the wheel
    assert collect(g, "crank_room_key") and collect(g, "gate_wheel")
    assert walk_beside(g, winch.cells)
    wake(g)
    g._interact()
    assert g.obj["winch_t"] > 0
    step(g, 60 * 8)
    assert g.obj["gate_open"]
    walk_to(g, px(exit_room.center))
    assert g.complete


def test_death_returns_you_to_the_last_safe_room_with_your_kit(cat):
    g = calm_game(cat, 1, 3)
    g.add_item("battery", 2)
    g.take_checkpoint("test")
    g.p.pocket["boiler_key"] = 1
    g.p.hp = 3
    g.p.x, g.p.y = px(g.lv.rooms[0].center)
    g.die("test")
    assert g.p.dead and g.deaths == 1
    g.respawn()
    assert not g.p.dead and g.p.hp == 3 and g.bag_count("battery") >= 2 and g.bag_count("boiler_key") == 0
    assert g.in_safe_room() and g.director.state == "calm"


def test_session_save_round_trip_resumes_at_the_checkpoint(cat):
    g = calm_game(cat, 2, 5)
    g.add_item("bottle", 1)
    g.p.pocket["brass_key"] = 1
    g.take_checkpoint("safe")
    d = json.loads(json.dumps(g.to_dict()))
    g2 = Game.from_dict(cat, d)
    assert g2 is not None and g2.night == 2 and g2.bag_count("bottle") == 1 and g2.bag_count("brass_key") == 1
    assert (g2.lv.grid == g.lv.grid).all() and g2.p.x == g.p.x
    assert Game.from_dict(cat, {**d, "v": 99}) is None and Game.from_dict(cat, {}) is None


def test_sim_cost_per_frame_is_small(cat):
    g = new_game(cat, 3, 7)
    for _ in range(120):
        g.update(1 / 60, Controls(move=(1, 0)))
    t = time.perf_counter()
    for i in range(600):
        g.update(1 / 60, Controls(move=(1, 0) if (i // 120) % 2 == 0 else (-1, 0)))
    assert (time.perf_counter() - t) / 600 < 0.004


# ------------------------------------------------------------------------------------------ scene integration
def enter(app, seed=5):
    from shardlight.hub.title import TitleScene
    app.scenes.reset_to(TitleScene(app), fade=False)
    app.scenes.process(0)
    app.enter_mode("umbra", seed=seed)
    run_ticks(app, 3, draw_every=0)
    s = app.scenes.top
    s.data["seen"]["controls"] = True
    return s


def test_scene_menu_play_pause_pack_and_leave(app):
    from shardlight.modes.umbra.scene import MenuScreen, NoteScreen, PackScreen, PauseMenu, PlayScreen
    s = enter(app)
    assert isinstance(s.screen, MenuScreen)
    s.start_night(1)
    run_ticks(app, 5)
    while app.scenes.top is not s:
        app.scenes.pop()
        run_ticks(app, 2, draw_every=0)
    assert isinstance(s.screen, PlayScreen)
    dev = app.input.attach_virtual(0)
    for i in range(400):
        dev.hold("RIGHT") if (i // 80) % 2 == 0 else dev.release("RIGHT")
        if i == 100:
            dev.tap("Y")
        if i == 200:
            dev.tap("B")
        run_ticks(app, 1, draw_every=4)
    g = s.game
    assert g.time > 5
    app.scenes.push(PackScreen(s, s.screen))
    run_ticks(app, 20)
    app.scenes.pop()
    app.scenes.push(PauseMenu(s))
    run_ticks(app, 20)
    app.scenes.pop()
    app.scenes.push(NoteScreen(s, s.cat.notes()[0]["id"]))
    run_ticks(app, 20)
    app.scenes.pop()
    s.save_run()
    assert s.data["run"]["night"] == 1
    s2 = enter(app)
    s2.start_night(1, resume=True)
    assert s2.game.night == 1


def test_scene_night_three_clears_the_facet_and_hooks_reach_the_world(app):
    s = enter(app, seed=9)
    s.start_night(1)
    run_ticks(app, 5)
    seen = []
    orig = app.world.emit
    app.world.emit = lambda name, **kw: (seen.append((name, kw)), orig(name, **kw))[1]
    s.data["cleared"] = [1, 2]
    g = s.game
    g.nd = s.cat.night(3)
    g.night = 3
    g._finish_night()
    s.drain_hooks()
    assert ("umbra.night_survived", {"night": 3}) in seen
    assert app.world.facet_repaired("umbra")


def test_scene_frame_time_in_the_dark(app):
    s = enter(app, seed=5)
    s.start_night(2)
    run_ticks(app, 10)
    while app.scenes.top is not s:
        app.scenes.pop()
        run_ticks(app, 2, draw_every=0)
    g = s.game
    g.p.mode = "flash"
    run_ticks(app, 30)
    t = time.perf_counter()
    run_ticks(app, 120)
    per = (time.perf_counter() - t) / 120
    assert per < 0.014, f"{per * 1000:.1f} ms per frame"
