"""Procedural art for Hollowmere: ground tiles with blended edges (cached per 16x16-tile chunk), object sprites, building
façades, people and creatures.  Everything is drawn from code, cached, and keyed by small integers so it is cheap at
runtime.  Palette follows the shard colour (leaf green, brass lamplight, slate and marsh teal).
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np
import pygame

from . import tiles as T

TS = T.TILE
CHUNK = 16

# ------------------------------------------------------------------------------------------ ground
GROUND_STYLE = {
    T.DEEP: ((28, 62, 112), "water"), T.SHALLOW: ((66, 124, 170), "water"), T.SAND: ((216, 198, 142), "sand"),
    T.MUD: ((112, 94, 62), "mud"), T.GRASS: ((98, 160, 76), "grass"), T.FOREST: ((54, 112, 62), "leaf"),
    T.MOOR: ((124, 114, 150), "moor"), T.ROCK: ((132, 130, 136), "rock"), T.DIRT: ((152, 122, 82), "dirt"),
    T.ROAD: ((182, 160, 116), "road"), T.BRIDGE: ((142, 100, 62), "plank"), T.PLANK: ((150, 110, 70), "plank"),
    T.FLAG: ((158, 158, 150), "slab"), T.FARM: ((140, 112, 68), "furrow"), T.CLIFF: ((86, 82, 92), "cliff"),
    T.RUIN: ((146, 146, 136), "slab"), T.COBBLE: ((170, 168, 164), "cobble"), T.WOODFLOOR: ((150, 108, 70), "plank"),
    T.CAVE: ((78, 70, 64), "cave"), T.CAVEWALL: ((38, 34, 36), "brick"), T.CRYPT: ((84, 82, 100), "slab"),
    T.CRYPTWALL: ((44, 42, 58), "brick"), T.VOID: ((6, 6, 10), "none"), T.BOG: ((66, 92, 64), "bog"),
    T.BLIGHT: ((92, 62, 98), "moor"), T.CARPET: ((140, 52, 56), "carpet"),
}


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


@lru_cache(maxsize=2048)
def ground_tile(gid: int, variant: int, house: bool = False) -> pygame.Surface:
    base, kind = GROUND_STYLE.get(gid, ((120, 120, 120), "none"))
    if house and gid == T.CRYPTWALL:
        base, kind = (92, 66, 44), "wood"
    s = pygame.Surface((TS, TS))
    s.fill(base)
    r = random.Random(gid * 131 + variant * 17)
    dark, light = _shade(base, 0.82), _shade(base, 1.14)
    if kind in ("grass", "leaf", "moor"):
        for _ in range(9):
            x, y = r.randrange(TS), r.randrange(TS)
            c = dark if r.random() < 0.55 else light
            pygame.draw.line(s, c, (x, y), (x + r.choice((-1, 0, 1)), y - r.randrange(2, 4)))
    elif kind == "water":
        for _ in range(4):
            x, y = r.randrange(1, TS - 6), r.randrange(1, TS - 1)
            pygame.draw.line(s, light if gid == T.SHALLOW else _shade(base, 1.25), (x, y), (x + r.randrange(3, 6), y))
    elif kind in ("sand", "mud", "dirt", "bog"):
        for _ in range(14):
            s.set_at((r.randrange(TS), r.randrange(TS)), dark if r.random() < 0.6 else light)
        if kind == "bog":
            for _ in range(3):
                pygame.draw.circle(s, _shade(base, 0.7), (r.randrange(2, 14), r.randrange(2, 14)), r.randrange(1, 3))
    elif kind in ("road", "cobble", "slab"):
        n = 4 if kind != "slab" else 2
        step = TS // n
        for j in range(n):
            off = (step // 2) if (j % 2 and kind != "slab") else 0
            for i in range(-1, n + 1):
                rect = pygame.Rect(i * step + off, j * step, step, step)
                pygame.draw.rect(s, _shade(base, r.uniform(0.94, 1.06)), rect.inflate(-1, -1))
                pygame.draw.rect(s, dark, rect, 1)
    elif kind == "plank":
        for j in range(0, TS, 4):
            pygame.draw.line(s, dark, (0, j), (TS, j))
            if r.random() < 0.5:
                pygame.draw.line(s, light, (r.randrange(TS), j + 1), (r.randrange(TS), j + 2))
        for j in range(0, TS, 4):
            s.set_at((r.randrange(TS), j + 2), dark)
    elif kind == "wood":
        for i in range(0, TS, 4):
            pygame.draw.line(s, _shade(base, 0.78), (i, 0), (i, TS))
        pygame.draw.line(s, _shade(base, 1.25), (0, 0), (TS, 0))
    elif kind == "furrow":
        for j in range(2, TS, 4):
            pygame.draw.line(s, dark, (0, j), (TS, j))
            pygame.draw.line(s, light, (0, j + 1), (TS, j + 1))
    elif kind == "cliff":
        for _ in range(4):
            x, y = r.randrange(TS), r.randrange(TS)
            pygame.draw.line(s, _shade(base, 0.6), (x, y), (x + r.randrange(-3, 4), y + r.randrange(3, 7)), 2)
        pygame.draw.line(s, light, (0, 0), (TS, 0))
    elif kind == "rock":
        for _ in range(5):
            pygame.draw.circle(s, dark if r.random() < 0.5 else light, (r.randrange(TS), r.randrange(TS)), r.randrange(1, 3))
    elif kind == "cave":
        for _ in range(12):
            s.set_at((r.randrange(TS), r.randrange(TS)), dark if r.random() < 0.7 else light)
    elif kind == "brick":
        for j in range(0, TS, 4):
            pygame.draw.line(s, _shade(base, 0.6), (0, j), (TS, j))
            off = 4 if (j // 4) % 2 else 0
            for i in range(off, TS, 8):
                pygame.draw.line(s, _shade(base, 0.6), (i, j), (i, j + 3))
        pygame.draw.line(s, _shade(base, 1.5), (0, 0), (TS, 0))
    elif kind == "carpet":
        pygame.draw.rect(s, _shade(base, 0.72), (0, 0, TS, TS), 1)
        pygame.draw.rect(s, (218, 176, 82), (3, 3, TS - 6, TS - 6), 1)
    return s


_EDGE_PRIO = T.GROUND_PRIO


@lru_cache(maxsize=512)
def edge_overlay(gid: int, side: int, variant: int) -> pygame.Surface:
    """Spill of ground ``gid`` over a neighbouring tile along ``side`` (0 E, 1 S, 2 W, 3 N): a wavy 5px band."""
    tile = ground_tile(gid, variant & 3)
    mask = pygame.Surface((TS, TS), pygame.SRCALPHA)
    r = random.Random(gid * 7 + side * 3 + variant)
    depth = [r.randrange(3, 6) for _ in range(TS)]
    for i in range(TS):
        d = depth[i]
        for k in range(d):
            a = 255 if k < d - 2 else 140
            if side == 0:
                mask.set_at((TS - 1 - k, i), (255, 255, 255, a))
            elif side == 2:
                mask.set_at((k, i), (255, 255, 255, a))
            elif side == 1:
                mask.set_at((i, TS - 1 - k), (255, 255, 255, a))
            else:
                mask.set_at((i, k), (255, 255, 255, a))
    out = pygame.Surface((TS, TS), pygame.SRCALPHA)
    out.blit(tile, (0, 0))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def build_chunk(wm, cx: int, cy: int, house: bool) -> pygame.Surface:
    surf = pygame.Surface((CHUNK * TS, CHUNK * TS))
    surf.fill((6, 6, 10))
    g = wm.ground
    H, W = g.shape
    x0, y0 = cx * CHUNK, cy * CHUNK
    for ty in range(CHUNK):
        y = y0 + ty
        if y >= H:
            break
        for tx in range(CHUNK):
            x = x0 + tx
            if x >= W:
                break
            gid = int(g[y, x])
            v = (x * 7 + y * 13 + (x * y) % 5) & 3
            surf.blit(ground_tile(gid, v, house), (tx * TS, ty * TS))
            if gid in (T.VOID, T.CLIFF, T.CAVEWALL, T.CRYPTWALL):
                continue
            pr = _EDGE_PRIO.get(gid, 5)
            for side, (dx, dy) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1))):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                ng = int(g[ny, nx])
                if ng == gid or ng in (T.VOID, T.CLIFF, T.CAVEWALL, T.CRYPTWALL):
                    continue
                if _EDGE_PRIO.get(ng, 5) > pr:
                    surf.blit(edge_overlay(ng, side, v), (tx * TS, ty * TS))
    return surf


# ------------------------------------------------------------------------------------------ objects
def _hash_var(x: int, y: int) -> int:
    return T.hash2(x, y) & 7


def _sp(w: int = TS, h: int = TS) -> pygame.Surface:
    return pygame.Surface((w, h), pygame.SRCALPHA)


def _circ(s, c, p, r):
    pygame.draw.circle(s, c, p, r)


def _tree(kind: str, v: int) -> pygame.Surface:
    s = _sp(TS, TS * 2)
    r = random.Random(v * 31 + len(kind))
    leaf = [(54, 118, 58), (64, 130, 62), (46, 104, 56), (72, 138, 66)][v % 4]
    if kind == "oak":
        pygame.draw.rect(s, (92, 64, 40), (6, 18, 4, 14))
        pygame.draw.rect(s, (70, 48, 30), (6, 18, 1, 14))
        for (cx, cy, rad) in ((8, 10, 8), (4, 14, 5), (12, 14, 5), (8, 6, 5)):
            _circ(s, _shade(leaf, 0.8), (cx, cy + 1), rad)
        for (cx, cy, rad) in ((8, 9, 7), (5, 13, 4), (11, 13, 4)):
            _circ(s, leaf, (cx, cy), rad)
        for _ in range(7):
            pygame.draw.circle(s, _shade(leaf, 1.25), (r.randrange(3, 13), r.randrange(3, 14)), 1)
    elif kind == "pine":
        pygame.draw.rect(s, (80, 56, 36), (7, 24, 2, 8))
        for i, (w, y) in enumerate(((14, 22), (11, 16), (8, 10), (5, 5))):
            pygame.draw.polygon(s, _shade((36, 88, 62), 0.9 + 0.1 * i), [(8, y - 7), (8 - w // 2, y), (8 + w // 2, y)])
    elif kind == "dead":
        pygame.draw.line(s, (80, 66, 58), (8, 32), (8, 10), 2)
        for (x1, y1, x2, y2) in ((8, 20, 3, 14), (8, 16, 13, 9), (8, 24, 13, 20), (8, 12, 5, 6)):
            pygame.draw.line(s, (70, 58, 52), (x1, y1), (x2, y2), 1)
    else:  # willow
        pygame.draw.rect(s, (84, 70, 50), (7, 16, 3, 16))
        _circ(s, (86, 126, 84), (8, 10), 8)
        for i in range(-7, 8, 2):
            pygame.draw.line(s, (112, 156, 100), (8 + i, 12), (8 + i + r.choice((-1, 0, 1)), 22 + abs(i) // 2))
    return s


def _simple(name: str, v: int) -> pygame.Surface:
    h = T.OBJ_LIST[T.O[name]].height
    s = _sp(TS, TS * h)
    r = random.Random(v * 53 + sum(map(ord, name)))
    H = TS * h
    B = H - 1  # bottom row
    if name == "bush":
        for (cx, cy, rad) in ((8, 10, 5), (4, 11, 4), (12, 11, 4)):
            _circ(s, (52, 110, 56), (cx, cy), rad)
        _circ(s, (70, 136, 70), (7, 9), 3)
    elif name == "berry":
        _simple_bush = _simple("bush", v)
        s.blit(_simple_bush, (0, 0))
        for _ in range(5):
            s.set_at((r.randrange(3, 13), r.randrange(7, 14)), (190, 40, 90))
            _circ(s, (200, 50, 100), (r.randrange(3, 13), r.randrange(7, 14)), 1)
    elif name == "boulder":
        pygame.draw.ellipse(s, (112, 112, 118), (1, 5, 14, 10))
        pygame.draw.ellipse(s, (140, 140, 146), (3, 6, 8, 5))
        pygame.draw.ellipse(s, (80, 80, 88), (1, 11, 14, 4), 1)
    elif name == "stones":
        for _ in range(3):
            _circ(s, (128, 126, 130), (r.randrange(3, 13), r.randrange(8, 14)), r.randrange(1, 3))
    elif name in ("reeds", "cattail"):
        for i in range(3, 14, 3):
            x = i + r.randrange(-1, 2)
            pygame.draw.line(s, (96, 142, 78), (x, 15), (x + r.choice((-1, 0, 1)), 4 + r.randrange(0, 4)))
            if name == "cattail":
                pygame.draw.rect(s, (110, 70, 40), (x - 1, 3 + r.randrange(0, 3), 2, 4))
    elif name == "flowers":
        for _ in range(5):
            x, y = r.randrange(2, 14), r.randrange(6, 14)
            pygame.draw.line(s, (60, 120, 60), (x, y), (x, y + 2))
            s.set_at((x, y - 1), r.choice([(240, 230, 120), (230, 120, 160), (200, 160, 240), (255, 255, 255)]))
            s.set_at((x + 1, y), (255, 240, 180))
    elif name == "tuft":
        for _ in range(3):
            x = r.randrange(3, 13)
            pygame.draw.line(s, (68, 128, 64), (x, 14), (x + r.choice((-2, -1, 1, 2)), 9))
    elif name == "mushroom":
        for _ in range(2):
            x, y = r.randrange(3, 12), r.randrange(8, 13)
            pygame.draw.rect(s, (230, 220, 200), (x, y + 1, 2, 3))
            pygame.draw.ellipse(s, (200, 70, 70), (x - 2, y - 2, 6, 4))
            s.set_at((x, y - 1), (255, 240, 230))
    elif name == "standing":
        pygame.draw.polygon(s, (88, 90, 104), [(4, B), (5, 6), (8, 2), (11, 6), (12, B)])
        pygame.draw.line(s, (120, 124, 144), (6, 8), (6, B - 2))
        pygame.draw.line(s, (130, 200, 255), (8, 8), (8, 12))
    elif name == "pillar":
        pygame.draw.rect(s, (150, 148, 140), (4, 4, 8, B - 4))
        pygame.draw.rect(s, (176, 174, 166), (3, 2, 10, 3))
        pygame.draw.rect(s, (176, 174, 166), (3, B - 2, 10, 3))
        pygame.draw.line(s, (110, 108, 100), (7, 6), (7, B - 3))
    elif name == "ruinwall":
        for j in range(3):
            for i in range(0, 16, 6):
                pygame.draw.rect(s, (132, 130, 120), (i + (3 if j % 2 else 0), 4 + j * 4, 6, 4), 0)
                pygame.draw.rect(s, (92, 90, 84), (i + (3 if j % 2 else 0), 4 + j * 4, 6, 4), 1)
    elif name == "fence":
        pygame.draw.line(s, (130, 96, 62), (0, 9), (15, 9), 2)
        pygame.draw.line(s, (130, 96, 62), (0, 12), (15, 12), 2)
        for x in (1, 8, 14):
            pygame.draw.rect(s, (104, 74, 48), (x, 6, 2, 9))
    elif name in ("lamp", "lamp_lit"):
        pygame.draw.rect(s, (46, 44, 54), (7, 12, 2, H - 12))
        pygame.draw.rect(s, (60, 58, 70), (5, B - 1, 6, 2))
        pygame.draw.rect(s, (40, 40, 52), (4, 3, 8, 3))
        pygame.draw.polygon(s, (40, 40, 52), [(4, 3), (8, 0), (12, 3)])
        pygame.draw.rect(s, (255, 214, 120) if name == "lamp_lit" else (80, 92, 110), (5, 6, 6, 7))
        if name == "lamp_lit":
            pygame.draw.rect(s, (255, 244, 190), (7, 8, 2, 3))
    elif name == "well":
        pygame.draw.ellipse(s, (96, 92, 100), (2, 6, 12, 9))
        pygame.draw.ellipse(s, (28, 52, 82), (4, 7, 8, 5))
        pygame.draw.rect(s, (110, 80, 52), (2, 0, 2, 9))
        pygame.draw.rect(s, (110, 80, 52), (12, 0, 2, 9))
        pygame.draw.rect(s, (140, 100, 62), (1, 0, 14, 2))
    elif name == "stall":
        pygame.draw.rect(s, (130, 94, 62), (1, 8, 14, 7))
        pygame.draw.rect(s, (190, 60, 56), (0, 4, 16, 4))
        for i in range(0, 16, 4):
            pygame.draw.rect(s, (236, 226, 200), (i, 4, 2, 4))
    elif name == "barrel":
        pygame.draw.ellipse(s, (130, 90, 56), (3, 3, 10, 12))
        pygame.draw.line(s, (60, 46, 36), (3, 7), (12, 7))
        pygame.draw.line(s, (60, 46, 36), (3, 11), (12, 11))
    elif name == "crate":
        pygame.draw.rect(s, (160, 120, 78), (2, 3, 12, 12))
        pygame.draw.rect(s, (110, 80, 52), (2, 3, 12, 12), 1)
        pygame.draw.line(s, (110, 80, 52), (2, 3), (13, 14))
    elif name == "notice":
        pygame.draw.rect(s, (110, 80, 52), (2, 4, 12, 8))
        pygame.draw.rect(s, (86, 60, 40), (2, 4, 12, 8), 1)
        for (x, y) in ((4, 6), (8, 6), (5, 9), (10, 9)):
            pygame.draw.rect(s, (236, 226, 200), (x, y, 3, 2))
        pygame.draw.rect(s, (86, 60, 40), (4, 12, 2, 4))
        pygame.draw.rect(s, (86, 60, 40), (10, 12, 2, 4))
    elif name == "haystack":
        pygame.draw.ellipse(s, (206, 176, 80), (1, 4, 14, 11))
        for i in range(5):
            pygame.draw.line(s, (170, 140, 56), (3 + i * 2, 6), (4 + i * 2, 13))
    elif name == "campfire":
        for a in (20, 80, 140):
            pygame.draw.line(s, (96, 66, 40), (8, 13), (8 + int(5 * math.cos(math.radians(a))), 13 - int(3 * math.sin(math.radians(a)))), 2)
        pygame.draw.polygon(s, (255, 150, 60), [(5, 12), (8, 4), (11, 12)])
        pygame.draw.polygon(s, (255, 226, 120), [(7, 12), (8, 7), (9, 12)])
    elif name == "tent":
        pygame.draw.polygon(s, (140, 106, 76), [(0, B), (8, 4), (16, B)])
        pygame.draw.polygon(s, (110, 80, 56), [(8, 4), (16, B), (9, B)])
        pygame.draw.polygon(s, (30, 24, 24), [(6, B), (8, 20), (10, B)])
    elif name == "ore":
        pygame.draw.ellipse(s, (96, 94, 102), (1, 5, 14, 10))
        for _ in range(6):
            s.set_at((r.randrange(3, 13), r.randrange(7, 13)), (200, 110, 80))
        pygame.draw.rect(s, (210, 120, 86), (5, 8, 2, 2))
        pygame.draw.rect(s, (210, 120, 86), (10, 10, 2, 2))
    elif name == "reedmint":
        for i in (4, 8, 11):
            pygame.draw.line(s, (96, 190, 140), (i, 15), (i + 1, 5))
            pygame.draw.circle(s, (170, 240, 200), (i + 1, 5), 1)
    elif name == "heather":
        for i in (3, 7, 11):
            pygame.draw.line(s, (92, 74, 100), (i, 15), (i, 8))
            for j in range(3):
                s.set_at((i + r.choice((-1, 0, 1)), 6 + j), (180, 100, 190))
    elif name == "flax":
        for i in (4, 8, 11):
            pygame.draw.line(s, (92, 150, 84), (i, 15), (i, 6))
            s.set_at((i, 5), (150, 170, 240))
            s.set_at((i + 1, 6), (170, 190, 250))
    elif name == "chest":
        pygame.draw.rect(s, (130, 86, 48), (2, 6, 12, 8))
        pygame.draw.rect(s, (160, 108, 60), (2, 4, 12, 4))
        pygame.draw.rect(s, (60, 40, 28), (2, 4, 12, 10), 1)
        pygame.draw.rect(s, (230, 190, 80), (7, 8, 2, 3))
    elif name == "grave":
        pygame.draw.rect(s, (130, 130, 136), (4, 4, 8, 11), border_top_left_radius=4, border_top_right_radius=4)
        pygame.draw.line(s, (90, 90, 96), (8, 6), (8, 10))
        pygame.draw.line(s, (90, 90, 96), (6, 8), (10, 8))
    elif name == "statue":
        pygame.draw.rect(s, (130, 128, 134), (4, B - 5, 8, 5))
        pygame.draw.rect(s, (160, 158, 164), (6, 8, 4, B - 13))
        _circ(s, (170, 168, 174), (8, 6), 3)
        pygame.draw.line(s, (160, 158, 164), (3, 12), (13, 12), 2)
    elif name == "brazier":
        pygame.draw.rect(s, (60, 54, 56), (6, 10, 4, 5))
        pygame.draw.polygon(s, (60, 54, 56), [(3, 8), (13, 8), (10, 11), (6, 11)])
        pygame.draw.polygon(s, (255, 150, 60), [(5, 8), (8, 2), (11, 8)])
        pygame.draw.polygon(s, (255, 226, 120), [(7, 8), (8, 4), (9, 8)])
    elif name == "bed":
        pygame.draw.rect(s, (120, 84, 56), (1, 3, 14, 12))
        pygame.draw.rect(s, (222, 218, 204), (2, 4, 12, 4))
        pygame.draw.rect(s, (96, 120, 170), (2, 8, 12, 6))
    elif name == "table":
        pygame.draw.rect(s, (150, 106, 66), (0, 5, 16, 8))
        pygame.draw.rect(s, (110, 78, 50), (0, 5, 16, 8), 1)
        pygame.draw.rect(s, (96, 66, 44), (1, 13, 2, 3))
        pygame.draw.rect(s, (96, 66, 44), (13, 13, 2, 3))
    elif name == "counter":
        pygame.draw.rect(s, (130, 92, 58), (0, 4, 16, 11))
        pygame.draw.rect(s, (174, 128, 80), (0, 3, 16, 3))
        pygame.draw.rect(s, (96, 66, 44), (0, 3, 16, 12), 1)
    elif name == "hearth":
        pygame.draw.rect(s, (110, 106, 110), (0, 0, 16, H))
        pygame.draw.rect(s, (30, 26, 30), (3, 5, 10, 10))
        pygame.draw.polygon(s, (255, 150, 60), [(5, 14), (8, 7), (11, 14)])
        pygame.draw.polygon(s, (255, 226, 120), [(7, 14), (8, 10), (9, 14)])
    elif name == "shelf":
        pygame.draw.rect(s, (112, 78, 50), (0, 0, 16, H))
        for j in range(3, H, 8):
            pygame.draw.line(s, (80, 54, 36), (0, j), (15, j), 2)
            for _ in range(3):
                pygame.draw.rect(s, r.choice([(190, 70, 70), (70, 120, 190), (220, 190, 90), (100, 170, 110)]), (r.randrange(1, 12), j - 4, 3, 4))
    elif name == "bench":
        pygame.draw.rect(s, (140, 100, 62), (1, 8, 14, 4))
        pygame.draw.rect(s, (96, 66, 44), (2, 12, 2, 3))
        pygame.draw.rect(s, (96, 66, 44), (12, 12, 2, 3))
    elif name == "forge":
        pygame.draw.rect(s, (92, 88, 92), (0, 0, 16, H))
        pygame.draw.rect(s, (24, 20, 22), (3, 6, 10, 9))
        pygame.draw.rect(s, (255, 130, 50), (4, 10, 8, 5))
        pygame.draw.rect(s, (255, 214, 110), (6, 12, 4, 3))
    elif name == "anvil":
        pygame.draw.rect(s, (70, 70, 78), (3, 7, 10, 3))
        pygame.draw.rect(s, (60, 60, 68), (5, 10, 6, 4))
        pygame.draw.polygon(s, (70, 70, 78), [(13, 7), (16, 8), (13, 10)])
    elif name == "hiddendoor":
        pygame.draw.rect(s, (100, 100, 108), (0, 0, 16, H))
        pygame.draw.rect(s, (130, 130, 140), (3, 6, 10, B - 6), 1)
        pygame.draw.circle(s, (130, 200, 255), (8, 14), 2, 1)
    elif name == "signpost":
        pygame.draw.rect(s, (96, 66, 44), (7, 4, 2, 11))
        pygame.draw.polygon(s, (170, 128, 80), [(2, 4), (13, 4), (15, 6), (13, 8), (2, 8)])
    elif name == "boat":
        pygame.draw.ellipse(s, (120, 82, 50), (0, 6, 16, 8))
        pygame.draw.ellipse(s, (70, 50, 36), (2, 8, 12, 4))
    elif name == "net":
        for i in range(0, 16, 4):
            pygame.draw.line(s, (180, 170, 140), (i, 4), (i, 14))
            pygame.draw.line(s, (180, 170, 140), (0, 4 + i // 2 * 2), (15, 4 + i // 2 * 2))
        pygame.draw.rect(s, (96, 66, 44), (0, 3, 16, 2))
    elif name == "pierpost":
        pygame.draw.rect(s, (100, 72, 48), (6, 5, 4, 10))
        pygame.draw.rect(s, (130, 96, 62), (5, 4, 6, 2))
    elif name == "stairdown":
        pygame.draw.rect(s, (30, 26, 34), (1, 1, 14, 14))
        for i in range(4):
            pygame.draw.rect(s, (60 + i * 18, 56 + i * 16, 64 + i * 14), (2 + i, 2 + i * 3, 12 - 2 * i, 3))
    elif name == "stairup":
        pygame.draw.rect(s, (30, 26, 34), (1, 1, 14, 14))
        for i in range(4):
            pygame.draw.rect(s, (130 - i * 18, 126 - i * 16, 140 - i * 14), (2 + i, 2 + i * 3, 12 - 2 * i, 3))
        pygame.draw.polygon(s, (255, 230, 150), [(8, 3), (5, 7), (11, 7)])
    elif name == "ringtree":
        s.blit(_tree("oak", v + 3), (0, 0))
    elif name == "banner":
        pygame.draw.rect(s, (96, 66, 44), (7, 0, 2, H))
        pygame.draw.polygon(s, (190, 60, 56), [(9, 3), (15, 3), (15, 13), (12, 10), (9, 13)])
    elif name == "barricade":
        pygame.draw.line(s, (120, 86, 56), (1, 14), (15, 6), 3)
        pygame.draw.line(s, (120, 86, 56), (1, 6), (15, 14), 3)
        pygame.draw.line(s, (80, 56, 40), (1, 10), (15, 10), 2)
    elif name == "stump":
        pygame.draw.ellipse(s, (110, 78, 50), (3, 7, 10, 7))
        pygame.draw.ellipse(s, (170, 130, 86), (3, 6, 10, 5))
    elif name == "log":
        pygame.draw.rect(s, (110, 78, 50), (1, 8, 14, 6), border_radius=3)
        pygame.draw.ellipse(s, (170, 130, 86), (0, 8, 4, 6))
    elif name == "brokenplank":
        pygame.draw.line(s, (130, 96, 62), (2, 10), (13, 7), 2)
    elif name == "glowmoss":
        for _ in range(8):
            s.set_at((r.randrange(2, 14), r.randrange(2, 14)), (120, 230, 170))
        pygame.draw.circle(s, (80, 190, 140), (8, 8), 4, 1)
    elif name == "cairn":
        for (x, y, rad) in ((8, 12, 5), (7, 8, 3), (9, 5, 2)):
            _circ(s, (128, 126, 130), (x, y), rad)
    elif name == "dig":
        pygame.draw.ellipse(s, (96, 76, 54), (2, 8, 12, 6))
        pygame.draw.ellipse(s, (62, 48, 36), (4, 9, 8, 4))
        pygame.draw.line(s, (196, 160, 100), (11, 3), (8, 11), 1)
    elif name == "rug":
        pygame.draw.rect(s, (150, 60, 60), (1, 1, 14, 14))
        pygame.draw.rect(s, (220, 178, 84), (3, 3, 10, 10), 1)
    elif name == "candle":
        pygame.draw.rect(s, (236, 226, 190), (7, 9, 2, 5))
        pygame.draw.polygon(s, (255, 200, 90), [(7, 9), (8, 5), (9, 9)])
    elif name in ("greatlamp", "greatlamp_lit"):
        pygame.draw.rect(s, (76, 70, 80), (6, 12, 4, H - 12))
        pygame.draw.rect(s, (96, 90, 100), (3, B - 2, 10, 3))
        pygame.draw.rect(s, (60, 56, 66), (3, 4, 10, 10))
        lit = name == "greatlamp_lit"
        pygame.draw.rect(s, (255, 226, 130) if lit else (60, 70, 90), (5, 6, 6, 7))
        pygame.draw.polygon(s, (60, 56, 66), [(2, 4), (8, 0), (14, 4)])
    elif name == "tablet":
        pygame.draw.rect(s, (96, 96, 112), (3, 2, 10, 13), border_top_left_radius=4, border_top_right_radius=4)
        for j in range(4):
            pygame.draw.line(s, (130, 200, 255), (5, 5 + j * 2), (11, 5 + j * 2))
    return s


@lru_cache(maxsize=1024)
def obj_sprite(oid: int, variant: int) -> pygame.Surface:
    name = T.OBJ_LIST[oid].name
    if name in ("oak", "pine", "dead", "willow"):
        return _tree(name, variant)
    return _simple(name, variant)


# ------------------------------------------------------------------------------------------ buildings
STYLE_COLORS = {
    "cottage": ((176, 74, 58), (214, 194, 150)), "inn": ((150, 70, 52), (226, 204, 160)), "shop": ((70, 112, 150), (222, 204, 164)),
    "smithy": ((92, 88, 100), (184, 176, 168)), "hall": ((88, 94, 130), (200, 196, 190)), "lamp_house": ((60, 100, 90), (220, 200, 150)),
    "farmhouse": ((156, 96, 62), (232, 214, 170)), "longhouse": ((94, 86, 70), (178, 168, 150)), "hut": ((108, 126, 70), (170, 150, 110)),
    "ruined_hall": ((90, 90, 98), (140, 138, 130)), "chapel": ((92, 98, 110), (196, 196, 200)),
}


@lru_cache(maxsize=128)
def building_sprite(style: str, w: int, h: int, door: int, night: bool, lit: bool, label_hash: int) -> pygame.Surface:
    """Façade for a w*h-tile footprint.  The roof covers the upper rows; the wall and door fill the bottom row."""
    roof, wall = STYLE_COLORS.get(style, STYLE_COLORS["cottage"])
    W, H = w * TS, h * TS
    s = pygame.Surface((W, H + 8), pygame.SRCALPHA)
    r = random.Random(label_hash)
    ruined = style == "ruined_hall"
    wall_h = TS + 4
    pygame.draw.rect(s, wall, (0, H - wall_h + 8, W, wall_h))
    pygame.draw.rect(s, _shade(wall, 0.7), (0, H - wall_h + 8, W, wall_h), 1)
    for x in range(0, W, 6):
        pygame.draw.line(s, _shade(wall, 0.9), (x, H - wall_h + 9), (x, H + 6))
    roof_h = H - wall_h + 10
    pts = [(-3, roof_h), (W // 2, 2), (W + 3, roof_h)] if style not in ("hall", "longhouse") else [(-3, roof_h), (4, 2), (W - 4, 2), (W + 3, roof_h)]
    pygame.draw.polygon(s, roof, pts)
    pygame.draw.polygon(s, _shade(roof, 0.7), pts, 1)
    for y in range(6, roof_h, 5):
        pygame.draw.line(s, _shade(roof, 0.84), (4, y), (W - 4, y))
    if ruined:
        for _ in range(7):
            pygame.draw.rect(s, (0, 0, 0, 0), (r.randrange(0, W - 6), r.randrange(0, roof_h - 4), r.randrange(4, 9), r.randrange(3, 7)))
    # chimney
    if style in ("cottage", "inn", "smithy", "farmhouse", "longhouse", "lamp_house"):
        cx = W - 10 - (w * 2 % 7)
        pygame.draw.rect(s, (96, 88, 90), (cx, 0, 5, 12))
        pygame.draw.rect(s, (60, 56, 60), (cx - 1, 0, 7, 2))
    # windows
    win = (255, 214, 120) if (night and lit) else (92, 118, 150)
    nwin = max(1, w // 3)
    wy = H - wall_h + 11
    for i in range(nwin):
        wx = int((i + 0.5) * (W / nwin)) - 3
        if abs(wx + 3 - (door * TS + TS // 2)) < 9:
            continue
        pygame.draw.rect(s, (60, 44, 34), (wx - 1, wy - 1, 8, 9))
        pygame.draw.rect(s, win, (wx, wy, 6, 7))
        pygame.draw.line(s, (60, 44, 34), (wx + 3, wy), (wx + 3, wy + 6))
    # door
    dx = door * TS + 3
    pygame.draw.rect(s, (70, 48, 34), (dx - 1, H - 13 + 8, 12, 13))
    pygame.draw.rect(s, (110, 76, 50), (dx, H - 12 + 8, 10, 12))
    pygame.draw.rect(s, (240, 200, 90), (dx + 7, H - 6 + 8, 2, 2))
    if style in ("shop", "smithy"):
        pygame.draw.rect(s, (96, 66, 44), (dx - 10, H - 24 + 8, 4, 8))
        pygame.draw.circle(s, (230, 190, 90), (dx - 8, H - 20 + 8), 3)
    return s


# ------------------------------------------------------------------------------------------ people & creatures
@lru_cache(maxsize=512)
def person(skin, cloth, hair, facing: int, phase: int, mode: str = "", extra: tuple = ()) -> pygame.Surface:
    """12x18 villager.  ``facing``: 0 down, 1 left, 2 right, 3 up.  ``phase`` 0..3 walk frame."""
    s = _sp(14, 20)
    sway = (0, 1, 0, -1)[phase & 3]
    # shadow
    pygame.draw.ellipse(s, (0, 0, 0, 60), (2, 16, 10, 4))
    # legs
    lw = 2
    leg = _shade(cloth, 0.55)
    pygame.draw.rect(s, leg, (4, 12, lw, 5 - (1 if sway > 0 else 0)))
    pygame.draw.rect(s, leg, (8, 12, lw, 5 - (1 if sway < 0 else 0)))
    # body
    pygame.draw.rect(s, cloth, (3, 6, 8, 7), border_radius=2)
    pygame.draw.rect(s, _shade(cloth, 1.2), (3, 6, 8, 2))
    # arms
    ay = 7 + sway
    pygame.draw.rect(s, _shade(cloth, 0.8), (2, ay, 2, 5))
    pygame.draw.rect(s, _shade(cloth, 0.8), (10, 7 - sway, 2, 5))
    # head
    pygame.draw.circle(s, skin, (7, 4), 3)
    if facing == 3:
        pygame.draw.circle(s, hair, (7, 4), 3)
    else:
        pygame.draw.rect(s, hair, (4, 1, 6, 2))
        ex = {0: (6, 8), 1: (5, 6), 2: (8, 9)}[facing]
        for x in ex[:2] if facing == 0 else ex[:1]:
            s.set_at((x, 4), (30, 24, 28))
    if mode == "hood":
        pygame.draw.polygon(s, _shade(cloth, 0.65), [(3, 5), (7, 0), (11, 5)])
    if mode == "cloak":
        pygame.draw.polygon(s, _shade(cloth, 0.8), [(2, 6), (12, 6), (13, 14), (1, 14)])
        pygame.draw.rect(s, cloth, (4, 6, 6, 8))
    if mode == "lantern":
        pygame.draw.line(s, (60, 50, 40), (12, 8), (13, 11))
        pygame.draw.rect(s, (255, 214, 120), (12, 11, 3, 4))
    return s


def _flash(surf: pygame.Surface, amount: float) -> pygame.Surface:
    out = surf.copy()
    out.fill((int(255 * amount),) * 3 + (0,), special_flags=pygame.BLEND_RGB_ADD)
    return out


@lru_cache(maxsize=512)
def creature(kind: str, facing: int, phase: int, size10: int, flash: bool = False, guard: bool = False) -> pygame.Surface:
    sz = size10 / 10.0
    base = {"wolf": (122, 124, 134), "bandit": (150, 90, 70), "bandit_archer": (110, 122, 78), "bogwight": (78, 110, 78),
            "shade": (150, 140, 200), "drowned": (90, 132, 142), "crawler": (112, 92, 62), "rook_captain": (172, 60, 52),
            "debt_collector": (190, 170, 232), "bell_warden": (92, 172, 162), "root_mother": (122, 152, 70)}.get(kind, (160, 160, 160))
    W = int(24 * sz) + 8
    s = _sp(W, W + 4)
    cx, cy = W // 2, W // 2 + 2
    sway = (0, 1, 0, -1)[phase & 3]
    if kind == "wolf":
        pygame.draw.ellipse(s, (0, 0, 0, 60), (cx - 8, cy + 3, 16, 5))
        d = -1 if facing == 1 else 1
        pygame.draw.ellipse(s, base, (cx - 7, cy - 4, 14, 8))
        pygame.draw.ellipse(s, _shade(base, 1.2), (cx - 5, cy - 4, 9, 4))
        pygame.draw.circle(s, base, (cx + 7 * d, cy - 3), 3)
        pygame.draw.polygon(s, base, [(cx + 6 * d, cy - 8), (cx + 8 * d, cy - 5), (cx + 5 * d, cy - 5)])
        pygame.draw.line(s, (220, 60, 50), (cx + 8 * d, cy - 3), (cx + 8 * d, cy - 3))
        pygame.draw.line(s, base, (cx - 7 * d, cy - 2), (cx - 11 * d, cy - 5 + sway), 2)
        for lx in (-5, -2, 2, 5):
            pygame.draw.line(s, _shade(base, 0.7), (cx + lx, cy + 3), (cx + lx + sway * (1 if lx % 2 else -1), cy + 7))
    elif kind in ("bandit", "bandit_archer", "drowned", "rook_captain", "debt_collector", "bell_warden"):
        skin = {"drowned": (150, 190, 180), "debt_collector": (200, 196, 220)}.get(kind, (226, 184, 150))
        mode = {"bandit": "hood", "bandit_archer": "hood", "debt_collector": "cloak", "drowned": "", "rook_captain": "", "bell_warden": ""}[kind]
        p = person(skin, base, _shade(base, 0.5), facing, phase, mode)
        sc = max(1.0, sz * 1.0)
        p = pygame.transform.scale(p, (int(p.get_width() * sc), int(p.get_height() * sc))) if sc != 1.0 else p
        s.blit(p, (cx - p.get_width() // 2, W + 4 - p.get_height() - 2))
        if kind == "bandit_archer":
            pygame.draw.arc(s, (150, 110, 70), (cx + 3, cy - 6, 7, 12), -1.2, 1.2, 1)
        if kind == "rook_captain":
            pygame.draw.polygon(s, (60, 60, 70), [(cx - 12, cy - 8), (cx - 7, cy - 18), (cx - 4, cy - 8)])
        if kind == "bell_warden":
            pygame.draw.polygon(s, (214, 184, 90), [(cx - 7, cy - 14), (cx + 7, cy - 14), (cx + 10, cy - 2), (cx - 10, cy - 2)])
            pygame.draw.circle(s, (240, 214, 120), (cx, cy - 1), 2)
        if kind == "debt_collector":
            pygame.draw.rect(s, (160, 120, 80), (cx + 6, cy - 6, 6, 8))
            pygame.draw.line(s, (60, 40, 30), (cx + 7, cy - 4), (cx + 11, cy - 4))
    elif kind == "bogwight":
        pygame.draw.ellipse(s, (0, 0, 0, 60), (cx - 7, cy + 3, 14, 5))
        pygame.draw.ellipse(s, base, (cx - 7, cy - 8, 14, 14))
        pygame.draw.ellipse(s, _shade(base, 1.3), (cx - 4, cy - 7, 8, 6))
        for dx in (-5, 3):
            pygame.draw.line(s, (60, 110, 64), (cx + dx, cy - 6), (cx + dx + sway, cy - 12), 1)
        for dx in (-3, 2):
            s.set_at((cx + dx, cy - 3), (255, 240, 120))
            s.set_at((cx + dx + 1, cy - 3), (255, 240, 120))
    elif kind == "shade":
        for i in range(5):
            a = 150 - i * 28
            pygame.draw.ellipse(s, (*base, max(10, a)), (cx - 6 + i // 2, cy - 8 + i * 3, 12 - i * 2, 8))
        pygame.draw.circle(s, (240, 230, 255), (cx - 2, cy - 6), 1)
        pygame.draw.circle(s, (240, 230, 255), (cx + 2, cy - 6), 1)
    elif kind == "crawler":
        for i in range(4):
            pygame.draw.circle(s, _shade(base, 1.0 - i * 0.08), (cx - 6 + i * 4, cy + (sway if i % 2 else -sway)), 3)
        for i in range(4):
            x = cx - 6 + i * 4
            pygame.draw.line(s, _shade(base, 0.6), (x, cy + 2), (x - 2, cy + 6 + sway))
            pygame.draw.line(s, _shade(base, 0.6), (x, cy + 2), (x + 2, cy + 6 - sway))
        s.set_at((cx + 7, cy - 1), (240, 220, 120))
    elif kind == "root_mother":
        for i in range(7):
            a = i * math.tau / 7 + sway * 0.05
            pygame.draw.line(s, (80, 100, 50), (cx, cy), (cx + int(math.cos(a) * 16 * sz / 1.5), cy + int(math.sin(a) * 12 * sz / 1.5)), 3)
        pygame.draw.circle(s, base, (cx, cy - 2), int(9 * sz / 1.3))
        pygame.draw.circle(s, (255, 150, 70), (cx, cy - 2), int(4 * sz / 1.3))
        pygame.draw.circle(s, (255, 226, 130), (cx, cy - 2), int(2 * sz / 1.3))
    else:
        pygame.draw.circle(s, base, (cx, cy), 7)
    if guard:
        pygame.draw.rect(s, (120, 150, 190), (cx + (4 if facing != 1 else -9), cy - 8, 5, 9), border_radius=2)
        pygame.draw.rect(s, (200, 220, 250), (cx + (4 if facing != 1 else -9), cy - 8, 5, 9), 1, border_radius=2)
    return _flash(s, 0.7) if flash else s


# ------------------------------------------------------------------------------------------ misc sprites
@lru_cache(maxsize=64)
def icon(kind: str, color: tuple, size: int = 12) -> pygame.Surface:
    s = _sp(size, size)
    c = color
    d = _shade(c, 0.6)
    if kind == "weapon":
        pygame.draw.line(s, c, (2, size - 3), (size - 3, 2), 2)
        pygame.draw.line(s, d, (2, size - 3), (4, size - 5), 3)
        pygame.draw.line(s, (120, 90, 60), (1, size - 2), (3, size - 4), 2)
    elif kind == "armor":
        pygame.draw.polygon(s, c, [(2, 2), (size - 2, 2), (size - 2, size // 2), (size // 2, size - 1), (2, size // 2)])
        pygame.draw.polygon(s, d, [(2, 2), (size - 2, 2), (size - 2, size // 2), (size // 2, size - 1), (2, size // 2)], 1)
    elif kind == "consumable":
        pygame.draw.rect(s, c, (3, 4, size - 6, size - 5), border_radius=2)
        pygame.draw.rect(s, d, (4, 1, size - 8, 3))
    elif kind == "ammo":
        pygame.draw.line(s, c, (2, size - 2), (size - 2, 2))
        pygame.draw.polygon(s, d, [(size - 2, 1), (size - 5, 2), (size - 2, 5)])
    elif kind == "quest":
        pygame.draw.circle(s, c, (size // 2, size // 2), size // 2 - 1)
        pygame.draw.circle(s, (255, 255, 255), (size // 2, size // 2), size // 2 - 1, 1)
    else:
        pygame.draw.circle(s, c, (size // 2, size // 2 + 1), size // 2 - 2)
        pygame.draw.circle(s, d, (size // 2, size // 2 + 1), size // 2 - 2, 1)
    return s
