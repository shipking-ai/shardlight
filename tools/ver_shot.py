"""Headless Verdant screenshots.  python tools/ver_shot.py outprefix view [seed]
view: menu | town | night | forest | interior | dungeon | boss | journal | map | dialogue | shop | combat"""
import os, sys, tempfile
from pathlib import Path
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SHARDLIGHT_HOME"] = tempfile.mkdtemp(prefix="sl_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import math
import pygame
from shardlight.core.app import App, TICK
from shardlight.hub.title import TitleScene

out = sys.argv[1]; view = sys.argv[2] if len(sys.argv) > 2 else "town"
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
app = App(headless=True, seed=3, audio=False); app.new_game(0, "T")
app.scenes.reset_to(TitleScene(app), fade=False); app.scenes.process(0)
app.enter_mode("verdant", seed=seed)
for _ in range(3): app.tick(TICK)
vs = app.scenes.top
def run(n):
    for _ in range(n):
        app.tick(TICK); app.input.end_frame(); app.render()
def shot(name):
    pygame.image.save(pygame.transform.scale(app.frame, (960, 540)), f"{out}_{name}.png")
run(20)
if view == "menu":
    shot("a"); print("ok"); sys.exit()
vs.new_world()
run(5)
while app.scenes.top is not vs: app.scenes.pop(); run(2)
run(40)
g = vs.game
def tp(x, y, area=None):
    if area and g.area != area: g.enter_area(area, (x, y))
    g.p.x, g.p.y = x, y; vs.screen.snap_camera()
def site(sid): 
    s = g.over.sites[sid]; return s.front
if view == "town":
    g.clock = 12.0
    x, y = g.over.spots["wickering.front"]; tp(x + 0.5, y + 0.5); run(30); shot("a")
elif view == "night":
    g.clock = 21.0
    x, y = g.over.spots["wickering.front"]; tp(x + 0.5, y + 0.5); g.give("taper", 5)
    for (lx, ly) in [(l["x"], l["y"]) for l in g.over.lamps][:10]: g.set_obj("overworld", lx, ly, 0) if False else None
    run(30); shot("a")
elif view == "forest":
    g.clock = 10.0
    x, y = site("hollow_roots"); tp(x + 0.5, y + 0.5); run(30); shot("a")
elif view == "interior":
    g.clock = 10.0
    x, y = g.over.spots["wickering.front"]; tp(x + 0.5, y + 0.5)
    g.enter_area("b:wickering.inn"); run(40); shot("a")
elif view == "dungeon":
    g.enter_area("d:cairn_of_debts"); run(60); shot("a")
elif view == "boss":
    g.enter_area("d:cairn_of_debts")
    bx, by = g.wm.spots["boss"]; tp(bx + 0.5, by + 4.5)
    for _ in range(3): run(30)
    shot("a")
elif view == "combat":
    from shardlight.modes.verdant import combat
    g.clock = 20.0
    x, y = g.over.spots["wickering.gate_w"]; tp(x + 4.5, y + 0.5)
    g.give("hunting_bow") if False else None
    for i, k in enumerate(("wolf", "wolf", "bandit", "bandit_archer", "bogwight")):
        e = combat.Enemy(g, k, g.p.x + 3 + i * 0.8, g.p.y + (i - 2) * 1.4, "t", i, 5); e.aggro = 9; g.enemies.append(e)
    e = combat.Enemy(g, "bandit", g.p.x - 3, g.p.y, "t", 0, 1); e.guard = True; e.aggro = 9; g.enemies.append(e)
    g.p.hp = 1e9; g.p.facing = 0
    g.hazards.append(combat.Hazard("circle", g.p.x + 2, g.p.y - 2, 1.9, 5.0, 5.0, 5, 0, area=g.area))
    for i in range(25): g.update(1/60, __import__("shardlight.modes.verdant.sim", fromlist=["Intent"]).Intent(attack=(i == 3)))
    run(2); shot("a")
elif view in ("dialogue", "shop", "journal", "map", "craft", "quests"):
    from shardlight.modes.verdant import npcs
    from shardlight.modes.verdant.screens import DialogueScreen, ShopScreen, JournalScreen, CraftScreen
    g.clock = 12.0; npcs.update(g, 0.0, teleport=True)
    g.give("iron_ore", 4); g.give("plank", 3); g.give("hide", 2); g.give("tonic", 2); g.give("flax", 6); g.give("hedge_berries", 2)
    g.give("iron_sword"); g.give("studded_coat"); g.give("hunting_bow"); g.give("arrow", 12); g.p.gold = 240
    for sid in list(g.over.sites)[:8]: g.known_sites.add(sid)
    g.discovered[:, :140] = True
    g.accept_quest("first_light")
    if view == "dialogue":
        g.enter_area("b:wickering.lamp_house"); st = g.npcs["marrow_pell"]; g.p.x, g.p.y = st.x + 1, st.y + 1.2
        run(3); app.scenes.push(DialogueScreen(vs, g, "marrow_pell")); run(8)
    elif view == "shop":
        g.enter_area("b:wickering.store"); app.scenes.push(ShopScreen(vs, g, "general")); run(12)
    elif view == "craft":
        app.scenes.push(CraftScreen(vs, g, "forge")); run(12)
    else:
        j = JournalScreen(vs, g); j.tab = {"journal": 0, "quests": 1, "map": 2}[view]; app.scenes.push(j); run(12)
    shot("a")
print("ok", g.area, g.time_text())
