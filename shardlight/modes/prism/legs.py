"""The eight Grand Tour legs.

Every leg is a short, playable vignette built on one shared frame: you carry the
Lampwright's lamp through a shard you already know, and the lamp only moves when
you push it.

Leg contract (the tour depends on it):

* ``update(dt)`` advances ``self.progress`` from 0 to 1 and ends the leg by
  setting ``self.state`` to ``"won"`` or ``"lost"``.
* ``draw(surf)`` shows the objective, a progress bar and the lamp.
* The player pushes the lamp by holding CONFIRM (or A).
* ``BACK`` leaves the tour - a leg can never trap the player.
"""
from __future__ import annotations

import math
import random

import pygame

from ...core.scene import Scene
from .world import ShardWorld

INK = (14, 12, 30)
PAPER = (238, 232, 210)
GOLD = (232, 198, 120)
DIM = (150, 146, 176)
LAMP = (255, 226, 168)
DANGER = (214, 96, 84)
W, H = 480, 270
PATH_Y = 214          # the line the lamp-bearer walks
PATH_X0 = 44
PATH_X1 = W - 44


class Leg(Scene):
    """One leg of the tour.  Subclasses implement ``_update_leg`` and the copy."""

    title = "Leg"
    objective = "Push the lamp onward"
    hint = "Hold CONFIRM to push the lamp"
    shard = "prism"
    rate = 0.14          # progress per second while the lamp is pushed
    drift = 0.015        # progress per second while idle (nobody gets stuck)
    par = 75.0           # seconds before the leg is lost
    leg_number = 1
    legs_total = 8

    def __init__(self, app, seed: int, config: dict):
        super().__init__(app)
        self.seed = int(seed)
        self.config = dict(config or {})
        self.state = "run"          # "run" | "won" | "lost"
        self.t = 0.0
        self.hud_t = 4.0            # splash time for the objective
        self.rng_seed = self.seed
        self.rng = random.Random(self.seed)
        self.progress = 0.0
        self.holding = False
        self.flash = 0.0
        self.world = ShardWorld(self.shard, self.seed)

    # ------------------------------------------------------------------ input
    def _player(self):
        return self.inp.player(0)

    def _pushing(self) -> bool:
        p = self._player()
        return ("CONFIRM" in p.down) or ("A" in p.down)

    def _tapped(self) -> bool:
        p = self._player()
        return ("CONFIRM" in p.pressed) or ("A" in p.pressed)

    # ------------------------------------------------------------------ loop
    def update(self, dt: float) -> None:
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        self.flash = max(0.0, self.flash - dt * 2.0)
        self.holding = self._pushing()
        self._update_leg(dt)
        if self.state != "run":
            return
        if self.progress >= 1.0:
            self.progress = 1.0
            self.state = "won"
        elif self.t > self.par:
            self.state = "lost"

    def _update_leg(self, dt: float) -> None:
        self.progress += (self.rate if self.holding else self.drift) * dt

    def debug_force_win(self) -> None:          # test-only
        self.progress = 1.0
        self.state = "won"

    # ------------------------------------------------------------------ look
    def _path_x(self) -> float:
        """Where the lamp-bearer walks: the progress of the leg along the path."""
        return PATH_X0 + (PATH_X1 - PATH_X0) * max(0.0, min(1.0, self.progress))

    def _scene(self, surf) -> None:
        """Paint the shard this leg belongs to."""
        w = self.world
        w.backdrop(surf, self.t)
        w.midground(surf, self.t)
        w.ground(surf, self.t)

    def _bearer(self, surf) -> None:
        """The lamp-bearer and the pool of light the lamp throws."""
        x = self._path_x()
        self.world.lamp_light(surf, x, PATH_Y, 74.0)
        self.world.traveller(surf, x, PATH_Y, self.t, self.holding)

    def _finish_frame(self, surf) -> None:
        self.world.particles(surf, self.t)
        self.world.grade(surf)

    def _backdrop(self, surf) -> None:
        surf.fill(INK)
        # a slow drift of stars so the scene is never static
        for i in range(48):
            x = (i * 97 + self.t * (6 + i % 5)) % (W + 20) - 10
            y = (i * 53) % H
            a = 40 + 60 * (0.5 + 0.5 * math.sin(self.t * 1.7 + i))
            c = int(a)
            pygame.draw.circle(surf, (c, c, int(c * 1.15)), (int(x), int(y)), 1)

    def _lamp(self, surf, x: float, y: float, r: float = 7.0) -> None:
        glow = 0.6 + 0.4 * math.sin(self.t * 3.0)
        for k in range(5, 0, -1):
            rr = r + k * 5 * glow
            pygame.draw.circle(surf, (40, 34, 26), (int(x), int(y)), int(rr), 1)
        pygame.draw.circle(surf, LAMP, (int(x), int(y)), int(r))
        pygame.draw.circle(surf, (255, 250, 230), (int(x), int(y)), max(2, int(r * 0.45)))

    def _bar(self, surf, y: int, value: float, color=GOLD) -> None:
        x0, x1 = PATH_X0, PATH_X1
        pygame.draw.rect(surf, (44, 40, 62), (x0, y, x1 - x0, 8))
        pygame.draw.rect(surf, color, (x0, y, int((x1 - x0) * max(0.0, min(1.0, value))), 8))
        pygame.draw.rect(surf, (70, 64, 96), (x0, y, x1 - x0, 8), 1)

    def _hud(self, surf) -> None:
        f = self.app.font
        f.draw(surf, f"THE GRAND TOUR   {self.leg_number}/{self.legs_total}", (10, 8), DIM, (0, 0, 0))
        f.draw(surf, self.title, (10, H - 22), GOLD, (0, 0, 0))
        if self.hud_t > 0:
            f.draw(surf, self.objective, (10, 22), PAPER, (0, 0, 0))
            f.draw(surf, "BACK leaves the tour", (10, 36), DIM, (0, 0, 0))

    def _hud_band(self, surf, name: str, reminder: str) -> None:
        """Kept for compatibility with the old scaffold legs."""
        self.title = name
        self.objective = reminder
        self._hud(surf)


