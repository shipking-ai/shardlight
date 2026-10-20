import math

import pytest

from shardlight.core import ai, nav
from shardlight.core.rng import Rng, derive_seed

MAZE = [
    "##########",
    "#........#",
    "#.######.#",
    "#.#....#.#",
    "#.#.##.#.#",
    "#...##...#",
    "##########",
]


def test_astar_finds_shortest_and_none_when_blocked():
    g = nav.Grid.from_rows(MAZE)
    path = nav.astar(g, (1, 1), (4, 3), diagonal=False)
    assert path[0] == (1, 1) and path[-1] == (4, 3)
    assert all(g.walkable(*c) for c in path)
    assert all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(path, path[1:]))
    g.set_blocked(1, 2)
    g.set_blocked(1, 3)
    g.set_blocked(1, 4)
    g.set_blocked(1, 5)
    g.set_blocked(2, 5)
    g.set_blocked(3, 5)
    g.set_blocked(7, 1)
    g.set_blocked(8, 1)
    assert nav.astar(g, (1, 1), (4, 3)) is None


def test_diagonal_moves_do_not_cut_corners():
    g = nav.Grid.from_rows(["....", ".##.", "....", "...."])
    nb = {c for c, _ in g.neighbors((0, 0), True)}
    assert (1, 1) not in nb                           # blocked tile
    g2 = nav.Grid.from_rows([".#", "#."])
    assert list(g2.neighbors((0, 0), True)) == []     # squeezing between two walls is forbidden


def test_line_of_sight_and_smoothing():
    g = nav.Grid.from_rows(MAZE)
    assert nav.line_of_sight(g, (1, 1), (8, 1))
    assert not nav.line_of_sight(g, (1, 1), (4, 3))
    path = nav.astar(g, (1, 1), (8, 5), diagonal=False)
    sm = nav.smooth_path(g, path)
    assert len(sm) < len(path) and sm[0] == path[0] and sm[-1] == path[-1]


def test_flow_field_matches_astar_distance():
    g = nav.Grid.from_rows(MAZE)
    ff = nav.FlowField(g, [(8, 5)], diagonal=False)
    c = (1, 1)
    steps = 0
    while c != (8, 5):
        c = ff.next_step(c, diagonal=False)
        steps += 1
        assert steps < 100
    assert steps == len(nav.astar(g, (1, 1), (8, 5), diagonal=False)) - 1


def test_spatial_hash_query():
    sh = nav.SpatialHash(16)
    for i in range(100):
        sh.insert(i, i * 3.0, 0.0)
    near = sh.query(30.0, 0.0, 9.0)
    assert sorted(near) == [7, 8, 9, 10, 11, 12, 13]


def test_behaviour_tree_sequence_selector_cooldown():
    log = []
    seq = ai.Sequence(ai.Condition(lambda bb: bb["see"]), ai.Action(lambda bb: (log.append("shoot"), ai.Status.SUCCESS)[1]))
    root = ai.Selector(ai.Cooldown(seq, 1.0), ai.Action(lambda bb: (log.append("patrol"), ai.Status.SUCCESS)[1]))
    bb = {"see": True, "time": 0.0}
    root.tick(bb)
    bb["time"] = 0.5
    root.tick(bb)
    bb["time"] = 1.2
    root.tick(bb)
    bb["see"] = False
    bb["time"] = 5
    root.tick(bb)
    assert log == ["shoot", "patrol", "shoot", "patrol"]


def test_utility_selector_commitment_and_hysteresis():
    a = ai.UtilityOption("attack", lambda bb: bb["a"], commit=1.0)
    b = ai.UtilityOption("flee", lambda bb: bb["b"])
    u = ai.UtilitySelector([a, b])
    bb = {"time": 0.0, "a": 0.6, "b": 0.5}
    assert u.choose(bb) is a
    bb.update(time=0.5, a=0.1, b=0.9)
    assert u.choose(bb) is a                 # still committed
    bb["time"] = 1.5
    assert u.choose(bb) is b


