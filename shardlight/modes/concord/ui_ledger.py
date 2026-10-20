"""Concord ledger screens: end turn, research, diplomacy, rival overview, chronicle, events, turn report, ending."""
from __future__ import annotations

import pygame

from ...core.fx import clamp
from ...core.scene import Scene
from ...core.ui import BRASS, DANGER, DIM, GOOD, INK_2, LENS, PARCHMENT, Menu, MenuItem, MenuScene, draw_panel, draw_prompts
from . import art
from .diplomacy import TREATY_LABEL
from .rules import TERRAIN_NAMES

W, H = 480, 270
PANEL = (40, 34, 56)


def _bg(app, t: int = 0) -> pygame.Surface:
    return art.parchment((W, H), 9)


def house_col(camp, hid: str):
    return tuple(camp.rules.houses[hid]["color"])


# ====================================================================================== ledger menu
class LedgerMenu(MenuScene):
    def __init__(self, cs, ms):
        self.cs, self.ms = cs, ms
        super().__init__(cs.app, "LEDGER", self._items, 230)

    def _items(self) -> list[MenuItem]:
        cs, c = self.cs, self.cs.camp
        idle = [a for a in c.armies_of(c.player) if a.units and not a.path]
        h = c.houses[c.player]
        items = [MenuItem("End turn", self._end, hint=f"{c.date_text()}. {len(idle)} army(ies) without orders."),
                 MenuItem("Research", lambda: self.app.scenes.push(ResearchScreen(cs)),
                          hint=("Researching " + c.rules.techs[h.research]["name"]) if h.research else "Nothing is being researched"),
                 MenuItem("Diplomacy", lambda: self.app.scenes.push(DiplomacyScreen(cs, self.ms))),
                 MenuItem("Rival houses", lambda: self.app.scenes.push(HousesScreen(cs))),
                 MenuItem("Chronicle", lambda: self.app.scenes.push(ChronicleScreen(cs))),
                 MenuItem("Back", self.app.scenes.pop)]
        return items

    def _end(self) -> None:
        self.app.scenes.pop()
        self.ms.end_turn()


