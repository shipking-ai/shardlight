"""Cinder art: procedurally drawn tower rooms, the Lampwright, enemies, bosses, telegraphs and effects.

Identity: charcoal and ash, ember orange and gold, sharp angular silhouettes; telegraphs are radial and bright;
braziers throw hard orange rim light against violet shadows.
"""
from __future__ import annotations

import math
import random

import pygame

from ...core import art
from ...core.fx import blit_additive_glow, clamp, mix, radial_gradient
from .sim.entities import ENEMY_TEAM, PLAYER_TEAM
from .sim.levelgen import H_T, TILE, W_T
from .sim.status import STATUS_COLORS

W_PX, H_PX = W_T * TILE, H_T * TILE
INK = (14, 10, 22)
CHAR = (23, 20, 28)
ASH = (58, 51, 64)
EMBER = (255, 122, 60)
GOLD = (255, 194, 90)
VIOLET = (60, 40, 90)
LANTERN = (255, 196, 96)


def pol(surf, color, pts, edge=INK, width=1):
    pygame.draw.polygon(surf, color, pts)
    pygame.draw.polygon(surf, edge, pts, width)


def circ(surf, color, c, r, edge=INK):
    pygame.draw.circle(surf, edge, (int(c[0]), int(c[1])), int(r) + 1)
    pygame.draw.circle(surf, color, (int(c[0]), int(c[1])), int(r))


# ==================================================================================================== room
def bake_room(spec, floor: int) -> pygame.Surface:
    """Static background for a room: stone floor, cracks, wall bricks, door frames."""
    rng = random.Random(spec.seed)
    surf = pygame.Surface((W_PX, H_PX))
    base = mix((46, 40, 56), (66, 38, 50), 0.15 * min(4, floor))
    surf.fill(base)
    for ty in range(H_T):
        for tx in range(W_T):
            ch = spec.layout[ty][tx]
            x, y = tx * TILE, ty * TILE
            if ch in ".D":
                v = rng.randint(-5, 5)
                col = (base[0] + v + 8, base[1] + v + 6, base[2] + v + 10)
                if (tx + ty) % 2:
                    col = (col[0] - 3, col[1] - 3, col[2] - 2)
                pygame.draw.rect(surf, col, (x, y, TILE, TILE))
                pygame.draw.line(surf, (base[0] - 6, base[1] - 6, base[2] - 4), (x, y), (x + TILE - 1, y))
                pygame.draw.line(surf, (base[0] - 6, base[1] - 6, base[2] - 4), (x, y), (x, y + TILE - 1))
                if rng.random() < 0.08:
                    px, py = x + rng.randint(2, 12), y + rng.randint(2, 12)
                    pygame.draw.line(surf, (base[0] - 12, base[1] - 12, base[2] - 8), (px, py), (px + rng.randint(-6, 6), py + rng.randint(2, 6)))
                if rng.random() < 0.03:
                    surf.set_at((x + rng.randint(1, 14), y + rng.randint(1, 14)), (200, 90, 50))
            else:
                _wall_tile(surf, spec, tx, ty, ch, rng)
    # soft edge darkening toward the walls
    vg = pygame.Surface((W_PX, H_PX), pygame.SRCALPHA)
    for i in range(16):
        a = int(110 * (1 - i / 16) ** 2)
        pygame.draw.rect(vg, (6, 3, 12, a), (i, i, W_PX - i * 2, H_PX - i * 2), 1)
    surf.blit(vg, (0, 0))
    return surf


def _wall_tile(surf, spec, tx, ty, ch, rng) -> None:
    x, y = tx * TILE, ty * TILE
    if ch == "o":
        return                                   # braziers are drawn dynamically on top of floor
    below_floor = ty + 1 < H_T and spec.layout[ty + 1][tx] in ".D"
    col = (78, 68, 90)
    pygame.draw.rect(surf, col, (x, y, TILE, TILE))
    off = (ty % 2) * 8
    pygame.draw.line(surf, (40, 34, 48), (x, y + 8), (x + TILE, y + 8))
    pygame.draw.line(surf, (40, 34, 48), (x + (off + 8) % TILE, y), (x + (off + 8) % TILE, y + 8))
    pygame.draw.line(surf, (40, 34, 48), (x + off % TILE, y + 8), (x + off % TILE, y + 16))
    pygame.draw.line(surf, (82, 72, 92), (x, y), (x + TILE - 1, y))
    if below_floor:
        pygame.draw.rect(surf, (96, 84, 104), (x, y + 10, TILE, 6))
        pygame.draw.line(surf, (126, 112, 128), (x, y + 10), (x + TILE - 1, y + 10))
        pygame.draw.line(surf, (30, 24, 38), (x, y + 15), (x + TILE - 1, y + 15))


