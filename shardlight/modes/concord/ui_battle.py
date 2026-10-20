"""Tactical battle screens: the pre-battle briefing and the grid battle itself."""
from __future__ import annotations

import math
import random

import pygame

from ...core.fx import FEEL, FloatingTexts, ParticleSystem, clamp, mix
from ...core.scene import Scene
from ...core.ui import BRASS, DANGER, DIM, GOOD, INK_2, LENS, PARCHMENT, Menu, MenuItem, MenuScene, SettingsScene, ControlsScene, draw_panel, draw_prompts
from . import art
from . import battle as B

W, H = 480, 270
T = 28
GX, GY = 8, 26
PANEL = (40, 34, 56)


def hcol(camp, hid: str):
    return tuple(camp.rules.houses[hid]["color"])


# ====================================================================================== briefing
class BattleIntro(Scene):
    def __init__(self, cs, ms, req):
        super().__init__(cs.app)
        self.cs, self.ms, self.req, self.c = cs, ms, req, cs.camp
        self.t = 0
        self.bg = art.parchment((W, H), 21)
        c = self.c
        self.att = c.armies[req.attacker]
        self.defs = [c.armies[i] for i in req.defenders if i in c.armies]
        mine = req.player_side
        items = [MenuItem("Command the battle", self._fight, hint="You issue every order. The enemy answers by the same rules."),
                 MenuItem("Auto-resolve", self._auto, hint="Both sides fight on their own; usually worse than commanding well.")]
        self.menu = Menu(self.app, items, 260)
        self.app.audio.play("concord_horn", 0.8)

    def on_enter(self, **kw) -> None:
        self.app.audio.set_intensity(0.9)

    def _fight(self) -> None:
        self.app.scenes.pop()
        self.app.scenes.push(TacticalScreen(self.cs, self.ms, self.req))

    def _auto(self) -> None:
        res = self.c.auto_battle(self.req)
        self.app.scenes.pop()
        self.app.scenes.push(ResultScreen(self.cs, self.ms, self.req, res))

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 14:
            self.menu.update()

    def draw(self, surf: pygame.Surface) -> None:
        c, f, req = self.c, self.app.font, self.req
        surf.blit(self.bg, (0, 0))
        p = c.map.provinces[req.pid]
        f.draw(surf, "BATTLE", (W // 2, 10), art.WAX, None, anchor="midtop", scale=4)
        f.draw(surf, f"{p.name}  -  {p.terrain}" + (f"  -  fortified (level {req.fort})" if req.fort else "") + ("  -  river crossing" if req.river else ""),
               (W // 2, 42), art.INK, None, anchor="midtop")
        for side, (x, armies, hid) in enumerate(((20, [self.att], req.att_house), (252, self.defs, req.def_house))):
            r = pygame.Rect(x, 62, 208, 100)
            draw_panel(surf, r, fill=PANEL, alpha=246, border=hcol(c, hid))
            surf.blit(art.crest(hcol(c, hid), 14), (r.x + 8, r.y + 7))
            f.draw(surf, c.rules.houses[hid]["name"], (r.x + 28, r.y + 7), PARCHMENT, None)
            f.draw(surf, "Attacking" if side == 0 else "Defending", (r.x + 28, r.y + 17), DIM, None)
            units = [u for a in armies for u in a.units][:8]
            for i, u in enumerate(units):
                role = c.rules.units[u.type]["role"]
                spr = art.unit_figure(role, hcol(c, hid), 20, flip=side == 1)
                surf.blit(spr, (r.x + 8 + (i % 4) * 48, r.y + 34 + (i // 4) * 32))
                f.draw(surf, art.ROLE_GLYPH[role], (r.x + 31 + (i % 4) * 48, r.y + 34 + (i // 4) * 32), DIM, None)
            f.draw(surf, f"{sum(len(a.units) for a in armies)} units  strength {sum(c.army_strength(a) for a in armies):.0f}", (r.x + 8, r.bottom - 12), PARCHMENT, None)
        if req.player_side is not None:
            side = "attack" if req.player_side == 0 else "defend"
            f.draw(surf, f"You {side} here.", (W // 2, 170), art.WAX, None, anchor="midtop")
        draw_panel(surf, pygame.Rect(110, 184, 260, 56), fill=PANEL, alpha=246)
        self.menu.draw(surf, (116, 188))
        draw_prompts(surf, self.app, [("CONFIRM", "Choose")], y=H - 14)


# ====================================================================================== tactical battle
class TacticalScreen(Scene):
    def __init__(self, cs, ms, req):
        super().__init__(cs.app)
        self.cs, self.ms, self.req, self.c = cs, ms, req, cs.camp
        self.b = cs.camp.build_battle(req)
        self.side = req.player_side if req.player_side is not None else 0
        pers = self.c.rules.houses[req.def_house if self.side == 0 else req.att_house]["personality"]
        self.ai = B.BattleAI(self.b, 1 - self.side, pers["aggression"], pers["caution"], self.b.rng.child("ui_ai"))
        self.cols = {0: hcol(self.c, req.att_house), 1: hcol(self.c, req.def_house)}
        self.cursor = [0, B.GRID_H // 2]
        self.sel: B.BUnit | None = None
        self.mode = "move"
        self.t = 0
        self.vis: dict[int, list[float]] = {u.id: [float(u.x), float(u.y)] for u in self.b.units}
        self.flash: dict[int, int] = {}
        self.dying: dict[int, int] = {}
        self.lunge: dict[int, tuple[float, float, int]] = {}
        self.floats = FloatingTexts()
        self.parts = ParticleSystem(300, random.Random(4))
        self.ai_list: list[B.BUnit] = []
        self.ai_wait = 0
        self.phase_banner = 70
        self.msg = ""
        self.msg_t = 0
        self.confirm_end = False
        self.shake = 0.0
        self.done = False
        self.bg = art.parchment((W, H), 8)
        self.hp_always = True
        self._last_phase = -1
        self._reach: dict = {}
        self._targets: list = []

    def on_enter(self, **kw) -> None:
        self.app.audio.set_intensity(1.0)
        seen = self.cs.data["seen"]
        if not seen.get("battle_tip"):
            seen["battle_tip"] = True
            self.app.scenes.push(_Tip(self.app))

    # ------------------------------------------------------------------ helpers
    def say(self, text: str, good: bool = True) -> None:
        self.msg, self.msg_t = text, 160
        if not good:
            self.app.audio.play("ui_error", 0.5)

    def my_units(self) -> list[B.BUnit]:
        return self.b.side_units(self.side)

    def player_phase(self) -> bool:
        return self.b.phase == self.side and not self.b.over

    def center(self, x: float, y: float) -> tuple[float, float]:
        return GX + x * T + T / 2, GY + y * T + T / 2

    def refresh(self) -> None:
        u = self.sel
        self._reach, self._targets = {}, []
        if u is None or not u.active:
            return
        self._reach = self.b.reachable(u)
        if self.mode == "ability":
            self._targets = self.b.ability_targets(u)
        else:
            self._targets = [e for e in self.b.targets(u)] + [("wall", w) for w in self.b.wall_targets(u)]

    def select(self, u: B.BUnit | None) -> None:
        self.sel = u
        self.mode = "move"
        if u:
            self.cursor = [u.x, u.y]
            self.app.audio.play("ui_move", 0.4)
        self.refresh()

    # ------------------------------------------------------------------ events -> feedback
    def process_events(self) -> None:
        b = self.b
        for e in b.drain():
            if e.kind == "move":
                pass
            elif e.kind == "attack":
                a, t = b.unit(e.a), b.unit(e.b)
                dx, dy = t.x - a.x, t.y - a.y
                n = math.hypot(dx, dy) or 1
                self.lunge[a.id] = (dx / n, dy / n, 8)
                self.app.audio.play("concord_clash", 0.6, pan=clamp((a.x - 5) / 6, -1, 1))
            elif e.kind == "hit":
                t = b.unit(e.b)
                cx, cy = self.center(t.x, t.y)
                self.flash[t.id] = 6
                col = (255, 120, 90) if e.text != "flank" else (255, 214, 120)
                self.floats.add(f"{e.amount:.0f}" + ("!" if e.text == "flank" else ""), (cx, cy - 12), col, 0.9)
                self.parts.emit((cx, cy), 6, (30, 90), (0, 360), (0.15, 0.4), (1, 2), (255, 200, 140), (150, 40, 30), drag=3)
                self.shake = min(3.0, self.shake + 1.2)
            elif e.kind == "death":
                t = b.unit(e.b)
                self.dying[t.id] = 24
                cx, cy = self.center(t.x, t.y)
                self.parts.emit((cx, cy), 14, (20, 90), (0, 360), (0.3, 0.8), (1, 3), (255, 230, 200), (110, 80, 70), drag=2)
                self.app.audio.play("concord_bell", 0.3)
            elif e.kind == "rout":
                u = b.unit(e.a)
                self.dying[u.id] = 30
                cx, cy = self.center(u.x, u.y)
                self.floats.add("ROUT", (cx, cy - 12), (255, 214, 120), 1.0)
            elif e.kind in ("heal", "buff", "rally", "purge"):
                u = b.unit(e.a)
                cx, cy = self.center(e.x, e.y)
                col = {"heal": (130, 230, 150), "buff": (130, 214, 255), "rally": (255, 214, 120), "purge": (230, 180, 255)}[e.kind]
                self.parts.emit((cx, cy), 10, (10, 50), (0, 360), (0.4, 0.8), (1, 2), col, col, drag=2)
                if e.kind == "heal":
                    self.floats.add(f"+{e.amount:.0f}", (cx, cy - 12), (130, 230, 150), 0.9)
                self.app.audio.play("concord_quill", 0.4)
            elif e.kind == "wall_hit":
                cx, cy = self.center(e.x, e.y)
                self.parts.emit((cx, cy), 8, (20, 80), (0, 360), (0.2, 0.5), (1, 2), (200, 190, 170), (110, 100, 90), drag=3)
                self.app.audio.play("concord_clash", 0.7)
            elif e.kind == "wall_down":
                cx, cy = self.center(e.x, e.y)
                self.parts.emit((cx, cy), 24, (30, 120), (0, 360), (0.4, 0.9), (1, 3), (200, 190, 170), (110, 100, 90), drag=2)
                self.app.audio.play("concord_horn", 0.7)
                self.shake = 4.0

    # ------------------------------------------------------------------ input
    def update(self, dt: float) -> None:
        self.t += 1
        self.msg_t = max(0, self.msg_t - 1)
        self.phase_banner = max(0, self.phase_banner - 1)
        self.shake = max(0.0, self.shake - 0.4)
        self.floats.update(dt)
        self.parts.update(dt)
        for k in list(self.flash):
            self.flash[k] -= 1
            if self.flash[k] <= 0:
                del self.flash[k]
        for k in list(self.dying):
            self.dying[k] -= 1
        for k in list(self.lunge):
            dx, dy, n = self.lunge[k]
            if n <= 1:
                del self.lunge[k]
            else:
                self.lunge[k] = (dx, dy, n - 1)
        b = self.b
        for u in b.units:
            v = self.vis[u.id]
            v[0] += (u.x - v[0]) * 0.35
            v[1] += (u.y - v[1]) * 0.35
        if b.phase != self._last_phase and not b.over:
            self._last_phase = b.phase
            self.phase_banner = 60
            self.confirm_end = False
            if b.phase == self.side:
                self.sel = None
                self._reach, self._targets = {}, []
                nxt = next((u for u in self.my_units() if not u.done), None)
                if nxt:
                    self.cursor = [nxt.x, nxt.y]
            else:
                self.ai_list = self.ai.phase_order()
                self.ai_wait = 40
        if b.over:
            if not self.done:
                self.done = True
                self.finish_after = 50
            self.finish_after -= 1
            if self.finish_after <= 0:
                self.app.scenes.pop()
                self.app.scenes.push(ResultScreen(self.cs, self.ms, self.req, b.result))
            return
        if b.phase != self.side:
            self._ai_step()
            return
        self._player_input()

    def _ai_step(self) -> None:
        b = self.b
        if self.ai_wait > 0:
            self.ai_wait -= 1
            return
        while self.ai_list and not self.ai_list[0].active:
            self.ai_list.pop(0)
        if not self.ai_list:
            b.end_phase()
            self.process_events()
            return
        u = self.ai_list.pop(0)
        before = (u.x, u.y)
        self.ai.act(u)
        self.process_events()
        self.cursor = [u.x, u.y]
        self.ai_wait = 22 if (u.x, u.y) != before or u.acted else 6
        if b.check_over():
            self.ai_list = []

    def _tile_at_mouse(self):
        mx, my = self.inp.mouse_pos
        x, y = (mx - GX) // T, (my - GY) // T
        if 0 <= x < B.GRID_W and 0 <= y < B.GRID_H:
            return int(x), int(y)
        return None

    def _player_input(self) -> None:
        b, p = self.b, self.inp.player(0)
        dx, dy = p.menu_dir()
        if dx or dy:
            self.cursor[0] = max(0, min(B.GRID_W - 1, self.cursor[0] + dx))
            self.cursor[1] = max(0, min(B.GRID_H - 1, self.cursor[1] + dy))
            self.app.audio.play("ui_move", 0.25)
        tm = self._tile_at_mouse()
        click = 1 in self.inp.mouse_pressed and tm is not None
        if tm is not None and pygame.mouse.get_rel() != (0, 0):
            self.cursor = list(tm)
        if click:
            self.cursor = list(tm)
        if "A" in p.pressed or "CONFIRM" in p.pressed or click:
            self.press_a()
        if "B" in p.pressed or "BACK" in p.pressed or 3 in self.inp.mouse_pressed:
            if self.mode == "ability":
                self.mode = "move"
                self.refresh()
            else:
                self.select(None)
        if "X" in p.pressed:
            self.press_x()
        if "Y" in p.pressed and self.sel:
            b.end_unit(self.sel)
            self.select(None)
            self.app.audio.play("ui_back", 0.4)
        if "R" in p.pressed:
            ready = [u for u in self.my_units() if not u.done and not (u.acted and "_skirmish" not in u.status)]
            if ready:
                idx = ready.index(self.sel) if self.sel in ready else -1
                self.select(ready[(idx + 1) % len(ready)])
        if "L" in p.pressed:
            idle = [u for u in self.my_units() if not u.done and not u.acted and not u.moved]
            if idle and not self.confirm_end:
                self.confirm_end = True
                self.say(f"{len(idle)} unit(s) have not acted. Press L again to end the phase.", False)
            else:
                self.end_phase()
        if "SELECT" in p.pressed:
            self.hp_always = not self.hp_always
        if "PAUSE" in p.pressed:
            self.app.scenes.push(TacticalPause(self.cs, self))

    def end_phase(self) -> None:
        self.select(None)
        self.b.end_phase()
        self.process_events()
        self.app.audio.play("concord_page", 0.4)

    def press_a(self) -> None:
        b = self.b
        cx, cy = self.cursor
        here = b.at(cx, cy)
        u = self.sel
        if u is None:
            if here and here.side == self.side:
                if here.done:
                    self.say("That unit has finished.", False)
                else:
                    self.select(here)
            elif here:
                self.say(f"{here.name}: HP {here.hp:.0f}/{here.maxhp:.0f}")
            return
        if self.mode == "ability":
            tgt = None
            if here and here in self._targets:
                tgt = here
            elif (cx, cy) in self._targets:
                tgt = (cx, cy)
            if tgt is None:
                self.say("Not a valid target.", False)
                return
            if b.use_ability(u, tgt):
                self.process_events()
                self.mode = "move"
                self.refresh()
                self._after_action()
            return
        # attacking an enemy (walk into range first if needed)
        if here and here.side != self.side:
            self.attack_with_approach(u, here)
            return
        if (cx, cy) in b.wall_hp and b.wall_hp[(cx, cy)] > 0:
            if b.attack_wall(u, (cx, cy)):
                self.process_events()
                self._after_action()
            else:
                self.say("Out of reach.", False)
            return
        if here and here.side == self.side and here is not u:
            self.select(here)
            return
        if (cx, cy) in self._reach and (cx, cy) != (u.x, u.y):
            if b.move(u, cx, cy):
                self.process_events()
                self.refresh()
                if not self._targets and u.acted:
                    self._after_action()
            return
        if (cx, cy) == (u.x, u.y):
            self.press_x() if False else None

    def attack_with_approach(self, u: B.BUnit, t: B.BUnit) -> None:
        b = self.b
        if t in b.targets(u):
            if b.attack(u, t):
                self.process_events()
                self._after_action()
            return
        # find the cheapest reachable tile from which the target is attackable
        best, bc = None, 99
        for (x, y), cost in self._reach.items():
            if (x, y) != (u.x, u.y) and t in b.targets(u, (x, y)) and cost < bc:
                best, bc = (x, y), cost
        if best is None:
            self.say("Cannot reach that target this phase.", False)
            return
        if b.move(u, *best):
            if b.attack(u, t):
                self.process_events()
                self._after_action()
            else:
                self.process_events()
                self.refresh()

    def press_x(self) -> None:
        u = self.sel
        if u is None:
            return
        if not u.ability:
            self.say("This unit has no ability.", False)
            return
        if not b_ready(self.b, u):
            self.say(f"{u.ability['name']} is on cooldown ({u.cd}).", False)
            return
        tg = self.b.ability_targets(u)
        if tg == [None]:
            if self.b.use_ability(u, None):
                self.process_events()
                self._after_action()
            return
        if not tg:
            self.say("No valid target for that ability.", False)
            return
        self.mode = "ability"
        self.refresh()
        self.say(f"{u.ability['name']}: choose a target.")

    def _after_action(self) -> None:
        u = self.sel
        if self.b.check_over():
            return
        if u is not None and (not u.active or (u.acted and "_skirmish" not in u.status)):
            self.select(None)
        else:
            self.refresh()

    # ------------------------------------------------------------------ drawing
    def draw(self, surf: pygame.Surface) -> None:
        b, f, c = self.b, self.app.font, self.c
        surf.blit(self.bg, (0, 0))
        ox = oy = 0
        if self.shake > 0 and FEEL.shake_scale:
            ox = int(random.uniform(-1, 1) * self.shake * FEEL.shake_scale)
            oy = int(random.uniform(-1, 1) * self.shake * FEEL.shake_scale)
        grid = pygame.Surface((B.GRID_W * T, B.GRID_H * T))
        for y in range(B.GRID_H):
            for x in range(B.GRID_W):
                k = b.tiles[y][x]
                grid.blit(art.battle_tile(k, T, (x * 7 + y * 13) % 6), (x * T, y * T))
                if k == B.WALL:
                    hpf = b.wall_hp.get((x, y), 0) / (22.0 * max(1, b.fort))
                    pygame.draw.rect(grid, (30, 24, 24), (x * T + 3, y * T + T - 6, T - 6, 4))
                    pygame.draw.rect(grid, (220, 190, 120), (x * T + 4, y * T + T - 5, int((T - 8) * clamp(hpf)), 2))
        pulse = 0.5 + 0.5 * math.sin(self.t * 0.2)
        u = self.sel
        ov = pygame.Surface((T, T), pygame.SRCALPHA)
        if u and self.player_phase():
            for (x, y), cost in self._reach.items():
                if (x, y) == (u.x, u.y):
                    continue
                ov.fill((90, 170, 255, 70))
                grid.blit(ov, (x * T, y * T))
            for tg in self._targets:
                if isinstance(tg, B.BUnit):
                    tx, ty = tg.x, tg.y
                    col = (255, 80, 70, 100) if tg.side != self.side else (120, 255, 150, 100)
                elif isinstance(tg, tuple) and len(tg) == 2 and isinstance(tg[0], str):
                    tx, ty = tg[1]
                    col = (255, 190, 80, 100)
                elif isinstance(tg, tuple):
                    tx, ty = tg
                    col = (180, 130, 255, 90)
                else:
                    continue
                ov.fill(col)
                grid.blit(ov, (tx * T, ty * T))
                pygame.draw.rect(grid, (255, 255, 255), (tx * T + 1, ty * T + 1, T - 2, T - 2), 1)
        surf.blit(grid, (GX + ox, GY + oy))
        pygame.draw.rect(surf, art.INK, (GX - 1, GY - 1, B.GRID_W * T + 2, B.GRID_H * T + 2), 1)
        # ---- units (sorted by y so lower rows overlap higher ones)
        for un in sorted(b.units, key=lambda q: self.vis[q.id][1]):
            if not un.alive and self.dying.get(un.id, 0) <= 0:
                continue
            if un.routed and self.dying.get(un.id, 0) <= 0:
                continue
            vx, vy = self.vis[un.id]
            cx, cy = self.center(vx, vy)
            cx += ox
            cy += oy
            if un.id in self.lunge:
                dx, dy, n = self.lunge[un.id]
                k = math.sin(n / 8 * math.pi) * 6
                cx += dx * k
                cy += dy * k
            flip = un.facing[0] < 0 if un.facing[0] else un.side == 1
            spr = art.unit_figure(un.role, self.cols[un.side], T - 4, flip, self.flash.get(un.id, 0) > 0, un.rank)
            fade = self.dying.get(un.id, 0)
            if fade > 0 and (not un.alive or un.routed):
                spr = spr.copy()
                spr.set_alpha(int(255 * fade / 24))
            pygame.draw.ellipse(surf, (40, 34, 30), (cx - 9, cy + 8, 18, 6))
            surf.blit(spr, (cx - spr.get_width() / 2, cy - spr.get_height() / 2 - 2))
            if un.active:
                if self.hp_always or un is u or (self.cursor == [un.x, un.y]):
                    hp = clamp(un.hp / un.maxhp)
                    pygame.draw.rect(surf, (20, 16, 30), (cx - 10, cy + 12, 20, 4))
                    pygame.draw.rect(surf, GOOD if hp > 0.6 else (255, 190, 100) if hp > 0.3 else DANGER, (cx - 9, cy + 13, int(18 * hp), 2))
                    mo = clamp(un.morale / un.maxmorale)
                    pygame.draw.rect(surf, (120, 170, 240), (cx - 9, cy + 15, int(18 * mo), 1))
                if un.done or (un.acted and "_skirmish" not in un.status and un.side == b.phase):
                    pygame.draw.rect(surf, (20, 16, 30), (cx - 10, cy - 14, 6, 4))
                    pygame.draw.rect(surf, (140, 140, 150), (cx - 9, cy - 13, 4, 2))
                sx = cx - 11
                for s_ in un.status:
                    if s_.startswith("_"):
                        continue
                    colr = {"slow": (150, 150, 255), "marked": (255, 90, 90), "shielded": (130, 214, 255), "braced": (210, 190, 140),
                            "inspired": (255, 214, 120), "enraged": (255, 120, 60), "stagger": (200, 160, 255)}[s_]
                    pygame.draw.rect(surf, colr, (sx, cy - 16, 3, 3))
                    sx += 4
            if un is u:
                pygame.draw.ellipse(surf, (255, 255, 255), (cx - 13, cy + 4, 26, 12), 1)
        # ---- cursor
        cx, cy = self.center(*self.cursor)
        rr = pygame.Rect(GX + self.cursor[0] * T + ox, GY + self.cursor[1] * T + oy, T, T)
        pygame.draw.rect(surf, (255, 255, 255), rr, 2)
        pygame.draw.rect(surf, art.INK, rr.inflate(2, 2), 1)
        self.parts.draw(surf, (0, 0))
        self.floats.draw(surf, f)
        self._top(surf)
        self._side(surf)
        if self.msg_t > 0:
            r = pygame.Rect(GX, GY + B.GRID_H * T + 4, B.GRID_W * T, 14)
            draw_panel(surf, r, fill=PANEL, alpha=245)
            f.draw(surf, self.msg, (r.centerx, r.y + 3), PARCHMENT, None, anchor="midtop")
        if self.phase_banner > 0 and not b.over:
            k = min(1.0, self.phase_banner / 15)
            txt = "YOUR PHASE" if b.phase == self.side else "ENEMY PHASE"
            col = (255, 244, 205) if b.phase == self.side else (255, 150, 130)
            f.draw(surf, txt, (GX + B.GRID_W * T // 2, GY + B.GRID_H * T // 2 - 8), col, art.INK, anchor="midtop", scale=3)
        if b.over:
            win = b.result["winner"] == self.side
            f.draw(surf, "VICTORY" if win else "DEFEAT", (GX + B.GRID_W * T // 2, GY + B.GRID_H * T // 2 - 10),
                   (255, 244, 205) if win else (255, 150, 130), art.INK, anchor="midtop", scale=4)
        keys = [("A", "Select/Act"), ("X", "Ability"), ("Y", "Hold"), ("R", "Next"), ("L", "End phase"), ("B", "Cancel")]
        draw_prompts(surf, self.app, keys, y=H - 12)

    def _top(self, surf: pygame.Surface) -> None:
        b, f, c = self.b, self.app.font, self.c
        r = pygame.Rect(0, 0, W, 22)
        pygame.draw.rect(surf, PANEL, r)
        pygame.draw.line(surf, BRASS, (0, 22), (W, 22))
        p = c.map.provinces[self.req.pid]
        f.draw(surf, f"{p.name}  round {min(b.round, B.ROUND_LIMIT)}/{B.ROUND_LIMIT}", (8, 3), PARCHMENT, None)
        for s in (0, 1):
            surf.blit(art.crest(self.cols[s], 9), (8 + s * 160, 12))
            alive = len(b.side_units(s))
            hp = sum(u.hp for u in b.side_units(s)) / max(1.0, b.start_hp[s])
            f.draw(surf, f"{c.short(self.req.att_house if s == 0 else self.req.def_house)} {alive}", (20 + s * 160, 12), self.cols[s], None)
            pygame.draw.rect(surf, (20, 16, 30), (80 + s * 160, 13, 50, 5))
            pygame.draw.rect(surf, self.cols[s], (81 + s * 160, 14, int(48 * clamp(hp)), 3))
        f.draw(surf, ("Attackers must break the line by round 16" if self.side == 0 else "Hold the line until round 16"),
               (W - 6, 3), DIM, None, anchor="topright")

    def _side(self, surf: pygame.Surface) -> None:
        b, f = self.b, self.app.font
        r = pygame.Rect(GX + B.GRID_W * T + 8, 26, W - (GX + B.GRID_W * T + 8) - 4, 222)
        draw_panel(surf, r, fill=PANEL, alpha=246)
        un = self.sel or b.at(*self.cursor)
        x, y = r.x + 6, r.y + 6
        if un is None:
            t = b.tiles[self.cursor[1]][self.cursor[0]]
            f.draw(surf, t.title(), (x, y), PARCHMENT, None)
            hints = {"forest": "Cover: +1 armour (+2 vs ranged). Costs 2 to enter.", "hill": "+1 armour; +10% damage to those below.",
                     "marsh": "-1 armour. Costs 2 to enter.", "rock": "Blocks movement and sight.", "water": "Impassable.",
                     "ford": "Costs 2 to cross.", "wall": "Blocks all but siege. Battering it opens the line.", "open": "Open ground."}
            f.draw_wrapped(surf, hints.get(t, ""), pygame.Rect(x, y + 12, r.w - 12, 40), DIM, None)
            return
        col = self.cols[un.side]
        spr = art.unit_figure(un.role, col, 28, un.side == 1)
        surf.blit(spr, (x, y))
        f.draw(surf, un.name, (x + 32, y + 2), PARCHMENT, None)
        f.draw(surf, art.ROLE_NAME[un.role] + (f"  rank {un.rank}" if un.rank else ""), (x + 32, y + 12), DIM, None)
        y += 34
        f.draw(surf, f"HP {un.hp:.0f}/{un.maxhp:.0f}", (x, y), GOOD, None)
        f.draw(surf, f"Morale {un.morale:.0f}", (x + 70, y), (120, 170, 240), None)
        y += 11
        f.draw(surf, f"Atk {b.effective_atk(un):.0f}  Arm {b.effective_arm(un):.0f}", (x, y), PARCHMENT, None)
        y += 10
        f.draw(surf, f"Move {b.effective_move(un)}  Range {un.range}", (x, y), PARCHMENT, None)
        y += 12
        for tr in un.traits:
            f.draw(surf, "* " + tr.replace("_", " "), (x, y), (200, 190, 170), None)
            y += 9
        if un.ability:
            ready = un.cd <= 0
            f.draw(surf, f"{un.ability['name']} " + ("(ready)" if ready else f"(cd {un.cd})"), (x, y + 2), LENS if ready else DIM, None)
            y += 12
            f.draw_wrapped(surf, un.ability.get("desc", ""), pygame.Rect(x, y, r.w - 12, 36), DIM, None, max_lines=4)
            y += 38
        st = [s for s in un.status if not s.startswith("_")]
        if st:
            f.draw(surf, ", ".join(f"{s} {un.status[s]}" for s in st), (x, y), (255, 214, 120), None)
            y += 10
        # damage preview
        s = self.sel
        if s and un.side != self.side and s.side == self.side and s.active:
            if un in b.targets(s) or any(un in b.targets(s, p_) for p_ in self._reach):
                dmg = b.damage_estimate(s, un)
                flank = b.facing_factor(s, un)
                f.draw(surf, f"Hit ~{dmg:.0f}" + (" (kills)" if dmg >= un.hp else ""), (x, r.bottom - 22), DANGER if dmg >= un.hp else PARCHMENT, None)
                if flank > 1.05:
                    f.draw(surf, "flanking bonus", (x + 70, r.bottom - 22), (255, 214, 120), None)


def b_ready(b: B.Battle, u: B.BUnit) -> bool:
    return b.ability_ready(u)


class _Tip(Scene):
    opaque = False

    def __init__(self, app):
        super().__init__(app)
        self.t = 0

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 8 and ("CONFIRM" in p.pressed or "BACK" in p.pressed):
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((10, 8, 20, 170))
        surf.blit(dim, (0, 0))
        r = pygame.Rect(50, 50, 380, 150)
        draw_panel(surf, r, fill=(236, 224, 190), alpha=252, border=art.WAX)
        f.draw(surf, "On the field", (r.x + 12, r.y + 8), art.WAX, None, scale=2)
        lines = ["Each unit may move, then act once. Hit enemies from behind (+30%) or the side (+12%).",
                 "Cavalry that run three tiles in a line charge for extra damage, but braced pikes bite back.",
                 "Archers are blocked by rocks and walls. Siege engines batter walls open.",
                 "Units break when morale runs out: kill the banner bearer, flank, and keep your line together.",
                 "Attack an enemy you cannot yet reach and your unit will walk into range first."]
        y = r.y + 30
        for ln in lines:
            for sub in f.wrap(ln, r.w - 24):
                f.draw(surf, sub, (r.x + 12, y), art.INK, None)
                y += 10
            y += 2
        draw_prompts(surf, self.app, [("CONFIRM", "Fight")], y=r.bottom - 14)


class TacticalPause(MenuScene):
    def __init__(self, cs, ts: TacticalScreen):
        self.cs, self.ts = cs, ts
        super().__init__(cs.app, "BATTLE", self._items, 230, overlay=True, footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [MenuItem("Resume", a.scenes.pop),
                MenuItem("Let the captains finish it (auto-resolve)", self._auto),
                MenuItem("Retreat (forfeit)", self._retreat, hint="Your units survive but you lose the field."),
                MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a)))]

    def _auto(self) -> None:
        ts = self.ts
        self.app.scenes.pop()
        b = ts.b
        ai_p = B.BattleAI(b, ts.side, 0.6, 0.5, b.rng.child("auto_p"))
        res = B.auto_resolve(b, ai_p if ts.side == 0 else ts.ai, ts.ai if ts.side == 0 else ai_p)
        ts.process_events()

    def _retreat(self) -> None:
        ts = self.ts
        self.app.scenes.pop()
        for u in ts.b.units:
            if u.side == ts.side and u.active:
                u.routed = True
        ts.b.result = ts.b._summary(1 - ts.side)


class ResultScreen(Scene):
    def __init__(self, cs, ms, req, result: dict):
        super().__init__(cs.app)
        self.cs, self.ms, self.req, self.result, self.c = cs, ms, req, result, cs.camp
        self.t = 0
        self.bg = art.parchment((W, H), 31)
        p = req.player_side
        self.won = p is None or (result["winner"] == p)
        cs.app.audio.play("victory_sting" if self.won else "defeat_sting", 0.7)

    def update(self, dt: float) -> None:
        self.t += 1
        pl = self.inp.player(0)
        if self.t > 20 and ("CONFIRM" in pl.pressed or "A" in pl.pressed):
            self.app.scenes.pop()
            self.ms.battle_finished(self.result)

    def draw(self, surf: pygame.Surface) -> None:
        f, c, res, req = self.app.font, self.c, self.result, self.req
        surf.blit(self.bg, (0, 0))
        title = "VICTORY" if self.won else "DEFEAT"
        f.draw(surf, title, (W // 2, 14), art.WAX if self.won else art.INK, None, anchor="midtop", scale=5)
        p = c.map.provinces[req.pid]
        f.draw(surf, f"The battle of {p.name} ends after {res['rounds']} rounds.", (W // 2, 54), art.INK, None, anchor="midtop")
        for side, x in ((0, 40), (1, 250)):
            hid = req.att_house if side == 0 else req.def_house
            r = pygame.Rect(x, 76, 190, 110)
            draw_panel(surf, r, fill=PANEL, alpha=246, border=hcol(c, hid))
            surf.blit(art.crest(hcol(c, hid), 12), (r.x + 8, r.y + 7))
            f.draw(surf, c.rules.houses[hid]["name"], (r.x + 24, r.y + 8), PARCHMENT, None)
            win = (res["winner"] == side)
            f.draw(surf, "Held the field" if win else "Driven from the field", (r.x + 24, r.y + 18), GOOD if win else DANGER, None)
            f.draw(surf, f"Lost: {res['losses'][side]} units", (r.x + 10, r.y + 36), PARCHMENT, None)
            hp0, hp1 = res["hp_start"][side], res["hp_left"][side]
            f.draw(surf, f"Strength left: {hp1 / max(1.0, hp0) * 100:.0f}%", (r.x + 10, r.y + 48), PARCHMENT, None)
            routed = sum(1 for v in res["units"].values() if v["side"] == side and v["routed"] and not v["dead"])
            f.draw(surf, f"Broken but alive: {routed}", (r.x + 10, r.y + 60), DIM, None)
            kills = sum(v["kills"] for v in res["units"].values() if v["side"] == side)
            f.draw(surf, f"Enemies slain: {kills}", (r.x + 10, r.y + 72), DIM, None)
        if res["winner"] == B.ATTACKER and req.fort:
            f.draw(surf, "The walls are no longer a refuge.", (W // 2, 196), art.WAX, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Continue")], y=H - 14)
