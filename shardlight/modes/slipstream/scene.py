"""Slipstream scene: menus, garage, race screen (1 or 2 viewports), results, championship flow."""
from __future__ import annotations

import math
import random
from typing import Any

import pygame
from pygame import Vector2

from ...core.fx import ParticleSystem, clamp, damp, ease_out_cubic, lerp, mix, FEEL
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Dialogue, Menu, MenuItem, MenuScene,
                        SettingsScene, ControlsScene, draw_panel, draw_prompts)
from . import art, track as trk
from .ai import Driver, LineModel, classify_pass, make_adaptation
from .defs import K_CUP, Garage
from .info import INFO
from .physics import Controls, TARMAC
from .race import DT, Race, Racer, ghost_pose, pack_ghost, unpack_ghost
from .vehicle import UPGRADE_SLOTS, upgrade_cost

W, H = 480, 270
PRIZE = (150, 100, 70, 50, 35, 25)
SAVE_V = 1
PERS = ("clean", "aggressive", "clean", "erratic", "aggressive", "clean")
AI_NAMES = ("Vesper", "Orsolya", "Dunmore", "Quill", "Tamsin", "Rook")
AI_VEH = ("kestrel", "mantis", "anvil", "lance", "mantis", "kestrel")
SKILL = {"story": 0.72, "standard": 0.86, "hard": 0.96}


def human_controls(p) -> Controls:
    c = Controls()
    held = p.down
    c.steer = max(-1.0, min(1.0, p.move.x * 1.0))
    c.throttle = 1.0 if ("UP" in held or "A" in held) else max(0.0, -p.move.y)
    c.brake = 1.0 if ("DOWN" in held or "B" in held) else max(0.0, p.move.y)
    if p.move.y > 0.3 and p.move.y < 1.0 and "DOWN" not in held:
        c.brake = p.move.y
    c.handbrake = "X" in held
    c.boost = "Y" in held
    c.rewind = "R" in p.pressed
    c.reset = "SELECT" in p.pressed
    return c


def track_key(seed: int) -> str:
    return str(seed)


class SlipScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.garage: Garage | None = None
        self.screen: Scene | None = None
        self.sprites = art.CarSprites()
        self.opt_seed = opts.get("seed", "random")
        self.players = int(opts.get("players", 1))
        self.t = 0
        self.cups: list[dict] = []

    # ------------------------------------------------------------------ lifecycle
    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("credits", 0)
        d.setdefault("owned", ["kestrel"])
        d.setdefault("levels", {})
        d.setdefault("bests", {})
        d.setdefault("cups_won", [])
        d.setdefault("seen", {})
        d.setdefault("stats", {"races": 0, "wins": 0})
        self.garage = Garage(self.app.content, self.app.world)
        self.cups = sorted(self.app.content.all(K_CUP), key=lambda c: c["id"])
        if self.garage.available("chronograph") and "chronograph" not in d["owned"] and "chronograph" in self.garage.raw:
            d["owned"].append("chronograph")
            self.app.toast("Slipstream: the Chronograph is yours to drive", LENS)
        self.app.audio.play_music("slipstream", 1.0, 0.3)
        self.show_menu()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, RaceScreen):
            self.screen.pause(f"Controller for player {slot + 1} disconnected", slot)

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.input.assign_local(1)
        self.app.audio.set_intensity(0.25)
        self.set_screen(MainMenu(self))

    # ------------------------------------------------------------------ helpers
    def pick_seed(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        return random.Random(self.app.rng.randrange(1 << 30)).randrange(100, 99999)

    def owned_ids(self) -> list[str]:
        return [v for v in self.garage.ids() if v in self.data["owned"] and self.garage.available(v)]

    def levels(self, vid: str) -> dict:
        return self.data["levels"].get(vid, {})

    def spec(self, vid: str):
        return self.garage.spec(vid, self.levels(vid))

    def difficulty(self) -> float:
        return SKILL[self.app.settings.get("difficulty.preset")]


# ============================================================================================== menus
class MainMenu(Scene):
    def __init__(self, ss: SlipScene):
        super().__init__(ss.app)
        self.ss = ss
        self.t = 0
        items = [MenuItem("Championship", lambda: ss.set_screen(CupMenu(ss))),
                 MenuItem("Single race", lambda: ss.set_screen(VehicleSelect(ss, "race"))),
                 MenuItem("Time trial", lambda: ss.set_screen(VehicleSelect(ss, "trial"))),
                 MenuItem("Split-screen versus (2P)", self._versus),
                 MenuItem("Garage", lambda: ss.set_screen(GarageScreen(ss))),
                 MenuItem("Return to hub", lambda: ss.finish(left=True))]
        self.menu = Menu(self.app, items, 190)
        self.bg_t = 0.0

    def _versus(self) -> None:
        self.app.input.assign_local(2)
        self.ss.set_screen(VehicleSelect(self.ss, "versus"))

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
        if "BACK" in self.inp.player(0).pressed and self.t > 10:
            self.ss.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(art.SALT_WHITE)
        t = self.t
        # horizon wedges and speed lines for a bit of motion
        for k in range(14):
            y = 150 + k * 9
            x = int((t * (2 + k * 0.7) + k * 91) % (W + 160)) - 80
            pygame.draw.line(surf, mix(art.SALT_SHADE, (255, 255, 255), 0.4), (x, y), (x + 40 + k * 4, y), 1)
        pygame.draw.polygon(surf, art.VERM, [(0, 0), (330, 0), (270, 62), (0, 62)])
        pygame.draw.polygon(surf, art.ULTRA, [(0, 62), (270, 62), (250, 80), (0, 80)])
        f = self.app.font
        f.draw(surf, "SLIPSTREAM", (16, 10), (246, 244, 238), art.INK, scale=4)
        f.draw(surf, "salt, speed and one more corner", (18, 52), (246, 244, 238), art.INK)
        spec = self.ss.spec(self.ss.owned_ids()[0])
        spr = self.ss.sprites.get(spec, spec.accent, (t * 0.04) % math.tau)
        big = pygame.transform.scale(spr, (spr.get_width() * 3, spr.get_height() * 3))
        surf.blit(big, (W - 130, 140 - big.get_height() // 2))
        draw_panel(surf, pygame.Rect(16, 96, 206, 128), fill=INK, alpha=230)
        self.menu.draw(surf, (22, 104))
        st = self.ss.data["stats"]
        f.draw(surf, f"Salt: {self.ss.data['credits']}   races {st['races']}  wins {st['wins']}", (16, 230), art.INK, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])


class CupMenu(Scene):
    def __init__(self, ss: SlipScene):
        super().__init__(ss.app)
        self.ss = ss
        self.sel = 0
        self.t = 0

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        _, dy = p.menu_dir()
        n = len(self.ss.cups)
        if dy and n:
            self.sel = (self.sel + dy) % n
        if self.t < 6:
            return
        if "CONFIRM" in p.pressed and n:
            cup = self.ss.cups[self.sel]
            self.ss.set_screen(VehicleSelect(self.ss, "cup", cup=cup))
        if "BACK" in p.pressed:
            self.ss.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(art.SALT_WHITE)
        f = self.app.font
        f.draw(surf, "CHAMPIONSHIPS", (16, 10), art.VERM, art.INK, scale=3)
        for i, c in enumerate(self.ss.cups):
            r = pygame.Rect(30, 50 + i * 70, 420, 62)
            sel = i == self.sel
            draw_panel(surf, r, border=art.VERM if sel else DIM, fill=INK, alpha=235)
            won = c["id"] in self.ss.data["cups_won"]
            f.draw(surf, c["name"] + ("  [WON]" if won else ""), (r.x + 10, r.y + 8), (255, 244, 205), None, scale=2)
            f.draw_wrapped(surf, c.get("blurb", ""), pygame.Rect(r.x + 10, r.y + 28, r.w - 20, 20), PARCHMENT, None, max_lines=2)
            f.draw(surf, f"{len(c['tracks'])} races   prize {c.get('prize', 0)} salt", (r.x + 10, r.y + 48), BRASS, None)
        if not self.ss.cups:
            f.draw(surf, "No championships are installed.", (W // 2, 120), DANGER, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Choose vehicle"), ("BACK", "Back")])


class VehicleSelect(Scene):
    def __init__(self, ss: SlipScene, kind: str, cup: dict | None = None):
        super().__init__(ss.app)
        self.ss = ss
        self.kind = kind
        self.cup = cup
        self.ids = ss.owned_ids()
        self.cur = [0, min(1, len(self.ids) - 1)]
        self.locked = [False, False]
        self.two = kind == "versus"
        self.t = 0

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t < 6:
            return
        for s in range(2 if self.two else 1):
            p = self.inp.player(s)
            dx, _ = p.menu_dir()
            if not self.locked[s]:
                if dx:
                    self.cur[s] = (self.cur[s] + dx) % len(self.ids)
                    self.app.audio.play("ui_move", 0.5)
                if "CONFIRM" in p.pressed or "A" in p.pressed:
                    self.locked[s] = True
                    self.app.audio.play("ui_confirm", 0.8)
            elif "BACK" in p.pressed or "B" in p.pressed:
                self.locked[s] = False
        if "BACK" in self.inp.player(0).pressed and not any(self.locked):
            self.ss.show_menu()
            return
        if all(self.locked[:2 if self.two else 1]):
            vids = [self.ids[self.cur[0]], self.ids[self.cur[1]] if self.two else None]
            self.ss.set_screen(RaceScreen(self.ss, self.kind, vids, self.cup))

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(art.SALT_WHITE)
        f = self.app.font
        f.draw(surf, "CHOOSE YOUR CAR", (16, 8), art.VERM, art.INK, scale=2)
        for s in range(2 if self.two else 1):
            vid = self.ids[self.cur[s]]
            spec = self.ss.spec(vid)
            x0 = 16 + s * 236
            r = pygame.Rect(x0, 34, 222 if self.two else 448, 196)
            draw_panel(surf, r, border=spec.accent, fill=INK, alpha=240, title=f"P{s + 1}" if self.two else None, font=f)
            spr = self.ss.sprites.get(spec, spec.accent, (self.t * 0.05) % math.tau)
            big = pygame.transform.scale(spr, (spr.get_width() * 4, spr.get_height() * 4))
            surf.blit(big, (r.x + 24, r.y + 40))
            tx = r.x + (24 if self.two else 150)
            ty = r.y + (110 if self.two else 14)
            f.draw(surf, spec.name.upper(), (tx, ty), (255, 244, 205), None, scale=2)
            f.draw(surf, spec.tagline, (tx, ty + 18), PARCHMENT, None)
            for k, (label, v) in enumerate(spec.rating().items()):
                yy = ty + 34 + k * 12
                f.draw(surf, label, (tx, yy), DIM, None)
                pygame.draw.rect(surf, (50, 46, 70), (tx + 44, yy + 2, 80, 5))
                pygame.draw.rect(surf, spec.accent, (tx + 44, yy + 2, int(80 * clamp(v)), 5))
            if spec.special == "rewind":
                f.draw(surf, "Special: rewind 1.5s (R) once per lap", (tx, ty + 98), LENS, None)
            lv = sum(self.ss.levels(vid).values())
            f.draw(surf, f"upgrades {lv}/15", (tx, ty + 110 if not self.two else ty + 84), BRASS, None)
            if self.locked[s]:
                f.draw(surf, "READY", (r.right - 10, r.y + 10), GOOD, None, anchor="topright")
        draw_prompts(surf, self.app, [("LEFT", "Browse"), ("CONFIRM", "Lock in"), ("BACK", "Back")])


class GarageScreen(Scene):
    """Buy cars and upgrades with Salt (race winnings). Every upgrade has a tradeoff."""

    def __init__(self, ss: SlipScene):
        super().__init__(ss.app)
        self.ss = ss
        self.vi = 0
        self.row = 0
        self.t = 0
        self.msg = ""

    def _ids(self) -> list[str]:
        return [v for v in self.ss.garage.ids() if self.ss.garage.available(v)]

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        dx, dy = p.menu_dir()
        ids = self._ids()
        if dx:
            self.vi = (self.vi + dx) % len(ids)
            self.row = 0
        if dy:
            self.row = (self.row + dy) % (len(UPGRADE_SLOTS) + 1)
        if self.t < 6:
            return
        vid = ids[self.vi]
        raw = self.ss.garage.raw[vid]
        d = self.ss.data
        if "CONFIRM" in p.pressed:
            if vid not in d["owned"]:
                price = int(raw.get("price", 0))
                if d["credits"] >= price:
                    d["credits"] -= price
                    d["owned"].append(vid)
                    self.msg = f"Bought {raw['name']}"
                    self.app.audio.play("pickup", 0.9)
                else:
                    self.msg = "Not enough salt"
                    self.app.audio.play("ui_error", 0.7)
            elif self.row < len(UPGRADE_SLOTS):
                slot = UPGRADE_SLOTS[self.row]
                lv = d["levels"].setdefault(vid, {}).get(slot, 0)
                cost = upgrade_cost(raw, slot, lv + 1)
                if raw.get("upgrades", {}).get(slot) is None or lv >= 3 or cost == 0:
                    self.msg = "Fully upgraded"
                elif d["credits"] >= cost:
                    d["credits"] -= cost
                    d["levels"][vid][slot] = lv + 1
                    self.msg = "Upgraded"
                    self.app.audio.play("pickup", 0.9)
                else:
                    self.msg = "Not enough salt"
                    self.app.audio.play("ui_error", 0.7)
        if "BACK" in p.pressed:
            self.app.save_now()
            self.ss.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(art.SALT_WHITE)
        f = self.app.font
        ids = self._ids()
        vid = ids[self.vi]
        raw = self.ss.garage.raw[vid]
        owned = vid in self.ss.data["owned"]
        spec = self.ss.spec(vid)
        f.draw(surf, "GARAGE", (16, 8), art.VERM, art.INK, scale=3)
        f.draw(surf, f"Salt {self.ss.data['credits']}", (W - 16, 12), art.INK, None, anchor="topright", scale=2)
        r = pygame.Rect(16, 40, 448, 190)
        draw_panel(surf, r, border=spec.accent, fill=INK, alpha=240)
        spr = self.ss.sprites.get(spec, spec.accent, (self.t * 0.05) % math.tau)
        big = pygame.transform.scale(spr, (spr.get_width() * 4, spr.get_height() * 4))
        surf.blit(big, (r.x + 16, r.y + 20))
        f.draw(surf, spec.name.upper() + ("" if owned else f"   {raw.get('price', 0)} salt"), (r.x + 130, r.y + 10), (255, 244, 205), None, scale=2)
        f.draw(surf, spec.tagline, (r.x + 130, r.y + 28), PARCHMENT, None)
        for k, (label, v) in enumerate(spec.rating().items()):
            yy = r.y + 44 + k * 11
            f.draw(surf, label, (r.x + 16, yy + 54), DIM, None)
            pygame.draw.rect(surf, (50, 46, 70), (r.x + 62, yy + 56, 60, 5))
            pygame.draw.rect(surf, spec.accent, (r.x + 62, yy + 56, int(60 * clamp(v)), 5))
        if not owned:
            f.draw(surf, "Press confirm to buy", (r.x + 130, r.y + 60), BRASS, None)
        else:
            for k, slot in enumerate(UPGRADE_SLOTS):
                up = raw.get("upgrades", {}).get(slot)
                lv = self.ss.data["levels"].get(vid, {}).get(slot, 0)
                y = r.y + 46 + k * 22
                sel = k == self.row
                if sel:
                    pygame.draw.rect(surf, INK_2, (r.x + 128, y - 2, 312, 21))
                f.draw(surf, f"{slot.title():8s}", (r.x + 134, y), BRASS if sel else PARCHMENT, None)
                for lvl in range(3):
                    pygame.draw.rect(surf, spec.accent if lvl < lv else (60, 56, 80), (r.x + 190 + lvl * 12, y + 1, 9, 6))
                if up:
                    cost = upgrade_cost(raw, slot, lv + 1) if lv < 3 else 0
                    f.draw(surf, up.get("name", ""), (r.x + 232, y), PARCHMENT, None)
                    f.draw(surf, up.get("desc", ""), (r.x + 134, y + 10), DIM, None)
                    f.draw(surf, "MAX" if lv >= 3 else f"{cost}", (r.x + 436, y), GOOD if lv >= 3 else BRASS, None, anchor="topright")
        if self.msg:
            f.draw(surf, self.msg, (W // 2, 236), art.ULTRA, None, anchor="midtop")
        draw_prompts(surf, self.app, [("LEFT", "Vehicle"), ("UP", "Slot"), ("CONFIRM", "Buy"), ("BACK", "Back")])


# ============================================================================================== race screen
class Viewport:
    def __init__(self, rect: pygame.Rect, racer: Racer, slot: int):
        self.rect = rect
        self.racer = racer
        self.slot = slot
        self.cam = Vector2(racer.car.x, racer.car.y)
        self.surf = pygame.Surface(rect.size)
        self.shadow = pygame.Surface(rect.size, pygame.SRCALPHA)
        self.shake = 0.0


class RaceScreen(Scene):
    def __init__(self, ss: SlipScene, kind: str, vids: list, cup: dict | None = None, cup_state: dict | None = None):
        super().__init__(ss.app)
        self.ss = ss
        self.kind = kind
        self.vids = vids
        self.cup = cup
        self.cup_state = cup_state
        self.humans = 2 if kind == "versus" else 1
        self.t = 0
        self.paused = False
        self.done_t = 0
        self.results_shown = False
        self.prize = 0
        self.msgs: list[tuple[str, float, tuple]] = []
        self.fx = ParticleSystem(900, random.Random(5))
        self.engine_phase = [0.0, 0.0]
        self.ghost = None
        self.ghost_blob = None
        self.recorded_ghost = None
        self.stats_counted = False

    # ------------------------------------------------------------------ setup
    def on_enter(self, **kw) -> None:
        ss = self.ss
        app = self.app
        if self.cup_state is None and self.kind == "cup":
            self.cup_state = {"round": 0, "points": {}, "vehicle": self.vids[0], "results": []}
        if self.kind == "cup":
            tinfo = self.cup["tracks"][self.cup_state["round"]]
            seed, laps, self.track_name = tinfo["seed"], int(tinfo.get("laps", 3)), tinfo.get("name", "")
        else:
            seed, laps, self.track_name = ss.pick_seed(), 3, ""
        self.seed = seed
        self.track = trk.generate(seed)
        self.track_name = self.track_name or self.track.name
        self.baked, self.origin = art.bake_track(self.track)
        self.skids = pygame.Surface(self.baked.get_size(), pygame.SRCALPHA)
        self.mini, self.mini_scale, self.mini_org = art.make_minimap(self.track)
        self.race = Race(self.track, laps, seed)
        diff = ss.difficulty() * (self.cup.get("rival_skill", 0.9) / 0.9 if self.cup else 1.0)
        diff = clamp(diff, 0.4, 1.0)
        self.model, self.adapt = make_adaptation(float(app.settings.get("difficulty.adaptive_ai")))
        n_ai = 5 if self.humans == 1 else 4
        self.player_racers: list[Racer] = []
        grid = list(range(self.humans + n_ai))
        random.Random(seed).shuffle(grid)
        for h in range(self.humans):
            spec = ss.spec(self.vids[h])
            r = self.race.add(app.world.profile["name"] if h == 0 else "Player 2", spec, human=h, grid_slot=len(self.race.racers))
            self.player_racers.append(r)
        for k in range(n_ai):
            vid = AI_VEH[k % len(AI_VEH)]
            spec = ss.garage.spec(vid, {})
            lm = LineModel(self.track, spec)
            drv = Driver(lm, PERS[k % len(PERS)], diff, seed * 7 + k, self.adapt)
            self.race.add(AI_NAMES[k], spec, driver=drv, color=mix(spec.accent, (255, 255, 255), 0.0))
        self.race.on_pass = self._on_pass
        # viewports
        if self.humans == 1:
            self.views = [Viewport(pygame.Rect(0, 0, W, H), self.player_racers[0], 0)]
        else:
            self.views = [Viewport(pygame.Rect(0, 0, W // 2 - 1, H), self.player_racers[0], 0),
                          Viewport(pygame.Rect(W // 2 + 1, 0, W // 2 - 1, H), self.player_racers[1], 1)]
        app.input.assign_local(self.humans)
        # time-trial ghost of the best lap on this track
        best = ss.data["bests"].get(track_key(seed))
        if self.kind == "trial" and best and best.get("ghost"):
            self.ghost = unpack_ghost(best["ghost"])
        self.mm = pygame.Surface((64, 64), pygame.SRCALPHA)
        self.banner = ""
        self.last_pos = [r.position for r in self.player_racers]
        self.first_time()
        app.audio.set_intensity(0.4)
        self.countdown_beeps = 0

    def first_time(self) -> None:
        seen = self.ss.data["seen"]
        if not seen.get("race"):
            seen["race"] = True
            self.app.scenes.push(Dialogue(self.app, [
                ("Pit wall", "Hold UP or A to drive, DOWN or B to brake. X is the handbrake: slide the tail to build boost."),
                ("Pit wall", "Hold Y to spend boost. Tuck in behind another car to draft and refill it. SELECT resets you to the track."),
            ], color=LENS))

    def _on_pass(self, passer: Racer, passed: Racer) -> None:
        if passer.human >= 0 and passed.human < 0:
            kind = classify_pass(self.track, passer, passed)
            if kind in ("pass_inside", "pass_outside"):
                self.model.record(kind, self.race.t + 10)

    # ------------------------------------------------------------------ pause
    def pause(self, reason: str = "", lost: int = -1) -> None:
        if self.paused or self.race.state == "finished" and self.results_shown:
            return
        self.paused = True
        self.app.scenes.push(RacePause(self, reason, lost))

    # ------------------------------------------------------------------ update
    def update(self, dt: float) -> None:
        if self.paused:
            return
        self.t += 1
        inp = self.app.input
        race = self.race
        for r in self.player_racers:
            p = inp.player(r.human)
            if race.state != "finished":
                r.ctl = human_controls(p)
        if any("PAUSE" in inp.player(s).pressed for s in range(self.humans)) and race.state != "finished":
            self.pause()
            return
        # race.step builds controls for AI itself; human controls were prepared above
        saved = {r.idx: r.ctl for r in self.player_racers}
        race.step(DT)
        for r in self.player_racers:       # step() leaves human ctl untouched (driver is None)
            pass
        self.adapt.update(race.t + 10, DT)
        self._effects()
        self._audio()
        self._countdown()
        if race.state == "finished":
            self.done_t += 1
            if not self.results_shown and self.done_t > 90:
                self._finish()
        for v in self.views:
            self._update_camera(v, dt)
        self.fx.update(DT)
        self.msgs = [(m, t - DT, c) for m, t, c in self.msgs if t > DT]

    def _countdown(self) -> None:
        r = self.race
        if r.state == "countdown":
            sec = int(math.ceil(-r.t))
            if sec != getattr(self, "_last_sec", None):
                self._last_sec = sec
                self.app.audio.play("countdown_beep", 0.8)
        if r.events and any(e[0] == "go" for e in r.events):
            self.app.audio.play("countdown_beep", 1.0)

    def _update_camera(self, v: Viewport, dt: float) -> None:
        c = v.racer.car
        look = Vector2(c.vx, c.vy) * 0.34
        target = Vector2(c.x, c.y) + look
        k = 1 - math.exp(-5.5 * DT)
        v.cam += (target - v.cam) * k
        v.shake = max(0.0, v.shake - 0.05)

    def _effects(self) -> None:
        race = self.race
        for r in race.racers:
            c = r.car
            for kind, data in r.events:
                if kind == "wall" or kind == "bump":
                    if r.human >= 0:
                        self.views[min(r.human, len(self.views) - 1)].shake = min(1.0, data / 180)
                        FEEL.add_hitstop(0)
                    self.fx.emit((c.x, c.y), 6, (30, 90), (0, 360), (0.2, 0.5), (1, 2.5), (250, 246, 238), (190, 186, 172))
                    self.app.audio.play("slipstream_bump", clamp(data / 150, 0.2, 1.0))
                elif kind == "gate":
                    if r.human >= 0:
                        self.app.audio.play("lap_checkpoint", 0.4)
                elif kind == "lap" and r.human >= 0:
                    msg = f"LAP {r.laps_done}  {self._fmt(data)}"
                    self.msgs.append((msg + ("  BEST" if r.best_flag else ""), 2.5, (255, 244, 205)))
                    r.best_flag = False
                    self.app.audio.play("lap_checkpoint", 0.8)
                elif kind == "finish" and r.human >= 0:
                    self.msgs.append((f"FINISH  P{data}", 4.0, (255, 226, 130)))
                    self.app.audio.play("victory_sting" if data <= 3 else "ui_confirm", 0.9)
                elif kind == "shortcut" and r.human >= 0:
                    self.msgs.append(("SHORTCUT", 1.5, LENS))
                elif kind == "rewind":
                    self.msgs.append(("REWIND", 1.2, (182, 150, 255)))
                    self.app.audio.play("slipstream_rewind", 0.9)
                elif kind == "respawn" and r.human >= 0:
                    self.msgs.append(("BACK ON TRACK", 1.2, DIM))
            # tyre marks, dust and boost flames
            h = c.heading
            cs, sn = math.cos(h), math.sin(h)
            if c.skid > 0.35:
                for sgn in (-1, 1):
                    wx = c.x - cs * c.spec.length * 0.3 - sn * sgn * c.spec.width * 0.45
                    wy = c.y - sn * c.spec.length * 0.3 + cs * sgn * c.spec.width * 0.45
                    px, py = int(wx - self.origin[0]), int(wy - self.origin[1])
                    if 0 <= px < self.skids.get_width() and 0 <= py < self.skids.get_height():
                        pygame.draw.circle(self.skids, (40, 40, 60, int(70 * c.skid)), (px, py), 1)
                if race.frame % 2 == 0:
                    self.fx.emit((c.x - cs * c.spec.length * 0.35, c.y - sn * c.spec.length * 0.35), 1, (10, 40),
                                 (0, 360), (0.3, 0.7), (1.5, 3), (252, 250, 244), (206, 202, 190))
            if c.boosting:
                for _ in range(2):
                    self.fx.emit((c.x - cs * c.spec.length * 0.5, c.y - sn * c.spec.length * 0.5), 1, (40, 110),
                                 (math.degrees(h) + 160, math.degrees(h) + 200), (0.1, 0.25), (2, 3.5),
                                 (255, 214, 120), (239, 75, 51), glow=10)
            if r.zone in ("rough", "cut") and c.speed > 60 and race.frame % 3 == 0:
                self.fx.emit((c.x, c.y), 1, (10, 40), (0, 360), (0.3, 0.6), (1.5, 3), (200, 176, 140), (150, 130, 104))
        # ranking sounds / music
        pr = self.player_racers[0]
        lead_close = abs(self.race.gap_to_leader(pr)) < 60
        final = pr.laps_done >= race.laps - 1
        self.app.audio.set_intensity(0.45 + (0.25 if final else 0) + (0.25 if lead_close else 0) + (0.1 if pr.car.boosting else 0))

    def _audio(self) -> None:
        for r in self.player_racers:
            c = r.car
            self.engine_phase[r.human] += (18 + 150 * c.rpm) * DT
            if self.engine_phase[r.human] >= 1.0:
                self.engine_phase[r.human] -= 1.0
                if self.race.state != "countdown" or c.rpm > 0.3:
                    self.app.audio.play("slipstream_put", 0.18 + 0.12 * c.rpm, pan=-0.4 + 0.8 * r.human if self.humans > 1 else 0)
            if c.skid > 0.5 and self.race.frame % 9 == 0:
                self.app.audio.play("slipstream_skid", 0.25 * c.skid)
            if c.boosting and self.race.frame % 10 == 0:
                self.app.audio.play("slipstream_boost", 0.3)

    @staticmethod
    def _fmt(t: float) -> str:
        m = int(t // 60)
        return f"{m}:{t - 60 * m:05.2f}"

    # ------------------------------------------------------------------ finish
    def _finish(self) -> None:
        self.results_shown = True
        race = self.race
        d = self.ss.data
        res = race.results
        pr = self.player_racers[0]
        if not self.stats_counted:
            self.stats_counted = True
            d["stats"]["races"] += 1
            if pr.position == 1:
                d["stats"]["wins"] += 1
            if self.humans == 1:
                pos = pr.position
                self.prize = int(PRIZE[min(pos, len(PRIZE)) - 1] * race.laps / 3) if self.kind != "trial" else 0
                d["credits"] += self.prize
            # best lap / time trial ghost
            if self.humans == 1 and pr.best_lap > 0:
                key = track_key(self.seed)
                best = d["bests"].get(key)
                if best is None or pr.best_lap < best["time"]:
                    d["bests"][key] = {"time": round(pr.best_lap, 3), "vehicle": self.vids[0],
                                       "ghost": pack_ghost(self._best_lap_ghost(pr)) if self.kind == "trial" else
                                       (best or {}).get("ghost", "")}
            if self.kind == "cup" and self.cup_state:
                self._cup_points(res)
        self.ss.set_screen(ResultsScreen(self.ss, self))

    def _best_lap_ghost(self, r: Racer) -> list:
        # samples are every 2 ticks; cut the fastest lap out of the recording (laps are consecutive)
        if not r.lap_times:
            return r.ghost_samples[:1800]
        k = min(range(len(r.lap_times)), key=lambda i: r.lap_times[i])
        start = int(sum(r.lap_times[:k]) * 30)
        end = start + int(r.lap_times[k] * 30)
        return r.ghost_samples[start:end]

    def _cup_points(self, res: list) -> None:
        pts = self.cup.get("points", [10, 6, 4, 3, 2, 1])
        cs = self.cup_state
        for pos, r in enumerate(res, 1):
            cs["points"][r.name] = cs["points"].get(r.name, 0) + (pts[pos - 1] if pos <= len(pts) else 0)

    # ------------------------------------------------------------------ draw
    def draw(self, surf: pygame.Surface) -> None:
        race = self.race
        surf.fill(art.INK)
        for v in self.views:
            self._draw_view(v)
            surf.blit(v.surf, v.rect.topleft)
            self._draw_hud(surf, v)
        if len(self.views) == 2:
            pygame.draw.rect(surf, art.INK, (W // 2 - 1, 0, 2, H))
        if race.state == "countdown":
            n = int(math.ceil(-race.t))
            f = self.app.font
            f.draw(surf, str(max(1, n)), (W // 2, 70), (255, 244, 205), art.INK, anchor="midtop", scale=8)
        elif race.t < 1.0 and race.state == "racing":
            self.app.font.draw(surf, "GO!", (W // 2, 70), (255, 226, 130), art.INK, anchor="midtop", scale=8)
        yy = 92
        for m, t, c in self.msgs[-3:]:
            self.app.font.draw(surf, m, (W // 2, yy), c, art.INK, anchor="midtop", scale=2)
            yy += 20

    def _draw_view(self, v: Viewport) -> None:
        s = v.surf
        vw, vh = v.rect.size
        shake = Vector2(math.sin(self.t * 1.7), math.cos(self.t * 2.3)) * v.shake * 5 * FEEL.shake_scale
        cx = int(v.cam.x - vw / 2 + shake.x)
        cy = int(v.cam.y - vh / 2 + shake.y)
        s.fill(art.SALT_WHITE)
        s.blit(self.baked, (self.origin[0] - cx, self.origin[1] - cy))
        s.blit(self.skids, (self.origin[0] - cx, self.origin[1] - cy))
        # ghost
        if self.ghost and self.race.t > 0:
            pose = ghost_pose(self.ghost, self.race.t)
            if pose:
                spec = self.ss.spec(self.vids[0])
                gs = self.ss.sprites.get(spec, (182, 150, 255), pose[2]).copy()
                gs.set_alpha(120)
                s.blit(gs, (pose[0] - cx - gs.get_width() // 2, pose[1] - cy - gs.get_height() // 2))
        v.shadow.fill((0, 0, 0, 0))
        for r in self.race.racers:
            art.car_shadow(v.shadow, r.car.x - cx, r.car.y - cy, r.spec, r.car.heading)
        s.blit(v.shadow, (0, 0))
        self.fx.draw(s, (cx, cy))
        for r in sorted(self.race.racers, key=lambda q: q.car.y):
            c = r.car
            spr = self.ss.sprites.get(r.spec, r.color, c.heading)
            if c.ghost_t > 0 and int(self.t / 3) % 2 == 0:
                spr = spr.copy()
                spr.set_alpha(120)
            s.blit(spr, (c.x - cx - spr.get_width() // 2, c.y - cy - spr.get_height() // 2))
            if r.human >= 0 and len(self.views) > 1 or r is v.racer:
                pass
            else:
                tag = r.name[:3].upper()
                self.app.font.draw(s, tag, (c.x - cx, c.y - cy - 16), (255, 255, 255), art.INK, anchor="midbottom", scale=1)
        # dust-storm haze when the viewed car is inside a storm
        if v.racer.in_dust:
            haze = pygame.Surface((vw, vh), pygame.SRCALPHA)
            haze.fill((206, 184, 150, 140))
            s.blit(haze, (0, 0))
        else:
            for h in self.track.hazards:
                if h.kind == "dust":
                    px, py = h.x - cx, h.y - cy
                    if -h.r < px < vw + h.r and -h.r < py < vh + h.r:
                        hz = pygame.Surface((int(h.r * 2), int(h.r * 2)), pygame.SRCALPHA)
                        for k in range(5):
                            pygame.draw.circle(hz, (206, 184, 150, 26), (int(h.r + math.sin(self.t * 0.02 + k) * h.r * 0.4),
                                                                          int(h.r + math.cos(self.t * 0.027 + k * 2) * h.r * 0.4)),
                                               int(h.r * (0.5 + 0.1 * k)))
                        s.blit(hz, (px - h.r, py - h.r))

    def _draw_hud(self, surf: pygame.Surface, v: Viewport) -> None:
        f = self.app.font
        r = v.racer
        c = r.car
        race = self.race
        x0, w = v.rect.x, v.rect.w
        pos = f"{r.position}/{len(race.racers)}"
        draw_panel(surf, pygame.Rect(x0 + 4, 4, 62, 30), fill=INK, alpha=215)
        f.draw(surf, pos, (x0 + 10, 7), (255, 244, 205), None, scale=2)
        f.draw(surf, f"LAP {min(r.laps_done + 1, race.laps)}/{race.laps}", (x0 + 10, 24), PARCHMENT, None)
        t = max(0.0, race.t)
        f.draw(surf, self._fmt(t), (x0 + w - 6, 6), (255, 244, 205), art.INK, anchor="topright")
        if r.best_lap:
            f.draw(surf, f"best {self._fmt(r.best_lap)}", (x0 + w - 6, 18), PARCHMENT, art.INK, anchor="topright")
        # speed and boost
        kmh = int(c.speed * 0.9)
        bx, by = x0 + 6, H - 40
        draw_panel(surf, pygame.Rect(bx - 2, by - 4, 110, 38), fill=INK, alpha=215)
        f.draw(surf, f"{kmh}", (bx + 6, by), (255, 244, 205), None, scale=2)
        f.draw(surf, "km/h", (bx + 42, by + 8), DIM, None)
        cap = c.spec.boost_cap
        pygame.draw.rect(surf, (50, 46, 70), (bx + 4, by + 20, 100, 6))
        pygame.draw.rect(surf, (255, 214, 120) if c.boosting else art.ULTRA, (bx + 4, by + 20, int(100 * clamp(c.boost / cap)), 6))
        if c.bank > 0:
            pygame.draw.rect(surf, LENS, (bx + 4 + int(100 * clamp(c.boost / cap)), by + 20,
                                          min(100 - int(100 * clamp(c.boost / cap)), int(100 * clamp(c.bank / cap))), 6))
        if c.spec.special == "rewind":
            f.draw(surf, "REWIND READY" if r.rewind_ready else "rewind spent", (bx + 4, by + 29),
                   (182, 150, 255) if r.rewind_ready else DIM, None)
        # minimap
        mx, my = x0 + w - 70, H - 72
        surf.blit(self.mini, (mx, my))
        for q in race.racers:
            px = (q.car.x - self.mini_org[0]) * self.mini_scale + 3
            py = (q.car.y - self.mini_org[1]) * self.mini_scale + 3
            col = (255, 255, 255) if q is r else (q.color if q.human >= 0 else (239, 75, 51))
            pygame.draw.circle(surf, art.INK, (mx + int(px), my + int(py)), 3 if q is r else 2)
            pygame.draw.circle(surf, col, (mx + int(px), my + int(py)), 2 if q is r else 1)
        if r.wrong_way_t > 1.5 and race.state == "racing":
            f.draw(surf, "WRONG WAY", (x0 + w // 2, 120), DANGER, art.INK, anchor="midtop", scale=2)
        if c.drifting and c.bank > 8:
            f.draw(surf, "DRIFT", (x0 + w // 2, H - 30), LENS, art.INK, anchor="midtop")
        if len(self.views) == 2:
            f.draw(surf, f"P{v.slot + 1}", (x0 + w // 2, 4), art.ULTRA if v.slot == 0 else art.VERM, art.INK, anchor="midtop", scale=1)


class RacePause(MenuScene):
    def __init__(self, rs: RaceScreen, reason: str, lost: int):
        self.rs = rs
        self.reason = reason
        self.lost = lost
        super().__init__(rs.app, "PAUSED" if not reason else "CONTROLLER", self._items, 220, overlay=True,
                         footer=[("CONFIRM", "Select")] + ([] if lost >= 0 else [("BACK", "Resume")]))

    def _items(self) -> list[MenuItem]:
        a, rs = self.app, self.rs
        items: list[MenuItem] = []
        if self.reason:
            items.append(MenuItem(self.reason, kind="label"))
            ok = self.lost < 0 or bool(a.input.slots[self.lost].devices) and not a.input.slots[self.lost].lost_pad
            items.append(MenuItem("Resume" if ok else "Waiting for controller...", self._resume, enabled=ok))
            items.append(MenuItem("Play on keyboard", self._keyboard))
        else:
            items.append(MenuItem("Resume", self._resume))
        items += [MenuItem("Restart race", self._restart), MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                  MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))), MenuItem("Quit to Slipstream menu", self._quit)]
        return items

    def update(self, dt: float) -> None:
        if self.lost >= 0 and self.reason:
            slot = self.app.input.slots[self.lost]
            if slot.devices and not slot.lost_pad:
                self.reason, self.lost = f"Controller reconnected for player {self.lost + 1}", -1
                self.rebuild()
        super().update(dt)

    def on_exit(self) -> None:
        self.rs.paused = False

    def _resume(self) -> None:
        self.app.scenes.pop()

    def _keyboard(self) -> None:
        self.app.input.assign_local(self.rs.humans)
        self.lost = -1
        self.reason = "Switched to keyboard"
        self.rebuild()

    def _restart(self) -> None:
        self.app.scenes.pop()
        rs = self.rs
        rs.ss.set_screen(RaceScreen(rs.ss, rs.kind, rs.vids, rs.cup, rs.cup_state))

    def _quit(self) -> None:
        self.app.scenes.pop()
        self.rs.ss.show_menu()


class ResultsScreen(Scene):
    def __init__(self, ss: SlipScene, rs: RaceScreen):
        super().__init__(ss.app)
        self.ss = ss
        self.rs = rs
        self.t = 0
        self.cup_done = False
        self.cup_win = False
        self.facet = False
        if rs.kind == "cup" and rs.cup_state:
            cs = rs.cup_state
            cs["round"] += 1
            if cs["round"] >= len(rs.cup["tracks"]):
                self.cup_done = True
                standings = sorted(cs["points"].items(), key=lambda kv: -kv[1])
                me = ss.app.world.profile["name"]
                self.cup_win = bool(standings) and standings[0][0] == me
                if self.cup_win:
                    d = ss.data
                    cid = rs.cup["id"]
                    if cid not in d["cups_won"]:
                        d["cups_won"].append(cid)
                    d["credits"] += int(rs.cup.get("prize", 0))
                    ss.app.world.emit("slipstream.championship_won", cup=cid)
                    if cid == "salt_cup":
                        self.facet = ss.app.world.complete_facet("slipstream")
                        d["summary"] = "Salt Cup won"
        ss.app.save_now()

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t < 40:
            return
        rs = self.rs
        if "CONFIRM" in p.pressed:
            if rs.kind == "cup" and not self.cup_done:
                self.ss.set_screen(RaceScreen(self.ss, "cup", rs.vids, rs.cup, rs.cup_state))
            elif rs.kind == "cup":
                self.ss.show_menu()
            else:
                self.ss.set_screen(RaceScreen(self.ss, rs.kind, rs.vids, rs.cup))
        elif "BACK" in p.pressed:
            self.ss.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        rs = self.rs
        surf.fill(art.SALT_WHITE)
        pygame.draw.polygon(surf, art.VERM, [(0, 0), (W, 0), (W, 30), (0, 30)])
        f.draw(surf, "RESULTS  " + rs.track_name.upper(), (12, 8), (246, 244, 238), art.INK, scale=2)
        draw_panel(surf, pygame.Rect(30, 42, 420, 160), fill=INK, alpha=240)
        for pos, r in enumerate(rs.race.results[:6], 1):
            y = 52 + (pos - 1) * 18
            col = (255, 226, 130) if pos == 1 else PARCHMENT
            if r.human >= 0:
                pygame.draw.rect(surf, INK_2, (36, y - 2, 408, 16))
            f.draw(surf, f"{pos}", (44, y), col, None, scale=1)
            f.draw(surf, r.name, (62, y), col, None)
            f.draw(surf, r.spec.name, (170, y), DIM, None)
            f.draw(surf, rs._fmt(r.finish_time) if r.finished else "DNF", (300, y), col, None)
            f.draw(surf, f"best {rs._fmt(r.best_lap)}" if r.best_lap else "", (370, y), DIM, None)
        yy = 208
        if rs.prize:
            f.draw(surf, f"Prize: +{rs.prize} salt", (30, yy), GOOD, art.INK)
            yy += 12
        if rs.kind == "cup" and rs.cup_state:
            pts = sorted(rs.cup_state["points"].items(), key=lambda kv: -kv[1])[:4]
            f.draw(surf, "Standings: " + "  ".join(f"{n} {p}" for n, p in pts), (30, yy), BRASS, art.INK)
            yy += 12
        if self.cup_done:
            msg = "CHAMPION!  Facet repaired" if self.facet else ("CHAMPION!" if self.cup_win else "The cup goes elsewhere. Try again.")
            f.draw(surf, msg, (W // 2, 232), (255, 226, 130) if self.cup_win else DANGER, art.INK, anchor="midtop", scale=2)
        if self.t > 40:
            draw_prompts(surf, self.app, [("CONFIRM", "Continue" if rs.kind == "cup" and not self.cup_done else "Again"), ("BACK", "Menu")])
