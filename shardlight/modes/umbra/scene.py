"""Umbra scene: the Ward menu, play screen with HUD, note reader, pack and journal, pause and night results."""
from __future__ import annotations

import math
import random
from typing import Any

import pygame

from ...core.fx import FEEL, clamp, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Dialogue, Menu, MenuItem, MenuScene, SettingsScene,
                        ControlsScene, draw_panel, draw_prompts)
from .catalog import Catalog
from .consts import HEALTH_MAX, LAMP, STAMINA_MAX, TEAL, TEAL_LIGHT, TILE
from .info import INFO
from .props import PROP_DEFS
from .sim import BAG_SLOTS, Controls, Game
from .view import View

W, H = 480, 270
SAVE_V = 1
NOISE_SFX = {"door_open": "umbra_door", "door_open_sneak": "umbra_door", "door_close": "umbra_door", "door_close_sneak": "umbra_door",
             "door_bang": "umbra_bang", "door_break": "umbra_break", "unlock": "umbra_unlock", "flashlight": "umbra_click", "match": "umbra_match",
             "pickup": "umbra_pickup", "drawer": "umbra_drawer", "locker": "umbra_drawer", "breath": "umbra_breath", "gasp": "umbra_gasp",
             "pant": "umbra_gasp", "fuse": "umbra_fuse", "generator": "umbra_generator", "clock": "umbra_lever", "crank": "umbra_crank",
             "ward_hum": "umbra_ward", "hit": "umbra_hit", "thrown_default": "umbra_clatter", "lamp_refill": "umbra_pickup", "bandage": "umbra_cloth"}
STEP_SFX = ["umbra_step_wood", "umbra_step_tile", "umbra_step_stone", "umbra_step_carpet", "umbra_step_gravel", "umbra_step_glass", "umbra_step_water"]


class UmbraScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.cat: Catalog | None = None
        self.game: Game | None = None
        self.screen: Scene | None = None
        self.opt_seed = opts.get("seed", "random")
        self.t = 0

    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("seen", {})
        d.setdefault("cleared", [])
        d.setdefault("journal", {"notes": [], "facts": [], "relics": []})
        d.setdefault("seed", 0)
        self.cat = Catalog(self.app.content, self.app.world.has_unlock)
        self.app.audio.play_music("umbra", 1.2, 0.15)
        self.show_menu()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, PlayScreen):
            self.app.scenes.push(PauseMenu(self))

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.audio.set_intensity(0.1)
        self.set_screen(MenuScreen(self))

    # ------------------------------------------------------------------ nights
    def seed_for(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        s = self.data.get("seed") or random.Random(self.app.rng.randrange(1 << 30)).randrange(1000, 999999)
        self.data["seed"] = s
        return s

    def start_night(self, n: int, resume: bool = False) -> None:
        s = self.app.settings
        if resume and self.data.get("run"):
            g = Game.from_dict(self.cat, self.data["run"], float(s.get("difficulty.adaptive_ai")), self.app.world.has_unlock)
            if g is not None:
                g.journal = self.data["journal"] if g.journal is None else g.journal
                self.data["journal"] = g.journal
                self.game = g
                self.set_screen(PlayScreen(self))
                return
        self.game = Game(self.cat, n, self.seed_for(), s.get("difficulty.preset"), float(s.get("difficulty.adaptive_ai")),
                         self.data["journal"], self.app.world.has_unlock)
        self.data["run"] = None
        self.set_screen(PlayScreen(self, intro=True))

    def save_run(self) -> None:
        if self.game is not None and not self.game.complete:
            self.data["run"] = self.game.to_dict()
        self.data["summary"] = f"Nights cleared: {len(self.data['cleared'])}/{self.cat.night_count()}"
        self.app.save_now()

    def drain_hooks(self) -> None:
        g = self.game
        while g.hooks:
            name, payload = g.hooks.pop(0)
            if name == "umbra.night_survived":
                n = payload["night"]
                if n not in self.data["cleared"]:
                    self.data["cleared"].append(n)
                if len(set(self.data["cleared"])) >= self.cat.night_count():
                    if self.app.world.complete_facet("umbra"):
                        self.app.toast("Umbra: the Facet is repaired", LENS)
            self.app.world.emit(name, **payload)


# ====================================================================================== menu
class MenuScreen(Scene):
    def __init__(self, us: UmbraScene):
        super().__init__(us.app)
        self.us = us
        self.t = 0
        d = us.data
        items = []
        run = d.get("run")
        items.append(MenuItem("Continue (last safe room)", self._cont, enabled=bool(run),
                              hint=f"Night {run['night']}" if run else "No night in progress"))
        for n in range(1, us.cat.night_count() + 1):
            nd = us.cat.night(n)
            done = n in d["cleared"]
            ok = n == 1 or (n - 1) in d["cleared"]
            items.append(MenuItem(f"Night {n}: {nd['place']}" + ("  [survived]" if done else ""), (lambda n=n: self._start(n)), enabled=ok,
                                  hint=nd["brief"] if ok else "Survive the previous night first"))
        items.append(MenuItem("Journal", lambda: self.app.scenes.push(JournalScreen(us, None))))
        items.append(MenuItem("Return to hub", lambda: us.finish(left=True)))
        self.menu = Menu(self.app, items, 300)
        self.rng = random.Random(2)

    def _cont(self) -> None:
        self.us.start_night(self.us.data["run"]["night"], resume=True)

    def _start(self, n: int) -> None:
        self.us.data["run"] = None
        self.us.start_night(n)

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
            if "BACK" in self.inp.player(0).pressed and self.t > 12:
                self.us.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        surf.fill((7, 9, 14))
        rng = random.Random(4)
        # a flickering lamp in the dark
        flick = 0.85 + 0.15 * math.sin(self.t * 0.21) * math.sin(self.t * 0.13)
        for r in range(90, 6, -6):
            a = (1 - r / 90) ** 2 * flick
            pygame.draw.circle(surf, tuple(int(c * a * 0.5) for c in LAMP), (380, 120), r)
        pygame.draw.circle(surf, (255, 214, 150), (380, 120), 4)
        pygame.draw.polygon(surf, (6, 8, 12), [(350, 260), (370, 150), (392, 150), (410, 260)])    # a tall figure at the edge of the light
        pygame.draw.circle(surf, (6, 8, 12), (381, 140), 7)
        f.draw(surf, "UMBRA", (24, 18), TEAL_LIGHT, (4, 6, 8), scale=5)
        f.draw(surf, "The Gloaming Ward", (28, 62), (200, 195, 176), (4, 6, 8), scale=2)
        draw_panel(surf, pygame.Rect(18, 92, 316, 138), fill=(10, 14, 18), alpha=240, border=TEAL)
        self.menu.draw(surf, (24, 98))
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])


