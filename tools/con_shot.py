"""Headless Concord screenshots.  python tools/con_shot.py outprefix view   view: menu|map|battle|ledger|diplo|research"""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene

out = sys.argv[1]; view = sys.argv[2] if len(sys.argv) > 2 else "map"
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("concord", seed=7, house="ostrel", size="medium")
for _ in range(3): app.tick(TICK)
cs = app.scenes.top
def run(n):
    for _ in range(n):
        app.tick(TICK); app.input.end_frame(); app.render()
def shot(name):
    pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), f"{out}_{name}.png")
run(20)
if view == "menu":
    shot("a")
else:
    cs.data["intro_done"] = True; cs.data["seen"]["battle_tip"] = True
    cs.new_campaign()
    run(20)
    ms = cs.screen
    c = cs.camp
    if view == "map":
        shot("a")
        a = ms.my_armies()[0]; ms.select_army(a)
        # pick a far province for a path preview
        far = max(c.map.provinces, key=lambda p: (p.col - c.map.provinces[a.pid].col) ** 2 + (p.row - c.map.provinces[a.pid].row) ** 2)
        ms.cur = far.id; ms._update_path(); run(5); shot("b")
        ms.overlay = 2; run(3); shot("c")
    elif view == "battle":
        from shardlight.modes.concord.campaign import BattleRequest
        from shardlight.modes.concord.ui_battle import BattleIntro, TacticalScreen
        from shardlight.core.rng import derive_seed
        h = c.player; others = [x for x in c.rules.house_ids() if x != h]
        a = c.armies_of(h)[0]; o = c.armies_of(others[0])[0]
        o.pid = a.pid
        req = BattleRequest(a.pid, a.id, [o.id], h, others[0], c.map.provinces[a.pid].terrain, 1, False, 5, 0)
        app.scenes.push(BattleIntro(cs, ms, req)); run(30); shot("a")
        app.scenes.pop(); app.scenes.push(TacticalScreen(cs, ms, req)); run(90); shot("b")
        ts = app.scenes.top
        u = ts.my_units()[0]; ts.select(u); run(3); shot("c")
    elif view == "ledger":
        from shardlight.modes.concord.ui_ledger import ResearchScreen, DiplomacyScreen, HousesScreen
        app.scenes.push(ResearchScreen(cs)); run(15); shot("a"); app.scenes.pop(); run(3)
        app.scenes.push(DiplomacyScreen(cs, ms)); run(15); shot("b"); app.scenes.pop(); run(3)
        app.scenes.push(HousesScreen(cs)); run(15); shot("c")
print("ok", c.turn if view != "menu" else "")
