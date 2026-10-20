"""Concord scene: campaign menu, the hex campaign map, province and army menus, and turn processing."""
from __future__ import annotations

import math
import random
from typing import Any

import pygame

from ...core.fx import FloatingTexts, ParticleSystem, clamp, mix
from ...core.scene import ModeScene, Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK as UI_INK, INK_2, LENS, PARCHMENT, Dialogue, Menu, MenuItem, MenuScene,
                        SettingsScene, ControlsScene, draw_panel, draw_prompts)
from . import ai, art, hexgrid
from .campaign import Campaign
from .info import INFO
from .rules import RES_LABEL, TERRAIN_NAMES, Rules
from .schemas import RESOURCES

W, H = 480, 270
MAP_RECT = pygame.Rect(2, 22, 342, 226)
SIDE_X = 348
SAVE_V = 1
OVERLAYS = ("political", "terrain", "supply", "unrest")
RES_COL = {"grain": (222, 196, 96), "timber": (150, 112, 70), "ore": (150, 160, 180), "salt": (230, 230, 240),
           "ink": (150, 120, 220), "coin": (255, 214, 120)}
RES_SHORT = {"grain": "Gr", "timber": "Ti", "ore": "Or", "salt": "Sa", "ink": "Ik", "coin": "Co"}


def house_color(rules: Rules, hid: str | None) -> tuple[int, int, int]:
    if hid is None:
        return (150, 140, 120)
    return tuple(rules.houses[hid]["color"])


class ConcordScene(ModeScene):
    INFO = INFO

    def __init__(self, app, **opts: Any):
        super().__init__(app, **opts)
        self.rules: Rules | None = None
        self.camp: Campaign | None = None
        self.screen: Scene | None = None
        self.t = 0
        self.opt_house = opts.get("house", "ostrel")
        self.opt_size = opts.get("size", "medium")
        self.opt_seed = opts.get("seed", "random")
        self.runner = None
        self.pending_result = None

    # ------------------------------------------------------------------ lifecycle
    def on_enter(self, **kw) -> None:
        d = self.data
        d.setdefault("v", SAVE_V)
        d.setdefault("seen", {})
        d.setdefault("wins", {})
        d.setdefault("campaigns", 0)
        self.rules = Rules.from_db(self.app.content)
        problems = self.rules.validate()
        if problems:
            import logging
            logging.getLogger("shardlight.concord").warning("content problems: %s", "; ".join(problems[:4]))
        self.app.audio.play_music("concord", 1.2, 0.3)
        self.show_menu()

    def update(self, dt: float) -> None:
        self.t += 1
        if self.screen:
            self.screen.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        if self.screen:
            self.screen.draw(surf)

    def on_pad_lost(self, slot: int) -> None:
        if isinstance(self.screen, MapScreen):
            self.app.scenes.push(PauseMenu(self))

    def set_screen(self, s: Scene) -> None:
        self.screen = s
        s.on_enter()

    def show_menu(self) -> None:
        self.app.audio.set_intensity(0.2)
        self.set_screen(MenuScreen(self))

    # ------------------------------------------------------------------ campaign management
    def seed(self) -> int:
        if isinstance(self.opt_seed, int):
            return self.opt_seed
        return random.Random(self.app.rng.randrange(1 << 30)).randrange(1000, 999999)

    def unlocks(self) -> frozenset[str]:
        return frozenset(u for u in ("concord.tech.resonant_forging",) if self.app.world.has_unlock(u))

    def new_campaign(self) -> None:
        s = self.app.settings
        self.camp = Campaign(self.rules, self.seed(), self.opt_size, self.opt_house, self.unlocks(),
                             s.get("difficulty.preset"), float(s.get("difficulty.adaptive_ai")))
        self.data["campaigns"] += 1
        self.data["intro_done"] = False
        self.save_campaign()
        self.show_map()

    def continue_campaign(self) -> bool:
        raw = self.data.get("campaign")
        if not raw:
            return False
        c = Campaign.from_dict(self.rules, raw)
        if c is None:
            self.app.toast("That campaign could not be loaded", DANGER)
            return False
        c.unlocks = self.unlocks() | c.unlocks
        self.camp = c
        self.show_map()
        return True

    def save_campaign(self) -> None:
        if self.camp is None:
            return
        self.data["campaign"] = self.camp.to_dict()
        c = self.camp
        self.data["summary"] = f"{c.short(c.player)}, turn {c.turn}, {len(c.provinces_of(c.player))} provinces"
        self.app.save_now()

    def show_map(self) -> None:
        self.set_screen(MapScreen(self))

    def drain_hooks(self) -> None:
        c = self.camp
        while c.hooks:
            name, payload = c.hooks.pop(0)
            self.app.world.emit(name, **payload)
            if name == "concord.tech_researched":
                self.app.toast(f"Researched {c.rules.techs[payload['tech']]['name']}", LENS)

    def finish_campaign(self) -> None:
        c = self.camp
        won = c.victory in ("conquest", "concord", "dominion") and c.winner == c.player
        if won:
            self.data["wins"][c.victory] = self.data["wins"].get(c.victory, 0) + 1
            if self.app.world.complete_facet("concord"):
                self.app.toast("Concord: the Facet is repaired", LENS)
        self.data["campaign"] = None
        self.data["summary"] = ("Victory: " if won else "Fallen: ") + c.victory
        self.app.save_now()
        self.set_screen(EndScreen(self, won))


