"""The Prism Observatory: walkable hub, shard cards, archive (lore/echo board), forge (lantern hues)."""
from __future__ import annotations

import math
import random

import pygame
from pygame import Vector2

from ..core import art
from ..core.fx import FEEL, Lighting, ParticleSystem, blit_additive_glow, clamp, ease_out_cubic, mix
from ..core.scene import ModeInfo, Scene
from ..core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Dialogue, Menu, MenuItem,
                       MenuScene, SettingsScene, ControlsScene, draw_panel, draw_prompts)

W, H = 480, 270
CENTER = Vector2(240, 158)
RING = (185, 74)
FLOOR_TOP = 70

LANTERN_HUES = {
    "amber": ((255, 196, 96), 0),
    "verdigris": ((110, 235, 190), 12),
    "rose": ((255, 130, 160), 12),
    "violet": ((190, 140, 255), 20),
    "azure": ((120, 200, 255), 20),
    "pearl": ((250, 246, 235), 35),
}


def lantern_color(world) -> tuple[int, int, int]:
    return LANTERN_HUES.get(world.flag("lantern_hue", "amber") if world else "amber", LANTERN_HUES["amber"])[0]


# ------------------------------------------------------------------------------ background
def _bake_background() -> pygame.Surface:
    bg = pygame.Surface((W, H))
    bg.fill((20, 18, 34))
    # --- dome wall with night sky windows
    wall = pygame.Rect(0, 0, W, FLOOR_TOP)
    art.banded_vertical(bg, wall, [(16, 14, 30), (20, 18, 38), (24, 21, 44), (28, 25, 50)])
    sky = art.starfield((W, FLOOR_TOP), 11, 0.012)
    for i in range(7):
        x = 38 + i * 62
        win = pygame.Rect(x - 17, 10, 34, 54)
        pygame.draw.rect(bg, (10, 9, 28), win, border_top_left_radius=17, border_top_right_radius=17)
        bg.blit(sky, win.topleft, area=pygame.Rect(win.x, win.y, win.w, win.h))
        # clip the stars to the arch by overdrawing the corners with wall colour
        for yy in range(0, 17):
            inset = 17 - int(math.sqrt(max(0, 17 * 17 - (17 - yy) ** 2)))
            pygame.draw.line(bg, (20, 18, 38), (win.x, win.y + yy), (win.x + inset - 1, win.y + yy))
            pygame.draw.line(bg, (20, 18, 38), (win.right - inset, win.y + yy), (win.right, win.y + yy))
        pygame.draw.rect(bg, BRASS, win, 1, border_top_left_radius=17, border_top_right_radius=17)
        pygame.draw.line(bg, mix(BRASS, (0, 0, 0), 0.5), (win.centerx, win.y + 8), (win.centerx, win.bottom), 1)
    # pilasters between windows
    for i in range(8):
        x = 7 + i * 62
        pygame.draw.rect(bg, (34, 30, 56), (x - 3, 4, 7, FLOOR_TOP - 4))
        pygame.draw.line(bg, (60, 52, 84), (x - 3, 4), (x - 3, FLOOR_TOP))
        pygame.draw.line(bg, (14, 12, 26), (x + 3, 4), (x + 3, FLOOR_TOP))
    pygame.draw.rect(bg, (12, 10, 24), (0, FLOOR_TOP - 4, W, 5))
    pygame.draw.line(bg, BRASS, (0, FLOOR_TOP - 5), (W, FLOOR_TOP - 5))
    # --- floor tiles: elliptical perspective rings of stone
    floor = pygame.Rect(0, FLOOR_TOP, W, H - FLOOR_TOP)
    art.dither_vertical(bg, floor, (24, 22, 42), (34, 30, 58))
    rng = random.Random(5)
    for y in range(floor.y, H, 9):
        for x in range((y // 9) % 2 * 9, W, 18):
            if rng.random() < 0.5:
                bg.fill((38, 34, 62) if rng.random() < 0.5 else (30, 27, 52), (x, y, 17, 8))
    for ry in range(floor.y, H, 9):
        pygame.draw.line(bg, (20, 18, 34), (0, ry), (W, ry))
    # inlay rings and spokes
    for scale, col in ((1.0, mix(BRASS, (24, 22, 42), 0.35)), (0.96, mix(BRASS, (24, 22, 42), 0.6)),
                       (0.45, mix(BRASS, (24, 22, 42), 0.45))):
        r = pygame.Rect(0, 0, RING[0] * 2 * scale, RING[1] * 2 * scale)
        r.center = (int(CENTER.x), int(CENTER.y))
        pygame.draw.ellipse(bg, col, r, 1)
    for i in range(8):
        a = math.radians(-90 + 22.5 + i * 45)
        p = CENTER + Vector2(math.cos(a) * RING[0], math.sin(a) * RING[1])
        pygame.draw.line(bg, mix(BRASS, (24, 22, 42), 0.7), CENTER, p, 1)
    # lens dais
    d = pygame.Rect(0, 0, 76, 30)
    d.center = (int(CENTER.x), int(CENTER.y) + 8)
    pygame.draw.ellipse(bg, (14, 12, 26), d.inflate(6, 4))
    pygame.draw.ellipse(bg, (46, 40, 74), d)
    pygame.draw.ellipse(bg, BRASS, d, 1)
    # vignette at edges of the floor
    vg = pygame.Surface((W, H), pygame.SRCALPHA)
    for i in range(14):
        a = int(130 * (1 - i / 14) ** 2)
        pygame.draw.rect(vg, (6, 4, 14, a), (i, i, W - i * 2, H - i * 2), 1)
    bg.blit(vg, (0, 0))
    return bg


def _bake_player() -> dict[str, list[pygame.Surface]]:
    """Tiny cloaked lamplighter: 4 facings x 4 walk frames, 12x18."""
    frames: dict[str, list[pygame.Surface]] = {}
    cloak, cloak_l, cloak_d = (74, 84, 168), (108, 120, 210), (44, 48, 112)
    skin, hair = (240, 206, 170), (60, 40, 50)
    for facing in ("down", "up", "side"):
        lst = []
        for f in range(4):
            def drw(s, f=f, facing=facing):
                bob = 1 if f in (1, 3) else 0
                step = (0, 2, 0, -2)[f]
                # legs
                pygame.draw.rect(s, (30, 26, 52), (4 + (step if facing != "side" else 0) // 2, 13 + bob - 1, 2, 3))
                pygame.draw.rect(s, (30, 26, 52), (7 - (step if facing != "side" else 0) // 2, 13 + bob - 1, 2, 3))
                if facing == "side":
                    pygame.draw.rect(s, (30, 26, 52), (6 + step // 2, 13, 2, 3))
                # cloak
                pygame.draw.polygon(s, cloak, [(2, 12 + bob), (3, 6 + bob), (9, 6 + bob), (10, 12 + bob)])
                pygame.draw.line(s, cloak_l, (3, 7 + bob), (3, 11 + bob))
                pygame.draw.line(s, cloak_d, (9, 7 + bob), (9, 11 + bob))
                # head + hood
                pygame.draw.rect(s, cloak, (3, 1 + bob, 6, 6))
                pygame.draw.rect(s, cloak_l, (3, 1 + bob, 6, 1))
                if facing == "down":
                    pygame.draw.rect(s, skin, (4, 3 + bob, 4, 3))
                    s.set_at((5, 4 + bob), (30, 20, 40))
                    s.set_at((7, 4 + bob), (30, 20, 40))
                elif facing == "side":
                    pygame.draw.rect(s, skin, (6, 3 + bob, 3, 3))
                    s.set_at((8, 4 + bob), (30, 20, 40))
                else:
                    pygame.draw.rect(s, hair, (4, 3 + bob, 4, 3))
            surf = art.bake(drw, (12, 18))
            lst.append(surf)
        frames[facing] = lst
    return frames


# ------------------------------------------------------------------------------ interactables
class Station:
    def __init__(self, kind: str, key: str, pos: Vector2, label: str, color, info: ModeInfo | None = None):
        self.kind = kind          # "mode" | "archive" | "forge" | "menu"
        self.key = key
        self.pos = pos
        self.label = label
        self.color = color
        self.info = info


class HubScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = _bake_background()
        self.sprites = _bake_player()
        self.pos = Vector2(240, 232)
        self.facing = "down"
        self.anim = 0.0
        self.t = 0.0
        self.lighting = Lighting((W, H), ambient=(118, 110, 158))
        self.particles = ParticleSystem(400, random.Random(9))
        self.stations: list[Station] = []
        self.near: Station | None = None
        self.motes = [(random.random() * W, FLOOR_TOP + random.random() * (H - FLOOR_TOP), random.random() * 6.28)
                      for _ in range(36)]
        self._build_stations()

    # ---------------------------------------------------------------- setup
    def _build_stations(self) -> None:
        from .. import modes as modes_pkg
        infos = {i.id: i for i in self.app.available_modes}
        for idx, mid in enumerate(modes_pkg.MODE_IDS):
            a = math.radians(-90 + 22.5 + idx * 45)
            p = CENTER + Vector2(math.cos(a) * RING[0], math.sin(a) * RING[1])
            info = infos.get(mid)
            self.stations.append(Station("mode", mid, p, info.title if info else mid.title(),
                                         info.color if info else (90, 88, 104), info))
        self.stations.append(Station("archive", "archive", Vector2(62, FLOOR_TOP + 12), "Archive", LENS))
        self.stations.append(Station("forge", "forge", Vector2(418, FLOOR_TOP + 12), "Prism Forge", BRASS))
        self.stations.append(Station("menu", "menu", Vector2(240, FLOOR_TOP + 10), "Control Desk", PARCHMENT))

    def on_enter(self, **kw) -> None:
        self.app.audio.play_music("hub", 1.5, 0.2)
        self.app.save_now()
        w = self.app.world
        if len(w.profile["facets"]) >= 8 and not w.flag("lens_restored"):
            w.set_flag("lens_restored")
            self.app.scenes.push(Dialogue(self.app, [
                ("", "Eight edges, eight lights. The Lens turns in its cradle and the Observatory fills with a single, steady colour."),
                ("Lampwright", "It was never meant to be one world. It was meant to be one lamp, and we are the hands that carry it."),
                ("", "Play on: every shard remains open, and the Lens keeps listening for new echoes."),
            ], color=LENS))

    # ---------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        self.t += dt
        p = self.inp.player(0)
        move = p.move
        speed = 74
        if move.length_squared() > 0:
            self.pos += move * speed * dt
            self.anim += dt * 9 * min(1.0, move.length())
            if abs(move.x) > abs(move.y):
                self.facing = "side_r" if move.x > 0 else "side_l"
            else:
                self.facing = "down" if move.y > 0 else "up"
        else:
            self.anim = 0
        self.pos.x = clamp(self.pos.x, 18, W - 18)
        self.pos.y = clamp(self.pos.y, FLOOR_TOP + 20, H - 14)
        # keep out of the lens dais
        off = self.pos - (CENTER + Vector2(0, 8))
        e = (off.x / 40) ** 2 + (off.y / 17) ** 2
        if e < 1 and e > 0:
            self.pos = CENTER + Vector2(0, 8) + Vector2(off.x / math.sqrt(e), off.y / math.sqrt(e))
        # nearest interactable
        self.near = None
        best = 30.0
        for s in self.stations:
            d = (s.pos - self.pos).length()
            if d < best:
                best, self.near = d, s
        if self.near and p.any_pressed(("CONFIRM", "A")):
            self._interact(self.near)
        elif "PAUSE" in p.pressed:
            self._interact(next(s for s in self.stations if s.kind == "menu"))
        self.particles.update(dt)
        if random.random() < 0.15:
            self.particles.emit(CENTER + Vector2(random.uniform(-8, 8), -10), 1, (4, 14), (250, 290), (1.0, 2.0),
                                (1, 2), lantern_color(self.app.world), (255, 255, 255), glow=0)

    def _interact(self, s: Station) -> None:
        self.app.audio.play("ui_confirm", 0.8)
        if s.kind == "mode":
            self.app.scenes.push(ShardCard(self.app, s.key, s.info))
        elif s.kind == "archive":
            self.app.scenes.push(ArchiveScene(self.app))
        elif s.kind == "forge":
            self.app.scenes.push(ForgeScene(self.app))
        else:
            self.app.scenes.push(DeskMenu(self.app))

    # ---------------------------------------------------------------- draw
    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self.bg, (0, 0))
        w = self.app.world
        facets = set(w.profile["facets"])
        f = self.app.font
        self.lighting.clear()
        # central lens
        restored = len(facets)
        lens_c = (int(CENTER.x), int(CENTER.y) - 16)
        bob = math.sin(self.t * 1.3) * 2
        intensity = restored / 8
        art.draw_prism(surf, (lens_c[0], lens_c[1] + bob), 17, mix((120, 120, 150), (255, 250, 235), intensity),
                       self.t, True, True, 0.45 + 0.55 * intensity)
        self.lighting.add(lens_c, 90 + int(60 * intensity), mix((120, 130, 200), (255, 240, 200), intensity), 0.55 + intensity * 0.6)
        from .. import modes as modes_pkg
        for i, mid in enumerate(modes_pkg.MODE_IDS):
            a = self.t * 0.5 + i * math.tau / 8
            op = (lens_c[0] + math.cos(a) * 34, lens_c[1] + 6 + math.sin(a) * 12 + bob)
            st = next(s for s in self.stations if s.key == mid)
            lit = mid in facets
            if math.sin(a) < 0:
                art.draw_prism(surf, op, 4, st.color, self.t + i, lit, False, 1.0 if lit else 0.25)
        # stations
        draw_list = sorted(self.stations, key=lambda s: s.pos.y)
        drawn_player = False
        for s in draw_list:
            if not drawn_player and s.pos.y > self.pos.y:
                self._draw_player(surf)
                drawn_player = True
            self._draw_station(surf, s, facets)
        if not drawn_player:
            self._draw_player(surf)
        # orbit shards in front of lens
        for i, mid in enumerate(modes_pkg.MODE_IDS):
            a = self.t * 0.5 + i * math.tau / 8
            if math.sin(a) >= 0:
                op = (lens_c[0] + math.cos(a) * 34, lens_c[1] + 6 + math.sin(a) * 12 + bob)
                st = next(s for s in self.stations if s.key == mid)
                lit = mid in facets
                art.draw_prism(surf, op, 4, st.color, self.t + i, lit, False, 1.0 if lit else 0.25)
        # motes
        for (mx, my, ph) in self.motes:
            x = (mx + math.sin(self.t * 0.4 + ph) * 12) % W
            y = FLOOR_TOP + ((my - FLOOR_TOP) + math.cos(self.t * 0.3 + ph) * 8) % (H - FLOOR_TOP)
            surf.fill((200, 200, 230) if int(self.t * 2 + ph) % 3 else (255, 255, 255), (int(x), int(y), 1, 1))
        self.particles.draw(surf)
        self.lighting.add(self.pos - Vector2(0, 8), 64, lantern_color(w), 0.9)
        self.lighting.apply(surf)
        self._draw_hud(surf)

    def _draw_station(self, surf: pygame.Surface, s: Station, facets: set) -> None:
        f = self.app.font
        x, y = int(s.pos.x), int(s.pos.y)
        dormant = s.kind == "mode" and s.info is None
        base = pygame.Rect(x - 14, y + 2, 28, 10)
        pygame.draw.ellipse(surf, (10, 8, 22), base.inflate(4, 3))
        pygame.draw.ellipse(surf, (52, 46, 80), base)
        pygame.draw.ellipse(surf, s.color if not dormant else (70, 68, 84), base, 1)
        near = s is self.near
        if s.kind == "mode":
            lit = s.key in facets
            bob = math.sin(self.t * 1.6 + hash(s.key) % 7) * 2
            dim = 0.28 if dormant else 1.0
            art.draw_prism(surf, (x, y - 14 + bob), 10 + (2 if near else 0), s.color, self.t + (hash(s.key) % 5),
                           not dormant, True, dim)
            if lit:
                pygame.draw.circle(surf, (255, 244, 210), (x, y + 6), 2)
            if not dormant:
                self.lighting.add((x, y - 12), 58 + (20 if near else 0), s.color, 0.8 if near else 0.5)
        elif s.kind == "archive":
            pygame.draw.rect(surf, (60, 52, 90), (x - 9, y - 18, 18, 18))
            pygame.draw.rect(surf, LENS, (x - 7, y - 16, 14, 9), 1)
            pygame.draw.rect(surf, (20, 40, 60), (x - 6, y - 15, 12, 7))
            for i in range(3):
                pygame.draw.line(surf, LENS, (x - 4, y - 14 + i * 2), (x + 3 - i, y - 14 + i * 2))
            self.lighting.add((x, y - 10), 44, LENS, 0.45)
        elif s.kind == "forge":
            pygame.draw.rect(surf, (70, 56, 50), (x - 10, y - 14, 20, 14))
            pygame.draw.rect(surf, (28, 20, 22), (x - 7, y - 11, 14, 8))
            fl = 2 + int(math.sin(self.t * 9) > 0)
            pygame.draw.polygon(surf, (255, 190, 80), [(x - 4, y - 4), (x, y - 4 - fl * 2), (x + 4, y - 4)])
            self.lighting.add((x, y - 8), 56, (255, 170, 80), 0.7)
        else:
            pygame.draw.rect(surf, (62, 56, 92), (x - 12, y - 16, 24, 16))
            pygame.draw.rect(surf, PARCHMENT, (x - 10, y - 14, 20, 8), 1)
            f.draw(surf, "ESC", (x, y - 13), PARCHMENT, None, anchor="midtop", scale=1)
        if near:
            f.draw(surf, s.label, (x, y - 40 if s.kind == "mode" else y - 30), (255, 244, 205), (10, 8, 20), anchor="midbottom")
            if dormant:
                f.draw(surf, "dormant", (x, y - 30 if s.kind == "mode" else y - 20), DIM, (10, 8, 20), anchor="midbottom")

    def _draw_player(self, surf: pygame.Surface) -> None:
        facing = self.facing
        flip = False
        key = facing
        if facing.startswith("side"):
            key = "side"
            flip = facing == "side_l"
        frame = self.sprites[key][int(self.anim) % 4]
        if flip:
            frame = pygame.transform.flip(frame, True, False)
        art.draw_shadow(surf, (self.pos.x, self.pos.y + 1), 12)
        surf.blit(frame, (self.pos.x - frame.get_width() // 2, self.pos.y - frame.get_height() + 2))
        lc = lantern_color(self.app.world)
        lx = self.pos.x + (5 if facing in ("side_r", "down") else -5)
        ly = self.pos.y - 7 + math.sin(self.t * 5) * 0.8
        blit_additive_glow(surf, (lx, ly), 9, tuple(c // 2 for c in lc), 2)
        surf.fill(lc, (int(lx) - 1, int(ly) - 1, 3, 3))

    def _draw_hud(self, surf: pygame.Surface) -> None:
        f = self.app.font
        w = self.app.world
        draw_panel(surf, pygame.Rect(6, 6, 120, 28), fill=INK, alpha=200)
        f.draw(surf, w.profile["name"], (14, 11), PARCHMENT, None)
        f.draw(surf, f"Glint {w.profile['currency'].get('glint', 0)}", (14, 22), BRASS, None)
        n = len(w.profile["facets"])
        f.draw(surf, f"Lens {n}/8", (W - 8, 8), LENS if n < 8 else (255, 244, 205), (10, 8, 20), anchor="topright")
        if self.near:
            verb = "Enter shard" if self.near.kind == "mode" and self.near.info else \
                   "Dormant" if self.near.kind == "mode" else "Use"
            draw_prompts(surf, self.app, [("A", verb), ("PAUSE", "Menu")])
        else:
            draw_prompts(surf, self.app, [("PAUSE", "Menu")])


# ------------------------------------------------------------------------------ shard card
class ShardCard(Scene):
    opaque = False

    def __init__(self, app, mode_id: str, info: ModeInfo | None):
        super().__init__(app)
        self.mode_id = mode_id
        self.info = info
        self.opts: dict = {}
        self.age = 0.0
        items: list[MenuItem] = []
        if info:
            if info.max_players > 1:
                self.opts["players"] = 1
                items.append(MenuItem("Players", kind="choice", choices=list(range(1, info.max_players + 1)),
                                      get=lambda: self.opts["players"], set=lambda v: self.opts.__setitem__("players", v)))
            for o in info.options:
                key = o["key"]
                self.opts[key] = o["default"]
                items.append(MenuItem(o["label"], kind="choice", choices=list(o["choices"]),
                                      get=lambda k=key: self.opts[k], set=lambda v, k=key: self.opts.__setitem__(k, v)))
            items.append(MenuItem("Enter shard", self._launch))
        items.append(MenuItem("Back", app.scenes.pop))
        self.menu = Menu(app, items, 196)

    def _launch(self) -> None:
        n = int(self.opts.get("players", 1))
        self.app.input.assign_local(n)
        self.app.scenes.pop()
        self.app.enter_mode(self.mode_id, **self.opts)

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.1:
            return
        self.menu.update()
        if "BACK" in self.inp.player(0).pressed:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((6, 4, 14, 190))
        surf.blit(dim, (0, 0))
        info = self.info
        col = info.color if info else (110, 108, 124)
        k = ease_out_cubic(self.age / 0.18)
        rect = pygame.Rect(40, 22 + int((1 - k) * 12), W - 80, H - 54)
        draw_panel(surf, rect, border=col, title=(info.title.upper() if info else self.mode_id.upper()), font=f)
        if not info:
            f.draw_wrapped(surf, "This shard is dormant in this build. Its lens has not been repaired yet, so there is "
                           "nothing to enter.", pygame.Rect(rect.x + 14, rect.y + 24, rect.w - 28, 60), PARCHMENT, None)
            self.menu.draw(surf, (rect.x + 14, rect.bottom - 40))
            return
        art.draw_prism(surf, (rect.right - 44, rect.y + 46), 18, col, self.age * 2, True, True)
        f.draw(surf, info.genre, (rect.x + 14, rect.y + 16), col, None)
        f.draw(surf, info.tagline, (rect.x + 14, rect.y + 28), (255, 244, 205), None)
        y = f.draw_wrapped(surf, info.blurb, pygame.Rect(rect.x + 14, rect.y + 44, rect.w - 110, 60), PARCHMENT, None)
        yy = y + 6
        f.draw(surf, "CONTROLS", (rect.x + 14, yy), DIM, None)
        yy += 11
        p = self.inp.player(0)
        for btn, text in info.controls[:7]:
            lab = p.prompt(btn) if btn in ("UP", "A", "B", "X", "Y", "L", "R", "PAUSE", "SELECT") else btn
            f.draw(surf, f"{lab}", (rect.x + 18, yy), BRASS, None)
            f.draw(surf, text, (rect.x + 70, yy), PARCHMENT, None)
            yy += 10
        prog = self.app.world.mode_data(self.mode_id).get("summary")
        if prog:
            f.draw(surf, str(prog), (rect.x + 14, rect.bottom - 62 - 14 * len(self.menu.items) // 2), GOOD, None)
        if self.mode_id in self.app.world.profile["facets"]:
            f.draw(surf, "FACET REPAIRED", (rect.right - 14, rect.bottom - 18), GOOD, None, anchor="bottomright")
        self.menu.draw(surf, (rect.x + 14, rect.bottom - 14 - self.menu.height() - 8))
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Close")])


# ------------------------------------------------------------------------------ archive
class ArchiveScene(Scene):
    """Lore journal + Echo board (cross-shard threads) + mod report."""
    opaque = True
    TABS = ["Lore", "Echoes", "Mods"]

    def __init__(self, app):
        super().__init__(app)
        self.tab = 0
        self.sel = 0
        self.age = 0.0
        self.scroll = 0

    def _lore(self):
        w = self.app.world
        out = []
        for e in sorted(self.app.content.all("lore"), key=lambda e: e["id"]):
            out.append((e, e["id"] in w.profile["lore"]))
        return out

    def _echoes(self):
        w = self.app.world
        out = []
        for e in sorted(self.app.content.all("echo"), key=lambda e: e["id"]):
            if e.get("secret") is True:
                continue
            out.append((e, e["id"] in w.profile["echoes_fired"]))
        return out

    def update(self, dt: float) -> None:
        self.age += dt
        p = self.inp.player(0)
        dx, dy = p.menu_dir()
        if dx:
            self.tab = (self.tab + dx) % 3
            self.sel = 0
        n = {0: len(self._lore()), 1: len(self._echoes()), 2: len(self.app.mods.mods) + len(self.app.mods.report)}[self.tab]
        if dy and n:
            self.sel = (self.sel + dy) % n
        if "BACK" in p.pressed and self.age > 0.1:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        surf.fill(INK)
        art.dither_vertical(surf, pygame.Rect(0, 0, W, 40), (22, 20, 40), INK)
        draw_panel(surf, pygame.Rect(16, 12, W - 32, H - 40), border=LENS, title="ARCHIVE", font=f)
        x = 30
        for i, t in enumerate(self.TABS):
            col = LENS if i == self.tab else DIM
            f.draw(surf, t, (x, 22), col, None)
            if i == self.tab:
                pygame.draw.line(surf, LENS, (x, 32), (x + f.width(t), 32))
            x += f.width(t) + 18
        area = pygame.Rect(28, 40, 190, H - 76)
        detail = pygame.Rect(230, 40, W - 262, H - 76)
        pygame.draw.line(surf, (50, 46, 74), (224, 40), (224, H - 36))
        if self.tab == 0:
            rows = self._lore()
            self._list(surf, area, [(e["title"] if found else "? ? ?", found) for e, found in rows])
            if rows:
                e, found = rows[min(self.sel, len(rows) - 1)]
                if found:
                    f.draw(surf, e["title"], (detail.x, detail.y), (255, 244, 205), None)
                    f.draw_wrapped(surf, e["text"], pygame.Rect(detail.x, detail.y + 14, detail.w, detail.h - 14), PARCHMENT, None)
                else:
                    f.draw_wrapped(surf, "Undiscovered. Something in the shards remembers this.", detail, DIM, None)
            f.draw(surf, f"{sum(1 for _, ok in rows if ok)}/{len(rows)} recorded", (area.x, H - 52), DIM, None)
        elif self.tab == 1:
            rows = self._echoes()
            self._list(surf, area, [((e.get("title") or e["id"]) if found else "Unheard echo", found) for e, found in rows])
            if rows:
                e, found = rows[min(self.sel, len(rows) - 1)]
                if found:
                    f.draw(surf, e.get("title") or e["id"], (detail.x, detail.y), (255, 244, 205), None)
                    f.draw_wrapped(surf, e.get("description", "A consequence rippled between shards."),
                                   pygame.Rect(detail.x, detail.y + 14, detail.w, detail.h - 14), PARCHMENT, None)
                else:
                    f.draw_wrapped(surf, e.get("hint", "Something you do in one shard may matter in another."), detail, DIM, None)
        else:
            mm = self.app.mods
            lines = [(f"{m.name} v{m.version} {'(loaded)' if m.id in mm.loaded else '(skipped)'}", m.id in mm.loaded)
                     for m in mm.mods.values()]
            lines += [(r, False) for r in mm.report]
            if not lines:
                lines = [("No mods installed. Drop a folder with mod.json into /mods.", False)]
            self._list(surf, area, lines[:12])
            probs = self.app.content.problems
            f.draw(surf, f"{len(probs)} content notice(s)", (detail.x, detail.y), DIM, None)
            yy = detail.y + 14
            for pr in probs[:10]:
                for ln in f.wrap(pr, detail.w)[:2]:
                    f.draw(surf, ln, (detail.x, yy), DANGER, None)
                    yy += 10
        draw_prompts(surf, self.app, [("LEFT", "Tab"), ("UP", "Browse"), ("BACK", "Close")])

    def _list(self, surf, area: pygame.Rect, rows: list[tuple[str, bool]]) -> None:
        f = self.app.font
        per = area.h // 11
        start = max(0, min(self.sel - per // 2, len(rows) - per))
        y = area.y
        for i in range(start, min(len(rows), start + per)):
            text, ok = rows[i]
            if i == self.sel:
                pygame.draw.rect(surf, INK_2, (area.x - 2, y - 1, area.w, 11))
                pygame.draw.rect(surf, BRASS, (area.x - 2, y - 1, 2, 11))
            col = (255, 244, 205) if i == self.sel else (PARCHMENT if ok else DIM)
            while f.width(text) > area.w - 6 and len(text) > 4:
                text = text[:-4] + "..."
            f.draw(surf, text, (area.x + 4, y), col, None)
            y += 11


# ------------------------------------------------------------------------------ forge
class ForgeScene(MenuScene):
    def __init__(self, app):
        super().__init__(app, "PRISM FORGE  -  lantern hues (cosmetic)", self._items, 250, overlay=True)

    def _items(self) -> list[MenuItem]:
        w = self.app.world
        items = [MenuItem(f"Glint: {w.profile['currency'].get('glint', 0)}", kind="label")]
        for name, (col, cost) in LANTERN_HUES.items():
            owned = cost == 0 or w.has_unlock(f"hue.{name}")
            cur = w.flag("lantern_hue", "amber") == name
            label = f"{name.title()}  " + ("[equipped]" if cur else "[owned]" if owned else f"{cost} Glint")
            items.append(MenuItem(label, lambda n=name, c=cost, o=owned: self._pick(n, c, o),
                                  enabled=owned or w.profile["currency"].get("glint", 0) >= cost))
        items.append(MenuItem("Back", self.app.scenes.pop))
        return items

    def _pick(self, name: str, cost: int, owned: bool) -> None:
        w = self.app.world
        if not owned:
            w.profile["currency"]["glint"] -= cost
            w.unlock(f"hue.{name}")
        w.set_flag("lantern_hue", name)
        self.app.audio.play("pickup", 0.8)
        self.rebuild()


# ------------------------------------------------------------------------------ control desk
class DeskMenu(MenuScene):
    def __init__(self, app):
        super().__init__(app, "CONTROL DESK", self._items, 200, overlay=True,
                         footer=[("CONFIRM", "Select"), ("BACK", "Close")])

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [
            MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
            MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
            MenuItem("Save game", self._save),
            MenuItem("Save and quit to title", self._to_title),
            MenuItem("Close", a.scenes.pop),
        ]

    def _save(self) -> None:
        self.app.save_now()
        self.app.toast("Game saved", (150, 230, 170))

    def _to_title(self) -> None:
        from .title import TitleScene
        self.app.save_now()
        self.app.profile = None
        self.app.world = None
        self.app.scenes.reset_to(TitleScene(self.app), fade=True)
