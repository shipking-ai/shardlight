"""A quiet cartographic pause between Grand Tour legs.

The route is a fixed eight-stop pilgrimage, drawn as a winding lantern trail.
Completed places keep a warm glow, the next stop breathes with light, and later
stops remain unlit. The scene owns no tour state; it only presents the route and
signals when its caller should resume the next leg.
"""
from __future__ import annotations

import math

import pygame

from ...core.scene import Scene

W, H = 480, 270
INK = (14, 12, 30)
PAPER = (238, 232, 210)
GOLD = (232, 198, 120)
DIM = (150, 146, 176)
LAMP = (255, 226, 168)
LEG_TITLES: dict[str, str] = {
    "spire": "The Spire",
    "wisp": "The Wisp Clearing",
    "crossing": "The Gloaming Ward",
    "lap": "The Salt Cup",
    "duel": "The Ring of Masks",
    "bloom": "The Blossoming Terrace",
    "market": "The Ledger Hall",
    "swarm": "The Orrery Dark",
}
LEG_SHARDS: dict[str, str] = {
    "spire": "cinder", "wisp": "verdant", "crossing": "umbra",
    "lap": "slipstream", "duel": "masks", "bloom": "terrace",
    "market": "concord", "swarm": "orrery",
}
_POINTS = ((42, 196), (96, 151), (151, 181), (210, 123),
           (270, 151), (326, 98), (386, 128), (443, 70))