# ==================================================================================================== lights
def room_lights(room, lighting, ox: int, oy: int, t: int) -> None:
    for p in room.props:
        if p.kind == "brazier":
            fl = 0.8 + 0.2 * math.sin(t * 0.13 + p.x * 0.1) + random.random() * 0.05
            lighting.add((ox + p.x, oy + p.y), 62, (255, 150, 70), 0.75 * fl)
        elif p.kind in ("campfire",):
            lighting.add((ox + p.x, oy + p.y), 70, (255, 160, 80), 0.9)
        elif p.kind in ("stair", "altar", "choir_door", "anvil"):
            lighting.add((ox + p.x, oy + p.y), 52, (255, 210, 130) if p.kind != "choir_door" else (190, 160, 255), 0.7)
    pl = room.player
    lighting.add((ox + pl.x, oy + pl.y), 74, LANTERN, 0.85)
    for d in room.doors.values():
        cx = sum(c[0] for c in d.cells) / len(d.cells) * TILE + 8
        cy = sum(c[1] for c in d.cells) / len(d.cells) * TILE + 8
        lighting.add((ox + cx, oy + cy), 38, (255, 80, 50) if d.locked else (255, 190, 110), 0.55)
    for h in room.hazards:
        if h.kind in ("ember", "fire", "trail") or (h.kind == "vent" and h.armed):
            lighting.add((ox + h.x, oy + h.y), int(h.r * 3), (255, 120, 50), 0.6)
    for e in room.enemies:
        if e.alive and e.edef.art.get("accent"):
            lighting.add((ox + e.x, oy + e.y), 26, tuple(e.edef.art["accent"]), 0.25)
    for pr in room.projectiles:
        lighting.add((ox + pr.x, oy + pr.y), 22, pr.color, 0.5)


# ==================================================================================================== props
def draw_props(surf: pygame.Surface, room, ox: int, oy: int, t: int, near) -> None:
    for p in room.props:
        x, y = ox + p.x, oy + p.y
        k = p.kind
        if k == "brazier":
            pygame.draw.rect(surf, INK, (x - 6, y - 2, 12, 9))
            pygame.draw.rect(surf, (96, 84, 100), (x - 5, y - 1, 10, 7))
            pygame.draw.rect(surf, (60, 50, 70), (x - 5, y + 4, 10, 3))
            fl = int(math.sin(t * 0.3 + p.x) * 2)
            pol(surf, (255, 140, 50), [(x - 4, y), (x - 2, y - 7 - fl), (x, y - 3), (x + 2, y - 9 + fl), (x + 4, y)], (120, 40, 20))
            pol(surf, (255, 220, 120), [(x - 2, y), (x, y - 5), (x + 2, y)], (255, 200, 100), 0)
        elif k == "chest":
            col = (214, 168, 70) if not p.used else (90, 80, 70)
            pygame.draw.rect(surf, INK, (x - 8, y - 5, 16, 12))
            pygame.draw.rect(surf, (120, 70, 40), (x - 7, y - 4, 14, 10))
            pygame.draw.rect(surf, col, (x - 7, y - 4, 14, 3))
            pygame.draw.rect(surf, col, (x - 1, y - 2, 2, 5))
        elif k == "altar":
            pygame.draw.polygon(surf, INK, [(x - 11, y + 6), (x - 8, y - 6), (x + 8, y - 6), (x + 11, y + 6)])
            pygame.draw.polygon(surf, (110, 96, 120), [(x - 10, y + 5), (x - 7, y - 5), (x + 7, y - 5), (x + 10, y + 5)])
            if not p.used:
                art.draw_prism(surf, (x, y - 12 + math.sin(t * 0.07) * 2), 7, GOLD, t * 0.04, True, True)
        elif k == "anvil":
            pygame.draw.rect(surf, INK, (x - 10, y - 3, 20, 10))
            pygame.draw.rect(surf, (96, 92, 110), (x - 9, y - 2, 18, 5))
            pygame.draw.rect(surf, (70, 66, 82), (x - 5, y + 3, 10, 4))
            pygame.draw.polygon(surf, (110, 106, 124), [(x - 12, y - 2), (x - 9, y - 4), (x - 9, y)])
        elif k == "stall":
            pygame.draw.rect(surf, INK, (x - 10, y - 6, 20, 14))
            pygame.draw.rect(surf, (96, 60, 40), (x - 9, y - 5, 18, 12))
            pygame.draw.rect(surf, (214, 70, 60), (x - 10, y - 9, 20, 4))
            for i in range(3):
                pygame.draw.circle(surf, GOLD, (x - 5 + i * 5, y), 2)
        elif k == "campfire":
            pygame.draw.circle(surf, INK, (x, y + 3), 8)
            pygame.draw.circle(surf, (70, 56, 50), (x, y + 3), 7)
            if not p.used:
                fl = int(math.sin(t * 0.25) * 2)
                pol(surf, (255, 150, 50), [(x - 6, y + 3), (x - 3, y - 5 - fl), (x, y), (x + 3, y - 8 + fl), (x + 6, y + 3)], (140, 50, 20))
                pol(surf, (255, 230, 140), [(x - 3, y + 3), (x, y - 3), (x + 3, y + 3)], (255, 220, 120), 0)
        elif k == "stair":
            pygame.draw.rect(surf, INK, (x - 12, y - 8, 24, 18))
            for i in range(4):
                pygame.draw.rect(surf, mix((140, 120, 150), (60, 50, 70), i / 4), (x - 11 + i * 2, y - 7 + i * 4, 22 - i * 4, 3))
            blit_additive_glow(surf, (x, y), 22, (70, 50, 20), 2)
        elif k == "choir_door":
            pygame.draw.rect(surf, INK, (x - 14, y - 14, 28, 28))
            pygame.draw.rect(surf, (60, 40, 100), (x - 12, y - 12, 24, 26))
            for i in range(5):
                pygame.draw.line(surf, (190, 160, 255), (x - 8 + i * 4, y - 9), (x - 8 + i * 4, y + 10), 1)
            blit_additive_glow(surf, (x, y), 30, (60, 40, 100), 2)
    if near is not None:
        f = pygame.font.Font(None, 1) if False else None


