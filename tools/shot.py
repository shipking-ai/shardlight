"""Render a scene headlessly and save a PNG (scaled 2x).  Usage: python tools/shot.py title|hub|<mode> out.png [frames]"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="shardlight_shot_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene


def main() -> None:
    what, out = sys.argv[1], sys.argv[2]
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    app = App(headless=True, seed=7, audio=False)
    app.new_game(0, "Wren")
    if what == "title":
        app.scenes.reset_to(TitleScene(app), fade=False)
    elif what == "hub":
        app.return_to_hub()
    else:
        app.scenes.reset_to(TitleScene(app), fade=False)
        app.scenes.process(0)
        if not app.enter_mode(what):
            raise SystemExit(f"mode {what} unavailable")
    for _ in range(frames):
        app.tick(TICK)
        app.render()
    big = pygame.transform.scale(app.frame, (960, 540))
    pygame.image.save(big, out)


main()
