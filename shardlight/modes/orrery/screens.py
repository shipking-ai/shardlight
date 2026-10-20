"""Orrery screens that happen away from the cockpit: station services, the decode puzzle and the codex."""
from __future__ import annotations

import math

import pygame

from ...core.scene import Scene
from ...core.ui import DANGER, DIM, GOOD, INK_2, LENS, PARCHMENT, draw_panel, draw_prompts
from . import art
from . import signals as sigmod
from .game import FUEL_PRICE, REPAIR_PRICE

W, H = 480, 270
TONE_COLORS = [(255, 214, 120), (201, 162, 74), (111, 224, 255), (255, 140, 120), (190, 150, 255), (140, 235, 160),
               (230, 200, 160), (255, 244, 205)]
STATION_TABS = ("Trade", "Services", "Shipyard", "Missions", "Diplomacy", "Log")
QTYS = (1, 5, 10, 99)


def _bg(surf: pygame.Surface, t: int) -> None:
    surf.fill(art.INDIGO)
    art.draw_stars(surf, (t * 0.15, 0), 3)


class StationScreen(Scene):
    def __init__(self, os_, body):
        super().__init__(os_.app)
        self.os = os_
        self.g = os_.game
        self.body = body
        self.tab = 0
        self.sel = [0] * len(STATION_TABS)
        self.qi = 0
        self.msg = ""
        self.msg_t = 0
        self.t = 0
        self.age = 0

    def on_enter(self, **kw) -> None:
        g = self.g
        g.refresh_missions()
        g.codex_add(f"stn:{self.body.id}", "station", self.body.name, f"A {self.body.sub} in {g.g.systems[g.sid].name}.")
        self.app.audio.set_intensity(0.15)

    # ------------------------------------------------------------------ helpers
    def say(self, text: str, good: bool = True) -> None:
        self.msg, self.msg_t = text, 200
        self.app.audio.play("ui_confirm" if good else "ui_error", 0.7)

    def goods(self) -> list[str]:
        return self.os.defs.good_ids()

    def rows(self) -> list:
        g, d = self.g, self.os.defs
        tab = STATION_TABS[self.tab]
        if tab == "Trade":
            return self.goods() if g.can_trade() else []
        if tab == "Services":
            return ["fuel", "repair", "undock"]
        if tab == "Shipyard":
            return [("hull", h) for h in d.hulls] + [("mod", m) for m in sorted(d.modules)]
        if tab == "Missions":
            return g.offered_missions() + [m for m in g.missions if m.get("taken") and not m.get("done")]
        if tab == "Diplomacy":
            ids = d.civ_ids()
            return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
        return sorted(g.codex.items(), key=lambda kv: (kv[1]["kind"], kv[1]["name"]))

    # ------------------------------------------------------------------ input
    def update(self, dt: float) -> None:
        self.t += 1
        self.age += 1
        self.msg_t = max(0, self.msg_t - 1)
        if self.age < 8:
            return
        p = self.inp.player(0)
        rows = self.rows()
        dx, dy = p.menu_dir()
        if "L" in p.pressed:
            self.tab = (self.tab - 1) % len(STATION_TABS)
            self.app.audio.play("ui_move", 0.5)
        if "R" in p.pressed:
            self.tab = (self.tab + 1) % len(STATION_TABS)
            self.app.audio.play("ui_move", 0.5)
        n = max(1, len(rows))
        if dy:
            self.sel[self.tab] = (self.sel[self.tab] + dy) % n
            self.app.audio.play("ui_move", 0.4)
        self.sel[self.tab] = min(self.sel[self.tab], n - 1)
        if dx and STATION_TABS[self.tab] == "Trade":
            self.qi = (self.qi + dx) % len(QTYS)
        if "BACK" in p.pressed:
            self.undock()
            return
        row = rows[self.sel[self.tab]] if rows else None
        if row is None:
            return
        tab = STATION_TABS[self.tab]
        if tab == "Trade":
            self._trade(row, p)
        elif tab == "Services":
            if "CONFIRM" in p.pressed:
                self._services(row)
        elif tab == "Shipyard":
            self._shipyard(row, p)
        elif tab == "Missions":
            if "CONFIRM" in p.pressed:
                self._missions(row)
        elif tab == "Diplomacy":
            self._diplomacy(row, p)

    def undock(self) -> None:
        self.os.save_game()
        self.os.back_to_flight()

    def _trade(self, good: str, p) -> None:
        g = self.g
        q = QTYS[self.qi]
        if "CONFIRM" in p.pressed:
            got, cost = g.buy(good, q if q < 99 else g.cargo_free())
            if got:
                self.say(f"Bought {got} {self.os.defs.goods[good]['name']} for {int(cost)}.")
            else:
                self.say("Cannot buy: no stock, no room or no credits.", False)
        elif "X" in p.pressed:
            have = g.cargo.get(good, 0)
            pay = g.sell(good, q if q < 99 else have)
            if pay:
                self.say(f"Sold for {int(pay)}.")
            else:
                self.say("Nothing to sell.", False)

    def _services(self, row: str) -> None:
        g = self.g
        if row == "fuel":
            n = g.refuel()
            self.say(f"Refuelled {n:.1f}." if n > 0.05 else "Tank is full or you cannot pay.", n > 0.05)
        elif row == "repair":
            n = g.repair()
            self.say(f"Repaired {n:.0f} hull." if n > 0.5 else "Hull is sound or you cannot pay.", n > 0.5)
        else:
            self.undock()

    def _shipyard(self, row, p) -> None:
        g = self.g
        kind, ident = row
        if kind == "hull":
            if "CONFIRM" in p.pressed:
                if g.buy_hull(ident):
                    self.say(f"You now fly the {self.os.defs.hulls[ident]['name']}. Modules were sold back.")
                else:
                    self.say("Unavailable, owned or too expensive.", False)
        else:
            if "CONFIRM" in p.pressed:
                ok, why = g.can_install(ident)
                if ok and g.module_available_at(g.sid, ident) and g.install(ident):
                    self.say(f"Installed {self.os.defs.modules[ident]['name']}.")
                else:
                    self.say(why if not ok else "Not sold here, or you cannot pay.", False)
            elif "X" in p.pressed:
                if g.remove(ident):
                    self.say("Removed (half refunded).")
                else:
                    self.say("Not installed.", False)

    def _missions(self, m: dict) -> None:
        g = self.g
        if not m.get("taken"):
            g.take_mission(m["id"])
            self.say("Mission accepted.")
        elif m["sid"] == g.sid:
            msg = g.deliver_mission(m["id"])
            self.say(msg, msg.startswith("Delivered"))
            if msg.startswith("Delivered"):
                self.os.save_game()
        else:
            self.say(f"Deliver to {g.g.systems[m['sid']].name}.", False)

    def _diplomacy(self, pair: tuple[str, str], p) -> None:
        sim = self.g.sim
        a, b = pair
        if "CONFIRM" in p.pressed:
            if sim.at_war(a, b):
                ok, why = sim.can_broker_peace(a, b)
                if ok and sim.broker_peace(a, b):
                    self.say("Peace brokered. Both sides remember who asked.")
                else:
                    self.say(why, False)
            else:
                ok, why = sim.can_ally(a, b)
                if ok and sim.broker_alliance(a, b):
                    self.say("They sign. The lanes between them open up.")
                else:
                    self.say(why, False)
        elif "X" in p.pressed:
            ok, why = sim.can_embargo(a, b)
            if ok and sim.push_embargo(a, b):
                self.say(f"{self.os.defs.civs[a]['short']} now refuses {self.os.defs.civs[b]['short']}'s ships.")
            elif sim.embargoes(a, b) and sim.lift_embargo(a, b):
                self.say("Embargo lifted.")
            else:
                self.say(why, False)
        elif "Y" in p.pressed:
            ok, why = sim.can_embargo(b, a)
            if ok and sim.push_embargo(b, a):
                self.say(f"{self.os.defs.civs[b]['short']} now refuses {self.os.defs.civs[a]['short']}'s ships.")
            elif sim.embargoes(b, a) and sim.lift_embargo(b, a):
                self.say("Embargo lifted.")
            else:
                self.say(why, False)

    # ------------------------------------------------------------------ draw
    def draw(self, surf: pygame.Surface) -> None:
        g, f, d = self.g, self.app.font, self.os.defs
        _bg(surf, self.t)
        m = g.market()
        owner = d.civs[m.owner]["name"] if m is not None and m.owner else "Free port"
        f.draw(surf, f"{self.body.name}", (8, 6), art.STAR_WHITE, (8, 6, 20), scale=2)
        f.draw(surf, f"{owner}   {g.g.systems[g.sid].name}", (8, 25), art.CYAN, (8, 6, 20))
        f.draw(surf, f"Credits {int(g.credits)}   Fuel {g.fuel:.1f}/{g.ship_stats()['fuel']:.0f}   Hull {int(g.hull_hp)}/{int(g.ship_stats()['hull'])}   "
                     f"Cargo {g.cargo_used()}/{int(g.ship_stats()['cargo'])}", (W - 6, 27), art.STAR_WHITE, (8, 6, 20), anchor="topright")
        x = 8
        for i, name in enumerate(STATION_TABS):
            w = f.width(name) + 14
            r = pygame.Rect(x, 38, w, 14)
            on = i == self.tab
            pygame.draw.rect(surf, art.BRASS if on else INK_2, r)
            f.draw(surf, name, (r.centerx, r.y + 3), (16, 12, 30) if on else DIM, None, anchor="midtop")
            x += w + 3
        body = pygame.Rect(8, 54, W - 16, H - 54 - 34)
        draw_panel(surf, body, border=art.BRASS, fill=art.INDIGO, alpha=240)
        tab = STATION_TABS[self.tab]
        rows = self.rows()
        sel = self.sel[self.tab]
        {"Trade": self._draw_trade, "Services": self._draw_services, "Shipyard": self._draw_yard,
         "Missions": self._draw_missions, "Diplomacy": self._draw_diplo, "Log": self._draw_log}[tab](surf, body, rows, sel)
        if self.msg_t > 0:
            r = pygame.Rect(40, H - 56, W - 80, 16)
            draw_panel(surf, r, border=art.BRASS, fill=(30, 24, 56), alpha=250)
            f.draw(surf, self.msg, (r.centerx, r.y + 4), (255, 244, 205), None, anchor="midtop")
        keys = [("L", "<"), ("R", ">"), ("CONFIRM", "Do"), ("BACK", "Undock")]
        if tab == "Trade":
            keys = [("L", "<"), ("R", ">"), ("CONFIRM", "Buy"), ("X", "Sell"), ("LEFT", f"Qty {QTYS[self.qi] if QTYS[self.qi] < 99 else 'max'}"), ("BACK", "Undock")]
        elif tab == "Shipyard":
            keys = [("L", "<"), ("R", ">"), ("CONFIRM", "Buy / fit"), ("X", "Remove"), ("BACK", "Undock")]
        elif tab == "Diplomacy":
            keys = [("L", "<"), ("R", ">"), ("CONFIRM", "Peace/ally"), ("X", "Embargo A>B"), ("Y", "B>A"), ("BACK", "Undock")]
        draw_prompts(surf, self.app, keys)

    def _scroll(self, rows: list, sel: int, vis: int) -> tuple[int, int]:
        top = max(0, min(sel - vis // 2, len(rows) - vis))
        return top, min(len(rows), top + vis)

    def _draw_trade(self, surf, body, rows, sel) -> None:
        f, g, d = self.app.font, self.g, self.os.defs
        if not rows:
            f.draw(surf, "This port will not trade with you." if g.market() else "No market here.", (body.x + 10, body.y + 10), DANGER, None)
            return
        hdr = body.y + 6
        for label, x in (("GOOD", 14), ("STOCK", 150), ("BUY", 200), ("SELL", 250), ("HELD", 300), ("TREND", 340)):
            f.draw(surf, label, (body.x + x, hdr), DIM, None)
        m = g.market()
        top, end = self._scroll(rows, sel, 12)
        y = body.y + 20
        for i in range(top, end):
            gid = rows[i]
            gd = d.goods[gid]
            gi = g.sim.gi[gid]
            r = pygame.Rect(body.x + 4, y, body.w - 8, 14)
            if i == sel:
                pygame.draw.rect(surf, INK_2, r)
                pygame.draw.rect(surf, art.BRASS, (r.x, r.y, 2, r.h))
            surf.fill(tuple(gd.get("color", (200, 200, 200))), (body.x + 8, y + 4, 4, 4))
            f.draw(surf, gd["name"], (body.x + 16, y + 3), PARCHMENT if i == sel else DIM, None)
            stock = int(m.stock[gi])
            f.draw(surf, str(stock), (body.x + 150, y + 3), PARCHMENT if stock else DANGER, None)
            buy = g.sim.unit_price(g.sid, gid, "buy")
            sell = g.sim.unit_price(g.sid, gid, "sell")
            f.draw(surf, str(int(buy)), (body.x + 200, y + 3), PARCHMENT, None)
            f.draw(surf, str(int(sell)), (body.x + 250, y + 3), GOOD, None)
            held = g.cargo.get(gid, 0)
            f.draw(surf, str(held) if held else "-", (body.x + 300, y + 3), LENS if held else DIM, None)
            ratio = m.price[gi] / g.sim.base[gi]
            f.draw(surf, "cheap" if ratio < 0.85 else "dear" if ratio > 1.2 else "fair", (body.x + 340, y + 3),
                   GOOD if ratio < 0.85 else DANGER if ratio > 1.2 else DIM, None)
            y += 14
        if rows:
            gd = d.goods[rows[sel]]
            f.draw_wrapped(surf, gd.get("desc", ""), pygame.Rect(body.x + 10, body.bottom - 22, body.w - 20, 18), DIM, None, max_lines=2)

    def _draw_services(self, surf, body, rows, sel) -> None:
        f, g = self.app.font, self.g
        st = g.ship_stats()
        m = g.market()
        mod = g.sim.rep_price_mod(m.owner if m else None, True)
        infos = [("Refuel", f"{FUEL_PRICE * mod:.0f} per unit   ({st['fuel'] - g.fuel:.1f} needed)"),
                 ("Repair hull", f"{REPAIR_PRICE * mod:.1f} per point   ({st['hull'] - g.hull_hp:.0f} needed)"),
                 ("Undock", "Leave the station and return to flight")]
        for i, (a, b) in enumerate(infos):
            y = body.y + 12 + i * 18
            r = pygame.Rect(body.x + 4, y - 2, body.w - 8, 16)
            if i == sel:
                pygame.draw.rect(surf, INK_2, r)
                pygame.draw.rect(surf, art.BRASS, (r.x, r.y, 2, r.h))
            f.draw(surf, a, (body.x + 14, y + 2), PARCHMENT if i == sel else DIM, None)
            f.draw(surf, b, (body.x + 120, y + 2), DIM, None)
        art.panel(surf, pygame.Rect(body.x + 10, body.y + 80, body.w - 20, 70), "Ship", f)
        lines = [f"Hull {g.hull}   Slots {len(g.mods)}/{int(st['slots'])}   Power {g.power_used():.0f}/{st['power']:.0f}",
                 f"Shield {st['shield']:.0f}   Thrust {st['thrust']:.0f}   Speed {st['max_speed']:.0f}   Range {st['range']:.0f}",
                 f"Cargo {st['cargo']:.0f}   Fuel {st['fuel']:.0f}   Missiles {int(st['missiles'])}   Decoys {int(st['decoys'])}",
                 f"Modules: {', '.join(d_ for d_ in (self.os.defs.modules[x]['name'] for x in g.mods)) or 'none'}"]
        for i, ln in enumerate(lines):
            f.draw_wrapped(surf, ln, pygame.Rect(body.x + 18, body.y + 94 + i * 12, body.w - 36, 12), PARCHMENT, None, max_lines=1)

    def _draw_yard(self, surf, body, rows, sel) -> None:
        f, g, d = self.app.font, self.g, self.os.defs
        top, end = self._scroll(rows, sel, 10)
        y = body.y + 6
        for i in range(top, end):
            kind, ident = rows[i]
            r = pygame.Rect(body.x + 4, y, body.w - 8, 14)
            if i == sel:
                pygame.draw.rect(surf, INK_2, r)
                pygame.draw.rect(surf, art.BRASS, (r.x, r.y, 2, r.h))
            if kind == "hull":
                h = d.hulls[ident]
                av = g.hull_available(ident)
                col = LENS if ident == g.hull else (PARCHMENT if av else (90, 86, 100))
                f.draw(surf, f"HULL  {h['name']}", (body.x + 12, y + 3), col, None)
                f.draw(surf, "owned" if ident == g.hull else (f"{int(h.get('price', 0))}" if av else "locked"), (body.x + 200, y + 3),
                       col, None)
            else:
                mdef = d.modules[ident]
                inst = ident in g.mods
                avail = g.module_available_at(g.sid, ident)
                col = GOOD if inst else (PARCHMENT if avail else (90, 86, 100))
                f.draw(surf, f"MOD   {mdef['name']}", (body.x + 12, y + 3), col, None)
                tag = "fitted" if inst else (f"{int(mdef.get('price', 0))}" if avail else "not sold here")
                f.draw(surf, tag, (body.x + 200, y + 3), col, None)
                f.draw(surf, f"pw {mdef.get('power', 0):.0f}", (body.x + 330, y + 3), DIM, None)
            y += 14
        kind, ident = rows[sel]
        desc = d.hulls[ident].get("desc", "") if kind == "hull" else d.modules[ident].get("desc", "")
        f.draw_wrapped(surf, desc, pygame.Rect(body.x + 10, body.bottom - 28, body.w - 20, 22), DIM, None, max_lines=2)

    def _draw_missions(self, surf, body, rows, sel) -> None:
        f, g = self.app.font, self.g
        if not rows:
            f.draw(surf, "No supply requests right now. Colonies short of food, water, fuel or alloy post them here.",
                   (body.x + 10, body.y + 10), DIM, None)
            return
        y = body.y + 8
        for i, m in enumerate(rows):
            r = pygame.Rect(body.x + 4, y, body.w - 8, 24)
            if i == sel:
                pygame.draw.rect(surf, INK_2, r)
                pygame.draw.rect(surf, art.BRASS, (r.x, r.y, 2, r.h))
            dest = g.g.systems[m["sid"]].name
            state = "ACTIVE" if m.get("taken") else "OFFER"
            col = LENS if m.get("taken") else PARCHMENT
            f.draw(surf, f"{state}  {m['qty']} {self.os.defs.goods[m['good']]['name']} to {dest}", (body.x + 12, y + 3), col, None)
            f.draw(surf, f"{m['reward']} cr  by day {m['deadline']}", (body.x + 12, y + 13), GOOD, None)
            have = g.cargo.get(m["good"], 0)
            if m.get("taken") and m["sid"] == g.sid:
                f.draw(surf, "Deliver" + ("" if have >= m["qty"] else f" (need {m['qty'] - have} more)"), (body.right - 12, y + 8), GOOD if have >= m["qty"] else DANGER,
                       None, anchor="topright")
            y += 26
            if y > body.bottom - 30:
                break

    def _draw_diplo(self, surf, body, rows, sel) -> None:
        f, g, d = self.app.font, self.g, self.os.defs
        sim = g.sim
        x = body.x + 10
        for cid in d.civ_ids():
            c = d.civs[cid]
            rep = sim.player_rep.get(cid, 0.0)
            f.draw(surf, f"{c['short']} {rep:+.0f}", (x, body.y + 6), tuple(c["color"]), None)
            x += 74
        y = body.y + 22
        top, end = self._scroll(rows, sel, 9)
        for i in range(top, end):
            a, b = rows[i]
            r = pygame.Rect(body.x + 4, y, body.w - 8, 14)
            if i == sel:
                pygame.draw.rect(surf, INK_2, r)
                pygame.draw.rect(surf, art.BRASS, (r.x, r.y, 2, r.h))
            st = sim.state_between(a, b)
            col = DANGER if st in ("war", "hostile") else GOOD if st in ("alliance", "friendly") else PARCHMENT
            f.draw(surf, f"{d.civs[a]['short']} / {d.civs[b]['short']}", (body.x + 12, y + 3), PARCHMENT if i == sel else DIM, None)
            f.draw(surf, st, (body.x + 140, y + 3), col, None)
            tags = ""
            if sim.embargoes(a, b):
                tags += f" {d.civs[a]['short']}>{d.civs[b]['short']}"
            if sim.embargoes(b, a):
                tags += f" {d.civs[b]['short']}>{d.civs[a]['short']}"
            if tags:
                f.draw(surf, "embargo:" + tags, (body.x + 220, y + 3), (255, 190, 100), None)
            y += 14
        recent = [e for e in sim.events[-4:]] if hasattr(sim, "events") else []
        for j, e in enumerate(recent):
            f.draw(surf, str(e.get("text", ""))[:70] if isinstance(e, dict) else str(e)[:70], (body.x + 10, body.bottom - 52 + j * 11), DIM, None)

    def _draw_log(self, surf, body, rows, sel) -> None:
        f = self.app.font
        if not rows:
            f.draw(surf, "Your codex is empty.", (body.x + 10, body.y + 10), DIM, None)
            return
        top, end = self._scroll(rows, sel, 10)
        y = body.y + 8
        for i in range(top, end):
            cid, e = rows[i]
            if i == sel:
                pygame.draw.rect(surf, INK_2, (body.x + 4, y, 170, 14))
                pygame.draw.rect(surf, art.BRASS, (body.x + 4, y, 2, 14))
            f.draw(surf, e["name"][:26], (body.x + 12, y + 3), PARCHMENT if i == sel else DIM, None)
            y += 14
        cid, e = rows[sel]
        f.draw(surf, e["kind"].upper() + f"  day {e['day']}", (body.x + 190, body.y + 8), art.CYAN, None)
        f.draw_wrapped(surf, e["text"], pygame.Rect(body.x + 190, body.y + 22, body.w - 200, 120), PARCHMENT, None)


# ====================================================================================== decode
class DecodeScreen(Scene):
    def __init__(self, os_, sig: str):
        super().__init__(os_.app)
        self.os = os_
        self.g = os_.game
        self.sig = sig
        self.d = os_.defs.signals[sig]
        self.pz = self.g.puzzle(sig)
        self.guess = [0] * self.pz.length
        if self.pz.kind == "lock":
            self.guess = list(range(self.pz.length))
        self.cur = 0
        self.t = 0
        self.result: list[str] | None = None
        self.msg = ""
        self.hist: list[tuple[list[int], tuple[int, int]]] = []
        for a in self.g.sig_state(sig)["attempts"]:
            if self.pz.kind == "lock" and len(a) == self.pz.length:
                self.hist.append((list(a), sigmod.lock_feedback(self.pz.secret, tuple(a))))
        self.hist = self.hist[-8:]

    def on_enter(self, **kw) -> None:
        self.app.audio.set_intensity(0.1)
        self.app.audio.play("orrery_scan", 0.6)

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t < 8:
            return
        if self.result is not None:
            if "CONFIRM" in p.pressed or "BACK" in p.pressed:
                self.os.save_game()
                self.os.back_to_flight()
            return
        dx, dy = p.menu_dir()
        n = self.pz.length
        if dx:
            self.cur = (self.cur + dx) % n
            self.app.audio.play("ui_move", 0.4)
        if dy:
            self.guess[self.cur] = (self.guess[self.cur] - dy) % self.pz.symbols
            self.app.audio.play("ui_move", 0.4)
        if "BACK" in p.pressed:
            self.os.save_game()
            self.os.back_to_flight()
            return
        if "CONFIRM" in p.pressed:
            if self.pz.kind == "lock" and len(set(self.guess)) < len(self.guess):
                self.msg = "A lock probe uses each tone at most once."
                self.app.audio.play("ui_error", 0.6)
                return
            res = self.g.attempt_decode(self.sig, tuple(self.guess))
            if res["ok"]:
                self.result = res["reward"]
                self.app.audio.play("unlock", 0.9)
                self.app.toast(f"Decoded: {self.d['name']}", LENS)
            else:
                self.app.audio.play("ui_error", 0.7)
                if res["feedback"] is not None:
                    self.hist.append((list(self.guess), res["feedback"]))
                    self.hist = self.hist[-8:]
                    self.msg = f"{res['feedback'][0]} in place, {res['feedback'][1]} elsewhere."
                else:
                    self.msg = "The pattern does not satisfy every clue."

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        _bg(surf, self.t)
        f.draw(surf, f"DECODE  {self.d['name']}", (10, 8), art.STAR_WHITE, (8, 6, 20), scale=2)
        f.draw_wrapped(surf, "Tune each tone until every clue holds." if self.pz.kind == "sequence"
                       else "Probe the lock: each probe tells you how many tones sit right and how many are right but misplaced.",
                       pygame.Rect(10, 28, W - 20, 22), art.CYAN, (8, 6, 20), max_lines=2)
        n = self.pz.length
        bx = 240 - (n * 36) // 2
        for i in range(n):
            r = pygame.Rect(bx + i * 36, 70, 30, 44)
            on = i == self.cur and self.result is None
            draw_panel(surf, r, border=art.BRASS if on else art.BRASS_D, fill=(24, 20, 50))
            tone = self.guess[i]
            self._glyph(surf, r.centerx, r.y + 18, tone, 9)
            f.draw(surf, sigmod.TONES[tone], (r.centerx, r.bottom - 12), TONE_COLORS[tone], None, anchor="midtop")
            if on:
                f.draw(surf, "^", (r.centerx, r.y - 8), art.BRASS, None, anchor="midtop")
                f.draw(surf, "v", (r.centerx, r.bottom + 2), art.BRASS, None, anchor="midtop")
        if self.pz.kind == "sequence":
            f.draw(surf, "CLUES", (20, 130), DIM, None)
            for j, c in enumerate(self.pz.clues[:8]):
                f.draw(surf, sigmod.clue_text(c), (20, 142 + j * 11), PARCHMENT, None)
        else:
            f.draw(surf, "PROBES", (20, 130), DIM, None)
            for j, (gs, fb) in enumerate(self.hist):
                y = 142 + j * 11
                f.draw(surf, " ".join(sigmod.TONES[t][:3] for t in gs), (20, y), PARCHMENT, None)
                f.draw(surf, f"{fb[0]} in place  {fb[1]} elsewhere", (200, y), GOOD if fb[0] else DIM, None)
        if self.msg and self.result is None:
            f.draw(surf, self.msg, (240, 118), (255, 190, 100), None, anchor="midtop")
        if self.result is not None:
            r = pygame.Rect(40, 120, W - 80, 108)
            draw_panel(surf, r, border=art.BRASS, fill=(24, 20, 50), alpha=252)
            f.draw(surf, "SIGNAL RESOLVED", (r.centerx, r.y + 6), art.BRASS, None, anchor="midtop")
            yy = r.y + 20
            for ln in self.result:
                for sub in f.wrap(ln, r.w - 20):
                    f.draw(surf, sub, (r.x + 10, yy), PARCHMENT, None)
                    yy += 10
        draw_prompts(surf, self.app, [("CONFIRM", "Submit" if self.result is None else "Continue"), ("BACK", "Leave")])

    def _glyph(self, surf: pygame.Surface, x: int, y: int, tone: int, r: int) -> None:
        col = TONE_COLORS[tone]
        k = tone % 8
        if k == 0:
            pygame.draw.circle(surf, col, (x, y), r, 2)
        elif k == 1:
            art.draw_gear(surf, (x, y), r, 8, self.t * 0.03, col, False)
        elif k == 2:
            pygame.draw.ellipse(surf, col, (x - r, y - r // 2, r * 2, r), 2)
            pygame.draw.circle(surf, col, (x, y), 2)
        elif k == 3:
            pygame.draw.line(surf, col, (x, y - r), (x, y + r), 2)
            pygame.draw.circle(surf, col, (x, y - r), 2)
        elif k == 4:
            pygame.draw.polygon(surf, col, [(x, y - r), (x - r // 2, y + r), (x + r // 2, y + r)], 2)
        elif k == 5:
            pygame.draw.ellipse(surf, col, (x - r, y - r // 2, r * 2, r), 1)
            pygame.draw.circle(surf, col, (x, y), r // 3)
        elif k == 6:
            pygame.draw.rect(surf, col, (x - r // 2, y - r // 2, r, r), 2)
            pygame.draw.line(surf, col, (x - r, y), (x + r, y), 1)
        else:
            pygame.draw.polygon(surf, col, [(x - r, y + r // 2), (x + r, y + r // 2), (x + r // 2, y - r // 2), (x - r // 2, y - r // 2)], 2)


# ====================================================================================== codex
class CodexScreen(Scene):
    """Read-only list of everything the voyage has discovered (pushed over the current screen)."""

    def __init__(self, os_):
        super().__init__(os_.app)
        self.g = os_.game
        self.rows = sorted(self.g.codex.items(), key=lambda kv: (kv[1]["kind"], kv[1]["name"]))
        self.sel = 0
        self.t = 0

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        _, dy = p.menu_dir()
        if dy and self.rows:
            self.sel = (self.sel + dy) % len(self.rows)
        if "BACK" in p.pressed and self.t > 6:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        _bg(surf, self.t)
        f.draw(surf, "CODEX", (10, 8), art.STAR_WHITE, (8, 6, 20), scale=2)
        f.draw(surf, f"{len(self.rows)} entries   {self.g.decoded_count()} signals decoded", (10, 28), art.CYAN, (8, 6, 20))
        body = pygame.Rect(8, 42, W - 16, H - 42 - 22)
        draw_panel(surf, body, border=art.BRASS, fill=art.INDIGO, alpha=240)
        if not self.rows:
            f.draw(surf, "Nothing yet. Visit systems, scan anomalies and listen for signals.", (body.x + 10, body.y + 10), DIM, None)
        top = max(0, min(self.sel - 8, len(self.rows) - 17))
        y = body.y + 6
        for i in range(top, min(len(self.rows), top + 17)):
            cid, e = self.rows[i]
            if i == self.sel:
                pygame.draw.rect(surf, INK_2, (body.x + 4, y, 170, 13))
                pygame.draw.rect(surf, art.BRASS, (body.x + 4, y, 2, 13))
            f.draw(surf, e["name"][:26], (body.x + 12, y + 2), PARCHMENT if i == self.sel else DIM, None)
            y += 13
        if self.rows:
            cid, e = self.rows[self.sel]
            f.draw(surf, e["kind"].upper() + f"   day {e['day']}", (body.x + 190, body.y + 8), art.CYAN, None)
            f.draw_wrapped(surf, e["text"], pygame.Rect(body.x + 190, body.y + 22, body.w - 200, 150), PARCHMENT, None)
        draw_prompts(surf, self.app, [("BACK", "Close")])
