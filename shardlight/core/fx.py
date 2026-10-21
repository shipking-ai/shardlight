"""Shared feel toolkit: easing, camera with trauma shake, hit-stop, particles, lighting, flashes.

Everything respects the accessibility settings via the ``Feel`` object (reduce_shake / reduce_flash).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

import pygame
from pygame.math import Vector2

# ---------------------------------------------------------------------------------------- easing

def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - clamp(t)) ** 3


def ease_in_out(t: float) -> float:
    t = clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float) -> float:
    c1, c3 = 1.70158, 2.70158
    t = clamp(t)
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def approach(cur: float, target: float, step: float) -> float:
    if cur < target:
        return min(cur + step, target)
    return max(cur - step, target)


def damp(cur: float, target: float, rate: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing."""
    return lerp(cur, target, 1 - math.exp(-rate * dt))


def mix(c1, c2, t: float):
    t = clamp(t)
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


# ---------------------------------------------------------------------------------------- feel

class Feel:
    """Per-session accessibility-aware global effects state."""

    def __init__(self) -> None:
        self.shake_scale = 1.0
        self.flash_scale = 1.0
        self.hitstop = 0              # frames remaining (modes may query to freeze simulation)
        self.flash_color = (255, 255, 255)
        self.flash_alpha = 0.0
        self.high_contrast = False

    def configure(self, settings) -> None:
        self.shake_scale = 0.0 if settings.get("access.reduce_shake") else 1.0
        self.flash_scale = 0.0 if settings.get("access.reduce_flash") else 1.0
        self.high_contrast = bool(settings.get("access.high_contrast"))

    def add_hitstop(self, frames: int) -> None:
        self.hitstop = max(self.hitstop, int(frames))

    def flash(self, color=(255, 255, 255), alpha: float = 0.5) -> None:
        if self.flash_scale > 0:
            self.flash_color = color
            self.flash_alpha = max(self.flash_alpha, alpha * self.flash_scale)

    def update(self) -> None:
        if self.hitstop > 0:
            self.hitstop -= 1
        self.flash_alpha = max(0.0, self.flash_alpha - 0.06)

    def draw_flash(self, surf: pygame.Surface) -> None:
        if self.flash_alpha > 0.01:
            ov = pygame.Surface(surf.get_size())
            ov.fill(self.flash_color)
            ov.set_alpha(int(255 * min(self.flash_alpha, 0.9)))
            surf.blit(ov, (0, 0))


FEEL = Feel()


# ---------------------------------------------------------------------------------------- camera

class Camera:
    """Smooth-follow camera with deadzone look-ahead, bounds and trauma-based shake."""

    def __init__(self, view_size=(480, 270), bounds: pygame.Rect | None = None, rate: float = 8.0):
        self.view = Vector2(view_size)
        self.pos = Vector2(0, 0)            # centre of view in world space
        self.target = Vector2(0, 0)
        self.bounds = bounds
        self.rate = rate
        self.trauma = 0.0
        self._t = 0.0
        self.offset = Vector2()
        self.zoom = 1.0

    def snap(self, p) -> None:
        self.pos = Vector2(p)
        self.target = Vector2(p)

    def follow(self, p, lookahead=(0, 0)) -> None:
        self.target = Vector2(p) + Vector2(lookahead)

    def add_trauma(self, amount: float) -> None:
        self.trauma = min(1.0, self.trauma + amount * FEEL.shake_scale)

    def update(self, dt: float) -> None:
        self.pos.x = damp(self.pos.x, self.target.x, self.rate, dt)
        self.pos.y = damp(self.pos.y, self.target.y, self.rate, dt)
        if self.bounds:
            hw, hh = self.view.x / 2, self.view.y / 2
            b = self.bounds
            lo_x, hi_x = b.left + hw, b.right - hw
            lo_y, hi_y = b.top + hh, b.bottom - hh
            self.pos.x = (b.centerx if lo_x > hi_x else clamp(self.pos.x, lo_x, hi_x))
            self.pos.y = (b.centery if lo_y > hi_y else clamp(self.pos.y, lo_y, hi_y))
        self._t += dt * 60
        s = self.trauma ** 2
        self.offset = Vector2(math.sin(self._t * 1.7) + math.sin(self._t * 3.1 + 1) * 0.5,
                              math.cos(self._t * 2.3) + math.sin(self._t * 2.9 + 2) * 0.5) * (6 * s)
        self.trauma = max(0.0, self.trauma - dt * 1.6)

    @property
    def top_left(self) -> Vector2:
        return Vector2(round(self.pos.x - self.view.x / 2 + self.offset.x),
                       round(self.pos.y - self.view.y / 2 + self.offset.y))

    def to_screen(self, p) -> Vector2:
        return Vector2(p) - self.top_left

    def to_world(self, p) -> Vector2:
        return Vector2(p) + self.top_left

    def visible_rect(self, margin: int = 0) -> pygame.Rect:
        tl = self.top_left
        return pygame.Rect(tl.x - margin, tl.y - margin, self.view.x + margin * 2, self.view.y + margin * 2)