def draw_doors(surf: pygame.Surface, room, ox: int, oy: int, t: int) -> None:
    for side, d in room.doors.items():
        xs = [c[0] for c in d.cells]
        ys = [c[1] for c in d.cells]
        rect = pygame.Rect(ox + min(xs) * TILE, oy + min(ys) * TILE, (max(xs) - min(xs) + 1) * TILE, (max(ys) - min(ys) + 1) * TILE)
        if d.hidden:
            for i in range(0, rect.w, 6):
                for j in range(0, rect.h, 6):
                    pygame.draw.rect(surf, (74, 64, 82) if (i + j) // 6 % 2 else (66, 56, 74), (rect.x + i, rect.y + j, 6, 6))
            if d.hits:
                pygame.draw.line(surf, (30, 20, 30), rect.topleft, rect.bottomright, 1)
                pygame.draw.line(surf, (30, 20, 30), (rect.centerx, rect.y), (rect.centerx + 4, rect.bottom), 1)
            continue
        pygame.draw.rect(surf, (8, 6, 14), rect)
        if d.locked:
            n = 4
            for k in range(n):
                if side in ("n", "s"):
                    x = rect.x + 4 + k * (rect.w - 8) // (n - 1)
                    pygame.draw.line(surf, (150, 60, 50), (x, rect.y), (x, rect.bottom), 2)
                else:
                    y = rect.y + 4 + k * (rect.h - 8) // (n - 1)
                    pygame.draw.line(surf, (150, 60, 50), (rect.x, y), (rect.right, y), 2)
        else:
            blit_additive_glow(surf, rect.center, 20, (40, 24, 12), 2)
        pygame.draw.rect(surf, (96, 84, 100), rect, 1)


# ==================================================================================================== player
def draw_player(surf: pygame.Surface, room, ox: int, oy: int, t: int, lantern=LANTERN) -> None:
    p = room.player
    run = room.run
    x, y = ox + p.x, oy + p.y
    if not p.alive:
        art.draw_shadow(surf, (x, y + 4), 14)
        pygame.draw.ellipse(surf, (60, 66, 120), (x - 8, y - 2, 16, 8))
        pygame.draw.ellipse(surf, INK, (x - 8, y - 2, 16, 8), 1)
        return
    art.draw_shadow(surf, (x, y + 5), 13 if p.state != "dodge" else 9, alpha=110)
    flash = p.flash > 0
    bob = math.sin(p.walk_phase) * 1.2 if p.moving else 0.0
    cloak = (74, 84, 168) if not flash else (255, 255, 255)
    cloak_l = (108, 120, 210) if not flash else (255, 255, 255)
    cy = y - 5 - p.vault_z + bob
    if p.state == "dodge" and p.dodge_style == "roll":
        a = p.t * 0.9
        circ(surf, cloak, (x, y - 3), 6)
        pygame.draw.line(surf, cloak_l, (x + math.cos(a) * 5, y - 3 + math.sin(a) * 5), (x - math.cos(a) * 5, y - 3 - math.sin(a) * 5), 2)
        pygame.draw.circle(surf, (255, 235, 180), (int(x + math.cos(a) * 4), int(y - 3 + math.sin(a) * 4)), 2)
        return
    if p.state == "dodge":
        cy -= 2
    # cloak body
    f = p.facing
    fx, fy = math.cos(f), math.sin(f)
    pts = [(x - 6, y + 2), (x - 4, cy - 1), (x + 4, cy - 1), (x + 6, y + 2)]
    pol(surf, cloak, pts)
    pygame.draw.line(surf, cloak_l, (x - 3, cy), (x - 4, y + 1), 1)
    # hood and face toward facing
    circ(surf, cloak, (x + fx * 1.2, cy - 3 + fy * 0.6), 4)
    pygame.draw.circle(surf, (240, 206, 170), (int(x + fx * 2.6), int(cy - 3 + fy * 1.4)), 1)
    # lantern on the opposite hip
    lx, ly = x - fy * 6 - fx * 2, cy + 3 + fx * 2
    blit_additive_glow(surf, (lx, ly), 9, tuple(c // 3 for c in lantern), 2)
    pygame.draw.rect(surf, lantern, (int(lx) - 1, int(ly) - 1, 3, 3))
    # weapon
    _draw_weapon(surf, p, room, x, cy + 1, t)
    if p.parry_active or (p.state == "parry"):
        k = 1.0 - p.parry_t / max(1, p.parry_window)
        r = 12 + (0 if p.parry_t < p.parry_window else 2)
        col = (255, 255, 255) if p.parry_t < p.parry_window else (150, 160, 200)
        pygame.draw.arc(surf, col, pygame.Rect(x - r, cy - r, r * 2, r * 2), -f - 1.0, -f + 1.0, 2)
    if p.perfect_flash > 0:
        pygame.draw.circle(surf, (255, 255, 255), (int(x), int(cy)), 9 + (18 - p.perfect_flash), 1)
    if room.shield_t > 0:
        pygame.draw.circle(surf, (140, 200, 255), (int(x), int(cy)), 11, 1)
    if p.armor:
        pygame.draw.circle(surf, (255, 210, 120), (int(x), int(cy)), 10, 1)
    if p.state == "charge":
        tiers = len(p.weapon.heavy)
        k = p.charge_tier + 1
        pygame.draw.circle(surf, mix((255, 150, 60), (255, 255, 200), k / tiers), (int(x), int(cy - 12)), 2 + k)
        blit_additive_glow(surf, (x, cy - 12), 8 + 4 * k, (120, 70, 20), 2)
    _status_icons(surf, p, x, cy - 12)


def _draw_weapon(surf, p, room, x: float, y: float, t: int) -> None:
    w = p.weapon
    fam = w.family
    ang = p.swing_angle()
    f = p.facing
    if ang is None:
        ang = f + 0.9 if fam != "caster" else f
    col = w.color
    hand = (x + math.cos(ang + 0.6) * 5, y + math.sin(ang + 0.6) * 5) if fam != "caster" else (x + math.cos(f) * 5, y + math.sin(f) * 5)
    swing = p.state == "attack"
    if fam == "blade":
        L = 15 + (3 if swing else 0)
        tip = (hand[0] + math.cos(ang) * L, hand[1] + math.sin(ang) * L)
        pygame.draw.line(surf, INK, hand, tip, 4)
        pygame.draw.line(surf, mix(col, (255, 255, 255), 0.5), hand, tip, 2)
        pygame.draw.circle(surf, GOLD, (int(hand[0]), int(hand[1])), 2)
    elif fam == "hammer":
        tip = (hand[0] + math.cos(ang) * 14, hand[1] + math.sin(ang) * 14)
        pygame.draw.line(surf, INK, hand, tip, 3)
        pygame.draw.line(surf, (150, 110, 80), hand, tip, 1)
        hx, hy = tip
        pygame.draw.circle(surf, INK, (int(hx), int(hy)), 6)
        pygame.draw.circle(surf, col, (int(hx), int(hy)), 5)
        pygame.draw.circle(surf, mix(col, (255, 255, 255), 0.4), (int(hx - 1), int(hy - 1)), 2)
    elif fam == "spear":
        L = 24 + (10 if swing else 0)
        tip = (hand[0] + math.cos(ang) * L, hand[1] + math.sin(ang) * L)
        base = (hand[0] - math.cos(ang) * 8, hand[1] - math.sin(ang) * 8)
        pygame.draw.line(surf, INK, base, tip, 3)
        pygame.draw.line(surf, (150, 120, 90), base, tip, 1)
        pygame.draw.circle(surf, mix(col, (255, 255, 255), 0.5), (int(tip[0]), int(tip[1])), 2)
    else:
        tip = (hand[0] + math.cos(f) * 6, hand[1] + math.sin(f) * 6)
        pygame.draw.line(surf, INK, (x, y), tip, 3)
        pygame.draw.line(surf, (150, 110, 80), (x, y), tip, 1)
        glow = 3 + (2 if swing else 0)
        blit_additive_glow(surf, tip, 8 + glow, tuple(c // 2 for c in col), 2)
        pygame.draw.circle(surf, col, (int(tip[0]), int(tip[1])), 2)


def _status_icons(surf, e, x: float, y: float) -> None:
    names = e.status.names()
    for i, n in enumerate(names):
        c = STATUS_COLORS.get(n, (255, 255, 255))
        pygame.draw.rect(surf, INK, (x - len(names) * 3 + i * 6 - 1, y - 1, 5, 5))
        pygame.draw.rect(surf, c, (x - len(names) * 3 + i * 6, y, 3, 3))


# ==================================================================================================== enemies
def draw_enemy(surf: pygame.Surface, e, ox: int, oy: int, t: int) -> None:
    d = e.edef
    x, y = ox + e.x, oy + e.y
    if not e.alive:
        k = e.dead_t / 40.0
        if k < 1:
            art.draw_shadow(surf, (x, y + 4), int(e.r * 2.4 * (1 - k)))
            col = d.art.get("body", (150, 110, 96))
            pygame.draw.circle(surf, mix(col, (255, 150, 60), 1 - k), (int(x), int(y)), int(e.r * (1 - k) + 1))
        return
    if e.spawn_t > 0:
        k = 1 - e.spawn_t / 40.0
        pygame.draw.circle(surf, (255, 120, 60), (int(x), int(y)), int(10 * k) + 2, 1)
        for i in range(6):
            a = i * 1.047 + t * 0.2
            surf.set_at((int(x + math.cos(a) * 9 * (1 - k)), int(y + math.sin(a) * 9 * (1 - k))), (255, 220, 120))
        return
    art.draw_shadow(surf, (x, y + e.r * 0.8), int(e.r * 2.6))
    body = tuple(d.art.get("body", (150, 110, 96)))
    acc = tuple(d.art.get("accent", EMBER))
    shape = d.art.get("shape", "hunched")
    if e.flash > 0:
        body = (255, 255, 255)
    if e.stun > 0 and e.stun % 8 < 4:
        body = mix(body, (255, 255, 160), 0.4)
    if e.elite:
        pygame.draw.circle(surf, GOLD, (int(x), int(y)), int(e.r) + 3, 1)
    br = e.brain
    bob = math.sin(e.anim * 4) * 1.0
    f = e.facing
    fx, fy = math.cos(f), math.sin(f)
    r = e.r
    if shape == "hunched":
        circ(surf, body, (x, y - 3 + bob), r)
        circ(surf, art.shade(body, 0.2), (x + fx * 4, y - 6 + fy * 2 + bob), 3)
        for s in (-1, 1):
            hx, hy = x + fx * 5 - fy * 5 * s, y - 2 + fy * 5 + fx * 5 * s
            pygame.draw.line(surf, INK, (x, y - 2), (hx, hy), 3)
            pygame.draw.line(surf, body, (x, y - 2), (hx, hy), 1)
        surf.set_at((int(x + fx * 5), int(y - 6 + fy * 2 + bob)), acc)
        surf.set_at((int(x + fx * 5 + 1), int(y - 6 + fy * 2 + bob)), acc)
    elif shape == "archer":
        pol(surf, body, [(x - 4, y + 4), (x - 3, y - 7 + bob), (x + 3, y - 7 + bob), (x + 4, y + 4)])
        circ(surf, art.shade(body, 0.2), (x, y - 9 + bob), 3)
        bx, by = x + fx * 7, y - 2 + fy * 4
        pygame.draw.arc(surf, acc, pygame.Rect(bx - 6, by - 6, 12, 12), -f - 1.2, -f + 1.2, 2)
        if br.state == "aim":
            k = br.t / max(1, e.params["windup"])
            pygame.draw.line(surf, (255, 200, 120), (x, y - 2), (x + fx * 12 * k, y - 2 + fy * 12 * k), 1)
    elif shape == "shield":
        circ(surf, body, (x, y - 2 + bob), r)
        circ(surf, art.shade(body, 0.2), (x - fx * 2, y - 8 + bob), 3)
        if e.guard_front:
            half = e.guard_arc / 2
            pts = [(x + math.cos(f + a) * (r + 5), y + math.sin(f + a) * (r + 5) - 2) for a in (-half * 0.75, -half * 0.25, half * 0.25, half * 0.75)]
            pygame.draw.lines(surf, INK, False, pts, 6)
            pygame.draw.lines(surf, (190, 196, 214), False, pts, 4)
            pygame.draw.lines(surf, acc, False, pts, 1)
        else:
            sx, sy = x - fx * 7, y - fy * 7 - 2
            pygame.draw.circle(surf, (150, 156, 174), (int(sx), int(sy)), 4)
        pygame.draw.line(surf, INK, (x, y - 2), (x + fx * (r + 8), y + fy * (r + 8) - 2), 3)
    elif shape == "imp":
        flash = br.state == "fuse" and (br.t // 3) % 2 == 0
        circ(surf, (255, 255, 255) if flash else body, (x, y - 2 + bob), r + 1)
        pol(surf, body, [(x - 3, y - 6), (x - 5, y - 11), (x - 1, y - 7)])
        pol(surf, body, [(x + 3, y - 6), (x + 5, y - 11), (x + 1, y - 7)])
        sp = (x + fx * 3, y - 9 + bob)
        pygame.draw.circle(surf, GOLD, (int(sp[0]), int(sp[1])), 2 if (t // 3) % 2 else 1)
        if br.state == "fuse":
            blit_additive_glow(surf, (x, y), 18, (100, 40, 10), 2)
    elif shape == "brute":
        circ(surf, body, (x, y - 3 + bob), r)
        horn_l = (x + fx * 7 - fy * 7, y - 6 + fy * 7 + fx * 7)
        horn_r = (x + fx * 7 + fy * 7, y - 6 + fy * 7 - fx * 7)
        pol(surf, (230, 220, 200), [(x + fx * 2 - fy * 3, y - 5 + fy * 2 + fx * 3), horn_l, (x + fx * 2 - fy * 1, y - 5 + fy * 2 + fx * 1)])
        pol(surf, (230, 220, 200), [(x + fx * 2 + fy * 3, y - 5 + fy * 2 - fx * 3), horn_r, (x + fx * 2 + fy * 1, y - 5 + fy * 2 - fx * 1)])
        if br.state in ("tell", "charge"):
            blit_additive_glow(surf, (x, y - 3), 18, (110, 30, 10), 2)
            pygame.draw.circle(surf, acc, (int(x + fx * 4), int(y - 4)), 2)
    elif shape == "robed":
        pol(surf, body, [(x - 6, y + 5), (x - 3, y - 9 + bob), (x + 3, y - 9 + bob), (x + 6, y + 5)])
        circ(surf, art.shade(body, 0.3), (x, y - 11 + bob), 3)
        a = t * 0.08
        for i in range(3):
            gx, gy = x + math.cos(a + i * 2.09) * 9, y - 6 + math.sin(a + i * 2.09) * 4
            pygame.draw.circle(surf, acc, (int(gx), int(gy)), 1)
        if br.state == "cast":
            k = br.t / max(1, e.params["cast"])
            pygame.draw.circle(surf, acc, (int(x), int(y)), int(8 + 10 * k), 1)
    elif shape == "turret":
        pygame.draw.rect(surf, INK, (x - 7, y - 7, 14, 14))
        pygame.draw.rect(surf, body, (x - 6, y - 6, 12, 12))
        pygame.draw.rect(surf, art.shade(body, 0.3), (x - 6, y - 6, 12, 3))
        pygame.draw.line(surf, INK, (x, y), (x + fx * 11, y + fy * 11), 4)
        pygame.draw.line(surf, acc if br.state == "aim" else (120, 110, 130), (x, y), (x + fx * 11, y + fy * 11), 2)
    else:
        circ(surf, body, (x, y), r)
    if e.hp < e.max_hp and e.max_hp < 200:
        w = 14
        pygame.draw.rect(surf, INK, (x - w // 2 - 1, y - r - 9, w + 2, 4))
        pygame.draw.rect(surf, (220, 70, 60), (x - w // 2, y - r - 8, int(w * clamp(e.hp / e.max_hp)), 2))
    if br.aware and br.react > 0:
        surf.fill(GOLD, (int(x) - 1, int(y - r - 14), 2, 5))
        surf.fill(GOLD, (int(x) - 1, int(y - r - 7), 2, 2))
    _status_icons(surf, e, x, y - r - 12)


def draw_boss(surf: pygame.Surface, e, ox: int, oy: int, t: int) -> None:
    x, y = ox + e.x, oy + e.y
    bid = e.boss_id
    if not e.alive:
        k = e.dead_t / 40.0
        if k < 1:
            pygame.draw.circle(surf, mix((255, 220, 140), (80, 40, 30), k), (int(x), int(y)), int(e.r * (1.5 - k)))
        return
    flash = e.flash > 0
    art.draw_shadow(surf, (x, y + e.r * 0.9), int(e.r * 3), alpha=120)
    f = e.facing
    fx, fy = math.cos(f), math.sin(f)
    phase = e.brain.phase
    inv = e.untargetable and e.brain.pause > 0
    if bid == "slag_colossus":
        base = (96, 82, 90) if not flash else (255, 255, 255)
        heat = (255, 110 + int(40 * math.sin(t * 0.1)), 40)
        circ(surf, base, (x, y - 4), e.r)
        for i in range(6):
            a = i * 1.05 + 0.3
            pygame.draw.line(surf, heat, (x + math.cos(a) * 3, y - 4 + math.sin(a) * 3), (x + math.cos(a) * (e.r - 2), y - 4 + math.sin(a) * (e.r - 2)), 1)
        for s in (-1, 1):                          # arms
            hx, hy = x + fx * 12 - fy * 13 * s, y - 2 + fy * 12 + fx * 13 * s
            pygame.draw.line(surf, INK, (x, y - 4), (hx, hy), 7)
            pygame.draw.line(surf, base, (x, y - 4), (hx, hy), 5)
            circ(surf, heat if phase else base, (hx, hy), 5)
        circ(surf, art.shade(base, 0.2), (x + fx * 4, y - 12), 6)
        pygame.draw.rect(surf, heat, (int(x + fx * 4) - 3, int(y - 13), 6, 2))
        blit_additive_glow(surf, (x, y - 4), int(e.r * 2.2), (70, 30, 10), 2)
    elif bid == "crown_of_embers":
        gold = (255, 210, 110) if not flash else (255, 255, 255)
        bob = math.sin(t * 0.05) * 3
        cy = y - 8 + bob
        pygame.draw.ellipse(surf, INK, (x - e.r - 1, cy - 5, e.r * 2 + 2, 14))
        pygame.draw.ellipse(surf, (60, 40, 70), (x - e.r, cy - 4, e.r * 2, 12))
        for i in range(7):                         # crown spikes
            a = math.pi + i * math.pi / 6
            px, py = x + math.cos(a) * e.r, cy + math.sin(a) * 6
            pol(surf, gold, [(px - 3, py + 2), (px, py - 9 - (3 if i % 2 else 0)), (px + 3, py + 2)])
            pygame.draw.circle(surf, EMBER, (int(px), int(py - 9 - (3 if i % 2 else 0))), 2)
        circ(surf, (255, 240, 200), (x, cy + 1), 4 + int(abs(math.sin(t * 0.1)) * 2))
        blit_additive_glow(surf, (x, cy), int(e.r * 3), (90, 40, 10), 2)
    else:
        robe = (150, 130, 200) if not flash else (255, 255, 255)
        pol(surf, robe, [(x - 11, y + 8), (x - 6, y - 14), (x + 6, y - 14), (x + 11, y + 8)])
        circ(surf, (230, 224, 250), (x, y - 17), 5)
        pygame.draw.circle(surf, (210, 190, 255), (int(x), int(y - 17)), 11, 1)
        pygame.draw.circle(surf, (210, 190, 255), (int(x), int(y - 17)), 13 + int(math.sin(t * 0.1) * 1.5), 1)
        for o in e.brain.orbs:
            ox_, oy_ = x + math.cos(o[0]) * o[1], y - 8 + math.sin(o[0]) * o[1] * 0.6
            circ(surf, (230, 214, 255), (ox_, oy_), 3)
            blit_additive_glow(surf, (ox_, oy_), 12, (60, 40, 110), 2)
        blit_additive_glow(surf, (x, y - 10), 36, (50, 30, 90), 2)
    if inv:
        pygame.draw.circle(surf, (255, 255, 255), (int(x), int(y - 4)), int(e.r + 6), 1)


def draw_boss_bar(surf: pygame.Surface, e, font, w: int) -> None:
    if not e.alive:
        return
    bw = 240
    x = (w - bw) // 2
    y = 253
    pygame.draw.rect(surf, INK, (x - 2, y - 2, bw + 4, 10))
    pygame.draw.rect(surf, (50, 30, 40), (x, y, bw, 6))
    pygame.draw.rect(surf, (220, 70, 60) if not e.untargetable else (200, 200, 220), (x, y, int(bw * clamp(e.hp / e.max_hp)), 6))
    for th in (0.66, 0.55, 0.28):
        pass
    font.draw(surf, e.title, (w // 2, y - 12), (255, 238, 200), (10, 6, 16), anchor="midtop")


# ==================================================================================================== telegraphs / projectiles
def draw_hitboxes(surf: pygame.Surface, room, ox: int, oy: int, t: int, debug: bool = False) -> None:
    for hb in room.hitboxes:
        if hb.done:
            continue
        x, y = ox + hb.x, oy + hb.y
        if hb.team == ENEMY_TEAM and hb.windup > 0 and hb.t < hb.windup:
            k = hb.t / max(1, hb.windup)
            col = (255, 70, 50) if hb.style != "heavy" else (255, 190, 70)
            if hb.style == "line":
                col = (255, 50, 50)
            _shape(surf, hb, x, y, col, k, filled=True, alpha=40 + int(100 * k))
            if hb.parryable and hb.t >= hb.windup - 8:
                pygame.draw.circle(surf, (255, 255, 255), (int(ox + (hb.owner.x if hb.owner else hb.x)),
                                                           int(oy + (hb.owner.y if hb.owner else hb.y)) - 14), 3)
        elif hb.is_active and hb.team == ENEMY_TEAM and hb.damage > 0:
            _shape(surf, hb, x, y, (255, 240, 200), 1.0, filled=True, alpha=170)
        elif hb.team == PLAYER_TEAM and hb.is_active:
            _shape(surf, hb, x, y, (255, 255, 255), 1.0, filled=False, alpha=255, width=1)
        if debug:
            _shape(surf, hb, x, y, (0, 255, 0), 1.0, filled=False, alpha=255)


def _shape(surf, hb, x, y, col, k, filled: bool, alpha: int, width: int = 1) -> None:
    layer = pygame.Surface(surf.get_size(), pygame.SRCALPHA) if filled else None
    tgt = layer if filled else surf
    c = (*col, alpha) if filled else col
    if hb.shape == "arc":
        half = math.radians(hb.arc) / 2
        n = max(6, int(hb.arc / 10))
        pts = [(x, y)] + [(x + math.cos(hb.facing - half + 2 * half * i / n) * hb.reach,
                           y + math.sin(hb.facing - half + 2 * half * i / n) * hb.reach) for i in range(n + 1)]
        if hb.arc >= 359:
            pygame.draw.circle(tgt, c, (int(x), int(y)), int(hb.reach), 0 if filled else width)
        else:
            pygame.draw.polygon(tgt, c, pts, 0 if filled else width)
    elif hb.shape == "thrust":
        fx, fy = math.cos(hb.facing), math.sin(hb.facing)
        nx, ny = -fy, fx
        hw = hb.width / 2
        pts = [(x + nx * hw, y + ny * hw), (x + fx * hb.reach + nx * hw, y + fy * hb.reach + ny * hw),
               (x + fx * hb.reach - nx * hw, y + fy * hb.reach - ny * hw), (x - nx * hw, y - ny * hw)]
        pygame.draw.polygon(tgt, c, pts, 0 if filled else width)
    elif hb.shape == "circle":
        pygame.draw.circle(tgt, c, (int(x), int(y)), int(hb.reach), 0 if filled else width)
    elif hb.shape == "ring":
        cur = hb.cur_reach if hb.is_active else hb.reach
        pygame.draw.circle(tgt, c, (int(x), int(y)), int(max(2, cur)), width if not filled else 0 if hb.t < hb.windup else 4)
    if filled:
        surf.blit(layer, (0, 0))


def draw_projectiles(surf: pygame.Surface, room, ox: int, oy: int, t: int) -> None:
    for pr in room.projectiles:
        x, y = ox + pr.x, oy + pr.y
        for i, (tx, ty) in enumerate(pr.trail[:-1]):
            a = (i + 1) / max(1, len(pr.trail))
            pygame.draw.circle(surf, mix(INK, pr.color, a), (int(ox + tx), int(oy + ty)), max(1, int(pr.r * a * 0.6)))
        if pr.kind in ("orb", "note"):
            pygame.draw.circle(surf, INK, (int(x), int(y)), int(pr.r) + 1)
            pygame.draw.circle(surf, pr.color, (int(x), int(y)), int(pr.r))
            pygame.draw.circle(surf, (255, 255, 255), (int(x - 1), int(y - 1)), max(1, int(pr.r) - 3))
        elif pr.kind == "glob":
            pygame.draw.circle(surf, INK, (int(x), int(y)), int(pr.r) + 1)
            pygame.draw.circle(surf, (255, 110, 40), (int(x), int(y)), int(pr.r))
        else:
            ang = math.atan2(pr.vy, pr.vx)
            tip = (x + math.cos(ang) * (pr.r + 3), y + math.sin(ang) * (pr.r + 3))
            tail = (x - math.cos(ang) * (pr.r + 3), y - math.sin(ang) * (pr.r + 3))
            pygame.draw.line(surf, INK, tail, tip, 4)
            pygame.draw.line(surf, pr.color, tail, tip, 2)
            surf.set_at((int(tip[0]), int(tip[1])), (255, 255, 255))


def draw_hazards(surf: pygame.Surface, room, ox: int, oy: int, t: int) -> None:
    for h in room.hazards:
        x, y = ox + h.x, oy + h.y
        if h.kind == "ash":
            a = pygame.Surface((int(h.r * 2), int(h.r * 2)), pygame.SRCALPHA)
            for i in range(7):
                ang = t * 0.02 + i * 0.9
                pygame.draw.circle(a, (190, 184, 200, 50), (int(h.r + math.cos(ang) * h.r * 0.5), int(h.r + math.sin(ang) * h.r * 0.5)), int(h.r * 0.45))
            surf.blit(a, (x - h.r, y - h.r))
        elif h.kind == "vent":
            if h.warning:
                k = ((h.t + h.phase) % h.period) / h.period
                pygame.draw.circle(surf, (255, 90, 50), (int(x), int(y)), int(h.r), 1)
                pygame.draw.circle(surf, (255, 190, 90), (int(x), int(y)), int(h.r * (0.3 + 0.7 * (t % 12) / 12)), 1)
            elif h.armed:
                pygame.draw.circle(surf, (255, 140, 60), (int(x), int(y)), int(h.r))
                pygame.draw.circle(surf, (255, 240, 180), (int(x), int(y)), int(h.r * 0.5))
            else:
                pygame.draw.circle(surf, (36, 20, 28), (int(x), int(y)), int(h.r * 0.5))
                pygame.draw.circle(surf, (90, 50, 50), (int(x), int(y)), int(h.r * 0.5), 1)
        else:
            if h.warning:
                pygame.draw.circle(surf, (255, 90, 50), (int(x), int(y)), int(h.r), 1)
            else:
                pygame.draw.circle(surf, (255, 110, 40), (int(x), int(y)), int(h.r * (0.8 + 0.1 * math.sin(t * 0.3 + h.x))))
                pygame.draw.circle(surf, (255, 220, 130), (int(x), int(y)), int(h.r * 0.45))


def draw_pickups(surf: pygame.Surface, room, ox: int, oy: int, t: int) -> None:
    for k in room.pickups:
        x, y = ox + k.x, oy + k.y - 2 + math.sin(t * 0.15 + k.age) * 1
        if k.kind == "slag":
            pygame.draw.circle(surf, INK, (int(x), int(y)), 3)
            pygame.draw.circle(surf, (255, 180, 70), (int(x), int(y)), 2)
        elif k.kind == "heart":
            pol(surf, (230, 70, 80), [(x - 4, y - 1), (x, y + 4), (x + 4, y - 1), (x + 2, y - 4), (x, y - 2), (x - 2, y - 4)])
        else:
            pygame.draw.circle(surf, (190, 200, 255), (int(x), int(y)), 2)
