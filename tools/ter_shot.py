"""Headless Terrace screenshots.  python tools/ter_shot.py outprefix view   view: menu|play|night|cave|pack|craft"""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene
from shardlight.modes.terrace.player import Intent

out = sys.argv[1]; view = sys.argv[2] if len(sys.argv) > 2 else "play"
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("terrace", seed=7)
for _ in range(3): app.tick(TICK)
ts = app.scenes.top
ts.data["seen"]["intro"] = True
def run(n):
    for _ in range(n):
        app.tick(TICK); app.input.end_frame(); app.render()
def shot(name):
    pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), f"{out}_{name}.png")
run(20)
if view == "menu":
    shot("a")
else:
    ts.new_world(); run(40)
    g = ts.game
    if view == "play":
        run(60); shot("a")
        for tile in range(3):
            pass
        g.world.clock = 0.2
        run(5); shot("b")
    elif view == "night":
        g.world.clock = 0.7; g.inv.add("torch", 10)
        run(60)
        pl = g.player
        g.world.set(int(pl.x // 8) + 3, int(pl.y // 8) - 2, 23)   # a torch
        run(30); shot("a")
    elif view == "cave":
        w = g.world; pl = g.player
        # teleport into a cave
        import numpy as np
        ys, xs = np.nonzero((w.grid.blocks[150:200] == 0) & (w.grid.blocks[151:201] == 3))
        y, x = ys[len(ys) // 2] + 150, xs[len(xs) // 2]
        pl.x, pl.y = x * 8 + 4, (y + 1) * 8
        run(90); shot("a")
    elif view in ("pack", "craft"):
        from shardlight.modes.terrace.scene import PackScreen
        g.inv.add("log", 20); g.inv.add("stone", 30); g.inv.add("coal", 5); g.inv.add("planks", 20)
        app.scenes.push(PackScreen(ts, ts.screen, tab=0 if view == "pack" else 1)); run(20); shot("a")
print("ok", g.world.day if view != "menu" else "")
