"""Small, layered stage paintings for the Grand Tour.

Each scene borrows its shard's established colours and a few recognizable
shapes. Geometry and motes are seeded once, so animation moves the same world
every frame; translucent light and a restrained vignette bind the layers.
"""
from __future__ import annotations

import math
import random

import pygame

W, H = 480, 270
SHARDS = ("cinder", "verdant", "umbra", "slipstream", "masks", "terrace", "concord", "orrery", "prism")
PALETTES: dict[str, dict] = {
    "cinder": {"sky": (23, 20, 28), "far": (49, 29, 31), "mid": (83, 42, 32), "ground": (48, 31, 32), "accent": (255, 122, 60), "light": (255, 188, 102)},
    "verdant": {"sky": (18, 30, 20), "far": (42, 67, 48), "mid": (65, 94, 58), "ground": (38, 58, 37), "accent": (106, 163, 74), "light": (211, 224, 157)},
    "umbra": {"sky": (7, 9, 14), "far": (17, 27, 34), "mid": (24, 43, 47), "ground": (13, 22, 27), "accent": (70, 132, 132), "light": (148, 204, 194)},
    "slipstream": {"sky": (20, 21, 42), "far": (55, 49, 67), "mid": (112, 83, 82), "ground": (193, 189, 177), "accent": (239, 75, 51), "light": (255, 220, 181)},
    "masks": {"sky": (24, 15, 27), "far": (57, 25, 34), "mid": (103, 37, 42), "ground": (55, 27, 35), "accent": (214, 58, 44), "light": (255, 178, 107)},
    "terrace": {"sky": (34, 31, 30), "far": (75, 67, 49), "mid": (89, 103, 57), "ground": (83, 57, 39), "accent": (111, 168, 74), "light": (255, 196, 116)},
    "concord": {"sky": (23, 24, 34), "far": (55, 50, 61), "mid": (99, 82, 66), "ground": (83, 73, 67), "accent": (212, 171, 92), "light": (255, 225, 155)},
    "orrery": {"sky": (8, 10, 22), "far": (17, 24, 46), "mid": (28, 38, 70), "ground": (11, 13, 26), "accent": (96, 196, 232), "light": (206, 240, 255)},
    "prism": {"sky": (12, 17, 36), "far": (31, 39, 72), "mid": (50, 54, 93), "ground": (29, 34, 56), "accent": (141, 133, 255), "light": (184, 224, 255)},
}


