"""Render one in-game screenshot per shard (real gameplay, scripted bot input) into docs/screens and a contact sheet.

    python tools/contact_sheet.py            # all shards
Used for the graphical inspection recorded in docs/STATUS.md.  Headless (dummy video driver)."""
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="shardlight_sheet_")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pygame

from perf import start_gameplay
from shardlight import modes as modes_pkg
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene

OUT = ROOT / "docs" / "screens"


def shoot(mode_id: str) -> pygame.Surface:
    app = App(headless=True, seed=5, audio=False)
    app.new_game(0, "Sheet")
    if mode_id == "hub":
        app.return_to_hub()
    else:
        app.scenes.reset_to(TitleScene(app), fade=False)
        app.scenes.process(0)
        app.enter_mode(mode_id, seed=7) if mode_id in ("verdant", "terrace", "orrery", "umbra") else app.enter_mode(mode_id)
        print(mode_id, start_gameplay(app, mode_id))
    dev = app.input.attach_virtual(0)
    rng = random.Random(3)
    for i in range(360):
        if i % 20 == 0:
            dev.release_all()
            dev.hold(*rng.sample(["UP", "DOWN", "LEFT", "RIGHT", "A", "X"], 2))
        app.tick(TICK)
        app.input.end_frame()
        app.render()
    return app.frame.copy()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ids = ["hub"] + modes_pkg.MODE_IDS
    shots = []
    for mid in ids:
        s = shoot(mid)
        pygame.image.save(s, str(OUT / f"{mid}.png"))
        shots.append(s)
    w, h = shots[0].get_size()
    cols = 3
    rows = (len(shots) + cols - 1) // cols
    sheet = pygame.Surface((cols * w // 2, rows * h // 2))
    for i, s in enumerate(shots):
        sheet.blit(pygame.transform.smoothscale(s, (w // 2, h // 2)), ((i % cols) * w // 2, (i // cols) * h // 2))
    pygame.image.save(sheet, str(OUT / "contact_sheet.png"))
    print("wrote", OUT / "contact_sheet.png")


if __name__ == "__main__":
    main()
