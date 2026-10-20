"""Procedural art helpers shared by every mode: palettes, ramps, outlines, dithering, prisms, sprite baking.

Art rules (see docs/ART_BIBLE.md): 480x270 internal resolution, 1px dark outlines on characters, three-step
ramps (shadow / base / light) with a consistent top-left light, warm light vs cool shadow, no antialiasing.
"""
from __future__ import annotations

import math
from functools import lru_cache

import pygame

from .fx import blit_additive_glow, clamp, mix

Color = tuple[int, int, int]


def shade(c: Color, k: float) -> Color:
    """k<0 darkens toward a cool shadow, k>0 lightens toward a warm highlight."""
    if k < 0:
        return mix(c, (14, 12, 34), min(1.0, -k))
    return mix(c, (255, 244, 214), min(1.0, k))


def ramp(c: Color, steps: int = 4) -> list[Color]:
    """Dark-to-light ramp around base colour ``c`` (cool shadows, warm highlights)."""
    out = []
    for i in range(steps):
        k = (i - (steps - 2)) / max(1, steps - 1) * 0.9
        out.append(shade(c, k))
    return out


def outline(surf: pygame.Surface, color: Color = (10, 8, 20), diagonal: bool = False) -> pygame.Surface:
    """Return a copy of an SRCALPHA surface with a 1px outline added around opaque pixels."""
    w, h = surf.get_size()
    out = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
    mask = pygame.mask.from_surface(surf, 20)
    sil = mask.to_surface(setcolor=(*color, 255), unsetcolor=(0, 0, 0, 0))
    offs = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if diagonal:
        offs += ((-1, -1), (1, 1), (-1, 1), (1, -1))
    for dx, dy in offs:
        out.blit(sil, (1 + dx, 1 + dy))
    out.blit(surf, (1, 1))
    return out


def tint(surf: pygame.Surface, color: Color, amount: float = 0.5) -> pygame.Surface:
    s = surf.copy()
    ov = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    ov.fill((*color, int(255 * amount)))
    s.blit(ov, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    return s


def white_flash(surf: pygame.Surface, amount: float = 1.0) -> pygame.Surface:
    """Hit-flash version of a sprite (keeps alpha)."""
    s = surf.copy()
    ov = surf.copy()
    ov.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_ADD)
    ov.fill((int(255 * amount),) * 3 + (255,), special_flags=pygame.BLEND_RGBA_MIN)
    s.blit(ov, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    return s


_BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def dither_vertical(surf: pygame.Surface, rect: pygame.Rect, top: Color, bottom: Color) -> None:
    """Ordered-dither gradient (keeps the pixel-art look instead of smooth blends)."""
    for y in range(rect.h):
        t = y / max(1, rect.h - 1)
        for x in range(rect.w):
            thr = (_BAYER4[y % 4][x % 4] + 0.5) / 16
            surf.set_at((rect.x + x, rect.y + y), bottom if t > thr else top)


def banded_vertical(surf: pygame.Surface, rect: pygame.Rect, colors: list[Color]) -> None:
    n = len(colors)
    for i, c in enumerate(colors):
        y0 = rect.y + rect.h * i // n
        y1 = rect.y + rect.h * (i + 1) // n
        surf.fill(c, (rect.x, y0, rect.w, y1 - y0))


def draw_prism(surf: pygame.Surface, center, size: float, color: Color, t: float = 0.0,
               glow: bool = True, spin: bool = True, dim: float = 1.0) -> None:
    """Hexagonal floating crystal with faceted shading; ``t`` animates the shimmer."""
    cx, cy = center
    w = size * (0.62 + 0.18 * math.sin(t * 1.5)) if spin else size * 0.7
    top, bot = (cx, cy - size), (cx, cy + size)
    left, right = (cx - w, cy), (cx + w, cy)
    mid_l, mid_r = (cx - w * 0.35, cy), (cx + w * 0.35, cy)
    base = mix((40, 40, 60), color, dim)
    facets = [
        ([top, left, mid_l], shade(base, 0.35)),
        ([top, mid_l, mid_r], shade(base, 0.15)),
        ([top, mid_r, right], shade(base, -0.05)),
        ([bot, left, mid_l], shade(base, -0.25)),
        ([bot, mid_l, mid_r], shade(base, -0.1)),
        ([bot, mid_r, right], shade(base, -0.4)),
    ]
    if glow and dim > 0.2:
        blit_additive_glow(surf, center, int(size * 2.4), tuple(int(c * 0.55 * dim) for c in color), 2.2)
    for pts, col in facets:
        pygame.draw.polygon(surf, col, pts)
    pygame.draw.polygon(surf, (12, 10, 26), [top, right, bot, left], 1)
    sh = (math.sin(t * 2.2) * 0.5 + 0.5)
    pygame.draw.line(surf, shade(base, 0.8), (cx - w * 0.2, cy - size * 0.55 * sh - 2), (cx - w * 0.05, cy - size * 0.2), 1)


def draw_shadow(surf: pygame.Surface, pos, w: int, h: int = 0, alpha: int = 90) -> None:
    h = h or max(2, w // 3)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.ellipse(s, (0, 0, 10, alpha), s.get_rect())
    surf.blit(s, (pos[0] - w // 2, pos[1] - h // 2))


@lru_cache(maxsize=64)
def starfield(size: tuple[int, int], seed: int = 3, density: float = 0.004, tint_c: Color = (200, 215, 255)) -> pygame.Surface:
    import random
    rng = random.Random(seed)
    s = pygame.Surface(size, pygame.SRCALPHA)
    for _ in range(int(size[0] * size[1] * density)):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        b = rng.random()
        c = mix((90, 100, 140), tint_c, b)
        s.set_at((x, y), (*c, int(110 + 145 * b)))
        if b > 0.93:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if 0 <= x + dx < size[0] and 0 <= y + dy < size[1]:
                    s.set_at((x + dx, y + dy), (*c, 70))
    return s


def bake(draw_fn, size: tuple[int, int], with_outline: bool = True, outline_color: Color = (10, 8, 20)) -> pygame.Surface:
    """Draw into a transparent surface via ``draw_fn(surface)`` and optionally outline it."""
    s = pygame.Surface(size, pygame.SRCALPHA)
    draw_fn(s)
    return outline(s, outline_color) if with_outline else s


def poly_ngon(center, radius: float, n: int, rot: float = 0.0) -> list[tuple[float, float]]:
    return [(center[0] + math.cos(rot + i * math.tau / n) * radius,
             center[1] + math.sin(rot + i * math.tau / n) * radius) for i in range(n)]
