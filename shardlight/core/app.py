"""Application lifecycle: window, fixed-timestep loop, shared services, profile management."""
from __future__ import annotations

import importlib
import time
from collections import deque
from typing import Any

import numpy as np
import pygame

from . import log
from . import sfxlib  # noqa: F401  (registers shared sound-effect recipes)
from .audio import AudioManager
from .content import ContentDB
from .font import get_font
from .fx import FEEL
from .input import InputManager
from .mods import ModManager
from .paths import DATA_DIR, MODS_DIR
from .rng import Rng
from .save import SaveError, SaveManager, new_profile
from .scene import Scene, SceneStack
from .settings import Settings
from .world import ECHO_SCHEMA, Economy, World

LOG = log.get("app")

RENDER_SIZE = (480, 270)
TICK = 1 / 60.0
MAX_TICKS_PER_FRAME = 5

# Colour-assist matrices (applied to the final frame; approximate daltonisation).
COLORBLIND_MATRICES = {
    "protan": np.array([[0.567, 0.433, 0.0], [0.558, 0.442, 0.0], [0.0, 0.242, 0.758]]),
    "deutan": np.array([[0.625, 0.375, 0.0], [0.7, 0.3, 0.0], [0.0, 0.3, 0.7]]),
    "tritan": np.array([[0.95, 0.05, 0.0], [0.0, 0.433, 0.567], [0.0, 0.475, 0.525]]),
}

LORE_SCHEMA = {
    "title": {"type": "str", "required": True},
    "text": {"type": "str", "required": True},
    "shard": {"type": "str"},
    "tags": {"type": "list", "items": {"type": "str"}},
}


