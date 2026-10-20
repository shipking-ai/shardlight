"""Procedural articulated fighters, ink-wash stages and the match HUD.

Poses are *derived from the same frame data that drives the hitboxes*: the striking limb is solved with
two-bone IK toward the centre of the active hitbox, wound back during startup and relaxed during recovery.
So what you see during startup/active/recovery always agrees with what the simulation does.
"""
from __future__ import annotations

import math
import random

import pygame

from ...core import art
from ...core.fx import blit_additive_glow, clamp, ease_out_cubic, lerp, mix, radial_gradient
from ...core.ui import BRASS, DANGER, DIM, GOOD, INK, LENS, PARCHMENT
from .sim import consts as C
from .sim.fight import Fighter, Match
from .sim.moves import Character

W, H = 480, 270
GROUND_Y = 226
SKIN = (238, 202, 168)
SKIN_D = (196, 152, 124)


# ---------------------------------------------------------------------------------------- IK
def ik2(a, t, l1, l2, bend=1):
    """Elbow/knee position for a 2-bone chain from ``a`` to ``t`` (y up)."""
    dx, dy = t[0] - a[0], t[1] - a[1]
    d = math.hypot(dx, dy)
    d = max(0.001, min(d, l1 + l2 - 0.05))
    base = math.atan2(dy, dx)
    cos_a = clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1)
    ang = base + bend * math.acos(cos_a)
    return (a[0] + math.cos(ang) * l1, a[1] + math.sin(ang) * l1), (a[0] + dx / max(1e-6, math.hypot(dx, dy)) * d,
                                                                      a[1] + dy / max(1e-6, math.hypot(dx, dy)) * d)


def lp(a, b, k):
    return (lerp(a[0], b[0], k), lerp(a[1], b[1], k))


class Pose:
    """All joint targets in character space (x forward, y up, pixels)."""

    def __init__(self) -> None:
        self.hip_y = 34.0
        self.chest = (0.0, 56.0)
        self.head = (1.0, 68.0)
        self.hand_f = (14.0, 52.0)
        self.hand_b = (7.0, 47.0)
        self.foot_f = (11.0, 0.0)
        self.foot_b = (-9.0, 0.0)
        self.lean = 0.0
        self.angle = 0.0          # whole-body rotation for lying poses (degrees)
        self.glow = 0.0
        self.shift = 0.0
        self.head_tilt = 0


def base_pose(f: Fighter, t: int) -> Pose:
    p = Pose()
    st = f.state
    breath = math.sin(t * 0.11 + f.idx) * 1.2
    p.chest = (0.0, 56 + breath * 0.5)
    p.head = (1.0, 68 + breath * 0.5)
    p.hand_f = (13 + breath * 0.3, 52 + breath * 0.6)
    p.hand_b = (6, 46 + breath * 0.6)
    if st == "crouch" or (st in ("hit", "block") and f.crouch_block):
        p.hip_y, p.chest, p.head = 20.0, (4.0, 40.0), (6.0, 52.0)
        p.foot_f, p.foot_b = (14.0, 0.0), (-10.0, 0.0)
        p.hand_f, p.hand_b = (16.0, 38.0), (9.0, 34.0)
    elif st in ("walkf", "walkb"):
        k = math.sin(f.state_t * 0.55) * (1 if st == "walkf" else -1)
        p.foot_f = (11 + 7 * k, max(0.0, -4 * math.cos(f.state_t * 0.55)))
        p.foot_b = (-9 - 7 * k, max(0.0, 4 * math.cos(f.state_t * 0.55)))
        p.chest = (2.0 if st == "walkf" else -1.0, 55.5)
    elif st in ("air", "prejump") or f.y > 0:
        up = f.vy > 0
        p.foot_f, p.foot_b = (10.0, 16.0 if up else 8.0), (-6.0, 20.0 if up else 12.0)
        p.hand_f, p.hand_b = (15.0, 60.0), (-5.0, 56.0)
        p.hip_y = 40.0
        p.chest, p.head = (0.0, 60.0), (1.0, 72.0)
    elif st == "prejump":
        p.hip_y, p.chest = 26.0, (0.0, 46.0)
    elif st in ("dashf", "dashb"):
        sgn = 1 if st == "dashf" else -1
        p.chest, p.head = (5.0 * sgn, 52.0), (7.0 * sgn, 64.0)
        p.foot_f, p.foot_b = (16.0 * sgn, 2.0), (-14.0 * sgn, 6.0)
        p.hand_f, p.hand_b = (18.0 * sgn, 48.0), (-8.0 * sgn, 52.0)
    elif st == "block":
        p.hand_f, p.hand_b = (12.0, 58.0), (14.0, 50.0)
        p.chest, p.head = (-2.0, 55.0), (-1.0, 67.0)
        p.glow = 0.3
    elif st == "hit":
        k = max(0.0, 1 - f.state_t / 10)
        p.chest, p.head = (-6.0 * k - 2, 55.0), (-10.0 * k - 3, 67.0)
        p.hand_f, p.hand_b = (6.0, 62.0), (-4.0, 56.0)
        p.head_tilt = -1
    elif st == "hitair":
        p.angle = -40 if f.vy > 0 else -70
        p.hand_f, p.hand_b = (14.0, 60.0), (-8.0, 60.0)
        p.foot_f, p.foot_b = (9.0, 12.0), (-4.0, 18.0)
    elif st in ("down", "ko", "wake"):
        p.angle = -88 if st != "wake" else -88 + min(88, f.state_t * 14)
        p.hand_f, p.hand_b = (10.0, 40.0), (-6.0, 40.0)
        p.foot_f, p.foot_b = (10.0, 2.0), (-8.0, 2.0)
    elif st == "parry":
        k = ease_out_cubic(f.state_t / 5)
        p.hand_f = (lerp(12, 22, k), lerp(52, 60, k))
        p.glow = 0.6 if f.parry_ok else 0.2
    elif st == "thrown":
        p.angle = -30
        p.hand_f, p.hand_b = (12.0, 60.0), (-6.0, 56.0)
    return p


