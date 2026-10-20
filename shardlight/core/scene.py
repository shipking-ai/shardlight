"""Scene stack and the contract every game mode implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pygame

if TYPE_CHECKING:
    from .app import App


class Scene:
    """Base class.  ``opaque`` scenes hide everything beneath them; overlays set it False."""

    opaque = True

    def __init__(self, app: "App"):
        self.app = app

    # lifecycle ----------------------------------------------------------------------------
    def on_enter(self, **kwargs: Any) -> None: ...
    def on_exit(self) -> None: ...
    def on_pause(self) -> None: ...       # another scene was pushed above this one
    def on_resume(self) -> None: ...      # the scene above was popped

    # per tick -----------------------------------------------------------------------------
    def update(self, dt: float) -> None: ...
    def draw(self, surf: pygame.Surface) -> None: ...

    def on_pad_lost(self, slot: int) -> None:
        """A controller owned by ``slot`` was unplugged; gameplay scenes should pause."""

    # convenience --------------------------------------------------------------------------
    @property
    def inp(self):
        return self.app.input

    @property
    def font(self):
        return self.app.font


@dataclass(frozen=True)
class ModeInfo:
    """Static description of a game mode (shard)."""
    id: str
    title: str
    genre: str
    tagline: str
    blurb: str
    color: tuple[int, int, int]          # signature colour (hub lens, UI accents)
    dark: tuple[int, int, int]           # deep shade of the palette
    max_players: int = 1
    music: str = ""                      # music track id (defaults to the mode id)
    controls: tuple[tuple[str, str], ...] = ()    # (button label, action) pairs shown on the shard card
    options: tuple[dict, ...] = ()       # launch options shown on the shard card, see hub.shard_card


class ModeScene(Scene):
    """Base for the root scene of a mode.  Subclasses set ``INFO`` and call ``finish`` to leave."""

    INFO: ModeInfo

    def __init__(self, app: "App", **opts: Any):
        super().__init__(app)
        self.opts = opts

    @property
    def mode_id(self) -> str:
        return self.INFO.id

    @property
    def data(self) -> dict:
        """This mode's private persistent JSON dict inside the active profile."""
        return self.app.world.mode_data(self.mode_id)

    def finish(self, **summary: Any) -> None:
        """Leave the mode for the hub, emitting ``<mode>.finished`` so echoes can react."""
        self.app.world.emit(f"{self.mode_id}.finished", **summary)
        self.app.save_now()
        self.app.return_to_hub()

    def open_pause_menu(self) -> None:
        from .ui import PauseMenu
        self.app.scenes.push(PauseMenu(self.app, self))


class SceneStack:
    def __init__(self, app: "App"):
        self.app = app
        self.stack: list[Scene] = []
        self._pending: list[tuple[str, Scene | None, dict]] = []
        # transition state
        self.fade = 0.0              # 0 clear .. 1 black
        self._fading_out = False
        self._queued: list[tuple[str, Scene | None, dict]] = []
        self.fade_speed = 5.0        # per second
        self.instant = False

    @property
    def top(self) -> Scene | None:
        return self.stack[-1] if self.stack else None

    # requests are queued and executed between ticks so scenes may safely call these in update()
    def push(self, scene: Scene, fade: bool = False, **kw: Any) -> None:
        self._queued.append(("push_fade" if fade else "push", scene, kw))

    def pop(self, fade: bool = False) -> None:
        self._queued.append(("pop_fade" if fade else "pop", None, {}))

    def replace(self, scene: Scene, fade: bool = True, **kw: Any) -> None:
        self._queued.append(("replace_fade" if fade else "replace", scene, kw))

    def reset_to(self, scene: Scene, fade: bool = True, **kw: Any) -> None:
        self._queued.append(("reset_fade" if fade else "reset", scene, kw))

    def _apply(self, op: str, scene: Scene | None, kw: dict) -> None:
        base = op.replace("_fade", "")
        if base == "push":
            if self.top:
                self.top.on_pause()
            self.stack.append(scene)
            scene.on_enter(**kw)
        elif base == "pop":
            if self.stack:
                old = self.stack.pop()
                old.on_exit()
                if self.top:
                    self.top.on_resume()
        elif base == "replace":
            if self.stack:
                self.stack.pop().on_exit()
            self.stack.append(scene)
            scene.on_enter(**kw)
        elif base == "reset":
            while self.stack:
                self.stack.pop().on_exit()
            self.stack.append(scene)
            scene.on_enter(**kw)

    def process(self, dt: float) -> None:
        """Run queued scene changes, animating fades for ``*_fade`` operations."""
        if self._fading_out:
            self.fade = min(1.0, self.fade + self.fade_speed * dt)
            if self.fade >= 1.0 or self.instant:
                op, scene, kw = self._pending.pop(0)
                self._apply(op, scene, kw)
                self._fading_out = False
            return
        if self.fade > 0:
            self.fade = max(0.0, self.fade - self.fade_speed * dt)
            if self.instant:
                self.fade = 0.0
        if self._queued:
            op, scene, kw = self._queued.pop(0)
            if op.endswith("_fade") and not self.instant:
                self._pending.append((op, scene, kw))
                self._fading_out = True
            else:
                self._apply(op, scene, kw)

    @property
    def transitioning(self) -> bool:
        return self._fading_out or bool(self._queued)

    def update(self, dt: float) -> None:
        if self._fading_out:
            return
        if self.top:
            self.top.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if not self.stack:
            surf.fill((0, 0, 0))
            return
        start = len(self.stack) - 1
        while start > 0 and not self.stack[start].opaque:
            start -= 1
        for sc in self.stack[start:]:
            sc.draw(surf)
        if self.fade > 0:
            ov = pygame.Surface(surf.get_size())
            ov.set_alpha(int(255 * min(1.0, self.fade)))
            surf.blit(ov, (0, 0))