# ====================================================================================== research
class ResearchScreen(Scene):
    def __init__(self, cs):
        super().__init__(cs.app)
        self.cs = cs
        self.c = cs.camp
        self.sel = 0
        self.t = 0
        self.bg = _bg(cs.app)
        self.msg = ""

    def options(self) -> list[str]:
        c = self.c
        opts = c.research_options(c.player)
        order = {"martial": 0, "civic": 1, "lore": 2}
        return sorted(opts, key=lambda t: (order[c.rules.techs[t]["branch"]], c.rules.techs[t]["tier"], t))

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t < 6:
            return
        p = self.inp.player(0)
        opts = self.options()
        _, dy = p.menu_dir()
        if dy and opts:
            self.sel = (self.sel + dy) % len(opts)
            self.app.audio.play("ui_move", 0.4)
        if "CONFIRM" in p.pressed and opts:
            tid = opts[self.sel]
            if self.c.set_research(self.c.player, tid):
                self.app.audio.play("concord_quill", 0.6)
                self.msg = f"Researching {self.c.rules.techs[tid]['name']}."
        if "BACK" in p.pressed:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        c, f = self.c, self.app.font
        surf.blit(self.bg, (0, 0))
        f.draw(surf, "RESEARCH", (10, 8), art.WAX, None, scale=2)
        h = c.houses[c.player]
        rate = c.research_rate(c.player) + (2 if h.stock.get("ink", 0) >= 1 else 0)
        f.draw(surf, f"{rate:.1f} points per turn (an ink adds 2)   Known: {len(h.techs)}", (10, 28), art.INK, None)
        opts = self.options()
        body = pygame.Rect(8, 42, 220, 190)
        draw_panel(surf, body, fill=PANEL, alpha=245)
        y = body.y + 6
        top = max(0, min(self.sel - 8, len(opts) - 15))
        for i in range(top, min(len(opts), top + 15)):
            t = c.rules.techs[opts[i]]
            cur = h.research == opts[i]
            if i == self.sel:
                pygame.draw.rect(surf, INK_2, (body.x + 3, y - 1, body.w - 6, 12))
                pygame.draw.rect(surf, BRASS, (body.x + 3, y - 1, 2, 12))
            col = {"martial": (230, 130, 120), "civic": (140, 210, 150), "lore": (150, 170, 240)}[t["branch"]]
            f.draw(surf, t["name"], (body.x + 10, y + 1), PARCHMENT if i == self.sel else DIM, None)
            f.draw(surf, f"{int(c.tech_cost(opts[i]))}", (body.right - 8, y + 1), LENS if cur else col, None, anchor="topright")
            y += 12
        if not opts:
            f.draw(surf, "Everything available is known.", (body.x + 10, body.y + 8), DIM, None)
        det = pygame.Rect(236, 42, 236, 190)
        draw_panel(surf, det, fill=PANEL, alpha=245)
        if opts:
            tid = opts[self.sel]
            t = c.rules.techs[tid]
            f.draw(surf, t["name"], (det.x + 8, det.y + 8), PARCHMENT, None, scale=1)
            f.draw(surf, f"{t['branch'].title()}  tier {t['tier']}  cost {int(c.tech_cost(tid))}", (det.x + 8, det.y + 20), DIM, None)
            f.draw_wrapped(surf, t["desc"], pygame.Rect(det.x + 8, det.y + 36, det.w - 16, 80), PARCHMENT, None)
            if h.research == tid:
                f.draw(surf, f"In progress: {int(h.progress)}/{int(c.tech_cost(tid))}", (det.x + 8, det.y + 120), LENS, None)
            elif h.research:
                f.draw(surf, f"Switching wastes half of the current progress.", (det.x + 8, det.y + 120), (255, 190, 100), None)
            for i, e in enumerate(t["effects"][:5]):
                f.draw(surf, "- " + _effect_text(c, e), (det.x + 8, det.y + 134 + i * 10), (200, 190, 170), None)
        if self.msg:
            f.draw(surf, self.msg, (240, 236), art.INK, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Research"), ("BACK", "Close")], y=H - 14)


def _effect_text(c, e: dict) -> str:
    k = e.get("kind")
    if k == "mod":
        return f"{e['key'].replace('_', ' ').replace('.', ' ')} {e['value']:+g}"
    if k == "unit_mod":
        return f"{e['role']} {e['stat']} {e['value']:+g}"
    if k == "upgrade":
        return f"trait upgrade: {e.get('name', e['trait'])}"
    return str(e)


# ====================================================================================== diplomacy
class DiplomacyScreen(Scene):
    def __init__(self, cs, ms=None):
        super().__init__(cs.app)
        self.cs, self.c, self.ms = cs, cs.camp, ms
        self.sel = 0
        self.t = 0
        self.bg = _bg(cs.app)
        self.msg = ""
        self.msg_t = 0

    def houses(self) -> list[str]:
        return [h for h in self.c.rules.house_ids() if h != self.c.player and self.c.houses[h].alive]

    def update(self, dt: float) -> None:
        self.t += 1
        self.msg_t = max(0, self.msg_t - 1)
        if self.t < 6:
            return
        p = self.inp.player(0)
        hs = self.houses()
        _, dy = p.menu_dir()
        if dy and hs:
            self.sel = (self.sel + dy) % len(hs)
            self.app.audio.play("ui_move", 0.4)
        if "CONFIRM" in p.pressed and hs:
            self.app.scenes.push(HouseActions(self.cs, self, hs[self.sel]))
        if "BACK" in p.pressed:
            self.app.scenes.pop()

    def say(self, text: str, good: bool = True) -> None:
        self.msg, self.msg_t = text, 260
        self.app.audio.play("concord_seal" if good else "ui_error", 0.6)

    def draw(self, surf: pygame.Surface) -> None:
        c, f = self.c, self.app.font
        me = c.player
        surf.blit(self.bg, (0, 0))
        f.draw(surf, "DIPLOMACY", (10, 8), art.WAX, None, scale=2)
        mine = c.houses[me]
        f.draw(surf, f"Your oath record: {mine.oath:.0f} (broken treaties are remembered by everyone)", (10, 28), art.INK, None)
        hs = self.houses()
        y = 44
        for i, hid in enumerate(hs):
            r = pygame.Rect(8, y, 464, 52)
            draw_panel(surf, r, fill=PANEL if i != self.sel else (58, 48, 78), alpha=245, border=BRASS if i == self.sel else (110, 96, 120))
            col = house_col(c, hid)
            surf.blit(art.crest(col, 18), (r.x + 8, r.y + 8))
            hd = c.rules.houses[hid]
            f.draw(surf, hd["name"], (r.x + 32, r.y + 6), PARCHMENT, None)
            f.draw(surf, hd["epithet"], (r.x + 32, r.y + 16), col, None)
            st = c.dp.state_text(me, hid)
            f.draw(surf, st, (r.x + 32, r.y + 28), DANGER if st == "War" else GOOD if st in ("Alliance", "Non-aggression pact", "Trade pact") else DIM, None)
            op = c.dp.opinion_of(hid, me)
            bx = r.x + 200
            f.draw(surf, "Opinion of you", (bx, r.y + 6), DIM, None)
            pygame.draw.rect(surf, (20, 16, 30), (bx, r.y + 18, 104, 7))
            pygame.draw.rect(surf, (90, 80, 100), (bx + 52, r.y + 16, 1, 11))
            k = (op + 100) / 200
            pygame.draw.rect(surf, GOOD if op >= 0 else DANGER, (bx + 52, r.y + 19, int((k - 0.5) * 104), 5))
            f.draw(surf, f"{op:+.0f}", (bx + 110, r.y + 17), PARCHMENT, None)
            f.draw(surf, f"Oath {c.houses[hid].oath:.0f}", (bx, r.y + 30), DIM, None)
            f.draw(surf, f"Provinces {len(c.provinces_of(hid))}  Power {c.house_power(hid):.0f} (you {c.house_power(me):.0f})", (bx, r.y + 40), DIM, None)
            allies = [c.short(o) for o in c.dp.allies_of(hid) if o != me]
            wars = [c.short(o) for o in c.dp.enemies_of(hid)]
            tx = r.x + 330
            f.draw(surf, "At war: " + (", ".join(wars) or "none"), (tx + 6, r.y + 6), DANGER if wars else DIM, None)
            f.draw(surf, "Allied: " + (", ".join(allies) or "none"), (tx + 6, r.y + 16), GOOD if allies else DIM, None)
            f.draw(surf, hd["archetype"], (tx + 6, r.y + 28), DIM, None)
            y += 56
        if self.msg_t > 0:
            f.draw_wrapped(surf, self.msg, pygame.Rect(14, 220, 452, 24), art.INK, None, max_lines=2)
        conc = c.concord_turns
        f.draw(surf, f"Concord victory: ally every living house and hold it 3 turns ({conc}/3)", (10, 244), art.WAX, None)
        draw_prompts(surf, self.app, [("CONFIRM", "Envoy actions"), ("BACK", "Close")], y=H - 12)


class HouseActions(MenuScene):
    def __init__(self, cs, ds: DiplomacyScreen, hid: str):
        self.cs, self.ds, self.hid = cs, ds, hid
        super().__init__(cs.app, cs.camp.rules.houses[hid]["name"].upper(), self._items, 300)

    def _items(self) -> list[MenuItem]:
        c, me, o = self.cs.camp, self.cs.camp.player, self.hid
        items: list[MenuItem] = []
        if c.dp.at_war(me, o):
            a = c.assess_for(me, o, "peace")
            items.append(MenuItem("Propose peace", lambda: self._propose("peace"), hint=_assess_hint(a)))
        else:
            for kind in ("trade", "pact", "alliance"):
                if c.dp.treaty(me, o, kind):
                    continue
                ok_pre = not (kind == "alliance" and not c.dp.has_pact(me, o) and not c.dp.treaty(me, o, "trade"))
                a = c.assess_for(me, o, kind)
                hint = _assess_hint(a) if ok_pre else "Sign a trade pact or non-aggression pact first."
                items.append(MenuItem("Propose " + TREATY_LABEL[kind].lower(), (lambda k=kind: self._propose(k)), enabled=ok_pre, hint=hint))
            for kind in ("trade", "pact", "alliance"):
                if c.dp.treaty(me, o, kind):
                    pen = {"trade": 6, "pact": 22, "alliance": 30}[kind]
                    items.append(MenuItem(f"Break {TREATY_LABEL[kind].lower()}", (lambda k=kind: self._break(k)),
                                          hint=f"Everyone will remember: oath +{pen}."))
            ok, why = c.can_declare_war(me, o)
            just = c.war_justified(me, o)
            items.append(MenuItem("Declare war", self._war, enabled=ok,
                                  hint=("Justified by a grievance or claim." if just else "Unjust: your provinces turn restless for 8 turns and others distrust you.") if ok else why))
            have_claim = c.houses[me].claims.get(o, 0) >= c.turn
            items.append(MenuItem("Fabricate claim (3 ink)", self._claim, enabled=c.houses[me].stock.get("ink", 0) >= 3 and not have_claim,
                                  hint="A forged deed makes a later war just for 12 turns." if not have_claim else "A claim is already in force."))
        items.append(MenuItem("Gift 20 coin", lambda: self._gift("coin", 20), enabled=c.houses[me].stock.get("coin", 0) >= 20, hint="Raises their opinion of you."))
        items.append(MenuItem("Gift 4 ink", lambda: self._gift("ink", 4), enabled=c.houses[me].stock.get("ink", 0) >= 4, hint="Ink is worth more to them than coin."))
        items.append(MenuItem("Back", self.app.scenes.pop))
        return items

    def _propose(self, kind: str) -> None:
        c = self.cs.camp
        ok, msg = c.propose(c.player, self.hid, kind)
        self.cs.drain_hooks()
        self.ds.say(msg, ok)
        self.app.scenes.pop()

    def _break(self, kind: str) -> None:
        c = self.cs.camp
        c.break_treaty(c.player, self.hid, kind)
        self.ds.say("Treaty broken. They will not forget.", False)
        self.app.scenes.pop()

    def _war(self) -> None:
        c = self.cs.camp
        if c.declare_war(c.player, self.hid):
            self.ds.say(f"War with {c.short(self.hid)}.", False)
            self.app.audio.play("concord_horn", 0.8)
        self.app.scenes.pop()

    def _claim(self) -> None:
        c = self.cs.camp
        if c.fabricate_claim(c.player, self.hid):
            self.ds.say("A convenient deed turns up in the archive.")
        self.app.scenes.pop()

    def _gift(self, res: str, amt: int) -> None:
        c = self.cs.camp
        if c.gift(c.player, self.hid, res, amt):
            self.ds.say(f"{c.short(self.hid)} accepts the gift.")
        self.app.scenes.pop()


def _assess_hint(a) -> str:
    return f"{'Likely yes' if a.accept else 'Likely no'} ({a.score:.0f}): {a.text()}"[:118]


# ====================================================================================== houses / chronicle
class HousesScreen(Scene):
    def __init__(self, cs):
        super().__init__(cs.app)
        self.cs, self.c = cs, cs.camp
        self.t = 0
        self.bg = _bg(cs.app)

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t > 6 and ("BACK" in self.inp.player(0).pressed or "CONFIRM" in self.inp.player(0).pressed):
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        c, f = self.c, self.app.font
        surf.blit(self.bg, (0, 0))
        f.draw(surf, "THE HOUSES", (10, 8), art.WAX, None, scale=2)
        ids = c.rules.house_ids()
        vis = c.visible(c.player)
        r = pygame.Rect(8, 32, 464, 200)
        draw_panel(surf, r, fill=PANEL, alpha=246)
        heads = ["House", "Prov", "Units", "Techs", "Power", "Wars", "Alliances"]
        xs = [14, 140, 180, 224, 268, 320, 400]
        for h, x in zip(heads, xs):
            f.draw(surf, h, (r.x + x, r.y + 6), DIM, None)
        y = r.y + 20
        for hid in ids:
            h = c.houses[hid]
            col = house_col(c, hid)
            surf.blit(art.crest(col, 10), (r.x + 4, y))
            f.draw(surf, c.rules.houses[hid]["name"] + (" (you)" if hid == c.player else "") + ("" if h.alive else "  FALLEN"), (r.x + 18, y + 1),
                   col if h.alive else DIM, None)
            known = hid == c.player or any(p.id in vis for p in c.provinces_of(hid)) or True
            f.draw(surf, str(len(c.provinces_of(hid))), (r.x + xs[1], y + 1), PARCHMENT, None)
            seen_units = sum(len(a.units) for a in c.armies_of(hid)) if hid == c.player else sum(len(a.units) for a in c.armies_of(hid) if a.pid in vis)
            f.draw(surf, str(seen_units) + ("" if hid == c.player else "+?"), (r.x + xs[2], y + 1), PARCHMENT, None)
            f.draw(surf, str(len(h.techs)), (r.x + xs[3], y + 1), PARCHMENT, None)
            f.draw(surf, f"{c.house_power(hid):.0f}" if hid == c.player or h.alive else "-", (r.x + xs[4], y + 1), PARCHMENT, None)
            f.draw(surf, ",".join(c.short(o)[:3] for o in c.dp.enemies_of(hid)) or "-", (r.x + xs[5], y + 1), DANGER if c.dp.enemies_of(hid) else DIM, None)
            f.draw(surf, ",".join(c.short(o)[:3] for o in c.dp.allies_of(hid)) or "-", (r.x + xs[6], y + 1), GOOD if c.dp.allies_of(hid) else DIM, None)
            f.draw(surf, f"{c.rules.houses[hid]['archetype']}: {c.rules.houses[hid]['goal'][:62]}", (r.x + 18, y + 11), DIM, None)
            y += 30
        y += 4
        f.draw(surf, f"Provinces held by anyone: {sum(1 for p in c.map.provinces if p.owner)} of {len(c.map.provinces)}   Dominion at "
                     f"{-(-len(c.map.provinces) * 6 // 10)}", (r.x + 8, y), PARCHMENT, None)
        draw_prompts(surf, self.app, [("BACK", "Close")], y=H - 14)


class ChronicleScreen(Scene):
    def __init__(self, cs):
        super().__init__(cs.app)
        self.cs, self.c = cs, cs.camp
        self.sel = 0
        self.t = 0
        self.bg = _bg(cs.app)

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        _, dy = p.menu_dir()
        n = len(self.c.notes)
        if dy and n:
            self.sel = max(0, min(n - 1, self.sel + dy * 3))
        if self.t > 6 and "BACK" in p.pressed:
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        c, f = self.c, self.app.font
        surf.blit(self.bg, (0, 0))
        f.draw(surf, "CHRONICLE", (10, 8), art.WAX, None, scale=2)
        r = pygame.Rect(8, 30, 464, 204)
        draw_panel(surf, r, fill=PANEL, alpha=246)
        notes = list(reversed(c.notes))
        y = r.y + 6
        for n in notes[self.sel:self.sel + 18]:
            col = house_col(c, n.house) if n.house else PARCHMENT
            f.draw(surf, f"T{n.turn}", (r.x + 6, y), DIM, None)
            for j, ln in enumerate(f.wrap(n.text, 400)[:1]):
                f.draw(surf, ln, (r.x + 34, y), col if n.kind in ("capture", "war", "eliminated") else PARCHMENT, None)
            y += 10
        draw_prompts(surf, self.app, [("UP", "Scroll"), ("BACK", "Close")], y=H - 14)


# ====================================================================================== events / reports / end
class EventScreen(Scene):
    def __init__(self, cs, ev: dict):
        super().__init__(cs.app)
        self.cs, self.c, self.ev = cs, cs.camp, ev
        self.t = 0
        self.e = cs.camp.rules.events[ev["event"]]
        other = cs.camp.short(ev["other"]) if ev.get("other") else ""
        items = [MenuItem(o["label"], (lambda i=i: self.choose(i)), hint=o.get("hint", "").replace("{other}", other))
                 for i, o in enumerate(self.e["options"])]
        self.menu = Menu(cs.app, items, 380)
        self.result: list[str] | None = None
        self.opaque = False

    def choose(self, i: int) -> None:
        self.result = self.c.resolve_event(self.ev, i)
        self.app.audio.play("concord_quill", 0.6)

    def update(self, dt: float) -> None:
        self.t += 1
        if self.t < 8:
            return
        p = self.inp.player(0)
        if self.result is None:
            self.menu.update()
        elif "CONFIRM" in p.pressed or "BACK" in p.pressed:
            self.app.scenes.pop()
            if self.c.pending:
                self.app.scenes.push(EventScreen(self.cs, self.c.pending[0]))

    def draw(self, surf: pygame.Surface) -> None:
        f = self.app.font
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((10, 8, 20, 170))
        surf.blit(dim, (0, 0))
        r = pygame.Rect(40, 40, 400, 190)
        draw_panel(surf, r, fill=(236, 224, 190), alpha=252, border=art.WAX)
        f.draw(surf, self.e["title"], (r.x + 12, r.y + 10), art.WAX, None, scale=2)
        where = ""
        if self.ev.get("pid") is not None:
            where = self.c.map.provinces[self.ev["pid"]].name
        f.draw(surf, where or self.c.name_of(self.ev["house"]), (r.x + 12, r.y + 28), (90, 78, 70), None)
        text = self.e["text"]
        if self.ev.get("other"):
            text = text.replace("{other}", self.c.short(self.ev["other"]))
        f.draw_wrapped(surf, text, pygame.Rect(r.x + 12, r.y + 42, r.w - 24, 50), art.INK, None)
        if self.result is None:
            self.menu.draw(surf, (r.x + 12, r.y + 104))
        else:
            f.draw(surf, "Decided." if not self.result else "Outcome: " + ", ".join(self.result), (r.x + 12, r.y + 110), art.INK, None)
            draw_prompts(surf, self.app, [("CONFIRM", "Continue")], y=r.bottom - 14)


class ReportScreen(Scene):
    def __init__(self, cs, notes):
        super().__init__(cs.app)
        self.cs, self.c, self.notes = cs, cs.camp, notes
        self.t = 0
        self.opaque = False

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 10 and ("CONFIRM" in p.pressed or "BACK" in p.pressed or "A" in p.pressed):
            self.app.scenes.pop()

    def draw(self, surf: pygame.Surface) -> None:
        f, c = self.app.font, self.c
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((10, 8, 20, 150))
        surf.blit(dim, (0, 0))
        r = pygame.Rect(60, 36, 360, 198)
        draw_panel(surf, r, fill=(236, 224, 190), alpha=252, border=art.WAX)
        f.draw(surf, f"Turn {c.turn - 1} report", (r.x + 12, r.y + 8), art.WAX, None, scale=2)
        f.draw(surf, c.date_text(), (r.x + 12, r.y + 26), (90, 78, 70), None)
        y = r.y + 40
        if not self.notes:
            f.draw(surf, "A quiet season.", (r.x + 12, y), art.INK, None)
        for n in self.notes[:13]:
            col = house_col(c, n.house) if n.house else art.INK
            col = tuple(int(v * 0.7) for v in col)
            lines = f.wrap(n.text, r.w - 24)
            f.draw(surf, lines[0], (r.x + 12, y), col, None)
            y += 10
        draw_prompts(surf, self.app, [("CONFIRM", "Continue")], y=r.bottom - 14)


class EndScreen(Scene):
    def __init__(self, cs, won: bool):
        super().__init__(cs.app)
        self.cs, self.c, self.won = cs, cs.camp, won
        self.t = 0
        self.bg = _bg(cs.app)
        cs.app.audio.play("victory_sting" if won else "defeat_sting", 0.9)

    def update(self, dt: float) -> None:
        self.t += 1
        p = self.inp.player(0)
        if self.t > 30 and ("CONFIRM" in p.pressed or "BACK" in p.pressed):
            self.cs.show_menu()

    def draw(self, surf: pygame.Surface) -> None:
        f, c = self.app.font, self.c
        surf.blit(self.bg, (0, 0))
        title = {"conquest": "THE LAST CROWN", "concord": "THE CONCORD HOLDS", "dominion": "DOMINION", "defeat": "THE HOUSE FALLS"}.get(c.victory or "", "THE END")
        f.draw(surf, title, (W // 2, 34), art.WAX if self.won else art.INK, None, anchor="midtop", scale=4)
        text = {"conquest": "No rival banner remains.", "concord": "Every living house has sworn the Accord, and kept it.",
                "dominion": "Three provinces in five are yours. The rest will follow the ledger.",
                "defeat": "Your last province is lost. The chroniclers will tell it kindly, or not at all."}.get(c.victory or "", "")
        f.draw(surf, text, (W // 2, 80), art.INK, None, anchor="midtop")
        r = pygame.Rect(120, 110, 240, 100)
        draw_panel(surf, r, fill=PANEL, alpha=246)
        rows = [("Turns", c.turn), ("Provinces held", len(c.provinces_of(c.player))), ("Battles fought", c.stats["battles"]),
                ("Battles won", c.stats["battles_won"]), ("Provinces taken", c.stats["provinces_taken"]), ("Treaties signed", c.stats["treaties"])]
        for i, (k, v) in enumerate(rows):
            f.draw(surf, k, (r.x + 12, r.y + 8 + i * 13), DIM, None)
            f.draw(surf, str(v), (r.right - 12, r.y + 8 + i * 13), PARCHMENT, None, anchor="topright")
        if self.won:
            f.draw(surf, "The Concord facet is repaired.", (W // 2, 218), art.WAX, None, anchor="midtop")
        draw_prompts(surf, self.app, [("CONFIRM", "Continue")], y=H - 14)
