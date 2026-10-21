"""Title screen, save-slot selection and name entry."""
from __future__ import annotations

import math
import random

import pygame
from pygame.math import Vector2

from .. import GAME_TITLE
from ..core import art
from ..core.fx import blit_additive_glow, clamp, ease_out_cubic, mix
from ..core.save import SLOT_COUNT, SaveError
from ..core.scene import Scene
from ..core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Menu, MenuItem, SettingsScene,
                       ControlsScene, draw_panel, draw_prompts)

W, H = 480, 270

SHARD_COLORS = [(255, 122, 60), (120, 200, 90), (90, 170, 160), (255, 90, 70),
                (210, 170, 90), (190, 140, 90), (230, 70, 80), (110, 100, 220)]


class TitleScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.t = 0.0
        self.rng = random.Random(4)
        self.shards = []
        for i in range(8):
            self.shards.append({"a": i * math.tau / 8, "r": 40 + 10 * (i % 2), "spin": 0.3 + 0.08 * i,
                                "ph": self.rng.random() * 6.28, "c": SHARD_COLORS[i]})
        self.stars = art.starfield((W, H), 21, 0.006)
        self.stars2 = art.starfield((W, H), 22, 0.003, (255, 230, 200))
        has_save = any(self.app.saves.summaries())
        items = []
        if has_save:
            items.append(MenuItem("Continue", self._continue))
        items += [MenuItem("New game" if has_save else "Begin", self._slots),
                  MenuItem("Settings", lambda: app.scenes.push(SettingsScene(app))),
                  MenuItem("Controls", lambda: app.scenes.push(ControlsScene(app))),
                  MenuItem("Quit", self._quit)]
        self.menu = Menu(app, items, 150)
        self.age = 0.0

    def on_enter(self, **kw) -> None:
        self.app.audio.play_music("title", 2.0, 0.5)
        for note in self.app.saves.recovered:
            self.app.toast(note, (255, 210, 120))
        self.app.saves.recovered.clear()

    def _continue(self) -> None:
        # most recently played slot with a valid save
        best = None
        for s, summ in enumerate(self.app.saves.summaries()):
            if summ and not summ.get("broken"):
                try:
                    pf = self.app.saves.path(s).stat().st_mtime
                except OSError:
                    pf = 0
                if best is None or pf > best[0]:
                    best = (pf, s)
        if best and self.app.load_game(best[1]):
            self.app.return_to_hub()
        else:
            self._slots()

    def _slots(self) -> None:
        self.app.scenes.push(SlotScene(self.app))

    def _quit(self) -> None:
        self.app.running = False

    def update(self, dt: float) -> None:
        self.t += dt
        self.age += dt
        if self.age > 0.4:
            self.menu.update()

    def draw(self, surf: pygame.Surface) -> None:
        t = self.t
        surf.fill((10, 9, 22))
        art.dither_vertical(surf, pygame.Rect(0, 0, W, H), (10, 9, 24), (26, 20, 48))
        surf.blit(self.stars, (int(-t * 2) % W - W, 0))
        surf.blit(self.stars, (int(-t * 2) % W, 0))
        surf.blit(self.stars2, (int(-t * 5) % W - W, 0))
        surf.blit(self.stars2, (int(-t * 5) % W, 0))
        # reassembling lens
        cx, cy = 240, 74
        reform = ease_out_cubic(self.age / 3.0)
        blit_additive_glow(surf, (cx, cy), 120, (50, 44, 90), 2)
        for s in self.shards:
            ang = s["a"] + t * s["spin"] * 0.4
            rad = s["r"] * (1.0 + 1.5 * (1 - reform)) + math.sin(t + s["ph"]) * 3
            pos = (cx + math.cos(ang) * rad * 1.5, cy + math.sin(ang) * rad * 0.6)
            art.draw_prism(surf, pos, 9, s["c"], t + s["ph"], True, True, 0.9)
        art.draw_prism(surf, (cx, cy - 4 + math.sin(t) * 2), 22, (230, 235, 255), t, True, True, 0.35 + 0.1 * math.sin(t * 2))
        # title
        f = self.app.font
        title = GAME_TITLE
        sc = 4
        total = f.width(title, sc) + len(title) * 3
        x = (W - total) // 2
        for i, ch in enumerate(title):
            col = mix(BRASS, SHARD_COLORS[i % 8], 0.35)
            yoff = int(math.sin(t * 1.6 + i * 0.5) * 2)
            img = f.render(ch, col, (10, 6, 20), sc)
            surf.blit(img, (x, 124 + yoff))
            x += f.width(ch, sc) + 6 + 3
        f.draw(surf, "eight fractured worlds around one broken lens", (W // 2, 163), DIM, None, anchor="midtop", scale=1)
        self.menu.draw(surf, (W // 2 - 75, 184))
        f.draw(surf, "v0.1", (W - 6, H - 11), DIM, None, anchor="topright")


class SlotScene(Scene):
    opaque = True

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.age = 0.0
        self.confirm_delete = -1
        self.hold = 0.0
        self.summaries = app.saves.summaries()

    def refresh(self) -> None:
        self.summaries = self.app.saves.summaries()

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.12:
            return
        p = self.inp.player(0)
        _, dy = p.menu_dir()
        if dy:
            self.sel = (self.sel + dy) % SLOT_COUNT
            self.confirm_delete = -1
            self.app.audio.play("ui_move", 0.5)
        if "CONFIRM" in p.pressed:
            summ = self.summaries[self.sel]
            if summ is None:
                self.app.scenes.push(NameEntry(self.app, self.sel, self))
            elif summ.get("broken"):
                self.app.toast("That save is unrecoverable; delete it to reuse the slot", DANGER)
            elif self.app.load_game(self.sel):
                self.app.return_to_hub()
        if "X" in p.pressed and self.summaries[self.sel]:
            if self.confirm_delete == self.sel:
                self.app.saves.delete(self.sel)
                self.confirm_delete = -1
                self.refresh()
                self.app.toast("Slot cleared")
            else:
                self.confirm_delete = self.sel
                self.app.toast("Press X again to delete this slot", DANGER)
        if "BACK" in p.pressed:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        surf.fill(INK)
        art.dither_vertical(surf, pygame.Rect(0, 0, W, H), (14, 12, 28), (26, 22, 46))
        f.draw(surf, "CHOOSE A SAVE", (W // 2, 24), BRASS, (10, 6, 20), anchor="midtop", scale=2)
        for i in range(SLOT_COUNT):
            r = pygame.Rect(90, 62 + i * 52, 300, 44)
            sel = i == self.sel
            draw_panel(surf, r, border=BRASS if sel else (80, 72, 100), fill=INK_2 if sel else INK)
            s = self.summaries[i]
            f.draw(surf, f"Slot {i + 1}", (r.x + 10, r.y + 8), BRASS if sel else DIM, None)
            if s is None:
                f.draw(surf, "- empty -", (r.x + 10, r.y + 24), DIM, None)
            elif s.get("broken"):
                f.draw(surf, "Unrecoverable save", (r.x + 10, r.y + 24), DANGER, None)
            else:
                f.draw(surf, s["name"], (r.x + 70, r.y + 8), PARCHMENT, None)
                mins = int(s["playtime"] // 60)
                base = f"{mins // 60}h {mins % 60:02d}m   Lens {s['facets']}/8   Glint {s['glint']}"
                f.draw(surf, base, (r.x + 10, r.y + 26), LENS, None)
                tag = "LAMP RESTORED" if (s.get("tour", {}).get("done")) else ""
                if tag:
                    f.draw(surf, tag, (r.x + 10 + f.width(base) + 6, r.y + 26), BRASS, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Play / New"), ("X", "Delete"), ("BACK", "Back")])


class NameEntry(Scene):
    opaque = False

    def __init__(self, app, slot: int, parent: SlotScene):
        super().__init__(app)
        self.slot = slot
        self.name = ""
        self.age = 0.0
        self.parent = parent

    def update(self, dt: float) -> None:
        self.age += dt
        inp = self.app.input
        for ch in inp.text_input:
            if len(self.name) < 14 and (ch.isalnum() or ch in " -_'"):
                self.name += ch
        if any(e.key == pygame.K_BACKSPACE for e in inp.raw_key_events):
            self.name = self.name[:-1]
        inp.text_input.clear()
        if self.age < 0.2:
            inp.raw_key_events.clear()
            return
        if any(e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) for e in inp.raw_key_events) or \
                "A" in inp.player(0).pressed and inp.player(0).last_kind == "gamepad":
            self.app.scenes.pop()
            self.app.new_game(self.slot, self.name.strip() or "Lampwright")
            self.app.return_to_hub()
        elif any(e.key == pygame.K_ESCAPE for e in inp.raw_key_events) or "B" in inp.player(0).pressed and \
                inp.player(0).last_kind == "gamepad":
            self.app.scenes.pop()
        inp.raw_key_events.clear()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((6, 4, 14, 210))
        surf.blit(dim, (0, 0))
        r = pygame.Rect(120, 100, 240, 70)
        draw_panel(surf, r, title="NAME YOUR LAMPWRIGHT", font=f)
        shown = self.name + ("_" if int(self.age * 2) % 2 == 0 else " ")
        f.draw(surf, shown, (r.centerx, r.y + 22), (255, 244, 205), None, anchor="midtop", scale=2)
        f.draw(surf, "Type a name (or leave blank)", (r.centerx, r.y + 46), DIM, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Begin"), ("BACK", "Cancel")])
