"""Minimal HallFinale stub for the Grand Tour (replaced in Task 8)."""
from __future__ import annotations

from .legs import Leg


class HallFinale(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "hall"
        self.shard = "prism"
        self.state = "run"

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)

    def draw(self, surf):
        self._hud_band(surf, "Hall", "Fly")
