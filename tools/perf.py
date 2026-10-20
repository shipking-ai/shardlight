"""Measure update/draw cost per shard headlessly.  Usage: python tools/perf.py [mode ...] [--ticks 600]

Reports the average and p95 of (update + draw) per frame in milliseconds using a scripted bot that holds a
few movement/attack buttons.  Numbers are for this machine only and exclude window presentation.
"""
import argparse
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="shardlight_perf_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shardlight import modes as modes_pkg
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene


def start_gameplay(app, mode_id: str) -> str:
    """Leave the mode's menu and start real gameplay so the numbers measure the game, not the title screen."""
    for _ in range(10):
        app.tick(TICK)
    sc = app.scenes.top
    try:
        if mode_id == "cinder":
            sc.begin_run("ember_blade", [])
        elif mode_id == "verdant":
            sc.new_world()
        elif mode_id == "terrace":
            sc.new_world()
        elif mode_id == "concord":
            sc.new_campaign()
        elif mode_id == "orrery":
            sc.new_voyage()
        elif mode_id == "umbra":
            sc.start_night(1)
        elif mode_id == "masks":
            sc.start_match("versus", ("kagari", "ushi"))
        elif mode_id == "slipstream":
            from shardlight.modes.slipstream.scene import RaceScreen
            vid = app.content.ids("slipstream.vehicle")[0]
            sc.set_screen(RaceScreen(sc, "quick", [vid, None], None))
        else:
            return "menu"
        for _ in range(30):
            app.tick(TICK)
            app.input.end_frame()
        while app.scenes.top is not sc and app.scenes.top is not None and app.scenes.top.__class__.__name__ in ("TextOverlay", "BriefingScreen", "Dialogue"):
            app.scenes.pop()
            app.tick(TICK)
        return "gameplay"
    except Exception as exc:               # report instead of silently measuring a menu
        return f"menu ({exc!r})"


def measure(mode_id: str, ticks: int) -> dict:
    app = App(headless=True, seed=5, audio=False)
    app.new_game(0, "Perf")
    if mode_id == "hub":
        app.return_to_hub()
    else:
        app.scenes.reset_to(TitleScene(app), fade=False)
        app.scenes.process(0)
        if not app.enter_mode(mode_id):
            return {"mode": mode_id, "error": "unavailable"}
    started = start_gameplay(app, mode_id) if mode_id != "hub" else "hub"
    dev = app.input.attach_virtual(0)
    rng = random.Random(1)
    buttons = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y"]
    samples = []
    for i in range(ticks):
        if i % 15 == 0:
            dev.release_all()
            dev.hold(*rng.sample(buttons, 3))
        t0 = time.perf_counter()
        app.tick(TICK)
        app.input.end_frame()
        app.render()
        samples.append((time.perf_counter() - t0) * 1000)
    samples = samples[30:]
    samples.sort()
    return {"mode": mode_id, "scene": started, "avg_ms": round(statistics.fmean(samples), 2),
            "p95_ms": round(samples[int(len(samples) * 0.95)], 2), "max_ms": round(samples[-1], 2), "frames": len(samples)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("modes", nargs="*")
    ap.add_argument("--ticks", type=int, default=600)
    args = ap.parse_args()
    ids = args.modes or ["hub"] + [m for m in modes_pkg.MODE_IDS if modes_pkg.load(m)]
    for mid in ids:
        print(measure(mid, args.ticks))


if __name__ == "__main__":
    main()
