"""Verdant scene: title/menu, the world view with lighting and HUD, and glue to the echo system."""
from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
import pygame

from ...core.fx import FEEL, Lighting, clamp, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Menu, MenuItem, draw_panel, draw_prompts)
from . import art
from . import tiles as T
from .catalog import Catalog
from .info import INFO
from .sim import Game, Intent, SKILLS, SKILL_LABEL

W, H = 480, 270
TS = T.TILE
SAVE_V = 1
LIGHT_OBJ = {T.O["lamp_lit"], T.O["greatlamp_lit"], T.O["campfire"], T.O["brazier"], T.O["hearth"], T.O["forge"], T.O["candle"],
             T.O["glowmoss"]}


class VerdantScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.cat: Catalog | None = None
        self.game: Game | None = None
        self.screen: Scene | None = None
        self.opt_seed = opts.get("seed", "random")
        self.t = 0

    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("seen", {})
        d.setdefault("worlds", 0)
        self.cat = Catalog(self.app.content, self.app.world.has_unlock)
        self.app.audio.play_music("verdant", 1.2, 0.3)
        self.show_menu()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.game is not None:
            self.game.admin_god = bool(getattr(self.app, "admin_god", False))
            self.game.admin_oneshot = bool(getattr(self.app, "admin_oneshot", False))
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_exit(self) -> None:
        # "Leave shard" from the shared pause menu returns to the hub without asking the mode: keep the journey.
        if self.game is not None and not self.game.dead:
            self.save_game()

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, GameScreen):
            self.open_pause_menu()

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.audio.set_intensity(0.15)
        self.set_screen(MenuScreen(self))

    # ------------------------------------------------------------------ worlds
    def seed(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        return random.Random(self.app.rng.randrange(1 << 30)).randrange(1000, 999999)

    def _strength(self) -> float:
        try:
            return float(self.app.settings.get("difficulty.adaptive_ai"))
        except Exception:
            return 1.0

    def new_world(self) -> None:
        self.game = Game.new(self.cat, self.seed(), self.app.settings.get("difficulty.preset"), self._strength(), self.app.world.has_unlock)
        self.data["worlds"] += 1
        self.save_game()
        self.set_screen(GameScreen(self, intro=True))

    def continue_world(self) -> bool:
        raw = self.data.get("game")
        if not raw:
            return False
        g = Game.from_dict(self.cat, raw, self.app.world.has_unlock, self._strength())
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
        done = sum(1 for q in g.quests.state.values() if q["done"])
        self.data["summary"] = f"{g.time_text()}  -  {done} quests done  -  seed {g.seed}"
        self.app.save_now()

    def drain_hooks(self) -> None:
        g = self.game
        w = self.app.world
        while g.hooks:
            name, payload = g.hooks.pop(0)
            if name == "lore":
                w.add_lore(payload["id"])
            elif name == "rep":
                w.add_rep(payload["faction"], payload["amount"])
            elif name == "verdant.quest_completed":
                w.emit(name, **payload)
                if payload.get("quest") == "kindle_the_hollow":
                    if w.complete_facet("verdant"):
                        self.app.toast("Verdant: the Facet is repaired", LENS)
                        w.emit("verdant.great_quest_done")
                self.save_game()
            elif name in ("verdant.site_explored",):
                w.emit(name, **payload)
            elif name in ("verdant.quest_started", "verdant.site_discovered"):
                if name == "verdant.site_discovered":
                    w.add_counter("verdant.sites", 1)


# ====================================================================================== menu
class MenuScreen(Scene):
    def __init__(self, vs: VerdantScene):
        super().__init__(vs.app)
        self.vs = vs
        self.t = 0
        has = bool(vs.data.get("game"))
        items = [MenuItem("Continue journey", self._cont, enabled=has, hint=vs.data.get("summary", "") if has else ""),
                 MenuItem("New journey" + (" (replaces saved)" if has else ""), self._new),
                 MenuItem("Return to hub", lambda: vs.finish(left=True))]
        self.menu = Menu(self.app, items, 240)
        rnd = random.Random(2)
        self.stars = [(rnd.randrange(W), rnd.randrange(0, 110), rnd.random()) for _ in range(40)]
        self.lamps = [(40 + i * 61, 214 + (i % 2) * 4) for i in range(8)]

    def _cont(self) -> None:
        self.vs.continue_world()

    def _new(self) -> None:
        self.vs.new_world()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
            if "BACK" in self.inp.player(0).pressed and self.t > 12:
                self.vs.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        for y in range(0, 190, 2):
            k = y / 190
            pygame.draw.rect(surf, mix((20, 28, 56), (246, 170, 100), k ** 1.6), (0, y, W, 2))
        for (x, y, a) in self.stars:
            if y < 90:
                c = int(120 + 120 * ((math.sin(self.t * 0.03 + a * 9) + 1) / 2))
                surf.set_at((x, y), (c, c, c + 10))
        pygame.draw.rect(surf, (34, 54, 40), (0, 190, W, 80))
        for i in range(0, W, 24):
            pygame.draw.polygon(surf, (28, 46, 38), [(i - 10, 190), (i + 12, 168 + (i * 7) % 18), (i + 34, 190)])
        pygame.draw.rect(surf, (52, 84, 48), (0, 204, W, 66))
        for (x, y) in self.lamps:
            pygame.draw.rect(surf, (36, 34, 44), (x, y - 20, 2, 20))
            glow = 0.6 + 0.4 * math.sin(self.t * 0.07 + x)
            pygame.draw.circle(surf, (255, int(190 + 40 * glow), 100), (x + 1, y - 22), 3)
        f.draw(surf, "VERDANT", (24, 18), (186, 230, 120), (20, 40, 24), scale=5)
        f.draw(surf, "Hollowmere keeps its debts", (28, 64), (255, 244, 205), (30, 40, 24), scale=1)
        draw_panel(surf, pygame.Rect(18, 92, 256, 66), fill=INK, alpha=235)
        self.menu.draw(surf, (24, 98))
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])