class RouteScene(Scene):
    """The journey screen shown between legs."""

    def __init__(self, app, legs_spec: list, done_legs: list, next_index: int,
                 next_title: str = "", next_shard: str = ""):
        super().__init__(app)
        self.legs_spec = legs_spec
        self.done_legs = set(done_legs)
        self.next_index = max(0, min(int(next_index), len(_POINTS) - 1))
        spec = legs_spec[self.next_index] if self.next_index < len(legs_spec) else {}
        leg_id = spec.get("id", "") if isinstance(spec, dict) else ""
        self.next_title = next_title or LEG_TITLES.get(leg_id, leg_id.title())
        self.next_shard = next_shard or LEG_SHARDS.get(leg_id, "")
        self.leg_ids = [leg.get("id", "") for leg in legs_spec if isinstance(leg, dict)]
        self.t = 0.0
        self.continue_requested = False

    def on_enter(self, **kwargs) -> None:
        self.t = 0.0

    def on_exit(self) -> None:
        pass

    def update(self, dt: float) -> None:
        if self.continue_requested:
            return
        self.t += max(0.0, dt)
        p = self.inp.player(0)
        if "B" in p.pressed or "BACK" in p.pressed:
            self.app.return_to_hub()
        elif "CONFIRM" in p.pressed or "A" in p.pressed:
            self.continue_requested = True
        elif self.t >= 3.5:
            self.continue_requested = True

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(INK)
        for i in range(34):
            x, y = (i * 139 + 23) % W, (i * 71 + 17) % 224
            pygame.draw.circle(surf, (35, 33, 52), (x, y), 1)
        self._terrain(surf)
        self._trail(surf)
        self._stops(surf)
        f = self.app.font
        f.draw(surf, "THE GRAND TOUR", (12, 9), GOLD, (0, 0, 0))
        f.draw(surf, f"WAYFARER'S MAP   {self.next_index + 1:02d} / 08", (12, 22), DIM, (0, 0, 0))
        title_w = f.width(self.next_title)
        f.draw(surf, self.next_title, ((W - title_w) // 2, 223), PAPER, (0, 0, 0))
        f.draw(surf, f"SHARD: {self.next_shard.upper()}   CONFIRM TO TRAVEL", (12, 249), DIM, (0, 0, 0))
        f.draw(surf, "BACK: LEAVE TOUR", (355, 249), DIM, (0, 0, 0))

    def _terrain(self, surf: pygame.Surface) -> None:
        pygame.draw.polygon(surf, (20, 24, 39), ((0, 113), (46, 82), (88, 120), (130, 91),
                                                   (178, 130), (222, 87), (266, 122),
                                                   (313, 74), (359, 112), (413, 65),
                                                   (480, 105), (480, 212), (0, 212)))
        pygame.draw.lines(surf, (31, 34, 52), False,
                          ((0, 126), (46, 96), (88, 134), (130, 105), (178, 144),
                           (222, 101), (266, 136), (313, 88), (359, 126), (413, 79), (480, 119)), 1)
        pygame.draw.rect(surf, (23, 26, 43), (0, 211, W, 8))
        for x in (23, 181, 301, 462):
            pygame.draw.circle(surf, (49, 45, 61), (x, 205), 2)

    def _trail(self, surf: pygame.Surface) -> None:
        pts = _POINTS[:len(self.leg_ids)]
        if len(pts) > 1:
            pygame.draw.lines(surf, (8, 9, 20), False, pts, 12)
            pygame.draw.lines(surf, (73, 67, 77), False, pts, 7)
            for i in range(len(pts) - 1):
                if self.leg_ids[i] in self.done_legs:
                    pygame.draw.line(surf, (183, 142, 83), pts[i], pts[i + 1], 2)
        for i, (x, y) in enumerate(pts):
            if i < len(pts) - 1:
                mx, my = (x + pts[i + 1][0]) // 2, (y + pts[i + 1][1]) // 2
                pygame.draw.circle(surf, (134, 112, 82), (mx, my), 1)

    def _stops(self, surf: pygame.Surface) -> None:
        f = self.app.font
        for i, (x, y) in enumerate(_POINTS):
            if i >= len(self.leg_ids):
                break
            leg_id = self.leg_ids[i]
            done = leg_id in self.done_legs
            active = i == self.next_index
            if done or active:
                glow = 0.72 + 0.28 * math.sin(self.t * 4.0) if active else 1.0
                color = tuple(int(v * glow) for v in LAMP)
                for radius in (11, 8):
                    pygame.draw.circle(surf, (57, 48, 36), (x, y), radius, 1)
                pygame.draw.circle(surf, color, (x, y), 5 if active else 4)
                pygame.draw.circle(surf, (255, 249, 219), (x - 1, y - 1), 2)
            else:
                pygame.draw.circle(surf, (31, 30, 43), (x, y), 5)
                pygame.draw.circle(surf, (74, 68, 77), (x, y), 5, 1)
            number = f"{i + 1}"
            f.draw(surf, number, (x - 2, y + 10), (GOLD if done or active else DIM), (0, 0, 0))


def draw_title_card(surf: pygame.Surface, font, title: str, subtitle: str,
                    t: float, accent=(232, 198, 120)) -> None:
    """Slide a leg title into view, hold it briefly, then fade it away."""
    if t < 0.0 or t >= 3.0:
        return
    fade_in = min(1.0, t / 0.6)
    fade_out = min(1.0, max(0.0, (3.0 - t) / 0.6))
    alpha = int(255 * min(fade_in, fade_out))
    slide = int((1.0 - fade_in) * 12)
    card = pygame.Surface((368, 56), pygame.SRCALPHA)
    pygame.draw.rect(card, (14, 12, 30, int(alpha * 0.88)), (0, 0, 368, 56))
    pygame.draw.line(card, (*accent, alpha), (0, 0), (367, 0), 2)
    title_img = font.render(title.upper(), accent, (0, 0, 0)).copy()
    title_img.set_alpha(alpha)
    subtitle_img = font.render(subtitle, PAPER, (0, 0, 0)).copy()
    subtitle_img.set_alpha(alpha)
    card.blit(title_img, ((368 - title_img.get_width()) // 2, 11 + slide))
    card.blit(subtitle_img, ((368 - subtitle_img.get_width()) // 2, 34 + slide))
    card.set_alpha(alpha)
    surf.blit(card, ((W - 368) // 2, 38))