# ====================================================================================== menu
class MenuScreen(Scene):
    def __init__(self, cs: ConcordScene):
        super().__init__(cs.app)
        self.cs = cs
        self.t = 0
        has = bool(cs.data.get("campaign"))
        r = cs.rules
        h = r.houses[cs.opt_house]
        self.bg = art.parchment((W, H), 11)
        items = [MenuItem("Continue campaign", self._cont, enabled=has, hint=cs.data.get("summary", "") if has else ""),
                 MenuItem("New campaign" + (" (replaces saved)" if has else ""), self._new, hint=f"{h['name']}, {cs.opt_size} map"),
                 MenuItem("How to play", self._help),
                 MenuItem("Return to hub", lambda: cs.finish(left=True))]
        self.menu = Menu(self.app, items, 230)

    def _cont(self) -> None:
        self.cs.continue_campaign()

    def _new(self) -> None:
        self.cs.new_campaign()

    def _help(self) -> None:
        self.app.scenes.push(Dialogue(self.app, HELP_LINES, color=art.WAX))

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 8:
            self.menu.update()
            if "BACK" in self.inp.player(0).pressed and self.t > 12:
                self.cs.finish(left=True)

    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self.bg, (0, 0))
        f = self.app.font
        r = self.cs.rules
        f.draw(surf, "CONCORD", (24, 18), art.WAX, (240, 226, 190), scale=5)
        f.draw(surf, "Ledger of Crowns", (28, 62), art.INK, None, scale=2)
        draw_panel(surf, pygame.Rect(18, 92, 250, 92), fill=(40, 34, 56), alpha=240)
        self.menu.draw(surf, (24, 98))
        x = 292
        for i, hid in enumerate(r.house_ids()):
            hd = r.houses[hid]
            col = tuple(hd["color"])
            y = 30 + i * 52
            pygame.draw.rect(surf, (236, 224, 190), (x - 4, y - 4, 184, 46))
            pygame.draw.rect(surf, art.INK, (x - 4, y - 4, 184, 46), 1)
            surf.blit(art.crest(col, 16), (x, y))
            on = hid == self.cs.opt_house
            f.draw(surf, hd["name"] + ("  (you)" if on else ""), (x + 22, y), art.INK, None)
            f.draw(surf, hd["epithet"], (x + 22, y + 10), core_shade(col), None)
            for j, ln in enumerate(f.wrap(hd["blurb"], 160)[:2]):
                f.draw(surf, ln, (x, y + 22 + j * 9), (90, 78, 70), None)
        draw_prompts(surf, self.app, [("CONFIRM", "Select"), ("BACK", "Hub")], y=H - 14)


def core_shade(c, k: float = 0.65):
    return tuple(int(v * k) for v in c)


HELP_LINES = [
    ("Ledger", "Hold provinces, feed your armies, and outlast three rival houses. Win by conquest, by holding 60% of the map, or by gathering every living house into an alliance for three turns."),
    ("Ledger", "Armies march along roads you can supply. Outside a depot's range (capital, granary, fort) they starve and bleed. Rivers slow a march; mountains slow it more."),
    ("Ledger", "Press X on your province to build or recruit. Press Y for the ledger: end turn, research, diplomacy, rivals. Select an army with A or L/R, then A on a destination."),
    ("Ledger", "Treaties can be broken, but a house remembers: your oath record lowers every house's trust. Unjust wars sour your own provinces. Fabricate a claim (3 ink) to wage a just one."),
]


