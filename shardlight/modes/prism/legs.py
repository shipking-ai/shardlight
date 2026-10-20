"""Leg contract for the Grand Tour."""
from __future__ import annotations

from ...core.scene import Scene


class Leg(Scene):
    """A single Grand Tour leg. Subclasses set ``state`` and implement update/draw."""

    def __init__(self, app, seed: int, config: dict):
        super().__init__(app)
        self.seed = int(seed)
        self.config = dict(config or {})
        self.state = "run"          # "run" | "won" | "lost"
        self.t = 0.0
        self.hud_t = 3.0            # control-reminder splash
        self.rng_seed = self.seed

    def update(self, dt: float) -> None: ...   # must set self.state
    def draw(self, surf) -> None: ...
    def debug_force_win(self) -> None:          # test-only
        self.state = "won"

    def _hud_band(self, surf, name: str, reminder: str) -> None:
        f = self.app.font
        if self.hud_t > 0:
            f.write(surf, reminder, 8, 8, (240, 235, 210))
        f.write(surf, name, 8, 252, (230, 200, 120))


class SpireLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "spire"
        self.shard = "cinder"
        self.height = int(config.get("height", 12))
        self.progress = 0
        self.target = self.height

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.progress += dt * 1.5
        if self.progress >= self.target:
            self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Spire", "Up climb")


class WispLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "wisp"
        self.shard = "verdant"
        self.clearing = list(config.get("clearing", [0, 0, 6, 4]))
        self.x = 0.0
        self.y = 0.0
        self.exit_x = 6.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.x += dt * 0.6
        if self.x >= self.exit_x:
            self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Wisp", "Carry the lamp")


class ShadowLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "crossing"
        self.shard = "umbra"
        self.beats = int(config.get("beats", 3))
        self.beat = 0
        self.t_beat = 0.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.t_beat += dt
        if self.t_beat >= 4.0:
            self.t_beat = 0.0
            self.beat += 1
            if self.beat >= self.beats:
                self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Crossing", "Stay unseen")


class LapLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "lap"
        self.shard = "slipstream"
        self.checkpoints = int(config.get("checkpoints", 6))
        self.cp = 0
        self.t_par = 40.0
        self.t_elapsed = 0.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.t_elapsed += dt
        if self.t_elapsed >= 3.0 and self.cp < self.checkpoints:
            self.t_elapsed = 0.0
            self.cp += 1
            if self.cp >= self.checkpoints and self.t <= self.t_par:
                self.state = "won"
        if self.t > self.t_par and self.state == "run":
            self.state = "lost"

    def draw(self, surf):
        self._hud_band(surf, "Lap", "Drive")


class DuelLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "duel"
        self.shard = "masks"
        self.rounds = int(config.get("rounds", 1))
        self.done_rounds = 0
        self.t_limit = 30.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        if self.t >= self.t_limit:
            self.done_rounds += 1
            self.t = 0.0
            if self.done_rounds >= self.rounds:
                self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Duel", "A confirm")


class BloomLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "bloom"
        self.shard = "terrace"
        self.clock_mul = int(config.get("clock_mul", 8))
        self.progress = 0.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.progress += dt * self.clock_mul * 0.05
        if self.progress >= 1.0:
            self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Bloom", "Wait for bloom")


class MarketLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "market"
        self.shard = "concord"
        self.start = int(config.get("start", 100))
        self.goal = int(config.get("goal", 140))
        self.turns = int(config.get("turns", 6))
        self.turn = 0
        self.ledger = self.start
        self.t_turn = 0.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.t_turn += dt
        if self.t_turn >= 2.0:
            self.t_turn = 0.0
            self.turn += 1
            self.ledger += 7
            if self.ledger >= self.goal:
                self.state = "won"
            if self.turn >= self.turns and self.state == "run":
                self.state = "lost"

    def draw(self, surf):
        self._hud_band(surf, "Market", "Trade")


class SwarmLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "swarm"
        self.shard = "orrery"
        self.wave = int(config.get("wave", 1))
        self.t_wave = 0.0
        self.survived = False

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.t_wave += dt
        if self.t_wave >= 15.0:
            self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Swarm", "Survive")


class HallFinale(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "hall"
        self.shard = "prism"

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)

    def draw(self, surf):
        self._hud_band(surf, "Hall", "Fly")
