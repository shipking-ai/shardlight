"""Procedural art for Concord: cartographic hex tiles, battlefield tiles, unit figures, banners and icons.

Vellum paper, ink outlines, flat colour with hatching; four house colours.  Everything is baked once and cached.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import pygame

from ...core import art as core_art
from ...core.fx import mix
from . import hexgrid

VELLUM = (217, 201, 160)
VELLUM_D = (186, 168, 128)
INK = (43, 36, 56)
WAX = (168, 50, 58)
FOG = (60, 54, 74)

TERRAIN_COL = {"plain": (206, 196, 138), "forest": (128, 154, 98), "hill": (190, 164, 112), "mountain": (150, 140, 148),
               "marsh": (130, 166, 154)}
TILE_COL = {"open": (206, 196, 138), "forest": (128, 154, 98), "hill": (190, 164, 112), "rock": (120, 112, 124),
            "marsh": (130, 166, 154), "wall": (150, 140, 130), "water": (96, 140, 190), "ford": (140, 176, 196)}
ROLE_GLYPH = {"pike": "P", "infantry": "I", "archer": "A", "skirmisher": "S", "cavalry": "C", "siege": "T", "healer": "H",
              "banner": "B"}
ROLE_NAME = {"pike": "Pike", "infantry": "Infantry", "archer": "Archer", "skirmisher": "Skirmisher", "cavalry": "Cavalry",
             "siege": "Siege", "healer": "Healer", "banner": "Banner"}


def _noise_fill(surf: pygame.Surface, base, seed: int, amount: int = 10) -> None:
    rng = random.Random(seed)
    w, h = surf.get_size()
    for y in range(h):
        for x in range(w):
            if surf.get_at((x, y))[3] == 0:
                continue
            d = rng.randint(-amount, amount) if rng.random() < 0.35 else 0
            surf.set_at((x, y), (max(0, min(255, base[0] + d)), max(0, min(255, base[1] + d)), max(0, min(255, base[2] + d)), 255))


@lru_cache(maxsize=256)
def hex_tile(terrain: str, size: int, variant: int = 0) -> pygame.Surface:
    """A pointy-top hex of circumradius ``size`` with a terrain glyph.  Transparent outside the hex."""
    w = int(math.ceil(hexgrid.SQRT3 * size)) + 2
    h = int(2 * size) + 3
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    cx, cy = w / 2, h / 2
    pts = hexgrid.corners(cx, cy, size - 0.5)
    pygame.draw.polygon(surf, (*TERRAIN_COL[terrain], 255), pts)
    _noise_fill(surf, TERRAIN_COL[terrain], variant * 31 + len(terrain), 7)
    rng = random.Random(variant * 97 + hash(terrain) % 1000)
    ink = core_art.shade(TERRAIN_COL[terrain], 0.55)
    hi = core_art.shade(TERRAIN_COL[terrain], 1.18)
    s = size
    if terrain == "forest":
        for i in range(5):
            tx = cx + rng.uniform(-s * 0.55, s * 0.55)
            ty = cy + rng.uniform(-s * 0.4, s * 0.5)
            pygame.draw.polygon(surf, (86, 118, 80), [(tx, ty - s * 0.38), (tx - s * 0.2, ty + s * 0.1), (tx + s * 0.2, ty + s * 0.1)])
            pygame.draw.line(surf, ink, (tx, ty + s * 0.1), (tx, ty + s * 0.22))
            pygame.draw.line(surf, hi, (tx - 1, ty - s * 0.25), (tx - s * 0.12, ty + s * 0.05))
    elif terrain == "hill":
        for i in range(3):
            tx = cx + (i - 1) * s * 0.5 + rng.uniform(-2, 2)
            ty = cy + rng.uniform(-s * 0.1, s * 0.3)
            pygame.draw.arc(surf, ink, (tx - s * 0.32, ty - s * 0.28, s * 0.64, s * 0.56), 0.1, math.pi - 0.1, 1)
            pygame.draw.arc(surf, hi, (tx - s * 0.32, ty - s * 0.28 - 1, s * 0.64, s * 0.56), 0.9, math.pi - 0.9, 1)
    elif terrain == "mountain":
        for i, (dx, sc) in enumerate(((-0.35, 0.7), (0.3, 0.85), (0.0, 1.0))):
            tx, ty = cx + dx * s, cy + s * 0.25
            pk = [(tx, ty - s * 0.65 * sc), (tx - s * 0.38 * sc, ty), (tx + s * 0.38 * sc, ty)]
            pygame.draw.polygon(surf, (112, 104, 118), pk)
            pygame.draw.polygon(surf, (178, 170, 182), [(tx, ty - s * 0.65 * sc), (tx - s * 0.12 * sc, ty - s * 0.3 * sc), (tx + s * 0.05 * sc, ty - s * 0.28 * sc)])
            pygame.draw.lines(surf, ink, False, pk, 1)
    elif terrain == "marsh":
        for i in range(4):
            tx = cx + rng.uniform(-s * 0.6, s * 0.6)
            ty = cy + rng.uniform(-s * 0.4, s * 0.5)
            pygame.draw.line(surf, (88, 128, 118), (tx - 3, ty), (tx + 3, ty), 1)
            pygame.draw.line(surf, (88, 128, 118), (tx - 1, ty + 2), (tx + 1, ty + 2), 1)
            pygame.draw.line(surf, ink, (tx, ty), (tx, ty - 4))
    else:                                                     # plain: sparse grass ticks
        for i in range(7):
            tx = cx + rng.uniform(-s * 0.7, s * 0.7)
            ty = cy + rng.uniform(-s * 0.55, s * 0.6)
            pygame.draw.line(surf, ink, (tx, ty), (tx, ty - 2))
            pygame.draw.line(surf, ink, (tx + 2, ty), (tx + 3, ty - 2))
    return surf


@lru_cache(maxsize=64)
def hex_mask(size: int) -> pygame.Surface:
    w = int(math.ceil(hexgrid.SQRT3 * size)) + 2
    h = int(2 * size) + 3
    m = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.polygon(m, (255, 255, 255, 255), hexgrid.corners(w / 2, h / 2, size - 0.5))
    return m


@lru_cache(maxsize=64)
def fog_tile(size: int, kind: str) -> pygame.Surface:
    """``unknown``: opaque parchment smudge; ``memory``: translucent grey veil."""
    m = pygame.Surface(hex_mask(size).get_size(), pygame.SRCALPHA)
    w, h = m.get_size()
    pts = hexgrid.corners(w / 2, h / 2, size - 0.5)
    if kind == "unknown":
        pygame.draw.polygon(m, (*VELLUM_D, 70), pts)
        rng = random.Random(5)
        for _ in range(size):
            x, y = rng.randrange(w), rng.randrange(h)
            if hex_mask(size).get_at((x, y))[3]:
                m.set_at((x, y), (*core_art.shade(VELLUM_D, 0.8), 120))
        pygame.draw.polygon(m, (*core_art.shade(VELLUM_D, 0.85), 150), pts, 1)
    else:
        pygame.draw.polygon(m, (60, 54, 80, 105), pts)
    return m


def draw_hex_outline(surf: pygame.Surface, cx: float, cy: float, size: float, color, width: int = 1) -> None:
    pygame.draw.polygon(surf, color, hexgrid.corners(cx, cy, size - 0.5), width)


# ---------------------------------------------------------------------------------------------- map icons
def draw_castle(surf: pygame.Surface, x: float, y: float, col, s: int = 7) -> None:
    pygame.draw.rect(surf, INK, (x - s // 2 - 1, y - s // 2, s + 2, s))
    pygame.draw.rect(surf, col, (x - s // 2, y - s // 2 + 1, s, s - 1))
    for dx in (-s // 2, 0, s // 2 - 1):
        pygame.draw.rect(surf, INK, (x + dx - 1, y - s // 2 - 2, 3, 3))
        pygame.draw.rect(surf, col, (x + dx, y - s // 2 - 1, 1, 2))
    pygame.draw.rect(surf, INK, (x - 1, y + 1, 3, 3))


def draw_banner(surf: pygame.Surface, x: float, y: float, col, count: int, font, selected: bool = False, stance: str = "march",
                moving: bool = False) -> None:
    """Army marker: a pennant on a pole with the unit count."""
    pygame.draw.line(surf, INK, (x - 4, y + 6), (x - 4, y - 8))
    flag = [(x - 4, y - 8), (x + 6, y - 6), (x - 4, y - 2)]
    pygame.draw.polygon(surf, col, flag)
    pygame.draw.lines(surf, INK, True, flag, 1)
    if stance == "pillage":
        pygame.draw.line(surf, INK, (x - 2, y - 7), (x + 3, y - 3))
        pygame.draw.line(surf, INK, (x + 3, y - 7), (x - 2, y - 3))
    elif stance == "raid":
        pygame.draw.circle(surf, INK, (int(x), int(y - 5)), 1)
    font.draw(surf, str(count), (x + 7, y + 1), (255, 244, 220), INK)
    if selected:
        pygame.draw.circle(surf, (255, 236, 150), (int(x), int(y)), 11, 1)
    if moving:
        pygame.draw.polygon(surf, INK, [(x + 8, y - 9), (x + 12, y - 7), (x + 8, y - 5)])


def draw_building_pips(surf: pygame.Surface, x: float, y: float, n: int, col) -> None:
    for i in range(min(n, 5)):
        pygame.draw.rect(surf, INK, (x + i * 3 - 5, y, 3, 3))
        pygame.draw.rect(surf, col, (x + i * 3 - 4, y + 1, 1, 1))


# --------------------------------------------------------------------------------------- battlefield
@lru_cache(maxsize=128)
def battle_tile(kind: str, size: int, variant: int) -> pygame.Surface:
    surf = pygame.Surface((size, size))
    base = TILE_COL[kind]
    surf.fill(base)
    rng = random.Random(variant * 13 + hash(kind) % 997)
    for _ in range(size):
        x, y = rng.randrange(size), rng.randrange(size)
        d = rng.randint(-9, 9)
        surf.set_at((x, y), (max(0, min(255, base[0] + d)), max(0, min(255, base[1] + d)), max(0, min(255, base[2] + d))))
    ink = core_art.shade(base, 0.55)
    if kind == "forest":
        for _ in range(3):
            tx, ty = rng.randrange(4, size - 4), rng.randrange(8, size - 2)
            pygame.draw.polygon(surf, (82, 116, 78), [(tx, ty - 8), (tx - 4, ty), (tx + 4, ty)])
            pygame.draw.line(surf, ink, (tx, ty), (tx, ty + 2))
    elif kind == "hill":
        pygame.draw.arc(surf, ink, (3, size // 2 - 4, size - 6, 12), 0.2, math.pi - 0.2, 1)
        pygame.draw.arc(surf, core_art.shade(base, 1.2), (3, size // 2 - 5, size - 6, 12), 0.9, math.pi - 0.9, 1)
    elif kind == "rock":
        for _ in range(2):
            tx, ty = rng.randrange(5, size - 6), rng.randrange(6, size - 4)
            pygame.draw.polygon(surf, (96, 90, 102), [(tx - 5, ty + 4), (tx - 2, ty - 5), (tx + 4, ty - 3), (tx + 6, ty + 4)])
            pygame.draw.lines(surf, ink, False, [(tx - 5, ty + 4), (tx - 2, ty - 5), (tx + 4, ty - 3), (tx + 6, ty + 4)], 1)
    elif kind == "marsh":
        for _ in range(3):
            tx, ty = rng.randrange(3, size - 3), rng.randrange(4, size - 3)
            pygame.draw.line(surf, (88, 128, 118), (tx - 3, ty), (tx + 3, ty))
            pygame.draw.line(surf, ink, (tx, ty), (tx, ty - 4))
    elif kind in ("water", "ford"):
        for i in range(3):
            y = 5 + i * 8 + (variant % 3)
            pygame.draw.line(surf, (150, 190, 226), (3 + i * 2, y), (size - 5 - i * 2, y))
        if kind == "ford":
            for i in range(3):
                pygame.draw.circle(surf, (170, 160, 130), (6 + i * 8, size // 2 + (i % 2) * 5), 2)
    elif kind == "wall":
        surf.fill((142, 130, 120))
        for y in range(0, size, 7):
            pygame.draw.line(surf, (96, 88, 84), (0, y), (size, y))
            off = 0 if (y // 7) % 2 == 0 else size // 3
            for x in range(off, size, size // 1 or 1):
                pygame.draw.line(surf, (96, 88, 84), (x, y), (x, y + 7))
        pygame.draw.rect(surf, (96, 88, 84), (0, 0, size, size), 1)
    else:
        for _ in range(4):
            tx, ty = rng.randrange(2, size - 2), rng.randrange(4, size - 1)
            pygame.draw.line(surf, ink, (tx, ty), (tx, ty - 2))
    pygame.draw.rect(surf, core_art.shade(base, 0.8), (0, 0, size, size), 1)
    return surf


@lru_cache(maxsize=512)
def unit_figure(role: str, color: tuple, size: int = 24, flip: bool = False, flash: bool = False, rank: int = 0) -> pygame.Surface:
    """A small figure silhouette in the house colour.  ``flip`` mirrors it to face left."""
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    k = size / 24
    c = color
    dark = core_art.shade(c, 0.55)
    light = core_art.shade(c, 1.25)
    skin = (232, 200, 160)
    cx = size / 2

    def body(y0=9, h=9, w=7):
        pygame.draw.rect(s, c, (cx - w / 2, y0 * k, w, h * k))
        pygame.draw.rect(s, light, (cx - w / 2, y0 * k, 2, h * k))

    def head(y=5):
        pygame.draw.circle(s, skin, (int(cx), int(y * k)), max(2, int(3 * k)))
        pygame.draw.circle(s, dark, (int(cx), int(y * k)), max(2, int(3 * k)), 1)

    def legs():
        pygame.draw.rect(s, dark, (cx - 3 * k, 18 * k, 2 * k, 4 * k))
        pygame.draw.rect(s, dark, (cx + 1 * k, 18 * k, 2 * k, 4 * k))

    if role == "cavalry":
        pygame.draw.ellipse(s, (120, 86, 60), (3 * k, 12 * k, 17 * k, 8 * k))
        pygame.draw.polygon(s, (120, 86, 60), [(17 * k, 13 * k), (22 * k, 9 * k), (23 * k, 13 * k), (19 * k, 16 * k)])
        for lx in (5, 8, 15, 18):
            pygame.draw.line(s, (80, 56, 40), (lx * k, 19 * k), (lx * k, 23 * k), 2)
        pygame.draw.rect(s, c, (9 * k, 5 * k, 6 * k, 8 * k))
        pygame.draw.circle(s, skin, (int(12 * k), int(4 * k)), max(2, int(2.6 * k)))
        pygame.draw.line(s, (200, 200, 210), (14 * k, 2 * k), (22 * k, 11 * k), 1)
    elif role == "siege":
        pygame.draw.rect(s, (110, 80, 54), (3 * k, 17 * k, 18 * k, 4 * k))
        pygame.draw.circle(s, (70, 50, 36), (int(6 * k), int(21 * k)), int(3 * k))
        pygame.draw.circle(s, (70, 50, 36), (int(18 * k), int(21 * k)), int(3 * k))
        pygame.draw.line(s, (140, 104, 70), (8 * k, 17 * k), (17 * k, 6 * k), 3)
        pygame.draw.circle(s, (90, 90, 100), (int(18 * k), int(6 * k)), int(2.5 * k))
        pygame.draw.rect(s, c, (4 * k, 13 * k, 5 * k, 4 * k))
    else:
        legs()
        body()
        head()
        if role == "pike":
            pygame.draw.line(s, (170, 140, 100), (cx + 5 * k, 22 * k), (cx + 5 * k, 0), 2)
            pygame.draw.polygon(s, (210, 210, 220), [(cx + 5 * k, 0), (cx + 3 * k, 4 * k), (cx + 7 * k, 4 * k)])
        elif role == "infantry":
            pygame.draw.ellipse(s, light, (cx - 8 * k, 9 * k, 6 * k, 9 * k))
            pygame.draw.ellipse(s, dark, (cx - 8 * k, 9 * k, 6 * k, 9 * k), 1)
            pygame.draw.line(s, (210, 210, 220), (cx + 5 * k, 14 * k), (cx + 5 * k, 3 * k), 2)
        elif role == "archer":
            pygame.draw.arc(s, (150, 110, 70), (cx + 1 * k, 4 * k, 9 * k, 15 * k), -1.4, 1.4, 2)
            pygame.draw.line(s, (230, 230, 220), (cx + 6 * k, 5 * k), (cx + 6 * k, 18 * k), 1)
        elif role == "skirmisher":
            pygame.draw.line(s, (170, 140, 100), (cx + 3 * k, 14 * k), (cx + 10 * k, 4 * k), 2)
            pygame.draw.line(s, (170, 140, 100), (cx - 3 * k, 10 * k), (cx - 9 * k, 2 * k), 2)
        elif role == "healer":
            pygame.draw.rect(s, (240, 240, 240), (cx - 2 * k, 11 * k, 4 * k, 6 * k))
            pygame.draw.rect(s, (200, 60, 60), (cx - 1 * k, 11 * k, 2 * k, 6 * k))
            pygame.draw.rect(s, (200, 60, 60), (cx - 2 * k, 13 * k, 4 * k, 2 * k))
        elif role == "banner":
            pygame.draw.line(s, (170, 140, 100), (cx + 4 * k, 22 * k), (cx + 4 * k, 0), 2)
            pygame.draw.polygon(s, light, [(cx + 4 * k, 1 * k), (cx + 12 * k, 4 * k), (cx + 4 * k, 8 * k)])
    for i in range(rank):
        pygame.draw.rect(s, (255, 214, 120), (1 + i * 3, 1, 2, 2))
    out = core_art.outline(s, (20, 16, 30))
    if flash:
        out = core_art.white_flash(out, 0.8)
    return pygame.transform.flip(out, True, False) if flip else out


@lru_cache(maxsize=32)
def crest(color: tuple, size: int = 14) -> pygame.Surface:
    s = pygame.Surface((size, size + 2), pygame.SRCALPHA)
    pts = [(1, 1), (size - 2, 1), (size - 2, size * 0.6), (size / 2 - 0.5, size + 0.5), (1, size * 0.6)]
    pygame.draw.polygon(s, color, pts)
    pygame.draw.polygon(s, core_art.shade(color, 0.5), pts, 1)
    pygame.draw.line(s, core_art.shade(color, 1.4), (3, 3), (size - 4, 3))
    pygame.draw.line(s, core_art.shade(color, 0.6), (size // 2 - 1, 4), (size // 2 - 1, size - 3))
    return s


def parchment(size: tuple[int, int], seed: int = 3) -> pygame.Surface:
    """Textured vellum backdrop used behind the map and menus."""
    s = pygame.Surface(size)
    s.fill(VELLUM)
    rng = random.Random(seed)
    for _ in range(size[0] * size[1] // 90):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        d = rng.randint(-10, 6)
        s.set_at((x, y), (VELLUM[0] + d, VELLUM[1] + d, VELLUM[2] + d))
    # darkened edges
    for i in range(10):
        a = int(22 * (1 - i / 10))
        edge = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(edge, (60, 40, 30, a), (i, i, size[0] - 2 * i, size[1] - 2 * i), 1)
        s.blit(edge, (0, 0))
    return s