# ====================================================================================== play
class PlayScreen(Scene):
    def __init__(self, us: UmbraScene, intro: bool = False):
        super().__init__(us.app)
        self.us = us
        self.g: Game = us.game
        self.view = View(self.g)
        self.t = 0
        self.intro = intro
        self.toasts: list[list] = []
        self.hit_flash = 0.0
        self.heart_t = 0.0
        self.banner = ""
        self.banner_t = 0.0
        self.ended = False
        self.fade = 1.0
        self.prompt = None
        self.note_open = None

    def on_enter(self, **kw) -> None:
        self.app.input.assign_local(1)
        nd = self.g.nd
        self.banner, self.banner_t = nd["title"], 4.0
        if self.intro:
            lines = [("", nd["intro"])]
            if not self.us.data["seen"].get("controls"):
                self.us.data["seen"]["controls"] = True
                lines.append(("", "Hold L to sneak. B opens doors and searches. Y cycles flashlight and lamp. X uses the selected item, R changes it. Quiet feet beat fast ones."))
            self.app.scenes.push(Dialogue(self.app, lines, color=TEAL_LIGHT))

    def toast(self, text: str, col=PARCHMENT, t: float = 3.0) -> None:
        self.toasts.append([text, t, col])
        self.toasts = self.toasts[-4:]

    # ------------------------------------------------------------------ input
    def controls(self) -> Controls:
        p = self.inp.player(0)
        c = Controls()
        c.move = (p.move.x, p.move.y)
        c.run = "A" in p.down
        c.sneak = "L" in p.down
        c.interact = "B" in p.pressed
        c.use = "X" in p.pressed
        c.light = "Y" in p.pressed
        c.cycle = "R" in p.pressed
        if p.aim.length() > 0.3:
            c.aim = (p.aim.x, p.aim.y)
        return c

    def update(self, dt: float) -> None:
        self.t += 1
        g = self.g
        p0 = self.inp.player(0)
        self.fade = max(0.0, self.fade - dt * 1.6)
        self.banner_t = max(0.0, self.banner_t - dt)
        self.hit_flash = max(0.0, self.hit_flash - dt)
        for t in self.toasts:
            t[1] -= dt
        self.toasts = [t for t in self.toasts if t[1] > 0]
        if "PAUSE" in p0.pressed:
            self.app.scenes.push(PauseMenu(self.us))
            return
        if "SELECT" in p0.pressed and not g.p.dead:
            self.app.scenes.push(PackScreen(self.us, self))
            return
        if g.p.dead:
            if "CONFIRM" in p0.pressed or "B" in p0.pressed:
                g.respawn()
                self.us.save_run()
            self._events()
            return
        g.update(dt, self.controls())
        self._events()
        self.prompt = g.context()
        self.app.audio.set_intensity(g.director.music_intensity())
        # heartbeat when something is close and angry
        tension = g.director.tension
        if tension > 0.35:
            self.heart_t -= dt
            if self.heart_t <= 0:
                self.heart_t = 1.1 - 0.6 * tension
                self.app.audio.play("umbra_heart", 0.25 + 0.5 * tension)
        self.us.drain_hooks()
        if g.complete and not self.ended:
            self.ended = True
            self.us.data["run"] = None
            self.us.app.save_now()
            self.app.scenes.push(ResultScreen(self.us, g))

    def _events(self) -> None:
        g, a = self.g, self.app.audio
        for ev, d in g.pop_events():
            if ev == "step":
                vol = {"sneak": 0.1, "walk": 0.3, "run": 0.55}[d["stance"]]
                a.play(STEP_SFX[d["surface"]], vol)
            elif ev == "noise":
                k = d["kind"]
                if d["source"] == "player" and k != "step":
                    sfx = NOISE_SFX.get(k)
                    if sfx:
                        a.play(sfx, clamp(0.2 + d["loud"] / 20))
                elif d["source"] in ("hark", "stillwatch", "understudy"):
                    sfx = NOISE_SFX.get(k)
                    if sfx and k != "step":
                        a.play(sfx, clamp(0.2 + d["loud"] / 20))
                if d["loud"] >= 3.5:
                    self.view.add_ripple(d["x"], d["y"], d["loud"], "enemy" if d["source"] in ("hark", "stillwatch", "understudy") else "player")
            elif ev == "fact":
                self.toast("Journal: " + d["text"][:60] + "...", LENS, 4.0)
                a.play("umbra_note", 0.5)
            elif ev == "note_new":
                self.toast("Note added to the journal", LENS)
                a.play("umbra_note", 0.5)
            elif ev == "read":
                self.app.scenes.push(NoteScreen(self.us, d["id"]))
            elif ev == "hit":
                self.hit_flash = 0.5
                FEEL.flash((200, 30, 30), 0.35)
                a.play("umbra_hit", 0.8)
            elif ev == "died":
                a.play("umbra_death", 0.9)
            elif ev == "checkpoint":
                self.toast("Safe room: progress kept", GOOD)
                a.play("umbra_safe", 0.6)
                self.us.save_run()
            elif ev == "got":
                self.toast("Took " + g.item_def(d["item"])["name"], PARCHMENT)
            elif ev == "bag_full":
                self.toast("Your hands are full", DANGER)
            elif ev == "locked":
                self.toast("Locked. Missing: " + ", ".join(d["missing"]), DANGER)
                a.play("umbra_locked", 0.5)
            elif ev == "unlocked":
                self.toast("Unlocked", GOOD)
            elif ev == "gate_stuck":
                self.toast("The gate will not move by hand.", DANGER)
            elif ev == "info":
                self.toast(d["text"], PARCHMENT)
            elif ev == "fuse_in":
                self.toast(f"Fuse fitted ({d['n']})", GOOD)
            elif ev == "generator_on":
                self.toast("The generator roars. Everything heard it.", DANGER, 4.5)
            elif ev == "power_on":
                self.toast("Power returns. Get back to the Linen Room.", GOOD, 4.5)
            elif ev == "gate_open":
                self.toast("The gate groans open. Run for the stairs.", GOOD, 4.5)
                a.play("umbra_break", 0.6)
            elif ev == "relic":
                self.toast("The clock ticks once.", LENS, 4.0)
                a.play("umbra_clock", 0.8)
            elif ev == "light_died":
                self.toast("Your light gutters out", DANGER)
            elif ev == "recharged":
                self.toast("Flashlight recharged", GOOD)
            elif ev == "refilled":
                self.toast("Lamp refilled", GOOD)
            elif ev == "healed":
                self.toast("You feel steadier", GOOD)
            elif ev == "full":
                self.toast("Already full", DIM)
            elif ev == "combined":
                self.toast("Crafted " + g.item_def(d["out"])["name"], GOOD)
            elif ev == "thrown":
                a.play("umbra_throw", 0.4)
                if d["broke"]:
                    a.play("umbra_glass", 0.8)
            elif ev == "mimic":
                a.play("umbra_mimic", 0.6)
            elif ev == "peak":
                pass
            elif ev == "respawn":
                self.fade = 1.0
                self.toast("You wake in the last safe room", PARCHMENT, 4.0)

    # ------------------------------------------------------------------ drawing
    def draw(self, surf: pygame.Surface) -> None:
        g, f = self.g, self.app.font
        self.view.draw(surf, 1 / 60)
        self._hud(surf, f)
        if self.hit_flash > 0:
            vig = pygame.Surface((W, H), pygame.SRCALPHA)
            vig.fill((140, 10, 14, int(120 * self.hit_flash)))
            surf.blit(vig, (0, 0))
        t = g.director.tension
        if t > 0.5 and not g.p.dead:
            vig = pygame.Surface((W, H), pygame.SRCALPHA)
            a = int(60 * (t - 0.5) * 2)
            pygame.draw.rect(vig, (90, 0, 0, a), (0, 0, W, H), 14)
            surf.blit(vig, (0, 0))
        if g.p.dead:
            dim = pygame.Surface((W, H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 200))
            surf.blit(dim, (0, 0))
            f.draw(surf, "IT FOUND YOU", (W // 2, 90), (200, 40, 40), (10, 0, 0), anchor="midtop", scale=4)
            f.draw(surf, "You return to the last safe room. The ward remembers how you died.", (W // 2, 132), PARCHMENT, None, anchor="midtop")
            draw_prompts(surf, self.app, [("CONFIRM", "Rise")], y=150)
        if self.fade > 0:
            veil = pygame.Surface((W, H))
            veil.set_alpha(int(255 * clamp(self.fade)))
            surf.blit(veil, (0, 0))
        FEEL.draw_flash(surf)

    def _hud(self, surf: pygame.Surface, f) -> None:
        g, p = self.g, self.g.p
        # objective
        if self.banner_t > 0:
            a = clamp(self.banner_t / 1.0)
            f.draw(surf, self.banner, (W // 2, 110), tuple(int(c * a) for c in PARCHMENT), (0, 0, 0), anchor="midtop", scale=2)
        f.draw(surf, g.objective_text(), (8, 6), (170, 190, 186), (0, 0, 0))
        # health pips
        for i in range(HEALTH_MAX):
            col = (180, 50, 50) if i < p.hp else (50, 24, 28)
            pygame.draw.circle(surf, (0, 0, 0), (14 + i * 14, 24), 6)
            pygame.draw.circle(surf, col, (14 + i * 14, 24), 5)
        # lights and stamina
        def bar(x, y, wd, frac, col, label):
            pygame.draw.rect(surf, (0, 0, 0), (x - 1, y - 1, wd + 2, 6))
            pygame.draw.rect(surf, (28, 32, 36), (x, y, wd, 4))
            pygame.draw.rect(surf, col, (x, y, int(wd * clamp(frac)), 4))
            f.draw(surf, label, (x + wd + 4, y - 2), DIM, (0, 0, 0))
        bar(8, 36, 60, p.battery / 100.0, (150, 226, 200) if p.mode != "flash" else (230, 250, 240), "flash")
        bar(8, 44, 60, p.oil / 100.0, (230, 170, 70) if p.mode != "lamp" else (255, 214, 130), "lamp")
        bar(8, 52, 60, p.stamina / STAMINA_MAX, (170, 170, 190) if p.exhausted <= 0 else (200, 90, 90), "breath")
        # noise indicator: how loud you currently are
        loud = {"sneak": 1.5, "walk": 4.5, "run": 9.0}[p.stance] if p.moved else 0.4
        f.draw(surf, "sound", (8, 62), DIM, (0, 0, 0))
        for i in range(5):
            on = loud > [0.5, 2, 4, 7, 10][i]
            pygame.draw.rect(surf, (200, 210, 190) if on else (30, 34, 38), (44 + i * 5, 63, 4, 6))
        # bag
        x0 = W // 2 - BAG_SLOTS * 10
        for i in range(BAG_SLOTS):
            r = pygame.Rect(x0 + i * 20, H - 26, 18, 18)
            sel = i == p.sel
            pygame.draw.rect(surf, (10, 12, 14), r)
            pygame.draw.rect(surf, BRASS if sel else (50, 56, 60), r, 2 if sel else 1)
            if i < len(p.bag):
                it, n = p.bag[i]
                col = tuple(g.item_def(it).get("color", (200, 200, 200)))
                pygame.draw.circle(surf, col, (r.centerx, r.centery - 1), 5)
                pygame.draw.circle(surf, (0, 0, 0), (r.centerx, r.centery - 1), 5, 1)
                if n > 1:
                    f.draw(surf, str(n), (r.right - 1, r.bottom - 8), PARCHMENT, (0, 0, 0), anchor="topright")
        sel = g.selected()
        if sel:
            f.draw(surf, g.item_def(sel)["name"], (W // 2, H - 38), PARCHMENT, (0, 0, 0), anchor="midtop")
        # pockets (keys / objective items)
        px = W - 6
        for it, n in g.p.pocket.items():
            col = tuple(g.item_def(it).get("color", (200, 200, 200)))
            pygame.draw.rect(surf, (0, 0, 0), (px - 12, 6, 12, 12))
            pygame.draw.rect(surf, col, (px - 11, 7, 10, 10))
            px -= 15
        # prompt
        if self.prompt and not self.g.p.dead:
            f.draw(surf, f"[{self.inp.player(0).prompt('B')}] {self.prompt}", (W // 2, H - 52), (230, 236, 226), (0, 0, 0), anchor="midtop")
        # toasts
        y = 80
        for text, t, col in self.toasts:
            f.draw(surf, text, (W // 2, y), col, (0, 0, 0), anchor="midtop")
            y += 10
        if g.p.hiding is not None:
            f.draw(surf, "Hiding. Stay quiet.", (W // 2, 100), (170, 190, 186), (0, 0, 0), anchor="midtop")
        # tension tag (accessibility: the director state is visible in debug only)
        if self.app.debug:
            f.draw(surf, f"{g.director.state} T{g.director.tension:.2f} P{g.director.peaks}", (W - 6, H - 10), DIM, None, anchor="topright")


# ====================================================================================== overlays
class NoteScreen(Scene):
    opaque = False

    def __init__(self, us: UmbraScene, nid: str):
        super().__init__(us.app)
        self.us = us
        n = us.cat.note(nid)
        self.title = n["title"] if n else "?"
        self.text = n["text"] if n else ""
        self.t = 0
        self.speaker = n.get("speaker", "") if n else ""

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 10 and ("CONFIRM" in p.pressed or "B" in p.pressed or "BACK" in p.pressed):
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 190))
        surf.blit(dim, (0, 0))
        r = pygame.Rect(70, 34, 340, 190)
        pygame.draw.rect(surf, (200, 192, 168), r)
        pygame.draw.rect(surf, (90, 76, 56), r, 2)
        f.draw(surf, self.title, (r.x + 12, r.y + 10), (60, 40, 30), None)
        if self.speaker:
            f.draw(surf, f"({self.speaker})", (r.x + 12, r.y + 22), (110, 90, 70), None)
        shown = int(self.t * 3)
        f.draw_wrapped(surf, self.text[:shown], pygame.Rect(r.x + 12, r.y + 36, r.w - 24, r.h - 56), (40, 30, 24), None)
        draw_prompts(surf, self.app, [("CONFIRM", "Close")], y=r.bottom - 14)


class PackScreen(Scene):
    opaque = False

    def __init__(self, us: UmbraScene, ps: PlayScreen | None, tab: int = 0):
        super().__init__(us.app)
        self.us, self.ps, self.g = us, ps, us.game
        self.tab = tab
        self.cur = 0
        self.mark: int | None = None
        self.t = 0
        self.msg = ""
        self.msg_t = 0

    def update(self, dt: float) -> None:
        self.t += 1
        self.msg_t = max(0, self.msg_t - 1)
        p = self.inp.player(0)
        if self.t < 5:
            return
        if "SELECT" in p.pressed or "BACK" in p.pressed:
            self.app.scenes.pop()
            return
        if "L" in p.pressed or "R" in p.pressed:
            self.tab = (self.tab + 1) % 2
        dx, dy = p.menu_dir()
        if self.tab == 0:
            n = max(1, len(self.g.p.bag))
            self.cur = (self.cur + dx + dy * 4) % n
            if "CONFIRM" in p.pressed and self.g.p.bag:
                if self.mark is None:
                    self.mark = self.cur
                    self.say("Choose a second item to combine, or confirm again to use.")
                elif self.mark == self.cur:
                    self.g.p.sel = self.cur
                    self.g.use_selected()
                    self.mark = None
                else:
                    a, b = self.g.p.bag[self.mark][0], self.g.p.bag[self.cur][0]
                    if self.g.combine(a, b):
                        self.say("Crafted something.")
                        self.app.audio.play("umbra_pickup", 0.6)
                    else:
                        self.say("Those do not go together.")
                        self.app.audio.play("umbra_locked", 0.4)
                    self.mark = None
                    self.cur = min(self.cur, max(0, len(self.g.p.bag) - 1))
            if "X" in p.pressed and self.g.p.bag:
                self.g.p.sel = self.cur
                self.say("Selected.")
        else:
            notes = self.us.data["journal"]["notes"]
            if dy and notes:
                self.cur = (self.cur + dy) % max(1, len(notes))
            if "CONFIRM" in p.pressed and notes:
                self.app.scenes.push(NoteScreen(self.us, notes[self.cur % len(notes)]))

    def say(self, t: str) -> None:
        self.msg, self.msg_t = t, 150

    def draw(self, surf: pygame.Surface) -> None:
        f, g = self.app.font, self.g
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 215))
        surf.blit(dim, (0, 0))
        for i, nme in enumerate(("Bag", "Journal")):
            r = pygame.Rect(14 + i * 60, 10, 56, 14)
            pygame.draw.rect(surf, BRASS if i == self.tab else INK_2, r)
            f.draw(surf, nme, (r.centerx, r.y + 3), (16, 12, 30) if i == self.tab else DIM, None, anchor="midtop")
        body = pygame.Rect(10, 28, W - 20, H - 52)
        draw_panel(surf, body, fill=(10, 14, 18), alpha=245, border=TEAL)
        if self.tab == 0:
            for i in range(BAG_SLOTS):
                r = pygame.Rect(body.x + 12 + (i % 4) * 44, body.y + 14 + (i // 4) * 44, 40, 40)
                pygame.draw.rect(surf, (18, 22, 26), r)
                col = BRASS if i == self.cur else LENS if i == self.mark else (60, 70, 74)
                pygame.draw.rect(surf, col, r, 2 if i in (self.cur, self.mark) else 1)
                if i < len(g.p.bag):
                    it, n = g.p.bag[i]
                    c = tuple(g.item_def(it).get("color", (200, 200, 200)))
                    pygame.draw.circle(surf, c, r.center, 10)
                    pygame.draw.circle(surf, (0, 0, 0), r.center, 10, 1)
                    f.draw(surf, f"x{n}", (r.right - 2, r.bottom - 9), PARCHMENT, (0, 0, 0), anchor="topright")
                    if i == g.p.sel:
                        f.draw(surf, "*", (r.x + 3, r.y + 2), BRASS, None)
            if g.p.bag and self.cur < len(g.p.bag):
                it = g.p.bag[self.cur][0]
                d = g.item_def(it)
                f.draw(surf, d["name"], (body.x + 200, body.y + 16), PARCHMENT, None)
                f.draw_wrapped(surf, d.get("desc", ""), pygame.Rect(body.x + 200, body.y + 30, 240, 40), DIM, None)
            f.draw(surf, "Pockets: " + (", ".join(f"{g.item_def(k)['name']}" for k in g.p.pocket) or "empty"), (body.x + 200, body.y + 90), (200, 190, 150), None)
            rec = self.us.cat.recipes()
            f.draw(surf, "Known combinations:", (body.x + 200, body.y + 110), DIM, None)
            for j, r_ in enumerate(rec[:4]):
                f.draw(surf, r_["hint"], (body.x + 204, body.y + 122 + j * 10), (150, 190, 180), None)
        else:
            j = self.us.data["journal"]
            notes = j["notes"]
            f.draw(surf, f"Notes ({len(notes)})", (body.x + 10, body.y + 8), DIM, None)
            for i, nid in enumerate(notes[:12]):
                n = self.us.cat.note(nid)
                on = i == self.cur % max(1, len(notes))
                f.draw(surf, (n["title"] if n else nid)[:30], (body.x + 12, body.y + 22 + i * 10), PARCHMENT if on else DIM, None)
            f.draw(surf, "What I have learned", (body.x + 210, body.y + 8), DIM, None)
            y = body.y + 22
            for key in j["facts"]:
                kind, fid = key.split(":")
                e = self.us.cat.enemy(kind)
                text = next((x["text"] for x in e["facts"] if x["id"] == fid), "")
                for line in f.wrap(f"{e['name']}: {text}", body.w - 220)[:3]:
                    f.draw(surf, line, (body.x + 210, y), (200, 205, 190), None)
                    y += 9
                y += 2
                if y > body.bottom - 16:
                    break
            if "stopped_clock" in j["relics"]:
                f.draw(surf, "Relic: the Stopped Clock", (body.x + 12, body.bottom - 14), LENS, None)
        if self.msg_t > 0:
            f.draw(surf, self.msg, (W // 2, H - 24), (220, 230, 220), None, anchor="midtop")
        keys = [("CONFIRM", "Pick / combine / use"), ("X", "Select"), ("L", "Tab"), ("SELECT", "Close")] if self.tab == 0 else [("CONFIRM", "Read"), ("L", "Tab"), ("SELECT", "Close")]
        draw_prompts(surf, self.app, keys, y=H - 12)


class JournalScreen(PackScreen):
    def __init__(self, us: UmbraScene, ps):
        super().__init__(us, ps, tab=1)
        self.g = us.game or None

    def draw(self, surf: pygame.Surface) -> None:
        if self.g is None:
            self.g = _NullGame(self.us.cat)
        super().draw(surf)


class _NullGame:
    def __init__(self, cat):
        self.cat = cat

        class P:
            bag = []
            pocket = {}
            sel = 0
        self.p = P()

    def item_def(self, i):
        return self.cat.item(i)


class PauseMenu(MenuScene):
    def __init__(self, us: UmbraScene):
        self.us = us
        super().__init__(us.app, "PAUSED", self._items, 230, overlay=True, footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [MenuItem("Resume", a.scenes.pop), MenuItem("Save at last safe room", self._save),
                MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
                MenuItem("Ward menu (saves)", self._menu), MenuItem("Leave shard (saves)", self._leave)]

    def _save(self) -> None:
        self.us.save_run()
        self.app.toast("Saved at the last safe room", GOOD)

    def _menu(self) -> None:
        self.app.scenes.pop()
        self.us.save_run()
        self.us.show_menu()

    def _leave(self) -> None:
        self.app.scenes.pop()
        self.us.save_run()
        self.us.finish(left=True)


class ResultScreen(Scene):
    def __init__(self, us: UmbraScene, g: Game):
        super().__init__(us.app)
        self.us, self.g = us, g
        self.t = 0
        self.app.audio.play("umbra_safe", 0.8)

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 40 and ("CONFIRM" in p.pressed or "B" in p.pressed):
            self.app.scenes.pop()
            self.us.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        f, g = self.app.font, self.g
        surf.fill((6, 8, 12))
        f.draw(surf, "NIGHT SURVIVED", (W // 2, 24), TEAL_LIGHT, (0, 0, 0), anchor="midtop", scale=3)
        f.draw(surf, g.nd["title"], (W // 2, 54), (200, 195, 176), None, anchor="midtop")
        f.draw_wrapped(surf, g.nd["outro"], pygame.Rect(60, 84, W - 120, 60), (180, 190, 184), None)
        r = pygame.Rect(150, 150, 180, 66)
        draw_panel(surf, r, fill=(10, 14, 18), border=TEAL)
        rows = [("Time", f"{int(g.time // 60)}:{int(g.time % 60):02d}"), ("Doors opened", g.stats["doors"]), ("Hiding places used", g.stats["hides"]),
                ("Falls to the dark", g.deaths)]
        for i, (k, v) in enumerate(rows):
            f.draw(surf, k, (r.x + 10, r.y + 8 + i * 13), DIM, None)
            f.draw(surf, str(v), (r.right - 10, r.y + 8 + i * 13), PARCHMENT, None, anchor="topright")
        n = len(self.us.data["cleared"])
        if n >= self.us.cat.night_count():
            f.draw(surf, "The Ward is quiet. The facet answers.", (W // 2, 226), LENS, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Continue")], y=H - 14)
