"""Start a CPU-vs-CPU Masks match headlessly and save screenshots at given frames."""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene
from shardlight.modes.masks.cpu import CpuBrain

a_id, b_id, out = sys.argv[1], sys.argv[2], sys.argv[3]
frames = [int(x) for x in sys.argv[4].split(",")]
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("masks"); 
for _ in range(3): app.tick(TICK)
ms = app.scenes.top
ms.start_match("vscpu", (a_id, b_id), (None, 3))
fs = ms.screen
fs.cpu[0] = CpuBrain(3, 5, 1.0, 0)
fs._inputs_orig = fs._inputs
def both():
    return (fs.cpu[0].act(fs.match), fs.cpu[1].act(fs.match))
fs._inputs = both
for i in range(max(frames) + 1):
    app.tick(TICK); app.render()
    if i in frames:
        pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), out.replace(".png", f"_{i}.png"))
print("hp", [f.hp for f in fs.match.fighters], "wins", fs.match.wins, "phase", fs.match.phase)