def attack_pose(f: Fighter, p: Pose) -> None:
    mv = f.move
    if mv is None:
        return
    mf = f.mf
    box = mv.boxes[0] if mv.boxes else None
    if mv.throw:
        k = ease_out_cubic(min(1, mf / max(1, mv.startup)))
        p.hand_f, p.hand_b = (lerp(12, 28, k), 52.0), (lerp(8, 26, k), 46.0)
        p.chest = (lerp(0, 8, k), 52.0)
        return
    if mv.counter:
        p.hand_f, p.hand_b = (12.0, 56.0), (10.0, 52.0)
        p.glow = 0.8 if mv.counter.f0 <= mf <= mv.counter.f1 else 0.3
        return
    if box is None:
        k = ease_out_cubic(min(1, mf / max(1, mv.startup)))
        p.hand_f, p.hand_b = (lerp(12, 24, k), lerp(52, 54, k)), (lerp(7, 18, k), lerp(47, 56, k))
        p.glow = 0.4
        return
    cx = box.rect[0] / C.SUB + box.rect[2] / C.SUB / 2
    cy = box.rect[1] / C.SUB + box.rect[3] / C.SUB / 2
    kick = cy < 34 or (mv.air and cy < 30)
    wind = (-6.0, 50.0) if not kick else (-12.0, 20.0)
    ext = (cx + 6, cy)
    idle_t = p.foot_f if kick else p.hand_f
    if mf < mv.startup:
        k = ease_out_cubic(mf / max(1, mv.startup))
        tgt = lp(idle_t, wind, k)
        lean = -3 * k
    elif mf <= mv.last_active:
        tgt = ext
        lean = 4.0
        p.glow = 0.5
    else:
        k = ease_out_cubic((mf - mv.last_active) / max(1, mv.recovery))
        tgt = lp(ext, idle_t, k)
        lean = 4.0 * (1 - k)
    p.lean = lean
    p.chest = (p.chest[0] + lean, p.chest[1])
    p.head = (p.head[0] + lean * 1.3, p.head[1])
    if kick:
        p.foot_f = tgt
        p.hand_f, p.hand_b = (12.0, 54.0), (4.0, 58.0)
    else:
        p.hand_f = tgt
        if mf >= mv.startup:
            p.shift = clamp((cx - 26) * 0.35, 0, 8)
    if mv.stance == "crouch":
        p.hip_y, p.chest = 20.0, (p.chest[0] + 3, 40.0)
        p.head = (p.head[0] + 5, 52.0)
        if not kick:
            p.foot_f, p.foot_b = (14.0, 0.0), (-10.0, 0.0)