def test_vision_cone_and_los():
    cone = ai.VisionCone(range=100, fov_deg=90, peripheral_range=10)
    assert cone.sees((0, 0), 0, (50, 0))
    assert not cone.sees((0, 0), 0, (-50, 0))                       # behind
    assert cone.sees((0, 0), 0, (-5, 0))                            # peripheral
    assert not cone.sees((0, 0), 0, (150, 0))
    assert not cone.sees((0, 0), 0, (50, 0), los=lambda a, b: False)
    assert not cone.sees((0, 0), 0, (80, 0), visibility=0.5)        # darkness shortens sight


def test_memory_decays_and_forgets():
    m = ai.Memory(decay_per_s=0.5)
    m.observe(ai.Evidence("seen", (3, 4), 0.0, 1.0))
    assert m.last_known() == (3, 4)
    m.update(1.0)
    assert 0.4 < m.confidence < 0.6
    m.update(2.0)
    assert m.last_known() is None


def test_noise_bus_range_and_occlusion():
    class Ear:
        pass

    heard = []
    bus = ai.NoiseBus(occlusion=lambda a, b: 100 if b[0] > 200 else 0)   # anything past x=200 is behind a wall
    near, far, behind_wall, deaf, keen = Ear(), Ear(), Ear(), Ear(), Ear()
    bus.listen(near, lambda: (50, 0), lambda n, i: heard.append("near"))
    bus.listen(far, lambda: (500, 0), lambda n, i: heard.append("far"))
    bus.listen(behind_wall, lambda: (250, 0), lambda n, i: heard.append("wall"))
    bus.listen(deaf, lambda: (100, 0), lambda n, i: heard.append("deaf"), hearing=0.2)
    bus.listen(keen, lambda: (250, 0), lambda n, i: heard.append("keen"), hearing=1.5)
    n = bus.emit(ai.Noise((0, 0), 300))
    assert sorted(heard) == ["keen", "near"]          # 250+100=350 > 300 muffled; keen ears reach 450
    assert n == 2
    heard.clear()
    bus.emit(ai.Noise((0, 0), 400))                    # louder noise carries through the wall
    assert "wall" in heard and "far" not in heard


def test_adaptation_bounded_cooled_and_scaled():
    model = ai.PlayerModel(half_life=30)
    group = ("dodge_left", "dodge_right")
    adapt = ai.Adaptation("lead_left", "dodge_left", group, threshold=0.6, min_weight=4, max_bonus=0.3)
    ctl = ai.AdaptiveController(model, [adapt], strength=1.0, cooldown=8.0)
    t = 0.0
    for i in range(12):                         # player dodges left a lot
        t += 0.5
        model.record("dodge_left", t)
        ctl.update(t, 0.5)
    for _ in range(40):
        t += 0.5
        ctl.update(t, 0.5)
    assert adapt.active and 0 < adapt.level <= adapt.max_bonus * 1.5
    # strength 0 disables adaptation entirely
    model2 = ai.PlayerModel()
    a2 = ai.Adaptation("x", "dodge_left", group, min_weight=1)
    c2 = ai.AdaptiveController(model2, [a2], strength=0.0)
    for i in range(30):
        model2.record("dodge_left", i * 0.5)
        c2.update(i * 0.5, 0.5)
    assert not a2.active and a2.level == 0
    # cooldown: cannot flip back immediately
    flips_before = len(ctl.log)
    for i in range(8):
        t += 0.25
        model.record("dodge_right", t, weight=5)
        ctl.update(t, 0.25)
    assert len(ctl.log) - flips_before <= 1


def test_rng_children_independent_and_deterministic():
    a, b = Rng(5), Rng(5)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    c1 = Rng(5).child("map")
    c2 = Rng(5).child("loot")
    assert c1.random() != c2.random()
    assert derive_seed(1, "a", 2) == derive_seed(1, "a", 2) != derive_seed(1, "a", 3)
