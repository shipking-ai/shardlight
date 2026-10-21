"""Tests for the Grand Tour's legs: they must respond to input and never trap the player."""
import pytest

from conftest import run_ticks

LEGS = ["spire", "wisp", "crossing", "lap", "duel", "bloom", "market", "swarm"]


@pytest.fixture
def game(app):
    app.app = app
    return app


def _leg_classes():
    from shardlight.modes.prism import legs as L

    return {
        "spire": L.SpireLeg,
        "wisp": L.WispLeg,
        "crossing": L.ShadowLeg,
        "lap": L.LapLeg,
        "duel": L.DuelLeg,
        "bloom": L.BloomLeg,
        "market": L.MarketLeg,
        "swarm": L.SwarmLeg,
    }


def frames(app, leg, n: int) -> None:
    """Drive a leg the way the game does: refresh the input state, then update."""
    for _ in range(n):
        app.input.begin_tick()
        leg.update(1 / 60)
        app.input.end_frame()


def test_every_leg_responds_to_input(game):
    """No leg may sit there doing nothing: holding or tapping must change its state."""
    dev = game.app.input.attach_virtual(0)
    for name, cls in _leg_classes().items():
        leg = cls(game.app, 7, {})

        def snapshot(lg):
            return (lg.progress, getattr(lg, "hits", 0), getattr(lg, "misses", 0),
                    getattr(lg, "blooms", 0), getattr(lg, "turn", 0), getattr(lg, "ledger", 0))

        before = snapshot(leg)
        dev.hold("CONFIRM")
        frames(game.app, leg, 60)
        dev.tap("CONFIRM")
        frames(game.app, leg, 2)
        dev.release_all()
        assert snapshot(leg) != before, f"{name} ignored the input"
        assert leg.state in ("run", "won", "lost")


def test_holding_the_lamp_wins_the_simple_legs(game):
    dev = game.app.input.attach_virtual(0)
    for name in ("spire", "wisp", "lap"):
        cls = _leg_classes()[name]
        leg = cls(game.app, 3, {})
        dev.hold("CONFIRM")
        frames(game.app, leg, 3600)
        dev.release_all()
        assert leg.state == "won", f"{name} should be winnable by holding"


def test_duel_leg_is_won_by_timing_the_tap(game):
    cls = _leg_classes()["duel"]
    leg = cls(game.app, 5, {})
    dev = game.app.input.attach_virtual(0)
    lo, hi = cls.BAND
    for _ in range(3):
        while not (lo <= leg.mark <= hi):      # step the sweep into the band
            game.app.input.begin_tick()
            leg.update(1 / 60)
            game.app.input.end_frame()
        dev.tap("CONFIRM")
        frames(game.app, leg, 1)
    assert leg.hits == 3
    assert leg.state == "won"


def test_bloom_leg_is_won_by_timing_the_tap(game):
    cls = _leg_classes()["bloom"]
    leg = cls(game.app, 5, {})
    dev = game.app.input.attach_virtual(0)
    lo, hi = cls.WINDOW
    for _ in range(2):
        while not (lo <= leg.meter <= hi):
            game.app.input.begin_tick()
            leg.update(1 / 60)
            game.app.input.end_frame()
        dev.tap("CONFIRM")
        frames(game.app, leg, 1)
    assert leg.blooms == 2
    assert leg.state == "won"


def test_market_leg_is_won_by_trading(game):
    cls = _leg_classes()["market"]
    leg = cls(game.app, 5, {})
    dev = game.app.input.attach_virtual(0)
    for _ in range(8):
        dev.tap("CONFIRM")
        frames(game.app, leg, 1)
        if leg.state != "run":
            break
    assert leg.state == "won"
    assert leg.ledger >= leg.goal


def test_swarm_leg_can_be_survived(game):
    cls = _leg_classes()["swarm"]
    leg = cls(game.app, 5, {})
    dev = game.app.input.attach_virtual(0)
    dev.hold("CONFIRM")
    frames(game.app, leg, 60 * 20)
    dev.release_all()
    assert leg.state == "won"


def test_back_leaves_the_tour(game):
    """The escape hatch: a leg can never trap the player."""
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    game.app.scenes.push(tr)
    dev = game.app.input.attach_virtual(0)
    dev.tap("B")
    run_ticks(game.app, 3)
    assert not any(isinstance(s, TourRoot) for s in game.app.scenes.stack)


def test_leg_counter_is_shown(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    assert tr.leg.leg_number == 1
    assert tr.leg.legs_total == 8
