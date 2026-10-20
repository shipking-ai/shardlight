"""Headless Slipstream race screenshots: python tools/slip_shot.py out.png frames [players] [seed]"""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene

out = sys.argv[1]; frames = [int(x) for x in sys.argv[2].split(",")]
players = int(sys.argv[3]) if len(sys.argv) > 3 else 1
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 12
app = App(headless=True, seed=3, audio=False); app.new_game(0, "Wren")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("slipstream", seed=seed, players=players)
for _ in range(3): app.tick(TICK)
ss = app.scenes.top
ss.data["seen"]["race"] = True
from shardlight.modes.slipstream.scene import RaceScreen
ss.set_screen(RaceScreen(ss, "versus" if players == 2 else "race", ["kestrel", "mantis" if players == 2 else None]))
dev = app.input.attach_virtual(0)
dev2 = app.input.attach_virtual(1) if players == 2 else None
for i in range(max(frames) + 1):
    dev.hold("UP")
    if i % 90 < 40: dev.hold("RIGHT")
    else: dev.release("RIGHT")
    if dev2: dev2.hold("UP")
    app.tick(TICK); app.input.end_frame(); app.render()
    if i in frames:
        pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), out.replace(".png", f"_{i}.png"))
r = ss.screen.race
print([ (x.name, x.position, round(x.car.speed)) for x in r.racers])
