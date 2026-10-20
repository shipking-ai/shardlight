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