# ====================================================================================== map
class MapScreen(Scene):
    def __init__(self, cs: ConcordScene):
        super().__init__(cs.app)
        self.cs = cs
        self.camp: Campaign = cs.camp
        self.rules = cs.rules
        self.t = 0
        self.overlay = 0
        m = self.camp.map
        self.size = int(min(MAP_RECT.w / (hexgrid.SQRT3 * (m.cols + 0.5)), MAP_RECT.h / (1.5 * (m.rows - 1) + 2)))
        self.size = max(10, self.size)
        w_px = hexgrid.SQRT3 * self.size * (m.cols + 0.5)
        h_px = 1.5 * self.size * (m.rows - 1) + 2 * self.size
        self.ox = MAP_RECT.x + (MAP_RECT.w - w_px) / 2 + hexgrid.SQRT3 * self.size / 2
        self.oy = MAP_RECT.y + (MAP_RECT.h - h_px) / 2 + self.size
        self.centers = [(self.ox + hexgrid.center(p.col, p.row, self.size)[0], self.oy + hexgrid.center(p.col, p.row, self.size)[1])
                        for p in m.provinces]
        self.cur = self.camp.houses[self.camp.player].capital
        self.sel_army: int | None = None
        self.path: list[int] = []
        self.msg = ""
        self.msg_t = 0
        self.bg = art.parchment((W, H), 5)
        self.floats = FloatingTexts()
        self.report: list[str] = []
        self.last_start = self.camp.turn
        self._cycle = 0

    def on_enter(self, **kw) -> None:
        self.app.audio.set_intensity(0.25)
        c = self.camp
        if not self.cs.data.get("intro_done"):
            self.cs.data["intro_done"] = True
            self.app.scenes.push(Dialogue(self.app, [
                ("Chancellor", f"{c.date_text()}. You hold {len(c.provinces_of(c.player))} provinces and {sum(len(a.units) for a in c.armies_of(c.player))} soldiers."),
                ("Chancellor", "Select your army with A, pick a destination with A again. X opens your province, Y opens the ledger. Choose a research topic there before you end the turn."),
            ], color=art.WAX))
        self._after_turn_prompts()

    def on_resume(self) -> None:
        self.path = []
        self._after_turn_prompts()

    def _after_turn_prompts(self) -> None:
        c = self.camp
        if c.winner:
            self.cs.finish_campaign()
            return
        if c.pending:
            ev = c.pending[0]
            self.app.scenes.push(EventScreen(self.cs, ev))

    # ------------------------------------------------------------------ helpers
    def say(self, text: str, good: bool = True) -> None:
        self.msg, self.msg_t = text, 220
        self.app.audio.play("ui_confirm" if good else "ui_error", 0.6)

    def my_armies(self):
        return sorted([a for a in self.camp.armies_of(self.camp.player) if a.units], key=lambda a: a.id)

    def province_at_mouse(self) -> int | None:
        mx, my = self.inp.mouse_pos
        best, bd = None, (self.size * 0.95) ** 2
        for i, (x, y) in enumerate(self.centers):
            d = (x - mx) ** 2 + (y - my) ** 2
            if d < bd:
                best, bd = i, d
        return best

    def move_cursor(self, dx: int, dy: int) -> None:
        cx, cy = self.centers[self.cur]
        best, bs = None, 1e9
        for n in self.camp.map.adj[self.cur]:
            x, y = self.centers[n]
            vx, vy = x - cx, y - cy
            d = math.hypot(vx, vy) or 1
            along = (vx * dx + vy * dy) / d
            if along < 0.35:
                continue
            s = d * (1.7 - along)
            if s < bs:
                best, bs = n, s
        if best is None:
            # allow hopping two cells when nothing adjacent lies that way
            for p in self.camp.map.provinces:
                x, y = self.centers[p.id]
                vx, vy = x - cx, y - cy
                d = math.hypot(vx, vy) or 1
                along = (vx * dx + vy * dy) / d
                if along > 0.6 and d < self.size * 4 and d < bs:
                    best, bs = p.id, d
        if best is not None:
            self.cur = best
            self.app.audio.play("ui_move", 0.3)
            self._update_path()

    def _update_path(self) -> None:
        self.path = []
        if self.sel_army is not None:
            a = self.camp.armies.get(self.sel_army)
            if a is None:
                self.sel_army = None
                return
            if self.cur != a.pid:
                self.path = self.camp.find_path(a.owner, a.pid, self.cur) or []

    def select_army(self, a) -> None:
        self.sel_army = a.id
        self.cur = a.pid
        self._update_path()
        self.app.audio.play("concord_horn", 0.35)

    # ------------------------------------------------------------------ input
    def update(self, dt: float) -> None:
        self.t += 1
        self.msg_t = max(0, self.msg_t - 1)
        self.floats.update(dt)
        c = self.camp
        p = self.inp.player(0)
        dx, dy = p.menu_dir()
        if dx or dy:
            self.move_cursor(dx, dy)
        mp = self.province_at_mouse()
        if pygame.mouse.get_rel() != (0, 0) and mp is not None and mp != self.cur and MAP_RECT.collidepoint(self.inp.mouse_pos):
            self.cur = mp
            self._update_path()
        click = 1 in self.inp.mouse_pressed and MAP_RECT.collidepoint(self.inp.mouse_pos)
        if click and mp is not None:
            self.cur = mp
            self._update_path()
        if "A" in p.pressed or "CONFIRM" in p.pressed or click:
            self.act_on_cursor()
        if "B" in p.pressed or "BACK" in p.pressed or 3 in self.inp.mouse_pressed:
            if self.sel_army is not None:
                self.sel_army = None
                self.path = []
        if "X" in p.pressed:
            self.open_actions()
        if "Y" in p.pressed:
            self.app.scenes.push(LedgerMenu(self.cs, self))
        if "L" in p.pressed or "R" in p.pressed:
            armies = self.my_armies()
            if armies:
                idx = next((i for i, a in enumerate(armies) if a.id == self.sel_army), -1)
                idx = (idx + (1 if "R" in p.pressed else -1)) % len(armies)
                self.select_army(armies[idx])
        if "SELECT" in p.pressed:
            self.overlay = (self.overlay + 1) % len(OVERLAYS)
            self.app.audio.play("concord_page", 0.4)
        if "PAUSE" in p.pressed:
            self.app.scenes.push(PauseMenu(self.cs))

    def act_on_cursor(self) -> None:
        c = self.camp
        me = c.player
        if self.sel_army is not None:
            a = c.armies.get(self.sel_army)
            if a is None:
                self.sel_army = None
                return
            if self.cur == a.pid:
                self.sel_army = None
                self.path = []
                return
            if c.order_move(me, a.id, self.cur):
                turns = c.path_turns(a, a.path)
                tgt = c.map.provinces[self.cur]
                hostile = tgt.owner and c.dp.at_war(me, tgt.owner)
                self.say(f"Marching to {tgt.name}: {turns} turn{'s' if turns != 1 else ''}" + (" (hostile)" if hostile else ""))
                self.app.audio.play("concord_march", 0.5)
            else:
                tgt = c.map.provinces[self.cur]
                why = "That land belongs to a house you are not at war with." if tgt.owner else "No route."
                self.say(why, False)
            return
        mine = [a for a in c.armies_at(self.cur) if a.owner == me and a.units]
        if mine:
            nxt = mine[self._cycle % len(mine)]
            self._cycle += 1
            self.select_army(nxt)
        else:
            self.app.audio.play("ui_move", 0.3)

    def open_actions(self) -> None:
        c = self.camp
        if self.sel_army is not None and self.sel_army in c.armies:
            self.app.scenes.push(ArmyMenu(self.cs, self, self.sel_army))
        else:
            self.app.scenes.push(ProvinceMenu(self.cs, self, self.cur))

    # ------------------------------------------------------------------ turn flow
    def end_turn(self) -> None:
        c = self.camp
        if c.pending:
            self.say("Resolve the pending decision first.", False)
            return
        self.cs.runner = c.end_turn(ai.plan)
        self.cs.pending_result = None
        self.app.audio.play("concord_seal", 0.7)
        self.step_turn(None)

    def step_turn(self, result: dict | None) -> None:
        c = self.camp
        gen = self.cs.runner
        before = len(c.notes)
        try:
            req = gen.send(result) if result is not None else next(gen)
        except StopIteration:
            self.cs.runner = None
            self._turn_done(before)
            return
        self.app.scenes.push(BattleIntro(self.cs, self, req))

    def battle_finished(self, result: dict) -> None:
        self.step_turn(result)

    def _turn_done(self, before: int) -> None:
        c = self.camp
        self.cs.drain_hooks()
        self.sel_army = None
        self.path = []
        lines = [n for n in c.notes if n.turn == c.turn - 1 and n.kind != "start"]
        keep = [n for n in lines if n.house in (None, c.player) or n.kind in ("capture", "war", "peace", "treaty", "eliminated", "break",
                                                                              "battle", "revolt", "tech")]
        self.cs.save_campaign()
        self.app.audio.play("concord_bell", 0.6)
        if c.winner:
            self.cs.finish_campaign()
            return
        self.app.scenes.push(ReportScreen(self.cs, keep))
        if self.camp.houses[c.player].capital >= 0:
            self.cur = self.camp.houses[c.player].capital if self.cur not in self.camp.map.adj else self.cur

    # ------------------------------------------------------------------ drawing
    def draw(self, surf: pygame.Surface) -> None:
        c = self.camp
        f = self.app.font
        me = c.player
        surf.blit(self.bg, (0, 0))
        vis = c.visible(me)
        mem = c.houses[me].memory
        explored = c.houses[me].explored
        provs = c.map.provinces
        smap = c.supply_map(me) if OVERLAYS[self.overlay] == "supply" else None
        ov = OVERLAYS[self.overlay]
        # ---- tiles
        for p in provs:
            cx, cy = self.centers[p.id]
            tile = art.hex_tile(p.terrain, self.size, p.id % 4)
            if p.id not in explored:
                surf.blit(art.fog_tile(self.size, "unknown"), (cx - tile.get_width() / 2, cy - tile.get_height() / 2))
                continue
            surf.blit(tile, (cx - tile.get_width() / 2, cy - tile.get_height() / 2))
            owner = p.owner if p.id in vis else (mem.get(p.id) or {}).get("owner")
            if ov == "political" and owner:
                tint = pygame.Surface((tile.get_width(), tile.get_height()), pygame.SRCALPHA)
                tint.blit(art.hex_mask(self.size), (0, 0))
                tint.fill((*house_color(self.rules, owner), 70), special_flags=pygame.BLEND_RGBA_MIN)
                surf.blit(tint, (cx - tile.get_width() / 2, cy - tile.get_height() / 2))
            elif ov == "supply" and smap is not None:
                if p.id in smap:
                    tint = pygame.Surface((tile.get_width(), tile.get_height()), pygame.SRCALPHA)
                    tint.blit(art.hex_mask(self.size), (0, 0))
                    k = clamp(smap[p.id] / 5.0)
                    tint.fill((60, 190, 90, int(40 + 90 * k)), special_flags=pygame.BLEND_RGBA_MIN)
                    surf.blit(tint, (cx - tile.get_width() / 2, cy - tile.get_height() / 2))
            elif ov == "unrest" and p.owner == me:
                tint = pygame.Surface((tile.get_width(), tile.get_height()), pygame.SRCALPHA)
                tint.blit(art.hex_mask(self.size), (0, 0))
                tint.fill((220, 60, 50, int(clamp(p.unrest / 100.0) * 170)), special_flags=pygame.BLEND_RGBA_MIN)
                surf.blit(tint, (cx - tile.get_width() / 2, cy - tile.get_height() / 2))
            if p.id not in vis:
                surf.blit(art.fog_tile(self.size, "memory"), (cx - tile.get_width() / 2, cy - tile.get_height() / 2))
        # ---- rivers and roads
        for a, b in c.map.rivers:
            if a in explored and b in explored:
                ca, cb = self.centers[a], self.centers[b]
                e = hexgrid.shared_edge(ca, cb, self.size)
                pygame.draw.line(surf, (70, 120, 180), e[0], e[1], 3)
        for a, b in c.map.roads:
            if a in explored and b in explored:
                pygame.draw.line(surf, (120, 92, 64), self.centers[a], self.centers[b], 2)
                pygame.draw.line(surf, (190, 160, 110), self.centers[a], self.centers[b], 1)
        # ---- borders, icons
        for p in provs:
            if p.id not in explored:
                continue
            cx, cy = self.centers[p.id]
            owner = p.owner if p.id in vis else (mem.get(p.id) or {}).get("owner")
            if owner:
                col = house_color(self.rules, owner)
                for nb in c.map.adj[p.id]:
                    nowner = c.map.provinces[nb].owner if nb in vis else (mem.get(nb) or {}).get("owner")
                    if nb in explored and nowner == owner:
                        continue
                    ca, cb = self.centers[p.id], self.centers[nb]
                    e = hexgrid.shared_edge(ca, cb, self.size)
                    pygame.draw.line(surf, col, e[0], e[1], 2)
            if owner and c.houses[owner].capital == p.id:
                art.draw_castle(surf, cx, cy - 1, house_color(self.rules, owner))
            if p.id in vis:
                nb = sum(p.buildings.values())
                if nb:
                    art.draw_building_pips(surf, cx, cy + self.size * 0.45, nb, house_color(self.rules, p.owner))
                if p.feature:
                    col = (150, 120, 220) if p.feature == "inkwell" else (240, 240, 250)
                    pygame.draw.rect(surf, art.INK, (cx + self.size * 0.35 - 1, cy - self.size * 0.5 - 1, 5, 5))
                    pygame.draw.rect(surf, col, (cx + self.size * 0.35, cy - self.size * 0.5, 3, 3))
                if p.choke:
                    pygame.draw.circle(surf, art.INK, (int(cx - self.size * 0.45), int(cy - self.size * 0.4)), 2, 1)
                if p.wall_damage > 0 or (p.queue and p.owner == me):
                    f.draw(surf, "!" if p.wall_damage > 0 else "+", (cx - self.size * 0.5, cy + self.size * 0.1), (200, 40, 40) if p.wall_damage > 0 else (60, 90, 60), None)
        # ---- path preview
        if self.path and self.sel_army in c.armies:
            a = c.armies[self.sel_army]
            pts = [self.centers[a.pid]] + [self.centers[q] for q in self.path]
            for i in range(len(pts) - 1):
                x0, y0 = pts[i]
                x1, y1 = pts[i + 1]
                n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 5))
                for k in range(0, n, 2):
                    t0, t1 = k / n, min(1.0, (k + 1) / n)
                    pygame.draw.line(surf, (255, 255, 255), (x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1), 2)
                    pygame.draw.line(surf, art.INK, (x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0 + 1), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1 + 1), 1)
            f.draw(surf, f"{c.path_turns(a, self.path)}t", (pts[-1][0] + 6, pts[-1][1] - 12), (255, 255, 255), art.INK)
        # ---- orders of every own army (thin lines)
        for a in c.armies_of(me):
            if a.path and a.id != self.sel_army:
                pts = [self.centers[a.pid]] + [self.centers[q] for q in a.path]
                pygame.draw.lines(surf, house_color(self.rules, me), False, pts, 1)
        # ---- armies
        stacks: dict[int, list] = {}
        for a in c.armies.values():
            if not a.units:
                continue
            if a.owner == me or a.pid in vis:
                stacks.setdefault(a.pid, []).append(a)
        for pid, group in stacks.items():
            cx, cy = self.centers[pid]
            for i, a in enumerate(group[:3]):
                art.draw_banner(surf, cx + (i - (len(group[:3]) - 1) / 2) * 11, cy + 2, house_color(self.rules, a.owner), len(a.units), f,
                                a.id == self.sel_army, a.stance, bool(a.path) and a.owner == me)
        # ---- remembered armies (ghosts)
        for pid, m in mem.items():
            if pid in vis or not m["armies"]:
                continue
            cx, cy = self.centers[pid]
            f.draw(surf, "?", (cx - 2, cy - 3), (110, 90, 90), None)
        # ---- cursor
        cx, cy = self.centers[self.cur]
        pulse = 0.5 + 0.5 * math.sin(self.t * 0.12)
        art.draw_hex_outline(surf, cx, cy, self.size + 1, (255, 255, 255), 2)
        art.draw_hex_outline(surf, cx, cy, self.size - 1, art.INK, 1)
        self._top_bar(surf)
        self._side_panel(surf)
        self.floats.draw(surf, f)
        if self.msg_t > 0:
            r = pygame.Rect(30, H - 40, 300, 14)
            draw_panel(surf, r, fill=(40, 34, 56), alpha=245)
            f.draw(surf, self.msg, (r.centerx, r.y + 3), PARCHMENT, None, anchor="midtop")
        keys = [("A", "Select/Order"), ("X", "Province" if self.sel_army is None else "Army"), ("Y", "Ledger"), ("L", "Army"), ("SELECT", OVERLAYS[self.overlay])]
        draw_prompts(surf, self.app, keys, y=H - 12)

    def _top_bar(self, surf: pygame.Surface) -> None:
        c = self.camp
        f = self.app.font
        me = c.player
        h = c.houses[me]
        pygame.draw.rect(surf, (40, 34, 56), (0, 0, W, 20))
        pygame.draw.line(surf, BRASS, (0, 20), (W, 20))
        surf.blit(art.crest(house_color(self.rules, me), 12), (3, 2))
        f.draw(surf, f"{c.date_text()}", (20, 2), PARCHMENT, None)
        f.draw(surf, f"Turn {c.turn}", (W - 4, 2), DIM, None, anchor="topright")
        flow = c.house_flow(me)["net"]
        x = 20
        for r in RESOURCES:
            v = int(h.stock.get(r, 0))
            nv = flow[r]
            col = RES_COL[r]
            f.draw(surf, RES_SHORT[r], (x, 11), col, None)
            f.draw(surf, str(v), (x + 14, 11), PARCHMENT, None)
            f.draw(surf, f"{nv:+.0f}", (x + 14 + f.width(str(v)) + 3, 11), GOOD if nv >= 0 else DANGER, None)
            x += 62
        f.draw(surf, f"Research {int(h.progress)}/{int(c.tech_cost(h.research)) if h.research else 0}" if h.research else "Research: idle",
               (W - 4, 11), LENS if h.research else DANGER, None, anchor="topright")

    def _side_panel(self, surf: pygame.Surface) -> None:
        c = self.camp
        f = self.app.font
        me = c.player
        r = pygame.Rect(SIDE_X, 24, W - SIDE_X - 3, H - 24 - 18)
        draw_panel(surf, r, fill=(40, 34, 56), alpha=245)
        x, y = r.x + 6, r.y + 5
        vis = c.visible(me)
        p = c.map.provinces[self.cur]
        explored = self.cur in c.houses[me].explored
        if not explored:
            f.draw(surf, "Unexplored", (x, y), DIM, None)
            f.draw(surf, "Move an army here or scout it (1 ink).", (x, y + 12), DIM, None)
            return
        seen = self.cur in vis
        mem = c.houses[me].memory.get(self.cur, {})
        owner = p.owner if seen else mem.get("owner")
        f.draw(surf, p.name, (x, y), PARCHMENT, None)
        f.draw(surf, TERRAIN_NAMES[p.terrain] + ("  [choke]" if p.choke else "") + (f"  [{p.feature}]" if p.feature else ""), (x, y + 10), DIM, None)
        if owner:
            surf.blit(art.crest(house_color(self.rules, owner), 8), (x, y + 21))
            f.draw(surf, c.short(owner) + ("" if seen else f"  (seen t{mem.get('turn', '?')})"), (x + 12, y + 21), house_color(self.rules, owner), None)
        else:
            f.draw(surf, "Unclaimed", (x, y + 21), DIM, None)
        y += 34
        if seen:
            yl = c.province_yield(p)
            line = " ".join(f"{RES_SHORT[r_]}{v:.0f}" for r_, v in yl.items() if v >= 0.5)
            if p.owner:
                f.draw(surf, line or "no yield", (x, y), PARCHMENT, None)
                y += 10
            if p.buildings:
                for bid, lvl in p.buildings.items():
                    f.draw(surf, f"{c.rules.buildings[bid]['name']} {lvl}", (x, y), (200, 190, 170), None)
                    y += 9
            if p.queue:
                q = p.queue[0]
                f.draw(surf, f"Building {c.rules.buildings[q['b']]['name']} ({q['left']})", (x, y), LENS, None)
                y += 9
            if p.owner == me:
                col = DANGER if p.unrest >= 50 else (255, 190, 100) if p.unrest >= 25 else GOOD
                f.draw(surf, f"Unrest {int(p.unrest)}", (x, y), col, None)
                y += 9
                if p.devastation > 0.05:
                    f.draw(surf, f"Devastated {int(p.devastation * 100)}%", (x, y), DANGER, None)
                    y += 9
            fl = c.fort_level(p)
            if fl:
                f.draw(surf, f"Fort {fl}" + (f"  walls {p.wall_damage:.0f}/{2 * fl}" if p.wall_damage else ""), (x, y), (210, 180, 120), None)
                y += 9
            if p.owner is None and any(c.map.provinces[n].owner == me for n in c.map.adj[p.id]):
                f.draw(surf, f"Claim: {c.claim_cost(me)} coin", (x, y), GOOD, None)
                y += 9
            y += 3
            for a in c.armies_at(p.id):
                if not a.units:
                    continue
                col = house_color(self.rules, a.owner)
                f.draw(surf, f"{c.short(a.owner)} army: {len(a.units)}", (x, y), col, None)
                y += 9
                if a.owner == me:
                    counts: dict[str, int] = {}
                    for u in a.units:
                        counts[c.rules.units[u.type]["role"]] = counts.get(c.rules.units[u.type]["role"], 0) + 1
                    f.draw(surf, " ".join(f"{art.ROLE_GLYPH[k]}{v}" for k, v in sorted(counts.items())), (x + 4, y), DIM, None)
                    y += 9
                if y > r.bottom - 40:
                    break
        else:
            f.draw(surf, "Out of sight", (x, y), DIM, None)
            y += 10
            if mem.get("armies"):
                f.draw(surf, "Armies were seen here.", (x, y), (200, 150, 150), None)
                y += 10
        if self.sel_army in c.armies:
            self._army_card(surf, r, c.armies[self.sel_army])

    def _army_card(self, surf: pygame.Surface, r: pygame.Rect, a) -> None:
        c = self.camp
        f = self.app.font
        y = r.bottom - 74
        pygame.draw.line(surf, BRASS, (r.x + 4, y - 3), (r.right - 5, y - 3))
        smap = c.supply_map(a.owner)
        f.draw(surf, f"Army {a.name}: {len(a.units)} units", (r.x + 6, y), PARCHMENT, None)
        f.draw(surf, f"Speed {c.army_speed(a)}  Str {c.army_strength(a):.0f}", (r.x + 6, y + 10), DIM, None)
        f.draw(surf, "Supplied" if a.pid in smap else "OUT OF SUPPLY", (r.x + 6, y + 20), GOOD if a.pid in smap else DANGER, None)
        f.draw(surf, f"Stance: {a.stance}", (r.x + 6, y + 30), (200, 190, 170), None)
        # hp ticks
        from . import battle as B
        techs, m = c.houses[a.owner].techs, c.mods(a.owner)
        bx = r.x + 6
        for i, u in enumerate(a.units[:8]):
            mx = B.unit_stats(c.rules, u, techs, m)["hp"]
            k = clamp(u.hp / mx)
            pygame.draw.rect(surf, (20, 16, 30), (bx + i * 14, y + 42, 12, 5))
            pygame.draw.rect(surf, GOOD if k > 0.6 else (255, 190, 100) if k > 0.3 else DANGER, (bx + i * 14 + 1, y + 43, int(10 * k), 3))
            f.draw(surf, art.ROLE_GLYPH[c.rules.units[u.type]["role"]], (bx + i * 14 + 3, y + 49), DIM, None)


