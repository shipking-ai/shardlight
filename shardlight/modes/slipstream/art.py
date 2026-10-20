"""Slipstream art: baked track surface, pre-rotated car sprites, effects.  Palette: salt white, vermilion,
ultramarine, ink - flat colour blocks with long low-sun shadows (light from the upper-left)."""
from __future__ import annotations

import math
import random
from functools import lru_cache

import pygame

from ...core import art
from ...core.fx import clamp, mix
from .physics import ROUGH, SALT, TARMAC
from .track import SHOULDER, Track

SALT_WHITE = (240, 237, 226)
SALT_SHADE = (222, 218, 205)
TRACK_SALT = (206, 208, 214)
TARMAC_COL = (52, 54, 74)
ROUGH_COL = (186, 164, 134)
VERM = (239, 75, 51)
ULTRA = (42, 63, 176)
INK = (20, 21, 42)
ANGLES = 48


# ------------------------------------------------------------------------------------------ track
def _quad(surf, col, a, b, c, d):
    pygame.draw.polygon(surf, col, (a, b, c, d))


def bake_track(track: Track) -> tuple[pygame.Surface, tuple[int, int]]:
    """Return (surface, world_origin). The surface covers the track bounds plus margin."""
    x0, y0, x1, y1 = track.bounds
    ox, oy = int(x0) - 40, int(y0) - 40
    w, h = int(x1 - x0) + 80, int(y1 - y0) + 80
    surf = pygame.Surface((w, h))
    rng = random.Random(track.seed)
    surf.fill(SALT_WHITE)
    # salt-flat polygon cracks and pale blotches (infield/outfield decoration)
    for _ in range(int(w * h / 5200)):
        x, y = rng.randrange(w), rng.randrange(h)
        r = rng.randint(14, 46)
        pygame.draw.circle(surf, mix(SALT_WHITE, SALT_SHADE, rng.random() * 0.7), (x, y), r)
    for _ in range(int(w * h / 1700)):
        x, y = rng.randrange(w), rng.randrange(h)
        pts = [(x, y)]
        for _ in range(rng.randint(2, 4)):
            x += rng.randint(-22, 22)
            y += rng.randint(-22, 22)
            pts.append((x, y))
        pygame.draw.lines(surf, (206, 202, 188), False, pts, 1)
    n = track.n

    def P(i, lat):
        x, y = track.pts[i % n]
        nx, ny = track.norm[i % n]
        return (x + nx * lat - ox, y + ny * lat - oy)

    # barriers: shadow first (long low-sun shadows toward the lower right)
    for i in range(0, n):
        half = track.width[i] * 0.5 + SHOULDER
        for side in (-1, 1):
            if track.cut is not None and _in_cut_opening(track, i, side):
                continue
            px, py = P(i, side * (half + 6))
            pygame.draw.circle(surf, (190, 186, 172), (int(px + 7), int(py + 8)), 7)
    # rough shoulder
    for i in range(n):
        half = track.width[i] * 0.5
        for side in (-1, 1):
            a0, a1 = P(i, side * half), P(i + 1, side * half)
            b0, b1 = P(i, side * (half + SHOULDER)), P(i + 1, side * (half + SHOULDER))
            _quad(surf, mix(ROUGH_COL, SALT_WHITE, 0.25 if i % 3 else 0.1), a0, a1, b1, b0)
    # shortcut corridor floor (dirt) before the main surface so it reads as a rough cut
    if track.cut is not None:
        c = track.cut
        pygame.draw.line(surf, mix(ROUGH_COL, (120, 100, 80), 0.3), (c.ax - ox, c.ay - oy), (c.bx - ox, c.by - oy), int(c.half * 2))
        pygame.draw.line(surf, ROUGH_COL, (c.ax - ox, c.ay - oy), (c.bx - ox, c.by - oy), int(c.half * 2 - 6))
        for _ in range(int(c.length() / 5)):
            f = rng.random()
            px = c.ax + (c.bx - c.ax) * f + rng.uniform(-c.half, c.half) * 0.8
            py = c.ay + (c.by - c.ay) * f + rng.uniform(-c.half, c.half) * 0.8
            surf.set_at((int(px - ox), int(py - oy)), (150, 128, 104))
    # main surface
    for i in range(n):
        half = track.width[i] * 0.5
        sf = track.surface[i]
        col = TARMAC_COL if sf == TARMAC else mix(TRACK_SALT, SALT_WHITE, 0.3 if (i // 4) % 2 else 0.1)
        _quad(surf, col, P(i, -half), P(i + 1, -half), P(i + 1, half), P(i, half))
        if sf == TARMAC and (i // 3) % 2 == 0:                    # dashed centre line
            _quad(surf, (232, 230, 220), P(i, -1), P(i + 1, -1), P(i + 1, 1), P(i, 1))
    # kerbs on corners (red/white blocks on the inside edge)
    for i in range(n):
        k = track.kappa[i]
        if abs(k) < 0.006:
            continue
        side = 1 if k > 0 else -1
        half = track.width[i] * 0.5
        col = VERM if (i // 2) % 2 else (246, 244, 238)
        _quad(surf, col, P(i, side * (half - 5)), P(i + 1, side * (half - 5)), P(i + 1, side * half), P(i, side * half))
    # edge lines
    for i in range(n):
        half = track.width[i] * 0.5
        for side in (-1, 1):
            a, b = P(i, side * half), P(i + 1, side * half)
            pygame.draw.line(surf, (246, 244, 238), a, b, 2)
    # tyre walls
    for i in range(n):
        half = track.width[i] * 0.5 + SHOULDER
        for side in (-1, 1):
            if track.cut is not None and _in_cut_opening(track, i, side):
                continue
            px, py = P(i, side * (half + 6))
            col = VERM if (i // 2) % 2 == 0 else (246, 244, 238)
            pygame.draw.circle(surf, INK, (int(px), int(py)), 7)
            pygame.draw.circle(surf, col, (int(px), int(py)), 5)
            pygame.draw.circle(surf, art.shade(col, 0.4), (int(px) - 1, int(py) - 2), 2)
    # start / finish line and gantry
    s = track.start
    half = track.width[s] * 0.5
    cells = int(half * 2 / 6)
    for ci in range(cells):
        for row in range(2):
            col = INK if (ci + row) % 2 == 0 else (246, 244, 238)
            a = P(s + row, -half + ci * 6)
            b = P(s + row, -half + ci * 6 + 6)
            c2 = P(s + row + 1, -half + ci * 6 + 6)
            d2 = P(s + row + 1, -half + ci * 6)
            _quad(surf, col, a, b, c2, d2)
    for side in (-1, 1):
        px, py = P(s, side * (half + SHOULDER + 14))
        pygame.draw.rect(surf, INK, (px - 3, py - 3, 7, 7))
        pygame.draw.rect(surf, ULTRA, (px - 2, py - 2, 5, 5))
    # grid boxes
    for k, (gx, gy, gh) in enumerate(track.start_grid(8)):
        pygame.draw.rect(surf, (246, 244, 238), (gx - ox - 6, gy - oy - 1, 12, 2))
    # checkpoint flags
    for g in track.gates:
        for side in (-1, 1):
            px, py = P(g, side * (track.width[g] * 0.5 + SHOULDER + 12))
            pygame.draw.line(surf, INK, (px, py), (px, py - 10), 1)
            pygame.draw.polygon(surf, ULTRA, ((px, py - 10), (px + 6, py - 8), (px, py - 5)))
    # cones at corner entries, tyre-stack signage
    for i in range(0, n, 11):
        if abs(track.kappa[i]) > 0.0055 and abs(track.kappa[(i - 8) % n]) < 0.0055:
            side = 1 if track.kappa[i] > 0 else -1
            px, py = P(i - 4, -side * (track.width[i] * 0.5 - 6))
            pygame.draw.polygon(surf, INK, ((px - 4, py + 3), (px + 4, py + 3), (px, py - 6)))
            pygame.draw.polygon(surf, (255, 150, 50), ((px - 3, py + 2), (px + 3, py + 2), (px, py - 5)))
    # shortcut arrow signs
    if track.cut is not None:
        c = track.cut
        ang = math.atan2(c.by - c.ay, c.bx - c.ax)
        for back in (46, 78):
            ix = c.ax - ox - math.cos(ang) * back * 0.2
            iy = c.ay - oy - math.sin(ang) * back * 0.2
            for k in range(3):
                q = [(ix + math.cos(ang) * k * 6, iy + math.sin(ang) * k * 6)]
                pass
        for k in range(3):
            px = c.ax - ox + math.cos(ang) * (10 + k * 9)
            py = c.ay - oy + math.sin(ang) * (10 + k * 9)
            pts = [(px + math.cos(ang) * 6, py + math.sin(ang) * 6),
                   (px + math.cos(ang + 2.4) * 7, py + math.sin(ang + 2.4) * 7),
                   (px + math.cos(ang - 2.4) * 7, py + math.sin(ang - 2.4) * 7)]
            pygame.draw.polygon(surf, ULTRA, pts)
    # oil and boulders
    for hz in track.hazards:
        x, y = hz.x - ox, hz.y - oy
        if hz.kind == "oil":
            pygame.draw.ellipse(surf, (30, 30, 52), (x - hz.r, y - hz.r * 0.8, hz.r * 2, hz.r * 1.6))
            pygame.draw.ellipse(surf, (60, 60, 96), (x - hz.r * 0.6, y - hz.r * 0.6, hz.r * 0.9, hz.r * 0.5))
        elif hz.kind == "boulder":
            pygame.draw.circle(surf, (170, 166, 154), (int(x + 3), int(y + 4)), int(hz.r))
            pygame.draw.circle(surf, INK, (int(x), int(y)), int(hz.r) + 1)
            pygame.draw.circle(surf, (136, 132, 128), (int(x), int(y)), int(hz.r))
            pygame.draw.circle(surf, (186, 182, 172), (int(x - 2), int(y - 2)), max(2, int(hz.r) - 3))
    return surf, (ox, oy)


def _in_cut_opening(track: Track, i: int, side: int) -> bool:
    """No barrier where the shortcut corridor attaches to the track."""
    c = track.cut
    n = track.n
    for end in (c.ia, c.ib):
        if (i - end) % n < 9 or (end - i) % n < 9:
            x, y = track.pts[i]
            nx, ny = track.norm[i]
            px, py = x + nx * side * (track.width[i] * 0.5 + SHOULDER), y + ny * side * (track.width[i] * 0.5 + SHOULDER)
            d, _ = c.lateral(px, py)
            if d < c.half + 14:
                return True
    return False


def make_minimap(track: Track, size: int = 64) -> tuple[pygame.Surface, float, tuple[float, float]]:
    x0, y0, x1, y1 = track.bounds
    sc = (size - 6) / max(x1 - x0, y1 - y0)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pts = [((x - x0) * sc + 3, (y - y0) * sc + 3) for x, y in track.pts]
    pygame.draw.lines(surf, (20, 21, 42, 220), True, pts, 5)
    pygame.draw.lines(surf, (246, 244, 238, 255), True, pts, 3)
    if track.cut:
        c = track.cut
        pygame.draw.line(surf, (239, 75, 51, 255), ((c.ax - x0) * sc + 3, (c.ay - y0) * sc + 3),
                         ((c.bx - x0) * sc + 3, (c.by - y0) * sc + 3), 2)
    sx, sy = pts[track.start]
    pygame.draw.circle(surf, (42, 63, 176, 255), (int(sx), int(sy)), 2)
    return surf, sc, (x0, y0)


# -------------------------------------------------------------------------------------------- cars
def _rot(pts, ang, cx, cy):
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]


def _car_shapes(spec) -> dict:
    L, W = spec.length, spec.width
    body = spec.body
    shape = body.get("shape", "dart")
    hl, hw = L / 2, W / 2
    nose = {"dart": 0.55, "wedge": 0.35, "block": 0.85, "arc": 0.3, "twin": 0.6}.get(shape, 0.55)
    tail = {"dart": 0.9, "wedge": 1.0, "block": 1.0, "arc": 0.7, "twin": 0.9}.get(shape, 0.9)
    poly = [(-hl, -hw * tail), (hl * 0.35, -hw), (hl, -hw * nose), (hl, hw * nose), (hl * 0.35, hw), (-hl, hw * tail)]
    return {"body": poly, "wing_f": body.get("wing_f", 8), "wing_r": body.get("wing_r", 9), "shape": shape,
            "stripe": body.get("stripe", 1), "hl": hl, "hw": hw}


def bake_car(spec, color, k: int) -> pygame.Surface:
    """One rotation frame (k of ANGLES) drawn as rotated vector shapes so edges stay crisp."""
    size = int(spec.length * 2.1) | 1
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    ang = k * math.tau / ANGLES
    sh = _car_shapes(spec)
    ink = (14, 12, 30)
    hl, hw = sh["hl"], sh["hw"]
    # wheels
    for wx, wy in ((hl * 0.55, hw + 0.5), (hl * 0.55, -hw - 0.5), (-hl * 0.6, hw + 0.8), (-hl * 0.6, -hw - 0.8)):
        pts = _rot([(wx - 3, wy - 1.6), (wx + 3, wy - 1.6), (wx + 3, wy + 1.6), (wx - 3, wy + 1.6)], ang, c, c)
        pygame.draw.polygon(surf, ink, pts)
    # front/rear wings
    wf, wr = sh["wing_f"], sh["wing_r"]
    wfp = _rot([(hl - 1, -wf * 0.5), (hl + 1.5, -wf * 0.5), (hl + 1.5, wf * 0.5), (hl - 1, wf * 0.5)], ang, c, c)
    wrp = _rot([(-hl - 1.5, -wr * 0.5), (-hl + 1.2, -wr * 0.5), (-hl + 1.2, wr * 0.5), (-hl - 1.5, wr * 0.5)], ang, c, c)
    pygame.draw.polygon(surf, ink, wfp)
    pygame.draw.polygon(surf, (236, 232, 222), wfp, 0)
    pygame.draw.polygon(surf, ink, wrp)
    pygame.draw.polygon(surf, art.shade(color, -0.3), wrp)
    body = _rot(sh["body"], ang, c, c)
    pygame.draw.polygon(surf, ink, body)
    inner = _rot([(x * 0.86, y * 0.8) for x, y in sh["body"]], ang, c, c)
    pygame.draw.polygon(surf, color, inner)
    # side shading toward the light (upper-left)
    lit = _rot([(x * 0.86, y * 0.8 - hw * 0.15) for x, y in sh["body"][:3]] +
               [(x * 0.86, y * 0.2) for x, y in sh["body"][3:]][::-1], ang, c, c)
    pygame.draw.polygon(surf, art.shade(color, 0.28), lit)
    # stripes
    if sh["stripe"]:
        for off in ((0,) if sh["stripe"] == 1 else (-hw * 0.32, hw * 0.32)):
            st = _rot([(-hl * 0.8, off - 0.9), (hl * 0.8, off - 0.9), (hl * 0.8, off + 0.9), (-hl * 0.8, off + 0.9)], ang, c, c)
            pygame.draw.polygon(surf, (246, 244, 238), st)
    # cockpit
    cp = _rot([(-hl * 0.1, -hw * 0.38), (hl * 0.28, -hw * 0.3), (hl * 0.28, hw * 0.3), (-hl * 0.1, hw * 0.38)], ang, c, c)
    pygame.draw.polygon(surf, ink, cp)
    pygame.draw.polygon(surf, (112, 150, 214), _rot([(-hl * 0.05, -hw * 0.26), (hl * 0.2, -hw * 0.2),
                                                     (hl * 0.2, hw * 0.2), (-hl * 0.05, hw * 0.26)], ang, c, c))
    if sh["shape"] == "twin":
        for off in (-hw * 0.62, hw * 0.62):
            pod = _rot([(-hl * 0.5, off - 1.2), (hl * 0.5, off - 1.2), (hl * 0.5, off + 1.2), (-hl * 0.5, off + 1.2)], ang, c, c)
            pygame.draw.polygon(surf, ink, pod)
    return surf


class CarSprites:
    def __init__(self) -> None:
        self.cache: dict[tuple, list[pygame.Surface]] = {}

    def get(self, spec, color, heading: float) -> pygame.Surface:
        key = (spec.id, tuple(color), spec.length, spec.width)
        frames = self.cache.get(key)
        if frames is None:
            frames = [bake_car(spec, color, k) for k in range(ANGLES)]
            self.cache[key] = frames
        k = int(round(heading / math.tau * ANGLES)) % ANGLES
        return frames[k]


def car_shadow(surf: pygame.Surface, x: float, y: float, spec, heading: float) -> None:
    """Long low-sun shadow (offset down-right)."""
    sx, sy = x + 6, y + 7
    c, s = math.cos(heading), math.sin(heading)
    L, W = spec.length * 0.55, spec.width * 0.5
    pts = [(sx + c * L - s * W, sy + s * L + c * W), (sx + c * L + s * W, sy + s * L - c * W),
           (sx - c * L + s * W, sy - s * L - c * W), (sx - c * L - s * W, sy - s * L + c * W)]
    pygame.draw.polygon(surf, (20, 20, 44, 74), pts)      # surf is an SRCALPHA shadow layer
