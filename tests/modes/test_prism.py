"""Tests for the Grand Tour prism mode."""
import pytest

from conftest import run_ticks


@pytest.fixture
def game(app):
    app.app = app
    return app


def test_tourroot_walks_legs_in_order(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    assert tr.leg_index == 0
    tr.leg.debug_force_win()
    tr.update(1 / 60)
    assert tr.leg_index == 1
    assert "spire" in game.app.world.profile["tour"]["done_legs"]


def test_tourroot_failure_keeps_leg_index(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    tr.leg.state = "lost"
    tr.update(1 / 60)
    assert tr.state == "retry" and tr.leg_index == 0


def test_tourroot_retry_resets_only_failing_leg(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    tr.leg.state = "lost"
    tr.update(1 / 60)
    tr._retry()
    assert tr.state == "run" and tr.leg.id == "spire"


def test_tourroot_resumes_banked_leg(game):
    game.app.world.profile["tour"] = {"leg": 3, "done_legs": ["spire", "wisp", "crossing"], "done": False}
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    assert tr.leg.id == "lap"


def test_epilogue_writes_done_flag(game):
    from shardlight.modes.prism.epilogue import EpilogueScene
    e = EpilogueScene(game.app)
    e.debug_skip()
    assert game.app.world.profile["tour"]["done"] is True

def test_perspective_divide_invariant():
    from shardlight.modes.prism.tri import project_point
    p = project_point((0, 0, 5), yaw=0, pitch=0, cam=(0, 0, 0), fov=60, w=480, h=270)
    assert abs(p[0] - 240) < 1e-6 and abs(p[1] - 135) < 1e-6


def test_z_sort_back_to_front():
    from shardlight.modes.prism.tri import sort_polys
    polys = [{"z": 1.0}, {"z": 5.0}, {"z": 3.0}]
    out = sort_polys(polys)
    assert [p["z"] for p in out] == [5.0, 3.0, 1.0]


def test_fog_extremes():
    from shardlight.modes.prism.tri import fog_blend
    assert fog_blend(0.0, (10, 10, 10), (200, 200, 200)) == (10, 10, 10)
    c = fog_blend(1.0, (10, 10, 10), (200, 200, 200))
    assert c == (200, 200, 200)


def test_poly_budget_under_limit():
    from shardlight.modes.prism.tri import HallMesh
    m = HallMesh(debris=40)
    assert m.poly_count() <= 2500