# ====================================================================================== menus
class ProvinceMenu(MenuScene):
    def __init__(self, cs: ConcordScene, mapscreen: MapScreen, pid: int):
        self.cs, self.ms, self.pid = cs, mapscreen, pid
        super().__init__(cs.app, cs.camp.map.provinces[pid].name.upper(), self._items, 230)

    def _items(self) -> list[MenuItem]:
        c, pid = self.cs.camp, self.pid
        me = c.player
        p = c.map.provinces[pid]
        out: list[MenuItem] = []
        if p.owner == me:
            out.append(MenuItem("Build...", lambda: self.app.scenes.push(BuildMenu(self.cs, self.ms, pid)),
                                hint=f"Slots {len(p.buildings)}/{ {'plain': 3, 'forest': 2, 'hill': 3, 'marsh': 2, 'mountain': 2}[p.terrain]}"))
            rec = c.recruitable(me, pid)
            out.append(MenuItem("Recruit...", lambda: self.app.scenes.push(RecruitMenu(self.cs, self.ms, pid)), enabled=bool(rec),
                                hint=f"{c.recruits_left(pid)} recruits left this turn" if rec else "Needs a barracks, stable or workshop"))
            if p.queue:
                out.append(MenuItem("Cancel construction", self._cancel, hint="Refunds 60%"))
        elif p.owner is None:
            cost = c.claim_cost(me)
            adj = any(c.map.provinces[n].owner == me for n in c.map.adj[pid])
            out.append(MenuItem(f"Claim ({cost} coin)", self._claim, enabled=adj and c.houses[me].stock["coin"] >= cost,
                                hint="Annex unclaimed land beside yours" if adj else "Must border your land"))
        out.append(MenuItem("Scout (1 ink)", self._scout, enabled=c.houses[me].stock.get("ink", 0) >= 1,
                            hint="See this province and its neighbours for 3 turns"))
        out.append(MenuItem("Back", self.app.scenes.pop))
        return out

    def _cancel(self) -> None:
        c = self.cs.camp
        c.cancel_build(c.player, self.pid, len(c.map.provinces[self.pid].queue) - 1)
        self.rebuild()

    def _claim(self) -> None:
        c = self.cs.camp
        if c.claim_neutral(c.player, self.pid):
            self.ms.say("Province claimed.")
            self.app.audio.play("concord_seal", 0.6)
            self.app.scenes.pop()
        else:
            self.ms.say("Cannot claim it.", False)

    def _scout(self) -> None:
        c = self.cs.camp
        if c.scout(c.player, self.pid):
            self.app.audio.play("concord_quill", 0.5)
            self.app.scenes.pop()


