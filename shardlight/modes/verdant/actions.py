"""Player interactions with the world (B button): doors, stairs, lamps, chests, gathering, beds, stations, signs and
people.  ``ActionsMixin`` is mixed into :class:`~shardlight.modes.verdant.sim.Game`; actions that need UI return a small
dict (``{"type": "talk", ...}``) which the scene opens as a screen.
"""
from __future__ import annotations

import math
from typing import Any

from . import combat
from . import tiles as T

INN_COST = 10
REACH = 1.75
STATION_OF = {"hearth": "hearth", "forge": "forge", "bench": "bench", "campfire": "hearth"}
CACHE_KINDS = ("cairn", "dig", "hiddendoor")
TEXT_SIGNS = {}


class ActionsMixin:
    # ------------------------------------------------------------------ noise / helpers
    def alert_noise(self, x: float, y: float, radius: float) -> None:
        combat.alert_noise(self, x, y, radius)

    def dest_fallback(self, st):
        return ("overworld", st.x, st.y)

    # ------------------------------------------------------------------ target selection
    def interact_target(self) -> dict | None:
        P = self.p
        wm = self.wm
        best: tuple[float, dict] | None = None

        def consider(d: float, info: dict) -> None:
            nonlocal best
            if best is None or d < best[0]:
                best = (d, info)

        for st in self.npcs.values():
            if st.area != self.area:
                continue
            d = math.hypot(st.x - P.x, st.y - P.y)
            reach = 2.8 if st.defn.get("shop") and self.area.startswith("b:") else 2.0
            if d <= reach:
                consider(d - 0.5, {"kind": "npc", "id": st.id, "label": f"Talk to {st.defn['name']}", "x": st.x, "y": st.y})
        px, py = int(P.x), int(P.y)
        for y in range(py - 2, py + 3):
            for x in range(px - 2, px + 3):
                if not (0 <= x < wm.W and 0 <= y < wm.H):
                    continue
                oid = int(wm.obj[y, x])
                if oid == 0:
                    continue
                df = T.OBJ_LIST[oid]
                d = math.hypot(x + 0.5 - P.x, y + 0.5 - P.y)
                if d > REACH:
                    continue
                label = self._label_for(df, area=self.area, x=x, y=y)
                if not label:
                    continue
                fa = math.degrees(math.atan2(y + 0.5 - P.y, x + 0.5 - P.x))
                bias = 0.0 if abs((fa - P.facing + 180) % 360 - 180) < 70 else 0.35
                consider(d + bias, {"kind": "obj", "name": df.name, "x": x, "y": y, "label": label})
        if self.area == "overworld":
            for b in wm.buildings:
                fx, fy = b.front
                d = math.hypot(fx + 0.5 - P.x, fy + 0.5 - P.y)
                if d <= 1.25:
                    consider(d - 0.3, {"kind": "door", "b": b, "label": f"Enter {b.label or 'building'}", "x": fx, "y": fy})
        for m in wm.markers:
            if m.kind == "shrine":
                d = math.hypot(m.x + 0.5 - P.x, m.y + 0.5 - P.y)
                if d <= 1.8:
                    consider(d - 0.3, {"kind": "shrine", "x": m.x, "y": m.y, "label": "Pray at the wayshrine"})
        return best[1] if best else None

    def _label_for(self, df: T.ObjDef, area: str, x: int, y: int) -> str:
        n = df.name
        if df.gather:
            return df.interact
        if n == "chest":
            info = self.chests.get((area, x, y))
            if info and info["id"] in self.opened:
                return ""
            return "Open chest"
        if n == "stairdown":
            return "Descend" if any(m.kind == "entrance" and (m.x, m.y) == (x, y) for m in self.over.markers) or area != "overworld" else ""
        if n == "bed":
            return "Rest" if area.startswith("b:") else ""
        if n == "lamp_lit":
            return ""
        if n == "bench" and not self.wm.name.endswith("lamp_house"):
            return ""
        if n in ("cairn", "dig"):
            info = self.chests.get((area, x, y))
            return df.interact if info and info["id"] not in self.opened else ""
        if n == "hiddendoor":
            return df.interact
        return df.interact

    # ------------------------------------------------------------------ dispatch
    def do_interact(self) -> dict | None:
        tg = self.interact_target()
        if tg is None:
            return None
        kind = tg["kind"]
        if kind == "npc":
            return {"type": "talk", "npc": tg["id"]}
        if kind == "door":
            b = tg["b"]
            self.enter_area(f"b:{b.id}")
            return {"type": "enter", "label": b.label}
        if kind == "shrine":
            return self._shrine(tg)
        return self._act_obj(tg["name"], tg["x"], tg["y"])

    def _act_obj(self, name: str, x: int, y: int) -> dict | None:
        df = T.OBJ_LIST[T.O[name]]
        if df.gather:
            return self._start_gather(x, y, df)
        if name == "lamp":
            return self._light_lamp(x, y)
        if name == "well":
            self.p.stamina = 100.0
            self.toast("You drink. The water is cold and tastes of stone.")
            self.sfx("verdant_drink")
            return None
        if name == "bed":
            return self._bed()
        if name in STATION_OF:
            return {"type": "craft", "station": STATION_OF[name]}
        if name == "notice":
            return {"type": "text", "title": "Notice Board", "text": self.notice_text()}
        if name == "signpost":
            return {"type": "text", "title": "Signpost", "text": self.sign_text()}
        if name in ("chest", "cairn", "dig"):
            return self._open_chest(self.area, x, y)
        if name == "hiddendoor":
            return self._knock(x, y)
        if name == "stairdown":
            return self._stairs_down(x, y)
        if name == "stairup":
            if self.area.startswith("d:"):
                self.leave_area()
                return {"type": "leave"}
            return None
        if name == "greatlamp":
            return self._great_lamp(x, y)
        if name == "tablet":
            return self._tablet()
        return None

    # ------------------------------------------------------------------ individual actions
    def _shrine(self, tg: dict) -> dict | None:
        P = self.p
        P.hp = self.max_hp()
        P.stamina = 100.0
        P.fever = False
        self.respawn_point = (tg["x"] + 0.5, tg["y"] + 1.5, "overworld")
        self.toast("The shrine warms. You will wake here if you fall.")
        self.sfx("verdant_shrine")
        return None

    def _light_lamp(self, x: int, y: int) -> dict | None:
        if self.count("taper") <= 0:
            self.toast("You need a lamp taper.")
            return None
        self.take("taper", 1)
        self.set_obj("overworld", x, y, T.O["lamp_lit"])
        self.lit.add((x, y))
        self.stats["lamps"] += 1
        self.add_skill_xp("forage", 1.5)
        self.sfx("verdant_lamp")
        self.fx_add("glow", x + 0.5, y + 0.5, life=0.8)
        self.quests.on_lamp(self)
        return None

    def _bed(self) -> dict | None:
        b = self.building_of(self.area)
        if b is None or b.style != "inn":
            self.toast("This is someone's bed. It would be rude.")
            return None
        return {"type": "rest", "cost": INN_COST}

    def rest(self) -> str:
        if self.p.gold < INN_COST:
            return "You cannot afford a room."
        self.p.gold -= INN_COST
        hrs = (6.0 - self.clock) % 24.0
        hrs = max(hrs, 4.0) if hrs < 4 else hrs
        self.advance_hours(hrs)
        self.p.fever = False
        self.p.hp = self.max_hp()
        self.p.stamina = 100.0
        self.toast("You sleep soundly. Morning.")
        return "You sleep soundly."

    def roll_loot(self, lid: str, tag: str) -> list[tuple[str, int]]:
        t = self.cat.loot(lid)
        out: list[tuple[str, int]] = []
        if not t:
            return out
        r = self.rng.child("loot", tag)
        lo, hi = t.get("gold", [0, 0])
        gold = r.randint(int(lo), int(hi)) if hi else 0
        if gold:
            out.append(("gold", gold))
        for _ in range(int(t.get("rolls", 1))):
            e = r.choice(t["entries"])
            if r.random() <= e.get("chance", 1.0):
                n = r.randint(e.get("min", 1), max(e.get("min", 1), e.get("max", 1)))
                if n > 0 and self.item_ok(e["item"]):
                    out.append((e["item"], n))
        merged: dict[str, int] = {}
        for it, n in out:
            merged[it] = merged.get(it, 0) + n
        return list(merged.items())

    def _open_chest(self, area: str, x: int, y: int) -> dict | None:
        info = self.chests.get((area, x, y))
        if not info:
            return None
        if info["id"] in self.opened:
            self.toast("Empty.")
            return None
        self.opened.add(info["id"])
        self.stats["chests"] += 1
        loot = self.roll_loot(info["loot"], info["id"])
        parts = []
        for it, n in loot:
            if it == "gold":
                self.add_gold(n)
                parts.append(f"{n} gold")
            else:
                self.give(it, n)
                parts.append(f"{n} x {self.cat.item(it)['name']}")
        self.sfx("verdant_chest")
        self.add_skill_xp("forage", 3)
        self.toast("Found: " + (", ".join(parts) if parts else "nothing but dust"))
        return {"type": "loot", "items": loot}

    def _knock(self, x: int, y: int) -> dict | None:
        key = f"knock:{x},{y}"
        n, last = self.flags.get(key, [0, -99.0])
        n = n + 1 if self.t - last < 4.0 else 1
        self.flags[key] = [n, self.t]
        self.sfx("verdant_knock")
        if n >= 3:
            self.flags.pop(key, None)
            self.set_obj(self.area, x, y, 0)
            self.toast("The stone swings aside.")
            self.sfx("verdant_secret")
        else:
            self.toast("Knock. " + ("Something answers, hollow." if n == 2 else "The stone is cold."))
        return None

    def _stairs_down(self, x: int, y: int) -> dict | None:
        m = next((m for m in self.over.markers if m.kind == "entrance" and (m.x, m.y) == (x, y)), None)
        if m is None:
            return None
        self.enter_area(f"d:{m.data['area']}")
        return {"type": "enter", "label": self.wm.name}

    def _great_lamp(self, x: int, y: int) -> dict | None:
        st = self.quests.stage("kindle_the_hollow")
        if not st or st["kind"] != "use":
            self.toast("The Great Lamp is cold. Marrow Pell would know how to wake it.")
            return None
        if self.count("lamp_oil") < 3 or self.count("hollow_ember") < 1:
            self.toast("You need three flasks of lamp oil and the Hollow Ember.")
            return None
        self.take("lamp_oil", 3)
        self.take("hollow_ember", 1)
        self.set_obj(self.area, x, y, T.O["greatlamp_lit"])
        self.sfx("verdant_greatlamp")
        self.quests.on_use(self, "greatlamp")
        return {"type": "text", "title": "The Great Lamp", "text": "Oil, then the ember. The Lamp catches, stutters, and holds. "
                "Across Hollowmere every dark window, every road, every moor-stone turns a shade warmer. "
                "Somewhere very far away, something small turns its head."}

    def _tablet(self) -> dict | None:
        if not self.flags.get("tablet_read"):
            self.flags["tablet_read"] = True
            self.give("stone_rubbing", 1)
            self.hook("verdant.site_explored", site="listening_stones")
            self.hook("lore", id="listening_stones")
        self.quests.on_use(self, "tablet")
        return {"type": "text", "title": "The Tablet",
                "text": "Seven notes are cut into the basalt, each followed by a gap the width of a hand. "
                        "Where the eighth note should be is a smooth dish of stone, worn bright by touch. "
                        "You take a charcoal rubbing. The air hums a hymn that ends on a question."}

    # ------------------------------------------------------------------ gathering
    def _start_gather(self, x: int, y: int, df: T.ObjDef) -> dict | None:
        g = df.gather
        lvl = self.skill(g["skill"])
        need = float(g["time"]) / (1.0 + 0.1 * lvl)
        self.p.gather = {"x": x, "y": y, "t": 0.0, "need": need, "oid": T.O[df.name], "what": df.name}
        return None

    def _finish_gather(self) -> None:
        P = self.p
        gdat = P.gather
        P.gather = None
        if gdat is None:
            return
        x, y = gdat["x"], gdat["y"]
        if self.wm.obj[y, x] != gdat["oid"]:
            return
        df = T.OBJ_LIST[gdat["oid"]]
        g = df.gather
        n = 1 + (1 if self.rng.random() < 0.1 * self.skill(g["skill"]) else 0)
        self.give(g["item"], n)
        self.add_skill_xp(g["skill"], float(g["xp"]))
        self.depleted[f"{self.area}:{x}:{y}"] = {"oid": gdat["oid"], "ready": self.abs_time() + 24.0 * g["regrow"]}
        self.set_obj(self.area, x, y, 0)
        self.float_text(f"+{n} {self.cat.item(g['item'])['name']}", x + 0.5, y - 0.2, (200, 255, 200))
        self.sfx("verdant_gather")
        self.alert_noise(x + 0.5, y + 0.5, 4.0 if df.name == "ore" else 2.0)

    def _regrow(self) -> None:
        now = self.abs_time()
        for k in list(self.depleted):
            v = self.depleted[k]
            if now < v["ready"]:
                continue
            a, xs, ys = k.split(":")
            x, y = int(xs), int(ys)
            if a != "overworld":
                del self.depleted[k]
                continue
            if abs(self.p.x - x) < 2 and abs(self.p.y - y) < 2 and self.area == "overworld":
                continue
            if self.over.obj[y, x] == 0:
                self.set_obj("overworld", x, y, v["oid"])
            del self.depleted[k]

    # ------------------------------------------------------------------ text helpers
    def notice_text(self) -> str:
        lines = ["BOUNTIES & FAVOURS", ""]
        shown = 0
        for q in self.cat.quests():
            if q["id"] in self.quests.state or not self.quests.requirement_met(self, q["id"]):
                continue
            npc = self.cat.npc(q["giver"])
            if not npc:
                continue
            lines.append(f"* {q['title']} - ask {npc['name']} ({npc.get('role', '')})")
            shown += 1
        if not shown:
            lines.append("Nothing new is pinned up. The old notices are curling at the edges.")
        lines += ["", "Lamps lit across Hollowmere: " + str(self.stats["lamps"])]
        return "\n".join(lines)

    def sign_text(self) -> str:
        P = self.p
        lines = []
        for sid, s in self.over.sites.items():
            if s.kind != "settlement":
                continue
            fx, fy = s.front
            dx, dy = fx - P.x, fy - P.y
            d = int(math.hypot(dx, dy))
            ang = math.degrees(math.atan2(dy, dx)) % 360
            compass = ["east", "south-east", "south", "south-west", "west", "north-west", "north", "north-east"][int(((ang + 22.5) % 360) // 45)]
            lines.append(f"{s.name}: {d} paces {compass}")
        return "\n".join(lines) or "The sign has been scratched blank."

    # ------------------------------------------------------------------ people
    def _need_ok(self, need: str) -> bool:
        if not need:
            return True
        if need.startswith("quest."):
            qid, _, what = need[6:].partition(".")
            return self.quests.is_done(qid) if what == "done" else qid in self.quests.state
        if need.startswith("unlock."):
            return self.has_unlock("verdant.site." + need[7:])
        return bool(self.flags.get(need))

    def npc_dialogue(self, npc_id: str) -> dict:
        """Everything the conversation screen needs for one NPC right now."""
        st = self.npcs[npc_id]
        d = st.defn
        h = self.clock
        slot = "night" if (h >= 21.5 or h < 5.5) else "evening" if h >= 17.5 else "day"
        lines = d.get("lines", {}).get(slot) or d.get("lines", {}).get("day") or ["..."]
        greet = lines[(self.day + hash(npc_id) % 7) % len(lines)] if False else lines[(self.day + sum(map(ord, npc_id))) % len(lines)]
        offers = self.quests.offerable(self, npc_id)
        turn_in = []
        for qid in self.quests.active_ids():
            s = self.quests.stage(qid)
            if s and s["kind"] == "talk" and s["target"] == npc_id:
                turn_in.append(qid)
        shop = d.get("shop") or ""
        b = self.building_of(self.area)
        shop_ok = bool(shop) and b is not None and b.shop == shop
        topics = [t for t in d.get("topics", []) if self._need_ok(t.get("need", ""))]
        return {"npc": npc_id, "name": d["name"], "role": d.get("role", ""), "greet": greet, "offers": offers, "turn_in": turn_in,
                "shop": shop if shop_ok else "", "shop_closed": bool(shop) and not shop_ok, "topics": topics,
                "color": tuple(d.get("color", (180, 180, 180)))}

    def accept_quest(self, qid: str) -> bool:
        return self.quests.start(self, qid)

    def finish_talk(self, npc_id: str) -> tuple[bool, str]:
        return self.quests.try_talk(self, npc_id)

    def tell_topic(self, t: dict) -> None:
        if t.get("set"):
            self.set_flag(t["set"])