def compute_pose(f: Fighter) -> Pose:
    t = f.state_t + f.idx * 17
    p = base_pose(f, t)
    if f.state == "attack":
        attack_pose(f, p)
    return p


# ---------------------------------------------------------------------------------------- drawing
def _limb(surf, col, edge, a, b, c, w):
    for pts, ww, cc in (((a, b, c), w + 2, edge), ((a, b, c), w, col)):
        pygame.draw.line(surf, cc, pts[0], pts[1], ww)
        pygame.draw.line(surf, cc, pts[1], pts[2], ww)
        for q in pts:
            pygame.draw.circle(surf, cc, (round(q[0]), round(q[1])), max(1, ww // 2))


def draw_mask(surf, cid: str, c, r: int, tilt: int, color, accent, t: int) -> None:
    x, y = c
    base = (244, 238, 224) if cid not in ("kagari", "ushi") else mix(color, (255, 255, 255), 0.15)
    ink = (22, 18, 34)
    pygame.draw.circle(surf, ink, (x, y), r + 1)
    pygame.draw.circle(surf, base, (x, y), r)
    if cid == "kagari":           # horned oni: red mask, gold eye slits, tusks
        pygame.draw.polygon(surf, accent, [(x - 5, y - 4), (x - 7, y - 11), (x - 2, y - 6)])
        pygame.draw.polygon(surf, accent, [(x + 5, y - 4), (x + 7, y - 11), (x + 2, y - 6)])
        pygame.draw.line(surf, accent, (x - 4, y - 1), (x - 1, y), 1)
        pygame.draw.line(surf, accent, (x + 1, y), (x + 4, y - 1), 1)
        pygame.draw.line(surf, ink, (x - 3, y + 3), (x + 3, y + 3), 1)
        surf.set_at((x - 3, y + 4), (250, 250, 240))
        surf.set_at((x + 3, y + 4), (250, 250, 240))
    elif cid == "mirei":          # weeping mask with hood
        pygame.draw.arc(surf, color, pygame.Rect(x - r - 1, y - r - 2, r * 2 + 2, r * 2 + 2), 0.2, 2.94, 3)
        pygame.draw.line(surf, ink, (x - 4, y - 1), (x - 1, y), 1)
        pygame.draw.line(surf, ink, (x + 1, y), (x + 4, y - 1), 1)
        pygame.draw.line(surf, (110, 160, 240), (x - 3, y + 1), (x - 3, y + 6), 1)
        pygame.draw.line(surf, ink, (x - 2, y + 4), (x + 2, y + 4), 1)
    elif cid == "ushi":           # bull mask: wide horns, nose ring
        pygame.draw.line(surf, accent, (x - 5, y - 4), (x - 10, y - 8), 2)
        pygame.draw.line(surf, accent, (x + 5, y - 4), (x + 10, y - 8), 2)
        pygame.draw.line(surf, ink, (x - 4, y - 1), (x - 1, y - 1), 1)
        pygame.draw.line(surf, ink, (x + 1, y - 1), (x + 4, y - 1), 1)
        pygame.draw.circle(surf, accent, (x, y + 4), 2, 1)
    elif cid == "shizuka":        # serene noh mask: curved closed eyes
        pygame.draw.arc(surf, ink, pygame.Rect(x - 5, y - 3, 4, 3), 3.4, 6.0, 1)
        pygame.draw.arc(surf, ink, pygame.Rect(x + 1, y - 3, 4, 3), 3.4, 6.0, 1)
        pygame.draw.line(surf, color, (x - 2, y + 4), (x + 2, y + 4), 1)
        pygame.draw.circle(surf, color, (x, y - 5), 1)
    elif cid == "toki":           # hourglass mask with clock ticks
        pygame.draw.polygon(surf, color, [(x - 3, y - 3), (x + 3, y - 3), (x, y), (x + 3, y + 4), (x - 3, y + 4), (x, y)])
        a = t * 0.12
        pygame.draw.line(surf, ink, (x, y + 1), (x + math.cos(a) * 3, y + 1 + math.sin(a) * 3), 1)
        for k in range(4):
            surf.set_at((x + round(math.cos(k * 1.57) * (r - 1)), y + round(math.sin(k * 1.57) * (r - 1))), accent)
    else:                         # silence: blank mask, a single vertical seam
        pygame.draw.line(surf, (190, 186, 200), (x, y - r + 1), (x, y + r - 1), 1)
        pygame.draw.circle(surf, (190, 186, 200), (x, y), r, 1)


def draw_fighter(surf: pygame.Surface, f: Fighter, cam_x: float, t: int, flash: float = 0.0,
                 shadow: bool = True) -> None:
    ch: Character = f.char
    p = compute_pose(f)
    fx = f.x / C.SUB
    fy = f.y / C.SUB
    ox = 240 + (fx - cam_x) + p.shift * f.facing
    oy = GROUND_Y - fy
    s = f.facing
    body = ch.color
    dark = art.shade(body, -0.45)
    lite = art.shade(body, 0.35)
    if flash > 0:
        body = mix(body, (255, 255, 255), flash)
        dark = mix(dark, (255, 255, 255), flash)
        lite = mix(lite, (255, 255, 255), flash)
    edge = (14, 10, 26)
    rot = math.radians(p.angle * s)

    def P(q):
        x, y = q
        if p.angle:
            cx, cy = 0.0, 30.0
            dx, dy = x - cx, y - cy
            c, sn = math.cos(rot), math.sin(rot)
            x, y = cx + dx * c - dy * sn, cy + dx * sn + dy * c
            y -= 0
        return (ox + x * s, oy - y)

    if shadow:
        art.draw_shadow(surf, (240 + (fx - cam_x), GROUND_Y + 1), 30, 7, 110)
    hip = (0.0, p.hip_y)
    hipf, hipb = (3.0, p.hip_y), (-3.0, p.hip_y)
    knee_f, foot_f = ik2(hipf, p.foot_f, 16, 17, 1)
    knee_b, foot_b = ik2(hipb, p.foot_b, 16, 17, 1)
    sh = (p.chest[0], p.chest[1] - 2)
    el_b, hand_b = ik2(sh, p.hand_b, 11, 11, -1)
    el_f, hand_f = ik2(sh, p.hand_f, 11, 11, -1)
    # back arm and leg first
    _limb(surf, dark, edge, P(sh), P(el_b), P(hand_b), 4)
    _limb(surf, dark, edge, P(hipb), P(knee_b), P(foot_b), 5)
    # torso (gi) + sash
    pts = [P((-5, p.hip_y + 2)), P((5, p.hip_y + 2)), P((p.chest[0] + 6, p.chest[1])), P((p.chest[0] - 6, p.chest[1]))]
    pygame.draw.polygon(surf, edge, pts, 3)
    pygame.draw.polygon(surf, body, pts)
    pygame.draw.line(surf, lite, pts[3], pts[2], 1)
    sash = [P((-5.5, p.hip_y + 4)), P((5.5, p.hip_y + 4)), P((5.8, p.hip_y + 8)), P((-5.8, p.hip_y + 8))]
    pygame.draw.polygon(surf, ch.accent, sash)
    pygame.draw.line(surf, art.shade(ch.accent, -0.5), sash[0], sash[1], 1)
    # front leg and arm
    _limb(surf, body, edge, P(hipf), P(knee_f), P(foot_f), 5)
    pygame.draw.circle(surf, edge, (round(P(foot_f)[0]), round(P(foot_f)[1])), 3)
    pygame.draw.circle(surf, art.shade(body, -0.2), (round(P(foot_f)[0]), round(P(foot_f)[1])), 2)
    pygame.draw.circle(surf, edge, (round(P(foot_b)[0]), round(P(foot_b)[1])), 3)
    pygame.draw.circle(surf, dark, (round(P(foot_b)[0]), round(P(foot_b)[1])), 2)
    # neck + head
    pygame.draw.line(surf, SKIN_D, P((p.chest[0], p.chest[1])), P(p.head), 3)
    draw_mask(surf, ch.id, P(p.head), 6, p.head_tilt, ch.color, ch.accent, t)
    _limb(surf, lite, edge, P(sh), P(el_f), P(hand_f), 4)
    for hnd in (hand_f, hand_b):
        q = P(hnd)
        pygame.draw.circle(surf, edge, (round(q[0]), round(q[1])), 3)
        pygame.draw.circle(surf, SKIN, (round(q[0]), round(q[1])), 2)
    # trailing scarf in accent colour (reads direction of motion)
    sc = [P((p.head[0] - 2, p.head[1] - 5))]
    for k in range(1, 5):
        sc.append(P((p.head[0] - 2 - k * 4 - f.vx / C.SUB * 1.5 * k * 0.3 * (-s) * s, p.head[1] - 5 + math.sin(t * 0.2 + k) * 1.5 - k * 0.5)))
    pygame.draw.lines(surf, ch.accent, False, sc, 2)
    if p.glow > 0:
        g = radial_gradient(22, tuple(int(c * min(1.0, p.glow * 0.8)) for c in ch.accent), 2.2)
        q = P((0, 42))
        surf.blit(g, (q[0] - 22, q[1] - 22), special_flags=pygame.BLEND_RGB_ADD)


# ---------------------------------------------------------------------------------------- stages
class Stage:
    """Ink-wash backdrop with parallax layers, baked once."""

    def __init__(self, kind: str = "shrine", seed: int = 3):
        self.kind = kind
        rng = random.Random(seed)
        self.layers: list[tuple[pygame.Surface, float]] = []
        sky_top, sky_bot, ink = ((236, 227, 207), (214, 196, 172), (38, 34, 52)) if kind == "shrine" else \
                                ((54, 56, 86), (120, 96, 120), (16, 14, 30))
        sky = pygame.Surface((W, H))
        art.dither_vertical(sky, pygame.Rect(0, 0, W, GROUND_Y), sky_top, sky_bot)
        sky.fill(mix(sky_bot, ink, 0.3), (0, GROUND_Y, W, H - GROUND_Y))
        self.sky = sky
        for li, (alpha, par, amp, base_y) in enumerate(((60, 0.08, 52, 150), (110, 0.2, 40, 176), (190, 0.4, 26, 196))):
            wide = W + 120
            s = pygame.Surface((wide, H), pygame.SRCALPHA)
            ph = rng.random() * 6
            col = (*mix(ink, sky_bot, 0.55 - li * 0.2), alpha)
            pts = [(0, H)]
            for x in range(0, wide + 8, 8):
                y = base_y - amp * (0.5 + 0.5 * math.sin(x * 0.015 + ph) * math.sin(x * 0.037 + ph * 2)) ** 1.5
                pts.append((x, y))
            pts.append((wide, H))
            pygame.draw.polygon(s, col, pts)
            self.layers.append((s, par))
        # ground: planks with worn ink, lantern posts
        g = pygame.Surface((W + 80, H - GROUND_Y), pygame.SRCALPHA)
        ground_col = mix(ink, (90, 74, 62), 0.55) if kind == "shrine" else mix(ink, (70, 70, 110), 0.5)
        g.fill((*ground_col, 255))
        for x in range(0, W + 80, 20):
            pygame.draw.line(g, mix(ground_col, (0, 0, 0), 0.4), (x, 0), (x, H - GROUND_Y))
        pygame.draw.line(g, mix(ground_col, (255, 244, 220), 0.4), (0, 0), (W + 80, 0))
        pygame.draw.line(g, mix(ground_col, (0, 0, 0), 0.5), (0, 3), (W + 80, 3))
        self.ground = g
        self.ink = ink
        self.lantern_x = [-190, -60, 70, 200] if kind == "shrine" else [-150, 150]
        self.rain = [(rng.random() * W, rng.random() * H, 2 + rng.random() * 2) for _ in range(70)] if kind != "shrine" else []

    def draw(self, surf: pygame.Surface, cam_x: float, t: int) -> None:
        surf.blit(self.sky, (0, 0))
        for layer, par in self.layers:
            surf.blit(layer, (-60 - cam_x * par, 0))
        # sun / moon disc
        disc = (236, 90, 70) if self.kind == "shrine" else (240, 236, 214)
        pygame.draw.circle(surf, disc, (int(340 - cam_x * 0.04), 70), 22 if self.kind == "shrine" else 14)
        surf.blit(self.ground, (-40 - cam_x % 1, GROUND_Y))
        for lx in self.lantern_x:
            x = int(240 + lx - cam_x)
            if -20 < x < W + 20:
                pygame.draw.line(surf, (30, 24, 36), (x, GROUND_Y - 70), (x, GROUND_Y), 2)
                pygame.draw.rect(surf, (30, 24, 36), (x - 7, GROUND_Y - 84, 14, 3))
                glow = 0.75 + 0.25 * math.sin(t * 0.07 + lx)
                lan = pygame.Rect(x - 5, GROUND_Y - 81, 10, 14)
                pygame.draw.rect(surf, (222, 70, 40), lan)
                pygame.draw.rect(surf, (255, int(190 * glow), 90), lan.inflate(-4, -4))
                pygame.draw.rect(surf, (30, 24, 36), lan, 1)
                blit_additive_glow(surf, (x, GROUND_Y - 74), 26, (int(80 * glow), int(40 * glow), int(14 * glow)), 2.0)
        if self.rain:
            for rx, ry, sp in self.rain:
                y = (ry + t * sp * 3) % H
                surf.fill((170, 180, 220), (int((rx - t * 0.6 * sp) % W), int(y), 1, 4))


# ---------------------------------------------------------------------------------------- HUD / fx
class Sparks:
    def __init__(self) -> None:
        self.items: list[list] = []

    def add(self, x: float, y: float, kind: str, facing: int = 1) -> None:
        n = {"light": 6, "med": 9, "heavy": 14, "slash": 10, "ring": 8}.get(kind, 6)
        col = {"light": (255, 240, 200), "med": (255, 210, 120), "heavy": (255, 140, 80), "slash": (190, 220, 255),
               "ring": (255, 255, 255)}.get(kind, (255, 240, 200))
        for i in range(n):
            a = math.tau * i / n + random.random() * 0.4
            sp = 1.5 + random.random() * (3 if kind != "heavy" else 5)
            self.items.append([x, y, math.cos(a) * sp, math.sin(a) * sp, 10 + random.randint(0, 6), col, kind])
        self.items.append([x, y, 0, 0, 8, col, "flash"])

    def update(self) -> None:
        for s in self.items:
            s[0] += s[2]
            s[1] += s[3]
            s[2] *= 0.9
            s[3] *= 0.9
            s[4] -= 1
        self.items = [s for s in self.items if s[4] > 0]

    def draw(self, surf: pygame.Surface, cam_x: float) -> None:
        for x, y, vx, vy, life, col, kind in self.items:
            sx, sy = 240 + x - cam_x, GROUND_Y - y
            if kind == "flash":
                r = 3 + (8 - life) * 2
                pygame.draw.circle(surf, col, (int(sx), int(sy)), r, 1 if life < 5 else 0)
            else:
                pygame.draw.line(surf, col, (sx, sy), (sx - vx * 2, sy - vy * 2), 2 if life > 6 else 1)


def draw_projectiles(surf: pygame.Surface, m: Match, cam_x: float, t: int) -> None:
    for p in m.projs:
        sx = 240 + p.x / C.SUB - cam_x
        sy = GROUND_Y - p.y / C.SUB
        ch = m.chars[p.owner]
        w, h = p.rect[2] // C.SUB, p.rect[3] // C.SUB
        col = ch.accent
        if h > 30:
            pygame.draw.rect(surf, col, (sx - 4, sy - h // 2, 8, h))
            pygame.draw.rect(surf, (255, 255, 255), (sx - 1, sy - h // 2, 2, h))
        else:
            pygame.draw.polygon(surf, col, [(sx - p.facing * w // 2, sy), (sx + p.facing * w // 2, sy - h // 2),
                                            (sx + p.facing * (w // 2 + 4), sy), (sx + p.facing * w // 2, sy + h // 2)])
            pygame.draw.line(surf, (255, 255, 255), (sx - p.facing * w, sy), (sx + p.facing * w // 2, sy), 1)
    for z in m.zones:
        sx = 240 + z.x / C.SUB - cam_x
        w = z.rect[2] // C.SUB
        h = z.rect[3] // C.SUB
        ring = pygame.Surface((w, h), pygame.SRCALPHA)
        a = 36 + int(14 * math.sin(t * 0.1))
        pygame.draw.ellipse(ring, (*m.chars[z.owner].accent, a), ring.get_rect())
        pygame.draw.ellipse(ring, (*m.chars[z.owner].color, 150), ring.get_rect(), 1)
        surf.blit(ring, (sx - w // 2, GROUND_Y - h))
        for k in range(8):
            ang = t * 0.03 + k * 0.785
            surf.set_at((int(sx + math.cos(ang) * w * 0.4), int(GROUND_Y - h / 2 + math.sin(ang) * h * 0.4)), (255, 235, 190))
    for e in m.echoes:
        if e.t < e.delay:
            sx = 240 + e.x / C.SUB - cam_x
            k = e.t / e.delay
            ghost = pygame.Surface((26, 84), pygame.SRCALPHA)
            pygame.draw.ellipse(ghost, (*m.chars[e.owner].accent, int(40 + 70 * k)), ghost.get_rect(), 1)
            surf.blit(ghost, (sx - 13, GROUND_Y - 80))


def bar(surf, rect, frac, color, back=(30, 26, 44), flip=False, chip=None):
    x, y, w, h = rect
    pygame.draw.rect(surf, (10, 8, 20), (x - 1, y - 1, w + 2, h + 2))
    pygame.draw.rect(surf, back, rect)
    if chip is not None and chip > frac:
        cw = int(w * chip)
        surf.fill((250, 214, 120), (x + w - cw if flip else x, y, cw, h))
    fw = int(w * clamp(frac))
    surf.fill(color, (x + w - fw if flip else x, y, fw, h))
    surf.fill(art.shade(color, 0.4), (x + w - fw if flip else x, y, fw, 1))


def draw_hud(surf: pygame.Surface, app, m: Match, chip: list[float], banner: str | None, banner_t: float,
             show_input: list[str] | None = None) -> None:
    f = app.font
    for i, ft in enumerate(m.fighters):
        flip = i == 1
        x = 12 if not flip else W - 12 - 176
        frac = ft.hp / ft.char.health
        col = mix((220, 70, 60), (120, 230, 140), clamp(frac * 1.4))
        bar(surf, (x, 12, 176, 10), frac, col, flip=flip, chip=chip[i])
        bar(surf, (x, 25, 90 if not flip else 90, 4), ft.meter / C.MAX_METER, (110, 200, 255) if ft.meter < 500 else (255, 214, 110),
            flip=flip) if False else None
        mx = x if not flip else x + 176 - 100
        bar(surf, (mx, 25, 100, 5), ft.meter / C.MAX_METER, (255, 214, 110) if ft.meter >= C.SUPER_COST else (110, 190, 250),
            flip=flip)
        name = ft.char.name.upper()
        f.draw(surf, name, (x if not flip else x + 176, 32), PARCHMENT, (10, 8, 20), anchor="topleft" if not flip else "topright")
        for r in range(m.rounds_to_win):
            won = r < m.wins[i]
            cx = (x + 4 + r * 10) if not flip else (x + 172 - r * 10)
            pygame.draw.circle(surf, (10, 8, 20), (cx, 47), 4)
            pygame.draw.circle(surf, BRASS if won else (50, 46, 66), (cx, 47), 3)
        if ft.combo_hits >= 2 and ft.state in ("hit", "hitair", "down"):
            pass
    # combo counters show on the attacker's side
    for i, ft in enumerate(m.fighters):
        d = m.fighters[1 - i]
        if d.combo_hits >= 2 and d.state in ("hit", "hitair"):
            txt = f"{d.combo_hits} HITS"
            x = 14 if i == 0 else W - 14
            f.draw(surf, txt, (x, 62), (255, 226, 130), (10, 8, 20), anchor="topleft" if i == 0 else "topright", scale=2)
            f.draw(surf, f"{d.combo_dmg} dmg", (x, 82), PARCHMENT, (10, 8, 20), anchor="topleft" if i == 0 else "topright")
    t = max(0, m.timer // C.FPS) if not m.training else 99
    pygame.draw.rect(surf, (10, 8, 20), (W // 2 - 17, 8, 34, 24))
    pygame.draw.rect(surf, BRASS, (W // 2 - 17, 8, 34, 24), 1)
    f.draw(surf, "--" if m.training else f"{t:02d}", (W // 2, 12), PARCHMENT if t > 10 else DANGER, None, anchor="midtop", scale=2)
    if banner:
        k = ease_out_cubic(banner_t / 0.25)
        f.draw(surf, banner, (W // 2, int(90 - (1 - k) * 12)), (255, 244, 205), (10, 8, 20), anchor="midtop", scale=4)
