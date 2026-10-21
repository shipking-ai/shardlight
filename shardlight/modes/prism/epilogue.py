"""Epilogue scene for the Grand Tour: the eight lights come up, then the credits roll."""
from __future__ import annotations

import math

import pygame

from ...core.scene import ModeScene
from .world import PALETTES, ShardWorld

CARDS = (
    "The lamp holds.",
    "Eight shards, one light.",
    "The tour is ended.",
    "The Lens keeps listening.",
)

CREDITS = (
    "THE GRAND TOUR",
    "",
    "The Eight",
    "Cinder    - The Spire",
    "Verdant   - The Wisp Clearing",
    "Umbra     - The Gloaming Ward",
    "Slipstream- The Salt Cup",
    "Masks     - The Ring of Masks",
    "Terrace   - The Blossoming Terrace",
    "Concord   - The Ledger Hall",
    "Orrery    - The Orrery Dark",
    "",
    "The Cast",
    "Lampwright",
    "The Lens",
    "",
    "Thank you for carrying the light.",
)

SHARD_ORDER = ("cinder", "verdant", "umbra", "slipstream", "masks", "terrace", "concord", "orrery")
W, H = 480, 270


class EpilogueScene(ModeScene):
    INFO = None

    def __init__(self, app, **opts):
        super().__init__(app, **opts)
        self.app = app
        self._finished = False
        self.phase = "cards"  # cards | credits
        self.card_index = 0
        self.card_t = 0.0
        self.card_dur = 2.6
        self.credits_y = float(H)
        self.credits_speed = 26.0
        self.t = 0.0
        self.world = ShardWorld("prism", 99)
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
        self.t += dt
        if self.phase == "cards":
            self.card_t += dt
            p = self.app.inp.player(0)
            if self.card_t >= self.card_dur or "CONFIRM" in p.pressed or "A" in p.pressed:
                self.card_t = 0.0
                self.card_index += 1
                if self.card_index >= len(CARDS):
                    self.phase = "credits"
                    self.credits_y = float(H)
            return
        self.credits_y -= self.credits_speed * dt
        total_h = len(CREDITS) * 13 + 60
        if self.credits_y <= -total_h:
            self._finish()
            return
        p = self.app.inp.player(0)
        if "CONFIRM" in p.pressed or "A" in p.pressed or "B" in p.pressed:
            self._finish()

    # ------------------------------------------------------------------ look
    def _lights(self, surf, lit: int) -> None:
        """The eight shard lights along the horizon, one more lit with every card."""
        base_y = 186
        step = (W - 80) / (len(SHARD_ORDER) - 1)
        for i, shard in enumerate(SHARD_ORDER):
            x = 40 + i * step
            pal = PALETTES[shard]
            on = i < lit
            r = 7 if on else 5
            if on:
                glow = 0.65 + 0.35 * math.sin(self.t * 2.2 + i)
                for k in range(4, 0, -1):
                    pygame.draw.circle(surf, pal["accent"], (int(x), int(base_y)), int(r + k * 5 * glow), 1)
                pygame.draw.circle(surf, pal["light"], (int(x), int(base_y)), r)
            else:
                pygame.draw.circle(surf, (58, 54, 72), (int(x), int(base_y)), r, 1)
            f = self.app.font
            label = shard.capitalize()
            tw = f.width(label)
            f.draw(surf, label, (int(x - tw / 2), base_y + 12),
                   pal["light"] if on else (86, 82, 104), (0, 0, 0))

    def _draw(self, surf) -> None:
        self.world.backdrop(surf, self.t)
        self.world.midground(surf, self.t)
        self.world.ground(surf, self.t)

    def draw(self, surf) -> None:
        f = self.app.font
        if self.phase == "cards":
            self._draw(surf)
            lit = min(len(SHARD_ORDER), self.card_index + 2)
            self._lights(surf, lit)
            text = CARDS[min(self.card_index, len(CARDS) - 1)]
            tw = f.width(text)
            # the card fades in
            age = min(1.0, self.card_t / 0.5)
            col = (int(240 * age), int(235 * age), int(210 * age))
            f.draw(surf, text, ((W - tw) // 2, 96), col, (0, 0, 0))
            hint = "CONFIRM to continue"
            hw = f.width(hint)
            f.draw(surf, hint, ((W - hw) // 2, 118), (110, 106, 132), (0, 0, 0))
            self.world.particles(surf, self.t)
            self.world.grade(surf)
            return

        # credits: the lamp rises over the Hall while the names roll
        self._draw(surf)
        self._lights(surf, len(SHARD_ORDER))
        y = int(self.credits_y)
        for line in CREDITS:
            if line:
                tw = f.width(line)
                col = (232, 200, 128) if line.isupper() else (226, 222, 210)
                f.draw(surf, line, ((W - tw) // 2, y), col, (0, 0, 0))
            y += 13
        self.world.particles(surf, self.t)
        self.world.grade(surf)


from .info import INFO as _INFO
EpilogueScene.INFO = _INFO
