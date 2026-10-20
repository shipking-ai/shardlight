"""Masks scene: menus, character select, the match screen, training tools, replays and the arcade ladder."""
from __future__ import annotations

import math
import random
from typing import Any

import pygame

from ...core import art
from ...core.fx import FEEL, clamp, ease_out_cubic, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Menu, MenuItem, MenuScene,
                        SettingsScene, ControlsScene, Dialogue, draw_panel, draw_prompts)
from . import render, replay
from .cpu import CpuBrain
from .info import INFO
from .sim import consts as C
from .sim.fight import Match
from .sim.moves import Character
from .sim.roster import load_roster

W, H = 480, 270
RIVAL_IDS = {"toki": "warden_of_hours"}        # echo payload names differ from character ids for a few fighters
SAVE_V = 1


def read_mask(player) -> int:
    m = 0
    for b, bit in C.LOGICAL_TO_BIT.items():
        if b in player.down or b in player.pressed:      # a tap shorter than one tick still registers
            m |= bit
    return m


def bits_text(mask: int) -> str:
    s = ""
    d = {C.UP: "u", C.DOWN: "d", C.LEFT: "l", C.RIGHT: "r"}
    s += "".join(v for k, v in d.items() if mask & k)
    s += "".join(n for n, b in (("L", C.LP), ("M", C.MP), ("H", C.HP), ("P", C.PAR)) if mask & b)
    return s or "-"


class MasksScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.roster: dict[str, Character] = {}
        self.screen: Scene | None = None
        self.cpu_level = int(opts.get("cpu", 2))
        self.players = int(opts.get("players", 1))
        self.pad_lost = -1
        self.t = 0

    # ------------------------------------------------------------------ lifecycle
    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("arcade_clears", 0)
        d.setdefault("replays", [])
        d.setdefault("training", {"hp": True, "meter": True, "boxes": False, "inputs": True, "frames": True})
        d.setdefault("seen", {})
        self.roster = load_roster(self.app.content)
        self.app.audio.play_music("masks", 1.2, 0.3)
        if not self.roster:
            self.app.toast("No fighters could be loaded", DANGER)
        self.show_menu()

    def available(self) -> list[Character]:
        w = self.app.world
        return [c for c in self.roster.values()
                if c.selectable and (not c.requires_unlock or w.has_unlock(c.requires_unlock))]

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen is not None:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen is not None:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, FightScreen):
            self.screen.pause(f"Controller for player {slot + 1} disconnected", lost=slot)

    # ------------------------------------------------------------------ navigation helpers
    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.input.assign_local(1)
        self.app.audio.set_intensity(0.25)
        self.set_screen(MainMenu(self))

    def start_select(self, kind: str) -> None:
        self.set_screen(SelectScreen(self, kind))

    def start_match(self, kind: str, ids: tuple[str, str], cpu: tuple[int | None, int | None] = (None, None),
                    arcade: dict | None = None, replay_rec: dict | None = None) -> None:
        self.set_screen(FightScreen(self, kind, ids, cpu, arcade, replay_rec))


