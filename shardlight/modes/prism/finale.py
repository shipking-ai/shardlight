"""Hall finale: glide into the Lens, white-out, hand off to the epilogue."""
from __future__ import annotations

import math
import random

import pygame

from . import tri
from .legs import Leg
from .world import PALETTES

SHARD_ORDER = ("cinder", "verdant", "umbra", "slipstream", "masks", "terrace", "concord", "orrery")


class HallFinale(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "hall"
        self.shard = "prism"
        self.state = "glide"
        self.mesh = tri.HallMesh(debris=int((config or {}).get("debris", 40)))
        self.cam = tri.ChaseCam(yaw=0.0, pitch=-0.12, pos=(0.5, 3.0, -4.0),
                                target=(0.5, 2.5, 0.0), speed=4.0, smoothing=0.12)
        # debris positions (mirror HallMesh generation for collision)
        self.debris = []
        rng = random.Random(1234)
        n = int((config or {}).get("debris", 40))
        for _ in range(n):
            self.debris.append((
                rng.uniform(-5.5, 6.0),
                rng.uniform(0.0, 4.5),
                rng.uniform(1.0, 15.0),
                rng.uniform(0.15, 0.45),
            ))
        self.ship = [0.5, 2.5, -3.0]
        self.forward_speed = 2.0
        self.base_speed = 2.0
        self.shake = 0.0
        self.whiteout_t = 0.0
        self._replaced = False
        self._rng = random.Random(seed)

    def _near_debris(self) -> bool:
        sx, sy, sz = self.ship
        for dx, dy, dz, ds in self.debris:
            if abs(dz - sz) > 2.5:
                continue
            d = math.sqrt((sx - dx) ** 2 + (sy - dy) ** 2 + (sz - dz) ** 2)
            if d < (0.9 + ds):
                return True
        return False

    def update(self, dt):
        if dt is None:
            dt = 0.0
        dt = float(dt)
        if dt < 0:
            dt = 0.0
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)

        if self.state == "done":
            return

        if self.state == "whiteout":
            self.whiteout_t += dt
            if self.whiteout_t >= 2.0 and not self._replaced:
                self._replaced = True
                self.state = "done"
                from .epilogue import EpilogueScene
                self.app.scenes.replace(EpilogueScene(self.app), fade=True)
            return

        # glide
        near = self._near_debris()
        target_speed = self.base_speed * (0.4 if near else 1.0)
        self.forward_speed += (target_speed - self.forward_speed) * min(1.0, dt * 6.0)
        self.ship[2] += self.forward_speed * dt
        if near:
            self.shake = min(1.2, self.shake + dt * 4.0)
        else:
            self.shake = max(0.0, self.shake - dt * 2.5)

        self.cam.follow(self.ship, yaw=0.0, pitch=-0.12)
        self.cam.update(dt, target=self.ship)

        if self.ship[2] >= 13.5:
            self.state = "whiteout"
            self.whiteout_t = 0.0

    def draw(self, surf):
        if self.shake > 0:
            jx = (self._rng.random() - 0.5) * self.shake * 1.6
            jy = (self._rng.random() - 0.5) * self.shake * 1.0
            jz = (self._rng.random() - 0.5) * self.shake * 0.6
            cx, cy, cz = self.cam.pos
            render_cam = (self.cam.yaw, self.cam.pitch, (cx + jx, cy + jy, cz + jz))
        else:
            render_cam = self.cam
        tri.render(surf, self.mesh, render_cam, post=True)
        self._shard_streaks(surf)

        # 2D chrome
        w, h = surf.get_size()
        bar = 24
        pygame.draw.rect(surf, (0, 0, 0), (0, 0, w, bar))
        pygame.draw.rect(surf, (0, 0, 0), (0, h - bar, w, bar))
        f = self.app.font
        if self.hud_t > 0:
            f.draw(surf, "Fly the seam", (8, 8), (240, 235, 210), (0, 0, 0))
        f.draw(surf, "The Hall of the Lens", (8, h - 18), (230, 200, 120), (0, 0, 0))

        if self.state == "whiteout":
            alpha = min(1.0, self.whiteout_t / 2.0)
            overlay = pygame.Surface((w, h))
            overlay.fill((255, 255, 255))
            overlay.set_alpha(int(255 * alpha))
            surf.blit(overlay, (0, 0))
        elif self.state == "done":
            surf.fill((255, 255, 255))

    def _shard_streaks(self, surf) -> None:
        """The eight shard colours stream past the hull on the way to the Lens."""
        if self.state != "glide":
            return
        w, h = surf.get_size()
        for i, shard in enumerate(SHARD_ORDER):
            pal = PALETTES[shard]
            phase = (self.t * 0.35 + i * 0.12) % 1.0
            x = int((1.0 - phase) * (w + 60) - 30)
            y = int(h * 0.5 + math.sin(self.t * 1.3 + i) * h * 0.28)
            fade = int(90 * (1.0 - phase))
            if fade <= 2:
                continue
            streak = pygame.Surface((26, 3), pygame.SRCALPHA)
            streak.fill((*pal["accent"], fade))
            surf.blit(streak, (x, y))

    def debug_force_win(self):
        if self._replaced:
            return
        self._replaced = True
        self.state = "done"
        from .epilogue import EpilogueScene
        self.app.scenes.replace(EpilogueScene(self.app), fade=True)



