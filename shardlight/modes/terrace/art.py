"""Procedural art for Terrace: 8 px bevelled tiles, item icons, creatures, the player and the sky.

Everything is baked once and cached; chunk surfaces are re-rendered only when their tiles change.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np
import pygame

from ...core import art as core_art
from ...core.fx import mix
from . import constants as K

T = K.TILE
OUT = (22, 18, 26)
WALL_COL = (38, 32, 44)


def _c(v):
    return tuple(int(max(0, min(255, x))) for x in v)


def shade(c, k):
    return _c([x * k for x in c])


def _speckle(s: pygame.Surface, base, rng: random.Random, n: int, amount: int = 14, lighter: bool = True) -> None:
    for _ in range(n):
        x, y = rng.randrange(T), rng.randrange(T)
        d = rng.randint(-amount, amount if lighter else 0)
        s.set_at((x, y), _c([base[0] + d, base[1] + d, base[2] + d]))


@lru_cache(maxsize=1024)
def block_sprite(style: str, color: tuple, accent: tuple | None, variant: int = 0, stage: int = 0, kind: str = "") -> pygame.Surface:
    """An 8x8 tile for a block style.  Transparent styles use per-pixel alpha."""
    rng = random.Random(hash((style, variant)) & 0xffff)
    s = pygame.Surface((T, T), pygame.SRCALPHA)
    base = color
    hi, lo = shade(base, 1.22), shade(base, 0.72)
    acc = accent or base

    def fill(c=base):
        s.fill((*c, 255))

    if style in ("dirt", "farmland", "farmland_wet"):
        fill(base)
        _speckle(s, base, rng, 14, 12)
        if style != "dirt":
            for y in (1, 4):
                pygame.draw.line(s, lo, (0, y), (T - 1, y))
            if style == "farmland_wet":
                s.fill((30, 50, 90, 70), special_flags=pygame.BLEND_RGBA_ADD)
    elif style == "grass":
        fill((112, 78, 52))
        _speckle(s, (112, 78, 52), rng, 12, 10)
        pygame.draw.rect(s, acc, (0, 0, T, 2))
        pygame.draw.line(s, shade(acc, 1.2), (0, 0), (T - 1, 0))
        for x in range(T):
            if rng.random() < 0.5:
                s.set_at((x, 2), acc)
    elif style in ("stone", "slate", "sandstone", "sand", "salt", "snow", "ice", "moss", "bedrock"):
        fill(base)
        _speckle(s, base, rng, 18, 10)
        if style in ("stone", "slate", "moss"):
            x = rng.randrange(1, T - 3)
            pygame.draw.line(s, lo, (x, 1), (x + 2, 3))
            pygame.draw.line(s, lo, (x + 2, 3), (x + 1, 6))
        if style == "moss":
            for x in range(T):
                if rng.random() < 0.5:
                    s.set_at((x, 0), (80, 150, 70))
                    if rng.random() < 0.4:
                        s.set_at((x, 1), (60, 120, 60))
        if style == "sandstone":
            pygame.draw.line(s, lo, (0, 3), (T - 1, 3))
            pygame.draw.line(s, hi, (0, 4), (T - 1, 4))
        if style == "ice":
            pygame.draw.line(s, (230, 248, 255), (1, 1), (3, 1))
            pygame.draw.line(s, (230, 248, 255), (1, 1), (1, 3))
        if style == "bedrock":
            for _ in range(5):
                pygame.draw.rect(s, shade(base, 0.6), (rng.randrange(T - 2), rng.randrange(T - 2), 2, 2))
        if style == "salt":
            for _ in range(4):
                s.set_at((rng.randrange(T), rng.randrange(T)), (255, 255, 255))
    elif style == "ore":
        fill((138, 133, 144))
        _speckle(s, (138, 133, 144), rng, 14, 8)
        for _ in range(5):
            x, y = rng.randrange(1, T - 2), rng.randrange(1, T - 2)
            pygame.draw.rect(s, base, (x, y, 2, 2))
            s.set_at((x, y), shade(acc, 1.3) if accent else hi)
    elif style == "metal":
        fill(base)
        pygame.draw.rect(s, hi, (0, 0, T, 1))
        pygame.draw.rect(s, lo, (0, T - 1, T, 1))
        pygame.draw.rect(s, shade(base, 0.85), (1, 1, T - 2, T - 2), 1)
        pygame.draw.line(s, hi, (2, 2), (3, 2))
        s.set_at((T - 3, T - 3), lo)
    elif style == "crystal":
        fill(base)
        pygame.draw.polygon(s, hi, [(4, 0), (7, 4), (4, 7), (1, 4)])
        pygame.draw.polygon(s, shade(base, 1.5), [(4, 1), (6, 4), (4, 6), (2, 4)])
        s.set_at((3, 3), (255, 255, 255))
    elif style == "prism":
        for y in range(T):
            for x in range(T):
                d = abs(x - 3.5) + abs(y - 3.5)
                if d < 4.6:
                    s.set_at((x, y), (*_c(mix((255, 214, 120), (130, 214, 255), (x + y) / 14)), 255 if d < 3.6 else 150))
        s.set_at((3, 2), (255, 255, 255))
    elif style == "log":
        fill(base)
        for x in range(0, T, 2):
            pygame.draw.line(s, lo, (x, 0), (x, T - 1))
        pygame.draw.line(s, hi, (1, 0), (1, T - 1))
        _speckle(s, base, rng, 5, 10)
    elif style == "planks":
        fill(base)
        for y in (0, 4):
            pygame.draw.line(s, lo, (0, y + 3), (T - 1, y + 3))
        pygame.draw.line(s, hi, (0, 0), (T - 1, 0))
        pygame.draw.line(s, hi, (0, 4), (T - 1, 4))
        s.set_at((rng.randrange(T), 1), lo)
    elif style in ("brick", "ruin_brick"):
        fill(base)
        pygame.draw.line(s, lo, (0, 3), (T - 1, 3))
        pygame.draw.line(s, lo, (0, 7), (T - 1, 7))
        pygame.draw.line(s, lo, (3, 0), (3, 3))
        pygame.draw.line(s, lo, (6, 4), (6, 7))
        pygame.draw.line(s, hi, (0, 0), (T - 1, 0))
        pygame.draw.line(s, hi, (0, 4), (T - 1, 4))
        if style == "ruin_brick":
            for _ in range(4):
                s.set_at((rng.randrange(T), rng.randrange(T)), (70, 120, 70))
            s.set_at((rng.randrange(T), 0), (0, 0, 0, 0))
    elif style == "glass":
        s.fill((*base, 70))
        pygame.draw.rect(s, (*hi, 190), (0, 0, T, T), 1)
        pygame.draw.line(s, (255, 255, 255, 220), (1, 1), (3, 1))
        pygame.draw.line(s, (255, 255, 255, 220), (1, 1), (1, 3))
    elif style == "obsidian":
        fill((30, 22, 44))
        pygame.draw.line(s, (96, 70, 150), (1, 5), (4, 2))
        pygame.draw.line(s, (150, 120, 220), (5, 6), (6, 5))
        _speckle(s, (30, 22, 44), rng, 8, 10)
    elif style == "leaves":
        fill(base)
        for _ in range(16):
            x, y = rng.randrange(T), rng.randrange(T)
            s.set_at((x, y), (*_c(shade(base, rng.choice((0.7, 1.2, 1.35)))), 255))
        for _ in range(7):
            s.set_at((rng.randrange(T), rng.randrange(T)), (0, 0, 0, 0))
    elif style == "torch":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (110, 76, 44), (3, 3, 2, 5))
        pygame.draw.rect(s, (255, 190, 90), (2, 0, 4, 4))
        pygame.draw.rect(s, (255, 244, 180), (3, 1, 2, 2))
    elif style == "workbench":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, base, (0, 3, T, 2))
        pygame.draw.rect(s, shade(base, 0.7), (0, 5, 2, 3))
        pygame.draw.rect(s, shade(base, 0.7), (6, 5, 2, 3))
        pygame.draw.rect(s, (200, 200, 210), (1, 1, 3, 2))
    elif style in ("furnace", "forge"):
        fill((120, 116, 126) if style == "furnace" else (84, 80, 96))
        pygame.draw.rect(s, (30, 24, 28), (2, 3, 4, 4))
        pygame.draw.rect(s, (255, 150, 60) if style == "furnace" else (255, 90, 60), (3, 4, 2, 2))
        pygame.draw.line(s, hi, (0, 0), (T - 1, 0))
    elif style == "loom":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (130, 92, 56), (0, 0, 1, T))
        pygame.draw.rect(s, (130, 92, 56), (T - 1, 0, 1, T))
        for x in range(1, T - 1, 2):
            pygame.draw.line(s, (232, 228, 214), (x, 1), (x, T - 2))
    elif style == "chest":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (128, 88, 52), (0, 2, T, 6))
        pygame.draw.rect(s, (150, 106, 62), (0, 2, T, 2))
        pygame.draw.rect(s, (60, 44, 30), (0, 2, T, 6), 1)
        pygame.draw.rect(s, (230, 200, 90), (3, 4, 2, 2))
    elif style in ("door", "door_open"):
        s.fill((0, 0, 0, 0))
        if style == "door":
            pygame.draw.rect(s, (150, 104, 62), (1, 0, 6, T))
            pygame.draw.rect(s, (96, 66, 38), (1, 0, 6, T), 1)
            s.set_at((5, 4), (230, 200, 90))
        else:
            pygame.draw.rect(s, (150, 104, 62), (0, 0, 2, T))
            pygame.draw.rect(s, (96, 66, 38), (0, 0, 2, T), 1)
    elif style == "bed":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (200, 80, 80), (0, 4, T, 3))
        pygame.draw.rect(s, (240, 230, 220), (0, 3, 3, 2))
        pygame.draw.rect(s, (110, 76, 44), (0, 7, T, 1))
    elif style == "ladder":
        s.fill((0, 0, 0, 0))
        pygame.draw.line(s, (130, 92, 56), (1, 0), (1, T - 1))
        pygame.draw.line(s, (130, 92, 56), (6, 0), (6, T - 1))
        for y in (1, 4, 7):
            pygame.draw.line(s, (170, 124, 76), (1, y), (6, y))
    elif style == "fence":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (130, 92, 56), (3, 0, 2, T))
        pygame.draw.rect(s, (150, 106, 64), (0, 2, T, 1))
        pygame.draw.rect(s, (150, 106, 64), (0, 5, T, 1))
    elif style == "tallgrass":
        s.fill((0, 0, 0, 0))
        for x, h in ((1, 4), (3, 6), (5, 3), (6, 5)):
            pygame.draw.line(s, (92, 160, 70) if x % 2 else (118, 188, 84), (x, T - 1), (x + (1 if x < 4 else -1) * (variant % 2), T - h))
    elif style == "flower":
        s.fill((0, 0, 0, 0))
        pygame.draw.line(s, (80, 150, 70), (4, T - 1), (4, 3))
        petal = [(240, 120, 150), (250, 220, 90), (160, 140, 240), (255, 255, 255)][variant % 4]
        pygame.draw.rect(s, petal, (3, 1, 3, 3))
        s.set_at((4, 2), (255, 220, 100))
    elif style == "glowcap":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (220, 220, 200), (3, 4, 2, 4))
        pygame.draw.ellipse(s, (90, 210, 190), (1, 1, 6, 4))
        s.set_at((3, 2), (220, 255, 240))
    elif style == "cactus":
        fill((60, 140, 70))
        pygame.draw.line(s, (90, 180, 90), (2, 0), (2, T - 1))
        pygame.draw.line(s, (40, 100, 56), (5, 0), (5, T - 1))
        for y in (1, 3, 5, 7):
            s.set_at((rng.choice((0, 7)), y), (240, 230, 200))
    elif style == "sapling":
        s.fill((0, 0, 0, 0))
        pygame.draw.line(s, (110, 76, 44), (4, T - 1), (4, 4))
        pygame.draw.rect(s, (80, 160, 70), (2, 1, 4, 3))
    elif style == "crop":
        s.fill((0, 0, 0, 0))
        kind = kind or "wheat"
        n = 4
        h = 2 + stage * 2
        stalk = (130, 170, 70) if stage < 3 else ((222, 196, 90) if kind == "wheat" else (150, 110, 70))
        for x in (1, 3, 5, 7)[: 2 + stage]:
            pygame.draw.line(s, stalk, (x, T - 1), (x, T - h))
            if stage == 3:
                if kind == "wheat":
                    pygame.draw.rect(s, (240, 214, 100), (x - 1 if x > 1 else x, T - h - 1, 2, 2))
                else:
                    pygame.draw.circle(s, (170, 120, 80), (x, T - 2), 1)
    elif style == "shrine":
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (150, 150, 160), (2, 2, 4, 6))
        pygame.draw.rect(s, (110, 110, 124), (1, 7, 6, 1))
        pygame.draw.circle(s, (130, 214, 255), (4, 3), 1)
    elif style == "seal":
        fill((96, 92, 104))
        pygame.draw.rect(s, (60, 56, 70), (0, 0, T, T), 1)
        pygame.draw.circle(s, (130, 214, 255), (4, 4), 2, 1)
    elif style == "plinth":
        fill((70, 64, 86))
        pygame.draw.rect(s, (150, 140, 180), (0, 0, T, 2))
        pygame.draw.rect(s, (40, 36, 52), (0, 6, T, 2))
        pygame.draw.line(s, (130, 214, 255), (1, 4), (6, 4))
    elif style == "air":
        s.fill((0, 0, 0, 0))
    else:
        fill(base)
        _speckle(s, base, rng, 8, 8)
    return s


# ------------------------------------------------------------------------------------------------ chunks
def render_chunk(world, cx: int, cy: int) -> pygame.Surface:
    """Bake a 32x32-tile chunk (tiles, cave walls, liquids) into an alpha surface."""
    from .constants import CHUNK
    reg = world.reg
    surf = pygame.Surface((CHUNK * T, CHUNK * T), pygame.SRCALPHA)
    gx0, gy0 = cx * CHUNK, cy * CHUNK
    blocks = world.grid.blocks
    liq = world.grid.liq
    for ty in range(CHUNK):
        y = gy0 + ty
        if y >= world.h:
            break
        for tx in range(CHUNK):
            x = gx0 + tx
            if x >= world.w:
                break
            n = int(blocks[y, x])
            px, py = tx * T, ty * T
            b = reg.block_by_n[n]
            if n == K.AIR or b is None:
                if y > world.surf[x] + 1:
                    w = (x * 3 + y * 5) % 7
                    pygame.draw.rect(surf, (WALL_COL[0] + (w % 2) * 3, WALL_COL[1] + (w % 3), WALL_COL[2] + (w % 2) * 2), (px, py, T, T))
                    if (x + y) % 5 == 0:
                        pygame.draw.line(surf, (30, 25, 36), (px, py + 3), (px + T - 1, py + 3))
            else:
                if not b.get("opaque", True) and b["style"] not in ("leaves",) and y > world.surf[x] + 1:
                    pygame.draw.rect(surf, WALL_COL, (px, py, T, T))
                crop = b.get("crop")
                spr = block_sprite(b["style"], tuple(b["color"]), tuple(b["accent"]) if b.get("accent") else None, (x * 7 + y * 13) % 4,
                                   crop["stage"] if crop else 0, crop["kind"] if crop else "")
                surf.blit(spr, (px, py))
                if b.get("opaque", True) and b.get("solid", True) and b["style"] not in ("glass", "leaves", "prism"):
                    # bevel: light top edge and dark bottom edge where the neighbour is open
                    if y > 0 and not reg.solid[blocks[y - 1, x]]:
                        pygame.draw.line(surf, (*shade(b["color"], 1.35), 255), (px, py), (px + T - 1, py))
                    if y + 1 < world.h and not reg.solid[blocks[y + 1, x]]:
                        pygame.draw.line(surf, (*shade(b["color"], 0.55), 255), (px, py + T - 1), (px + T - 1, py + T - 1))
                    if x > 0 and not reg.solid[blocks[y, x - 1]]:
                        pygame.draw.line(surf, (*shade(b["color"], 1.15), 255), (px, py), (px, py + T - 1))
                    if x + 1 < world.w and not reg.solid[blocks[y, x + 1]]:
                        pygame.draw.line(surf, (*shade(b["color"], 0.7), 255), (px + T - 1, py), (px + T - 1, py + T - 1))
            v = int(liq[y, x])
            if v:
                amt = v & K.LIQ_AMOUNT_MASK
                lava = bool(v & K.LIQ_LAVA)
                above = int(liq[y - 1, x]) & K.LIQ_AMOUNT_MASK if y > 0 else 0
                h = T if above else max(1, int(amt * T / K.LIQ_MAX))
                col = (255, 120, 40, 235) if lava else (70, 120, 220, 150)
                pygame.draw.rect(surf, col, (px, py + T - h, T, h))
                if not above:
                    pygame.draw.line(surf, (255, 220, 120, 255) if lava else (190, 225, 255, 220), (px, py + T - h), (px + T - 1, py + T - h))
    return surf


# --------------------------------------------------------------------------------------------- icons
@lru_cache(maxsize=512)
def item_icon(item_id: str, color: tuple, accent: tuple | None, icon: str, block_sprite_args: tuple | None = None) -> pygame.Surface:
    """12x12 inventory icon."""
    s = pygame.Surface((12, 12), pygame.SRCALPHA)
    c = tuple(color)
    dark = shade(c, 0.55)
    light = shade(c, 1.3)
    wood = (140, 100, 60)

    def line(a, b, col, w=1):
        pygame.draw.line(s, col, a, b, w)

    if icon == "block" and block_sprite_args:
        spr = block_sprite(*block_sprite_args)
        s.blit(pygame.transform.scale(spr, (10, 10)), (1, 1))
        pygame.draw.rect(s, OUT, (0, 0, 12, 12), 1)
        s.set_at((0, 0), (0, 0, 0, 0))
        return s
    if icon in ("pick", "axe", "shovel", "hoe", "sword", "shears"):
        if icon == "sword":
            line((2, 10), (9, 3), c, 2)
            line((3, 9), (8, 4), light)
            line((1, 8), (4, 11), wood, 2)
            line((1, 11), (3, 9), dark)
        else:
            line((2, 10), (9, 3), wood, 1)
            if icon == "pick":
                pygame.draw.arc(s, c, (3, 0, 9, 9), 0.3, 2.9, 2)
            elif icon == "axe":
                pygame.draw.polygon(s, c, [(7, 1), (11, 3), (10, 6), (7, 5)])
                line((7, 1), (7, 5), light)
            elif icon == "shovel":
                pygame.draw.polygon(s, c, [(8, 0), (11, 3), (9, 5), (6, 3)])
            elif icon == "hoe":
                line((6, 3), (11, 2), c, 2)
                line((10, 2), (10, 5), c)
            else:
                line((3, 3), (9, 9), c)
                line((3, 9), (9, 3), c)
                pygame.draw.circle(s, dark, (6, 6), 1)
    elif icon in ("helmet",):
        pygame.draw.ellipse(s, c, (2, 2, 8, 7))
        pygame.draw.rect(s, c, (2, 6, 8, 3))
        pygame.draw.rect(s, dark, (4, 6, 4, 2))
    elif icon == "chest" and item_id.endswith(("head", "chest", "legs")) or icon == "legs":
        if icon == "legs":
            pygame.draw.rect(s, c, (2, 1, 8, 4))
            pygame.draw.rect(s, c, (2, 5, 3, 6))
            pygame.draw.rect(s, c, (7, 5, 3, 6))
        else:
            pygame.draw.rect(s, c, (2, 2, 8, 8))
            pygame.draw.rect(s, c, (0, 2, 2, 4))
            pygame.draw.rect(s, c, (10, 2, 2, 4))
            pygame.draw.rect(s, light, (3, 3, 2, 5))
    elif icon in ("ingot",):
        pygame.draw.polygon(s, c, [(1, 8), (3, 4), (11, 4), (9, 8)])
        pygame.draw.polygon(s, light, [(3, 4), (11, 4), (10, 5), (3, 5)])
        pygame.draw.line(s, dark, (1, 9), (9, 9))
    elif icon in ("chunk", "coal", "shard"):
        pts = [(2, 8), (4, 3), (8, 2), (10, 6), (8, 10), (4, 10)]
        pygame.draw.polygon(s, c, pts)
        pygame.draw.polygon(s, dark, pts, 1)
        pygame.draw.line(s, light, (5, 4), (7, 3))
    elif icon in ("seed", "tuber", "wheat", "cooked", "meat", "fruit", "bread", "flower", "mushroom", "sapling", "cactus", "stick", "wool", "cloth"):
        if icon == "wheat":
            for x in (3, 6, 9):
                line((x, 11), (x, 2), (222, 196, 90))
                pygame.draw.rect(s, (240, 214, 100), (x - 1, 1, 2, 3))
        elif icon == "stick":
            line((2, 10), (9, 2), wood, 2)
        elif icon in ("seed", "tuber"):
            pygame.draw.ellipse(s, c, (3, 3, 6, 6))
            s.set_at((5, 4), light)
        elif icon in ("cooked", "meat"):
            pygame.draw.ellipse(s, c, (1, 3, 9, 7))
            pygame.draw.rect(s, (235, 230, 215), (8, 2, 3, 3))
            pygame.draw.ellipse(s, light, (3, 4, 4, 2))
        elif icon == "bread":
            pygame.draw.ellipse(s, c, (1, 4, 10, 6))
            line((4, 5), (4, 8), dark)
            line((7, 5), (7, 8), dark)
        elif icon == "fruit":
            pygame.draw.circle(s, c, (6, 7), 3)
            s.set_at((6, 3), (80, 150, 70))
        elif icon == "flower":
            line((6, 11), (6, 5), (80, 150, 70))
            pygame.draw.circle(s, c, (6, 4), 3)
            s.set_at((6, 4), (255, 220, 100))
        elif icon == "mushroom":
            pygame.draw.rect(s, (220, 220, 200), (5, 6, 2, 5))
            pygame.draw.ellipse(s, c, (1, 2, 10, 6))
        elif icon == "sapling":
            line((6, 11), (6, 6), wood)
            pygame.draw.circle(s, (80, 160, 70), (6, 4), 3)
        elif icon == "cactus":
            pygame.draw.rect(s, (60, 140, 70), (4, 2, 4, 9))
            pygame.draw.rect(s, (60, 140, 70), (1, 4, 3, 2))
            pygame.draw.rect(s, (60, 140, 70), (8, 5, 3, 2))
        else:
            pygame.draw.rect(s, c, (2, 3, 8, 7))
            pygame.draw.rect(s, light, (2, 3, 8, 2))
    elif icon in ("bucket", "water_bucket"):
        pygame.draw.polygon(s, (196, 200, 214), [(2, 3), (10, 3), (9, 11), (3, 11)])
        pygame.draw.line(s, (120, 124, 140), (3, 3), (9, 3))
        if icon == "water_bucket":
            pygame.draw.rect(s, (90, 150, 240), (3, 4, 6, 2))
    elif icon == "door":
        pygame.draw.rect(s, (150, 104, 62), (3, 1, 6, 10))
        pygame.draw.rect(s, (96, 66, 38), (3, 1, 6, 10), 1)
        s.set_at((7, 6), (230, 200, 90))
    else:
        pygame.draw.rect(s, c, (2, 2, 8, 8))
        pygame.draw.rect(s, dark, (2, 2, 8, 8), 1)
    return core_art.outline(s, OUT)


# ------------------------------------------------------------------------------------------- creatures
@lru_cache(maxsize=256)
def creature_sprite(kind: str, size: tuple, color: tuple, accent: tuple | None, frame: int, flip: bool, flash: bool = False) -> pygame.Surface:
    w, h = size
    s = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
    ox, oy = 2, 2
    c = tuple(color)
    a = tuple(accent) if accent else shade(c, 0.6)
    dark = shade(c, 0.55)
    light = shade(c, 1.25)
    bob = frame % 2
    if kind == "hopper":
        pygame.draw.ellipse(s, c, (ox, oy + 2 - bob, w - 2, h - 2))
        pygame.draw.ellipse(s, light, (ox + 1, oy + 3 - bob, w - 6, 2))
        pygame.draw.rect(s, c, (ox + w - 3, oy - 1 - bob, 2, 4))              # ears
        pygame.draw.rect(s, c, (ox + w - 5, oy - 1 - bob, 1, 3))
        s.set_at((ox + w - 3, oy + 2 - bob), (20, 16, 24))
        pygame.draw.rect(s, dark, (ox, oy + h - 3, 3, 2 + bob))               # hind leg
    elif kind == "woolback":
        pygame.draw.ellipse(s, (240, 236, 224), (ox, oy, w - 3, h - 2))
        for i in range(3):
            pygame.draw.circle(s, (255, 252, 244), (ox + 3 + i * 3, oy + 2), 2)
        pygame.draw.rect(s, c, (ox + w - 5, oy + 2, 4, 4))                    # face
        s.set_at((ox + w - 3, oy + 3), (20, 16, 24))
        for lx in (ox + 2, ox + w - 7):
            pygame.draw.rect(s, dark, (lx, oy + h - 3, 1, 3 - bob if lx > ox + 3 else 3 - (1 - bob)))
    elif kind == "ridgewolf":
        pygame.draw.ellipse(s, c, (ox, oy + 1, w - 4, h - 3))
        pygame.draw.polygon(s, c, [(ox + w - 6, oy + 2), (ox + w - 1, oy + 4), (ox + w - 6, oy + 6)])
        pygame.draw.polygon(s, dark, [(ox + w - 6, oy), (ox + w - 5, oy + 3), (ox + w - 8, oy + 3)])
        pygame.draw.line(s, a, (ox + 2, oy + 1), (ox + w - 7, oy + 1))        # ridge of lighter fur
        pygame.draw.line(s, dark, (ox, oy + 2), (ox - 2, oy + 5 - bob))        # tail
        for lx in (ox + 3, ox + w - 8):
            pygame.draw.line(s, dark, (lx, oy + h - 3), (lx + (bob * 2 - 1), oy + h - 1))
        s.set_at((ox + w - 3, oy + 3), (255, 214, 90))
    elif kind == "bumblet":
        pygame.draw.ellipse(s, (250, 214, 70), (ox, oy + 1, w - 1, h - 1))
        pygame.draw.line(s, (40, 30, 30), (ox + 2, oy + 1), (ox + 2, oy + h - 1))
        pygame.draw.line(s, (40, 30, 30), (ox + 4, oy + 1), (ox + 4, oy + h - 1))
        pygame.draw.ellipse(s, (210, 230, 255, 200), (ox + 1, oy - 1 + bob, 3, 3))
    elif kind == "crawler":
        pygame.draw.ellipse(s, c, (ox, oy + 1, w - 1, h - 1))
        for i in range(4):
            pygame.draw.line(s, dark, (ox + 2 + i * 2, oy + h - 1), (ox + 1 + i * 2 + (bob if i % 2 else -bob), oy + h + 1))
        pygame.draw.rect(s, a, (ox + 2, oy + 1, w - 5, 1))
        s.set_at((ox + w - 3, oy + 2), (255, 90, 90))
        s.set_at((ox + w - 5, oy + 2), (255, 90, 90))
    elif kind == "gleaner":
        pygame.draw.ellipse(s, c, (ox + 1, oy + 1, w - 3, h - 3))
        wing = -2 if bob else 2
        pygame.draw.polygon(s, dark, [(ox + 3, oy + 2), (ox + w // 2, oy + 2 + wing), (ox + w - 3, oy + 2)])
        pygame.draw.polygon(s, a, [(ox + w - 2, oy + 3), (ox + w + 1, oy + 4), (ox + w - 2, oy + 5)])
        s.set_at((ox + w - 4, oy + 3), (255, 255, 255))
    elif kind == "gloam":
        pygame.draw.ellipse(s, (20, 16, 32), (ox, oy, w, h - 2))
        pygame.draw.rect(s, (20, 16, 32), (ox + 1, oy + h // 2, w - 2, h // 2))
        for i in range(3):
            pygame.draw.line(s, (20, 16, 32), (ox + 1 + i * 2, oy + h - 2), (ox + 1 + i * 2 + (bob if i == 1 else 0), oy + h + 1))
        pygame.draw.rect(s, (255, 214, 90), (ox + 1, oy + 3, 2, 2))
        pygame.draw.rect(s, (255, 214, 90), (ox + w - 3, oy + 3, 2, 2))
        pygame.draw.line(s, (60, 40, 90), (ox + w // 2, oy + 1), (ox + w // 2, oy + h // 2))
    else:
        pygame.draw.ellipse(s, c, (ox, oy, w, h))
    out = core_art.outline(s, OUT)
    if flash:
        out = core_art.white_flash(out, 0.8)
    return pygame.transform.flip(out, True, False) if flip else out


# ----------------------------------------------------------------------------------------------- player
@lru_cache(maxsize=64)
def player_sprite(frame: int, flip: bool, state: str, armor: tuple = ()) -> pygame.Surface:
    s = pygame.Surface((10, 18), pygame.SRCALPHA)
    skin, hair, tunic, trim, boots = (236, 200, 160), (92, 60, 44), (60, 130, 140), (230, 200, 120), (70, 52, 44)
    if armor and armor[1]:
        tunic = armor[1]
    # head
    pygame.draw.rect(s, skin, (3, 1, 4, 4))
    pygame.draw.rect(s, hair, (3, 0, 4, 2))
    pygame.draw.rect(s, hair, (2, 1, 1, 3))
    s.set_at((6, 3), (30, 24, 34))
    if armor and armor[0]:
        pygame.draw.rect(s, armor[0], (3, 0, 4, 2))
    # body
    pygame.draw.rect(s, tunic, (2, 5, 6, 6))
    pygame.draw.rect(s, trim, (2, 9, 6, 1))
    pygame.draw.rect(s, shade(tunic, 1.2), (2, 5, 1, 5))
    # legs
    lc = armor[2] if armor and armor[2] else (70, 78, 120)
    if state == "walk":
        a = [(3, 11, 2, 5), (5, 11, 2, 4)] if frame % 2 == 0 else [(3, 11, 2, 4), (5, 11, 2, 5)]
        if frame % 4 in (1, 3):
            a = [(4, 11, 2, 5), (4, 11, 2, 5)]
    elif state == "jump":
        a = [(2, 11, 2, 4), (6, 11, 2, 3)]
    else:
        a = [(3, 11, 2, 5), (5, 11, 2, 5)]
    for r in a:
        pygame.draw.rect(s, lc, r)
        pygame.draw.rect(s, boots, (r[0], r[1] + r[3] - 1, 2, 1))
    # arm
    if state == "climb":
        pygame.draw.rect(s, skin, (1, 4 + (frame % 2), 1, 3))
        pygame.draw.rect(s, skin, (8, 5 - (frame % 2), 1, 3))
    else:
        pygame.draw.rect(s, skin, (7, 6, 2, 3))
    out = core_art.outline(s, OUT)
    return pygame.transform.flip(out, True, False) if flip else out


# ------------------------------------------------------------------------------------------------- sky
def sky_gradient(daylight: float, clock: float, size: tuple[int, int]) -> pygame.Surface:
    """Vertical sky gradient with dawn/dusk warmth."""
    w, h = size
    top_day, bot_day = (82, 160, 226), (178, 220, 244)
    top_night, bot_night = (8, 10, 30), (26, 28, 64)
    warm = max(0.0, 1.0 - abs(daylight - 0.55) * 3.2) if 0.2 < daylight < 0.9 else 0.0
    k = (daylight - 0.12) / 0.88
    top = mix(top_night, top_day, k)
    bot = mix(bot_night, bot_day, k)
    bot = mix(bot, (255, 150, 90), warm * 0.55)
    top = mix(top, (170, 96, 120), warm * 0.25)
    s = pygame.Surface((1, h))
    for y in range(h):
        s.set_at((0, y), _c(mix(top, bot, y / max(1, h - 1))))
    return pygame.transform.scale(s, (w, h))


@lru_cache(maxsize=4)
def far_hills(seed: int, w: int, color: tuple, base: float, amp: float, period: float) -> pygame.Surface:
    rng = random.Random(seed)
    ph = [rng.uniform(0, 6.28) for _ in range(3)]
    s = pygame.Surface((w, 120), pygame.SRCALPHA)
    for x in range(w):
        y = base + amp * (math.sin(x / period + ph[0]) * 0.6 + math.sin(x / (period * 0.43) + ph[1]) * 0.3 + math.sin(x / (period * 0.17) + ph[2]) * 0.1)
        pygame.draw.line(s, (*color, 255), (x, int(y)), (x, 119))
    return s


@lru_cache(maxsize=2)
def star_layer(size: tuple[int, int]) -> pygame.Surface:
    return core_art.starfield(size, 11, 0.003)
