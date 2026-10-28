"""Generic smoke test applied to every mode that exists: enter, run with scripted input, leave."""
import pytest
from conftest import run_ticks

from shardlight import modes as modes_pkg


def _available():
    return [m for m in modes_pkg.MODE_IDS if modes_pkg.load(m) is not None]


# TODO(#17): the Cinder smoke run takes ~37 s; shorten or mark slow.
@pytest.mark.parametrize("mode_id", [pytest.param(m, marks=pytest.mark.slow) if m == "cinder" else m for m in modes_pkg.MODE_IDS])
def test_mode_enters_runs_and_leaves(app, mode_id):
    if mode_id not in _available():
        pytest.skip(f"{mode_id} not implemented")
    ok = app.enter_mode(mode_id)
    assert ok
    dev = app.input.attach_virtual(0)
    import random
    rng = random.Random(3)
    buttons = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "L", "R"]
    for i in range(120):
        if i % 20 == 0:
            dev.release_all()
            dev.hold(*rng.sample(buttons, 2))
        run_ticks(app, 1, draw_every=4)
    dev.release_all()
    top = app.scenes.top
    assert top is not None
    app.return_to_hub()
    run_ticks(app, 10)
    assert app.scenes.top.__class__.__name__ == "HubScene"
