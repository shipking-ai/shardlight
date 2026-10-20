"""Terrace scene: world menu, the side-on game view, pack / crafting / chest screens and the HUD."""
from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
import pygame

from ...core.fx import FEEL, FloatingTexts, ParticleSystem, clamp, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Menu, MenuItem, MenuScene, SettingsScene,
                        ControlsScene, draw_panel, draw_prompts)
from . import art
from . import constants as K
from . import light as lightmod
from .game import Game
from .info import INFO
from .inventory import HOTBAR, SLOTS, can_craft, craft, recipes_for, stations_near
from .player import Intent, REACH
from .registry import Registry

W, H = 480, 270
T = K.TILE
SAVE_V = 1
LIGHT_LUT = np.array([[9, 9, 20], [16, 16, 30], [24, 24, 42], [30, 30, 50], [44, 42, 62], [60, 56, 76], [80, 74, 92], [104, 96, 108],
                      [132, 122, 126], [160, 148, 144], [188, 174, 160], [212, 200, 180], [232, 222, 202], [246, 238, 220],
                      [252, 248, 236], [255, 255, 255]], dtype=np.uint8)
SOUND_FOR_BLOCK = {"stone": "terrace_mine_stone", "dirt": "terrace_mine_dirt", "wood": "terrace_mine_wood", "plant": "terrace_mine_plant",
                   "glass": "terrace_mine_glass"}


class TerraceScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.reg: Registry | None = None
        self.game: Game | None = None
        self.screen: Scene | None = None
        self.opt_seed = opts.get("seed", "random")
        self.t = 0

    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("seen", {})
        d.setdefault("worlds", 0)
        d.setdefault("keystones", 0)
        self.reg = Registry.from_content(self.app.content)
        self.app.audio.play_music("terrace", 1.2, 0.3)
        self.show_menu()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, GameScreen):
            self.app.scenes.push(PauseMenu(self))

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.audio.set_intensity(0.2)
        self.set_screen(MenuScreen(self))

    # ------------------------------------------------------------------ world management
    def seed(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        return random.Random(self.app.rng.randrange(1 << 30)).randrange(1000, 999999)

    def _unlock_fn(self):
        return self.app.world.has_unlock

    def new_world(self) -> None:
        self.game = Game.new(self.reg, self.seed(), self.app.settings.get("difficulty.preset"), self._unlock_fn())
        self.data["worlds"] += 1
        self.save_game()
        self.set_screen(GameScreen(self))

    def continue_world(self) -> bool:
        raw = self.data.get("game")
        if not raw:
            return False
        g = Game.from_dict(self.reg, raw, self._unlock_fn())
        if g is None:
            self.app.toast("That world could not be loaded", DANGER)
            return False
        self.game = g
        self.set_screen(GameScreen(self))
        return True

    def save_game(self) -> None:
        if self.game is None:
            return
        self.data["game"] = self.game.to_dict()
        g = self.game
        self.data["summary"] = f"Day {g.world.day}, seed {g.world.seed}" + (", Keystone lit" if g.facet_done else "")
        self.app.save_now()

    def drain_hooks(self) -> None:
        g = self.game
        while g.hooks:
            name, payload = g.hooks.pop(0)
            if name == "terrace.keystone_lit":
                self.data["keystones"] += 1
                if self.app.world.complete_facet("terrace"):
                    self.app.toast("Terrace: the Facet is repaired", LENS)
                continue
            if name == "terrace.shrine":
                continue
            self.app.world.emit(name, **payload)


# ====================================================================================== menu
class MenuScreen(Scene):
    def __init__(self, ts: TerraceScene):
        super().__init__(ts.app)
        self.ts = ts
        self.t = 0
        has = bool(ts.data.get("game"))
        items = [MenuItem("Continue world", self._cont, enabled=has, hint=ts.data.get("summary", "") if has else ""),
                 MenuItem("New world" + (" (replaces saved)" if has else ""), self._new),
                 MenuItem("Return to hub", lambda: ts.finish(left=True))]
        self.menu = Menu(self.app, items, 230)
        rng = random.Random(4)
        self.hills = art.far_hills(5, 520, (60, 98, 70), 60, 22, 40)
        self.hills2 = art.far_hills(9, 520, (44, 74, 52), 80, 18, 25)

    def _cont(self) -> None:
        self.ts.continue_world()

    def _new(self) -> None:
        self.ts.new_world()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
            if "BACK" in self.inp.player(0).pressed and self.t > 12:
                self.ts.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        surf.blit(art.sky_gradient(0.95, 0.2, (W, H)), (0, 0))
        surf.blit(self.hills, (-(self.t // 6 % 40), 120))
        surf.blit(self.hills2, (-(self.t // 3 % 40), 150))
        pygame.draw.rect(surf, (90, 61, 43), (0, 222, W, 48))
        pygame.draw.rect(surf, (111, 168, 74), (0, 218, W, 6))
        for x in range(0, W, 8):
            surf.blit(art.block_sprite("grass", (112, 78, 52), (111, 168, 74), x // 8 % 4), (x, 224))
        f.draw(surf, "TERRACE", (24, 20), (111, 168, 74), (30, 40, 24), scale=5)
        f.draw(surf, "dig, build, keep the vigil", (28, 66), (255, 244, 205), (30, 40, 24), scale=1)
        draw_panel(surf, pygame.Rect(18, 96, 256, 60), fill=INK, alpha=235)
        self.menu.draw(surf, (24, 102))
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])


# ====================================================================================== game
class GameScreen(Scene):
    def __init__(self, ts: TerraceScene):
        super().__init__(ts.app)
        self.ts = ts
        self.g: Game = ts.game
        self.reg = ts.reg
        self.cam = [0.0, 0.0]
        self.chunks: dict[tuple[int, int], pygame.Surface] = {}
        self.parts = ParticleSystem(500, random.Random(3))
        self.floats = FloatingTexts()
        self.t = 0
        self.light_win = None
        self.light_key = None
        self.aim_tile: tuple[int, int] | None = None
        self.place_tile: tuple[int, int] | None = None
        self.mouse_mode = False
        self.toast_q: list[tuple[str, int]] = []
        self.autosave = 0.0
        self.anim = 0.0
        self.paused = False
        self.hills = [art.far_hills(5, 960, (70, 110, 90), 52, 20, 46), art.far_hills(9, 960, (46, 80, 62), 72, 16, 28)]
        self.sky_cache = (-1, None)
        self.seen_vigil = False
        self.flash_t = 0.0
        self.last_sound: dict[str, int] = {}

    def on_enter(self, **kw) -> None:
        p = self.g.player
        self.cam = [p.x - W / 2, p.y - H / 2]
        self.app.input.assign_local(1)
        seen = self.ts.data["seen"]
        if not seen.get("intro"):
            seen["intro"] = True
            from ...core.ui import Dialogue
            self.app.scenes.push(Dialogue(self.app, [
                ("Wayfarer", "Hold X to mine, Y to place or use, B to interact. Chop a tree for logs and open your pack with SELECT to craft."),
                ("Wayfarer", "Torches hold the night back. Shrines point toward the plinth where the Keystone must stand."),
            ], color=(111, 168, 74)))

    def open_pause(self) -> None:
        self.app.scenes.push(PauseMenu(self.ts))

    # ------------------------------------------------------------------ input
    def build_intent(self) -> Intent:
        p0 = self.inp.player(0)
        pl = self.g.player
        it = Intent()
        it.move = float(clamp(p0.move.x, -1, 1)) if abs(p0.move.x) > 0.2 else 0.0
        it.up = p0.move.y < -0.5
        it.down = p0.move.y > 0.5
        it.jump = "A" in p0.pressed
        it.jump_held = "A" in p0.down
        md, mp = self.inp.mouse_down, self.inp.mouse_pressed
        it.mine = "X" in p0.down or 1 in md
        it.use = "Y" in p0.pressed or 3 in mp
        it.interact = "B" in p0.pressed or 2 in mp
        return it

    def compute_targets(self, it: Intent) -> None:
        g, pl, w = self.g, self.g.player, self.g.world
        mx, my = self.inp.mouse_pos
        if pygame.mouse.get_rel() != (0, 0) and 0 <= mx < W and 0 <= my < H:
            self.mouse_mode = True
        if (it.move or it.up or it.down or "A" in self.inp.player(0).down) and not (self.inp.mouse_down):
            pass
        pa = self.inp.player(0).aim
        if pa.length() > 0.4:
            self.mouse_mode = False
        if self.mouse_mode and not (it.up or it.down):
            tx = int((mx + self.cam[0]) // T)
            ty = int((my + self.cam[1]) // T)
            self.aim_tile = self.place_tile = (tx, ty)
            return
        # keyboard / pad: cast a ray from the player's chest in the aim direction
        if pa.length() > 0.4:
            dx, dy = pa.x / pa.length(), pa.y / pa.length()
        else:
            dy = -1.0 if it.up else 1.0 if it.down else 0.0
            dx = pl.facing * (0.0 if dy and not it.move else 1.0) if (dy == 0 or it.move) else 0.0
            if dy and not it.move:
                dx = 0.0
            if dy and it.move:
                dx, dy = pl.facing * 0.7, dy * 0.7
            if dx == 0 and dy == 0:
                dx = pl.facing
        ox, oy = pl.x, pl.y - 8
        first_solid = None
        last_air = None
        for i in range(1, int(REACH * 2) + 1):
            px, py = ox + dx * i * T * 0.5, oy + dy * i * T * 0.5
            tx, ty = int(px // T), int(py // T)
            if (tx, ty) == (int(pl.x // T), int((pl.y - 8) // T)) or (tx, ty) == (int(pl.x // T), int((pl.y - 3) // T)):
                continue
            if w.get(tx, ty) != K.AIR and not w.reg.block(w.get(tx, ty)).get("replaceable") or w.liquid(tx, ty)[0] and False:
                first_solid = (tx, ty)
                break
            last_air = (tx, ty)
        self.aim_tile = first_solid or last_air
        self.place_tile = last_air if first_solid else (last_air or None)
        if first_solid is None and last_air is not None:
            # nothing in reach: mining targets the tile ahead, placing bridges one tile in front
            self.aim_tile = last_air

    # ------------------------------------------------------------------ update
    def update(self, dt: float) -> None:
        if self.paused:
            return
        self.t += 1
        self.anim += dt
        g, pl = self.g, self.g.player
        p0 = self.inp.player(0)
        if "PAUSE" in p0.pressed:
            self.open_pause()
            return
        if "SELECT" in p0.pressed and not pl.dead:
            self.app.scenes.push(PackScreen(self.ts, self))
            return
        if "L" in p0.pressed:
            g.inv.selected = (g.inv.selected - 1) % HOTBAR
            self.app.audio.play("ui_move", 0.3)
        if "R" in p0.pressed:
            g.inv.selected = (g.inv.selected + 1) % HOTBAR
            self.app.audio.play("ui_move", 0.3)
        it = self.build_intent()
        self.compute_targets(it)
        if pl.dead:
            if "CONFIRM" in p0.pressed or "A" in p0.pressed:
                pl.respawn()
                self.app.audio.play("ui_confirm", 0.6)
            it = Intent()
        tgt = self.aim_tile
        use_tile = self.place_tile if (self.inp.mouse_pos and self.mouse_mode) else (self.place_tile or self.aim_tile)
        # interaction / use targets differ: mine the block hit, place into the free tile before it
        g.update(dt, it, tgt)
        if it.use and use_tile is not None and use_tile != tgt:
            g._use(*use_tile)
        self._interaction_ui(it, tgt)
        self._feedback()
        # camera
        k = 1 - math.exp(-9 * dt)
        want = (pl.x - W / 2 + pl.facing * 14, pl.y - H / 2 - 6)
        self.cam[0] += (want[0] - self.cam[0]) * k
        self.cam[1] += (want[1] - self.cam[1]) * k
        self.cam[0] = max(0, min(g.world.w * T - W, self.cam[0]))
        self.cam[1] = max(0, min(g.world.h * T - H, self.cam[1]))
        self.parts.update(dt)
        self.floats.update(dt)
        self.flash_t = max(0.0, self.flash_t - dt)
        self.autosave += dt
        if self.autosave > 120:
            self.autosave = 0.0
            self.ts.save_game()
        self.ts.drain_hooks()
        self._music()

    def _interaction_ui(self, it: Intent, tgt) -> None:
        g = self.g
        if it.interact and tgt is not None:
            kind = g.player.interact_block(*tgt)
            if kind == "chest":
                self.app.scenes.push(ChestScreen(self.ts, self, tgt))
            elif kind == "station":
                self.app.scenes.push(PackScreen(self.ts, self, tab=1))

    def _music(self) -> None:
        g = self.g
        danger = any(c.kind in ("gloam", "ridgewolf") and abs(c.x - g.player.x) < 120 for c in g.eco.alive())
        inten = 0.9 if g.world.keystone_state == "vigil" else 0.65 if danger else 0.3 if g.world.is_night() else 0.2
        self.app.audio.set_intensity(inten)

    def _feedback(self) -> None:
        g = self.g
        a = self.app.audio
        cx, cy = self.cam
        for name, data in g.sound:
            n = self.last_sound.get(name, -99)
            if self.t - n < 3 and name in ("pickup", "hiss", "died"):
                continue
            self.last_sound[name] = self.t
            if name == "broke":
                a.play("terrace_break", 0.7)
                col = self.reg.blocks[data["block"]]["color"]
                self.parts.emit(((data["x"] + 0.5) * T - cx, (data["y"] + 0.5) * T - cy), 9, (20, 80), (0, 360), (0.2, 0.6), (1, 2.2), tuple(col),
                                shade(col), gravity=220, drag=1)
            elif name == "placed":
                a.play("terrace_place", 0.6)
            elif name == "jump":
                a.play("terrace_jump", 0.3)
            elif name == "land":
                a.play("terrace_land", 0.4)
            elif name == "thud":
                a.play("terrace_thud", 0.9)
                self.flash_t = 0.2
            elif name == "hurt":
                a.play("terrace_hurt", 0.8)
                FEEL.flash((255, 80, 70), 0.25)
            elif name == "died":
                a.play("terrace_hurt", 1.0)
                FEEL.flash((255, 60, 60), 0.5)
            elif name in ("slash",):
                a.play("terrace_slash", 0.6)
            elif name == "kill":
                a.play("terrace_hurt", 0.4)
            elif name == "eat":
                a.play("terrace_eat", 0.7)
            elif name == "door":
                a.play("terrace_door", 0.7)
            elif name == "hiss":
                a.play("terrace_hiss", 0.5, pan=0.0)
            elif name == "pickup":
                a.play("pickup", 0.35)
            elif name == "shrine":
                a.play("terrace_shrine", 0.8)
            elif name == "vigil":
                a.play("terrace_vigil", 0.9)
                FEEL.flash((255, 244, 200), 0.4)
            elif name == "graze":
                pass
            elif name == "gloam_spawn":
                a.play("terrace_gloam", 0.4)
            elif name == "born":
                a.play("terrace_" + data["kind"], 0.25) if ("terrace_" + data["kind"]) in _CALLS else None
            elif name in ("till", "shear", "tame", "scoop", "pour"):
                a.play("terrace_splash" if name in ("scoop", "pour") else "terrace_place", 0.5)
            elif name == "cannot_mine":
                self.toast_q.append((data["why"], 120))
        g.sound.clear()
        for t in g.toasts:
            self.toast_q.append((t, 220))
        g.toasts.clear()
        self.toast_q = [(t, n - 1) for t, n in self.toast_q if n > 1][-4:]
        if g.world.keystone_state == "vigil" and not self.seen_vigil:
            self.seen_vigil = True
        if g.world.keystone_state != "vigil":
            self.seen_vigil = False

    # ------------------------------------------------------------------ drawing
    def _chunk(self, cx: int, cy: int) -> pygame.Surface:
        grid = self.g.world.grid
        key = (cx, cy)
        if key in grid.render_dirty or key not in self.chunks:
            self.chunks[key] = art.render_chunk(self.g.world, cx, cy)
            grid.render_dirty.discard(key)
        return self.chunks[key]

    def light_surface(self, x0: int, y0: int, tw: int, th: int) -> pygame.Surface:
        g = self.g
        pl = g.player
        lamp = (int(pl.x // T), int((pl.y - 8) // T), 6)
        key = (x0, y0, tw, th, g.world.grid.version, int(g.world.daylight() * 24), self.t // 5, lamp)
        if self.light_key != key:
            arr = lightmod.compute(g.world, x0, y0, tw, th, lamps=[lamp])
            h, w = arr.shape
            rgb = LIGHT_LUT[arr]                          # (h, w, 3)
            small = pygame.surfarray.make_surface(np.ascontiguousarray(np.transpose(rgb, (1, 0, 2))))
            self.light_win = pygame.transform.smoothscale(small, (w * T, h * T))
            self.light_key = key
        return self.light_win

    def draw(self, surf: pygame.Surface) -> None:
        g, w, pl, f = self.g, self.g.world, self.g.player, self.app.font
        day = w.daylight()
        cx, cy = int(self.cam[0]), int(self.cam[1])
        # sky
        k = int(day * 20)
        if self.sky_cache[0] != k:
            self.sky_cache = (k, art.sky_gradient(day, w.clock, (W, H)))
        surf.blit(self.sky_cache[1], (0, 0))
        if day < 0.6:
            st = art.star_layer((W, H)).copy()
            st.set_alpha(int(255 * (0.6 - day) / 0.5))
            surf.blit(st, (0, 0))
        self._sun_moon(surf, w.clock, day)
        # parallax hills fade out underground
        depth_fade = clamp((cy + H * 0.5 - (g.world.surf[min(w.w - 1, max(0, int(pl.x // T)))] * T)) / 140.0)
        if depth_fade < 1.0:
            for i, hl in enumerate(self.hills):
                ox = -int(self.cam[0] * (0.1 + 0.12 * i)) % 960
                horizon = int(w.surf[min(w.w - 1, max(0, int(pl.x // T)))]) * T - cy
                oy = horizon - 104 + i * 14
                tint = hl.copy()
                tint.fill((int(255 * (0.25 + 0.75 * day)),) * 3 + (255,), special_flags=pygame.BLEND_RGBA_MULT)
                tint.set_alpha(int(255 * (1 - depth_fade)))
                surf.blit(tint, (-ox, oy))
                surf.blit(tint, (960 - ox, oy))
        # underground backdrop
        under_y = int(w.surf[min(w.w - 1, max(0, int(pl.x // T)))] * T + 24 - cy)
        if under_y < H:
            pygame.draw.rect(surf, (28, 24, 34), (0, max(0, under_y), W, H - max(0, under_y)))
        # tiles
        cw = K.CHUNK * T
        for ccx in range(cx // cw, (cx + W) // cw + 1):
            for ccy in range(cy // cw, (cy + H) // cw + 1):
                if 0 <= ccx < w.grid.cw and 0 <= ccy < w.grid.ch:
                    surf.blit(self._chunk(ccx, ccy), (ccx * cw - cx, ccy * cw - cy))
        # liquid shimmer on the surface cells
        tx0, ty0 = cx // T, cy // T
        sub = w.grid.liq[ty0:ty0 + H // T + 2, tx0:tx0 + W // T + 2]
        ys, xs = np.nonzero(((sub & 15) > 0))
        for yy, xx in zip(ys[:400], xs[:400]):
            if yy == 0 or (sub[yy - 1, xx] & 15) == 0:
                px, py = (tx0 + xx) * T - cx, (ty0 + yy) * T - cy + T - max(1, int((sub[yy, xx] & 15) * T / 8))
                lava = bool(sub[yy, xx] & K.LIQ_LAVA)
                ph = math.sin(self.anim * 3 + xx * 0.9)
                pygame.draw.line(surf, (255, 200, 90) if lava else (210, 235, 255), (px + 1 + int(ph), py), (px + 4 + int(ph), py))
        # drops, carcasses
        for d in w.drops:
            it = self.reg.items[d.item]
            ico = self._icon(d.item)
            bob = math.sin(self.anim * 4 + d.x) * 1.2
            surf.blit(ico, (d.x - cx - 6, d.y - cy - 10 + bob))
        for cz in g.eco.carcasses:
            pygame.draw.ellipse(surf, (110, 80, 70), (cz.x - cx - 5, cz.y - cy - 3, 10, 4))
        # creatures
        for c in g.eco.alive():
            if cx - 30 < c.x < cx + W + 30 and cy - 30 < c.y < cy + H + 30:
                d = self.reg.creatures[c.kind]
                fr = int(c.anim * (4 if abs(c.vx) > 3 or d.get("habitat") == "air" else 1.2)) % 2
                spr = art.creature_sprite(c.kind, tuple(d["size"]), tuple(d.get("color", (160, 160, 160))),
                                          tuple(d["accent"]) if d.get("accent") else None, fr, c.facing < 0, c.flash > 0)
                surf.blit(spr, (c.x - cx - spr.get_width() / 2, c.y - cy - spr.get_height() + 2))
                if c.tamed:
                    pygame.draw.rect(surf, (255, 120, 150), (c.x - cx - 1, c.y - cy - d["size"][1] - 5, 3, 3))
        # player
        if not pl.dead:
            state = "climb" if pl.climbing else "jump" if not pl.on_ground and not pl.in_water else "walk" if abs(pl.vx) > 6 else "idle"
            fr = int(self.anim * 9)
            armor = tuple(self._armor_col(s) for s in ("head", "chest", "legs"))
            spr = art.player_sprite(fr % 4, pl.facing < 0, state, armor)
            px, py = pl.x - cx - spr.get_width() / 2, pl.y - cy - spr.get_height() + 2
            if pl.invuln > 0 and int(self.anim * 20) % 2:
                spr = spr.copy()
                spr.set_alpha(110)
            surf.blit(spr, (px, py))
            held = g.inv.held()
            if held:
                ico = self._icon(held)
                hx = px + (7 if pl.facing > 0 else -3)
                swing = math.sin(self.anim * 14) * 3 if (pl.mine_pos or pl.attack_cd > 0.2) else 0
                surf.blit(pygame.transform.flip(ico, pl.facing < 0, False), (hx, py + 6 + swing))
        # mining cracks and cursor
        if pl.mine_pos and pl.mine_progress() > 0:
            mx, my = pl.mine_pos
            prog = pl.mine_progress()
            for i in range(int(prog * 8)):
                a = (i * 53 + mx * 7) % T
                pygame.draw.line(surf, (20, 16, 24), (mx * T - cx + a, my * T - cy), (mx * T - cx + (a * 3) % T, my * T - cy + T - 1))
            pygame.draw.rect(surf, (255, 255, 255), (mx * T - cx - 1, my * T - cy - 1, T + 2, T + 2), 1)
        elif self.aim_tile and not pl.dead:
            ax, ay = self.aim_tile
            ok = pl.tile_in_reach(ax, ay)
            pygame.draw.rect(surf, (255, 255, 255) if ok else (120, 120, 130), (ax * T - cx, ay * T - cy, T, T), 1)
        self.parts.draw(surf, (0, 0))
        # lighting
        lx0, ly0 = max(0, tx0 - 2), max(0, ty0 - 2)
        lw, lh = W // T + 6, H // T + 6
        lsurf = self.light_surface(lx0, ly0, lw, lh)
        surf.blit(lsurf, (lx0 * T - cx, ly0 * T - cy), special_flags=pygame.BLEND_MULT)
        self._hud(surf)
        if self.flash_t > 0:
            pass
        FEEL.draw_flash(surf)

    def _armor_col(self, slot: str):
        it = self.g.inv.armor.get(slot)
        return tuple(self.reg.items[it]["color"]) if it else None

    def _icon(self, item: str) -> pygame.Surface:
        it = self.reg.items[item]
        args = None
        if it.get("place") and it.get("icon") == "block":
            b = self.reg.blocks[it["place"]]
            args = (b["style"], tuple(b["color"]), tuple(b["accent"]) if b.get("accent") else None, 0, 0, "")
        return art.item_icon(item, tuple(it["color"]), tuple(it["accent"]) if it.get("accent") else None, it.get("icon", "misc"), args)

    def _sun_moon(self, surf: pygame.Surface, clock: float, day: float) -> None:
        c = (clock + 0.06) % 1.0
        # sun travels from c=0.0 (east horizon) to 0.55 (west); moon the rest
        if c < 0.58:
            a = c / 0.58 * math.pi
            x, y = W / 2 - math.cos(a) * 190, 150 - math.sin(a) * 130
            pygame.draw.circle(surf, (255, 238, 170), (int(x), int(y)), 10)
            pygame.draw.circle(surf, (255, 250, 220), (int(x), int(y)), 7)
        else:
            a = (c - 0.58) / 0.42 * math.pi
            x, y = W / 2 - math.cos(a) * 190, 150 - math.sin(a) * 120
            pygame.draw.circle(surf, (226, 230, 246), (int(x), int(y)), 8)
            pygame.draw.circle(surf, (190, 196, 220), (int(x) - 2, int(y) - 1), 2)

    def _hud(self, surf: pygame.Surface) -> None:
        g, pl, w, f = self.g, self.g.player, self.g.world, self.app.font
        # bars
        def bar(x, y, wd, frac, col, label):
            pygame.draw.rect(surf, (10, 8, 16), (x - 1, y - 1, wd + 2, 8))
            pygame.draw.rect(surf, (40, 34, 50), (x, y, wd, 6))
            pygame.draw.rect(surf, col, (x, y, int(wd * clamp(frac)), 6))
            f.draw(surf, label, (x + wd + 4, y - 1), PARCHMENT, (10, 8, 16))
        bar(6, 6, 80, pl.hp / 100.0, (220, 70, 80) if pl.hp > 30 else (255, 150, 60), f"{int(pl.hp)}")
        bar(6, 16, 80, pl.hunger / 100.0, (220, 170, 70), "food")
        # clock and place
        depth = int(pl.y / T - w.surf[min(w.w - 1, int(pl.x // T))])
        place = w.biome_name(int(pl.x // T)).title() if depth < 8 else "Caves" if depth < 100 else "Deep caves"
        t = (w.clock + 0.06) % 1.0
        hh = int(((t * 24) + 6) % 24)
        mm = int((t * 24 * 60) % 60)
        f.draw(surf, f"Day {w.day}  {hh:02d}:{mm:02d}", (W - 6, 5), PARCHMENT, (10, 8, 16), anchor="topright")
        f.draw(surf, f"{place}  depth {max(0, depth)}", (W - 6, 15), DIM, (10, 8, 16), anchor="topright")
        # hotbar
        x0 = (W - HOTBAR * 20) // 2
        y0 = H - 24
        for i in range(HOTBAR):
            r = pygame.Rect(x0 + i * 20, y0, 18, 18)
            sel = i == g.inv.selected
            pygame.draw.rect(surf, (24, 20, 34), r)
            pygame.draw.rect(surf, BRASS if sel else (70, 62, 84), r, 2 if sel else 1)
            s = g.inv.slots[i]
            if s:
                surf.blit(self._icon(s[0]), (r.x + 3, r.y + 3))
                if s[1] > 1:
                    f.draw(surf, str(s[1]), (r.right - 1, r.bottom - 8), PARCHMENT, (10, 8, 16), anchor="topright")
        held = g.inv.held()
        if held:
            f.draw(surf, self.reg.items[held]["name"], (W // 2, y0 - 10), PARCHMENT, (10, 8, 16), anchor="midtop")
        # toasts
        y = 30
        for text, n in self.toast_q:
            f.draw(surf, text, (W // 2, y), (255, 244, 205), (10, 8, 16), anchor="midtop")
            y += 10
        if w.keystone_state == "vigil":
            f.draw(surf, "VIGIL: hold out until dawn", (W // 2, 4), (255, 214, 120), (10, 8, 16), anchor="midtop")
        elif w.keystone_state == "assembled":
            f.draw(surf, "The Keystone stands: light its prism (B)", (W // 2, 4), (255, 214, 120), (10, 8, 16), anchor="midtop")
        if pl.dead:
            dim = pygame.Surface((W, H), pygame.SRCALPHA)
            dim.fill((60, 8, 8, 150))
            surf.blit(dim, (0, 0))
            f.draw(surf, "YOU FELL", (W // 2, 90), (255, 200, 190), (40, 6, 6), anchor="midtop", scale=4)
            f.draw(surf, "Part of your pack lies where you fell.", (W // 2, 130), PARCHMENT, (10, 8, 16), anchor="midtop")
            draw_prompts(surf, self.app, [("CONFIRM", "Rise again")], y=150)


def shade(c, k: float = 0.6):
    return tuple(int(max(0, min(255, v * k))) for v in c)


_CALLS = {"terrace_hopper", "terrace_woolback", "terrace_wolf", "terrace_bumblet", "terrace_crawler", "terrace_gleaner", "terrace_gloam"}


# ====================================================================================== pack / crafting
class PackScreen(Scene):
    def __init__(self, ts: TerraceScene, gs: GameScreen, tab: int = 0):
        super().__init__(ts.app)
        self.ts, self.gs, self.g, self.reg = ts, gs, ts.game, ts.reg
        self.tab = tab
        self.sel = 0
        self.cur = 0
        self.held_slot: int | None = None
        self.t = 0
        self.msg = ""
        self.msg_t = 0
        self.crafted_flash = 0

    def recipes(self) -> list[dict]:
        pl = self.g.player
        st = stations_near(self.g.world, pl.x / T, (pl.y - 7) / T) | {"hand"}
        return recipes_for(self.reg, self.g, st)

    def update(self, dt: float) -> None:
        self.t += 1
        self.msg_t = max(0, self.msg_t - 1)
        self.crafted_flash = max(0, self.crafted_flash - 1)
        p = self.inp.player(0)
        if self.t < 6:
            return
        if "SELECT" in p.pressed or "BACK" in p.pressed:
            self.app.scenes.pop()
            return
        if "L" in p.pressed:
            self.tab = (self.tab - 1) % 3
        if "R" in p.pressed:
            self.tab = (self.tab + 1) % 3
        dx, dy = p.menu_dir()
        if self.tab == 0:
            if dx:
                self.cur = (self.cur + dx) % SLOTS
            if dy:
                self.cur = (self.cur + dy * HOTBAR) % SLOTS
            if "CONFIRM" in p.pressed:
                if self.held_slot is None:
                    if self.g.inv.slots[self.cur]:
                        self.held_slot = self.cur
                else:
                    self.g.inv.swap(self.held_slot, self.cur)
                    self.held_slot = None
                self.app.audio.play("ui_move", 0.5)
            if "X" in p.pressed and self.g.inv.slots[self.cur]:
                if self.g.inv.equip(self.cur):
                    self.app.audio.play("ui_confirm", 0.6)
                    self.say("Equipped.")
                else:
                    ok = self.g.player.eat(self.g.inv.slots[self.cur][0]) if self.reg.items[self.g.inv.slots[self.cur][0]].get("food") else False
                    if ok:
                        self.g.inv.take_slot(self.cur)
                        self.app.audio.play("terrace_eat", 0.7)
            if "Y" in p.pressed and self.g.inv.slots[self.cur]:
                s = self.g.inv.slots[self.cur]
                from .world import Drop
                self.g.world.drops.append(Drop(self.g.player.x + self.g.player.facing * 12, self.g.player.y - 8, s[0], 1, self.g.player.facing * 40, -50))
                self.g.inv.take_slot(self.cur)
        elif self.tab == 1:
            recs = self.recipes()
            if dy and recs:
                self.sel = (self.sel + dy) % len(recs)
                self.app.audio.play("ui_move", 0.4)
            self.sel = min(self.sel, max(0, len(recs) - 1))
            if "CONFIRM" in p.pressed and recs:
                r = recs[self.sel]
                if craft(self.reg, self.g.inv, r):
                    self.g.player.stats["crafted"] += 1
                    self.app.audio.play("terrace_craft", 0.7)
                    self.crafted_flash = 12
                    self.say("Crafted.")
                else:
                    self.say(can_craft(self.reg, self.g.inv, r)[1])
                    self.app.audio.play("ui_error", 0.5)
        else:
            if "CONFIRM" in p.pressed:
                pass

    def say(self, text: str) -> None:
        self.msg, self.msg_t = text, 120

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((8, 6, 16, 200))
        surf.blit(dim, (0, 0))
        names = ["Pack", "Craft", "Gear"]
        x = 14
        for i, n in enumerate(names):
            r = pygame.Rect(x, 10, 50, 14)
            pygame.draw.rect(surf, BRASS if i == self.tab else INK_2, r)
            f.draw(surf, n, (r.centerx, r.y + 3), (16, 12, 30) if i == self.tab else DIM, None, anchor="midtop")
            x += 54
        f.draw(surf, "[L] [R] switch", (W - 8, 13), DIM, None, anchor="topright")
        body = pygame.Rect(10, 28, W - 20, H - 52)
        draw_panel(surf, body, fill=INK, alpha=245)
        if self.tab == 0:
            self._draw_pack(surf, body)
        elif self.tab == 1:
            self._draw_craft(surf, body)
        else:
            self._draw_gear(surf, body)
        if self.msg_t > 0:
            f.draw(surf, self.msg, (W // 2, H - 24), (255, 244, 205), None, anchor="midtop")
        keys = {0: [("CONFIRM", "Pick / drop"), ("X", "Equip / eat"), ("Y", "Throw"), ("SELECT", "Close")],
                1: [("CONFIRM", "Craft"), ("SELECT", "Close")], 2: [("SELECT", "Close")]}[self.tab]
        draw_prompts(surf, self.app, keys, y=H - 12)

    def _draw_pack(self, surf, body) -> None:
        f, g = self.app.font, self.g
        for i in range(SLOTS):
            r = pygame.Rect(body.x + 10 + (i % HOTBAR) * 22, body.y + 14 + (i // HOTBAR) * 22 + (4 if i >= HOTBAR else 0), 20, 20)
            pygame.draw.rect(surf, (28, 24, 40), r)
            pygame.draw.rect(surf, BRASS if i == self.cur else (80, 70, 96) if i != self.held_slot else LENS, r, 2 if i in (self.cur, self.held_slot) else 1)
            s = g.inv.slots[i]
            if s:
                surf.blit(self.gs._icon(s[0]), (r.x + 4, r.y + 4))
                if s[1] > 1:
                    f.draw(surf, str(s[1]), (r.right - 1, r.bottom - 8), PARCHMENT, (10, 8, 16), anchor="topright")
        f.draw(surf, "Hotbar", (body.x + 10, body.y + 4), DIM, None)
        s = g.inv.slots[self.cur]
        if s:
            it = self.reg.items[s[0]]
            f.draw(surf, it["name"], (body.x + 10, body.y + 112), PARCHMENT, None)
            f.draw_wrapped(surf, it.get("desc", ""), pygame.Rect(body.x + 10, body.y + 124, 300, 24), DIM, None, max_lines=2)
            if it.get("food"):
                f.draw(surf, f"Food +{it['food']['hunger']:.0f}  Health {it['food'].get('heal', 0):+.0f}", (body.x + 10, body.y + 148), GOOD, None)
            if it.get("tool"):
                t = it["tool"]
                f.draw(surf, f"{t['type']} tier {t.get('tier', 0)}  power {t.get('power', 1):.1f}  damage {t.get('damage', 0):.1f}", (body.x + 10, body.y + 148), LENS, None)
            if it.get("armor"):
                f.draw(surf, f"{it['armor']['slot']} defense {it['armor']['defense']}", (body.x + 10, body.y + 148), LENS, None)
        f.draw(surf, f"Furnace fuel stored: {g.inv.fuel_buffer:.0f}", (body.right - 10, body.y + 4), DIM, None, anchor="topright")

    def _draw_craft(self, surf, body) -> None:
        f, g = self.app.font, self.g
        recs = self.recipes()
        left = pygame.Rect(body.x + 6, body.y + 6, 190, body.h - 12)
        top = max(0, min(self.sel - 6, len(recs) - 13))
        y = left.y
        for i in range(top, min(len(recs), top + 13)):
            r = recs[i]
            ok = can_craft(self.reg, g.inv, r)[0]
            out = next(iter(r["outputs"]))
            row = pygame.Rect(left.x, y, left.w, 13)
            if i == self.sel:
                pygame.draw.rect(surf, INK_2, row)
                pygame.draw.rect(surf, BRASS, (row.x, row.y, 2, row.h))
            surf.blit(self.gs._icon(out), (row.x + 4, row.y))
            f.draw(surf, self.reg.items[out]["name"], (row.x + 20, row.y + 3), PARCHMENT if ok else (110, 104, 120), None)
            f.draw(surf, r["station"][:4], (row.right - 4, row.y + 3), (120, 160, 200) if ok else (80, 76, 96), None, anchor="topright")
            y += 13
        if not recs:
            f.draw(surf, "Nothing to craft yet.", (left.x + 6, left.y + 6), DIM, None)
        det = pygame.Rect(body.x + 204, body.y + 6, body.w - 212, body.h - 12)
        if recs:
            r = recs[self.sel]
            out, cnt = next(iter(r["outputs"].items()))
            f.draw(surf, f"{self.reg.items[out]['name']} x{cnt}", (det.x, det.y + 2), BRASS, None)
            f.draw(surf, f"at {r['station']}" + (f"   heat {r['heat']:.0f}" if r.get("heat") else ""), (det.x, det.y + 12), DIM, None)
            yy = det.y + 28
            for k, v in r["inputs"].items():
                have = g.inv.count(k)
                f.draw(surf, f"{self.reg.items[k]['name']}", (det.x, yy), GOOD if have >= v else DANGER, None)
                f.draw(surf, f"{have}/{v}", (det.right - 4, yy), GOOD if have >= v else DANGER, None, anchor="topright")
                yy += 10
            if r.get("heat"):
                fuel_have = g.inv.fuel_buffer
                f.draw(surf, f"Fuel buffer {fuel_have:.0f}", (det.x, yy + 4), DIM, None)
            hint = r.get("hint") or ""
            if hint:
                f.draw_wrapped(surf, hint, pygame.Rect(det.x, det.bottom - 40, det.w, 36), DIM, None, max_lines=3)
        f.draw(surf, "Stations (workbench, furnace, loom, forge) work within a few tiles.", (body.x + 8, body.bottom - 12), DIM, None)

    def _draw_gear(self, surf, body) -> None:
        f, g = self.app.font, self.g
        pl = g.player
        for i, slot in enumerate(("head", "chest", "legs")):
            r = pygame.Rect(body.x + 20, body.y + 20 + i * 26, 22, 22)
            pygame.draw.rect(surf, (28, 24, 40), r)
            pygame.draw.rect(surf, (80, 70, 96), r, 1)
            it = g.inv.armor[slot]
            if it:
                surf.blit(self.gs._icon(it), (r.x + 5, r.y + 5))
                f.draw(surf, f"{self.reg.items[it]['name']}  def {self.reg.items[it]['armor']['defense']}", (r.right + 8, r.y + 7), PARCHMENT, None)
            else:
                f.draw(surf, f"({slot})", (r.right + 8, r.y + 7), DIM, None)
        f.draw(surf, f"Defense {g.inv.defense()}   Lava resist {int(g.inv.lava_resist() * 100)}%", (body.x + 20, body.y + 100), LENS, None)
        s = pl.stats
        f.draw(surf, f"Mined {s['mined']}  Placed {s['placed']}  Crafted {s['crafted']}  Slain {s['kills']}  Falls {s['deaths']}", (body.x + 20, body.y + 120), DIM, None)
        f.draw(surf, "Equip armor from the Pack tab (X).", (body.x + 20, body.y + 140), DIM, None)
        ks = g.world.keystone_state
        txt = {"unbuilt": "The Keystone is not yet raised.", "assembled": "The Keystone stands, unlit.", "vigil": "The vigil is under way.", "done": "The Keystone is lit."}[ks]
        f.draw(surf, txt, (body.x + 20, body.y + 162), (255, 214, 120), None)


# ====================================================================================== chest
class ChestScreen(Scene):
    def __init__(self, ts: TerraceScene, gs: GameScreen, pos: tuple[int, int]):
        super().__init__(ts.app)
        self.ts, self.gs, self.g = ts, gs, ts.game
        self.pos = pos
        w = self.g.world
        if pos not in w.chests:
            w.chests[pos] = [None] * 20
        self.slots = w.chests[pos]
        self.side = 0
        self.cur = 0
        self.t = 0
        self.app.audio.play("terrace_door", 0.5)

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t < 6:
            return
        if "BACK" in p.pressed or "SELECT" in p.pressed:
            self.app.scenes.pop()
            return
        dx, dy = p.menu_dir()
        cols = 10 if self.side == 0 else 5
        n = SLOTS if self.side == 0 else len(self.slots)
        if dx:
            self.cur = (self.cur + dx) % n
        if dy:
            self.cur = (self.cur + dy * cols) % n
        if "L" in p.pressed or "R" in p.pressed:
            self.side = 1 - self.side
            self.cur = 0
        if "CONFIRM" in p.pressed:
            self._move()

    def _move(self) -> None:
        inv = self.g.inv
        if self.side == 0:
            s = inv.slots[self.cur]
            if not s:
                return
            item, cnt = s
            for i, c in enumerate(self.slots):
                if c and c[0] == item and c[1] < inv.stack_limit(item):
                    take = min(cnt, inv.stack_limit(item) - c[1])
                    c[1] += take
                    cnt -= take
                    break
            if cnt > 0:
                for i, c in enumerate(self.slots):
                    if c is None:
                        self.slots[i] = [item, cnt]
                        cnt = 0
                        break
            if cnt == 0:
                inv.slots[self.cur] = None
            else:
                s[1] = cnt
        else:
            c = self.slots[self.cur]
            if not c:
                return
            left = inv.add(c[0], c[1])
            if left == 0:
                self.slots[self.cur] = None
            else:
                c[1] = left
        self.app.audio.play("ui_move", 0.5)

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((8, 6, 16, 200))
        surf.blit(dim, (0, 0))
        body = pygame.Rect(30, 30, W - 60, 190)
        draw_panel(surf, body, fill=INK, alpha=245, title="CHEST", font=f)
        for side, slots, cols, ox, oy in ((1, self.slots, 5, body.x + 12, body.y + 18), (0, self.g.inv.slots, 10, body.x + 12, body.y + 110)):
            for i, s in enumerate(slots):
                r = pygame.Rect(ox + (i % cols) * 22, oy + (i // cols) * 22, 20, 20)
                pygame.draw.rect(surf, (28, 24, 40), r)
                on = (self.side == (0 if side == 0 else 1)) and self.cur == i
                pygame.draw.rect(surf, BRASS if on else (80, 70, 96), r, 2 if on else 1)
                if s:
                    surf.blit(self.gs._icon(s[0]), (r.x + 4, r.y + 4))
                    if s[1] > 1:
                        f.draw(surf, str(s[1]), (r.right - 1, r.bottom - 8), PARCHMENT, (10, 8, 16), anchor="topright")
        f.draw(surf, "Chest", (body.x + 130, body.y + 18), DIM, None)
        f.draw(surf, "Pack", (body.x + 12, body.y + 100), DIM, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Move stack"), ("L", "Switch side"), ("BACK", "Close")], y=H - 12)


# ====================================================================================== pause
class PauseMenu(MenuScene):
    def __init__(self, ts: TerraceScene):
        self.ts = ts
        super().__init__(ts.app, "PAUSED", self._items, 220, overlay=True, footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [MenuItem("Resume", a.scenes.pop), MenuItem("Save world", self._save),
                MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
                MenuItem("World menu (saves)", self._menu), MenuItem("Leave shard (saves)", self._leave)]

    def _save(self) -> None:
        self.ts.save_game()
        self.app.toast("World saved", GOOD)

    def _menu(self) -> None:
        self.app.scenes.pop()
        self.ts.save_game()
        self.ts.show_menu()

    def _leave(self) -> None:
        self.app.scenes.pop()
        self.ts.save_game()
        self.ts.finish(left=True)
