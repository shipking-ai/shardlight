"""Shared fixtures: headless pygame, isolated user directory, fresh App per test."""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARDLIGHT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def app(home):
    from shardlight.core.app import App
    a = App(headless=True, seed=1234, audio=False)
    a.new_game(0, "Tester")
    yield a
    import pygame
    pygame.quit()


def run_ticks(app, n: int, draw_every: int = 1) -> None:
    from shardlight.core.app import TICK
    for i in range(n):
        app.tick(TICK)
        app.input.end_frame()          # the real main loop clears per-frame text/key buffers
        if draw_every and i % draw_every == 0:
            app.render()