# ====================================================================================== main menu
class MainMenu(Scene):
    def __init__(self, ms: MasksScene):
        super().__init__(ms.app)
        self.ms = ms
        self.t = 0
        items = [
            MenuItem("Arcade ladder", lambda: ms.start_select("arcade")),
            MenuItem("Versus (2 players)", lambda: self._versus()),
            MenuItem("Versus CPU", lambda: ms.start_select("vscpu")),
            MenuItem("Training", lambda: ms.start_select("training")),
            MenuItem("Replays", lambda: ms.set_screen(ReplayList(ms)), enabled=bool(ms.data["replays"])),
            MenuItem("Move lists", lambda: ms.set_screen(MoveList(ms, None))),
            MenuItem("Return to hub", lambda: ms.finish(left=True)),
        ]
        self.menu = Menu(self.app, items, 170)
        self.rng = random.Random(5)

    def _versus(self) -> None:
        self.app.input.assign_local(2)
        self.ms.start_select("versus")

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
        p = self.inp.player(0)
        if "BACK" in p.pressed and self.t > 10:
            self.ms.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        st = self._stage()
        st.draw(surf, 0, self.t)
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((18, 14, 30, 120))
        surf.blit(shade, (0, 0))
        f = self.app.font
        f.draw(surf, "MASKS", (W // 2, 20), (244, 234, 214), (30, 18, 30), anchor="midtop", scale=5)
        f.draw(surf, "The Gauntlet", (W // 2, 62), PARCHMENT, (30, 18, 30), anchor="midtop", scale=2)
        draw_panel(surf, pygame.Rect(W // 2 - 100, 96, 200, 120), fill=INK, alpha=225)
        self.menu.draw(surf, (W // 2 - 94, 102))
        n = self.ms.data.get("arcade_clears", 0)
        f.draw(surf, f"Ladder clears: {n}", (W // 2, 220), DIM, (10, 8, 20), anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])

    def _stage(self):
        if not hasattr(self, "_st"):
            self._st = render.Stage("shrine", 3)
        return self._st


# ====================================================================================== character select
class SelectScreen(Scene):
    def __init__(self, ms: MasksScene, kind: str):
        super().__init__(ms.app)
        self.ms = ms
        self.kind = kind
        self.chars = ms.available()
        self.cur = [0, min(1, len(self.chars) - 1)]
        self.locked = [False, False]
        self.two = kind == "versus"
        self.cpu_level = ms.cpu_level
        self.t = 0
        self.stage = render.Stage("shrine", 3)

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t < 6:
            return
        for s in range(2 if self.two else 1):
            p = self.inp.player(s)
            dx, dy = p.menu_dir()
            if not self.locked[s]:
                if dx or dy:
                    n = len(self.chars)
                    self.cur[s] = (self.cur[s] + dx + dy * 4) % n
                    self.app.audio.play("ui_move", 0.5)
                if "CONFIRM" in p.pressed or "A" in p.pressed:
                    self.locked[s] = True
                    self.app.audio.play("ui_confirm", 0.8)
            elif "BACK" in p.pressed or "B" in p.pressed:
                self.locked[s] = False
        p0 = self.inp.player(0)
        if self.kind == "vscpu" and ("L" in p0.pressed or "R" in p0.pressed):
            self.cpu_level = 1 + (self.cpu_level - 1 + (1 if "R" in p0.pressed else -1)) % 4
        if "BACK" in p0.pressed and not any(self.locked):
            self.ms.show_menu()
            return
        if all(self.locked[:2 if self.two else 1]):
            self._go()

    def _go(self) -> None:
        a = self.chars[self.cur[0]].id
        rng = random.Random(self.t)
        if self.kind == "arcade":
            ladder = [c.id for c in self.ms.available() if c.id != a and c.archetype != "boss"]
            ladder.sort(key=lambda i: (self.ms.roster[i].requires_unlock != "", i))
            order = [i for i in ladder if not self.ms.roster[i].requires_unlock] + \
                    [i for i in ladder if self.ms.roster[i].requires_unlock]
            boss = next((c.id for c in self.ms.roster.values() if c.boss), None)
            if boss:
                order.append(boss)
            self.ms.start_match("arcade", (a, order[0]), (None, 2), {"order": order, "step": 0, "pick": a,
                                                                    "defeated": []})
        elif self.kind == "versus":
            self.ms.start_match("versus", (a, self.chars[self.cur[1]].id), (None, None))
        elif self.kind == "vscpu":
            b = rng.choice([c.id for c in self.chars])
            self.ms.cpu_level = self.cpu_level
            self.ms.start_match("vscpu", (a, b), (None, self.cpu_level))
        else:
            b = self.chars[(self.cur[0] + 1) % len(self.chars)].id
            self.ms.start_match("training", (a, b), (None, None))

    def draw(self, surf: pygame.Surface) -> None:
        self.stage.draw(surf, 0, self.t)
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((18, 14, 30, 150))
        surf.blit(shade, (0, 0))
        f = self.app.font
        title = {"arcade": "ARCADE - choose your mask", "versus": "VERSUS - choose masks",
                 "vscpu": "VS CPU - choose your mask", "training": "TRAINING - choose your mask"}[self.kind]
        f.draw(surf, title, (W // 2, 10), (250, 240, 220), (20, 12, 28), anchor="midtop", scale=2)
        cols = 4
        for i, c in enumerate(self.chars):
            x = 40 + (i % cols) * 96
            y = 40 + (i // cols) * 58
            r = pygame.Rect(x, y, 90, 52)
            sel = [s for s in range(2) if self.cur[s] == i and (s == 0 or self.two)]
            col = c.color
            pygame.draw.rect(surf, (20, 16, 34), r)
            pygame.draw.rect(surf, mix(col, (20, 16, 34), 0.6), r.inflate(-4, -4))
            render.draw_mask(surf, c.id, (r.x + 22, r.y + 26), 12, 0, c.color, c.accent, self.t)
            f.draw(surf, c.name, (r.x + 40, r.y + 14), (255, 246, 226), (10, 8, 20))
            f.draw(surf, c.archetype, (r.x + 40, r.y + 28), c.accent, (10, 8, 20), scale=1)
            for s in sel:
                bc = LENS if s == 0 else (255, 150, 120)
                pygame.draw.rect(surf, bc, r, 2 if not self.locked[s] else 3)
                f.draw(surf, f"P{s + 1}", (r.x + 3 + s * 14, r.y + 3), bc, (10, 8, 20))
        # info panel for each active cursor
        for s in range(2 if self.two else 1):
            c = self.chars[self.cur[s]]
            px = 20 if s == 0 else W // 2 + 4
            rect = pygame.Rect(px, 160, W // 2 - 24, 84)
            draw_panel(surf, rect, border=c.color, fill=INK, alpha=235, title=f"{'P' + str(s + 1)} {c.title}", font=f)
            f.draw_wrapped(surf, c.desc, pygame.Rect(rect.x + 8, rect.y + 10, rect.w - 16, 30), PARCHMENT, None, max_lines=3)
            f.draw_wrapped(surf, c.mech, pygame.Rect(rect.x + 8, rect.y + 42, rect.w - 16, 30), LENS, None, max_lines=3)
            f.draw(surf, f"HP {c.health}", (rect.right - 8, rect.bottom - 12), DIM, None, anchor="topright")
            if self.locked[s]:
                f.draw(surf, "READY", (rect.right - 8, rect.y + 2), GOOD, None, anchor="topright")
        extra = f"CPU level {self.cpu_level}  (L/R)" if self.kind == "vscpu" else ""
        pr = [("CONFIRM", "Lock in"), ("BACK", "Back")]
        draw_prompts(surf, self.app, pr)
        if extra:
            f.draw(surf, extra, (W // 2, 248), BRASS, (10, 8, 20), anchor="midtop")


# ====================================================================================== fight screen
class FightScreen(Scene):
    def __init__(self, ms: MasksScene, kind: str, ids: tuple[str, str], cpu: tuple[int | None, int | None],
                 arcade: dict | None, replay_rec: dict | None):
        super().__init__(ms.app)
        self.ms = ms
        self.kind = kind
        self.ids = ids
        self.arcade = arcade
        self.rec = replay_rec
        self.chars = (ms.roster[ids[0]], ms.roster[ids[1]])
        training = kind == "training"
        seed = random.Random(ms.t * 977 + ms.app.rng.randrange(1 << 20)).randrange(1, 1 << 30)
        rounds = 2 if kind != "training" else 2
        if replay_rec:
            self.match = replay.rebuild(replay_rec, ms.roster)
            self.frames = replay.decode(replay_rec["rle"])
            self.pos = 0
        else:
            self.match = Match(self.chars, seed=seed, rounds=rounds, training=training)
            self.match.record = not training
        self.cpu = [None, None]
        diff_scale = ms.app.settings.get("difficulty.preset")
        base = {"story": -1, "standard": 0, "hard": 1}[diff_scale]
        adapt = float(ms.app.settings.get("difficulty.adaptive_ai"))
        for i, lvl in enumerate(cpu):
            if lvl is not None and not replay_rec:
                if kind == "arcade" and arcade:
                    lvl = max(1, min(4, 1 + arcade["step"] // 2 + base))
                    if self.chars[1].boss:
                        lvl = 4
                self.cpu[i] = CpuBrain(lvl, seed, adapt, i)
        # training dummy
        self.dummy_mode = "stand"
        self.dummy_rec: list[int] = []
        self.recording = False
        self.dummy_play: list[int] = []
        self.dummy_pos = 0
        self.cpu_dummy = None
        self.tr = ms.data["training"]
        self.stage = render.Stage("shrine" if (seed % 2 == 0 or replay_rec) else "rain", seed % 7)
        self.sparks = render.Sparks()
        self.t = 0
        self.banner = ""
        self.banner_t = 0.0
        self.paused_overlay = False
        self.chip = [1.0, 1.0]
        self.trauma = 0.0
        self.slow = 0
        self.flash_super = 0
        self.history: list[list[int]] = [[], []]
        self.result_timer = 0
        self.done = False
        self.scale_hist = 0
        self.speed_credit = 0.0
        self.tut = 0

    def on_enter(self, **kw) -> None:
        self.app.input.assign_local(2 if self.kind == "versus" else 1)
        self.apply_training()
        self.app.audio.set_intensity(0.5)
        if self.kind == "training" and not self.ms.data["seen"].get("training"):
            self.ms.data["seen"]["training"] = True
            self.app.scenes.push(Dialogue(self.app, [
                ("Training", "A, B and X are light, medium and heavy. Y is parry: press it just before a hit lands."),
                ("Training", "Quarter circle is down, down-forward, forward plus a button. Press SELECT for options and frame data."),
            ], color=LENS))
        elif self.kind == "arcade" and not self.ms.data["seen"].get("arcade"):
            self.ms.data["seen"]["arcade"] = True
            self.app.scenes.push(Dialogue(self.app, [
                ("Gauntlet", "Win two rounds to answer each mask. Blocked attacks leave you plus or minus - learn which."),
            ], color=LENS))

    # ------------------------------------------------------------------ training helpers
    def apply_training(self) -> None:
        m = self.match
        if self.kind == "training":
            m.infinite_health = bool(self.tr.get("hp", True))
            m.infinite_meter = bool(self.tr.get("meter", True))

    def pause(self, reason: str = "", lost: int = -1) -> None:
        if self.paused_overlay or self.done:
            return
        self.paused_overlay = True
        self.app.scenes.push(MatchPause(self, reason, lost))

    # ------------------------------------------------------------------ update
    def _inputs(self) -> tuple[int, int]:
        m = self.match
        inp = self.app.input
        if self.rec:
            if self.pos < len(self.frames):
                pair = self.frames[self.pos]
                self.pos += 1
                return pair
            return (0, 0)
        masks = [0, 0]
        if self.kind in ("versus",):
            masks[0] = read_mask(inp.player(0))
            masks[1] = read_mask(inp.player(1))
        else:
            masks[0] = read_mask(inp.player(0))
            if self.cpu[1] is not None:
                masks[1] = self.cpu[1].act(m)
            elif self.kind == "training":
                masks[1] = self._dummy(masks)
        return (masks[0], masks[1])

    def _dummy(self, masks) -> int:
        f2 = self.match.fighters[1]
        back = C.RIGHT if f2.facing < 0 else C.LEFT
        mode = self.dummy_mode
        if self.recording:
            masks_raw = read_mask(self.inp.player(0))
            self.dummy_rec.append(masks_raw)
            masks[0] = 0
            if len(self.dummy_rec) > 360:
                self.stop_recording()
            return masks_raw
        if mode == "stand":
            return 0
        if mode == "crouch":
            return C.DOWN
        if mode == "block":
            return back
        if mode == "crouchblock":
            return back | C.DOWN
        if mode == "jump":
            return C.UP if self.t % 90 == 0 else 0
        if mode == "playback" and self.dummy_play:
            m = self.dummy_play[self.dummy_pos % len(self.dummy_play)]
            self.dummy_pos += 1
            return m if f2.facing > 0 else m
        if mode == "cpu":
            if self.cpu_dummy is None:
                self.cpu_dummy = CpuBrain(3, 1, 1.0, 1)
            return self.cpu_dummy.act(self.match)
        return 0

    def stop_recording(self) -> None:
        self.recording = False
        self.dummy_play = list(self.dummy_rec)
        self.dummy_mode = "playback" if self.dummy_play else "stand"
        self.dummy_pos = 0
        self.app.toast(f"Dummy recorded ({len(self.dummy_play)} frames)", GOOD)

    def update(self, dt: float) -> None:
        self.t += 1
        m = self.match
        p0 = self.inp.player(0)
        if self.done:
            self._result_update()
            return
        if self.paused_overlay:
            return
        if "PAUSE" in p0.pressed or (self.kind == "versus" and "PAUSE" in self.inp.player(1).pressed):
            self.pause()
            return
        if self.kind == "training" and "SELECT" in p0.pressed:
            if self.recording:
                self.stop_recording()
            else:
                self.app.scenes.push(TrainingMenu(self))
                self.paused_overlay = True
            return
        speed = 1
        if m.phase == "ko" and self.slow < 36:
            self.slow += 1
            speed = 0 if self.slow % 3 else 1
        if speed:
            pair = self._inputs()
            m.step(pair)
            for i in range(2):
                self.history[i].append(pair[i])
                del self.history[i][:-14]
            self._events()
        self.sparks.update()
        self.trauma = max(0.0, self.trauma - 0.04)
        self.banner_t += dt
        for i, f in enumerate(m.fighters):
            frac = f.hp / f.char.health
            self.chip[i] = max(frac, self.chip[i] - 0.004) if self.chip[i] > frac else frac
        low = min(f.hp / f.char.health for f in m.fighters)
        self.app.audio.set_intensity(0.45 + 0.5 * (1 - clamp(low * 1.6)) if m.phase == "fight" else 0.4)
        if m.phase == "over" and not self.done and m.phase_t > 2:
            self._finish_match()

    def _events(self) -> None:
        m = self.match
        a = self.app
        for kind, x, y, d in m.events:
            sx = x
            if kind == "hit":
                self.sparks.add(sx, y, d.get("spark", "light"))
                FEEL.add_hitstop(0)
                self.trauma = min(0.9, self.trauma + (0.5 if d.get("heavy") else 0.22))
                a.audio.play("masks_hit_heavy" if d.get("heavy") else "masks_hit", 0.9, pan=clamp(x / 260, -1, 1))
                if d.get("combo", 0) >= 3 and a.settings.get("access.reduce_flash") is False:
                    FEEL.flash((255, 250, 235), 0.05)
            elif kind == "block":
                self.sparks.add(sx, y, "ring")
                a.audio.play("masks_block", 0.8, pan=clamp(x / 260, -1, 1))
            elif kind == "parry":
                self.sparks.add(sx, y, "ring")
                self.sparks.add(sx, y, "slash")
                FEEL.flash((255, 255, 255), 0.25)
                a.audio.play("masks_parry", 1.0)
            elif kind in ("clash", "armor", "counter", "tech"):
                self.sparks.add(sx, y, "ring")
                a.audio.play("masks_block", 0.7)
            elif kind == "move":
                mv = m.fighters[d["idx"]].move
                if mv:
                    heavy = mv.hit.damage >= 60 or mv.kind in ("special", "super")
                    a.audio.play("masks_swing_heavy" if heavy else "masks_swing", 0.5 if not heavy else 0.7,
                                 pan=clamp(x / 260, -1, 1))
            elif kind == "superflash":
                self.flash_super = 26
                a.audio.play("masks_super", 1.0)
            elif kind == "grab":
                a.audio.play("masks_throw", 0.9)
            elif kind == "land_hard":
                self.trauma = min(0.9, self.trauma + 0.2)
                a.audio.play("masks_thud", 0.7)
            elif kind == "ko":
                self.trauma = 1.0
                FEEL.flash((255, 255, 255), 0.5)
                a.audio.play("masks_ko", 1.0)
                self.banner, self.banner_t = "K.O.", 0
            elif kind == "fight":
                self.banner, self.banner_t = "FIGHT!", 0
                a.audio.play("masks_gong", 0.8)
        if m.phase == "intro" and m.phase_t == 1:
            self.banner, self.banner_t = f"ROUND {m.round_no}", 0
        if m.phase == "intro" and m.phase_t == 70:
            self.banner = ""
        if m.phase == "fight" and m.phase_t > 40 and self.banner == "FIGHT!":
            self.banner = ""
        if m.phase == "roundend" and m.phase_t == 1:
            w = m.round_winner
            self.banner = "DRAW" if w == -1 else ("TIME" if m.timer <= 0 else "")
            self.slow = 0

    def _finish_match(self) -> None:
        m = self.match
        self.done = True
        self.result_timer = 0
        if self.rec:
            return
        w = m.winner
        if self.kind != "training":
            recs = self.ms.data["replays"]
            recs.append(replay.make_record(m, self.ids))
            del recs[:-3]
        if self.kind == "arcade" and self.arcade is not None and w == 0:
            beaten = self.ids[1]
            self.arcade["defeated"].append(beaten)
            self.app.world.emit("masks.rival_defeated", rival=RIVAL_IDS.get(beaten, beaten))
            if self.arcade["step"] + 1 >= len(self.arcade["order"]):
                self.ms.data["arcade_clears"] = self.ms.data.get("arcade_clears", 0) + 1
                self.ms.data["summary"] = f"Gauntlet cleared {self.ms.data['arcade_clears']}x"
                self.app.world.complete_facet("masks")
                self.arcade["cleared"] = True
        self.app.save_now()

    def _result_update(self) -> None:
        self.result_timer += 1
        p = self.inp.player(0)
        if self.result_timer < 40:
            return
        if "CONFIRM" in p.pressed or "A" in p.pressed:
            w = self.match.winner
            if self.rec:
                self.ms.set_screen(ReplayList(self.ms))
            elif self.kind == "arcade" and self.arcade is not None:
                if w == 0 and not self.arcade.get("cleared"):
                    self.arcade["step"] += 1
                    nxt = self.arcade["order"][self.arcade["step"]]
                    self.ms.start_match("arcade", (self.arcade["pick"], nxt), (None, 2), self.arcade)
                elif w == 0:
                    self.ms.show_menu()
                else:
                    self.ms.start_match("arcade", self.ids, (None, 2), {**self.arcade})
            elif self.kind in ("versus", "vscpu"):
                self.ms.start_match(self.kind, self.ids, tuple(
                    (c.level if c else None) for c in self.cpu))
            else:
                self.ms.show_menu()
        elif "BACK" in p.pressed:
            self.ms.show_menu()

    # ------------------------------------------------------------------ draw
    def draw(self, surf: pygame.Surface) -> None:
        m = self.match
        fa, fb = m.fighters
        mid = (fa.x + fb.x) / 2 / C.SUB
        cam = clamp(mid, -20, 20)
        if self.trauma > 0 and FEEL.shake_scale:
            cam += math.sin(self.t * 1.9) * self.trauma * 4 * FEEL.shake_scale
        self.stage.draw(surf, cam, self.t)
        order = sorted(m.fighters, key=lambda f: (f.state == "attack" or f.hitstop > 0, f.idx))
        for f in order:
            flash = 0.0
            if f.hitstop > 0 and f.state in ("hit", "hitair"):
                flash = 0.55
            draw_x = cam
            render.draw_fighter(surf, f, draw_x, self.t, flash)
        render.draw_projectiles(surf, m, cam, self.t)
        self.sparks.draw(surf, cam)
        if self.kind == "training" and self.tr.get("boxes"):
            self._draw_boxes(surf, cam)
        if self.flash_super > 0:
            self.flash_super -= 1
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill((10, 6, 24, int(150 * self.flash_super / 26)))
            surf.blit(ov, (0, 0))
        banner = self.banner if self.banner else None
        render.draw_hud(surf, self.app, m, self.chip, banner, self.banner_t)
        if self.kind == "training":
            self._draw_training_hud(surf)
        elif self.rec:
            self.app.font.draw(surf, "REPLAY", (W // 2, 40), DIM, (10, 8, 20), anchor="midtop")
        if self.done:
            self._draw_result(surf)

    def _draw_boxes(self, surf, cam) -> None:
        from .sim.fight import world_rect
        for f in self.match.fighters:
            for r in f.hurt_rects():
                x0, y0, x1, y1 = world_rect(f.x, f.y, f.facing, r)
                pygame.draw.rect(surf, (80, 200, 255), (240 + x0 / 16 - cam, render.GROUND_Y - y1 / 16, (x1 - x0) / 16, (y1 - y0) / 16), 1)
            mv = f.move
            if mv and f.state == "attack":
                for b in mv.boxes:
                    if b.active_on(f.mf):
                        x0, y0, x1, y1 = world_rect(f.x, f.y, f.facing, b.rect)
                        pygame.draw.rect(surf, (255, 90, 80), (240 + x0 / 16 - cam, render.GROUND_Y - y1 / 16, (x1 - x0) / 16, (y1 - y0) / 16), 1)

    def _draw_training_hud(self, surf) -> None:
        f = self.app.font
        m = self.match
        if self.tr.get("frames"):
            for i in range(2):
                info = m.last_move_info[i]
                if not info:
                    continue
                x = 12 if i == 0 else W - 12
                anchor = "topleft" if i == 0 else "topright"
                mv = m.chars[i].moves.get(info["key"])
                y = 100
                f.draw(surf, mv.name if mv else info["key"], (x, y), (255, 236, 190), (10, 8, 20), anchor=anchor)
                f.draw(surf, f"startup {info['startup']}  active {info['active']}  recovery {info['recovery']}",
                       (x, y + 11), PARCHMENT, (10, 8, 20), anchor=anchor)
                ah, ab = info.get("adv_hit"), info.get("adv_block")
                f.draw(surf, f"on hit {ah:+d}" if ah is not None else "on hit -", (x, y + 22),
                       GOOD if (ah or 0) > 0 else DANGER, (10, 8, 20), anchor=anchor)
                f.draw(surf, f"on block {ab:+d}" if ab is not None else "on block -", (x, y + 33),
                       GOOD if (ab or 0) > 0 else DANGER, (10, 8, 20), anchor=anchor)
        if self.tr.get("inputs"):
            for i in range(2):
                col = [bits_text(h) for h in self.history[i][-8:]]
                x = 8 if i == 0 else W - 8
                for k, txt in enumerate(reversed(col)):
                    f.draw(surf, txt, (x, 150 + k * 9), PARCHMENT if k else (255, 236, 190), (10, 8, 20),
                           anchor="topleft" if i == 0 else "topright")
        mode = "REC" if self.recording else self.dummy_mode.upper()
        f.draw(surf, f"Dummy: {mode}", (W // 2, 36), LENS if not self.recording else DANGER, (10, 8, 20), anchor="midtop")
        f.draw(surf, "SELECT: options", (W // 2, 258), DIM, (10, 8, 20), anchor="midtop")

    def _draw_result(self, surf) -> None:
        f = self.app.font
        m = self.match
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((10, 8, 20, 170))
        surf.blit(shade, (0, 0))
        w = m.winner
        if w is None or w < 0:
            title, sub = "DRAW", ""
        else:
            title, sub = f"{m.chars[w].name.upper()} WINS", m.chars[w].title
        f.draw(surf, title, (W // 2, 80), (255, 240, 200), (10, 8, 20), anchor="midtop", scale=4)
        f.draw(surf, sub, (W // 2, 118), PARCHMENT, (10, 8, 20), anchor="midtop", scale=2)
        a = m.fighters[0]
        f.draw(surf, f"Best combo: {m.fighters[0].combo_best} / {m.fighters[1].combo_best}", (W // 2, 146), DIM, None, anchor="midtop")
        if self.kind == "arcade" and self.arcade:
            if w == 0 and self.arcade.get("cleared"):
                f.draw(surf, "THE GAUNTLET IS ANSWERED", (W // 2, 164), GOOD, (10, 8, 20), anchor="midtop", scale=2)
                f.draw(surf, "Facet repaired", (W // 2, 184), LENS, (10, 8, 20), anchor="midtop")
            elif w == 0:
                f.draw(surf, f"Next: {self.arcade['order'][self.arcade['step'] + 1].title()}", (W // 2, 168), BRASS, None, anchor="midtop")
            else:
                f.draw(surf, "Try again", (W // 2, 168), DANGER, None, anchor="midtop")
        if self.result_timer > 40:
            draw_prompts(surf, self.app, [("CONFIRM", "Continue"), ("BACK", "Menu")])


class MatchPause(MenuScene):
    def __init__(self, fs: FightScreen, reason: str, lost: int):
        self.fs = fs
        self.reason = reason
        self.lost = lost
        super().__init__(fs.app, "PAUSED" if not reason else "CONTROLLER", self._items, 220, overlay=True,
                         footer=[("CONFIRM", "Select")] + ([] if lost >= 0 else [("BACK", "Resume")]))

    def _items(self) -> list[MenuItem]:
        a, fs = self.app, self.fs
        items: list[MenuItem] = []
        if self.reason:
            items.append(MenuItem(self.reason, kind="label"))
            ok = self.lost < 0 or all(a.input.slots[s].devices for s in range(max(1, a.input.num_players)))
            items.append(MenuItem("Resume" if ok else "Waiting for controller...", self._resume, enabled=ok))
            items.append(MenuItem("Play on keyboard", self._keyboard))
        else:
            items.append(MenuItem("Resume", self._resume))
        items += [
            MenuItem("Move list", lambda: a.scenes.push(MoveListOverlay(fs))),
            MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
            MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
            MenuItem("Restart match" if fs.kind != "training" else "Reset positions", self._restart),
            MenuItem("Quit to Masks menu", self._quit),
        ]
        return items

    def update(self, dt: float) -> None:
        if self.lost >= 0:
            slot = self.app.input.slots[self.lost]
            if slot.devices and not slot.lost_pad and self.reason:
                self.reason = f"Controller reconnected for player {self.lost + 1}"
                self.lost = -1
                self.rebuild()
        super().update(dt)

    def on_exit(self) -> None:
        self.fs.paused_overlay = False

    def _resume(self) -> None:
        self.app.scenes.pop()

    def _keyboard(self) -> None:
        self.app.input.assign_local(2 if self.fs.kind == "versus" else 1)
        self.lost = -1
        self.reason = "Switched to keyboard"
        self.rebuild()

    def _restart(self) -> None:
        fs = self.fs
        self.app.scenes.pop()
        if fs.kind == "training":
            m = fs.match
            m.fighters[0].x, m.fighters[1].x = -80 * 16, 80 * 16
            m.fighters[0].hp = m.fighters[0].char.health
            m.fighters[1].hp = m.fighters[1].char.health
        else:
            lv = tuple((c.level if c else None) for c in fs.cpu)
            fs.ms.start_match(fs.kind, fs.ids, lv, fs.arcade)

    def _quit(self) -> None:
        self.app.scenes.pop()
        self.fs.ms.show_menu()

    def update_back(self) -> None:
        pass


class TrainingMenu(MenuScene):
    MODES = ["stand", "crouch", "block", "crouchblock", "jump", "cpu", "playback"]

    def __init__(self, fs: FightScreen):
        self.fs = fs
        super().__init__(fs.app, "TRAINING OPTIONS", self._items, 240, overlay=True)

    def _tog(self, key: str):
        fs = self.fs
        return dict(kind="toggle", get=lambda: fs.tr.get(key, False), set=lambda v: (fs.tr.__setitem__(key, v), fs.apply_training()))

    def _items(self) -> list[MenuItem]:
        fs = self.fs
        modes = [m for m in self.MODES if m != "playback" or fs.dummy_play]
        return [
            MenuItem("Infinite health", **self._tog("hp")),
            MenuItem("Infinite meter", **self._tog("meter")),
            MenuItem("Show hitboxes", **self._tog("boxes")),
            MenuItem("Show input history", **self._tog("inputs")),
            MenuItem("Show frame data", **self._tog("frames")),
            MenuItem("Dummy behaviour", kind="choice", choices=modes, get=lambda: fs.dummy_mode,
                     set=lambda v: setattr(fs, "dummy_mode", v)),
            MenuItem("Record dummy (5s)", self._record),
            MenuItem("Reset positions", self._reset),
            MenuItem("Close", self.app.scenes.pop),
        ]

    def _record(self) -> None:
        fs = self.fs
        fs.dummy_rec = []
        fs.recording = True
        self.app.toast("Recording: you control the dummy. SELECT stops.", LENS)
        self.app.scenes.pop()

    def _reset(self) -> None:
        m = self.fs.match
        m.fighters[0].x, m.fighters[1].x = -80 * 16, 80 * 16
        self.app.scenes.pop()

    def on_exit(self) -> None:
        self.fs.paused_overlay = False


# ====================================================================================== move list & replays
def move_rows(ch: Character) -> list[tuple[str, str, str]]:
    rows = []
    for mv in ch.moves.values():
        if not mv.notation:
            continue
        if mv.hit and mv.boxes or mv.throw or mv.projectile:
            adv = mv.adv_on(True)
            advb = mv.adv_on(False)
            rows.append((mv.name, mv.notation, f"{mv.startup}/{mv.active}/{mv.recovery}  {adv:+d}/{advb:+d}" if adv is not None else f"{mv.startup}/{mv.active}/{mv.recovery}"))
        else:
            rows.append((mv.name, mv.notation, f"{mv.startup}/{mv.active}/{mv.recovery}"))
    return rows


class MoveList(Scene):
    def __init__(self, ms: MasksScene, ch: Character | None):
        super().__init__(ms.app)
        self.ms = ms
        self.chars = ms.available()
        self.i = 0 if ch is None else max(0, [c.id for c in self.chars].index(ch.id))
        self.t = 0
        self.scroll = 0

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        dx, dy = p.menu_dir()
        if dx:
            self.i = (self.i + dx) % len(self.chars)
            self.scroll = 0
        if dy:
            self.scroll = max(0, self.scroll + dy)
        if "BACK" in p.pressed and self.t > 6:
            self.back()

    def back(self) -> None:
        self.ms.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(INK)
        f = self.app.font
        ch = self.chars[self.i]
        draw_panel(surf, pygame.Rect(14, 10, W - 28, H - 32), border=ch.color, title=f"{ch.name} - {ch.title}", font=f)
        render.draw_mask(surf, ch.id, (50, 52), 16, 0, ch.color, ch.accent, self.t)
        f.draw_wrapped(surf, ch.mech, pygame.Rect(80, 26, W - 120, 30), LENS, None, max_lines=3)
        f.draw(surf, "move", (28, 76), DIM, None)
        f.draw(surf, "input", (180, 76), DIM, None)
        f.draw(surf, "start/active/recov  hit/block", (260, 76), DIM, None)
        rows = move_rows(ch)
        per = 14
        self.scroll = min(self.scroll, max(0, len(rows) - per))
        y = 88
        for name, inp, fd in rows[self.scroll:self.scroll + per]:
            f.draw(surf, name, (28, y), PARCHMENT, None)
            f.draw(surf, inp, (180, y), BRASS, None)
            f.draw(surf, fd, (260, y), PARCHMENT, None)
            y += 11
        f.draw(surf, "Motion: 236 = quarter circle forward, 623 = dragon punch, 214 = quarter circle back. L/M/H = A/B/X.", (24, 246), DIM, None)
        draw_prompts(surf, self.app, [("LEFT", "Character"), ("UP", "Scroll"), ("BACK", "Back")])


class MoveListOverlay(MoveList):
    opaque = True

    def __init__(self, fs: FightScreen):
        super().__init__(fs.ms, None)
        self.fs = fs
        self.i = [c.id for c in self.chars].index(fs.ids[0]) if fs.ids[0] in [c.id for c in self.chars] else 0

    def back(self) -> None:
        self.app.scenes.pop()


class ReplayList(Scene):
    def __init__(self, ms: MasksScene):
        super().__init__(ms.app)
        self.ms = ms
        self.recs = ms.data["replays"]
        self.sel = 0
        self.t = 0
        self.verified: dict[int, bool] = {}

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        _, dy = p.menu_dir()
        if dy and self.recs:
            self.sel = (self.sel + dy) % len(self.recs)
        if self.t < 6:
            return
        if "CONFIRM" in p.pressed and self.recs:
            r = self.recs[self.sel]
            if replay.valid_record(r) and all(c in self.ms.roster for c in r["chars"]):
                self.ms.start_match("replay", tuple(r["chars"]), (None, None), None, r)
            else:
                self.app.toast("That replay cannot be played (missing fighter or damaged)", DANGER)
        if "X" in p.pressed and self.recs:
            self.verified[self.sel] = replay.verify(self.recs[self.sel], self.ms.roster)
        if "BACK" in p.pressed:
            self.ms.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(INK)
        f = self.app.font
        draw_panel(surf, pygame.Rect(40, 20, W - 80, 200), title="REPLAYS", font=f)
        if not self.recs:
            f.draw(surf, "Play a match and it is saved here.", (W // 2, 100), DIM, None, anchor="midtop")
        for i, r in enumerate(self.recs):
            y = 40 + i * 22
            sel = i == self.sel
            if sel:
                pygame.draw.rect(surf, INK_2, (50, y - 3, W - 100, 20))
            names = " vs ".join(c.title() for c in r["chars"])
            f.draw(surf, f"{i + 1}. {names}", (58, y), PARCHMENT if sel else DIM, None)
            win = r["wins"]
            f.draw(surf, f"{win[0]}-{win[1]}   {r['frames'] // 60}s   hash {r['hash'][:6]}", (58, y + 10), DIM, None)
            if i in self.verified:
                f.draw(surf, "verified" if self.verified[i] else "MISMATCH", (W - 60, y), GOOD if self.verified[i] else DANGER, None, anchor="topright")
        draw_prompts(surf, self.app, [("CONFIRM", "Watch"), ("X", "Verify"), ("BACK", "Back")])
