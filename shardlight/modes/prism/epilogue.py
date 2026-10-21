"""Epilogue scene for the Grand Tour: dialogue cards, credits scroll, final flag."""
from __future__ import annotations

from ...core.scene import ModeScene

CARDS = (
    "The Lamp holds.",
    "Eight shards, one light.",
    "The Tour is ended.",
)

CREDITS = (
    "THE GRAND TOUR",
    "",
    "Shard Cast",
    "Cinder  - Spire",
    "Verdant - Wisp",
    "Umbra   - Crossing",
    "Slipstream - Lap",
    "Masks   - Duel",
    "Terrace - Bloom",
    "Concord - Market",
    "Orrery  - Swarm",
    "",
    "Tour Roles",
    "Lampwright",
    "The Lens",
    "",
    "fin",
)


class EpilogueScene(ModeScene):
    INFO = None

    def __init__(self, app, **opts):
        super().__init__(app, **opts)
        self.app = app
        self._finished = False
        self.phase = "cards"  # cards | credits
        self.card_index = 0
        self.card_t = 0.0
        self.card_dur = 2.4
        self.credits_y = 270.0
        self.credits_speed = 30.0
        self._ensure_tour()

    def _ensure_tour(self) -> None:
        prof = self.app.world.profile
        prof.setdefault("tour", {"leg": 0, "done_legs": [], "done": False})
        tour = prof["tour"]
        tour.setdefault("leg", 0)
        tour.setdefault("done_legs", [])
        tour.setdefault("done", False)

    def debug_skip(self) -> None:  # test-only
        self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._ensure_tour()
        self.app.world.profile["tour"]["done"] = True
        self.app.save_now()
        self.app.return_to_hub()

    def update(self, dt: float) -> None:
        if self._finished:
            return
        if self.phase == "cards":
            self.card_t += dt
            p = self.app.inp.player(0)
            if self.card_t >= self.card_dur or "CONFIRM" in p.pressed or "A" in p.pressed:
                self.card_t = 0.0
                self.card_index += 1
                if self.card_index >= len(CARDS):
                    self.phase = "credits"
                    self.credits_y = 270.0
            return
        # credits
        self.credits_y -= self.credits_speed * dt
        total_h = len(CREDITS) * 12 + 40
        if self.credits_y <= -total_h:
            self._finish()
            return
        p = self.app.inp.player(0)
        if "CONFIRM" in p.pressed or "A" in p.pressed or "B" in p.pressed:
            self._finish()

    def draw(self, surf) -> None:
        surf.fill((8, 10, 20))
        f = self.app.font
        if self.phase == "cards":
            if 0 <= self.card_index < len(CARDS):
                text = CARDS[self.card_index]
                tw = f.width(text)
                f.draw(surf, text, ((480 - tw) // 2, 120), (240, 235, 210), (0, 0, 0))
        else:
            y = int(self.credits_y)
            for line in CREDITS:
                if line:
                    tw = f.width(line)
                    f.draw(surf, line, ((480 - tw) // 2, y), (230, 200, 120), (0, 0, 0))
                y += 12


from .info import INFO as _INFO
EpilogueScene.INFO = _INFO