# ---------------------------------------------------------------------------------------- glow cache

@lru_cache(maxsize=256)
def radial_gradient(radius: int, color: tuple, power: float = 2.0) -> pygame.Surface:
    """Soft light sprite: colour * falloff, for additive blending."""
    size = radius * 2
    s = pygame.Surface((size, size))
    for r in range(radius, 0, -1):
        k = (1 - r / radius) ** power
        pygame.draw.circle(s, tuple(int(c * k) for c in color), (radius, radius), r)
    return s


def blit_additive_glow(surf: pygame.Surface, pos, radius: int, color, power: float = 2.0) -> None:
    g = radial_gradient(int(radius), tuple(color), power)
    surf.blit(g, (int(pos[0]) - g.get_width() // 2, int(pos[1]) - g.get_height() // 2),
              special_flags=pygame.BLEND_RGB_ADD)


class Lighting:
    """Multiplicative light map. Draw the scene, then ``apply`` to darken by ambient and add lights."""

    def __init__(self, size=(480, 270), ambient=(40, 40, 60), downscale: int = 2):
        self.size = size
        self.ambient = ambient
        self.ds = downscale
        self.lights: list[tuple[Vector2, int, tuple, float]] = []
        self._map = pygame.Surface((size[0] // downscale, size[1] // downscale))

    def clear(self) -> None:
        self.lights.clear()

    def add(self, screen_pos, radius: int, color=(255, 220, 160), intensity: float = 1.0) -> None:
        self.lights.append((Vector2(screen_pos), radius, color, intensity))

    def apply(self, surf: pygame.Surface) -> None:
        self._map.fill(self.ambient)
        for pos, radius, color, inten in self.lights:
            c = tuple(min(255, int(v * inten)) for v in color)
            g = radial_gradient(max(2, radius // self.ds), c, 1.6)
            self._map.blit(g, (pos.x / self.ds - g.get_width() / 2, pos.y / self.ds - g.get_height() / 2),
                           special_flags=pygame.BLEND_RGB_ADD)
        big = pygame.transform.smoothscale(self._map, self.size)
        surf.blit(big, (0, 0), special_flags=pygame.BLEND_RGB_MULT)


# ---------------------------------------------------------------------------------------- particles

@dataclass(slots=True)
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color: tuple
    end_color: tuple
    gravity: float = 0.0
    drag: float = 0.0
    shrink: bool = True
    glow: int = 0
    shape: str = "square"          # square | line | ring


class ParticleSystem:
    """Capped CPU particle pool. Cheap enough for ~1500 live particles at 60 fps."""

    def __init__(self, cap: int = 1500, rng: random.Random | None = None):
        self.items: list[Particle] = []
        self.cap = cap
        self.rng = rng or random.Random(1)

    def emit(self, pos, count: int, speed=(20, 90), angle=(0, 360), life=(0.3, 0.7), size=(1, 3),
             color=(255, 200, 100), end_color=None, gravity=0.0, drag=0.0, glow=0, shape="square",
             shrink=True) -> None:
        r = self.rng
        for _ in range(count):
            if len(self.items) >= self.cap:
                return
            a = math.radians(r.uniform(*angle))
            sp = r.uniform(*speed)
            lf = r.uniform(*life)
            self.items.append(Particle(pos[0], pos[1], math.cos(a) * sp, math.sin(a) * sp, lf, lf,
                                       r.uniform(*size), color, end_color or color, gravity, drag, shrink,
                                       glow, shape))

    def burst_hit(self, pos, direction_deg: float, color=(255, 230, 180), count: int = 10) -> None:
        self.emit(pos, count, (60, 180), (direction_deg - 35, direction_deg + 35), (0.12, 0.3), (1, 2.5),
                  color, (255, 80, 40), drag=4, shape="line")

    def update(self, dt: float) -> None:
        keep: list[Particle] = []
        for p in self.items:
            p.life -= dt
            if p.life <= 0:
                continue
            if p.drag:
                k = max(0.0, 1 - p.drag * dt)
                p.vx *= k
                p.vy *= k
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            keep.append(p)
        self.items = keep

    def draw(self, surf: pygame.Surface, offset=(0, 0)) -> None:
        ox, oy = offset
        w, h = surf.get_size()
        for p in self.items:
            t = 1 - p.life / p.max_life
            x, y = p.x - ox, p.y - oy
            if x < -8 or y < -8 or x > w + 8 or y > h + 8:
                continue
            col = mix(p.color, p.end_color, t)
            size = p.size * (1 - t) if p.shrink else p.size
            if p.shape == "line":
                ln = max(1.0, size * 2)
                m = math.hypot(p.vx, p.vy) or 1
                pygame.draw.line(surf, col, (x, y), (x - p.vx / m * ln, y - p.vy / m * ln), 1)
            elif p.shape == "ring":
                pygame.draw.circle(surf, col, (x, y), max(1, int(size * 3 * t + 1)), 1)
            else:
                s = max(1, int(round(size)))
                surf.fill(col, (int(x) - s // 2, int(y) - s // 2, s, s))
            if p.glow:
                blit_additive_glow(surf, (x, y), p.glow, tuple(c // 3 for c in col))


# ---------------------------------------------------------------------------------------- misc

@dataclass
class FloatingText:
    text: str
    x: float
    y: float
    color: tuple = (255, 255, 255)
    life: float = 0.8
    age: float = 0.0
    rise: float = 24.0


class FloatingTexts:
    def __init__(self) -> None:
        self.items: list[FloatingText] = []

    def add(self, text: str, pos, color=(255, 255, 255), life: float = 0.8) -> None:
        if len(self.items) < 60:
            self.items.append(FloatingText(text, pos[0], pos[1], color, life))

    def update(self, dt: float) -> None:
        for t in self.items:
            t.age += dt
        self.items = [t for t in self.items if t.age < t.life]

    def draw(self, surf: pygame.Surface, font, offset=(0, 0)) -> None:
        for t in self.items:
            k = t.age / t.life
            y = t.y - t.rise * ease_out_cubic(k) - offset[1]
            col = mix(t.color, (0, 0, 0), max(0.0, (k - 0.7) / 0.3) * 0.7)
            font.draw(surf, t.text, (t.x - offset[0], y), col, (10, 10, 20), anchor="midbottom")


def vignette(size, strength: float = 0.5, color=(0, 0, 0)) -> pygame.Surface:
    """Cached by caller; darkens the edges."""
    w, h = size
    small = pygame.Surface((w // 4, h // 4), pygame.SRCALPHA)
    cx, cy = small.get_width() / 2, small.get_height() / 2
    maxd = math.hypot(cx, cy)
    for y in range(small.get_height()):
        for x in range(small.get_width()):
            d = math.hypot(x - cx, y - cy) / maxd
            a = int(255 * strength * clamp((d - 0.45) / 0.55) ** 1.5)
            small.set_at((x, y), (*color, a))
    return pygame.transform.smoothscale(small, size)


def scanlines(size, alpha: int = 28) -> pygame.Surface:
    s = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(0, size[1], 2):
        pygame.draw.line(s, (0, 0, 0, alpha), (0, y), (size[0], y))
    return s
