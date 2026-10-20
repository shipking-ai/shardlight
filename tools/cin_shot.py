"""Headless Cinder screenshots with a simple bot.  python tools/cin_shot.py out.png frames [weapon] [floor] [kind]"""
import math, os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene
from shardlight.modes.cinder import scene as S
from shardlight.modes.cinder.sim.player import Intent

out = sys.argv[1]; frames = [int(x) for x in sys.argv[2].split(",")]
weapon = sys.argv[3] if len(sys.argv) > 3 else "ember_blade"
floor = int(sys.argv[4]) if len(sys.argv) > 4 else 1
kind = sys.argv[5] if len(sys.argv) > 5 else "arena"
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("cinder")
for _ in range(3): app.tick(TICK)
cs = app.scenes.top
cs.data["seen"].update({"intro": True, "tip_move": True})
cs.begin_run(weapon, [])
rs = cs.screen
if floor > 1 or kind != "start":
    rs.run.floor = floor
    rs.start_floor(floor)
    spec = next((r for r in rs.plan.rooms.values() if r.kind == kind), None)
    if spec: rs.enter_room(spec.id, list(spec.doors)[0])
def bot(app_, p, toggle):
    room = rs.room; pl = room.player; it = Intent()
    es = [e for e in room.enemies if e.alive and not e.untargetable]
    if es:
        e = min(es, key=lambda e: (e.x - pl.x) ** 2 + (e.y - pl.y) ** 2)
        dx, dy = e.x - pl.x, e.y - pl.y; d = math.hypot(dx, dy) or 1
        it.move = (dx / d, dy / d) if d > 28 else (0, 0)
        it.aim = (dx / d, dy / d)
        if d < 44: it.pressed = {"attack"}
        thr = room.nearest_threat(pl.x, pl.y)
        if thr and room.t % 40 == 0: it.pressed = {"dodge"}
    elif room.cleared:
        t = room.interact_target()
        if t: it.pressed = {"interact"}
        else:
            for pr in room.props:
                if pr.interactable:
                    dx, dy = pr.x - pl.x, pr.y - pl.y; d = math.hypot(dx, dy) or 1; it.move = (dx / d, dy / d)
    return it
S.make_intent = bot
for i in range(max(frames) + 1):
    app.tick(TICK); app.input.end_frame(); app.render()
    if i in frames:
        pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), out.replace(".png", f"_{i}.png"))
r = rs.room
print("room", r.spec.kind, "hp", round(r.player.hp), "kills", r.stats, "enemies", [(e.title, round(e.hp)) for e in r.enemies if e.alive][:6], "over", rs.over)