class BuildMenu(MenuScene):
    def __init__(self, cs: ConcordScene, ms: MapScreen, pid: int):
        self.cs, self.ms, self.pid = cs, ms, pid
        super().__init__(cs.app, "BUILD", self._items, 280)

    def _items(self) -> list[MenuItem]:
        c, pid = self.cs.camp, self.pid
        me = c.player
        p = c.map.provinces[pid]
        items = []
        for bid, b in sorted(c.rules.buildings.items(), key=lambda kv: kv[1]["name"]):
            cur = p.buildings.get(bid, 0)
            ok, why = c.can_build(me, pid, bid)
            cost = c.building_cost(me, bid, cur + 1)
            ctext = " ".join(f"{v}{RES_SHORT[r]}" for r, v in cost.items())
            lab = f"{b['name']}{' ' + str(cur + 1) if cur else ''}  {ctext}"
            hint = b["desc"] if ok else why
            if ok and b.get("trade_off"):
                hint += "  Cost: " + b["trade_off"]
            items.append(MenuItem(lab, (lambda bid=bid: self._do(bid)), enabled=ok, hint=hint[:110]))
        items.append(MenuItem("Back", self.app.scenes.pop))
        return items

    def _do(self, bid: str) -> None:
        c = self.cs.camp
        if c.build(c.player, self.pid, bid):
            self.app.audio.play("concord_seal", 0.6)
            self.ms.say(f"{c.rules.buildings[bid]['name']} begun.")
            self.rebuild()


