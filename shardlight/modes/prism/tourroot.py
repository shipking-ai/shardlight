"""Sequences the Grand Tour legs, owns the retry overlay, persists progress."""
from __future__ import annotations

from ...core.scene import ModeScene
from ...core import log
from . import tourspec

LOG = log.get("prism.tourroot")


class TourRoot(ModeScene):
    INFO = None  # set at bottom to avoid circular import

    def __init__(self, app, **opts):
        super().__init__(app, **opts)
        self.app = app
        self.leg = None
        tour, problems = tourspec.load(app)
        if problems:
            app.toast("The Lens is clouded", (200, 120, 120))
            app.return_to_hub()
            self._broken = True
            return
        self._broken = False
        self.tour_data = tour
        self.legs_spec = tour["legs"]
        prof = app.world.profile.setdefault("tour", {"leg": 0, "done_legs": [], "done": False})
        prof.setdefault("leg", 0)
        prof.setdefault("done_legs", [])
        prof.setdefault("done", False)
        self.prof = prof
        self.leg_index = int(prof.get("leg", 0))
        self.leg_index = max(0, min(self.leg_index, len(self.legs_spec)))
        self.state = "run"          # run | retry | done
        self.overlay_t = 0.0
        self._start_leg()

    def _start_leg(self) -> None:
        spec = self.legs_spec[self.leg_index] if self.leg_index < len(self.legs_spec) else None
        if spec is None:
            self._finish()
            return
        cls = tourspec.LEG_CLASSES[spec["kind"]]
        self.leg = cls(self.app, spec["seed"], spec["config"])
        self.leg.id = spec["id"]
        self.leg.shard = spec["shard"]
        self.state = "run"

    def update(self, dt: float) -> None:
        if getattr(self, "_broken", False):
            return
        if self.state == "retry":
            self.overlay_t += dt
            p = self.app.inp.player(0)
            if "CONFIRM" in p.pressed or "A" in p.pressed:
                self._retry()
            elif "B" in p.pressed:
                self._abort_to_hub()
            return
        if self.state == "done":
            return
        self.leg.update(dt)
        if self.leg.state == "won":
            self._on_win()
        elif self.leg.state == "lost":
            self.state = "retry"
            self.overlay_t = 0.0

    def _on_win(self) -> None:
        spec = self.legs_spec[self.leg_index]
        lid = spec["id"]
        if lid not in self.prof["done_legs"]:
            self.prof["done_legs"].append(lid)
        self.prof["leg"] = self.leg_index + 1
        self.app.save_now()
        self.leg_index += 1
        if self.leg_index >= len(self.legs_spec):
            self._start_finale()
        else:
            self._start_leg()

    def _start_finale(self) -> None:
        from .finale import HallFinale
        self.app.scenes.replace(HallFinale(self.app, self.tour_data["finale"]["seed"],
                                          self.tour_data["finale"]["config"]), fade=True)

    def _retry(self) -> None:
        self.state = "run"
        self._start_leg()

    def _abort_to_hub(self) -> None:
        self.app.return_to_hub()

    def _finish(self) -> None:
        self.prof["done"] = True
        self.app.save_now()
        from .epilogue import EpilogueScene
        self.app.scenes.replace(EpilogueScene(self.app), fade=True)

    def draw(self, surf) -> None:
        if getattr(self, "_broken", False):
            return
        if self.state == "retry":
            self.leg.draw(surf)
            self._draw_retry_overlay(surf)
            return
        if self.leg is not None:
            self.leg.draw(surf)

    def _draw_retry_overlay(self, surf) -> None:
        import pygame
        w, h = surf.get_size()
        panel = pygame.Surface((360, 120), pygame.SRCALPHA)
        panel.fill((120, 90, 40, 210))
        surf.blit(panel, ((w - 360) // 2, (h - 120) // 2))
        f = self.app.font
        f.draw(surf, "The seam closes... again?", (w - 300) // 2, (h - 120) // 2 + 16, (255, 235, 180), (0, 0, 0))
        f.draw(surf, "CONFIRM retry   BACK to hub", (w - 260) // 2, (h - 120) // 2 + 72, (240, 235, 210), (0, 0, 0))


from .info import INFO as _INFO
TourRoot.INFO = _INFO
