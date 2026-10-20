"""Top-down renderer for the Gloaming Ward: baked floors and props, true shadow-casting lights (visibility polygons
against walls, closed doors and tall props) multiplied over the scene, and visual sound cues.

Darkness is the default: the frame is drawn at full brightness and then multiplied by a light mask built from
the lamps, windows, the player's flashlight / lamp / match and any Lantern Ward.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np
import pygame

from ...core import art as core_art
from ...core.fx import clamp, mix
from . import consts as C
from .consts import BONE, BONE_DIM, LAMP, NEAR_BLACK, TEAL, TEAL_DARK, TILE
from .props import PROP_DEFS
from .sim import FLASH_HALF, FLASH_RANGE, LAMP_RADIUS, MATCH_RADIUS, Game

W, H = 480, 270
AMBIENT = (5, 7, 11)

SURFACE_COL = [((78, 60, 46), (66, 50, 38)), ((92, 104, 104), (78, 90, 90)), ((70, 70, 78), (60, 60, 68)), ((84, 54, 60), (72, 44, 52)),
               ((82, 76, 66), (70, 64, 56)), ((90, 120, 130), (80, 108, 120)), ((50, 86, 100), (44, 76, 90))]
PROP_COL = {
    "bed": (190, 190, 186), "cot": (150, 150, 140), "locker": (84, 96, 104), "wardrobe": (96, 70, 52), "table": (118, 86, 58),
    "desk": (104, 74, 50), "shelf": (92, 66, 46), "bookshelf": (80, 56, 44), "crate": (120, 94, 62), "barrel": (110, 78, 50),
    "cabinet": (96, 108, 112), "bench": (112, 82, 56), "sofa": (110, 56, 60), "rack": (88, 60, 48), "coffin": (74, 58, 50),
    "counter": (120, 120, 124), "pillar": (110, 108, 116), "chair": (122, 90, 60), "wheelchair": (130, 134, 140), "mirror": (190, 186, 180),
    "clock": (150, 130, 90), "generator": (110, 118, 96), "fuse_box": (130, 130, 120), "lever": (150, 140, 120), "winch": (140, 140, 132),
    "stairs": (120, 120, 126), "barricade": (104, 72, 46), "rug": (96, 52, 56), "bloodstain": (96, 22, 26), "papers": (214, 208, 188),
    "drawing": (206, 196, 168), "sign": (160, 130, 80), "candle": (255, 214, 130), "tally": (220, 220, 214),
}


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


@lru_cache(maxsize=256)
def prop_sprite(kind: str, w: int, h: int, rot: bool, state: int = 0) -> pygame.Surface:
    """Sprite for a w x h tile footprint (already rotated)."""
    s = pygame.Surface((w * TILE, h * TILE), pygame.SRCALPHA)
    col = PROP_COL.get(kind, (120, 120, 120))
    dark, light = _shade(col, 0.55), _shade(col, 1.3)
    pw, ph = w * TILE, h * TILE
    r = pygame.Rect(1, 1, pw - 2, ph - 2)
    d = PROP_DEFS[kind]
    if kind in ("rug",):
        pygame.draw.rect(s, col, (0, 0, pw, ph))
        pygame.draw.rect(s, _shade(col, 1.25), (2, 2, pw - 4, ph - 4), 1)
        pygame.draw.rect(s, _shade(col, 0.8), (4, 4, pw - 8, ph - 8), 1)
        return s
    if kind == "bloodstain":
        pygame.draw.ellipse(s, col, (1, 2, pw - 3, ph - 5))
        pygame.draw.ellipse(s, _shade(col, 1.4), (3, 4, 4, 3))
        return s
    if kind in ("papers", "drawing", "sign", "tally"):
        pygame.draw.rect(s, col, (2, 2, pw - 5, ph - 5))
        pygame.draw.rect(s, dark, (2, 2, pw - 5, ph - 5), 1)
        if kind == "tally":
            for i in range(4):
                pygame.draw.line(s, (60, 60, 60), (3 + i * 2, 3), (3 + i * 2, 7))
        else:
            for yy in (4, 6):
                pygame.draw.line(s, _shade(col, 0.6), (4, yy), (pw - 5, yy))
        return s
    if kind == "candle":
        pygame.draw.rect(s, (230, 224, 200), (4, 5, 3, 5))
        pygame.draw.rect(s, (255, 214, 130), (4, 3, 3, 3))
        return s
    if kind in ("barrel",):
        pygame.draw.ellipse(s, col, (1, 1, pw - 2, ph - 2))
        pygame.draw.ellipse(s, dark, (1, 1, pw - 2, ph - 2), 1)
        pygame.draw.ellipse(s, light, (3, 3, pw - 6, ph - 6), 1)
        return core_art.outline(s, (8, 8, 12))
    if kind in ("chair", "wheelchair"):
        pygame.draw.rect(s, col, (3, 3, pw - 6, ph - 6))
        pygame.draw.rect(s, dark, (3, 2, pw - 6, 2))
        if kind == "wheelchair":
            pygame.draw.circle(s, (60, 60, 64), (2, ph // 2 + 1), 2, 1)
            pygame.draw.circle(s, (60, 60, 64), (pw - 3, ph // 2 + 1), 2, 1)
        return core_art.outline(s, (8, 8, 12))
    pygame.draw.rect(s, col, r)
    pygame.draw.rect(s, light, (1, 1, pw - 2, 1))
    pygame.draw.rect(s, dark, (1, ph - 2, pw - 2, 1))
    pygame.draw.rect(s, dark, r, 1)
    if kind in ("bed", "cot"):
        pw2 = pw if not rot else pw
        pygame.draw.rect(s, (230, 230, 226) if kind == "bed" else (170, 170, 160), (2, 2, pw - 4, ph // 2 + 1))
        pygame.draw.rect(s, dark, (2, 2, pw - 4, ph // 2 + 1), 1)
    elif kind in ("locker", "wardrobe", "cabinet"):
        for xx in range(3, pw - 2, 3):
            pygame.draw.line(s, dark, (xx, 3), (xx, ph - 4))
        pygame.draw.rect(s, light, (pw // 2, ph // 2, 2, 2))
    elif kind in ("shelf", "bookshelf", "rack"):
        for yy in range(3, ph - 2, 3):
            pygame.draw.line(s, dark, (2, yy), (pw - 3, yy))
        for xx in range(3, pw - 3, 2):
            pygame.draw.line(s, [(150, 60, 60), (60, 90, 130), (190, 160, 70)][xx % 3], (xx, 2), (xx, 4))
    elif kind in ("crate",):
        pygame.draw.line(s, dark, (1, 1), (pw - 2, ph - 2))
        pygame.draw.line(s, dark, (pw - 2, 1), (1, ph - 2))
    elif kind == "table":
        pygame.draw.rect(s, light, (2, 2, pw - 4, ph - 4), 1)
    elif kind == "generator":
        pygame.draw.rect(s, (60, 70, 56), (3, 3, pw - 6, ph - 6))
        pygame.draw.circle(s, (230, 190, 90) if state else (90, 90, 80), (pw // 2, ph // 2), 4)
        pygame.draw.circle(s, dark, (pw // 2, ph // 2), 4, 1)
    elif kind == "fuse_box":
        pygame.draw.rect(s, (60, 60, 56), (2, 2, pw - 4, ph - 4))
        pygame.draw.rect(s, (255, 226, 150) if state else (20, 20, 20), (4, 4, 4, 4))
    elif kind == "lever":
        pygame.draw.line(s, (200, 60, 50), (6, 9), (3 if not state else 9, 3), 2)
    elif kind == "winch":
        pygame.draw.circle(s, dark, (6, 6), 5, 2)
        pygame.draw.line(s, light, (6, 6), (6 + (3 if state else 0), 2 + (3 if state else 0)))
    elif kind == "clock":
        pygame.draw.circle(s, (230, 220, 190), (6, 6), 4)
        pygame.draw.circle(s, dark, (6, 6), 4, 1)
        pygame.draw.line(s, (30, 30, 30), (6, 6), (6, 3))
        pygame.draw.line(s, (30, 30, 30), (6, 6), (8, 6))
    elif kind == "mirror":
        pygame.draw.rect(s, (200, 196, 190), (2, 1, pw - 4, ph - 2))
        pygame.draw.line(s, (150, 146, 140), (3, 2), (3, ph - 3))
    elif kind == "coffin":
        pygame.draw.rect(s, _shade(col, 0.8), (2, 2, pw - 4, ph - 4))
        pygame.draw.line(s, light, (pw // 2, 3), (pw // 2, ph - 4))
    elif kind == "sofa":
        pygame.draw.rect(s, light, (2, 2, pw - 4, 3))
    elif kind == "barricade":
        for xx in range(0, pw, 3):
            pygame.draw.line(s, dark, (xx, 1), (xx + 3, ph - 2))
    elif kind == "pillar":
        pygame.draw.circle(s, col, (pw // 2, ph // 2), pw // 2 - 1)
        pygame.draw.circle(s, light, (pw // 2 - 1, ph // 2 - 1), pw // 2 - 3, 1)
    elif kind == "stairs":
        for yy in range(1, ph, 3):
            pygame.draw.line(s, dark, (1, yy), (pw - 2, yy))
    return core_art.outline(s, (8, 8, 12))


@lru_cache(maxsize=8)
def floor_tile(surface: int, variant: int) -> pygame.Surface:
    base, alt = SURFACE_COL[surface]
    s = pygame.Surface((TILE, TILE))
    s.fill(base)
    rng = random.Random(surface * 31 + variant)
    if surface == C.S_WOOD:
        pygame.draw.line(s, alt, (0, 3), (TILE, 3))
        pygame.draw.line(s, alt, (0, 8), (TILE, 8))
        pygame.draw.line(s, _shade(base, 0.8), (rng.randrange(2, 10), 0), (rng.randrange(2, 10), 3))
    elif surface == C.S_TILE:
        pygame.draw.rect(s, alt, (0, 0, TILE, TILE), 1)
        if (variant & 1):
            pygame.draw.rect(s, _shade(base, 1.06), (1, 1, 5, 5))
    elif surface == C.S_STONE:
        for _ in range(5):
            s.set_at((rng.randrange(TILE), rng.randrange(TILE)), alt)
        pygame.draw.line(s, alt, (0, 6), (TILE, 6)) if variant & 1 else pygame.draw.line(s, alt, (5, 0), (5, TILE))
    elif surface == C.S_CARPET:
        pygame.draw.rect(s, alt, (0, 0, TILE, TILE), 1)
        s.set_at((6, 6), _shade(base, 1.3))
    elif surface == C.S_GRAVEL:
        for _ in range(9):
            s.set_at((rng.randrange(TILE), rng.randrange(TILE)), _shade(base, rng.choice((0.7, 1.25))))
    else:
        for _ in range(5):
            s.set_at((rng.randrange(TILE), rng.randrange(TILE)), alt)
    return s


@lru_cache(maxsize=2)
def wall_tile(style: int) -> pygame.Surface:
    s = pygame.Surface((TILE, TILE))
    s.fill((38, 42, 52))
    pygame.draw.rect(s, (52, 58, 70), (0, 0, TILE, 3))
    pygame.draw.line(s, (26, 28, 36), (0, TILE - 1), (TILE, TILE - 1))
    pygame.draw.line(s, (60, 66, 80), (0, 0), (TILE, 0))
    return s


class View:
    def __init__(self, game: Game):
        self.g = game
        lv = game.lv
        self.static = pygame.Surface((lv.w * TILE, lv.h * TILE))
        self._bake_static()
        self.opq = np.zeros((lv.h, lv.w), dtype=bool)
        self.opq_version = -1
        self.static_lights: dict[tuple, pygame.Surface] = {}
        self.ripples: list[list] = []
        self.t = 0.0
        self.cam = [0.0, 0.0]
        self.last_light_version = -1
        self.glow = self._radial(64)
        self.mask = pygame.Surface((W, H))

    # ------------------------------------------------------------------ baking
    def _bake_static(self) -> None:
        lv = self.g.lv
        s = self.static
        s.fill(NEAR_BLACK)
        for y in range(lv.h):
            for x in range(lv.w):
                v = lv.grid[y, x]
                if v == C.FLOOR or v == C.DOOR:
                    s.blit(floor_tile(int(lv.surface[y, x]), (x * 7 + y * 13) % 4), (x * TILE, y * TILE))
                elif v == C.WALL:
                    # only draw walls next to floor; the rest stays black
                    near = False
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            xx, yy = x + dx, y + dy
                            if 0 <= xx < lv.w and 0 <= yy < lv.h and lv.grid[yy, xx] in (C.FLOOR, C.DOOR):
                                near = True
                    if near:
                        s.blit(wall_tile(0), (x * TILE, y * TILE))
        # rugs and stains first (floor decoration)
        for p in lv.props:
            d = PROP_DEFS[p.kind]
            if d.deco:
                w, h = (d.h, d.w) if p.rot else (d.w, d.h)
                s.blit(prop_sprite(p.kind, w, h, p.rot), (p.cell[0] * TILE, p.cell[1] * TILE))

    @staticmethod
    @lru_cache(maxsize=8)
    def _radial(r: int) -> pygame.Surface:
        s = pygame.Surface((r * 2, r * 2))
        s.fill((0, 0, 0))
        arr = pygame.surfarray.pixels3d(s)
        yy, xx = np.mgrid[-r:r, -r:r]
        d = np.sqrt((xx + 0.5) ** 2 + (yy + 0.5) ** 2) / r
        v = np.clip(1 - d, 0, 1) ** 1.6
        for c in range(3):
            arr[:, :, c] = (v.T * 255).astype(np.uint8)
        del arr
        return s

    def _refresh_opaque(self) -> None:
        g = self.g
        if self.opq_version == g.version:
            return
        lv = g.lv
        o = (lv.grid == C.WALL) | (lv.grid == 0)
        for d in g.doors:
            if d.open < 0.35 and not d.broken:
                for (x, y) in lv.doors[d.id].cells:
                    o[y, x] = True
        for p in lv.props:
            dd = PROP_DEFS[p.kind]
            if dd.solid and dd.opaque:
                for (x, y) in p.cells:
                    o[y, x] = True
        self.opq = o
        self.opq_version = g.version
        self.static_lights.clear()

    # ------------------------------------------------------------------ light shapes
    def _cast(self, x: float, y: float, radius: float, a0: float, a1: float, n: int) -> list[tuple[float, float]]:
        """Visibility polygon around (x, y) between angles a0..a1 (radians) out to ``radius`` px."""
        opq = self.opq
        h, w = opq.shape
        pts = []
        step = 2.5
        for i in range(n + 1):
            a = a0 + (a1 - a0) * i / n
            dx, dy = math.cos(a), math.sin(a)
            d = 0.0
            px, py = x, y
            while d < radius:
                px += dx * step
                py += dy * step
                d += step
                cx, cy = int(px // TILE), int(py // TILE)
                if not (0 <= cx < w and 0 <= cy < h) or opq[cy, cx]:
                    d += 3.0
                    break
            pts.append((x + dx * min(d, radius), y + dy * min(d, radius)))
        return pts

    def _shaped(self, cx: float, cy: float, radius: float, a0: float, a1: float, n: int, intensity: float, tint=(255, 255, 255), full=False) -> tuple[pygame.Surface, tuple[int, int]]:
        r = int(radius) + 4
        g = pygame.transform.smoothscale(self.glow, (r * 2, r * 2))
        pts = self._cast(cx, cy, radius, a0, a1, n)
        if not full:
            pts = [(cx, cy)] + pts
        poly = [(px - cx + r, py - cy + r) for px, py in pts]
        m = pygame.Surface((r * 2, r * 2))
        m.fill((0, 0, 0))
        if len(poly) >= 3:
            pygame.draw.polygon(m, (255, 255, 255), poly)
        g.blit(m, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        tinted = pygame.Surface((r * 2, r * 2))
        tinted.fill(tuple(int(t * intensity) for t in tint))
        g.blit(tinted, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        return g, (int(cx - r), int(cy - r))

    # ------------------------------------------------------------------ frame
    def draw(self, surf: pygame.Surface, dt: float) -> None:
        g = self.g
        p = g.p
        self.t += dt
        self._refresh_opaque()
        # camera follows the player, clamped to the building
        lv = g.lv
        tx = p.x - W / 2
        ty = p.y - H / 2
        self.cam[0] += (tx - self.cam[0]) * min(1.0, dt * 8)
        self.cam[1] += (ty - self.cam[1]) * min(1.0, dt * 8)
        cx = int(max(-40, min(lv.w * TILE - W + 40, self.cam[0])))
        cy = int(max(-40, min(lv.h * TILE - H + 40, self.cam[1])))
        surf.fill(NEAR_BLACK)
        surf.blit(self.static, (-cx, -cy))
        self._draw_dynamic(surf, cx, cy)
        self._light(surf, cx, cy)
        self._ripples(surf, cx, cy, dt)

    def _draw_dynamic(self, surf: pygame.Surface, cx: int, cy: int) -> None:
        g = self.g
        lv = g.lv
        # solid props
        for i, p in enumerate(g.props):
            d = PROP_DEFS[p.kind]
            if d.deco:
                continue
            w, h = (d.h, d.w) if p.rot else (d.w, d.h)
            px, py = p.cell[0] * TILE - cx, p.cell[1] * TILE - cy
            if -30 < px < W + 30 and -30 < py < H + 30:
                st = 1 if (p.state.get("fused") or (p.kind == "generator" and g.obj.get("generator_on")) or (p.kind == "lever" and g.obj.get("power")) or
                           (p.kind == "winch" and g.obj.get("gate_open"))) else 0
                spr = prop_sprite(p.kind, w, h, p.rot, st)
                surf.blit(spr, (px, py))
                if p.kind == "clock" and p.state.get("taken"):
                    pass
        # doors
        for d in g.doors:
            dd = lv.doors[d.id]
            for (x, y) in dd.cells:
                px, py = x * TILE - cx, y * TILE - cy
                if not (-12 < px < W and -12 < py < H):
                    continue
                if d.broken:
                    pygame.draw.rect(surf, (60, 44, 34), (px + 2, py + 2, TILE - 4, TILE - 4))
                    continue
                openness = d.open
                col = (108, 80, 56) if not d.locks and not d.gate else (120, 90, 50) if d.locks else (130, 130, 140)
                if dd.vertical:
                    wdt = max(2, int(TILE * (1 - openness)))
                    pygame.draw.rect(surf, col, (px + 3, py, 3, TILE)) if openness > 0.6 else pygame.draw.rect(surf, col, (px + 3, py, 6, TILE))
                    if openness > 0.6:
                        pygame.draw.rect(surf, (80, 58, 40), (px + 3, py, 3, 3))
                else:
                    if openness > 0.6:
                        pygame.draw.rect(surf, col, (px, py + 3, 3, 6))
                    else:
                        pygame.draw.rect(surf, col, (px, py + 3, TILE, 6))
                        pygame.draw.rect(surf, (60, 44, 34), (px, py + 3, TILE, 6), 1)
                if d.locks or d.gate:
                    pygame.draw.rect(surf, (230, 200, 90) if d.locks else (200, 200, 210), (px + 4, py + 4, 3, 3))
        # floor items
        for f in g.floor_items:
            px, py = f.x - cx, f.y - cy
            if -10 < px < W + 10 and -10 < py < H + 10:
                col = tuple(g.item_def(f.item).get("color", (200, 200, 200)))
                pygame.draw.circle(surf, (10, 10, 14), (int(px), int(py)), 4)
                pygame.draw.circle(surf, col, (int(px), int(py)), 3)
                s = int(math.sin(self.t * 4 + f.x) * 1.5)
                surf.set_at((int(px) + 1, int(py) - 1 + s), (255, 255, 255))
        # enemies
        for e in g.enemies:
            px, py = e.x - cx, e.y - cy
            if -20 < px < W + 20 and -20 < py < H + 20:
                self._enemy(surf, e, px, py)
        # player
        p = g.p
        if not p.dead and p.hiding is None:
            self._player(surf, p, p.x - cx, p.y - cy)
        for w in g.wards:
            pygame.draw.circle(surf, (255, 214, 140), (int(w.x - cx), int(w.y - cy)), 3)

    def _player(self, surf, p, x, y) -> None:
        pygame.draw.ellipse(surf, (8, 8, 12), (x - 5, y + 1, 10, 6))
        col = (190, 180, 160)
        pygame.draw.circle(surf, (28, 28, 34), (int(x), int(y)), 5)
        pygame.draw.circle(surf, col, (int(x), int(y)), 4)
        a = math.radians(p.facing)
        pygame.draw.line(surf, (255, 240, 200), (x, y), (x + math.cos(a) * 6, y + math.sin(a) * 6), 2)
        if p.invuln > 0 and int(self.t * 14) % 2:
            pygame.draw.circle(surf, (255, 90, 90), (int(x), int(y)), 6, 1)

    def _enemy(self, surf, e, x, y) -> None:
        g = self.g
        k = e.kind
        bob = math.sin(self.t * 5 + e.idx) * 0.8 if e.moving else 0
        if k == "hark":
            body, head = (46, 44, 52), (86, 84, 92)
            pygame.draw.ellipse(surf, (8, 8, 12), (x - 6, y + 2, 12, 7))
            pygame.draw.ellipse(surf, body, (x - 4, y - 8 + bob, 8, 14))
            pygame.draw.circle(surf, head, (int(x), int(y - 9 + bob)), 4)
            for sx in (-1, 1):                              # the cupped hands that are its ears
                pygame.draw.arc(surf, (150, 140, 150), (x + sx * 4 - 3, y - 12 + bob, 6, 7), -1.2, 1.2, 1) if sx > 0 else pygame.draw.arc(surf, (150, 140, 150), (x - 7, y - 12 + bob, 6, 7), 1.9, 4.3, 1)
        elif k == "stillwatch":
            pygame.draw.ellipse(surf, (8, 8, 12), (x - 5, y + 2, 10, 6))
            pygame.draw.ellipse(surf, (196, 200, 206), (x - 3, y - 9 + bob, 6, 14))
            pygame.draw.circle(surf, (230, 234, 238), (int(x), int(y - 9 + bob)), 3)
            a = math.radians(e.facing)
            pygame.draw.circle(surf, (20, 20, 24), (int(x + math.cos(a) * 1.6), int(y - 9 + bob + math.sin(a) * 1.6)), 1)
        else:
            pygame.draw.ellipse(surf, (8, 8, 12), (x - 5, y + 2, 10, 6))
            pygame.draw.ellipse(surf, (70, 50, 46), (x - 4, y - 8 + bob, 8, 13))
            pygame.draw.circle(surf, (190, 170, 150), (int(x), int(y - 9 + bob)), 3)
            pygame.draw.rect(surf, (40, 30, 30), (x - 4, y - 3 + bob, 8, 3))
        if e.windup > 0:
            pygame.draw.circle(surf, (255, 70, 60), (int(x), int(y - 4)), 8, 1)

    def _light(self, surf: pygame.Surface, cx: int, cy: int) -> None:
        g = self.g
        p = g.p
        mask = self.mask
        mask.fill(AMBIENT)
        # a faint memory of the layout near the player so the dark is scary but not unreadable
        base_r = 20 if p.hiding is None else 8
        glow = pygame.transform.smoothscale(self.glow, (base_r * 2, base_r * 2))
        glow.fill((14, 16, 20), special_flags=pygame.BLEND_RGB_MULT)
        mask.blit(glow, (int(p.x - cx - base_r), int(p.y - cy - base_r)), special_flags=pygame.BLEND_RGB_ADD)
        # static lamps and windows (cached per door/prop version)
        for lc in g.lamp_cells():
            self._add_static(mask, "lamp", lc, cx, cy, 6.0 * TILE, (255, 190, 120), 0.95)
        for wc in g.lv.windows:
            self._add_static(mask, "win", wc, cx, cy, 4.5 * TILE, (120, 150, 190), 0.55)
        # the player's lights
        if not p.dead and p.hiding is None:
            if p.mode == "flash" and p.battery > 0:
                a = math.radians(p.facing)
                half = math.radians(FLASH_HALF)
                surf_g, pos = self._shaped(p.x, p.y, FLASH_RANGE, a - half, a + half, 26, 1.0, (236, 244, 240))
                mask.blit(surf_g, (pos[0] - cx, pos[1] - cy), special_flags=pygame.BLEND_RGB_ADD)
                small, pos = self._shaped(p.x, p.y, 2.2 * TILE, 0, math.tau, 18, 0.5, (210, 220, 215), True)
                mask.blit(small, (pos[0] - cx, pos[1] - cy), special_flags=pygame.BLEND_RGB_ADD)
            elif p.mode == "lamp" and p.oil > 0:
                flick = 0.92 + 0.08 * math.sin(self.t * 11 + math.sin(self.t * 3))
                surf_g, pos = self._shaped(p.x, p.y, LAMP_RADIUS, 0, math.tau, 40, 0.95 * flick, (255, 190, 110), True)
                mask.blit(surf_g, (pos[0] - cx, pos[1] - cy), special_flags=pygame.BLEND_RGB_ADD)
            if p.match > 0:
                flick = 0.8 + 0.2 * math.sin(self.t * 17)
                surf_g, pos = self._shaped(p.x, p.y, MATCH_RADIUS, 0, math.tau, 24, 0.9 * flick, (255, 170, 90), True)
                mask.blit(surf_g, (pos[0] - cx, pos[1] - cy), special_flags=pygame.BLEND_RGB_ADD)
        for w in g.wards:
            surf_g, pos = self._shaped(w.x, w.y, w.radius * TILE * 1.2, 0, math.tau, 36, 0.9, (255, 214, 150), True)
            mask.blit(surf_g, (pos[0] - cx, pos[1] - cy), special_flags=pygame.BLEND_RGB_ADD)
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    def _add_static(self, mask, tag, cell, cx, cy, radius, tint, intensity) -> None:
        x, y = (cell[0] + 0.5) * TILE, (cell[1] + 0.5) * TILE
        if not (-radius < x - cx < W + radius and -radius < y - cy < H + radius):
            return
        key = (tag, cell)
        s = self.static_lights.get(key)
        if s is None:
            s = self._shaped(x, y, radius, 0, math.tau, 48, intensity, tint, True)
            self.static_lights[key] = s
        mask.blit(s[0], (s[1][0] - cx, s[1][1] - cy), special_flags=pygame.BLEND_RGB_ADD)

    # ------------------------------------------------------------------ sound cues
    def add_ripple(self, x: float, y: float, loud_tiles: float, kind: str) -> None:
        if loud_tiles < 2.5:
            return
        self.ripples.append([x, y, loud_tiles * TILE, 0.0, kind])
        if len(self.ripples) > 24:
            del self.ripples[:8]

    def _ripples(self, surf: pygame.Surface, cx: int, cy: int, dt: float) -> None:
        for r in list(self.ripples):
            r[3] += dt
            life = 0.9
            if r[3] > life:
                self.ripples.remove(r)
                continue
            k = r[3] / life
            rad = r[2] * (0.25 + 0.75 * k)
            a = int(110 * (1 - k))
            col = (120, 210, 200) if r[4] != "enemy" else (230, 120, 110)
            tmp = pygame.Surface((int(rad * 2) + 4, int(rad * 2) + 4), pygame.SRCALPHA)
            pygame.draw.circle(tmp, (*col, a), (tmp.get_width() // 2, tmp.get_height() // 2), int(rad), 1)
            surf.blit(tmp, (r[0] - cx - tmp.get_width() // 2, r[1] - cy - tmp.get_height() // 2))