class SpireLeg(Leg):
    """Cinder: climb the Spire with the lamp in your teeth."""

    title = "Spire"
    objective = "Climb. The lamp burns brighter the higher you get."
    hint = "Hold CONFIRM to climb"
    shard = "cinder"
    rate = 0.16
    par = 60.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "spire"
        self.embers: list[tuple[float, float, float]] = []

    def _update_leg(self, dt: float) -> None:
        self.progress += (self.rate if self.holding else self.drift) * dt
        if self.holding and self.rng.random() < dt * 26:
            self.embers.append((self.rng.uniform(40, W - 40), float(H - 6), self.rng.uniform(0.4, 1.0)))
        self.embers = [(x, y - 40 * s * dt, s) for (x, y, s) in self.embers]

    def draw(self, surf) -> None:
        self._scene(surf)
        for (x, y, s) in self.embers:
            pygame.draw.circle(surf, (250, 150 + int(80 * s), 70), (int(x), int(y)), max(1, int(2 * s)))
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)


class WispLeg(Leg):
    """Verdant: carry the wisp across the clearing; the wind pushes back."""

    title = "Wisp"
    objective = "Carry the wisp. The wind will push you back."
    hint = "Hold CONFIRM to push into the wind"
    shard = "verdant"
    rate = 0.13
    drift = -0.02
    par = 70.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "wisp"
        self.gust = 0.0

    def _update_leg(self, dt: float) -> None:
        self.gust = 0.5 + 0.5 * math.sin(self.t * 1.3)
        self.progress += ((self.rate if self.holding else 0.0) + self.drift * self.gust) * dt
        self.progress = max(0.0, self.progress)

    def draw(self, surf) -> None:
        self._scene(surf)
        for i in range(14):
            x = (i * 61 + self.t * 140 * (0.4 + self.gust)) % (W + 40) - 20
            pygame.draw.line(surf, (120, 150, 120), (int(x), 40 + i * 6), (int(x + 26), 40 + i * 6), 1)
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)


class ShadowLeg(Leg):
    """Umbra: the lamp must stay lit, but the watcher hates the light."""

    title = "Crossing"
    objective = "Keep the lamp lit - but the watcher hates the light."
    hint = "Hold to climb, release to let the heat fade"
    shard = "umbra"
    rate = 0.15
    drift = 0.0
    par = 60.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "crossing"
        self.heat = 0.0
        self.watcher = 0.0

    def _update_leg(self, dt: float) -> None:
        self.heat = max(0.0, self.heat + (0.20 if self.holding else -0.25) * dt)
        if self.heat >= 1.0:
            self.watcher = min(1.0, self.watcher + dt * 0.5)
        else:
            self.watcher = max(0.0, self.watcher - dt * 0.35)
        if self.holding and self.heat < 0.9:
            self.progress += 0.17 * dt
        if self.watcher >= 1.0:
            self.state = "lost"

    def draw(self, surf) -> None:
        self._scene(surf)
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((4, 6, 12, 205))
        surf.blit(veil, (0, 0))
        for i in range(30):
            x = (i * 71 + self.t * 20) % (W + 20) - 10
            pygame.draw.circle(surf, (40, 46, 58), (int(x), (i * 37) % H), 2)
        self._bar(surf, PATH_Y + 10, self.progress)
        self._bar(surf, PATH_Y + 24, self.heat, DANGER)
        x = self._path_x()
        self.world.lamp_light(surf, x, PATH_Y, 58.0 + 26.0 * self.heat)
        self.world.traveller(surf, x, PATH_Y, self.t, self.holding)
        self._finish_frame(surf)
        self._hud(surf)


