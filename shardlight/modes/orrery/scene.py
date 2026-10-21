"""Orrery scene: voyage menu, galaxy map, system flight.  Station / decode / codex screens live in ``screens.py``."""
from __future__ import annotations

import math
import random
from typing import Any

import pygame

from ...core.fx import FEEL, FloatingTexts, ParticleSystem, clamp, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Dialogue, Menu, MenuItem,
                        MenuScene, SettingsScene, ControlsScene, draw_panel, draw_prompts)
from . import art
from .defs import Defs, standalone_defs
from .flight import FlightControls, FlightSim
from .galaxy import body_state, features_from_unlocks
from .game import Game
from .info import INFO

W, H = 480, 270
MAP_SCALE = 0.34
MAP_OFF = (40.0, 8.0)
OVERLAYS = ("chart", "politics", "trade", "signals")
SAVE_V = 1


class OrreryScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.defs: Defs | None = None
        self.game: Game | None = None
        self.screen: Scene | None = None
        self.opt_seed = opts.get("seed", "random")
        self.t = 0
        self.flight: FlightSim | None = None

    # ------------------------------------------------------------------ lifecycle
    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("seen", {})
        d.setdefault("voyages", 0)
        self.defs = Defs(self.app.content) if self.app.content.ids("orrery.hull") else standalone_defs()
        self.app.audio.play_music("orrery", 1.2, 0.25)
        self.show_menu()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, FlightScreen):
            self.screen.open_pause()

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.audio.set_intensity(0.25)
        self.set_screen(MenuScreen(self))

    # ------------------------------------------------------------------ game management
    def features(self) -> tuple[str, ...]:
        return features_from_unlocks(self.defs, self.app.world.has_unlock)

    def seed(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        return random.Random(self.app.rng.randrange(1 << 30)).randrange(1000, 999999)

    def new_voyage(self) -> None:
        self.game = Game.new(self.defs, self.seed(), self.features())
        self.data["voyages"] += 1
        self._wire()
        self.save_game()
        self.enter_system()

    def continue_voyage(self) -> bool:
        raw = self.data.get("game")
        if not raw:
            return False
        g = Game.from_dict(self.defs, raw, self.app.world.has_unlock)
        if g is None:
            self.app.toast("That voyage could not be loaded", DANGER)
            return False
        self.game = g
        self._wire()
        self.enter_system()
        return True

    def _wire(self) -> None:
        g, w = self.game, self.app.world
        g.emit = lambda name, **kw: w.emit(name, **kw)
        g.add_lore = lambda lid: w.add_lore(lid)
        g.flags["unlocks"] = [u for u in ("orrery.ship.salt_runner",) if w.has_unlock(u)]

    def save_game(self) -> None:
        if self.game is not None:
            self.data["game"] = self.game.to_dict()
            self.data["summary"] = f"Day {self.game.sim.day}  signals {self.game.decoded_count()}"
            self.app.save_now()

    def enter_system(self) -> None:
        g = self.game
        self.flight = FlightSim(g, g.sid, self.app.settings.get("difficulty.preset"),
                                float(self.app.settings.get("difficulty.adaptive_ai")))
        self.set_screen(FlightScreen(self))

    def open_map(self, from_flight: bool = True) -> None:
        self.set_screen(MapScreen(self))

    def back_to_flight(self) -> None:
        self.set_screen(FlightScreen(self))

    def on_player_destroyed(self) -> None:
        g = self.game
        g.stats["lost_ships"] += 1
        g.cargo.clear()
        g.credits = int(g.credits * 0.85)
        g.hull_hp = g.ship_stats()["hull"]
        g.fuel = max(g.fuel, 6.0)
        self.app.toast("Your ship was lost. A salvage crew returns you to port.", DANGER)
        home = g.flags.get("home_sid", g.g.start)
        g.sid = home
        g.advance_clock(3 * 24.0)
        self.save_game()
        self.enter_system()


# ====================================================================================== menu
class MenuScreen(Scene):
    def __init__(self, os_: OrreryScene):
        super().__init__(os_.app)
        self.os = os_
        self.t = 0
        has = bool(os_.data.get("game"))
        items = [MenuItem("Continue voyage", self._cont, enabled=has),
                 MenuItem("New voyage" + ("  (replaces the current one)" if has else ""), self._new),
                 MenuItem("Return to hub", lambda: os_.finish(left=True))]
        self.menu = Menu(self.app, items, 240)
        self.rng = random.Random(3)
        self.stars = [(self.rng.random() * W, self.rng.random() * H, self.rng.random()) for _ in range(90)]

    def _cont(self) -> None:
        self.os.continue_voyage()

    def _new(self) -> None:
        self.os.new_voyage()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
        if "BACK" in self.inp.player(0).pressed and self.t > 10:
            self.os.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(art.INDIGO)
        for x, y, b in self.stars:
            surf.fill(mix((90, 100, 150), art.STAR_WHITE, b), (int(x), int(y), 1, 1))
        f = self.app.font
        cx, cy = 340, 130
        for i, (r, per) in enumerate(((30, 7), (52, 11), (78, 19), (104, 31))):
            pygame.draw.ellipse(surf, (50, 44, 96), (cx - r, cy - r * 0.45, r * 2, r * 0.9), 1)
            a = self.t * math.tau / (per * 60) + i
            px, py = cx + math.cos(a) * r, cy + math.sin(a) * r * 0.45
            pygame.draw.circle(surf, art.BRASS if i % 2 else art.CYAN, (int(px), int(py)), 3 + i)
        pygame.draw.circle(surf, (255, 236, 170), (cx, cy), 8)
        art.blit_additive_glow(surf, (cx, cy), 36, (80, 60, 20), 2)
        f.draw(surf, "ORRERY", (20, 16), art.BRASS, (10, 6, 24), scale=5)
        f.draw(surf, "of lights", (24, 62), art.STAR_WHITE, (10, 6, 24), scale=2)
        draw_panel(surf, pygame.Rect(18, 100, 258, 62), fill=art.INDIGO, alpha=235, border=art.BRASS)
        self.menu.draw(surf, (24, 106))
        d = self.os.data
        f.draw(surf, f"Voyages begun: {d['voyages']}", (20, 176), art.STAR_WHITE, (10, 6, 24))
        if d.get("summary"):
            f.draw(surf, d["summary"], (20, 188), art.CYAN, (10, 6, 24))
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")])


# ====================================================================================== galaxy map
class MapScreen(Scene):
    def __init__(self, os_: OrreryScene):
        super().__init__(os_.app)
        self.os = os_
        self.g: Game = os_.game
        self.sel = self.g.sid
        self.overlay = 0
        self.zoom = 2
        self.t = 0
        self.msg = ""
        self.msg_t = 0

    def on_enter(self, **kw) -> None:
        self.app.audio.set_intensity(0.2)

    # -- geometry ---------------------------------------------------------------------------------
    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        if self.zoom == 1:
            return MAP_OFF[0] + x * MAP_SCALE, MAP_OFF[1] + y * MAP_SCALE
        s = self.g.g.systems[self.sel]
        k = MAP_SCALE * 2.4
        return W / 2 + (x - s.x) * k, H / 2 - 20 + (y - s.y) * k

    def known(self) -> set[int]:
        g = self.g
        out = set(g.visited)
        for sid in list(g.visited):
            out.update(g.g.neighbors(sid, g.revealed))
        return out

    def lane_visible(self, ln, known: set[int]) -> bool:
        g = self.g
        if ln.kind == "hidden" and ln.key not in g.revealed:
            return False
        return (ln.a in g.visited) or (ln.b in g.visited)

    # -- input --------------------------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.t += 1
        self.msg_t = max(0, self.msg_t - 1)
        p = self.inp.player(0)
        g = self.g
        dx, dy = p.menu_dir()
        if dx or dy:
            self._select_dir(dx, dy)
        if "L" in p.pressed:
            self.zoom = 3 - self.zoom
        if "Y" in p.pressed:
            self.overlay = (self.overlay + 1) % len(OVERLAYS)
        if "X" in p.pressed:
            res = g.listen()
            self.os.save_game()
            self._say(f"Listening... {len(res)} signal(s) heard." if res else "The dish hears nothing from here.")
            self.app.audio.play("orrery_scan", 0.8)
        if "CONFIRM" in p.pressed or "A" in p.pressed:
            self._jump()
        if "B" in p.pressed or "BACK" in p.pressed or "SELECT" in p.pressed:
            self.os.back_to_flight()
        if "PAUSE" in p.pressed:
            self.app.scenes.push(PauseMenu(self.os))

    def _say(self, text: str) -> None:
        self.msg, self.msg_t = text, 200

    def _select_dir(self, dx: int, dy: int) -> None:
        g = self.g
        cur = g.g.systems[self.sel]
        best, bs = None, 1e9
        known = self.known()
        for sid in known:
            if sid == self.sel:
                continue
            s = g.g.systems[sid]
            vx, vy = s.x - cur.x, s.y - cur.y
            d = math.hypot(vx, vy) or 1
            along = (vx * dx + vy * dy) / d
            if along < 0.45:
                continue
            score = d * (1.6 - along)
            if score < bs:
                best, bs = sid, score
        if best is not None:
            self.sel = best
            self.app.audio.play("ui_move", 0.4)

    def _jump(self) -> None:
        g = self.g
        fs = self.os.flight
        if self.sel == g.sid:
            self.os.back_to_flight()
            return
        ok, why = g.can_jump(self.sel)
        if not ok:
            self._say(why)
            self.app.audio.play("ui_error", 0.7)
            return
        if fs is not None and not fs.jump_ready():
            self._say("The drive needs clear space: fly out past the system's edge and away from hostiles.")
            self.app.audio.play("ui_error", 0.7)
            return
        res = g.jump(self.sel)
        self.app.audio.play("orrery_jump", 0.9)
        self.os.save_game()
        self.os.enter_system()
        self.app.toast(f"Jumped to {g.g.systems[g.sid].name}  ({res['days']} days)", LENS)

    # -- draw -------------------------------------------------------------------------------------
    def draw(self, surf: pygame.Surface) -> None:
        g = self.g
        f = self.app.font
        surf.fill(art.INDIGO)
        art.draw_stars(surf, (self.t * 0.2, 0), 7)
        known = self.known()
        sim = g.sim
        t = self.t / 60
        ov = OVERLAYS[self.overlay]
        # civ territory glow
        if ov == "politics":
            for sid in known:
                m = sim.markets.get(sid)
                if m is None or not m.owner:
                    continue
                s = g.g.systems[sid]
                col = tuple(self.os.defs.civs[m.owner]["color"])
                sx, sy = self.to_screen(s.x, s.y)
                rad = 30 * (1.0 if self.zoom == 1 else 2.4) * (0.6 + 0.12 * m.size)
                art.blit_additive_glow(surf, (sx, sy), int(rad), tuple(int(c * 0.35) for c in col), 1.4)
        # lanes
        for ln in g.g.lanes.values():
            if not self.lane_visible(ln, known):
                continue
            a, b = g.g.systems[ln.a], g.g.systems[ln.b]
            pa, pb = self.to_screen(a.x, a.y), self.to_screen(b.x, b.y)
            col = (60, 56, 120)
            w = 1
            if ln.kind == "hidden":
                col = (200, 140, 255)
            if g.sid in (ln.a, ln.b):
                other = ln.b if ln.a == g.sid else ln.a
                ok, _ = g.can_jump(other)
                col = (110, 200, 150) if ok else (150, 90, 90)
                w = 2
            if self.sel in (ln.a, ln.b) and g.sid in (ln.a, ln.b):
                col = (255, 244, 205)
            pygame.draw.line(surf, col, pa, pb, w)
        # trade: convoys
        if ov == "trade":
            for c in sim.convoys.values():
                a = g.g.systems[c.path[c.leg - 1]] if c.leg > 0 else g.g.systems[c.path[0]]
                b = g.g.systems[c.path[c.leg]]
                span = max(0.001, c.t_arrive - c.t_depart)
                k = clamp((sim.day - c.t_depart) / span)
                x, y = a.x + (b.x - a.x) * k, a.y + (b.y - a.y) * k
                sx, sy = self.to_screen(x, y)
                if -5 < sx < W + 5 and -5 < sy < H + 5:
                    col = tuple(self.os.defs.civs[c.owner]["color"]) if c.owner else (200, 200, 200)
                    surf.fill(col, (int(sx) - 1, int(sy) - 1, 3, 3))
        # signals overlay: wedges from listening posts and candidate halos
        if ov == "signals":
            self._draw_signals(surf)
        # systems
        for sid in known:
            s = g.g.systems[sid]
            sx, sy = self.to_screen(s.x, s.y)
            if not (-10 < sx < W + 10 and -10 < sy < H + 10):
                continue
            visited = sid in g.visited
            r = 2 + int(s.star.radius / 30)
            col = s.star.color if visited else mix(s.star.color, art.INDIGO, 0.6)
            pygame.draw.circle(surf, (8, 6, 20), (int(sx), int(sy)), r + 1)
            pygame.draw.circle(surf, col, (int(sx), int(sy)), r)
            m = sim.markets.get(sid)
            if m is not None and m.owner and visited:
                ccol = tuple(self.os.defs.civs[m.owner]["color"])
                pygame.draw.circle(surf, ccol, (int(sx), int(sy)), r + 3, 1)
            if m is not None and m.blockaded_by:
                pygame.draw.line(surf, (255, 90, 80), (sx - 5, sy - 5), (sx + 5, sy + 5), 1)
            if sid == g.g.last_lamp and (sid in g.visited or g.decoded_count() >= 1):
                pygame.draw.circle(surf, (255, 214, 120), (int(sx), int(sy)), r + 5, 1)
            if sid in g.g.signal_sources.values() and ov == "signals":
                pass
            if visited and self.zoom == 2:
                f.draw(surf, s.name, (sx, sy + r + 3), art.STAR_WHITE, (8, 6, 20), anchor="midtop")
        # current and selected markers
        cs = g.g.systems[g.sid]
        cx, cy = self.to_screen(cs.x, cs.y)
        pygame.draw.circle(surf, art.CYAN, (int(cx), int(cy)), 7, 1)
        f.draw(surf, "YOU", (cx, cy - 16), art.CYAN, (8, 6, 20), anchor="midbottom")
        ss = g.g.systems[self.sel]
        sx, sy = self.to_screen(ss.x, ss.y)
        a = t * 3
        for k in range(4):
            ang = a + k * math.pi / 2
            pygame.draw.line(surf, (255, 244, 205), (sx + math.cos(ang) * 9, sy + math.sin(ang) * 9), (sx + math.cos(ang) * 12, sy + math.sin(ang) * 12), 1)
        f.draw(surf, ss.name, (sx, sy - 16), (255, 244, 205), (8, 6, 20), anchor="midbottom")
        self._info(surf)
        if self.msg_t > 0:
            r = pygame.Rect(30, 28, W - 60, 22)
            draw_panel(surf, r, border=art.BRASS, fill=art.INDIGO, alpha=235)
            f.draw(surf, self.msg, (r.centerx, r.y + 7), (255, 244, 205), None, anchor="midtop")
        f.draw(surf, f"Overlay: {ov}", (W - 6, 4), art.CYAN, (8, 6, 20), anchor="topright")
        f.draw(surf, f"Day {g.sim.day}   Fuel {g.fuel:.1f}/{g.ship_stats()['fuel']:.0f}   Credits {int(g.credits)}", (6, 4), art.STAR_WHITE, (8, 6, 20))
        draw_prompts(surf, self.app, [("CONFIRM", "Jump"), ("X", "Listen"), ("Y", "Overlay"), ("L", "Zoom"), ("SELECT", "Back")])

    def _info(self, surf: pygame.Surface) -> None:
        g = self.g
        f = self.app.font
        s = g.g.systems[self.sel]
        r = pygame.Rect(W - 150, H - 118, 144, 92)
        draw_panel(surf, r, border=art.BRASS, fill=art.INDIGO, alpha=232)
        visited = self.sel in g.visited
        f.draw(surf, s.name if visited or self.sel in g.visited else "Unvisited", (r.x + 6, r.y + 5), (255, 244, 205), None)
        f.draw(surf, s.star.label, (r.x + 6, r.y + 16), tuple(s.star.color), None)
        m = g.sim.markets.get(self.sel)
        if visited and m:
            civ = self.os.defs.civs[m.owner]["short"] if m.owner else "free port"
            f.draw(surf, f"{civ}  size {m.size:.1f}", (r.x + 6, r.y + 28), art.STAR_WHITE, None)
            if m.blockaded_by:
                f.draw(surf, f"BLOCKADED by {self.os.defs.civs[m.blockaded_by]['short']}", (r.x + 6, r.y + 40), DANGER, None)
            else:
                men = g.sim.menace[self.sel]
                f.draw(surf, "pirates: " + ("quiet" if men < 0.2 else "active" if men < 0.5 else "rife"), (r.x + 6, r.y + 40), DIM, None)
        elif visited:
            f.draw(surf, "no port", (r.x + 6, r.y + 28), DIM, None)
        ln = g.g.lane(g.sid, self.sel)
        if self.sel == g.sid:
            f.draw(surf, "Current system", (r.x + 6, r.y + 56), art.CYAN, None)
        elif ln is None or (ln.kind == "hidden" and ln.key not in g.revealed):
            f.draw(surf, "No known lane", (r.x + 6, r.y + 56), DANGER, None)
        else:
            ok, why = g.can_jump(self.sel)
            f.draw(surf, f"Lane {ln.length:.0f}  fuel {ln.fuel:.1f}", (r.x + 6, r.y + 56), GOOD if ok else DANGER, None)
            f.draw(surf, f"Range {g.ship_stats()['range']:.0f}", (r.x + 6, r.y + 68), DIM, None)
        if self.sel == g.g.last_lamp and (self.sel in g.visited or g.decoded_count() >= 1):
            f.draw(surf, "THE LAST LAMP", (r.x + 6, r.y + 80), (255, 214, 120), None)

    def _draw_signals(self, surf: pygame.Surface) -> None:
        g = self.g
        f = self.app.font
        pos = g.positions()
        for sig in g.enabled_signals():
            ss = g.sig_state(sig)
            d = self.os.defs.signals[sig]
            for rd in ss["readings"]:
                if rd.get("here"):
                    continue
                ox, oy = pos[rd["origin"]]
                ang = math.radians(rd["bearing"])
                err = math.radians(rd["err"])
                length = d["range"] * (1.0 - rd["strength"]) + 20
                sx, sy = self.to_screen(ox, oy)
                pts = [(sx, sy)]
                for k in range(-1, 2):
                    a = ang + err * k
                    ex, ey = self.to_screen(ox + math.cos(a) * length * 1.1, oy + math.sin(a) * length * 1.1)
                    pts.append((ex, ey))
                col = (111, 224, 255)
                pygame.draw.lines(surf, col, False, pts[1:], 1)
                pygame.draw.line(surf, col, pts[0], pts[1], 1)
                pygame.draw.line(surf, col, pts[0], pts[3], 1)
            if ss["decoded"]:
                continue
            cand = g.signal_candidates(sig)
            if ss["readings"] and len(cand) <= 6:
                for c in cand:
                    cx, cy = self.to_screen(*pos[c])
                    pygame.draw.circle(surf, (255, 214, 120), (int(cx), int(cy)), 9 if len(cand) > 1 else 12, 1)
                    if len(cand) == 1:
                        f.draw(surf, d["name"], (cx, cy + 14), (255, 214, 120), (8, 6, 20), anchor="midtop")


# ====================================================================================== flight
class FlightScreen(Scene):
    def __init__(self, os_: OrreryScene):
        super().__init__(os_.app)
        self.os = os_
        self.g: Game = os_.game
        self.fs: FlightSim = os_.flight
        self.cam = [self.fs.player.x, self.fs.player.y]
        self.parts = ParticleSystem(800, random.Random(2))
        self.floats = FloatingTexts()
        self.t = 0
        self.msg = ""
        self.msg_t = 0
        self.paused = False
        self.prev_ctl = FlightControls()
        self.dampers = True
        self.banner = ""
        self.banner_t = 0
        self.trauma = 0.0
        self.toggle_r = False

    def on_enter(self, **kw) -> None:
        self.app.input.assign_local(1)
        s = self.g.g.systems[self.g.sid]
        self.banner, self.banner_t = s.name.upper(), 150
        seen = self.os.data["seen"]
        if not seen.get("intro"):
            seen["intro"] = True
            self.app.scenes.push(Dialogue(self.app, [
                ("Navigator", "Up thrusts, left and right turn. A fires pulses, leant at nearby foes; hold B to lock a missile; hold X for the beam."),
                ("Navigator", "Hold R near stations, wrecks and anomalies. SELECT opens the star chart. The drive needs clear space at the system's edge."),
            ], color=art.CYAN))
        g = self.g
        g.refresh_missions()
        g.flags.setdefault("home_sid", g.g.start)

    def open_pause(self) -> None:
        if self.paused:
            return
        self.paused = True
        self.app.scenes.push(PauseMenu(self.os, self))

    def controls(self) -> FlightControls:
        p = self.inp.player(0)
        c = FlightControls()
        c.turn = p.move.x
        c.thrust = max(-1.0, min(1.0, -p.move.y))
        c.pulse = "A" in p.down
        c.missile = "B" in p.down
        c.beam = "X" in p.down
        c.boost = "Y" in p.down
        c.decoy = "L" in p.pressed
        c.interact = "R" in p.down
        c.ability = "R" in p.pressed and self.fs.nearest_interactive() is None
        c.dampers = self.dampers
        c.aim_assist = bool(self.app.settings.get("access.aim_assist"))
        return c

    def update(self, dt: float) -> None:
        if self.paused:
            return
        self.t += 1
        fs, g = self.fs, self.g
        p0 = self.inp.player(0)
        self.msg_t = max(0, self.msg_t - 1)
        self.banner_t = max(0, self.banner_t - 1)
        self.trauma = max(0.0, self.trauma - 0.03)
        if "PAUSE" in p0.pressed:
            self.open_pause()
            return
        if "SELECT" in p0.pressed:
            self.os.open_map()
            return
        fs.update(self.controls(), 1 / 60)
        if getattr(self.app, "admin_god", False):
            pl = fs.player
            pl.hull = pl.hull_max
            pl.shield = pl.shield_max
            pl.energy = pl.energy_max
            pl.heat = 0.0
            fs.player_dead = False
        self.parts.update(dt)
        self.floats.update(dt)
        pl = fs.player
        k = 1 - math.exp(-5.0 * dt)
        self.cam[0] += (pl.x + pl.vx * 0.25 - self.cam[0]) * k
        self.cam[1] += (pl.y + pl.vy * 0.25 - self.cam[1]) * k
        self._events(fs.drain())
        while fs.msgs:
            self._say(fs.msgs.pop(0))
        while fs.comms:
            self._say(fs.comms.pop(0), 220)
        if fs.dock_request is not None:
            b = fs.dock_request
            fs.dock_request = None
            self.app.audio.play("orrery_dock", 0.9)
            from .screens import StationScreen
            g.flags["home_sid"] = g.sid if g.market() is not None else g.flags.get("home_sid", g.g.start)
            self.os.save_game()
            self.os.set_screen(StationScreen(self.os, b))
            return
        if fs.decode_request is not None:
            sig = fs.decode_request
            fs.decode_request = None
            from .screens import DecodeScreen
            self.os.set_screen(DecodeScreen(self.os, sig))
            return
        if fs.player_dead:
            self.os.on_player_destroyed()
            return
        self.app.audio.set_intensity(0.85 if any(e.alive for e in fs.enemies) else 0.3)
        # facet trial
        if g.lamp["done"] and not self.os.data.get("lamp_done"):
            self.os.data["lamp_done"] = True
            self.app.world.complete_facet("orrery")
            self.os.data["summary"] = "The Last Lamp is lit"
            self.banner, self.banner_t = "THE LAST LAMP BURNS", 400
            self.os.save_game()

    def _say(self, text: str, frames: int = 150) -> None:
        self.msg, self.msg_t = text, frames

    # ------------------------------------------------------------------ feedback
    def _events(self, evs) -> None:
        a = self.app.audio
        P = self.parts
        cx, cy = self.cam
        for e in evs:
            sx, sy = W / 2 + e.x - cx, H / 2 + e.y - cy
            k = e.kind
            if k == "pulse":
                a.play("orrery_pulse", 0.25)
            elif k == "npc_pulse":
                a.play("orrery_pulse", 0.12, pan=clamp((sx - W / 2) / 240, -1, 1))
            elif k == "missile":
                a.play("orrery_missile", 0.5)
            elif k == "shield_hit":
                P.emit((sx, sy), 6, (20, 70), (0, 360), (0.1, 0.3), (1, 2), (140, 220, 255), (40, 80, 200), drag=3)
                a.play("orrery_shield", 0.35)
            elif k == "hull_hit":
                P.emit((sx, sy), 8, (30, 90), (0, 360), (0.15, 0.4), (1, 2), (255, 190, 100), (150, 40, 20), drag=3)
                a.play("orrery_hull", 0.4)
                if abs(e.x - self.fs.player.x) < 20:
                    self.trauma = min(0.8, self.trauma + 0.2)
            elif k == "explode":
                n = 34 if e.data.get("big") else 18
                P.emit((sx, sy), n, (20, 140), (0, 360), (0.3, 0.9), (1, 3.5), (255, 220, 140), (180, 50, 30), drag=2, glow=8)
                a.play("orrery_boom", 0.8)
                self.trauma = min(0.8, self.trauma + 0.15)
            elif k == "decoy":
                a.play("orrery_decoy", 0.5)
            elif k == "pickup":
                a.play("pickup", 0.5)
            elif k == "scanned":
                a.play("orrery_scan", 0.7)
            elif k == "comms":
                a.play("ui_open", 0.5)
            elif k == "ability":
                P.emit((sx, sy), 14, (20, 80), (0, 360), (0.3, 0.7), (1, 2), (180, 230, 255), (60, 100, 200), drag=3)
            elif k == "gear":
                a.play("orrery_gear" if e.data.get("ok") else "ui_error", 0.8)
            elif k == "lamp_lit":
                a.play("unlock", 1.0)
                FEEL.flash((255, 240, 180), 0.5)
            elif k == "cleared":
                self._say("Sector clear.")
                a.play("lap_checkpoint", 0.6)
            elif k == "convoy_raided":
                self._say("Convoy raided. Its owners will remember.", 200)
            elif k == "player_dead":
                a.play("orrery_boom", 1.0)

    # ------------------------------------------------------------------ draw
    def draw(self, surf: pygame.Surface) -> None:
        fs, g = self.fs, self.g
        sysm = fs.sys
        f = self.app.font
        t = fs.time
        surf.fill(art.INDIGO)
        cx, cy = self.cam
        if self.trauma > 0 and FEEL.shake_scale:
            cx += random.uniform(-1, 1) * self.trauma * 5 * FEEL.shake_scale
            cy += random.uniform(-1, 1) * self.trauma * 5 * FEEL.shake_scale
        art.draw_stars(surf, (cx, cy), 11 + g.sid)

        def S(x: float, y: float) -> tuple[float, float]:
            return W / 2 + x - cx, H / 2 + y - cy

        star = sysm.star
        sx0, sy0 = S(0, 0)
        # orbit guides
        for b in sysm.bodies:
            if b.parent is None and b.kind in ("planet", "lamp", "belt") and b.orbit.a > 30:
                r = b.orbit.a
                if abs(math.hypot(cx, cy) - r) < 340:
                    pygame.draw.circle(surf, (28, 26, 60), (int(sx0), int(sy0)), int(r), 1)
        art.draw_star(surf, (sx0, sy0), star, t)
        owner = g.sim.owner(g.sid)
        for b, (bx, by) in zip(sysm.bodies, fs.body_pos):
            x, y = S(bx, by)
            if x < -120 or x > W + 120 or y < -120 or y > H + 120:
                continue
            if b.kind in ("planet", "moon"):
                la = int(math.degrees(math.atan2(-by, -bx)) % 360)
                spr = art.planet_sprite(b.sub if b.sub in art.PLANET_COLORS else "rock", b.seed, int(b.radius), la // 15 * 15,
                                        b.ring, lit_city=b.hab > 0.5 and owner is not None)
                surf.blit(spr, (x - spr.get_width() / 2, y - spr.get_height() / 2))
            elif b.kind == "station":
                art.draw_station(surf, (x, y), b.sub, t, t * 0.3)
                f.draw(surf, b.name, (x, y + 16), art.STAR_WHITE, (8, 6, 20), anchor="midtop")
            elif b.kind == "anomaly":
                art.draw_anomaly(surf, (x, y), b.sub, t, b.radius)
            elif b.kind == "derelict":
                art.draw_derelict(surf, (x, y), t)
            elif b.kind == "lamp":
                order = b.extra.get("order", 0)
                lit = g.lamp["lit"][order]
                art.draw_gear(surf, (x, y), 14 + order * 2, 8 + order * 2, t * (0.9 - order * 0.12), (255, 214, 120), lit)
            elif b.kind == "belt":
                n = b.extra.get("rocks", 26)
                from .galaxy import belt_rock_state
                for k in range(n):
                    rx, ry = belt_rock_state(sysm, b, k, n, g.clock)
                    px, py = S(rx, ry)
                    if -4 < px < W + 4 and -4 < py < H + 4:
                        pygame.draw.circle(surf, (120, 110, 100), (int(px), int(py)), 2 + k % 3)
        near = fs.nearest_interactive()
        # crates
        for c in fs.crates:
            x, y = S(c.x, c.y)
            col = {"credits": (255, 214, 120), "fuel": (120, 230, 160), "goods": (200, 160, 255)}[c.kind]
            pygame.draw.rect(surf, (8, 6, 20), (int(x) - 3, int(y) - 3, 7, 7))
            pygame.draw.rect(surf, col, (int(x) - 2, int(y) - 2, 5, 5))
        # ships
        for e in fs.npcs:
            if e.alive:
                x, y = S(e.x, e.y)
                art.draw_ship(surf, None, (x, y), e.heading, "freighter", e.flash > 0)
        for e in fs.enemies:
            if e.alive:
                x, y = S(e.x, e.y)
                art.draw_ship(surf, None, (x, y), e.heading, e.kind, e.flash > 0)
                if e.shield > 0 and e.flash:
                    pygame.draw.circle(surf, (140, 220, 255), (int(x), int(y)), int(e.radius) + 3, 1)
                if fs.player.lock_target is e:
                    k = clamp(fs.player.lock_t / max(0.01, fs.stats["lock_time"] * self.os.defs.weapons["missile"]["lock_time"]))
                    col = (255, 90, 80) if k >= 0.999 else (255, 214, 120)
                    r = 16 - 6 * k
                    for ang in (0, 1.57, 3.14, 4.71):
                        pygame.draw.line(surf, col, (x + math.cos(ang + t * 2) * r, y + math.sin(ang + t * 2) * r),
                                         (x + math.cos(ang + t * 2) * (r + 5), y + math.sin(ang + t * 2) * (r + 5)), 2)
                elif fs.assist_target is e:                       # pulse aim-assist bracket: quiet, steady
                    r = int(e.radius) + 8
                    for ang in (0.785, 2.356, 3.927, 5.498):
                        dx_, dy_ = math.cos(ang), math.sin(ang)
                        pygame.draw.line(surf, (255, 214, 120), (x + dx_ * (r - 5), y + dy_ * (r - 5)),
                                         (x + dx_ * r, y + dy_ * r), 1)
        pl = fs.player
        if pl.alive:
            x, y = S(pl.x, pl.y)
            style = g.hull if g.hull in art.SHIP_SHAPES else "wayfarer"
            art.draw_ship(surf, None, (x, y), pl.heading, style, pl.flash > 0, 1.0 if self.inp.player(0).move.y < -0.2 else 0.0)
            if pl.slip > 0:
                pygame.draw.circle(surf, (255, 255, 255), (int(x), int(y)), 14, 1)
            if pl.beam_on:
                ex, ey = S(*fs.beam_end)
                over = pl.beam_t > self.os.defs.weapons["beam"]["overcharge_after"]
                col = (255, 120, 90) if over else (255, 236, 150)
                pygame.draw.line(surf, col, (x, y), (ex, ey), 3 if over else 2)
                pygame.draw.line(surf, (255, 255, 255), (x, y), (ex, ey), 1)
                art.blit_additive_glow(surf, (ex, ey), 10, (90, 60, 20), 2)
        for b in fs.bolts:
            x, y = S(b.x, b.y)
            col = (255, 240, 170) if b.team == 0 else (255, 110, 90)
            pygame.draw.line(surf, col, (x, y), (x - b.vx * 0.02, y - b.vy * 0.02), 2)
        for m in fs.missiles:
            x, y = S(m.x, m.y)
            pygame.draw.circle(surf, (255, 200, 120), (int(x), int(y)), 3)
            pygame.draw.line(surf, (255, 120, 60), (x, y), (x - math.cos(m.heading) * 9, y - math.sin(m.heading) * 9), 2)
        for d in fs.decoys:
            x, y = S(d.x, d.y)
            pygame.draw.circle(surf, (255, 255, 255) if int(t * 10) % 2 else (180, 200, 255), (int(x), int(y)), 3)
            pygame.draw.circle(surf, (120, 140, 220), (int(x), int(y)), int(10 * (1 - d.life / 4.0)) + 4, 1)
        self.parts.draw(surf, (0, 0))
        self.floats.draw(surf, f)
        self._hud(surf, near)
        if self.banner_t > 0:
            f.draw(surf, self.banner, (W // 2, 70), art.STAR_WHITE, (8, 6, 24), anchor="midtop", scale=3)
        if self.msg_t > 0:
            r = pygame.Rect(40, H - 56, W - 80, 20)
            draw_panel(surf, r, border=art.BRASS, fill=art.INDIGO, alpha=225)
            f.draw(surf, self.msg, (r.centerx, r.y + 6), (255, 244, 205), None, anchor="midtop")

    def _hud(self, surf: pygame.Surface, near) -> None:
        fs, g = self.fs, self.g
        f = self.app.font
        pl = fs.player
        st = fs.stats
        def bar(x, y, w, frac, col, label=""):
            pygame.draw.rect(surf, (8, 6, 20), (x - 1, y - 1, w + 2, 7))
            pygame.draw.rect(surf, (40, 36, 80), (x, y, w, 5))
            pygame.draw.rect(surf, col, (x, y, int(w * clamp(frac)), 5))
            if label:
                f.draw(surf, label, (x + w + 4, y - 1), art.STAR_WHITE, None, scale=1)
        bar(8, 8, 90, pl.shield / max(1, pl.shield_max), (120, 200, 255), "SHIELD")
        bar(8, 17, 90, pl.hull / max(1, pl.hull_max), (240, 90, 80) if pl.hull < pl.hull_max * 0.3 else (120, 230, 150), "HULL")
        bar(8, 26, 90, pl.energy / max(1, pl.energy_max), (255, 214, 120), "ENERGY")
        bar(8, 35, 90, pl.heat / max(1, st["heat_cap"]), (255, 110, 60) if not pl.overheated else (255, 40, 40), "HEAT" if not pl.overheated else "OVERHEAT")
        f.draw(surf, f"Missiles {pl.missiles}  Decoys {pl.decoys}", (8, 46), art.STAR_WHITE, (8, 6, 20))
        f.draw(surf, f"Credits {int(g.credits)}  Fuel {g.fuel:.1f}", (W - 6, 6), art.STAR_WHITE, (8, 6, 20), anchor="topright")
        f.draw(surf, f"Cargo {g.cargo_used()}/{int(st['cargo'])}   Day {g.sim.day}", (W - 6, 17), art.CYAN, (8, 6, 20), anchor="topright")
        sy = fs.sys
        f.draw(surf, f"{sy.name}  ({sy.star.label})", (W // 2, 4), art.STAR_WHITE, (8, 6, 20), anchor="midtop")
        # radar
        rx, ry, rr = W - 44, H - 44, 36
        pygame.draw.circle(surf, (8, 6, 22), (rx, ry), rr + 1)
        pygame.draw.circle(surf, (24, 22, 56), (rx, ry), rr, 1)
        rng_ = 1100.0
        def rp(x, y, col, size=1):
            dx, dy = (x - pl.x) / rng_ * rr, (y - pl.y) / rng_ * rr
            d = math.hypot(dx, dy)
            if d > rr - 1:
                dx, dy = dx / d * (rr - 1), dy / d * (rr - 1)
            surf.fill(col, (int(rx + dx) - size // 2, int(ry + dy) - size // 2, size, size))
        for b, (bx, by) in zip(fs.sys.bodies, fs.body_pos):
            if b.kind == "station":
                rp(bx, by, art.CYAN, 3)
            elif b.kind in ("anomaly", "derelict"):
                rp(bx, by, (200, 150, 255))
            elif b.kind == "planet":
                rp(bx, by, (140, 140, 190), 2)
            elif b.kind == "lamp":
                rp(bx, by, (255, 214, 120), 2)
        for e in fs.enemies:
            if e.alive:
                rp(e.x, e.y, (255, 80, 70), 2)
        for e in fs.npcs:
            if e.alive:
                rp(e.x, e.y, (200, 200, 120), 2)
        rp(0, 0, (255, 230, 140), 3)
        a = pl.heading
        pygame.draw.line(surf, (255, 255, 255), (rx, ry), (rx + math.cos(a) * 8, ry + math.sin(a) * 8), 1)
        # prompts
        if near is not None:
            b = near[0]
            label = {"station": "Dock", "anomaly": "Decode signal" if b.sub == "emitter" else "Scan", "derelict": "Salvage", "lamp": "Wind the gear"}[b.kind]
            if b.id in g.looted and b.kind in ("anomaly", "derelict") and b.sub != "emitter":
                label = "Already searched"
            f.draw(surf, f"Hold [{self.inp.player(0).prompt('R')}] {label}", (W // 2, H - 76), (255, 244, 205), (8, 6, 20), anchor="midbottom")
            if fs.scan_t > 0:
                pygame.draw.rect(surf, (8, 6, 20), (W // 2 - 31, H - 74, 62, 6))
                pygame.draw.rect(surf, art.CYAN, (W // 2 - 30, H - 73, int(60 * fs.scan_t / 1.4), 4))
            if b.kind == "lamp" and fs.lamp_hold > 0:
                pygame.draw.rect(surf, (255, 214, 120), (W // 2 - 30, H - 73, int(60 * fs.lamp_hold / 2.0), 4))
        if fs.jump_ready():
            f.draw(surf, "DRIVE READY - open the chart (SELECT)", (W // 2, H - 14), (140, 255, 170), (8, 6, 20), anchor="midtop")


# ====================================================================================== pause
class PauseMenu(MenuScene):
    def __init__(self, os_: OrreryScene, fscreen: FlightScreen | None = None):
        self.os = os_
        self.fscreen = fscreen
        super().__init__(os_.app, "PAUSED", self._items, 220, overlay=True, footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def on_exit(self) -> None:
        if self.fscreen is not None:
            self.fscreen.paused = False

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [MenuItem("Resume", a.scenes.pop), MenuItem("Save voyage", self._save),
                MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
                MenuItem("Voyage menu (saves)", self._to_menu), MenuItem("Leave shard (saves)", self._leave)]

    def _save(self) -> None:
        self.os.save_game()
        self.app.toast("Voyage saved", GOOD)

    def _to_menu(self) -> None:
        self.app.scenes.pop()
        self.os.save_game()
        self.os.show_menu()

    def _leave(self) -> None:
        self.app.scenes.pop()
        self.os.save_game()
        self.os.finish(left=True)