class App:
    def __init__(self, headless: bool = False, user_home: str | None = None, seed: int | None = None,
                 audio: bool = True):
        self.headless = headless
        self.running = False
        pygame.init()
        self.settings = Settings()
        self.settings.load()
        if not audio:
            self.settings.data["audio"]["enabled"] = False
        self.feel = FEEL
        self.feel.configure(self.settings)
        self.screen = self._create_window()
        self.frame = pygame.Surface(RENDER_SIZE).convert()
        self.font = get_font()
        self.font.scale = self.settings.get("access.text_scale")
        self.input = InputManager(self.settings)
        self.input.init_controllers()
        self.audio = AudioManager(self.settings)
        self.audio.init()
        self.saves = SaveManager()
        self.scenes = SceneStack(self)
        self.scenes.instant = headless
        self.rng = Rng(seed if seed is not None else int(time.time()))
        self.clock = pygame.time.Clock()
        # content & mods
        self.content = ContentDB()
        self.mods = ModManager(MODS_DIR)
        self.mode_modules: dict[str, Any] = {}
        self._load_content()
        # profile
        self.slot: int | None = None
        self.profile: dict | None = None
        self.world: World | None = None
        self.economy: Economy | None = None
        self._autosave_t = 0.0
        # toasts and diagnostics
        self.toasts: deque[dict] = deque(maxlen=6)
        self.frame_ms: deque[float] = deque(maxlen=240)
        self.update_ms: deque[float] = deque(maxlen=240)
        self.draw_ms: deque[float] = deque(maxlen=240)
        self.tick_count = 0
        self.frames_drawn = 0
        self.session_time = 0.0
        self._acc = 0.0
        self.debug = False
        self.screenshot_on_exit: str | None = None

    # ---------------------------------------------------------------------------- setup
    def _create_window(self) -> pygame.Surface:
        pygame.display.set_caption("SHARDLIGHT")
        if self.headless:
            return pygame.display.set_mode(RENDER_SIZE)
        flags = pygame.SCALED | pygame.RESIZABLE
        if self.settings.get("video.fullscreen"):
            flags |= pygame.FULLSCREEN
        try:
            screen = pygame.display.set_mode(RENDER_SIZE, flags, vsync=1 if self.settings.get("video.vsync") else 0)
        except pygame.error:
            screen = pygame.display.set_mode(RENDER_SIZE, flags)
        if not self.settings.get("video.fullscreen"):
            try:
                win = pygame.Window.from_display_module()
                scale = int(self.settings.get("video.window_scale"))
                win.size = (RENDER_SIZE[0] * scale, RENDER_SIZE[1] * scale)
                win.position = pygame.WINDOWPOS_CENTERED
            except Exception as exc:
                LOG.debug("could not size window: %s", exc)
        return screen

    def _load_content(self) -> None:
        from .. import modes as modes_pkg
        self.content.register_kind("echo", ECHO_SCHEMA)
        self.content.register_kind("lore", LORE_SCHEMA)
        for mid in modes_pkg.MODE_IDS:
            mod = modes_pkg.load(mid)
            if mod is None:
                continue
            self.mode_modules[mid] = mod
            if hasattr(mod, "register_content"):
                try:
                    mod.register_content(self.content)
                except Exception:
                    LOG.exception("mode %s failed to register content", mid)
        self.content.load_dir(DATA_DIR, "base")
        self.mods.discover()
        self.mods.apply(self.content)
        self.content.problems += [f"mods: {r}" for r in self.mods.report]
        self.content.problems += self.content.check_refs()
        for p in self.content.problems:
            LOG.warning("content: %s", p)

    @property
    def available_modes(self) -> list:
        infos = [m.INFO for m in self.mode_modules.values() if hasattr(m, "INFO")]
        return sorted(infos, key=lambda i: __import__("shardlight.modes", fromlist=["MODE_IDS"]).MODE_IDS.index(i.id))

    # ---------------------------------------------------------------------------- profiles
    def new_game(self, slot: int, name: str = "Lampwright") -> None:
        self.slot = slot
        self.profile = new_profile(name)
        self._bind_profile()
        for lid in ("the_lens", "night_of_edges", "lampwrights"):
            self.world.add_lore(lid)
        self.save_now()

    def load_game(self, slot: int) -> bool:
        try:
            self.profile = self.saves.read(slot)
        except SaveError as exc:
            LOG.error("load failed: %s", exc)
            self.toast("Could not load that save", (255, 120, 100))
            return False
        self.slot = slot
        self._bind_profile()
        for note in self.saves.recovered:
            self.toast(note, (255, 210, 120))
        self.saves.recovered.clear()
        return True

    def _bind_profile(self) -> None:
        self.world = World(self.profile, self.content)
        self.economy = Economy(self.world)

    def save_now(self) -> None:
        if self.profile is None or self.slot is None:
            return
        try:
            self.profile["playtime"] = self.profile.get("playtime", 0.0) + self.session_time
            self.session_time = 0.0
            self.saves.write(self.slot, self.profile)
        except OSError as exc:
            LOG.error("save failed: %s", exc)
            self.toast("Save failed - check disk space", (255, 120, 100))
        if self.settings.dirty:
            self.settings.save()

    def return_to_hub(self) -> None:
        from ..hub.hub import HubScene
        self.scenes.reset_to(HubScene(self), fade=True)

    def enter_mode(self, mode_id: str, **opts: Any) -> bool:
        mod = self.mode_modules.get(mode_id)
        if mod is None:
            self.toast("That shard is dormant", (200, 120, 120))
            return False
        self.economy.reset_session()
        scene = mod.create(self, **opts)
        self.world.emit(f"{mode_id}.entered")
        self.scenes.reset_to(scene, fade=True)
        return True

    # ---------------------------------------------------------------------------- ui helpers
    def toast(self, text: str, color=(240, 235, 210), seconds: float = 3.0) -> None:
        self.toasts.append({"text": text, "color": color, "t": seconds, "max": seconds})

    def apply_settings(self) -> None:
        self.feel.configure(self.settings)
        self.font.scale = int(self.settings.get("access.text_scale"))
        self.font._cache.clear()
        if not self.headless:
            want = bool(self.settings.get("video.fullscreen"))
            if want != bool(pygame.display.get_surface().get_flags() & pygame.FULLSCREEN):
                pygame.display.toggle_fullscreen()
        for dev in self.input.pads.values():
            dev.deadzone = float(self.settings.get("input.deadzone"))
            dev.trigger_threshold = float(self.settings.get("input.trigger_threshold"))

    # ---------------------------------------------------------------------------- main loop
    def tick(self, dt: float) -> None:
        """Advance exactly one fixed simulation step (also used directly by tests)."""
        t0 = time.perf_counter()
        self.input.begin_tick()
        for kind, slot in self.input.pop_notices():
            if kind == "pad_lost":
                self.toast(f"Controller for P{slot + 1} disconnected", (255, 180, 100), 4)
                top = self.scenes.top
                if top:
                    top.on_pad_lost(slot)
            else:
                self.toast(f"Controller connected for P{slot + 1}", (150, 230, 170))
        self.scenes.process(dt)
        self.scenes.update(dt)
        self.audio.update(dt)
        self.feel.update()
        if self.world:
            while self.world.toasts:
                self.toast(self.world.toasts.popleft(), (255, 232, 160))
            self.session_time += dt
            self._autosave_t += dt
            if self._autosave_t > 90 and not self.scenes.transitioning:
                self._autosave_t = 0
                self.save_now()
        for t in self.toasts:
            t["t"] -= dt
        while self.toasts and self.toasts[0]["t"] <= 0:
            self.toasts.popleft()
        self.tick_count += 1
        self.update_ms.append((time.perf_counter() - t0) * 1000)

    def render(self) -> None:
        t0 = time.perf_counter()
        self.scenes.draw(self.frame)
        self.feel.draw_flash(self.frame)
        self._draw_toasts(self.frame)
        if self.settings.get("video.show_fps") or self.debug:
            self._draw_fps(self.frame)
        self._postprocess(self.frame)
        self.screen.blit(self.frame, (0, 0))
        pygame.display.flip()
        self.frames_drawn += 1
        self.draw_ms.append((time.perf_counter() - t0) * 1000)

    def _postprocess(self, surf: pygame.Surface) -> None:
        mode = self.settings.get("access.colorblind")
        if mode == "none":
            return
        m = COLORBLIND_MATRICES[mode]
        arr = pygame.surfarray.pixels3d(surf)
        out = np.clip(arr.astype(np.float32) @ m.T, 0, 255).astype(np.uint8)
        arr[:] = out
        del arr

    def _draw_toasts(self, surf: pygame.Surface) -> None:
        y = 6
        for t in list(self.toasts)[-4:]:
            k = min(1.0, t["t"] / 0.4, (t["max"] - t["t"]) / 0.15 + 0.01)
            w = self.font.width(t["text"]) + 12
            h = self.font.line_height() + 6
            x = RENDER_SIZE[0] - w - 6 + int((1 - min(1.0, k)) * (w + 8))
            pygame.draw.rect(surf, (14, 14, 26), (x, y, w, h))
            pygame.draw.rect(surf, t["color"], (x, y, w, h), 1)
            pygame.draw.rect(surf, t["color"], (x, y, 2, h))
            self.font.draw(surf, t["text"], (x + 7, y + 3), t["color"], None)
            y += h + 3

    def _draw_fps(self, surf: pygame.Surface) -> None:
        if self.frame_ms:
            avg = sum(self.frame_ms) / len(self.frame_ms)
            txt = f"{1000 / max(avg, 0.01):.0f} fps  {avg:.1f}ms  upd {self.avg(self.update_ms):.2f}  drw {self.avg(self.draw_ms):.2f}"
            self.font.draw(surf, txt, (4, RENDER_SIZE[1] - 12), (160, 255, 160), (0, 0, 0), scale=1)

    @staticmethod
    def avg(d: deque) -> float:
        return sum(d) / len(d) if d else 0.0

    def handle_global_events(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_F11:
                    self.settings.set("video.fullscreen", not self.settings.get("video.fullscreen"))
                    self.apply_settings()
                elif e.key == pygame.K_F3:
                    self.debug = not self.debug
                elif e.key == pygame.K_F12 and not self.headless:
                    self.screenshot()

    def screenshot(self, path: str | None = None) -> str:
        from .paths import user_dir
        d = user_dir() / "screenshots"
        d.mkdir(exist_ok=True)
        p = path or str(d / f"shot_{int(time.time())}.png")
        pygame.image.save(self.frame, p)
        self.toast("Screenshot saved")
        return p

    def run(self, max_frames: int | None = None) -> None:
        self.running = True
        last = time.perf_counter()
        frames = 0
        try:
            while self.running and (max_frames is None or frames < max_frames):
                now = time.perf_counter()
                real_dt = min(0.25, now - last)
                last = now
                self.frame_ms.append(real_dt * 1000)
                events = pygame.event.get()
                self.handle_global_events(events)
                self.input.process(events)
                speed = float(self.settings.get("access.game_speed"))
                self._acc += real_dt * speed
                n = 0
                while self._acc >= TICK and n < MAX_TICKS_PER_FRAME:
                    self.tick(TICK)
                    self._acc -= TICK
                    n += 1
                if n == MAX_TICKS_PER_FRAME:
                    self._acc = 0.0
                self.input.end_frame()
                self.render()
                frames += 1
                if not self.headless:
                    self.clock.tick(240 if self.settings.get("video.vsync") else 120)
                if not self.scenes.stack:
                    self.running = False
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        try:
            if self.screenshot_on_exit:
                pygame.image.save(self.frame, self.screenshot_on_exit)
            self.save_now()
            self.settings.save()
        finally:
            self.audio.shutdown()
            pygame.quit()