class LapLeg(Leg):
    """Slipstream: keep the lamp lit through the corner."""

    title = "Lap"
    objective = "Take the Salt Cup corner with the lamp still burning."
    hint = "Hold CONFIRM to drive"
    shard = "slipstream"
    rate = 0.12
    par = 70.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "lap"
        self.speed = 0.0

    def _update_leg(self, dt: float) -> None:
        self.speed += ((1.0 if self.holding else 0.25) - self.speed) * min(1.0, dt * 3.0)
        self.progress += self.rate * self.speed * dt

    def draw(self, surf) -> None:
        self._scene(surf)
        for i in range(9):
            y = 60 + i * 20
            off = int((self.t * 240 * self.speed) % 60)
            pygame.draw.line(surf, (150, 150, 190), (0, y + off), (W, y + off - 40), 1)
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)


class DuelLeg(Leg):
    """Masks: strike on the beat.  A marker sweeps; hit it in the bright band."""

    title = "Duel"
    objective = "Strike on the beat. Three clean parries."
    hint = "Press CONFIRM when the marker is in the bright band"
    shard = "masks"
    par = 70.0

    BAND = (0.42, 0.58)

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "duel"
        self.hits = 0
        self.misses = 0
        self.needed = 3
        self.sweep = 0.0
        self.mark = 0.0
        self.hit_flash = 0.0

    def _update_leg(self, dt: float) -> None:
        self.sweep = (self.sweep + dt * 0.55) % 1.0
        self.mark = self.sweep
        self.hit_flash = max(0.0, self.hit_flash - dt * 2.0)
        if self._tapped():
            lo, hi = self.BAND
            if lo <= self.mark <= hi:
                self.hits += 1
                self.hit_flash = 1.0
                self.progress = min(1.0, self.hits / self.needed)
                if self.hits >= self.needed:
                    self.state = "won"
            else:
                self.misses += 1
        # a miss costs time, not progress
        self.progress = max(0.0, self.progress - 0.0)

    def draw(self, surf) -> None:
        self._scene(surf)
        lo, hi = self.BAND
        x0, x1 = 60, W - 60
        pygame.draw.rect(surf, (60, 56, 84), (x0, 120, x1 - x0, 22))
        pygame.draw.rect(surf, (180, 165, 105), (x0 + (x1 - x0) * lo, 118, (x1 - x0) * (hi - lo), 26), 2)
        mx = x0 + (x1 - x0) * self.mark
        pygame.draw.rect(surf, LAMP if self.hit_flash <= 0 else (255, 255, 255), (mx - 3, 112, 6, 38))
        f = self.app.font
        f.draw(surf, f"parries {self.hits}/{self.needed}", (10, 96), PAPER, (0, 0, 0))
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)


class BloomLeg(Leg):
    """Terrace: wait for the bloom, then strike while it is open."""

    title = "Bloom"
    objective = "Wait for the bloom, then press while it is open."
    hint = "Press CONFIRM when the meter is in the green"
    shard = "terrace"
    par = 70.0

    WINDOW = (0.72, 0.9)

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "bloom"
        self.meter = 0.0
        self.blooms = 0
        self.misses = 0
        self.needed = 2
        self.phase = 0.0

    def _update_leg(self, dt: float) -> None:
        self.phase += dt * 0.35
        self.meter = (math.sin(self.phase) * 0.5 + 0.5)
        if self._tapped():
            lo, hi = self.WINDOW
            if lo <= self.meter <= hi:
                self.blooms += 1
                self.progress = min(1.0, self.blooms / self.needed)
                self.phase = 0.0
                self.meter = 0.5          # the meter restarts closed
                if self.blooms >= self.needed:
                    self.state = "won"
            else:
                self.misses += 1
                self.phase = 0.0
                self.meter = 0.5

    def draw(self, surf) -> None:
        self._scene(surf)
        lo, hi = self.WINDOW
        x0, x1 = 60, W - 60
        pygame.draw.rect(surf, (46, 60, 44), (x0, 120, x1 - x0, 22))
        pygame.draw.rect(surf, (140, 215, 140), (x0 + (x1 - x0) * lo, 118, (x1 - x0) * (hi - lo), 26), 2)
        mx = x0 + (x1 - x0) * self.meter
        pygame.draw.rect(surf, (255, 240, 200), (mx - 3, 112, 6, 38))
        f = self.app.font
        f.draw(surf, f"blooms {self.blooms}/{self.needed}", (10, 96), PAPER, (0, 0, 0))
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)


