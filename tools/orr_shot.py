"""Headless Orrery screenshots.  python tools/orr_shot.py outprefix [view]   view: flight|map|station|decode|codex"""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene

out = sys.argv[1]; view = sys.argv[2] if len(sys.argv) > 2 else "flight"
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("orrery")
for _ in range(3): app.tick(TICK)
os_ = app.scenes.top
os_.data["seen"]["intro"] = True
os_.opt_seed = 42
os_.new_voyage()
def run(n):
    for _ in range(n):
        app.tick(TICK); app.input.end_frame(); app.render()
def shot(name):
    pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), f"{out}_{name}.png")
run(30)
fs = os_.flight
g = os_.game
if view == "flight":
    st = fs.sys.stations()
    run(5); shot("a")
    from shardlight.modes.orrery.flight import FlightControls
    fs.player.x, fs.player.y = 0, -600
    e = fs._make("raider", 200, -500)
    for i in range(240):
        c = FlightControls(thrust=0.6, turn=0.3, pulse=(i % 8 < 4)); fs.update(c); 
        if i % 4 == 0: app.tick(TICK); app.input.end_frame(); app.render()
    shot("b")
elif view == "map":
    os_.open_map(); run(5); shot("a")
    os_.screen.overlay = 3; g.listen(); run(3); shot("b")
elif view == "station":
    from shardlight.modes.orrery.screens import StationScreen
    b = fs.sys.stations()[0]
    os_.set_screen(StationScreen(os_, b))
    for tab in range(6):
        os_.screen.tab = tab; run(12); shot(f"t{tab}")
elif view == "decode":
    from shardlight.modes.orrery.screens import DecodeScreen
    os_.set_screen(DecodeScreen(os_, "choir")); run(12); shot("a")
    os_.set_screen(DecodeScreen(os_, "undertow")); run(12); shot("b")
elif view == "codex":
    from shardlight.modes.orrery.screens import CodexScreen
    app.scenes.push(CodexScreen(os_)); run(12); shot("a")
print("sid", g.sid, g.g.systems[g.sid].name, "seed", g.seed, "credits", g.credits)