class RecruitMenu(MenuScene):
    def __init__(self, cs: ConcordScene, ms: MapScreen, pid: int):
        self.cs, self.ms, self.pid = cs, ms, pid
        super().__init__(cs.app, "RECRUIT", self._items, 290)

    def _items(self) -> list[MenuItem]:
        c, pid = self.cs.camp, self.pid
        me = c.player
        items = []
        for uid in c.recruitable(me, pid):
            u = c.rules.units[uid]
            ok, why = c.can_recruit(me, pid, uid)
            cost = c.unit_cost(me, uid)
            ctext = " ".join(f"{v}{RES_SHORT[r]}" for r, v in cost.items())
            stats = f"HP{u['hp']} Atk{u['atk']:.0f} Arm{u['arm']:.0f} Mv{u['move']} Rng{u['range']}"
            hint = (f"{stats}. {u.get('ability', {}).get('name', '')}: {u.get('ability', {}).get('desc', '')}" if ok else why)[:120]
            items.append(MenuItem(f"{u['name']}  {ctext}", (lambda uid=uid: self._do(uid)), enabled=ok, hint=hint))
        items.append(MenuItem("Back", self.app.scenes.pop))
        return items

    def _do(self, uid: str) -> None:
        c = self.cs.camp
        if c.recruit(c.player, self.pid, uid):
            self.app.audio.play("concord_horn", 0.5)
            self.ms.say(f"{c.rules.units[uid]['name']} recruited.")
            self.rebuild()