class ShardWorld:
    def __init__(self, shard: str, seed: int):
        self.shard = shard if shard in PALETTES else "prism"
        self.p = PALETTES[self.shard]
        rng = random.Random(seed)
        self.stars = [(rng.randrange(W), rng.randrange(12, 190), rng.randrange(1, 3), rng.random() * 6.28) for _ in range(46)]
        self.motes = [(rng.randrange(W), rng.randrange(H), rng.uniform(.4, 1.6), rng.random() * 6.28) for _ in range(38)]
        self.hills = [(x, rng.randrange(112, 177), rng.randrange(24, 75)) for x in range(-30, W + 50, 50)]
        self.light_cache: dict[int, pygame.Surface] = {}
        self.grade_layer = pygame.Surface((W, H), pygame.SRCALPHA)
        self.grade_layer.fill((4, 5, 13, 22))
        vignette = pygame.Surface((120, 68), pygame.SRCALPHA)
        for vx in range(120):
            for vy in range(68):
                dx = (vx - 59.5) / 59.5
                dy = (vy - 33.5) / 33.5
                alpha = int(min(38, max(0, (dx * dx + dy * dy - .42) * 25)))
                vignette.set_at((vx, vy), (0, 0, 0, alpha))
        self.grade_layer.blit(pygame.transform.smoothscale(vignette, (W, H)), (0, 0))

    def backdrop(self, surf: pygame.Surface, t: float) -> None:
        surf.fill(self.p["sky"])
        for x, y, r, phase in self.stars:
            if (math.sin(t * .8 + phase) + 1) > .35:
                pygame.draw.circle(surf, self.p["light"], (x, y), r)
        if self.shard in ("cinder", "masks", "terrace"):
            pygame.draw.circle(surf, (*self.p["accent"], 25), (390, 52), 38)
            pygame.draw.circle(surf, self.p["far"], (390, 52), 22)
        elif self.shard == "prism":
            pygame.draw.polygon(surf, (72, 78, 130), [(370, 12), (427, 54), (386, 103), (350, 65)])
            pygame.draw.polygon(surf, (32, 52, 96), [(370, 12), (386, 103), (350, 65)])
        elif self.shard == "orrery":
            # a planet limb underfoot and a hard little sun far away
            pygame.draw.circle(surf, self.p["mid"], (250, 420), 210)
            pygame.draw.circle(surf, self.p["far"], (250, 430), 196)
            pygame.draw.circle(surf, (232, 238, 255), (78, 44), 9)
            for k in range(3):
                pygame.draw.circle(surf, self.p["far"], (78, 44), 14 + k * 5, 1)
            pygame.draw.polygon(surf, (32, 52, 96), [(370, 12), (386, 103), (350, 65)])
        if self.shard == "slipstream":
            for i in range(9):
                x = (i * 71 - int(t * 165)) % 560 - 40
                pygame.draw.line(surf, (108, 82, 94), (x, 45 + i * 13), (x + 38, 45 + i * 13), 1)

    def midground(self, surf: pygame.Surface, t: float) -> None:
        for i, (x, y, width) in enumerate(self.hills):
            pygame.draw.ellipse(surf, self.p["far"], (x, y, width + 45, 125))
        col = self.p["mid"]
        if self.shard == "cinder":
            for x, y, w in ((35, 42, 55), (135, 63, 42), (306, 32, 62), (424, 62, 38)):
                pygame.draw.polygon(surf, col, [(x, 177), (x+5, y+22), (x+15, y+22), (x+18, y), (x+w-17, y), (x+w-12, y+17), (x+w-5, y+17), (x+w, 177)])
                pygame.draw.rect(surf, self.p["sky"], (x+w//2-4, y+35, 8, 14))
        elif self.shard == "verdant":
            for x, y, _ in self.hills[::2]:
                pygame.draw.line(surf, col, (x+22, y+85), (x+22, y+28), 5)
                pygame.draw.circle(surf, col, (x+12, y+35), 14)
                pygame.draw.circle(surf, col, (x+31, y+30), 16)
        elif self.shard == "umbra":
            for x in (25, 145, 330, 445):
                pygame.draw.rect(surf, col, (x, 18, 15, 194))
                pygame.draw.polygon(surf, col, [(x-20, 24), (x+7, 3), (x+35, 24)])
            pygame.draw.rect(surf, (12, 20, 25), (40, 55, 92, 119))
            pygame.draw.rect(surf, (12, 20, 25), (348, 55, 84, 119))
        elif self.shard == "masks":
            for x in (80, 400):
                pygame.draw.line(surf, (144, 65, 56), (x, 0), (x, 82), 2)
                pygame.draw.circle(surf, self.p["light"], (x, 88), 7)
            pygame.draw.line(surf, (125, 40, 43), (0, 69), (480, 69), 2)
        elif self.shard == "concord":
            for x in (48, 145, 322, 420):
                pygame.draw.rect(surf, (133, 119, 98), (x, 35, 12, 150))
                pygame.draw.rect(surf, (170, 149, 112), (x-5, 32, 22, 9))
            for x in (112, 368):
                pygame.draw.polygon(surf, (132, 47, 55), [(x, 28), (x+42, 37), (x+35, 98), (x+4, 86)])
        elif self.shard == "prism":
            for x, y in ((55, 74), (150, 38), (325, 62), (414, 89)):
                pygame.draw.polygon(surf, col, [(x, y+50), (x+13, y), (x+29, y+50), (x+20, y+58)])
                pygame.draw.line(surf, (126, 124, 206), (x+13, y+8), (x+18, y+51), 1)
        elif self.shard == "terrace":
            for x, y, _ in self.hills[::2]:
                pygame.draw.rect(surf, (103, 76, 48), (x+8, y+48, 34, 48))
                pygame.draw.polygon(surf, (132, 95, 59), [(x, y+48), (x+25, y+32), (x+50, y+48)])
        elif self.shard == "orrery":
            # the orrery itself: rings around a cold star
            for rx, ry in ((150, 44), (108, 30), (196, 58)):
                pygame.draw.ellipse(surf, self.p["mid"], (250 - rx, 74 - ry, rx * 2, ry * 2), 1)
            pygame.draw.circle(surf, (226, 240, 255), (250, 74), 5)

    def ground(self, surf: pygame.Surface, t: float) -> None:
        pygame.draw.rect(surf, self.p["ground"], (0, 184, W, 86))
        if self.shard == "terrace":
            for i in range(7):
                y = 194 + i * 12
                pygame.draw.line(surf, (116, 83, 51), (0, y), (480, y-16), 2)
                pygame.draw.line(surf, (52, 48, 35), (0, y+3), (480, y-13), 1)
        elif self.shard == "slipstream":
            for i in range(7):
                y = 195 + i * 12
                pygame.draw.line(surf, (225, 215, 196), (0, y), (480, y+5), 1)
        elif self.shard == "orrery":
            # a dark hull deck with a cold rim light
            pygame.draw.rect(surf, self.p["ground"], (0, 184, W, 86))
            pygame.draw.line(surf, self.p["accent"], (0, 186), (480, 186), 1)
            for i in range(24):
                x = (i * 21) % W
                pygame.draw.circle(surf, self.p["far"], (x, 214), 2)
        else:
            for i in range(28):
                x = (i * 67 + int(t * (8 if self.shard == "cinder" else 2))) % W
                y = 190 + (i * 19) % 78
                pygame.draw.line(surf, self.p["mid"], (x, y), (x+8+(i%9), y-1), 1)

    def particles(self, surf: pygame.Surface, t: float) -> None:
        for x, y, speed, phase in self.motes:
            yy = int((y - t * speed * 9) % H)
            xx = int((x + math.sin(t + phase) * 7 + t * speed * (9 if self.shard == "slipstream" else 1)) % W)
            pygame.draw.circle(surf, self.p["light"], (xx, yy), 1 if speed < 1 else 2)

    def lamp_light(self, surf: pygame.Surface, x: float, y: float, r: float) -> None:
        radius = max(8, min(128, int(r)))
        glow = self.light_cache.get(radius)
        if glow is None:
            glow = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
            for step in range(7, 0, -1):
                rr = radius * step // 7
                pygame.draw.circle(glow, (255, 191, 104, 5 + (8-step)*3), (radius, radius), rr)
            self.light_cache[radius] = glow
        surf.blit(glow, (int(x-radius), int(y-radius)))

    def traveller(self, surf: pygame.Surface, x: float, y: float, t: float, walking: bool) -> None:
        bob = math.sin(t * 9) * 1.5 if walking else 0
        px, py = int(x), int(y + bob)
        pygame.draw.ellipse(surf, (10, 10, 15), (px-8, py+13, 17, 5))
        pygame.draw.circle(surf, (19, 18, 25), (px, py-8), 5)
        pygame.draw.polygon(surf, (16, 16, 23), [(px-5, py-4), (px+5, py-4), (px+7, py+10), (px-7, py+10)])
        stride = math.sin(t * 10) * 3 if walking else 0
        pygame.draw.line(surf, (13, 13, 19), (px-3, py+8), (int(px-4+stride), py+16), 3)
        pygame.draw.line(surf, (13, 13, 19), (px+3, py+8), (int(px+4-stride), py+16), 3)
        pygame.draw.line(surf, (18, 17, 22), (px+3, py-1), (px+10, py+2), 2)
        pygame.draw.circle(surf, self.p["light"], (px+12, py+4), 3)

    def grade(self, surf: pygame.Surface) -> None:
        surf.blit(self.grade_layer, (0, 0))
