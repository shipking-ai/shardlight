"""Verdant overlays: conversation, shop, crafting, journal (pack / quests / map / skills / beasts), text, rest, death."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pygame

from ...core.fx import clamp, mix
from ...core.scene import Scene
from ...core.ui import (BRASS, DANGER, DIM, GOOD, INK, INK_2, LENS, PARCHMENT, Menu, MenuItem, draw_panel, draw_prompts)
from . import art
from . import tiles as T
from .sim import SKILL_LABEL, SKILLS, skill_level

W, H = 480, 270


def _wrap(app, surf, text, rect, color=PARCHMENT, max_lines=None):
    return app.font.draw_wrapped(surf, text, rect, color, None, max_lines=max_lines)


class _MouseRows:
    """Clickable list rows, rebuilt at draw time. Hover follows the pointer; click activates.

    Mirrors the mouse handling of core Menu: hover only steals the selection once the
    pointer actually moves, so keyboard navigation is never interrupted mid-frame.
    """

    def __init__(self, app):
        self.app = app
        self.rects: list[tuple[pygame.Rect, int]] = []

    def reset(self) -> None:
        self.rects.clear()

    def add(self, rect: pygame.Rect, idx: int) -> None:
        self.rects.append((rect, idx))

    def poll(self, cur: Callable[[], int], set_sel: Callable[[int], None], activate: Callable[[int], None],
             alt: Callable[[int], None] | None = None) -> None:
        inp = self.app.input
        mx, my = inp.mouse_pos
        hover = [idx for r, idx in self.rects if r.collidepoint(mx, my)]
        if not hover:
            return
        idx = hover[0]
        moved = pygame.mouse.get_rel() != (0, 0)
        if moved and cur() != idx:
            set_sel(idx)
            self.app.audio.play("ui_move", 0.5)
        if 1 in inp.mouse_pressed:
            activate(idx)
        elif alt is not None and 3 in inp.mouse_pressed:
            alt(idx)


# ====================================================================================== text
class TextOverlay(Scene):
    opaque = False

    def __init__(self, app, title: str, text: str):
        super().__init__(app)
        self.title, self.text = title, text
        self.age = 0.0

    def update(self, dt: float) -> None:
        self.age += dt
        p = self.inp.player(0)
        if self.age > 0.15 and (p.any_pressed(("CONFIRM", "BACK", "B", "A")) or 1 in self.inp.mouse_pressed):
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        lines = f.wrap(self.text, 330)
        h = 28 + len(lines) * f.line_height() + 10
        r = pygame.Rect((W - 360) // 2, max(10, (H - h) // 2), 360, h)
        draw_panel(surf, r, title=self.title, font=f)
        f.draw_wrapped(surf, self.text, pygame.Rect(r.x + 14, r.y + 18, 332, h), PARCHMENT, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Close")], y=r.bottom - 14)


# ====================================================================================== dialogue
class DialogueScreen(Scene):
    opaque = False

    def __init__(self, vs, g, npc_id: str):
        super().__init__(vs.app)
        self.vs, self.g, self.npc = vs, g, npc_id
        self.info = g.npc_dialogue(npc_id)
        self.age = 0.0
        g.talking = npc_id
        g.sfx("verdant_pickup")
        progressed, msg = g.finish_talk(npc_id)
        self.text = msg or self.info["greet"]
        self.mode = "main"
        self.pending: str | None = None
        self.menu = Menu(self.app, [], 400)
        self.rebuild()

    def on_exit(self) -> None:
        self.g.talking = ""

    def say(self, text: str) -> None:
        self.text = text

    def rebuild(self) -> None:
        g = self.g
        self.info = g.npc_dialogue(self.npc)
        items: list[MenuItem] = []
        if self.mode == "offer":
            q = g.cat.quest(self.pending)
            items = [MenuItem("Accept", self._accept), MenuItem("Not now", self._decline)]
        else:
            for qid in self.info["offers"]:
                q = g.cat.quest(qid)
                items.append(MenuItem(f"! {q['title']}", lambda qid=qid: self._offer(qid)))
            for qid in self.info["turn_in"]:
                q = g.cat.quest(qid)
                items.append(MenuItem(f"? {q['title']} - report", lambda qid=qid: self._report(qid)))
            if self.info["shop"]:
                items.append(MenuItem("Trade", self._trade))
            elif self.info["shop_closed"]:
                items.append(MenuItem("Trade (come to the shop)", None, enabled=False))
            for t in self.info["topics"]:
                items.append(MenuItem(f"Ask: {t['label']}", lambda t=t: self._topic(t)))
            items.append(MenuItem("Goodbye", self._bye))
        self.menu = Menu(self.app, items, 440)

    def _offer(self, qid: str) -> None:
        self.pending = qid
        self.mode = "offer"
        self.say(self.g.cat.quest(qid)["offer"])
        self.rebuild()

    def _accept(self) -> None:
        qid = self.pending
        self.g.accept_quest(qid)
        self.mode = "main"
        self.say("Good. Mind yourself out there.")
        self.rebuild()

    def _decline(self) -> None:
        self.mode = "main"
        self.say("Another time, then.")
        self.rebuild()

    def _report(self, qid: str) -> None:
        ok, msg = self.g.finish_talk(self.npc)
        self.say(msg or "Not yet. Come back when you have what I asked for.")
        self.rebuild()

    def _trade(self) -> None:
        self.app.scenes.push(ShopScreen(self.vs, self.g, self.info["shop"]))

    def _topic(self, t: dict) -> None:
        self.g.tell_topic(t)
        self.say(t["text"])
        self.rebuild()

    def _bye(self) -> None:
        self.app.scenes.pop()

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.12:
            return
        p = self.inp.player(0)
        if "BACK" in p.pressed:
            if self.mode == "offer":
                self._decline()
            else:
                self._bye()
            return
        self.menu.update()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        n = len(self.menu.items)
        h = 64 + n * 14 * f.scale + 10
        r = pygame.Rect(20, H - h - 8, W - 40, h)
        draw_panel(surf, r, border=tuple(self.info["color"]) if self.info["color"] else BRASS, title=f"{self.info['name']} - {self.info['role']}", font=f)
        _wrap(self.app, surf, self.text, pygame.Rect(r.x + 12, r.y + 14, r.w - 24, 52), PARCHMENT, 5)
        self.menu.draw(surf, (r.x + 8, r.y + 58))


# ====================================================================================== shop
class ShopScreen(Scene):
    opaque = False

    def __init__(self, vs, g, shop_id: str):
        super().__init__(vs.app)
        self.vs, self.g, self.shop_id = vs, g, shop_id
        self.shop = g.cat.shop(shop_id)
        self.tab = 0
        self.sel = 0
        self.msg = ""
        self.age = 0.0
        self.rep = 0.0
        self._mrows = _MouseRows(self.app)
        self._mtab: list[tuple[pygame.Rect, int]] = []

    def rows(self) -> list[tuple[str, int, int]]:
        g = self.g
        if self.tab == 0:
            return [(i, q, p) for i, q, p in g.shop_items(self.shop_id)]
        out = []
        for it, n in sorted(g.p.inv.items()):
            price = g.sell_price(it, self.shop)
            if price > 0 and n > 0:
                out.append((it, n, price))
        return out

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.12:
            return
        p = self.inp.player(0)
        if "BACK" in p.pressed:
            self.app.scenes.pop()
            return
        if "L" in p.pressed or "R" in p.pressed:
            self.tab = 1 - self.tab
            self.sel = 0
        dx, dy = p.menu_dir()
        rows = self.rows()
        if dx:
            self.tab = 1 - self.tab
            self.sel = 0
        if dy and rows:
            self.sel = (self.sel + dy) % len(rows)
            self.app.audio.play("ui_move", 0.5)
        # mouse: hover selects, click buys/sells, right click leaves, wheel scrolls
        if 3 in self.inp.mouse_pressed:
            self.app.scenes.pop()
            return
        if self.inp.wheel and rows:
            self.sel = clamp(self.sel - self.inp.wheel, 0, len(rows) - 1)
        for rt, t2 in self._mtab:
            if rt.collidepoint(*self.inp.mouse_pos) and 1 in self.inp.mouse_pressed and self.tab != t2:
                self.tab = t2
                self.sel = 0
                self.app.audio.play("ui_move", 0.5)
        self._mrows.poll(
            lambda: min(self.sel, max(0, len(self.rows()) - 1)),
            lambda i: setattr(self, "sel", min(i, max(0, len(self.rows()) - 1))),
            lambda i: self._trade_row(i),
        )

    def _trade_row(self, i: int) -> None:
        rows = self.rows()
        if not rows or i >= len(rows):
            return
        it = rows[i][0]
        self.msg = self.g.buy(self.shop_id, it) if self.tab == 0 else self.g.sell(self.shop_id, it)
        self.sel = min(i, max(0, len(self.rows()) - 1))

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        g = self.g
        r = pygame.Rect(30, 18, W - 60, H - 36)
        surf.fill((10, 10, 16))
        draw_panel(surf, r, title=self.shop["name"], font=f, alpha=255)
        bw = f.width("BUY") + 6
        f.draw(surf, "BUY", (r.x + 14, r.y + 14), BRASS if self.tab == 0 else DIM, None)
        f.draw(surf, "SELL", (r.x + 14 + bw, r.y + 14), DIM if self.tab == 0 else BRASS, None)
        self._mtab = [(pygame.Rect(r.x + 12, r.y + 11, bw, 13), 0),
                      (pygame.Rect(r.x + 12 + bw, r.y + 11, f.width("SELL") + 4, 13), 1)]
        f.draw(surf, "[L/R] switch", (r.x + 14 + bw + f.width("SELL") + 10, r.y + 14), DIM, None)
        f.draw(surf, f"Gold: {g.p.gold}", (r.right - 14, r.y + 14), (255, 220, 100), None, anchor="topright")
        rows = self.rows()
        y0 = r.y + 30
        vis = 12
        top = max(0, min(self.sel - vis // 2, max(0, len(rows) - vis)))
        self._mrows.reset()
        for i, (it, q, price) in enumerate(rows[top:top + vis]):
            idx = top + i
            d = g.cat.item(it)
            rr = pygame.Rect(r.x + 10, y0 + i * 13, 230, 12)
            self._mrows.add(rr, idx)
            if idx == self.sel:
                pygame.draw.rect(surf, INK_2, rr)
                pygame.draw.rect(surf, BRASS, (rr.x, rr.y, 2, rr.h))
            surf.blit(art.icon(d["kind"], tuple(d.get("color", (200, 200, 200))), 10), (rr.x + 5, rr.y + 1))
            col = PARCHMENT if (self.tab == 1 or q > 0) else (90, 86, 100)
            f.draw(surf, d["name"], (rr.x + 18, rr.y + 2), col, None)
            right = f"x{q}  {price}g" if self.tab == 0 else f"x{q}  {price}g"
            f.draw(surf, right, (rr.right - 4, rr.y + 2), (255, 220, 100) if (self.tab == 1 or g.p.gold >= price) else DANGER, None, anchor="topright")
        if not rows:
            f.draw(surf, "Nothing here." if self.tab == 0 else "Nothing they would buy.", (r.x + 16, y0 + 4), DIM, None)
        # detail
        dr = pygame.Rect(r.x + 252, r.y + 30, r.w - 266, r.h - 60)
        if rows:
            it = rows[min(self.sel, len(rows) - 1)][0]
            d = g.cat.item(it)
            f.draw(surf, d["name"], (dr.x, dr.y), (255, 244, 205), None)
            f.draw(surf, d["kind"].title(), (dr.x, dr.y + 11), DIM, None)
            y = _wrap(self.app, surf, d.get("desc", ""), pygame.Rect(dr.x, dr.y + 26, dr.w, 40), PARCHMENT, 4)
            y += 4
            for lbl, key, cur in (("Damage", "dmg", g.weapon().get("dmg", 0) if d.get("slot") != "bow" else (g.bow() or {}).get("dmg", 0)),
                                  ("Armour", "armor", g.armor()), ("Heals", "heal", 0), ("Reach", "reach", g.weapon().get("reach", 0))):
                if d.get(key):
                    delta = d[key] - cur
                    txt = f"{lbl}: {d[key]:g}" + (f" ({delta:+g})" if key in ("dmg", "armor") and delta else "")
                    f.draw(surf, txt, (dr.x, y), GOOD if delta > 0 else PARCHMENT, None)
                    y += 11
        f.draw(surf, self.msg, (r.x + 14, r.bottom - 26), LENS, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Buy" if self.tab == 0 else "Sell"), ("BACK", "Leave")], y=r.bottom - 14)


# ====================================================================================== crafting
class CraftScreen(Scene):
    opaque = False
    NAMES = {"hearth": "Hearth", "forge": "Forge", "bench": "Workbench"}

    def __init__(self, vs, g, station: str):
        super().__init__(vs.app)
        self.vs, self.g, self.station = vs, g, station
        self.sel = 0
        self.msg = ""
        self.age = 0.0
        self._mrows = _MouseRows(self.app)

    def recipes(self):
        return self.g.cat.recipes(self.station)

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.12:
            return
        p = self.inp.player(0)
        if "BACK" in p.pressed or "B" in p.pressed and self.age > 0.3:
            self.app.scenes.pop()
            return
        rs = self.recipes()
        _, dy = p.menu_dir()
        if dy and rs:
            self.sel = (self.sel + dy) % len(rs)
            self.app.audio.play("ui_move", 0.5)
        # mouse: hover selects, click crafts, right click closes, wheel scrolls
        if 3 in self.inp.mouse_pressed:
            self.app.scenes.pop()
            return
        if self.inp.wheel and rs:
            self.sel = clamp(self.sel - self.inp.wheel, 0, len(rs) - 1)
        self._mrows.poll(
            lambda: min(self.sel, max(0, len(self.recipes()) - 1)),
            lambda i: setattr(self, "sel", min(i, max(0, len(self.recipes()) - 1))),
            lambda i: self._craft_row(i),
        )

    def _craft_row(self, i: int) -> None:
        rs = self.recipes()
        if rs and i < len(rs):
            self.sel = i
            self.msg = self.g.craft(rs[i]["id"])

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        g = self.g
        r = pygame.Rect(40, 24, W - 80, H - 48)
        surf.fill((10, 10, 16))
        draw_panel(surf, r, title=self.NAMES.get(self.station, self.station), font=f, alpha=255)
        rs = self.recipes()
        vis = 12
        top = max(0, min(self.sel - vis // 2, max(0, len(rs) - vis)))
        self._mrows.reset()
        for i, rc in enumerate(rs[top:top + vis]):
            idx = top + i
            rr = pygame.Rect(r.x + 10, r.y + 16 + i * 13, 190, 12)
            self._mrows.add(rr, idx)
            if idx == self.sel:
                pygame.draw.rect(surf, INK_2, rr)
                pygame.draw.rect(surf, BRASS, (rr.x, rr.y, 2, rr.h))
            ok = g.craft_level() >= rc.get("skill", 0) and all(g.count(it) >= n for it, n in rc["inputs"].items())
            d = g.cat.item(rc["out"])
            f.draw(surf, f"{d['name']}" + (f" x{rc['count']}" if rc.get("count", 1) > 1 else ""), (rr.x + 8, rr.y + 2), PARCHMENT if ok else (100, 96, 112), None)
        if rs:
            rc = rs[self.sel]
            d = g.cat.item(rc["out"])
            dr = pygame.Rect(r.x + 214, r.y + 16, r.w - 226, 120)
            f.draw(surf, d["name"], (dr.x, dr.y), (255, 244, 205), None)
            y = _wrap(self.app, surf, d.get("desc", ""), pygame.Rect(dr.x, dr.y + 12, dr.w, 30), DIM, 3)
            y += 6
            f.draw(surf, "Needs:", (dr.x, y), BRASS, None)
            y += 11
            for it, n in rc["inputs"].items():
                have = g.count(it)
                f.draw(surf, f"{g.cat.item(it)['name']}  {have}/{n}", (dr.x + 6, y), GOOD if have >= n else DANGER, None)
                y += 11
            if rc.get("skill", 0):
                ok = g.craft_level() >= rc["skill"]
                f.draw(surf, f"Skill level {rc['skill']} (yours {g.craft_level()})", (dr.x, y + 3), GOOD if ok else DANGER, None)
        else:
            f.draw(surf, "No recipes known.", (r.x + 16, r.y + 20), DIM, None)
        f.draw(surf, self.msg, (r.x + 12, r.bottom - 26), LENS, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Make"), ("BACK", "Close")], y=r.bottom - 14)


# ====================================================================================== rest / death
class RestOverlay(Scene):
    opaque = False

    def __init__(self, vs, g):
        super().__init__(vs.app)
        self.vs, self.g = vs, g
        self.menu = Menu(self.app, [MenuItem("Sleep until morning (10 gold)", self._sleep, enabled=g.p.gold >= 10), MenuItem("Never mind", self._no)], 240)
        self.age = 0.0

    def _sleep(self) -> None:
        self.g.rest()
        self.vs.save_game()
        self.app.scenes.pop()

    def _no(self) -> None:
        self.app.scenes.pop()

    def update(self, dt: float) -> None:
        self.age += dt
        if self.age < 0.12:
            return
        if "BACK" in self.inp.player(0).pressed:
            self._no()
            return
        self.menu.update()

    def draw(self, surf: pygame.Surface) -> None:
        r = pygame.Rect(W // 2 - 130, H // 2 - 30, 260, 62)
        draw_panel(surf, r, title="A room for the night", font=self.app.font)
        self.menu.draw(surf, (r.x + 8, r.y + 14))


class DeathOverlay(Scene):
    opaque = False

    def __init__(self, vs, g):
        super().__init__(vs.app)
        self.vs, self.g = vs, g
        self.menu = Menu(self.app, [MenuItem("Wake at the last shrine", self._wake)], 220)
        self.t = 0.0

    def _wake(self) -> None:
        self.g.respawn()
        self.vs.save_game()
        self.app.scenes.pop()
        sc = self.vs.screen
        if hasattr(sc, "snap_camera"):
            sc.snap_camera()
            sc.fade = 1.0

    def update(self, dt: float) -> None:
        self.t += dt
        if self.t > 1.2:
            self.menu.update()

    def draw(self, surf: pygame.Surface) -> None:
        ov = pygame.Surface((W, H))
        ov.set_alpha(int(min(1.0, self.t / 1.0) * 200))
        ov.fill((20, 0, 8))
        surf.blit(ov, (0, 0))
        f = self.app.font
        if self.t > 0.4:
            f.draw(surf, "YOU FALL", (W // 2, 80), (230, 90, 90), (10, 0, 4), anchor="midtop", scale=4)
            f.draw(surf, "Some debts are paid in daylight.", (W // 2, 126), PARCHMENT, (10, 0, 4), anchor="midtop")
        if self.t > 1.2:
            self.menu.draw(surf, (W // 2 - 110, 160))


# ====================================================================================== journal
class JournalScreen(Scene):
    opaque = True
    TABS = ["Pack", "Quests", "Map", "Skills", "Beasts"]

    def __init__(self, vs, g):
        super().__init__(vs.app)
        self.vs, self.g = vs, g
        self.tab = 0
        self.sel = [0, 0, 0, 0, 0]
        self.msg = ""
        self.age = 0.0
        self.map_img: pygame.Surface | None = None
        self.map_key = None
        self._mrows = _MouseRows(self.app)
        self._mtab: list[tuple[pygame.Rect, int]] = []

    # ---- data
    def pack_rows(self) -> list[tuple[str, int]]:
        g = self.g
        order = {"weapon": 0, "armor": 1, "consumable": 2, "tool": 3, "ammo": 4, "material": 5, "trade": 6, "key": 7, "quest": 8}
        return sorted(((i, n) for i, n in g.p.inv.items() if n > 0), key=lambda t: (order.get(g.cat.item(t[0])["kind"], 9), g.cat.item(t[0])["name"]))

    def quest_rows(self) -> list[str]:
        g = self.g
        act = g.quests.active_ids()
        done = [q for q, s in g.quests.state.items() if s["done"]]
        return act + sorted(done)

    def beast_rows(self) -> list[str]:
        return sorted(self.g.kills)

    def update(self, dt: float) -> None:
        self.age += dt
        p = self.inp.player(0)
        if self.age > 0.15 and p.any_pressed(("BACK", "SELECT", "PAUSE")):
            self.app.scenes.pop()
            return
        if "L" in p.pressed:
            self.tab = (self.tab - 1) % len(self.TABS)
            self.msg = ""
        if "R" in p.pressed:
            self.tab = (self.tab + 1) % len(self.TABS)
            self.msg = ""
        # mouse
        if self.age > 0.15:
            if 3 in self.inp.mouse_pressed:
                self.app.scenes.pop()
                return
            for rt, t2 in self._mtab:
                if rt.collidepoint(*self.inp.mouse_pos) and 1 in self.inp.mouse_pressed and self.tab != t2:
                    self.tab = t2
                    self.msg = ""
                    self.app.audio.play("ui_move", 0.5)
        wheel = self.inp.wheel
        if wheel and self.age > 0.15:
            n_rows = {"Pack": len(self.pack_rows()), "Quests": len(self.quest_rows()), "Beasts": len(self.beast_rows())}.get(
                self.TABS[self.tab], 0)
            if n_rows:
                self.sel[self.tab] = clamp(self.sel[self.tab] - wheel, 0, n_rows - 1)
        if self.age > 0.15 and self._mrows.rects:
            if self.tab == 0:
                rpm = len(self.pack_rows())
                self._mrows.poll(lambda: min(self.sel[0], rpm - 1) if rpm else 0,
                                 lambda i: self._tab_sel(0, i, rpm), self._use_row, self._unequip_row)
            elif self.tab == 1:
                rq = len(self.quest_rows())
                self._mrows.poll(lambda: min(self.sel[1], rq - 1) if rq else 0,
                                 lambda i: self._tab_sel(1, i, rq), lambda i: None)
            elif self.tab == 4:
                rb = len(self.beast_rows())
                self._mrows.poll(lambda: min(self.sel[4], rb - 1) if rb else 0,
                                 lambda i: self._tab_sel(4, i, rb), lambda i: None)
        dx, dy = p.menu_dir()
        if self.tab == 0:
            rows = self.pack_rows()
            if dy and rows:
                self.sel[0] = (self.sel[0] + dy) % len(rows)
            if "CONFIRM" in p.pressed and rows:
                it = rows[min(self.sel[0], len(rows) - 1)][0]
                self.msg = self.g.use_item(it)
            if "X" in p.pressed and rows:
                d = self.g.cat.item(rows[min(self.sel[0], len(rows) - 1)][0])
                if d.get("slot") and self.g.p.equip.get(d["slot"]) == d["id"]:
                    self.g.unequip(d["slot"])
                    self.msg = f"Unequipped {d['name']}."
        elif self.tab == 1:
            rows = self.quest_rows()
            if dy and rows:
                self.sel[1] = (self.sel[1] + dy) % len(rows)
        elif self.tab == 4:
            rows = self.beast_rows()
            if dy and rows:
                self.sel[4] = (self.sel[4] + dy) % len(rows)
        self.g.toasts.clear() if False else None

    def _tab_sel(self, col: int, i: int, n: int) -> None:
        if n:
            self.sel[col] = min(i, n - 1)

    def _use_row(self, i: int) -> None:
        rows = self.pack_rows()
        if rows and i < len(rows):
            self.sel[0] = i
            self.msg = self.g.use_item(rows[i][0])

    def _unequip_row(self, i: int) -> None:
        rows = self.pack_rows()
        if rows and i < len(rows):
            d = self.g.cat.item(rows[i][0])
            if d.get("slot") and self.g.p.equip.get(d["slot"]) == d["id"]:
                self.g.unequip(d["slot"])
                self.msg = f"Unequipped {d['name']}."

    # ---- drawing
    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        g = self.g
        surf.fill((14, 14, 22))
        r = pygame.Rect(8, 8, W - 16, H - 16)
        draw_panel(surf, r, fill=INK, alpha=255)
        x = r.x + 12
        self._mtab = []
        self._mrows.reset()
        for i, name in enumerate(self.TABS):
            col = BRASS if i == self.tab else DIM
            tw = f.width(name)
            if i == self.tab:
                pygame.draw.rect(surf, INK_2, (x - 4, r.y + 6, tw + 8, 13))
                pygame.draw.rect(surf, BRASS, (x - 4, r.y + 18, tw + 8, 1))
            self._mtab.append((pygame.Rect(x - 4, r.y + 6, tw + 8, 13), i))
            f.draw(surf, name, (x, r.y + 9), col, None)
            x += tw + 18
        f.draw(surf, f"{g.p.gold}g   {g.time_text()}", (r.right - 12, r.y + 9), (255, 220, 100), None, anchor="topright")
        body = pygame.Rect(r.x + 10, r.y + 26, r.w - 20, r.h - 46)
        [self._pack, self._quests, self._map, self._skills, self._beasts][self.tab](surf, body)
        f.draw(surf, self.msg, (r.x + 12, r.bottom - 24), LENS, None)
        draw_prompts(surf, self.app, [("L", "Prev tab"), ("R", "Next tab")] + ([("CONFIRM", "Use / equip"), ("X", "Unequip")] if self.tab == 0 else []) + [("BACK", "Close")],
                     y=r.bottom - 13)

    def _pack(self, surf: pygame.Surface, body: pygame.Rect) -> None:
        f = self.app.font
        g = self.g
        rows = self.pack_rows()
        # equipment
        ex = body.x
        for lbl, slot in (("Weapon", "weapon"), ("Bow", "bow"), ("Body", "body")):
            it = g.p.equip.get(slot, "")
            nm = g.cat.item(it)["name"] if it else "-"
            f.draw(surf, f"{lbl}: {nm}", (ex, body.y), PARCHMENT if it else DIM, None)
            ex += 112
        f.draw(surf, f"HP {int(g.p.hp)}/{int(g.max_hp())}   Armour {g.armor():g}   Damage {g.weapon().get('dmg', 0):g}", (body.x, body.y + 11), DIM, None)
        vis = 13
        sel = min(self.sel[0], max(0, len(rows) - 1))
        top = max(0, min(sel - vis // 2, max(0, len(rows) - vis)))
        y0 = body.y + 26
        for i, (it, n) in enumerate(rows[top:top + vis]):
            idx = top + i
            d = g.cat.item(it)
            rr = pygame.Rect(body.x, y0 + i * 13, 240, 12)
            self._mrows.add(rr, idx)
            if idx == sel:
                pygame.draw.rect(surf, INK_2, rr)
                pygame.draw.rect(surf, BRASS, (rr.x, rr.y, 2, rr.h))
            surf.blit(art.icon(d["kind"], tuple(d.get("color", (200, 200, 200))), 10), (rr.x + 5, rr.y + 1))
            eq = g.p.equip.get(d.get("slot", "")) == it
            f.draw(surf, d["name"] + ("  [equipped]" if eq else ""), (rr.x + 18, rr.y + 2), GOOD if eq else PARCHMENT, None)
            f.draw(surf, f"x{n}", (rr.right - 4, rr.y + 2), DIM, None, anchor="topright")
        if not rows:
            f.draw(surf, "Your pack is empty.", (body.x + 4, y0 + 2), DIM, None)
        else:
            it = rows[sel][0]
            d = g.cat.item(it)
            dr = pygame.Rect(body.x + 256, y0, body.w - 262, 140)
            f.draw(surf, d["name"], (dr.x, dr.y), (255, 244, 205), None)
            f.draw(surf, d["kind"].title() + (f"   worth {d['value']}g" if d.get("value") else ""), (dr.x, dr.y + 11), DIM, None)
            y = _wrap(self.app, surf, d.get("desc", ""), pygame.Rect(dr.x, dr.y + 26, dr.w, 44), PARCHMENT, 4) + 4
            for lbl, key in (("Damage", "dmg"), ("Reach", "reach"), ("Armour", "armor"), ("Heals", "heal")):
                if d.get(key):
                    f.draw(surf, f"{lbl}: {d[key]:g}", (dr.x, y), PARCHMENT, None)
                    y += 11

    def _quests(self, surf: pygame.Surface, body: pygame.Rect) -> None:
        f = self.app.font
        g = self.g
        rows = self.quest_rows()
        sel = min(self.sel[1], max(0, len(rows) - 1))
        y0 = body.y
        for i, qid in enumerate(rows[:14]):
            q = g.cat.quest(qid)
            done = g.quests.is_done(qid)
            rr = pygame.Rect(body.x, y0 + i * 13, 190, 12)
            self._mrows.add(rr, i)
            if i == sel:
                pygame.draw.rect(surf, INK_2, rr)
                pygame.draw.rect(surf, BRASS, (rr.x, rr.y, 2, rr.h))
            col = DIM if done else (BRASS if q.get("track") == "main" else PARCHMENT)
            f.draw(surf, ("[x] " if done else "") + q["title"], (rr.x + 6, rr.y + 2), col, None)
        if not rows:
            f.draw(surf, "No quests yet. Talk to people.", (body.x + 4, y0 + 2), DIM, None)
            return
        qid = rows[sel]
        q = g.cat.quest(qid)
        dr = pygame.Rect(body.x + 204, y0, body.w - 210, body.h)
        f.draw(surf, q["title"], (dr.x, dr.y), (255, 244, 205), None)
        giver = g.cat.npc(q["giver"])
        f.draw(surf, f"Given by {giver['name'] if giver else '?'}", (dr.x, dr.y + 11), DIM, None)
        y = _wrap(self.app, surf, q["offer"], pygame.Rect(dr.x, dr.y + 26, dr.w, 70), PARCHMENT, 6) + 6
        if g.quests.is_done(qid):
            f.draw(surf, "Completed.", (dr.x, y), GOOD, None)
        else:
            f.draw(surf, "Now:", (dr.x, y), BRASS, None)
            _wrap(self.app, surf, g.quests.progress_text(g, qid), pygame.Rect(dr.x + 4, y + 11, dr.w - 4, 40), LENS, 4)

    def _map(self, surf: pygame.Surface, body: pygame.Rect) -> None:
        f = self.app.font
        g = self.g
        key = (int(g.discovered.sum()), len(g.known_sites), g.flags.get("bridge_built", False), g.flags.get("stones_revealed", False))
        if self.map_img is None or self.map_key != key:
            img = np.zeros((g.over.H, g.over.W, 3), dtype=np.uint8)
            for gid, (col, _) in art.GROUND_STYLE.items():
                img[g.over.ground == gid] = col
            ob = g.over.obj
            blocked = T.OBJ_BLOCKS[ob] & (ob > 0)
            tree = np.isin(ob, [T.O["oak"], T.O["pine"], T.O["willow"], T.O["ringtree"]])
            img[tree] = (img[tree] * 0.7).astype(np.uint8)
            img[g.over.bmask] = (200, 80, 70)
            img[~g.discovered] = (16, 16, 24)
            self.map_img = pygame.surfarray.make_surface(img.swapaxes(0, 1))
            self.map_key = key
        mr = pygame.Rect(body.x, body.y, 256, 224)
        surf.blit(self.map_img, mr.topleft, pygame.Rect(0, 0, 256, 224))
        # the map is 256x256: show a window that follows the player
        px, py = int(g.p.x), int(g.p.y)
        oy = int(clamp(py - 112, 0, 256 - 224))
        surf.blit(self.map_img, mr.topleft, pygame.Rect(0, oy, 256, 224))
        pygame.draw.rect(surf, BRASS, mr.inflate(2, 2), 1)
        if g.area == "overworld":
            pygame.draw.rect(surf, (255, 255, 120), (mr.x + px - 2, mr.y + py - oy - 2, 5, 5))
            pygame.draw.rect(surf, (20, 20, 20), (mr.x + px - 2, mr.y + py - oy - 2, 5, 5), 1)
        ly = body.y
        f.draw(surf, "Places", (body.x + 268, ly), BRASS, None)
        ly += 12
        for sid, st in g.over.sites.items():
            if st.hidden or sid not in g.known_sites:
                continue
            fx, fy = st.front
            if oy <= fy < oy + 224:
                col = (255, 255, 255) if st.kind == "settlement" else (255, 150, 110)
                pygame.draw.rect(surf, col, (mr.x + fx - 2, mr.y + fy - oy - 2, 5, 5))
                pygame.draw.rect(surf, (20, 20, 20), (mr.x + fx - 2, mr.y + fy - oy - 2, 5, 5), 1)
            if ly < body.bottom - 12:
                f.draw(surf, st.name, (body.x + 268, ly), PARCHMENT if st.kind == "settlement" else (255, 190, 160), None)
                ly += 11
        f.draw(surf, f"Explored: {int(g.discovered_fraction() * 100)}%", (body.x + 268, body.bottom - 14), DIM, None)

    def _skills(self, surf: pygame.Surface, body: pygame.Rect) -> None:
        f = self.app.font
        g = self.g
        y = body.y + 2
        for sk in SKILLS:
            xp = g.p.xp[sk]
            lv = skill_level(xp)
            lo = (lv ** 2) * 12.0
            hi = ((lv + 1) ** 2) * 12.0
            f.draw(surf, f"{SKILL_LABEL[sk]}  Lv {lv}", (body.x + 4, y), PARCHMENT, None)
            fr = 1.0 if lv >= 10 else (xp - lo) / (hi - lo)
            pygame.draw.rect(surf, (40, 36, 56), (body.x + 130, y + 2, 120, 5))
            pygame.draw.rect(surf, BRASS, (body.x + 130, y + 2, int(120 * clamp(fr)), 5))
            eff = {"blade": "+5% melee damage / level", "bow": "+5% bow damage / level", "forage": "+10% double yield, faster picking",
                   "delve": "faster mining and forging", "vigor": "+5 max HP / level"}[sk]
            f.draw(surf, eff, (body.x + 262, y), DIM, None)
            y += 18
        y += 8
        st = g.stats
        for lbl, v in (("Days survived", g.day), ("Foes defeated", st["kills"]), ("Lamps lit", st["lamps"]), ("Chests opened", st["chests"]),
                       ("Gold earned", st["gold_earned"]), ("Distance walked", f"{int(st['steps'])} paces"), ("Times fallen", g.death_count),
                       ("Fighting style", self._style())):
            f.draw(surf, f"{lbl}: {v}", (body.x + 4, y), PARCHMENT, None)
            y += 12

    def _style(self) -> str:
        g = self.g
        m = g.model
        mel, rng = m.weights.get("melee", 0.0), m.weights.get("ranged", 0.0)
        if mel + rng < 3:
            return "still learning"
        return "close and personal" if mel > rng * 1.6 else "from a distance" if rng > mel * 1.6 else "mixed"

    def _beasts(self, surf: pygame.Surface, body: pygame.Rect) -> None:
        f = self.app.font
        g = self.g
        rows = self.beast_rows()
        if not rows:
            f.draw(surf, "You have not felled anything worth recording.", (body.x + 4, body.y + 2), DIM, None)
            return
        sel = min(self.sel[4], len(rows) - 1)
        for i, k in enumerate(rows[:14]):
            e = g.cat.enemy(k)
            rr = pygame.Rect(body.x, body.y + i * 13, 190, 12)
            self._mrows.add(rr, i)
            if i == sel:
                pygame.draw.rect(surf, INK_2, rr)
                pygame.draw.rect(surf, BRASS, (rr.x, rr.y, 2, rr.h))
            f.draw(surf, f"{e['name']}  x{g.kills[k]}", (rr.x + 6, rr.y + 2), PARCHMENT, None)
        e = g.cat.enemy(rows[sel])
        dr = pygame.Rect(body.x + 204, body.y, body.w - 210, body.h)
        sp = art.creature(rows[sel], 0, 0, int(e.get("size", 1.0) * 10))
        surf.blit(pygame.transform.scale(sp, (sp.get_width() * 2, sp.get_height() * 2)), (dr.x, dr.y))
        f.draw(surf, e["name"], (dr.x + 70, dr.y + 4), (255, 244, 205), None)
        f.draw(surf, f"HP {e['hp']:g}  Damage {e.get('dmg', 0):g}  Style: {e['ai']}", (dr.x + 70, dr.y + 15), DIM, None)
        _wrap(self.app, surf, e.get("blurb", ""), pygame.Rect(dr.x, dr.y + 70, dr.w, 60), PARCHMENT, 5)
