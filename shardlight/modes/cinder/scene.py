"""Cinder scene: foot of the Spire (menu, ledger, setup), the run itself, reward/forge overlays and end screens."""
from __future__ import annotations

import math
import random
from typing import Any

import pygame

from ...core import art as core_art
from ...core.fx import FEEL, FloatingTexts, Lighting, ParticleSystem, clamp, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Dialogue, Menu, MenuItem, MenuScene,
                        SettingsScene, ControlsScene, draw_panel, draw_prompts)
from . import art
from .defs import Library
from .info import INFO
from .sim import levelgen as LG
from .sim.bosses import make_boss
from .sim.entities import ENEMY_TEAM
from .sim.player import Intent
from .sim.room import H_PX, W_PX, Room
from .sim.run import Difficulty, Run
from .sim.status import STATUS_COLORS

W, H = 480, 270
OX, OY = 16, 26
SAVE_V = 1
FLOORS = 7
STARTER = ("ember_blade", "ember_caster")
TAG_COLORS = {"fire": (255, 130, 60), "ash": (180, 176, 196), "shock": (255, 236, 120), "status": (214, 120, 150),
              "ranged": (120, 200, 255), "defense": (110, 200, 150), "mobility": (150, 230, 220), "parry": (255, 255, 255),
              "offense": (255, 90, 80), "heavy": (230, 170, 110), "synergy": (200, 140, 255), "economy": (255, 214, 110),
              "melee": (220, 190, 160), "flare": (255, 200, 120)}


def make_intent(app, p, toggle_state: dict) -> Intent:
    it = Intent()
    it.move = (p.move.x, p.move.y)
    it.aim = (p.aim.x, p.aim.y)
    pressed = set()
    held = set()
    if "A" in p.pressed:
        pressed.add("attack")
    if "A" in p.down:
        held.add("attack")
    if app.settings.get("access.toggle_hold"):
        if "X" in p.pressed:
            toggle_state["heavy"] = not toggle_state.get("heavy", False)
        if toggle_state.get("heavy"):
            held.add("heavy")
            pressed.add("heavy") if "X" in p.pressed else None
    else:
        if "X" in p.pressed:
            pressed.add("heavy")
        if "X" in p.down:
            held.add("heavy")
    if "B" in p.pressed:
        pressed.add("dodge")
    if "Y" in p.pressed:
        pressed.add("parry")
    if "Y" in p.down:
        held.add("parry")
    if "R" in p.pressed:
        pressed.add("interact")
    if "L" in p.pressed:
        pressed.add("flare")
    it.pressed = pressed
    it.held = held
    it.aim_assist = bool(app.settings.get("access.aim_assist"))
    return it


class CinderScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.lib: Library | None = None
        self.screen: Scene | None = None
        self.opt_seed = opts.get("seed", "random")
        self.t = 0
        self.fonts = app.font

    # ------------------------------------------------------------------ lifecycle
    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("soot", 0)
        d.setdefault("unlocked", {"weapons": [], "boons": [], "mods": []})
        d.setdefault("best_floor", 0)
        d.setdefault("runs", 0)
        d.setdefault("wins", 0)
        d.setdefault("heat_best", 0)
        d.setdefault("seen", {})
        d.setdefault("last_mods", [])
        d.setdefault("weapon", "ember_blade")
        d.setdefault("evolved", [])
        self.lib = Library(self.app.content)
        self.app.audio.play_music("cinder", 1.0, 0.25)
        self.show_foot()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, RunScreen):
            self.screen.pause()

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_foot(self) -> None:
        self.app.audio.set_intensity(0.2)
        self.set_screen(FootScreen(self))

    # ------------------------------------------------------------------ meta helpers
    def unlocked_sets(self) -> dict:
        u = self.data["unlocked"]
        w = self.app.world
        flags = {k for k in ("choir",) if w.has_unlock("cinder.boss.choir_warden")}
        return {"boons": set(u["boons"]), "weapons": set(u["weapons"]) | {x.id for x in self.lib.weapons.values() if x.unlock_cost == 0},
                "mods": set(u["mods"]) | {m.id for m in self.lib.mods.values() if m.unlock_cost == 0}, "flags": flags}

    def seed(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        return random.Random(self.app.rng.randrange(1 << 30)).randrange(1000, 999999)

    def begin_run(self, weapon_id: str, mod_ids: list[str]) -> None:
        mods = [self.lib.mods[m] for m in mod_ids if m in self.lib.mods]
        diff = Difficulty.preset(self.app.settings.get("difficulty.preset"))
        run = Run(self.lib, self.seed(), weapon_id, mods, diff, float(self.app.settings.get("difficulty.adaptive_ai")))
        self.data["weapon"] = weapon_id
        self.data["last_mods"] = list(mod_ids)
        self.data["runs"] += 1
        self.set_screen(RunScreen(self, run))


# ====================================================================================== foot of the spire
class FootScreen(Scene):
    def __init__(self, cs: CinderScene):
        super().__init__(cs.app)
        self.cs = cs
        self.t = 0
        items = [MenuItem("Climb the Spire", lambda: cs.set_screen(SetupScreen(cs))),
                 MenuItem("Ledger of Soot", lambda: cs.set_screen(LedgerScreen(cs))),
                 MenuItem("Return to hub", lambda: cs.finish(left=True))]
        self.menu = Menu(self.app, items, 170)
        self.embers = [[random.random() * W, random.random() * H, random.random()] for _ in range(60)]

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
        if "BACK" in self.inp.player(0).pressed and self.t > 10:
            self.cs.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(art.CHAR)
        core_art.dither_vertical(surf, pygame.Rect(0, 0, W, H), (20, 14, 26), (52, 24, 28))
        t = self.t
        # the spire: a jagged tower silhouette lit from below
        cx = 350
        pts = [(cx - 40, H), (cx - 30, 170), (cx - 22, 120), (cx - 28, 70), (cx - 10, 30), (cx, 8), (cx + 10, 30), (cx + 28, 70),
               (cx + 22, 120), (cx + 30, 170), (cx + 40, H)]
        pygame.draw.polygon(surf, (10, 8, 16), pts)
        pygame.draw.polygon(surf, (70, 40, 50), pts, 1)
        for i in range(7):
            yy = 190 - i * 24
            pygame.draw.rect(surf, (255, 130, 60) if (i + t // 20) % 3 else (255, 200, 120), (cx - 3, yy, 6, 8))
        core_art.dither_vertical(surf, pygame.Rect(0, H - 60, W, 60), (30, 14, 20), (255, 110, 50))
        for e in self.embers:
            e[1] -= 0.3 + e[2] * 0.6
            e[0] += math.sin(t * 0.03 + e[2] * 9) * 0.3
            if e[1] < 0:
                e[1] = H
            surf.fill((255, 180 + int(e[2] * 60), 90), (int(e[0]), int(e[1]), 1, 1))
        f = self.app.font
        f.draw(surf, "CINDER", (24, 18), art.GOLD, (40, 10, 10), scale=5)
        f.draw(surf, "the spire that rebuilds itself", (26, 62), art.EMBER, (30, 8, 8))
        draw_panel(surf, pygame.Rect(20, 92, 190, 66), fill=INK, alpha=225)
        self.menu.draw(surf, (26, 98))
        d = self.cs.data
        f.draw(surf, f"Soot {d['soot']}   Best floor {d['best_floor']}/{FLOORS}", (24, 168), PARCHMENT, (10, 6, 12))
        f.draw(surf, f"Climbs {d['runs']}   Summits {d['wins']}   Heat record {d['heat_best']}", (24, 180), DIM, (10, 6, 12))
        if self.app.world.has_unlock("cinder.boss.choir_warden"):
            f.draw(surf, "A door sings on floors 2 and 4 (Choir Warden)", (24, 196), LENS, (10, 6, 12))
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])


class SetupScreen(Scene):
    def __init__(self, cs: CinderScene):
        super().__init__(cs.app)
        self.cs = cs
        self.t = 0
        un = cs.unlocked_sets()
        self.weapons = [w for w in cs.lib.starter_weapons() if w.id in un["weapons"]]
        self.mods = [m for m in cs.lib.mods.values() if m.id in un["mods"]]
        self.mods.sort(key=lambda m: (m.heat, m.id))
        self.wi = max(0, [w.id for w in self.weapons].index(cs.data["weapon"])) if cs.data["weapon"] in [w.id for w in self.weapons] else 0
        self.mi = 0
        self.chosen = {m for m in cs.data["last_mods"] if m in {x.id for x in self.mods}}
        self.row = 0          # 0 weapon, 1 mods, 2 start

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        dx, dy = p.menu_dir()
        if dy:
            self.row = (self.row + dy) % 3
        if self.row == 0 and dx:
            self.wi = (self.wi + dx) % len(self.weapons)
        if self.row == 1 and self.mods:
            if dx:
                self.mi = (self.mi + dx) % len(self.mods)
        if self.t < 6:
            return
        if "CONFIRM" in p.pressed or "A" in p.pressed:
            if self.row == 1 and self.mods:
                m = self.mods[self.mi].id
                self.chosen.symmetric_difference_update({m})
            elif self.row == 2 or self.row == 0:
                self.cs.begin_run(self.weapons[self.wi].id, sorted(self.chosen))
        if "BACK" in p.pressed:
            self.cs.show_foot()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        surf.fill(art.CHAR)
        core_art.dither_vertical(surf, pygame.Rect(0, 0, W, H), (20, 14, 26), (40, 20, 26))
        f.draw(surf, "PREPARE THE CLIMB", (16, 8), art.GOLD, (30, 8, 8), scale=2)
        w = self.weapons[self.wi]
        r = pygame.Rect(16, 32, 448, 76)
        draw_panel(surf, r, border=w.color if self.row == 0 else DIM, fill=INK, alpha=240, title="WEAPON", font=f)
        f.draw(surf, f"< {w.name} >", (r.x + 12, r.y + 12), (255, 238, 200), None, scale=2)
        f.draw(surf, w.family.upper(), (r.right - 10, r.y + 12), w.color, None, anchor="topright")
        f.draw_wrapped(surf, w.desc, pygame.Rect(r.x + 12, r.y + 32, r.w - 24, 22), PARCHMENT, None, max_lines=2)
        light = ", ".join(m.name for m in w.light)
        f.draw(surf, f"Light: {light}", (r.x + 12, r.y + 52), DIM, None)
        f.draw(surf, "Heavy: " + ", ".join(t.move.name for t in w.heavy), (r.x + 12, r.y + 62), DIM, None)
        r2 = pygame.Rect(16, 116, 448, 106)
        heat = sum(m.heat for m in self.mods if m.id in self.chosen)
        draw_panel(surf, r2, border=art.EMBER if self.row == 1 else DIM, fill=INK, alpha=240, title=f"HEAT {heat}", font=f)
        if not self.mods:
            f.draw(surf, "No modifiers unlocked yet.", (r2.x + 12, r2.y + 14), DIM, None)
        cols = 2
        per = 7
        start = max(0, min(self.mi - per // 2, len(self.mods) - per * cols)) // cols * cols
        for k, m in enumerate(self.mods[start:start + per * cols]):
            i = start + k
            cx = r2.x + 10 + (k % cols) * 220
            cy = r2.y + 12 + (k // cols) * 12
            on = m.id in self.chosen
            sel = self.row == 1 and i == self.mi
            if sel:
                pygame.draw.rect(surf, INK_2, (cx - 2, cy - 2, 214, 12))
            pygame.draw.rect(surf, art.EMBER if on else (60, 50, 70), (cx, cy, 7, 7))
            f.draw(surf, f"{m.name}", (cx + 11, cy), (255, 238, 200) if sel else PARCHMENT, None)
            f.draw(surf, f"+{m.heat}", (cx + 206, cy), art.GOLD, None, anchor="topright")
        if self.mods:
            m = self.mods[self.mi]
            f.draw(surf, m.desc, (r2.x + 10, r2.bottom - 12), DIM, None)
        start_r = pygame.Rect(16, 230, 448, 22)
        draw_panel(surf, start_r, border=art.GOLD if self.row == 2 else DIM, fill=INK, alpha=240)
        f.draw(surf, "BEGIN CLIMB", (start_r.centerx, start_r.y + 7), (255, 238, 200) if self.row == 2 else PARCHMENT, None, anchor="midtop")
        draw_prompts(surf, self.app, [("UP", "Row"), ("LEFT", "Change"), ("CONFIRM", "Toggle / Begin"), ("BACK", "Back")])


class LedgerScreen(Scene):
    def __init__(self, cs: CinderScene):
        super().__init__(cs.app)
        self.cs = cs
        self.sel = 0
        self.t = 0
        self.msg = ""

    def rows(self):
        un = self.cs.data["unlocked"]
        out = []
        for kind, uid, name, cost in self.cs.lib.unlockables():
            key = {"weapon": "weapons", "boon": "boons", "mod": "mods"}[kind]
            out.append((kind, uid, name, cost, uid in un[key]))
        return out

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        rows = self.rows()
        _, dy = p.menu_dir()
        if dy and rows:
            self.sel = (self.sel + dy) % len(rows)
        if self.t < 6:
            return
        if "CONFIRM" in p.pressed and rows:
            kind, uid, name, cost, owned = rows[self.sel]
            d = self.cs.data
            if owned:
                self.msg = "Already yours."
            elif d["soot"] >= cost:
                d["soot"] -= cost
                d["unlocked"][{"weapon": "weapons", "boon": "boons", "mod": "mods"}[kind]].append(uid)
                self.msg = f"Unlocked {name}"
                self.app.audio.play("unlock", 0.9)
            else:
                self.msg = "Not enough soot."
                self.app.audio.play("ui_error", 0.7)
        if "BACK" in p.pressed:
            self.app.save_now()
            self.cs.show_foot()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        surf.fill(art.CHAR)
        core_art.dither_vertical(surf, pygame.Rect(0, 0, W, H), (20, 14, 26), (44, 24, 30))
        f.draw(surf, "LEDGER OF SOOT", (16, 8), art.GOLD, (30, 8, 8), scale=2)
        f.draw(surf, f"Soot {self.cs.data['soot']}", (W - 16, 12), PARCHMENT, None, anchor="topright", scale=2)
        draw_panel(surf, pygame.Rect(16, 34, 448, 190), fill=INK, alpha=240)
        f.draw(surf, "Unlocks add options to the pool - they never add raw power.", (26, 40), DIM, None)
        rows = self.rows()
        per = 14
        start = max(0, min(self.sel - per // 2, len(rows) - per))
        for k, (kind, uid, name, cost, owned) in enumerate(rows[start:start + per]):
            y = 56 + k * 11
            sel = start + k == self.sel
            if sel:
                pygame.draw.rect(surf, INK_2, (22, y - 2, 436, 11))
            f.draw(surf, kind, (28, y), DIM, None)
            f.draw(surf, name, (80, y), (255, 238, 200) if sel else PARCHMENT, None)
            f.draw(surf, "owned" if owned else f"{cost} soot", (452, y), GOOD if owned else art.GOLD, None, anchor="topright")
        if self.msg:
            f.draw(surf, self.msg, (W // 2, 232), LENS, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Unlock"), ("BACK", "Back")])


# ====================================================================================== the run
class RunScreen(Scene):
    def __init__(self, cs: CinderScene, run: Run):
        super().__init__(cs.app)
        self.cs = cs
        self.run = run
        self.lib = cs.lib
        self.plan: LG.FloorPlan | None = None
        self.room: Room | None = None
        self.bg: pygame.Surface | None = None
        self.room_stack: list[tuple[Room, int]] = []
        self.parts = ParticleSystem(1200, random.Random(run.seed))
        self.floats = FloatingTexts()
        self.light = Lighting((W, H), ambient=(138, 112, 150), downscale=2)
        self.trauma = 0.0
        self.toggle = {}
        self.t = 0
        self.fade = 1.0
        self.pending: tuple | None = None
        self.paused = False
        self.tip = ""
        self.tip_t = 0
        self.banner = ""
        self.banner_t = 0
        self.over = False
        self.floor_vis: set[int] = set()
        self.last_cause = ""
        self.hit_flash = 0
        self.debug_lines: list[str] = []

    # ------------------------------------------------------------------ floors and rooms
    def _admin_aim_target(self, room):
        """Nearest living enemy, used by the admin aimbot."""
        best, bd = None, 1e9
        p = getattr(room, "player", None)
        if p is None:
            return None
        for e in getattr(room, "enemies", ()):  # type: ignore[arg-type]
            if not getattr(e, "alive", False):
                continue
            d = (e.x - p.x) ** 2 + (e.y - p.y) ** 2
            if d < bd:
                best, bd = e, d
        return best

    def on_enter(self, **kw) -> None:
        self.app.input.assign_local(1)
        self.start_floor(1)
        d = self.cs.data["seen"]
        if not d.get("intro"):
            d["intro"] = True
            self.app.scenes.push(Dialogue(self.app, [
                ("Lampwright", "The Spire rebuilds itself every time it is climbed. So I will climb it again."),
                ("Guide", "J / A strikes. Hold X to charge a heavy. B rolls through danger. Y parries - time it to a white spark."),
            ], color=art.EMBER))

    def start_floor(self, floor: int) -> None:
        run = self.run
        run.floor = floor
        choir = self.app.world.has_unlock("cinder.boss.choir_warden")
        self.plan = LG.generate_floor(self.lib, run.seed, floor, run.mods, choir, secrets=True)
        self.floor_vis = {self.plan.start}
        self.enter_room(self.plan.start, None)
        self.banner = f"FLOOR {floor}"
        self.banner_t = 120
        self.app.audio.play("cinder_floor", 0.8)

    def enter_room(self, rid: int, entry: str | None, spec: LG.RoomSpec | None = None) -> None:
        run = self.run
        spec = spec or self.plan.rooms[rid]
        spec.visited = True
        self.floor_vis.add(rid)
        prev_hp = self.room.player.hp if self.room else run.hp
        run.hp = prev_hp
        factory = make_boss(spec.boss) if spec.kind == "boss" else None
        self.room = Room(run, spec, run.floor, self.cs.unlocked_sets(), entry, boss_factory=factory)
        self.bg = art.bake_room(spec, run.floor)
        self.parts.items.clear()
        self.fade = 1.0
        run.room_no += 1
        self.tip_for_room(spec)
        self.app.audio.set_intensity(0.55 if spec.kind in ("arena", "elite") else 0.95 if spec.kind == "boss" else 0.3)

    def tip_for_room(self, spec: LG.RoomSpec) -> None:
        seen = self.cs.data["seen"]
        def tip(key, text):
            if not seen.get(key):
                seen[key] = True
                self.tip, self.tip_t = text, 420
        if spec.kind == "start" and self.run.floor == 1:
            tip("tip_move", "Move with WASD / left stick. Strike with J / A. Walk through an open doorway to enter the next room.")
        elif spec.kind in ("arena", "elite"):
            tip("tip_dodge", "Enemies telegraph every attack in red. Roll (B) just as the red fills in to slip through it.")
        elif spec.kind == "reward":
            tip("tip_altar", "Stand at the altar and press E / R to choose a boon. Every boon has a cost - read it.")
        elif spec.kind == "forge":
            tip("tip_forge", "The forge turns slag into weapon levels. The stall sells boons.")

    # ------------------------------------------------------------------ update
    def pause(self) -> None:
        if self.paused or self.over:
            return
        self.paused = True
        self.app.scenes.push(RunPause(self))

    def update(self, dt: float) -> None:
        if self.paused or self.over or self.room is None:
            return
        self.t += 1
        room = self.room
        p0 = self.inp.player(0)
        if "PAUSE" in p0.pressed:
            self.pause()
            return
        if "SELECT" in p0.pressed:
            self.app.scenes.push(BoonList(self))
            self.paused = True
            return
        self.fade = max(0.0, self.fade - 0.08)
        self.trauma = max(0.0, self.trauma - 0.045)
        self.parts.update(dt)
        self.floats.update(dt)
        self.banner_t = max(0, self.banner_t - 1)
        self.tip_t = max(0, self.tip_t - 1)
        self.hit_flash = max(0, self.hit_flash - 1)
        if self.pending is not None:
            self._do_transition()
            return
        if room.hitstop > 0:
            room.hitstop -= 1
            return
        intent = make_intent(self.app, p0, self.toggle) if self.fade < 0.5 else Intent()
        room.admin_god = bool(getattr(self.app, "admin_god", False))
        room.admin_oneshot = bool(getattr(self.app, "admin_oneshot", False))
        if getattr(self.app, "admin_aimbot", False):
            target = self._admin_aim_target(room)
            if target is not None:
                p = room.player
                dx = target.x - p.x
                dy = target.y - p.y
                n = math.hypot(dx, dy) or 1.0
                intent.aim = (dx / n, dy / n)
        room.update(intent)
        self._events(room.drain_events())
        for req in room.ui_requests:
            self._ui(req)
        room.ui_requests.clear()
        if room.exit_request is not None:
            self.pending = room.exit_request
            self.fade_out = 0.0
            room.exit_request = None
        if room.player_dead and not self.over:
            self._end(False)

    def _do_transition(self) -> None:
        side, target = self.pending
        self.fade = min(1.0, self.fade + 0.12)
        if self.fade < 1.0:
            return
        self.pending = None
        room = self.room
        if side == "stair":
            if self.run.floor >= FLOORS or room.spec.boss in ("crown_of_embers", "ash_wyrm") and room.boss_defeated:
                self._end(True)
                return
            self.run.hp = room.player.hp
            self.start_floor(self.run.floor + 1)
        elif side == "choir":
            self.run.hp = room.player.hp
            self.room_stack.append((room, 0))
            spec = LG.RoomSpec(-2, 0, 0, "boss", self.run.seed ^ 0xC0125, doors={}, layout=LG.build_layout("open", set()), boss="choir_warden")
            self.enter_room(-2, None, spec)
        elif side == "return":
            old, _ = self.room_stack.pop()
            self.run.hp = room.player.hp
            self.room = old
            self.room.player.hp = self.run.hp
            self.bg = art.bake_room(old.spec, self.run.floor)
            self.fade = 1.0
        else:
            self.run.hp = room.player.hp
            from .sim.levelgen import OPP
            self.enter_room(target, OPP[side])

    # ------------------------------------------------------------------ events -> feedback
    def _events(self, evs) -> None:
        a = self.app.audio
        P = self.parts
        for ev in evs:
            k = ev.kind
            x, y = OX + ev.x, OY + ev.y
            d = ev.data
            if k == "hit":
                ang = math.degrees(d.get("ang", 0))
                P.emit((x, y), 9, (50, 150), (ang - 40, ang + 40), (0.12, 0.35), (1, 2.5), (255, 236, 190), (255, 90, 40), drag=4, shape="line")
                self.trauma = min(0.8, self.trauma + d.get("shake", 0.1))
                a.play("cinder_hit_heavy" if d.get("stop", 0) >= 7 else "cinder_hit", 0.8, pan=clamp((ev.x - 224) / 224, -1, 1))
                self.hit_flash = 1
            elif k == "damage":
                col = (255, 120, 110) if d.get("player") else (255, 244, 205) if not d.get("crit") else (255, 214, 90)
                self.floats.add(str(int(round(d["amount"]))), (x, y), col, 0.7)
            elif k == "kill":
                n = 22 if d.get("big") else 12
                P.emit((x, y), n, (30, 110), (0, 360), (0.3, 0.8), (1, 3), (255, 190, 90), (120, 30, 20), gravity=-10, drag=2, glow=6)
                a.play("cinder_kill", 0.8)
            elif k == "player_hit":
                self.trauma = min(0.9, self.trauma + 0.45)
                FEEL.flash((255, 60, 40), 0.18)
                a.play("cinder_hurt", 1.0)
                self.last_cause = d.get("src", "") or self.last_cause
            elif k in ("swing",):
                pass
            elif k == "parry":
                P.emit((x, y), 14, (60, 160), (0, 360), (0.15, 0.4), (1, 2), (255, 255, 255), (150, 190, 255), drag=5, shape="ring")
                FEEL.flash((255, 255, 255), 0.22 if d.get("perfect") else 0.1)
                self.trauma = min(0.9, self.trauma + 0.3)
                a.play("cinder_parry", 1.0)
                if not self.cs.data["seen"].get("tip_parry_done"):
                    self.cs.data["seen"]["tip_parry_done"] = True
            elif k == "perfect_dodge":
                P.emit((x, y), 10, (30, 80), (0, 360), (0.3, 0.6), (1, 2), (180, 240, 255), (60, 100, 200), drag=3)
                self.floats.add("PERFECT", (x, y - 14), (150, 230, 255), 0.8)
                a.play("cinder_perfect", 0.8)
            elif k == "dodge":
                a.play("cinder_roll", 0.6)
            elif k == "attack_start":
                a.play(d.get("sfx", "cinder_slash"), 0.6, pan=clamp((ev.x - 224) / 224, -1, 1))
            elif k in ("flashover", "nova", "explode"):
                r = d.get("radius", 40)
                P.emit((x, y), 26, (40, 140), (0, 360), (0.2, 0.6), (1, 3), (255, 220, 140) if k != "nova" else (255, 240, 120), (255, 80, 30) if k != "nova" else (120, 160, 255), drag=3, glow=8)
                self.trauma = min(0.9, self.trauma + 0.4)
                a.play("cinder_boom", 0.9)
                self.floats.add({"flashover": "FLASHOVER", "nova": "CHAIN NOVA", "explode": ""}[k], (x, y - 16), (255, 190, 90), 0.8)
                if not self.cs.data["seen"].get("tip_synergy"):
                    self.cs.data["seen"]["tip_synergy"] = True
                    self.tip, self.tip_t = "Ash + burn = Flashover. Ash + shock = Chain Nova. Combine statuses.", 300
            elif k == "arc":
                self._arc(x, y, OX + d["tx"], OY + d["ty"])
            elif k == "boom" or k == "burst":
                P.emit((x, y), 16, (30, 90), (0, 360), (0.3, 0.7), (1, 3), (255, 160, 60), (90, 20, 10), gravity=-8)
            elif k == "room_clear":
                self.banner, self.banner_t = "CLEARED", 90
                a.play("cinder_clear", 0.9)
                self.app.audio.set_intensity(0.3)
            elif k == "doors":
                a.play("cinder_door", 0.8)
            elif k == "boss_start":
                self.banner, self.banner_t = self.room.boss.title.upper() if self.room.boss else "BOSS", 150
                self.app.audio.set_intensity(1.0)
                a.play("cinder_boss", 1.0)
            elif k == "phase":
                self.trauma = 1.0
                FEEL.flash((255, 220, 160), 0.4)
                self.banner, self.banner_t = "PHASE " + str(d.get("phase", 0) + 1), 80
                a.play("cinder_boss", 1.0)
            elif k == "boss_dead":
                self.trauma = 1.0
                FEEL.flash((255, 255, 255), 0.6)
                P.emit((x, y), 80, (30, 160), (0, 360), (0.6, 1.4), (1, 4), (255, 230, 150), (120, 40, 20), drag=2, glow=10)
                a.play("cinder_boom", 1.0)
                self._boss_rewards()
            elif k == "evolve":
                self.banner, self.banner_t = f"EVOLVED: {d['name'].upper()}", 200
                self.tip, self.tip_t = d.get("text", ""), 360
                FEEL.flash((255, 220, 140), 0.5)
                a.play("cinder_evolve", 1.0)
                self.cs.data.setdefault("evolved", [])
                if d["weapon"] not in self.cs.data["evolved"]:
                    self.cs.data["evolved"].append(d["weapon"])
            elif k == "heal":
                self.floats.add(f"+{int(d['amount'])}", (x, y - 10), (140, 255, 160), 0.8)
                a.play("heal", 0.6)
            elif k == "pickup":
                a.play("pickup", 0.35)
            elif k == "secret":
                self.banner, self.banner_t = "SECRET", 90
                a.play("unlock", 0.8)
                P.emit((x, y), 24, (20, 90), (0, 360), (0.4, 0.9), (1, 2), (255, 230, 150), (150, 100, 60), drag=3)
            elif k in ("notice",):
                pass
            elif k in ("block", "guard_break"):
                P.emit((x, y), 8, (30, 90), (0, 360), (0.1, 0.3), (1, 2), (210, 220, 255), (100, 120, 160), drag=5, shape="line")
                a.play("cinder_block", 0.7)
            elif k in ("shoot", "cast", "charge", "fuse", "aim", "warn", "quake", "crash", "spawned", "spawn_mark", "note",
                       "revive", "player_dead", "stagger", "open", "buff", "shield", "blink_in", "blink_out", "collapse",
                       "ash_cloud", "flare", "ricochet", "spark", "crack"):
                self._misc(k, x, y, d)

    def _misc(self, k: str, x: float, y: float, d: dict) -> None:
        P, a = self.parts, self.app.audio
        if k == "shoot":
            a.play("cinder_shoot", 0.5)
        elif k == "cast":
            a.play("cinder_cast", 0.6)
            P.emit((x, y), 10, (10, 40), (0, 360), (0.4, 0.8), (1, 2), (210, 190, 255), (90, 60, 150), gravity=-20)
        elif k == "fuse":
            a.play("cinder_fuse", 0.7)
        elif k == "charge":
            a.play("cinder_charge", 0.7)
        elif k == "crash" or k == "quake":
            self.trauma = min(1.0, self.trauma + 0.55)
            P.emit((x, y), 14, (30, 100), (0, 360), (0.3, 0.7), (1, 3), (190, 180, 170), (80, 70, 70), drag=3)
            a.play("cinder_smash", 0.9)
        elif k == "stagger":
            self.floats.add("STAGGER", (x, y - 16), (255, 230, 140), 0.7)
            a.play("cinder_stagger", 0.7)
        elif k == "spawned":
            P.emit((x, y), 8, (20, 60), (0, 360), (0.2, 0.5), (1, 2), (255, 190, 90), (150, 60, 30), gravity=-10)
        elif k == "spawn_mark":
            P.emit((x, y), 6, (10, 30), (0, 360), (0.5, 0.9), (1, 2), (255, 120, 60), (80, 20, 20), gravity=-10)
        elif k == "revive":
            self.banner, self.banner_t = "SECOND WIND", 100
            FEEL.flash((255, 240, 200), 0.5)
            a.play("cinder_evolve", 1.0)
        elif k == "player_dead":
            a.play("cinder_death", 1.0)
        elif k == "open":
            a.play("pickup", 0.9)
        elif k == "note":
            a.play("cinder_note", 0.8)
        elif k == "flare":
            P.emit((x, y), 40, (60, 180), (0, 360), (0.3, 0.7), (1, 3), (255, 230, 150), (255, 90, 40), drag=3, glow=8)
            FEEL.flash((255, 220, 150), 0.35)
            a.play("cinder_boom", 0.9)
        elif k == "ash_cloud":
            P.emit((x, y), 10, (10, 40), (0, 360), (0.5, 1.0), (2, 4), (190, 184, 200), (90, 84, 100), drag=2, shrink=False)
        elif k == "ricochet" or k == "spark":
            P.emit((x, y), 4, (30, 80), (0, 360), (0.1, 0.25), (1, 1.5), (255, 230, 160), (255, 120, 50), drag=4)
        elif k == "buff":
            self.floats.add("SHARP", (x, y - 16), (255, 214, 120), 0.8)
        elif k == "shield":
            self.floats.add("SHIELD", (x, y - 16), (150, 200, 255), 0.8)

    def _arc(self, x0, y0, x1, y1) -> None:
        n = 6
        for i in range(n + 1):
            f = i / n
            self.parts.emit((x0 + (x1 - x0) * f + random.uniform(-3, 3), y0 + (y1 - y0) * f + random.uniform(-3, 3)), 1, (0, 5),
                            (0, 360), (0.08, 0.16), (1.5, 2.5), (255, 244, 150), (120, 160, 255), glow=4)

    def _boss_rewards(self) -> None:
        room = self.room
        bid = room.boss.boss_id if room.boss else ""
        if not bid:
            return
        self.run.boss_kills.append(bid)
        w = self.app.world
        if bid == "choir_warden":
            w.emit("cinder.boss_defeated", boss="choir_warden")
            self.run.soot += 25
            self.run.slag += 30
            room.props.append(__import__("shardlight.modes.cinder.sim.entities", fromlist=["Prop"]).Prop("altar", W_PX / 2, H_PX / 2, 10, {}))
            room.cleared = True
            from .sim.entities import Prop
            room.props.append(Prop("stair", W_PX / 2 + 40, H_PX / 2, 10, {"kind": "return"}))
        else:
            w.emit("cinder.boss_defeated", boss=bid)

    # ------------------------------------------------------------------ overlays
    def _ui(self, req) -> None:
        kind, data, prop = req
        if kind == "boons":
            self.paused = True
            self.app.scenes.push(BoonChoice(self, data, prop))
        elif kind == "anvil":
            self.paused = True
            self.app.scenes.push(AnvilMenu(self))
        elif kind == "stall":
            self.paused = True
            self.app.scenes.push(StallMenu(self, prop))

    def apply_boon(self, bid: str) -> None:
        run = self.run
        if run.perks.add(bid):
            b = run.lib.boons[bid]
            self.banner, self.banner_t = b.name.upper(), 90
            self.app.audio.play("cinder_boon", 0.9)
        self.room._sync_player()
        ev = run.evolution_ready()
        if ev:
            w = run.evolve(ev)
            self.room.emit("evolve", self.room.player.x, self.room.player.y, weapon=w.id, name=w.name, text=ev.get("text", ""))

    # ------------------------------------------------------------------ run end
    def _end(self, won: bool) -> None:
        self.over = True
        run = self.run
        cs = self.cs
        d = cs.data
        depth = run.floor
        heat = run.mods.heat
        base = depth * 8 + run.kills // 2 + run.secrets * 6 + len(run.boss_kills) * 15 + (40 if won else 0)
        soot = int(base * (1 + 0.25 * heat)) + run.soot
        d["soot"] += soot
        d["best_floor"] = max(d["best_floor"], depth if not won else FLOORS)
        if won:
            d["wins"] += 1
            d["heat_best"] = max(d["heat_best"], heat)
        d["summary"] = f"Best floor {d['best_floor']}/{FLOORS}   Summits {d['wins']}"
        w = self.app.world
        w.emit("cinder.run_completed", depth=depth, won=won)
        facet = False
        if won:
            facet = w.complete_facet("cinder")
        self.app.economy.grant("cinder", 4 + depth * 3 + (15 if won else 0))
        self.app.save_now()
        self.app.audio.set_intensity(0.15)
        cs.set_screen(EndScreen(cs, run, won, soot, facet, self.last_cause or self._cause()))

    def _cause(self) -> str:
        return self.room.player.last_hit_by if self.room else ""

    # ------------------------------------------------------------------ draw
    def draw(self, surf: pygame.Surface) -> None:
        room = self.room
        surf.fill(art.INK)
        if room is None:
            return
        ox, oy = OX, OY
        if self.trauma > 0 and FEEL.shake_scale:
            s = self.trauma ** 2 * 5 * FEEL.shake_scale
            ox += int(random.uniform(-s, s))
            oy += int(random.uniform(-s, s))
        surf.blit(self.bg, (ox, oy))
        art.draw_hazards(surf, room, ox, oy, self.t)
        art.draw_doors(surf, room, ox, oy, self.t)
        art.draw_props(surf, room, ox, oy, self.t, None)
        art.draw_pickups(surf, room, ox, oy, self.t)
        # entities sorted by y
        ents: list[tuple[float, str, object]] = [(room.player.y, "p", room.player)]
        for e in room.enemies:
            ents.append((e.y, "b" if e.kind == "boss" else "e", e))
        for _, k, e in sorted(ents, key=lambda q: q[0]):
            if k == "p":
                art.draw_player(surf, room, ox, oy, self.t, self._lantern())
            elif k == "b":
                art.draw_boss(surf, e, ox, oy, self.t)
            else:
                art.draw_enemy(surf, e, ox, oy, self.t)
        art.draw_hitboxes(surf, room, ox, oy, self.t, self.app.debug)
        art.draw_projectiles(surf, room, ox, oy, self.t)
        self.parts.draw(surf, (0, 0))
        # lighting
        dim = room.mods["dim_light"]
        self.light.ambient = (int(138 - 70 * dim), int(112 - 60 * dim), int(150 - 55 * dim))
        self.light.clear()
        art.room_lights(room, self.light, ox, oy, self.t)
        self.light.apply(surf)
        for fx in room.hitboxes:
            pass
        self.floats.draw(surf, self.app.font)
        self._hud(surf, room)
        if self.hit_flash:
            pass
        if self.fade > 0:
            ov = pygame.Surface((W, H))
            ov.set_alpha(int(255 * self.fade))
            surf.blit(ov, (0, 0))
        if self.app.debug:
            self._debug(surf, room)

    def _lantern(self):
        from ...hub.hub import lantern_color
        return lantern_color(self.app.world)

    def _hud(self, surf: pygame.Surface, room: Room) -> None:
        f = self.app.font
        p = room.player
        run = self.run
        # health
        w = 120
        pygame.draw.rect(surf, art.INK, (6, 5, w + 4, 11))
        pygame.draw.rect(surf, (60, 24, 30), (8, 7, w, 7))
        frac = clamp(p.hp / max(1, p.max_hp))
        pygame.draw.rect(surf, mix((230, 70, 60), (120, 230, 140), frac), (8, 7, int(w * frac), 7))
        pygame.draw.rect(surf, core_art.shade((230, 70, 60), 0.5), (8, 7, int(w * frac), 2))
        f.draw(surf, f"{int(max(0, p.hp))}/{int(p.max_hp)}", (w + 14, 6), PARCHMENT, art.INK)
        # flare meter
        pygame.draw.rect(surf, art.INK, (6, 17, 62, 5))
        pygame.draw.rect(surf, (80, 60, 40), (7, 18, 60, 3))
        pygame.draw.rect(surf, art.GOLD if run.flare >= 100 else (255, 150, 60), (7, 18, int(60 * clamp(run.flare / 100)), 3))
        f.draw(surf, "FLARE" if run.flare < 100 else "FLARE: L", (72, 15), art.GOLD if run.flare >= 100 else DIM, art.INK)
        # right: slag, weapon, floor
        f.draw(surf, f"Slag {run.slag}", (W - 6, 5), art.GOLD, art.INK, anchor="topright")
        wp = run.weapon
        f.draw(surf, f"{wp.name} L{run.weapon_level}", (W - 6, 15), wp.color, art.INK, anchor="topright")
        # floor map
        self._minimap(surf, room)
        # boons strip
        x = 6
        for bid, n in run.perks.owned.items():
            b = run.lib.boons[bid]
            tag = next((t for t in b.tags if t in TAG_COLORS), "offense")
            col = TAG_COLORS[tag]
            pygame.draw.rect(surf, art.INK, (x - 1, H - 15, 11, 11))
            pygame.draw.rect(surf, col, (x, H - 14, 9, 9))
            f.draw(surf, b.name[0], (x + 2, H - 13), art.INK, None)
            if n > 1:
                f.draw(surf, str(n), (x + 8, H - 8), (255, 255, 255), art.INK)
            x += 12
        if run.kill_streak >= 3:
            f.draw(surf, f"x{run.kill_streak}", (W - 8, H - 24), art.GOLD, art.INK, anchor="topright", scale=2)
        # boss bar
        if room.boss and room.combat_started and room.boss.alive:
            art.draw_boss_bar(surf, room.boss, f, W)
        # interaction prompt
        tgt = room.interact_target()
        if tgt is not None:
            label = {"altar": "Choose a boon", "chest": "Open", "anvil": "Forge", "stall": "Shop", "campfire": "Rest",
                     "stair": "Ascend", "choir_door": "Open the singing door"}.get(tgt.kind, "Use")
            f.draw(surf, f"[{self.inp.player(0).prompt('R')}] {label}", (OX + tgt.x, OY + tgt.y - 22), (255, 244, 205), art.INK, anchor="midbottom")
        if self.banner_t > 0:
            k = min(1.0, self.banner_t / 20)
            f.draw(surf, self.banner, (W // 2, 80), (255, 244, 205), (40, 10, 10), anchor="midtop", scale=3)
        if self.tip_t > 0 and self.tip:
            r = pygame.Rect(40, H - 52, W - 80, 26)
            draw_panel(surf, r, fill=INK, alpha=215)
            f.draw_wrapped(surf, self.tip, pygame.Rect(r.x + 6, r.y + 6, r.w - 12, 16), PARCHMENT, None, max_lines=2)
        # parry cue: ring around threats about to land
        # kill bar (adaptation notice)
        notes = self.run.adapt.describe()
        if notes and self.app.settings.get("difficulty.adaptive_ai") > 0 and room.t % 600 < 150 and any("ON" in n for n in notes):
            f.draw(surf, "The enemies are learning your habits.", (W // 2, 40), (255, 160, 120), art.INK, anchor="midtop")

    def _minimap(self, surf: pygame.Surface, room: Room) -> None:
        plan = self.plan
        if plan is None:
            return
        size = 7
        x0, y0 = W - 4 * size * 2 - 6, 28
        colors = {"start": (150, 200, 255), "arena": (200, 90, 80), "elite": (255, 150, 60), "reward": (255, 214, 110),
                  "forge": (200, 160, 120), "rest": (130, 220, 150), "secret": (200, 140, 255), "boss": (255, 60, 60),
                  "stair": (230, 230, 240), "choir": (190, 160, 255)}
        for rid, spec in plan.rooms.items():
            if rid not in self.floor_vis and not any(n in self.floor_vis for n in spec.doors.values()):
                continue
            x, y = x0 + spec.gx * size * 2, y0 + spec.gy * size * 2
            seen = rid in self.floor_vis
            col = colors.get(spec.kind, (150, 150, 150)) if seen else (60, 56, 70)
            for s, tgt in spec.doors.items():
                if s in spec.hidden:
                    continue
                dx, dy = LG.SIDES[s]
                pygame.draw.line(surf, (90, 80, 100), (x + size // 2, y + size // 2), (x + size // 2 + dx * size, y + size // 2 + dy * size))
            pygame.draw.rect(surf, art.INK, (x - 1, y - 1, size + 2, size + 2))
            pygame.draw.rect(surf, col if not spec.cleared or spec.kind in ("start",) else mix(col, (40, 40, 50), 0.5), (x, y, size, size))
            if spec.id == room.spec.id:
                pygame.draw.rect(surf, (255, 255, 255), (x - 1, y - 1, size + 2, size + 2), 1)

    def _debug(self, surf: pygame.Surface, room: Room) -> None:
        f = self.app.font
        y = 40
        for line in self.run.adapt.describe()[:6]:
            f.draw(surf, line, (8, y), (160, 255, 160), art.INK)
            y += 10
        for e in room.enemies:
            if e.alive:
                f.draw(surf, e.brain.state, (OX + e.x, OY + e.y - e.r - 10), (255, 255, 120), art.INK, anchor="midbottom")
        f.draw(surf, f"seed {self.run.seed} floor {self.run.floor} room {room.spec.id} {room.spec.kind}", (8, H - 30), DIM, art.INK)


# ====================================================================================== overlays
class BoonChoice(Scene):
    opaque = False

    def __init__(self, rs: RunScreen, options: list[str], prop):
        super().__init__(rs.app)
        self.rs = rs
        self.opts = options
        self.sel = 0
        self.t = 0
        self.prop = prop

    def on_exit(self) -> None:
        self.rs.paused = False

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        dx, _ = p.menu_dir()
        if dx and self.opts:
            self.sel = (self.sel + dx) % len(self.opts)
            self.app.audio.play("ui_move", 0.5)
        if self.t < 10:
            return
        if "CONFIRM" in p.pressed or "A" in p.pressed:
            if self.opts:
                self.rs.apply_boon(self.opts[self.sel])
            self.app.scenes.pop()
        elif "BACK" in p.pressed:
            # the altar stays available: walk away and return
            self.prop.used = False
            self.rs.room.spec.reward_taken = False
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((8, 4, 14, 200))
        surf.blit(shade, (0, 0))
        f.draw(surf, "CHOOSE A BOON", (W // 2, 14), art.GOLD, (30, 8, 8), anchor="midtop", scale=2)
        if not self.opts:
            f.draw(surf, "The altar is silent.", (W // 2, 120), DIM, None, anchor="midtop")
            return
        n = len(self.opts)
        for i, bid in enumerate(self.opts):
            b = self.rs.run.lib.boons[bid]
            cw = 140
            x = W // 2 - (n * cw + (n - 1) * 8) // 2 + i * (cw + 8)
            r = pygame.Rect(x, 40, cw, 176 if i == self.sel else 168)
            if i == self.sel:
                r.y -= 4
            tag = next((t for t in b.tags if t in TAG_COLORS), "offense")
            col = TAG_COLORS[tag]
            draw_panel(surf, r, border=col if i == self.sel else DIM, fill=INK, alpha=245)
            f.draw(surf, b.rarity.upper(), (r.x + 8, r.y + 8), {"common": DIM, "rare": LENS, "epic": (255, 150, 255)}[b.rarity], None)
            f.draw(surf, b.name, (r.x + 8, r.y + 20), (255, 244, 205), None)
            core_art.draw_prism(surf, (r.centerx, r.y + 54), 14, col, self.t * 0.04 + i, True, True)
            y = f.draw_wrapped(surf, b.desc, pygame.Rect(r.x + 8, r.y + 78, cw - 16, 50), PARCHMENT, None, max_lines=5)
            f.draw(surf, "COST", (r.x + 8, r.bottom - 38), DANGER, None)
            f.draw_wrapped(surf, b.cost or "None.", pygame.Rect(r.x + 8, r.bottom - 28, cw - 16, 24), (255, 160, 140), None, max_lines=3)
            if b.needs_boons:
                f.draw(surf, "SYNERGY", (r.right - 8, r.y + 8), (200, 140, 255), None, anchor="topright")
        draw_prompts(surf, self.app, [("LEFT", "Browse"), ("CONFIRM", "Take"), ("BACK", "Leave for now")])


class AnvilMenu(MenuScene):
    def __init__(self, rs: RunScreen):
        self.rs = rs
        super().__init__(rs.app, "THE ANVIL", self._items, 230, overlay=True)

    def on_exit(self) -> None:
        self.rs.paused = False

    def _items(self) -> list[MenuItem]:
        run = self.rs.run
        cost = 30 * (run.weapon_level + 1)
        done = run.weapon_level >= 3
        return [MenuItem(f"Slag: {run.slag}", kind="label"),
                MenuItem(f"Temper {run.weapon.name} to L{run.weapon_level + 1}  ({cost} slag)" if not done else "Weapon fully tempered",
                         self._temper, enabled=not done and run.slag >= cost,
                         hint="+10% damage per level. The only raw damage in the game."),
                MenuItem("Leave", self.app.scenes.pop)]

    def _temper(self) -> None:
        run = self.rs.run
        cost = 30 * (run.weapon_level + 1)
        if run.slag >= cost and run.weapon_level < 3:
            run.slag -= cost
            run.weapon_level += 1
            self.app.audio.play("pickup", 0.9)
            self.rebuild()


class StallMenu(MenuScene):
    def __init__(self, rs: RunScreen, prop):
        self.rs = rs
        self.prop = prop
        if prop.data.get("stock") is None:
            prop.data["stock"] = rs.run.offer(rs.room.rng, rs.cs.unlocked_sets()["boons"], 3)
        super().__init__(rs.app, "THE STALL", self._items, 270, overlay=True)

    def on_exit(self) -> None:
        self.rs.paused = False

    def _items(self) -> list[MenuItem]:
        run = self.rs.run
        items = [MenuItem(f"Slag: {run.slag}", kind="label")]
        for bid in self.prop.data["stock"]:
            b = run.lib.boons[bid]
            price = int(round(40 * (1.5 if b.rarity != "common" else 1.0) * run.perks.get("shop_price_mul") if run.perks.get("shop_price_mul") else 40 * (1.5 if b.rarity != "common" else 1.0)))
            items.append(MenuItem(f"{b.name}  ({price})", lambda bid=bid, price=price: self._buy(bid, price),
                                  enabled=run.slag >= price, hint=f"{b.desc}  COST: {b.cost}"))
        if len(items) == 1:
            items.append(MenuItem("Sold out.", kind="label"))
        items.append(MenuItem("Leave", self.app.scenes.pop))
        return items

    def _buy(self, bid: str, price: int) -> None:
        run = self.rs.run
        if run.slag >= price:
            run.slag -= price
            self.prop.data["stock"].remove(bid)
            self.rs.apply_boon(bid)
            self.rebuild()


class BoonList(Scene):
    opaque = False

    def __init__(self, rs: RunScreen):
        super().__init__(rs.app)
        self.rs = rs
        self.t = 0

    def on_exit(self) -> None:
        self.rs.paused = False

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 6 and ("BACK" in p.pressed or "SELECT" in p.pressed or "CONFIRM" in p.pressed or "PAUSE" in p.pressed):
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((8, 4, 14, 215))
        surf.blit(shade, (0, 0))
        run = self.rs.run
        draw_panel(surf, pygame.Rect(20, 14, W - 40, H - 40), title="YOUR CLIMB", font=f)
        f.draw(surf, f"{run.weapon.name}  L{run.weapon_level}   Floor {run.floor}   Kills {run.kills}   Heat {run.mods.heat}", (32, 24), PARCHMENT, None)
        ev = run.weapon.evolutions
        if ev:
            for i, e in enumerate(ev[:2]):
                cond = ", ".join(f"{c['counter'].replace('_', ' ')} {run.counters.get(c['counter'], 0)}/{c['count']}" if 'counter' in c else c.get('boon', '') for c in e["when"])
                f.draw(surf, f"Evolves to {run.lib.weapons[e['to']].name}: {cond}", (32, 36 + i * 10), (255, 214, 140), None)
        y = 62
        if not run.perks.owned:
            f.draw(surf, "No boons yet.", (32, y), DIM, None)
        for bid, n in run.perks.owned.items():
            b = run.lib.boons[bid]
            f.draw(surf, f"{b.name}{' x' + str(n) if n > 1 else ''}", (32, y), (255, 244, 205), None)
            f.draw(surf, b.desc[:44], (150, y), PARCHMENT, None)
            f.draw(surf, "cost: " + (b.cost[:34] if b.cost else "-"), (310, y), (255, 160, 140), None)
            y += 11
            if y > H - 50:
                break
        draw_prompts(surf, self.app, [("BACK", "Close")])


class RunPause(MenuScene):
    def __init__(self, rs: RunScreen):
        self.rs = rs
        super().__init__(rs.app, "PAUSED", self._items, 210, overlay=True, footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def on_exit(self) -> None:
        self.rs.paused = False

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [MenuItem("Resume", a.scenes.pop), MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
                MenuItem("Abandon climb", self._abandon),
                MenuItem("Leave shard (lose this climb)", self._leave)]

    def _abandon(self) -> None:
        self.app.scenes.pop()
        self.rs.room.player.hp = 0
        self.rs.room.player_dead = True
        self.rs.room.player.alive = True
        self.rs.last_cause = "abandoned"

    def _leave(self) -> None:
        self.app.scenes.pop()
        self.app.save_now()
        self.rs.cs.finish(left=True)


class EndScreen(Scene):
    def __init__(self, cs: CinderScene, run: Run, won: bool, soot: int, facet: bool, cause: str):
        super().__init__(cs.app)
        self.cs = cs
        self.run = run
        self.won = won
        self.soot = soot
        self.facet = facet
        self.cause = cause
        self.t = 0

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 50 and ("CONFIRM" in p.pressed or "BACK" in p.pressed):
            self.cs.show_foot()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        run = self.run
        surf.fill(art.CHAR)
        core_art.dither_vertical(surf, pygame.Rect(0, 0, W, H), (20, 14, 26), (52, 26, 30) if not self.won else (90, 60, 30))
        title = "THE CROWN IS QUIET" if self.won else "YOU WAKE AT THE FOOT OF THE STAIR"
        f.draw(surf, title, (W // 2, 24), art.GOLD if self.won else (255, 150, 120), (30, 8, 8), anchor="midtop", scale=2)
        draw_panel(surf, pygame.Rect(60, 56, W - 120, 140), fill=INK, alpha=240)
        lines = [f"Reached floor {run.floor}/{FLOORS}", f"Kills {run.kills}     Secrets {run.secrets}     Bosses {len(run.boss_kills)}",
                 f"Heat {run.mods.heat}     Weapon {run.weapon.name} L{run.weapon_level}",
                 f"Seed {run.seed}   (enter it from the shard card to retry)",
                 f"Slain by: {self.cause}" if not self.won and self.cause else "",
                 f"Soot earned: +{self.soot}"]
        for i, ln in enumerate(lines):
            f.draw(surf, ln, (72, 66 + i * 12), PARCHMENT if i < 5 else art.GOLD, None)
        names = [run.lib.boons[b].name for b in run.perks.owned]
        f.draw_wrapped(surf, "Boons: " + (", ".join(names) or "none"), pygame.Rect(72, 142, W - 144, 40), DIM, None, max_lines=4)
        if self.facet:
            f.draw(surf, "FACET REPAIRED: Cinder", (W // 2, 204), LENS, (10, 6, 12), anchor="midtop", scale=2)
        if self.t > 50:
            draw_prompts(surf, self.app, [("CONFIRM", "Continue")])
