"""Shared UI: panels, navigable menus (keyboard / pad / mouse), prompts, pause menu, settings screens."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pygame

from .fx import clamp, ease_out_cubic, mix
from .input import REMAPPABLE
from .scene import Scene

INK = (16, 15, 28)
INK_2 = (28, 26, 46)
PARCHMENT = (238, 228, 200)
DIM = (150, 144, 160)
BRASS = (222, 168, 70)
LENS = (130, 214, 255)
DANGER = (240, 100, 90)
GOOD = (130, 230, 150)


def draw_panel(surf: pygame.Surface, rect: pygame.Rect, border=BRASS, fill=INK, alpha: int = 235,
               title: str | None = None, font=None) -> None:
    """Notched-corner panel used across all modes for a consistent UI language."""
    r = pygame.Rect(rect)
    layer = pygame.Surface(r.size, pygame.SRCALPHA)
    layer.fill((*fill, alpha))
    surf.blit(layer, r.topleft)
    x0, y0, x1, y1 = r.left, r.top, r.right - 1, r.bottom - 1
    for a, b in (((x0 + 2, y0), (x1 - 2, y0)), ((x0 + 2, y1), (x1 - 2, y1)),
                 ((x0, y0 + 2), (x0, y1 - 2)), ((x1, y0 + 2), (x1, y1 - 2))):
        pygame.draw.line(surf, border, a, b)
    for c in ((x0 + 1, y0 + 1), (x1 - 1, y0 + 1), (x0 + 1, y1 - 1), (x1 - 1, y1 - 1)):
        surf.set_at(c, border)
    inner = mix(border, fill, 0.75)
    pygame.draw.rect(surf, inner, r.inflate(-6, -6), 1)
    if title and font:
        tw = font.width(title) + 10
        tr = pygame.Rect(r.x + 8, r.y - 5, tw, 11)
        pygame.draw.rect(surf, fill, tr)
        font.draw(surf, title, (tr.x + 5, tr.y + 1), border, None)


def draw_prompts(surf: pygame.Surface, app, pairs: list[tuple[str, str]], slot: int = 0,
                 y: int | None = None, align: str = "center") -> None:
    """Footer like ``[J] Select   [K] Back`` using the labels of the device in use."""
    f = app.font
    player = app.input.player(slot)
    parts = [(player.prompt(btn), text) for btn, text in pairs]
    total = sum(f.width(f"[{k}] {t}") + 12 for k, t in parts) - 12
    x = (surf.get_width() - total) // 2 if align == "center" else 8
    y = y if y is not None else surf.get_height() - 14
    for k, t in parts:
        w = f.width(f"[{k}]")
        f.draw(surf, f"[{k}]", (x, y), BRASS)
        f.draw(surf, t, (x + w + 6, y), PARCHMENT)
        x += w + 6 + f.width(t) + 12


@dataclass
class MenuItem:
    label: str
    action: Callable[[], Any] | None = None
    kind: str = "button"                       # button | toggle | slider | choice | label
    get: Callable[[], Any] | None = None
    set: Callable[[Any], None] | None = None
    choices: list[Any] = field(default_factory=list)
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.05
    enabled: bool = True
    hint: str = ""
    fmt: Callable[[Any], str] | None = None


class Menu:
    """Vertical menu navigated with any player's directions; supports mouse hover/click."""

    def __init__(self, app, items: list[MenuItem], width: int = 220, slot: int = 0, row_h: int = 14):
        self.app = app
        self.items = items
        self.sel = next((i for i, it in enumerate(items) if it.enabled and it.kind != "label"), 0)
        self.width = width
        self.row_h = row_h
        self.slot = slot
        self.origin = (0, 0)
        self._rects: list[pygame.Rect] = []

    def _step(self, d: int) -> None:
        n = len(self.items)
        for _ in range(n):
            self.sel = (self.sel + d) % n
            it = self.items[self.sel]
            if it.enabled and it.kind != "label":
                break
        self.app.audio.play("ui_move", 0.6)

    def _adjust(self, it: MenuItem, d: int) -> None:
        if it.kind == "toggle":
            it.set(not it.get())
        elif it.kind == "slider":
            it.set(round(clamp(it.get() + d * it.step, it.lo, it.hi) / it.step) * it.step)
        elif it.kind == "choice":
            idx = it.choices.index(it.get()) if it.get() in it.choices else 0
            it.set(it.choices[(idx + d) % len(it.choices)])
        else:
            return
        self.app.audio.play("ui_move", 0.5)

    def update(self) -> None:
        inp = self.app.input
        dx = dy = 0
        activate = back = False
        for s in range(max(1, inp.num_players)):
            p = inp.player(s)
            x, y = p.menu_dir()
            dx, dy = dx or x, dy or y
            activate |= "CONFIRM" in p.pressed
        if dy:
            self._step(dy)
        it = self.items[self.sel] if self.items else None
        if it and it.enabled:
            if dx and it.kind in ("toggle", "slider", "choice"):
                self._adjust(it, dx)
            if activate:
                if it.kind in ("toggle", "choice"):
                    self._adjust(it, 1)
                elif it.action:
                    self.app.audio.play("ui_confirm", 0.8)
                    it.action()
        # mouse
        mx, my = inp.mouse_pos
        for i, r in enumerate(self._rects):
            if r.collidepoint(mx, my) and self.items[i].enabled and self.items[i].kind != "label":
                if pygame.mouse.get_rel() != (0, 0) and self.sel != i:
                    self.sel = i
                if 1 in inp.mouse_pressed:
                    self.sel = i
                    cur = self.items[i]
                    if cur.kind in ("toggle", "choice"):
                        self._adjust(cur, 1)
                    elif cur.kind == "slider":
                        frac = clamp((mx - (r.right - 70)) / 64)
                        cur.set(round((cur.lo + frac * (cur.hi - cur.lo)) / cur.step) * cur.step)
                    elif cur.action:
                        self.app.audio.play("ui_confirm", 0.8)
                        cur.action()

    def value_text(self, it: MenuItem) -> str:
        if it.kind == "toggle":
            return "ON" if it.get() else "OFF"
        if it.kind == "slider":
            return f"{int(round((it.get() - it.lo) / (it.hi - it.lo) * 100))}%" if it.hi != it.lo else ""
        if it.kind == "choice":
            v = it.get()
            return it.fmt(v) if it.fmt else str(v)
        if it.fmt and it.get:
            return it.fmt(it.get())
        return ""

    def draw(self, surf: pygame.Surface, topleft: tuple[int, int]) -> None:
        f = self.app.font
        self.origin = topleft
        self._rects = []
        y = topleft[1]
        rh = self.row_h * f.scale
        for i, it in enumerate(self.items):
            r = pygame.Rect(topleft[0], y, self.width, rh)
            self._rects.append(r)
            sel = i == self.sel
            col = PARCHMENT if it.enabled else (90, 86, 100)
            if it.kind == "label":
                col = DIM
            if sel and it.enabled:
                pygame.draw.rect(surf, INK_2, r)
                pygame.draw.rect(surf, BRASS, (r.x, r.y, 2, r.h))
                col = (255, 244, 205)
            f.draw(surf, it.label, (r.x + 8, r.y + (rh - 8 * f.scale) // 2), col, None)
            vt = self.value_text(it)
            if it.kind == "slider":
                bw = 60
                bx = r.right - bw - 10
                by = r.centery - 2
                pygame.draw.rect(surf, (50, 46, 70), (bx, by, bw, 4))
                frac = (it.get() - it.lo) / max(1e-6, (it.hi - it.lo))
                pygame.draw.rect(surf, BRASS if sel else DIM, (bx, by, int(bw * clamp(frac)), 4))
            elif vt:
                tw = f.width(vt)
                f.draw(surf, vt, (r.right - tw - 8, r.y + (rh - 8 * f.scale) // 2), BRASS if sel else DIM, None)
            y += rh
        # hint of selected item
        if self.items and self.items[self.sel].hint:
            f.draw(surf, self.items[self.sel].hint, (topleft[0] + 4, y + 6), DIM, None)

    def height(self) -> int:
        return len(self.items) * self.row_h * self.app.font.scale


class MenuScene(Scene):
    """A titled, centred menu panel (overlay or full screen)."""

    def __init__(self, app, title: str, items_factory: Callable[[], list[MenuItem]], width: int = 230,
                 overlay: bool = True, footer: list[tuple[str, str]] | None = None, on_back: Callable | None = None):
        super().__init__(app)
        self.title = title
        self.items_factory = items_factory
        self.width = width
        self.opaque = not overlay
        self.menu = Menu(app, items_factory(), width)
        self.footer = footer or [("CONFIRM", "Select"), ("BACK", "Back")]
        self.on_back = on_back
        self.age = 0.0

    def rebuild(self) -> None:
        sel = self.menu.sel
        self.menu = Menu(self.app, self.items_factory(), self.width)
        self.menu.sel = min(sel, len(self.menu.items) - 1)

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.12:
            return
        self.menu.update()
        if any("BACK" in self.inp.player(s).pressed for s in range(max(1, self.inp.num_players))):
            self.app.audio.play("ui_back", 0.6)
            (self.on_back or self.app.scenes.pop)()

    def draw(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        if self.opaque:
            surf.fill(INK)
        else:
            dim = pygame.Surface((w, h), pygame.SRCALPHA)
            dim.fill((8, 6, 16, 170))
            surf.blit(dim, (0, 0))
        mh = self.menu.height() + 24 + (14 if self.menu.items and self.menu.items[self.menu.sel].hint else 0)
        rect = pygame.Rect((w - self.width) // 2 - 6, max(10, (h - mh) // 2 - 8), self.width + 12, mh + 16)
        k = ease_out_cubic(self.age / 0.15)
        rect.y += int((1 - k) * 10)
        draw_panel(surf, rect, title=self.title, font=self.app.font)
        self.menu.draw(surf, (rect.x + 6, rect.y + 12))
        draw_prompts(surf, self.app, self.footer)


class PauseMenu(MenuScene):
    def __init__(self, app, mode_scene):
        self.mode_scene = mode_scene
        super().__init__(app, "PAUSED", self._items, 200, overlay=True,
                         footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def _items(self) -> list[MenuItem]:
        return [
            MenuItem("Resume", self.app.scenes.pop),
            MenuItem("Settings", lambda: self.app.scenes.push(SettingsScene(self.app))),
            MenuItem("Controls", lambda: self.app.scenes.push(ControlsScene(self.app))),
            MenuItem("Leave shard (save)", self._leave),
        ]

    def _leave(self) -> None:
        self.app.scenes.pop()
        self.app.save_now()
        self.app.return_to_hub()


def _setting_items(app, rows: list[tuple]) -> list[MenuItem]:
    items: list[MenuItem] = []
    for row in rows:
        label, key, kind = row[0], row[1], row[2]
        extra = row[3] if len(row) > 3 else {}

        def getter(k=key):
            return app.settings.get(k)

        def setter(v, k=key):
            app.settings.set(k, v)
            app.apply_settings()
            if k.startswith("audio."):
                app.audio.play("ui_move", 0.7)

        items.append(MenuItem(label, kind=kind, get=getter, set=setter, **extra))
    return items


class SettingsScene(MenuScene):
    def __init__(self, app):
        super().__init__(app, "SETTINGS", self._items, 250, overlay=True)

    def _items(self) -> list[MenuItem]:
        a = self.app
        rows = [
            ("Master volume", "audio.master", "slider"),
            ("Music volume", "audio.music", "slider"),
            ("Effects volume", "audio.sfx", "slider"),
            ("Fullscreen", "video.fullscreen", "toggle"),
            ("Show FPS", "video.show_fps", "toggle"),
            ("Difficulty", "difficulty.preset", "choice", {"choices": ["story", "standard", "hard"]}),
            ("Adaptive AI strength", "difficulty.adaptive_ai", "slider", {"lo": 0.0, "hi": 1.5, "step": 0.1}),
        ]
        items = _setting_items(a, rows)
        items.append(MenuItem("Accessibility...", lambda: a.scenes.push(AccessibilityScene(a))))
        items.append(MenuItem("Back", a.scenes.pop))
        return items

    def update(self, dt: float) -> None:
        super().update(dt)

    def on_exit(self) -> None:
        self.app.settings.save()


class AccessibilityScene(MenuScene):
    def __init__(self, app):
        super().__init__(app, "ACCESSIBILITY", self._items, 270, overlay=True)

    def _items(self) -> list[MenuItem]:
        a = self.app
        rows = [
            ("Reduce screen shake", "access.reduce_shake", "toggle"),
            ("Reduce flashes", "access.reduce_flash", "toggle"),
            ("High-contrast UI", "access.high_contrast", "toggle"),
            ("Colour assist", "access.colorblind", "choice", {"choices": ["none", "protan", "deutan", "tritan"]}),
            ("Large text", "access.text_scale", "choice", {"choices": [1, 2], "fmt": lambda v: "ON" if v == 2 else "OFF"}),
            ("Hold inputs as toggles", "access.toggle_hold", "toggle"),
            ("Game speed", "access.game_speed", "slider", {"lo": 0.5, "hi": 1.0, "step": 0.05}),
            ("Aim assist", "access.aim_assist", "toggle"),
        ]
        items = _setting_items(a, rows)
        items.append(MenuItem("Back", a.scenes.pop))
        return items

    def on_exit(self) -> None:
        self.app.settings.save()


class ControlsScene(Scene):
    """Rebind keyboard schemes and the gamepad.  Press confirm on a row, then the new key/button."""
    opaque = False

    def __init__(self, app):
        super().__init__(app)
        self.schemes = ["kb1", "kb2", "pad"]
        self.si = 0
        self.sel = 0
        self.capturing: str | None = None
        self.age = 0.0
        self.message = ""

    def on_exit(self) -> None:
        self.app.input.end_capture()
        self.app.settings.save()

    def _bindings(self) -> dict[str, list[str]]:
        sch = self.schemes[self.si]
        if sch == "pad":
            if self.app.input.pads:
                return next(iter(self.app.input.pads.values())).bindings
            from .input import DEFAULT_BINDINGS
            return DEFAULT_BINDINGS["pad"]
        return self.app.input.keyboards[sch].bindings

    def update(self, dt: float) -> None:
        self.age += dt
        inp = self.app.input
        if self.capturing:
            cap = inp.captured
            if cap:
                kind, raw = cap
                sch = self.schemes[self.si]
                ok = (sch == "pad") == (kind == "gamepad")
                if ok and raw != "escape":
                    inp.rebind(sch, self.capturing, raw)
                    self.message = f"{self.capturing} -> {raw}"
                elif not ok:
                    self.message = "Wrong device for this scheme"
                inp.end_capture()
                self.capturing = None
                self.age = 0.0
            return
        if self.age < 0.15:
            return
        p = inp.player(0)
        dx, dy = p.menu_dir()
        n = len(REMAPPABLE)
        if dy:
            self.sel = (self.sel + dy) % (n + 2)
        if dx and self.sel < n + 2:
            self.si = (self.si + dx) % len(self.schemes)
        if "CONFIRM" in p.pressed:
            if self.sel < n:
                self.capturing = REMAPPABLE[self.sel]
                inp.begin_capture()
                self.message = f"Press new input for {self.capturing}..."
            elif self.sel == n:
                inp.reset_bindings()
                self.message = "Defaults restored"
            else:
                self.app.scenes.pop()
        if "BACK" in p.pressed:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((8, 6, 16, 200))
        surf.blit(dim, (0, 0))
        f = self.app.font
        rect = pygame.Rect(90, 14, 300, 232)
        draw_panel(surf, rect, title="CONTROLS", font=f)
        sch = self.schemes[self.si]
        names = {"kb1": "Keyboard A (WASD)", "kb2": "Keyboard B (Arrows)", "pad": "Gamepad"}
        f.draw(surf, f"< {names[sch]} >", (w // 2, rect.y + 14), LENS, anchor="midtop")
        b = self._bindings()
        y = rect.y + 30
        for i, btn in enumerate(REMAPPABLE):
            sel = i == self.sel
            if sel:
                pygame.draw.rect(surf, INK_2, (rect.x + 6, y - 1, rect.w - 12, 12))
            f.draw(surf, btn, (rect.x + 14, y), BRASS if sel else PARCHMENT, None)
            val = "press..." if self.capturing == btn else ", ".join(b.get(btn, []))
            f.draw(surf, val, (rect.x + 90, y), PARCHMENT if sel else DIM, None)
            y += 13
        n = len(REMAPPABLE)
        f.draw(surf, "Reset to defaults", (rect.x + 14, y + 4), BRASS if self.sel == n else PARCHMENT, None)
        f.draw(surf, "Back", (rect.x + 14, y + 17), BRASS if self.sel == n + 1 else PARCHMENT, None)
        if self.message:
            f.draw(surf, self.message, (w // 2, rect.bottom - 14), GOOD, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Rebind"), ("BACK", "Back")])


class Dialogue(Scene):
    """Modal text box with typewriter reveal. ``lines`` is a list of (speaker, text)."""
    opaque = False

    def __init__(self, app, lines: list[tuple[str, str]], color=BRASS, on_done: Callable | None = None):
        super().__init__(app)
        self.lines = lines
        self.i = 0
        self.t = 0.0
        self.color = color
        self.on_done = on_done
        self.age = 0.0

    def update(self, dt: float) -> None:
        self.age += dt
        self.t += dt * 55
        p = self.inp.player(0)
        text = self.lines[self.i][1]
        if self.age > 0.1 and p.any_pressed(("CONFIRM", "A")):
            if self.t < len(text):
                self.t = len(text)
            else:
                self.i += 1
                self.t = 0
                self.app.audio.play("ui_move", 0.4)
                if self.i >= len(self.lines):
                    self.app.scenes.pop()
                    if self.on_done:
                        self.on_done()
        elif "BACK" in p.pressed and self.age > 0.1:
            self.app.scenes.pop()
            if self.on_done:
                self.on_done()

    def draw(self, surf: pygame.Surface) -> None:
        if self.i >= len(self.lines):
            return
        f = self.app.font
        speaker, text = self.lines[self.i]
        w, h = surf.get_size()
        rect = pygame.Rect(30, h - 86, w - 60, 72)
        draw_panel(surf, rect, border=self.color, title=speaker or None, font=f)
        shown = text[:int(self.t)]
        f.draw_wrapped(surf, shown, pygame.Rect(rect.x + 10, rect.y + 12, rect.w - 20, rect.h - 16), PARCHMENT, None)
        if self.t >= len(text) and int(self.age * 3) % 2 == 0:
            f.draw(surf, "v", (rect.right - 14, rect.bottom - 14), self.color, None)