class MarketLeg(Leg):
    """Concord: trade the lamp up to the goal before the ledger closes."""

    title = "Market"
    objective = "Trade the lamp up to 140 before the ledger closes."
    hint = "Press CONFIRM to trade (8 turns)"
    shard = "concord"
    par = 70.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "market"
        self.start = int(config.get("start", 100))
        self.goal = int(config.get("goal", 140))
        self.turns = int(config.get("turns", 8))
        self.turn = 0
        self.ledger = self.start
        self.trade = 7

    def _update_leg(self, dt: float) -> None:
        if self._tapped() and self.turn < self.turns:
            self.turn += 1
            self.ledger += self.trade
            if self.ledger >= self.goal:
                self.progress = 1.0
                self.state = "won"
                return
            if self.turn >= self.turns:
                self.state = "lost"
                return
        self.progress = max(0.0, (self.ledger - self.start) / max(1, self.goal - self.start))

    def draw(self, surf) -> None:
        self._scene(surf)
        f = self.app.font
        f.draw(surf, f"ledger {self.ledger} / {self.goal}", (10, 96), PAPER, (0, 0, 0))
        f.draw(surf, f"turns {self.turn}/{self.turns}", (10, 108), DIM, (0, 0, 0))
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)


class SwarmLeg(Leg):
    """Orrery: survive the wave of lights with the lamp in the hull."""

    title = "Swarm"
    objective = "Hold the line for fifteen seconds."
    hint = "Move with the stick, hold CONFIRM to fire"
    shard = "orrery"
    par = 70.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "swarm"
        self.ship_x = 120.0
        self.lights: list[tuple[float, float]] = []
        self.spawn_t = 0.0
        self.shots = 0

    def _update_leg(self, dt: float) -> None:
        p = self._player()
        self.ship_x = max(40.0, min(W - 40.0, self.ship_x + p.move.x * 160.0 * dt))
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = max(0.5, 1.6 - self.progress)
            self.lights.append((float(W + 10), self.rng.uniform(60.0, H - 60.0)))
        if self.holding and self.lights:
            # the lamp-lance takes the nearest light
            best, bi = 1e18, -1
            for i, (x, y) in enumerate(self.lights):
                d = (x - self.ship_x) ** 2 + (y - H / 2) ** 2
                if d < best:
                    best, bi = d, i
            if bi >= 0 and best ** 0.5 < 340.0:
                self.lights.pop(bi)
                self.shots += 1
        moved: list[tuple[float, float]] = []
        for (x, y) in self.lights:
            x -= 120.0 * dt
            if x < self.ship_x - 26:
                self.state = "lost"
                return
            moved.append((x, y))
        self.lights = moved
        self.progress = min(1.0, self.t / 15.0)
        if self.progress >= 1.0:
            self.state = "won"

    def draw(self, surf) -> None:
        self._scene(surf)
        for (x, y) in self.lights:
            pygame.draw.circle(surf, DANGER, (int(x), int(y)), 5)
        pygame.draw.circle(surf, LAMP, (int(self.ship_x), int(H / 2)), 8)
        f = self.app.font
        f.draw(surf, f"survived {int(self.t)}s", (10, 96), PAPER, (0, 0, 0))
        self._bar(surf, PATH_Y + 18, self.progress)
        self._finish_frame(surf)
        self._hud(surf)


class HallFinale(Leg):
    """The Hall itself: a place to stand before the epilogue."""

    title = "Hall"
    objective = "The Hall is lit. Walk on."
    hint = "Hold CONFIRM to walk on"
    shard = "prism"
    rate = 0.2
    par = 30.0

    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "hall"

    def draw(self, surf) -> None:
        self._scene(surf)
        self._bar(surf, PATH_Y + 18, self.progress)
        self._bearer(surf)
        self._finish_frame(surf)
        self._hud(surf)
