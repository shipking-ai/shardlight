"""Orrery art: shaded planets, stars, ships, stations and brass-and-indigo UI furniture, all procedural.

Palette: deep indigo space, brass trim, star white, signal cyan.  Planet spheres are shaded per pixel with numpy
(light from the system's star) and cached per body; ships are vector shapes baked at 32 headings.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np
import pygame

from ...core import art as core_art
from ...core.fx import blit_additive_glow, clamp, mix

INDIGO = (14, 12, 36)
INDIGO2 = (26, 22, 60)
BRASS = (201, 162, 74)
BRASS_D = (120, 94, 40)
STAR_WHITE = (244, 241, 255)
CYAN = (111, 224, 255)
W, H = 480, 270
ANGLES = 32

PLANET_COLORS = {
    "rock": ((150, 130, 110), (90, 76, 70)), "desert": ((214, 170, 110), (150, 100, 70)), "temperate": ((90, 160, 96), (50, 100, 150)),
    "ocean": ((70, 130, 210), (40, 80, 160)), "ice": ((226, 240, 250), (150, 190, 220)), "lava": ((255, 120, 50), (60, 20, 20)),
    "gas": ((230, 190, 130), (180, 120, 90)), "barren": ((140, 136, 140), (90, 88, 96)), "toxic": ((170, 200, 90), (110, 130, 60)),
    "moon": ((170, 166, 170), (110, 108, 116)),
}


# ------------------------------------------------------------------------------------------- planets
@lru_cache(maxsize=256)
def planet_sprite(sub: str, seed: int, radius: int, light_angle: int, ring: bool = False, lit_city: bool = False) -> pygame.Surface:
    r = max(3, int(radius))
    size = r * 2 + (r if ring else 0) * 0 + 4
    ys, xs = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    d2 = xs * xs + ys * ys
    mask = d2 <= r * r
    nz = np.sqrt(np.maximum(0.0, 1.0 - d2 / (r * r)))
    la = math.radians(light_angle)
    lx, ly, lz = math.cos(la) * 0.7, math.sin(la) * 0.7, 0.55
    lam = np.clip((xs / r) * lx + (ys / r) * ly + nz * lz, 0, 1)
    rng = np.random.default_rng(seed)
    a, b = PLANET_COLORS.get(sub, PLANET_COLORS["rock"])
    # surface pattern: bands for gas giants, blotches otherwise
    if sub == "gas":
        pat = 0.5 + 0.5 * np.sin(ys / r * (6 + (seed % 5)) + np.sin(xs / r * 3 + seed) * 0.6)
    else:
        n1 = rng.random((8, 8)).astype(np.float32)
        pat = np.kron(n1, np.ones((max(1, (2 * r + 1) // 8 + 1),) * 2, dtype=np.float32))[:2 * r + 1, :2 * r + 1]
        pat = 0.6 * pat + 0.4 * (0.5 + 0.5 * np.sin((xs + ys) / max(2, r / 3) + seed))
    col = np.empty((2 * r + 1, 2 * r + 1, 3), dtype=np.float32)
    for c in range(3):
        col[..., c] = a[c] * pat + b[c] * (1 - pat)
    shade = (0.16 + 0.95 * lam)[..., None]
    col = np.clip(col * shade, 0, 255)
    # quantise to a few steps for a pixel-art look
    col = (col // 24) * 24 + 12
    surf = pygame.Surface((2 * r + 1, 2 * r + 1), pygame.SRCALPHA)
    arr = pygame.surfarray.pixels3d(surf)
    arr[:] = np.transpose(col.astype(np.uint8), (1, 0, 2))
    del arr
    al = pygame.surfarray.pixels_alpha(surf)
    al[:] = np.transpose((mask * 255).astype(np.uint8))
    del al
    if lit_city:
        for _ in range(max(6, r)):
            px, py = rng.integers(-r, r + 1, size=2)
            if px * px + py * py < (r - 2) ** 2 and (px / r) * lx + (py / r) * ly < -0.1:
                surf.set_at((int(px + r), int(py + r)), (255, 224, 140, 255))
    # atmosphere rim
    pygame.draw.circle(surf, (*mix(b, (200, 220, 255), 0.5), 110), (r, r), r, 1)
    if ring:
        big = pygame.Surface((int(r * 3.4), int(r * 3.4)), pygame.SRCALPHA)
        c = big.get_width() // 2
        pygame.draw.ellipse(big, (210, 190, 150, 190), (c - int(r * 1.6), c - int(r * 0.5), int(r * 3.2), int(r * 1.0)), 2)
        pygame.draw.ellipse(big, (170, 150, 120, 150), (c - int(r * 1.35), c - int(r * 0.42), int(r * 2.7), int(r * 0.84)), 1)
        back = big.copy()
        big.blit(surf, (c - r, c - r))
        pygame.draw.arc(big, (210, 190, 150, 230), (c - int(r * 1.6), c - int(r * 0.5), int(r * 3.2), int(r * 1.0)), math.pi, math.tau, 2)
        return big
    return surf


def draw_star(surf: pygame.Surface, pos, star, t: float, zoom: float = 1.0) -> None:
    r = max(4, int(star.radius * zoom))
    col = star.color
    blit_additive_glow(surf, pos, int(r * 3.4), tuple(int(c * 0.55) for c in col), 2.0)
    pygame.draw.circle(surf, mix(col, (255, 255, 255), 0.3), (int(pos[0]), int(pos[1])), r)
    pygame.draw.circle(surf, mix(col, (255, 255, 255), 0.75), (int(pos[0] - r * 0.25), int(pos[1] - r * 0.25)), max(1, int(r * 0.55)))
    if star.cls == "PSR":
        a = t * 3
        for k in (0, 1):
            ex, ey = math.cos(a + k * math.pi) * r * 6, math.sin(a + k * math.pi) * r * 6
            pygame.draw.line(surf, (190, 236, 255), (pos[0], pos[1]), (pos[0] + ex, pos[1] + ey), 1)


# ------------------------------------------------------------------------------------------- ships
def _rot(pts, ang, cx, cy):
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]


SHIP_SHAPES = {
    "wayfarer": ([(10, 0), (-5, -7), (-3, 0), (-5, 7)], [(-1, -9), (-6, -9), (-6, -6)], (200, 190, 150), (111, 224, 255)),
    "lark": ([(12, 0), (-6, -5), (-2, 0), (-6, 5)], [], (230, 226, 250), (111, 224, 255)),
    "bulwark": ([(9, -4), (9, 4), (-8, 7), (-8, -7)], [(0, -9), (-8, -9), (-8, -7)], (150, 150, 170), (255, 190, 90)),
    "salt_runner": ([(11, 0), (-3, -9), (-7, -3), (-7, 3), (-3, 9)], [], (246, 244, 236), (239, 75, 51)),
    "raider": ([(9, 0), (-3, -4), (-8, -8), (-5, 0), (-8, 8), (-3, 4)], [], (150, 70, 60), (255, 120, 80)),
    "patrol": ([(10, 0), (3, -8), (-9, -6), (-9, 6), (3, 8)], [], (110, 140, 170), (255, 220, 120)),
    "drone": ([(6, 0), (0, -5), (-6, 0), (0, 5)], [], (170, 170, 190), (255, 90, 90)),
    "hunter": ([(13, 0), (-2, -5), (-9, -9), (-6, 0), (-9, 9), (-2, 5)], [], (60, 50, 90), (255, 60, 90)),
    "freighter": ([(12, -4), (12, 4), (-12, 6), (-12, -6)], [(0, -7), (-8, -7), (-8, -6)], (176, 156, 120), (255, 200, 110)),
}


@lru_cache(maxsize=512)
def ship_sprite(style: str, k: int, flash: bool = False) -> pygame.Surface:
    body, wings, base, accent = SHIP_SHAPES.get(style, SHIP_SHAPES["wayfarer"])
    size = 36
    c = size // 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    ang = k * math.tau / ANGLES
    col = (255, 255, 255) if flash else base
    ink = (10, 8, 24)
    for w in (wings, [(x, -y) for x, y in wings]):
        if w:
            pts = _rot(w, ang, c, c)
            pygame.draw.polygon(surf, ink, pts)
            pygame.draw.polygon(surf, mix(col, (0, 0, 0), 0.25), pts)
    pts = _rot(body, ang, c, c)
    pygame.draw.polygon(surf, ink, pts)
    inner = _rot([(x * 0.82, y * 0.78) for x, y in body], ang, c, c)
    pygame.draw.polygon(surf, col, inner)
    nose = _rot([(body[0][0] * 0.9, 0), (body[0][0] * 0.35, 0)], ang, c, c)
    pygame.draw.line(surf, accent if not flash else (255, 255, 255), nose[0], nose[1], 2)
    ck = _rot([(2, 0)], ang, c, c)[0]
    pygame.draw.circle(surf, (120, 190, 240) if not flash else (255, 255, 255), (int(ck[0]), int(ck[1])), 2)
    return surf


def draw_ship(surf: pygame.Surface, sp, pos, heading: float, style: str, flash: bool = False, thrust: float = 0.0) -> None:
    k = int(round(heading / math.tau * ANGLES)) % ANGLES
    img = ship_sprite(style, k, flash)
    if thrust > 0.1:
        bx = pos[0] - math.cos(heading) * 11
        by = pos[1] - math.sin(heading) * 11
        pygame.draw.line(surf, (255, 190, 100), (bx, by), (bx - math.cos(heading) * 7 * thrust, by - math.sin(heading) * 7 * thrust), 3)
        blit_additive_glow(surf, (bx, by), 8, (90, 50, 20), 2)
    surf.blit(img, (pos[0] - img.get_width() // 2, pos[1] - img.get_height() // 2))


def draw_station(surf: pygame.Surface, pos, kind: str, t: float, angle: float = 0.0, label: str = "") -> None:
    x, y = pos
    r = 9
    pygame.draw.circle(surf, (10, 8, 24), (int(x), int(y)), r + 2)
    pygame.draw.circle(surf, (150, 142, 170), (int(x), int(y)), r)
    pygame.draw.circle(surf, (90, 84, 110), (int(x), int(y)), r - 3, 1)
    for k in range(4):
        a = angle + k * math.pi / 2
        pygame.draw.line(surf, BRASS, (x + math.cos(a) * r, y + math.sin(a) * r), (x + math.cos(a) * (r + 6), y + math.sin(a) * (r + 6)), 2)
    pygame.draw.circle(surf, CYAN if int(t * 2) % 2 else BRASS, (int(x), int(y)), 2)
    blit_additive_glow(surf, pos, 22, (30, 40, 60), 2)


def draw_anomaly(surf: pygame.Surface, pos, kind: str, t: float, r: float = 14) -> None:
    x, y = pos
    if kind == "lensing_fold":
        for i in range(4):
            pygame.draw.ellipse(surf, (150, 120, 255), (x - r + i * 2, y - r * 0.6 + i, (r - i * 2) * 2, (r * 0.6 - i) * 2), 1)
    elif kind == "ancient_beacon":
        pygame.draw.polygon(surf, BRASS, [(x, y - r), (x + 5, y + r * 0.6), (x - 5, y + r * 0.6)])
        blit_additive_glow(surf, pos, 24, (60, 50, 20), 2)
        pygame.draw.circle(surf, STAR_WHITE, (int(x), int(y - r)), 2)
    elif kind == "crystal_bloom":
        for i in range(6):
            a = i * 1.05 + 0.3
            pygame.draw.line(surf, (190, 140, 255), (x, y), (x + math.cos(a) * r, y + math.sin(a) * r), 2)
        blit_additive_glow(surf, pos, 22, (50, 20, 70), 2)
    elif kind == "orrery_fragment":
        for i in range(3):
            pygame.draw.circle(surf, BRASS, (int(x), int(y)), int(r - i * 4), 1)
        a = t * 0.8
        pygame.draw.circle(surf, STAR_WHITE, (int(x + math.cos(a) * r), int(y + math.sin(a) * r)), 2)
    elif kind == "emitter":
        for i in range(3):
            rr = int(((t * 1.2 + i * 0.33) % 1.0) * 30 + 4)
            pygame.draw.circle(surf, mix(CYAN, INDIGO, rr / 34), (int(x), int(y)), rr, 1)
        pygame.draw.circle(surf, CYAN, (int(x), int(y)), 3)
    else:
        pygame.draw.circle(surf, (170, 120, 255), (int(x), int(y)), int(r), 1)


def draw_derelict(surf: pygame.Surface, pos, t: float) -> None:
    x, y = pos
    pts = [(x - 9, y - 3), (x - 2, y - 7), (x + 8, y - 2), (x + 5, y + 5), (x - 6, y + 6)]
    pygame.draw.polygon(surf, (10, 8, 24), pts)
    pygame.draw.polygon(surf, (96, 90, 104), [(px * 0.9 + x * 0.1, py * 0.9 + y * 0.1) for px, py in pts])
    pygame.draw.line(surf, (255, 140, 60) if int(t * 3) % 5 == 0 else (60, 50, 60), (x - 3, y), (x + 3, y - 2), 1)


def draw_gear(surf: pygame.Surface, pos, r: float, teeth: int, angle: float, color, lit: bool) -> None:
    x, y = pos
    pts = []
    for i in range(teeth * 2):
        a = angle + i * math.pi / teeth
        rr = r if i % 2 == 0 else r * 0.75
        pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
    pygame.draw.polygon(surf, (10, 8, 24), pts)
    pygame.draw.polygon(surf, color if lit else mix(color, (30, 30, 50), 0.6), pts)
    pygame.draw.circle(surf, (10, 8, 24), (int(x), int(y)), int(r * 0.35))
    pygame.draw.circle(surf, (255, 240, 180) if lit else (60, 54, 70), (int(x), int(y)), int(r * 0.2))
    if lit:
        blit_additive_glow(surf, pos, int(r * 2.2), (90, 70, 20), 2)


@lru_cache(maxsize=8)
def star_layers(seed: int) -> list[pygame.Surface]:
    return [core_art.starfield((W, H), seed + i, d, c) for i, (d, c) in
            enumerate(((0.004, (150, 160, 210)), (0.003, (210, 215, 255)), (0.0016, (255, 240, 200))))]


def draw_stars(surf: pygame.Surface, cam: tuple[float, float], seed: int) -> None:
    for layer, par in zip(star_layers(seed), (0.08, 0.18, 0.35)):
        ox = int(-cam[0] * par) % W
        oy = int(-cam[1] * par) % H
        for dx in (-W, 0):
            for dy in (-H, 0):
                surf.blit(layer, (ox + dx, oy + dy))


def panel(surf: pygame.Surface, rect, title: str | None = None, font=None, alpha: int = 235) -> None:
    from ...core.ui import draw_panel
    draw_panel(surf, rect, border=BRASS, fill=INDIGO, alpha=alpha, title=title, font=font)
