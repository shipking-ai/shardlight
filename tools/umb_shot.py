"""Headless Umbra screenshots.  python tools/umb_shot.py outprefix view   view: menu|dark|flash|lamp|map|hud"""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import math
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene

out = sys.argv[1]; view = sys.argv[2] if len(sys.argv) > 2 else "dark"
night = int(sys.argv[3]) if len(sys.argv) > 3 else 1
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("umbra", seed=5)
for _ in range(3): app.tick(TICK)
us = app.scenes.top
us.data["seen"]["controls"] = True
def run(n):
    for _ in range(n):
        app.tick(TICK); app.input.end_frame(); app.render()
def shot(name):
    pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), f"{out}_{name}.png")
run(20)
if view == "menu":
    shot("a")
else:
    us.start_night(night)
    run(10)
    if app.scenes.top is not us:
        app.scenes.pop()
    run(40)
    g = us.game
    if view == "dark":
        shot("a")
    elif view == "flash":
        g.p.mode = "flash"; g.p.facing = 0
        # move into the first room with some walls
        run(10); shot("a")
        g.p.facing = 90; run(10); shot("b")
    elif view == "lamp":
        g.p.mode = "lamp"; run(10); shot("a")
    elif view == "map":
        # a debug map of the whole level
        lv = g.lv
        surf = pygame.Surface((lv.w * 12, lv.h * 12))
        from shardlight.modes.umbra.view import View
        v = View(g)
        surf.blit(v.static, (0, 0))
        v._draw_dynamic(surf, 0, 0)
        for r in lv.rooms:
            col = (255, 255, 255)
            pygame.draw.rect(surf, (255, 80, 80) if r.role == "safe" else (90, 255, 120) if r.role not in ("any", "hall") else (80, 80, 255), (r.x * 12, r.y * 12, r.w * 12, r.h * 12), 1)
        pygame.image.save(surf, f"{out}_map.png")
    elif view == "hud":
        g.p.mode = "lamp"; g.add_item("battery", 2); g.add_item("tin_can", 2); g.add_item("bandage", 1)
        for e in g.events: pass
        run(20); shot("a")
print("ok", g.night if view != "menu" else "")