# ====================================================================================== game view
class GameScreen(Scene):
    def __init__(self, vs: VerdantScene, intro: bool = False):
        super().__init__(vs.app)
        self.vs = vs
        self.g: Game = vs.game
        self.t = 0
        self.cam = pygame.Vector2(0, 0)
        self.chunks: dict[tuple, pygame.Surface] = {}
        self.chunk_order: list[tuple] = []
        self.lighting = Lighting((W, H), (255, 255, 255), 2)
        self.shake = 0.0
        self.fade = 1.0
        self.banner = ("", 0.0)
        self.prompt: dict | None = None
        self.autosave = 0.0
        self.intro = intro
        self.last_area = ""
        self.mm_base: np.ndarray | None = None
        self.mm_key = None
        self.boss_bar: tuple[str, float] | None = None
        self.sprites_cache: dict = {}

    def on_enter(self, **kw) -> None:
        g = self.g
        self.snap_camera()
        if self.intro:
            self.intro = False
            self.app.scenes.push(TextOverlay(self.app, "Wickering", "You come in off the north road with the last of the daylight and a satchel of nothing in particular. "
                                                                 "A lamp-post stands in the square with its glass hood dark. An old man is looking at it as if it owes him money.\n\n"
                                                                 "Walk with the stick or pad.  A strikes, X rolls, Y fires a bow, B talks to people and uses things.  "
                                                                 "Press SELECT for your pack, quests, map and skills."))
        self.last_area = g.area
        self.set_banner(self.area_name())

    # ------------------------------------------------------------------ helpers
    def area_name(self) -> str:
        g = self.g
        if g.area == "overworld":
            return self.region_name()
        if g.area.startswith("b:"):
            b = g.building_of(g.area)
            return b.label if b and b.label else "Indoors"
        wm = g.wm
        return {"hollow_roots": "The Hollow Roots", "cairn_of_debts": "Cairn of Debts", "drowned_chapel": "The Drowned Crypt",
                "listening_stones": "Beneath the Stones"}.get(g.area[2:], "Below")

    def region_name(self) -> str:
        g = self.g
        x, y = int(g.p.x), int(g.p.y)
        for sid, s in g.over.sites.items():
            if s.hidden:
                continue
            rx, ry, rw, rh = s.rect
            if rx - 2 <= x < rx + rw + 2 and ry - 2 <= y < ry + rh + 2:
                return s.name
        rid = int(g.over.region[min(max(y, 0), g.over.H - 1), min(max(x, 0), g.over.W - 1)])
        return T.REGION_LABEL[T.REGION_NAMES[rid]]

    def set_banner(self, text: str) -> None:
        self.banner = (text, 2.6)

    def snap_camera(self) -> None:
        g = self.g
        self.cam.update(g.p.x * TS - W / 2, g.p.y * TS - H / 2)
        self._clamp_cam()

    def _clamp_cam(self) -> None:
        wm = self.g.wm
        mw, mh = wm.W * TS, wm.H * TS
        self.cam.x = (mw - W) / 2 if mw <= W else clamp(self.cam.x, 0, mw - W)
        self.cam.y = (mh - H) / 2 if mh <= H else clamp(self.cam.y, 0, mh - H)

    def build_intent(self) -> Intent:
        p0 = self.inp.player(0)
        it = Intent()
        mv = p0.move
        it.dx = float(mv.x) if abs(mv.x) > 0.2 else 0.0
        it.dy = float(mv.y) if abs(mv.y) > 0.2 else 0.0
        it.attack = "A" in p0.pressed or "A" in p0.down
        it.roll = "X" in p0.pressed
        it.shoot = "Y" in p0.pressed or "Y" in p0.down
        it.interact = "B" in p0.pressed
        it.cycle = (1 if "R" in p0.pressed else 0) - (1 if "L" in p0.pressed else 0)
        return it

    # ------------------------------------------------------------------ update
    def update(self, dt: float) -> None:
        g = self.g
        self.t += 1
        p0 = self.inp.player(0)
        if "PAUSE" in p0.pressed:
            self.vs.open_pause_menu()
            return
        if "SELECT" in p0.pressed and not g.dead:
            self.app.scenes.push(JournalScreen(self.vs, g))
            return
        if FEEL.hitstop > 0:
            self._after(dt)
            return
        it = self.build_intent()
        if "CONFIRM" in p0.pressed and not it.interact and g.interact_target() and False:
            it.interact = True
        g.last_action = None
        g.update(dt, it)
        self._after(dt)
        act = g.last_action
        if act:
            self.handle_action(act)
        if g.dead:
            self.app.scenes.push(DeathOverlay(self.vs, g))

    def _after(self, dt: float) -> None:
        g = self.g
        for n in g.sfx_queue:
            self.app.audio.play(n, 0.7)
        g.sfx_queue.clear()
        for t in g.toasts:
            self.app.toast(t, BRASS)
        g.toasts.clear()
        for f in list(g.fx):
            if f["k"] == "hitstop":
                FEEL.add_hitstop(f.get("frames", 3))
                g.fx.remove(f)
            elif f["k"] == "hit" and f.get("age", 0) == 0 and f.get("color") == (255, 90, 80):
                self.shake = max(self.shake, 4.0)
        if g.hooks:
            self.vs.drain_hooks()
        if g.area != self.last_area:
            self.last_area = g.area
            self.fade = 1.0
            self.snap_camera()
            self.set_banner(self.area_name())
            self.chunks.clear()
            self.chunk_order.clear()
        else:
            nm = self.area_name() if self.t % 30 == 0 else None
            if nm and nm != self.banner[0] and g.area == "overworld" and self.banner[1] <= 0:
                self.set_banner(nm)
        self.banner = (self.banner[0], max(0.0, self.banner[1] - dt))
        self.fade = max(0.0, self.fade - dt * 3.0)
        self.shake = max(0.0, self.shake - dt * 18)
        # camera
        tx, ty = g.p.x * TS - W / 2, g.p.y * TS - H / 2
        self.cam.x += (tx - self.cam.x) * min(1.0, dt * 9)
        self.cam.y += (ty - self.cam.y) * min(1.0, dt * 9)
        self._clamp_cam()
        self.prompt = g.interact_target() if not g.dead else None
        # audio intensity follows danger and night
        danger = sum(1 for e in g.enemies if not e.dead and e.aggro > 0)
        self.app.audio.set_intensity(min(1.0, 0.25 + 0.12 * danger + (0.2 if g.is_night() else 0.0)))
        self.autosave += dt
        if self.autosave > 45:
            self.autosave = 0
            self.vs.save_game()

    def handle_action(self, act: dict) -> None:
        t = act["type"]
        sc = self.app.scenes
        if t == "talk":
            sc.push(DialogueScreen(self.vs, self.g, act["npc"]))
        elif t == "craft":
            sc.push(CraftScreen(self.vs, self.g, act["station"]))
        elif t == "text":
            sc.push(TextOverlay(self.app, act["title"], act["text"]))
        elif t == "rest":
            sc.push(RestOverlay(self.vs, self.g))
        elif t == "loot":
            pass

    # ------------------------------------------------------------------ drawing
    # TODO(#11): first draw of a chunk costs up to ~38 ms; pre-build neighbouring chunks a few per frame.
    def chunk(self, cx: int, cy: int) -> pygame.Surface:
        g = self.g
        key = (g.area, cx, cy)
        s = self.chunks.get(key)
        if s is None:
            s = art.build_chunk(g.wm, cx, cy, g.area.startswith("b:"))
            self.chunks[key] = s
            self.chunk_order.append(key)
            if len(self.chunk_order) > 48:
                old = self.chunk_order.pop(0)
                self.chunks.pop(old, None)
        return s

    def _ambient(self) -> tuple[int, int, int]:
        g = self.g
        if g.area.startswith("d:"):
            return (44, 44, 72)
        if g.area.startswith("b:"):
            return (236, 220, 196) if not g.wm.dark else (60, 52, 70)
        dl = g.daylight()
        night = (46, 56, 104)
        dusk = (255, 190, 150)
        day = (255, 255, 255)
        if dl >= 1.0:
            return day
        if dl > 0.5:
            return mix(dusk, day, (dl - 0.5) * 2)
        return mix(night, dusk, dl * 2)

    def draw(self, surf: pygame.Surface) -> None:
        g = self.g
        wm = g.wm
        shake = (random.uniform(-1, 1) * self.shake, random.uniform(-1, 1) * self.shake) if self.shake > 0.1 else (0, 0)
        camx, camy = int(self.cam.x + shake[0]), int(self.cam.y + shake[1])
        surf.fill((6, 6, 10))
        cx0, cx1 = max(0, camx // (art.CHUNK * TS)), min((wm.W - 1) // art.CHUNK, (camx + W) // (art.CHUNK * TS))
        cy0, cy1 = max(0, camy // (art.CHUNK * TS)), min((wm.H - 1) // art.CHUNK, (camy + H) // (art.CHUNK * TS))
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                surf.blit(self.chunk(cx, cy), (cx * art.CHUNK * TS - camx, cy * art.CHUNK * TS - camy))
        self._water_shimmer(surf, camx, camy)
        self._hazards(surf, camx, camy)
        night = g.is_night()
        draw_list: list[tuple[float, int, Any]] = []
        x0, x1 = max(0, camx // TS - 1), min(wm.W, (camx + W) // TS + 2)
        y0, y1 = max(0, camy // TS - 1), min(wm.H, (camy + H) // TS + 3)
        sub = wm.obj[y0:y1, x0:x1]
        ys, xs = np.nonzero(sub)
        lights: list[tuple[float, float, int, tuple, float]] = []
        for yy, xx in zip(ys.tolist(), xs.tolist()):
            x, y = x0 + xx, y0 + yy
            oid = int(sub[yy, xx])
            df = T.OBJ_LIST[oid]
            var = T.hash2(x, y) & 7
            if df.name == "chest":
                info = g.chests.get((g.area, x, y))
                opened = bool(info and info["id"] in g.opened)
                sp = self._chest_sprite(opened)
            else:
                sp = art.obj_sprite(oid, var)
            px, py = x * TS - camx, (y + 1) * TS - sp.get_height() - camy
            draw_list.append(((y + 1) * TS - (6 if df.decor else 0), 0, (sp, px, py)))
            if oid in LIGHT_OBJ and df.light:
                rad, col, night_only = df.light
                if not night_only or g.daylight() < 0.75 or g.area != "overworld":
                    lights.append((px + TS / 2, py + sp.get_height() - 8, rad, col, 1.0))
        if g.area == "overworld":
            for b in wm.buildings:
                if b.x * TS - camx > W + 40 or (b.x + b.w) * TS - camx < -40 or b.y * TS - camy > H + 40 or (b.y + b.h) * TS - camy < -40:
                    continue
                door_dx = b.door[0] - b.x
                sp = art.building_sprite(b.style, b.w, b.h, door_dx, night, b.lit and self._building_occupied(b), hash(b.label) & 0xFFFF)
                px, py = b.x * TS - camx, b.y * TS - 6 - camy
                draw_list.append(((b.y + b.h) * TS, 0, (sp, px, py)))
                if night and b.lit and self._building_occupied(b):
                    lights.append((b.door[0] * TS + 8 - camx, (b.y + b.h) * TS - 4 - camy, 36, (255, 190, 110), 0.8))
        # entities
        for st in g.npcs.values():
            if st.area != g.area:
                continue
            sx, sy = st.x * TS - camx, st.y * TS - camy
            if -20 < sx < W + 20 and -20 < sy < H + 20:
                d = st.defn
                fi = self._face_index(st.facing)
                sp = art.person((226, 188, 154), tuple(d.get("color", (160, 160, 160))), tuple(d.get("hair", (90, 60, 40))),
                                fi, int(st.phase) & 3 if st.moving else 0, "lantern" if st.id == "marrow_pell" else "")
                draw_list.append((st.y * TS + 6, 1, (sp, int(sx - 7), int(sy - 15))))
        for e in g.enemies:
            sx, sy = e.x * TS - camx, e.y * TS - camy
            if -40 < sx < W + 40 and -40 < sy < H + 40:
                fi = self._face_index(e.facing)
                sp = art.creature(e.kind, fi, int(e.walk_phase) & 3, int(e.d.get("size", 1.0) * 10), e.flash > 0 or (e.st == "windup" and int(self.t / 3) % 2 == 0), e.guard)
                draw_list.append((e.y * TS + 6, 1, (sp, int(sx - sp.get_width() / 2), int(sy - sp.get_height() + 6))))
                if e.st == "windup" and e.d["ai"] != "boss":
                    draw_list.append((e.y * TS + 7, 2, ("warn", int(sx), int(sy - 18))))
        P = g.p
        sx, sy = P.x * TS - camx, P.y * TS - camy
        pfi = self._face_index(P.facing)
        psp = art.person((232, 190, 156), (40, 126, 130), (96, 60, 40), pfi, int(P.walk_phase) & 3 if P.moving else 0, "lantern" if True else "cloak")
        if P.inv_t > 0 and int(self.t / 3) % 2 == 0 and P.hurt_t > 0:
            psp = art._flash(psp, 0.6)
        bob = 0
        if P.roll_t > 0:
            psp = pygame.transform.rotate(psp, (P.roll_t / 0.28) * 360 * (1 if P.roll_dx >= 0 else -1))
        draw_list.append((P.y * TS + 6, 1, (psp, int(sx - psp.get_width() / 2), int(sy - 15 + bob))))
        for d in g.drops:
            if d.get("area") != g.area:
                continue
            dx, dy = d["x"] * TS - camx, d["y"] * TS - camy
            if -10 < dx < W + 10 and -10 < dy < H + 10:
                col = (255, 214, 90) if d["item"] == "gold" else tuple(g.cat.item(d["item"]).get("color", (230, 230, 230)))
                draw_list.append((d["y"] * TS, 2, ("drop", int(dx), int(dy - 3 - 2 * math.sin(self.t * 0.1 + d["x"])), col)))
        draw_list.sort(key=lambda t: (t[0], t[1]))
        for _, _, item in draw_list:
            if isinstance(item[0], pygame.Surface):
                surf.blit(item[0], (item[1], item[2]))
            elif item[0] == "warn":
                pygame.draw.polygon(surf, (255, 90, 70), [(item[1], item[2] - 4), (item[1] - 3, item[2] + 2), (item[1] + 3, item[2] + 2)])
                pygame.draw.rect(surf, (255, 90, 70), (item[1] - 1, item[2] - 8, 2, 3))
            elif item[0] == "drop":
                pygame.draw.circle(surf, item[3], (item[1], item[2]), 3)
                pygame.draw.circle(surf, (255, 255, 255), (item[1] - 1, item[2] - 1), 1)
        self._overlay_fx(surf, camx, camy)
        # harvest / attack arcs
        self._attack_arc(surf, camx, camy)
        # lighting
        amb = self._ambient()
        if amb != (255, 255, 255):
            self.lighting.ambient = amb
            self.lighting.clear()
            dark = g.wm.dark or g.area.startswith("d:") or g.is_night()
            self.lighting.add((sx, sy - 6), 92 if dark else 46, (255, 214, 150), 0.85 if dark else 0.35)
            for (lx, ly, rad, col, k) in lights:
                self.lighting.add((lx, ly), int(rad * 1.5), col, k)
            for e in g.enemies:
                if e.kind == "root_mother":
                    self.lighting.add((e.x * TS - camx, e.y * TS - camy - 6), 52, (255, 150, 70), 0.9)
            for pj in g.projectiles:
                self.lighting.add((pj.x * TS - camx, pj.y * TS - camy), 22, (255, 220, 150) if pj.friendly else (200, 140, 255), 0.7)
            self.lighting.apply(surf)
        # floating text
        f = self.app.font
        for tx in g.texts:
            a = tx["age"]
            f.draw(surf, tx["t"], (int(tx["x"] * TS - camx), int(tx["y"] * TS - camy - a * 18)), tx["c"], (10, 8, 16), anchor="midtop")
        self._hud(surf, camx, camy)
        if self.fade > 0:
            ov = pygame.Surface((W, H))
            ov.set_alpha(int(255 * self.fade))
            surf.blit(ov, (0, 0))
        FEEL.draw_flash(surf)

    # ------------------------------------------------------------------ draw helpers
    def _building_occupied(self, b) -> bool:
        return True

    @staticmethod
    def _face_index(angle: float) -> int:
        a = angle % 360
        if 45 <= a < 135:
            return 0
        if 135 <= a < 225:
            return 1
        if 225 <= a < 315:
            return 3
        return 2

    def _chest_sprite(self, opened: bool) -> pygame.Surface:
        key = ("chest", opened)
        s = self.sprites_cache.get(key)
        if s is None:
            s = art.obj_sprite(T.O["chest"], 0).copy()
            if opened:
                pygame.draw.rect(s, (40, 26, 20), (3, 5, 10, 4))
                pygame.draw.rect(s, (110, 74, 44), (2, 2, 12, 3))
            self.sprites_cache[key] = s
        return s

    def _water_shimmer(self, surf: pygame.Surface, camx: int, camy: int) -> None:
        g = self.g
        if g.area != "overworld":
            return
        wm = g.wm
        x0, x1 = max(0, camx // TS), min(wm.W, camx // TS + 31)
        y0, y1 = max(0, camy // TS), min(wm.H, camy // TS + 18)
        sub = wm.ground[y0:y1, x0:x1]
        ys, xs = np.nonzero((sub == T.SHALLOW) | (sub == T.DEEP))
        t = self.t
        for yy, xx in zip(ys.tolist()[::2], xs.tolist()[::2]):
            x, y = x0 + xx, y0 + yy
            h = T.hash2(x, y, 5)
            ph = (t * 0.04 + (h & 15)) % 6
            if ph < 1.2:
                sx = x * TS - camx + (h >> 4) % 10
                sy = y * TS - camy + (h >> 8) % 12
                pygame.draw.line(surf, (200, 228, 245), (sx, sy), (sx + 3, sy))

    def _hazards(self, surf: pygame.Surface, camx: int, camy: int) -> None:
        g = self.g
        for h in g.hazards:
            if h.area != g.area:
                continue
            cx, cy = int(h.x * TS - camx), int(h.y * TS - camy)
            if h.kind == "circle":
                if h.t > 0:
                    k = 1.0 - h.t / max(0.05, h.dur)
                    r = int(h.r * TS)
                    ov = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.circle(ov, (255, 70, 60, int(40 + 70 * k)), (r + 2, r + 2), r)
                    pygame.draw.circle(ov, (255, 140, 110, 200), (r + 2, r + 2), r, 1)
                    pygame.draw.circle(ov, (255, 90, 70, 150), (r + 2, r + 2), int(r * k))
                    surf.blit(ov, (cx - r - 2, cy - r - 2))
            else:
                if h.t >= 0:
                    r = int(h.r * TS * min(1.0, h.t / h.dur))
                    if r > 2:
                        pygame.draw.circle(surf, (255, 230, 150), (cx, cy), r, 3)
                        pygame.draw.circle(surf, (255, 150, 90), (cx, cy), max(1, r - 3), 1)

    def _overlay_fx(self, surf: pygame.Surface, camx: int, camy: int) -> None:
        g = self.g
        for f in g.fx:
            age = f.get("age", 0.0)
            life = f.get("life", 0.5)
            k = age / life if life else 1.0
            x, y = int(f["x"] * TS - camx), int(f["y"] * TS - camy)
            kind = f["k"]
            if kind == "hit":
                col = f.get("color", (255, 255, 255))
                for i in range(6):
                    a = i * 1.05 + age * 3
                    pygame.draw.line(surf, col, (x, y - 4), (x + int(math.cos(a) * (3 + 10 * k)), y - 4 + int(math.sin(a) * (3 + 10 * k))))
            elif kind == "poof":
                col = f.get("color", (200, 200, 200))
                for i in range(8):
                    a = i * 0.8 + 0.4
                    pygame.draw.circle(surf, col, (x + int(math.cos(a) * 14 * k), y - 4 + int(math.sin(a) * 10 * k - 8 * k)), max(1, int(3 * (1 - k))))
            elif kind == "spark":
                for i in range(4):
                    a = i * 1.57
                    pygame.draw.line(surf, (240, 250, 255), (x, y), (x + int(math.cos(a) * 7 * (1 - k)), y + int(math.sin(a) * 7 * (1 - k))))
            elif kind == "boom":
                r = int(f.get("r", 1.5) * TS * (0.6 + 0.6 * k))
                pygame.draw.circle(surf, (255, 200, 130), (x, y), r, 2)
            elif kind == "glow":
                pygame.draw.circle(surf, (255, 230, 150), (x, y - 18), int(6 + 14 * k), 1)
        for pj in g.projectiles:
            px, py = int(pj.x * TS - camx), int(pj.y * TS - camy)
            if pj.friendly or pj.kind == "arrow":
                n = math.hypot(pj.vx, pj.vy) or 1
                pygame.draw.line(surf, (230, 220, 190), (px, py), (px - int(pj.vx / n * 7), py - int(pj.vy / n * 7)))
                pygame.draw.circle(surf, (250, 250, 250), (px, py), 1)
            else:
                pygame.draw.circle(surf, (190, 120, 255), (px, py), 3)
                pygame.draw.circle(surf, (240, 220, 255), (px, py), 1)

    def _attack_arc(self, surf: pygame.Surface, camx: int, camy: int) -> None:
        g = self.g
        P = g.p
        if P.atk_t <= 0:
            return
        w = g.weapon()
        k = 1.0 - P.atk_t / max(0.01, P.atk_total)
        reach = float(w.get("reach", 1.4)) * TS
        base = math.radians(P.facing)
        sweep = math.radians(130)
        a0 = base - sweep / 2 + sweep * min(1.0, k * 1.4)
        cx, cy = int(P.x * TS - camx), int(P.y * TS - camy - 4)
        for i in range(6):
            a = a0 - i * 0.12
            col = (255, 255, 255) if i < 2 else (200, 220, 240)
            pygame.draw.line(surf, col, (cx + int(math.cos(a) * 5), cy + int(math.sin(a) * 5)),
                             (cx + int(math.cos(a) * reach), cy + int(math.sin(a) * reach)), 1 if i else 2)

    # ------------------------------------------------------------------ HUD
    def _bar(self, surf, x, y, w, h, frac, col, back=(30, 24, 36), edge=(10, 8, 16)):
        pygame.draw.rect(surf, edge, (x - 1, y - 1, w + 2, h + 2))
        pygame.draw.rect(surf, back, (x, y, w, h))
        pygame.draw.rect(surf, col, (x, y, int(w * clamp(frac)), h))
        pygame.draw.line(surf, mix(col, (255, 255, 255), 0.4), (x, y), (x + int(w * clamp(frac)) - 1, y))

    def _hud(self, surf: pygame.Surface, camx: int, camy: int) -> None:
        g = self.g
        P = g.p
        f = self.app.font
        hp = min(P.hp, g.max_hp())
        self._bar(surf, 8, 8, 96, 8, hp / g.max_hp(), (214, 70, 70))
        f.draw(surf, f"{int(hp)}/{int(g.max_hp())}", (108, 8), PARCHMENT, (10, 8, 16))
        self._bar(surf, 8, 19, 76, 4, P.stamina / 100, (110, 200, 120))
        if P.fever:
            f.draw(surf, "FEVER", (8, 26), (150, 230, 110), (10, 8, 16))
        f.draw(surf, f"{P.gold}g", (8, 36 if P.fever else 28), (255, 220, 100), (10, 8, 16))
        # clock
        tt = g.time_text()
        f.draw(surf, tt, (W - 8, 6), PARCHMENT, (10, 8, 16), anchor="topright")
        dl = g.daylight()
        sunx = W - 100
        if g.area == "overworld":
            pygame.draw.circle(surf, (255, 220, 120) if dl > 0.3 else (190, 200, 240), (sunx, 10), 4)
            if dl <= 0.3:
                pygame.draw.circle(surf, (20, 24, 46), (sunx + 2, 9), 3)
        # minimap (overworld)
        if g.area == "overworld":
            self._minimap(surf)
        # quest target marker
        self._quest_marker(surf, camx, camy)
        # quest tracker
        qs = g.quests.active_ids()
        y = 42
        if qs:
            q = g.cat.quest(qs[0])
            f.draw(surf, q["title"], (8, y), BRASS, (10, 8, 16))
            txt = g.quests.progress_text(g, qs[0])
            f.draw_wrapped(surf, txt, pygame.Rect(8, y + 10, 150, 40), (232, 226, 206), (10, 8, 16), max_lines=3)
        # equipment strip
        by = H - 22
        w = g.weapon()
        surf.blit(art.icon("weapon", tuple(w.get("color", (200, 200, 200))), 12), (8, by))
        f.draw(surf, w["name"], (24, by + 2), PARCHMENT, (10, 8, 16))
        bow = g.bow()
        if bow:
            surf.blit(art.icon("ammo", (230, 220, 190), 12), (120, by))
            f.draw(surf, f"{g.count('arrow')}", (136, by + 2), PARCHMENT if g.count("arrow") else DANGER, (10, 8, 16))
        if P.quick:
            qd = g.cat.item(P.quick)
            surf.blit(art.icon("consumable", tuple(qd.get("color", (200, 200, 200))), 12), (170, by))
            f.draw(surf, f"{qd['name']} x{g.count(P.quick)}", (186, by + 2), PARCHMENT, (10, 8, 16))
        # prompt
        if self.prompt and not g.dead and not g.player_locked:
            pl = self.inp.player(0)
            txt = f"[{pl.prompt('B')}] {self.prompt['label']}"
            tw = f.width(txt)
            r = pygame.Rect(W // 2 - tw // 2 - 6, H - 40, tw + 12, 14)
            draw_panel(surf, r, fill=INK, alpha=215)
            f.draw(surf, txt, (r.x + 6, r.y + 3), (255, 244, 205), None)
        if P.gather:
            fr = P.gather["t"] / max(0.01, P.gather["need"])
            self._bar(surf, W // 2 - 20, H // 2 + 14, 40, 4, fr, (160, 230, 150))
        # boss bar
        boss = next((e for e in g.enemies if e.d["ai"] == "boss" and not e.dead and e.aggro > 0), None)
        if boss:
            bw = 220
            self._bar(surf, W // 2 - bw // 2, 20, bw, 6, boss.hp / boss.maxhp, (200, 80, 90))
            f.draw(surf, boss.d["name"], (W // 2, 8), PARCHMENT, (10, 8, 16), anchor="midtop")
        # banner
        txt, t = self.banner
        if t > 0 and txt:
            a = min(1.0, t / 0.6, (2.6 - t) / 0.4 + 0.01)
            img = f.render(txt, (255, 244, 205), (20, 14, 8), scale=2)
            img.set_alpha(int(255 * clamp(a)))
            surf.blit(img, (W // 2 - img.get_width() // 2, 52))

    def _minimap(self, surf: pygame.Surface) -> None:
        g = self.g
        key = (g.seed, g.discovered.sum() // 40)
        if self.mm_key != key or self.mm_base is None:
            img = np.zeros((g.over.H, g.over.W, 3), dtype=np.uint8)
            for gid, (col, _) in art.GROUND_STYLE.items():
                img[g.over.ground == gid] = col
            self.mm_base = img
            self.mm_key = key
        R = 24
        px, py = int(g.p.x), int(g.p.y)
        x0, y0 = max(0, min(g.over.W - 2 * R, px - R)), max(0, min(g.over.H - 2 * R, py - R))
        crop = self.mm_base[y0:y0 + 2 * R, x0:x0 + 2 * R].copy()
        disc = g.discovered[y0:y0 + 2 * R, x0:x0 + 2 * R]
        crop[~disc] = (18, 18, 26)
        s = pygame.surfarray.make_surface(crop.swapaxes(0, 1))
        s = pygame.transform.scale(s, (R * 4, R * 4))
        r = pygame.Rect(W - 8 - R * 4, 36, R * 4, R * 4)
        surf.blit(s, r.topleft)
        pygame.draw.rect(surf, BRASS, r.inflate(2, 2), 1)
        for sid, st in g.over.sites.items():
            if st.hidden or sid not in g.known_sites:
                continue
            fx, fy = st.front
            if x0 <= fx < x0 + 2 * R and y0 <= fy < y0 + 2 * R:
                pygame.draw.rect(surf, (255, 255, 255) if st.kind == "settlement" else (255, 140, 100), (r.x + (fx - x0) * 2 - 1, r.y + (fy - y0) * 2 - 1, 3, 3))
        qs = g.quests.active_ids()
        tgt = g.quests.target_pos(g, qs[0]) if qs else None
        if tgt and tgt[0] == g.area and tgt is not None:
            tx, ty = int(tgt[1]), int(tgt[2])
            if x0 <= tx < x0 + 2 * R and y0 <= ty < y0 + 2 * R:
                pygame.draw.rect(surf, (10, 8, 16), (r.x + (tx - x0) * 2 - 2, r.y + (ty - y0) * 2 - 2, 5, 5))
                pygame.draw.rect(surf, BRASS, (r.x + (tx - x0) * 2 - 1, r.y + (ty - y0) * 2 - 1, 3, 3))
            else:
                mx, my = clamp(tx, x0, x0 + 2 * R), clamp(ty, y0, y0 + 2 * R)
                pygame.draw.circle(surf, BRASS, (r.x + (mx - x0) * 2, r.y + (my - y0) * 2), 2, 1)
        pygame.draw.rect(surf, (255, 240, 120), (r.x + (px - x0) * 2 - 1, r.y + (py - y0) * 2 - 1, 3, 3))

    @staticmethod
    def _hud_avoid(sx: float, sy: float) -> tuple[float, float]:
        """Keep an edge chevron clear of HUD furniture (tracker, minimap, boss bar, bottom strip)."""
        rects = [pygame.Rect(0, 40, 172, 56),                     # quest tracker
                 pygame.Rect(W - 106, 34, 108, 102),              # minimap inset
                 pygame.Rect(W // 2 - 112, 6, 224, 24),           # boss bar
                 pygame.Rect(0, H - 26, W, 26)]                   # equipment strip
        for r in rects:
            if r.collidepoint(sx, sy):
                pen = [sx - r.left, r.right - sx, sy - r.top, r.bottom - sy]
                m = min(range(4), key=lambda i: pen[i])
                if m == 0:
                    sx = r.left - 6
                elif m == 1:
                    sx = min(r.right + 6, W - 12)
                    if r.collidepoint(sx, sy):        # pushed past the screen: slide inside instead
                        sx = r.left - 6
                elif m == 2:
                    sy = r.top - 6
                else:
                    sy = min(r.bottom + 6, H - 32)
                    if r.collidepoint(sx, sy):
                        sy = r.top - 6
        return clamp(sx, 12, W - 12), clamp(sy, 20, H - 32)

    def _quest_marker(self, surf: pygame.Surface, camx: int, camy: int) -> None:
        """A bobbing chevron over the active quest's target, or an edge chevron pointing at it."""
        g = self.g
        qs = g.quests.active_ids()
        tgt = g.quests.target_pos(g, qs[0]) if qs else None
        if tgt is None or tgt[0] != g.area:
            return
        sx, sy = tgt[1] * TS - camx, tgt[2] * TS - camy
        px, py = g.p.x * TS - camx, g.p.y * TS - camy
        dirx, diry = sx - px, sy - py
        n = math.hypot(dirx, diry)
        if n < 1:
            return
        dirx, diry = dirx / n, diry / n
        bob = math.sin(self.t * 5.0) * 1.5
        if 8 <= sx < W - 8 and 26 <= sy < H - 28:
            sx, sy = self._hud_avoid(sx, sy)     # never under the tracker / minimap / boss bar
            cy = sy + bob                    # chevron hovers over the spot
        else:
            s = min((W / 2 - 10) / max(1e-9, abs(sx - W / 2)), (H / 2 - 16) / max(1e-9, abs(sy - H / 2)), 1.0)
            sx, sy = W / 2 + (sx - W / 2) * s, H / 2 + (sy - H / 2) * s
            sx, sy = self._hud_avoid(sx, sy)
            cy = sy
        side = 3.6
        bx, by = -diry * side, dirx * side
        tail = (sx - dirx * 5, cy - diry * 5)
        tri = [(sx, cy), (tail[0] + bx, tail[1] + by), (tail[0] - bx, tail[1] - by)]
        pygame.draw.polygon(surf, (14, 10, 22), tri)
        pygame.draw.polygon(surf, BRASS, tri, 1)


# screens are defined in screens.py; imported lazily to keep this module readable
from .screens import CraftScreen, DeathOverlay, DialogueScreen, JournalScreen, RestOverlay, TextOverlay  # noqa: E402