class ArmyMenu(MenuScene):
    def __init__(self, cs: ConcordScene, ms: MapScreen, aid: int):
        self.cs, self.ms, self.aid = cs, ms, aid
        super().__init__(cs.app, "ARMY ORDERS", self._items, 240)

    def _items(self) -> list[MenuItem]:
        c = self.cs.camp
        a = c.armies.get(self.aid)
        if a is None:
            return [MenuItem("Back", self.app.scenes.pop)]
        others = [x for x in c.armies_at(a.pid) if x.owner == a.owner and x.id != a.id and x.units]
        items = [MenuItem("Stance", None, kind="choice", get=lambda: a.stance, set=self._stance, choices=["march", "raid", "pillage"],
                          hint="March: just move. Raid: devastate and loot enemy land. Pillage: also loot captured provinces."),
                 MenuItem("Merge with army here", self._merge, enabled=bool(others) and len(a.units) < 8,
                          hint="Combine stacks (max 8 units)"),
                 MenuItem("Split off the weaker half", self._split, enabled=len(a.units) >= 2),
                 MenuItem("Cancel orders", self._cancel, enabled=bool(a.path)),
                 MenuItem("Back", self.app.scenes.pop)]
        return items

    def _stance(self, v: str) -> None:
        self.cs.camp.set_stance(self.cs.camp.player, self.aid, v)

    def _merge(self) -> None:
        c = self.cs.camp
        a = c.armies[self.aid]
        for x in c.armies_at(a.pid):
            if x.owner == a.owner and x.id != a.id and x.units:
                c.merge(a.owner, a.id, x.id)
                break
        self.rebuild()

    def _split(self) -> None:
        c = self.cs.camp
        a = c.armies[self.aid]
        ids = [u.uid for u in sorted(a.units, key=lambda u: u.hp)[: len(a.units) // 2]]
        n = c.split(a.owner, a.id, ids)
        if n:
            self.ms.say("Army split. Select the new army with L/R.")
        self.rebuild()

    def _cancel(self) -> None:
        a = self.cs.camp.armies[self.aid]
        a.path = []
        self.rebuild()


class PauseMenu(MenuScene):
    def __init__(self, cs: ConcordScene):
        self.cs = cs
        super().__init__(cs.app, "PAUSED", self._items, 220, overlay=True, footer=[("CONFIRM", "Select"), ("BACK", "Resume")])

    def _items(self) -> list[MenuItem]:
        a = self.app
        return [MenuItem("Resume", a.scenes.pop), MenuItem("Save campaign", self._save),
                MenuItem("Settings", lambda: a.scenes.push(SettingsScene(a))),
                MenuItem("Controls", lambda: a.scenes.push(ControlsScene(a))),
                MenuItem("Campaign menu (saves)", self._menu), MenuItem("Leave shard (saves)", self._leave)]

    def _save(self) -> None:
        self.cs.save_campaign()
        self.app.toast("Campaign saved", GOOD)

    def _menu(self) -> None:
        self.app.scenes.pop()
        if self.cs.camp and not self.cs.camp.winner:
            self.cs.save_campaign()
        self.cs.show_menu()

    def _leave(self) -> None:
        self.app.scenes.pop()
        if self.cs.camp and not self.cs.camp.winner:
            self.cs.save_campaign()
        self.cs.finish(left=True)


from .ui_ledger import EndScreen, EventScreen, LedgerMenu, ReportScreen  # noqa: E402
from .ui_battle import BattleIntro  # noqa: E402
