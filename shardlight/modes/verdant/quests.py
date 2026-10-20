"""Quest engine: data-driven stages (talk / kill / have / visit / lamps / flag / use) with event notifications.

``QuestLog`` holds only primitives (saved as JSON).  It reads quest definitions from the :class:`Catalog` and acts on
the :class:`~shardlight.modes.verdant.sim.Game` through a tiny surface: ``game.count(item)``, ``game.take(item, n)``,
``game.give(item, n)``, ``game.add_gold``, ``game.add_skill_xp``, ``game.flags``, ``game.kills``, ``game.hook`` and
``game.say``.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import interiors
from . import npcs
from . import tiles as T


class QuestLog:
    def __init__(self, cat):
        self.cat = cat
        self.state: dict[str, dict[str, Any]] = {}      # qid -> {"stage": int, "progress": int, "done": bool}

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {k: dict(v) for k, v in self.state.items()}

    def load(self, raw: dict) -> None:
        self.state = {}
        for qid, v in (raw or {}).items():
            if self.cat.quest(qid) is None:
                continue
            self.state[qid] = {"stage": int(v.get("stage", 0)), "progress": int(v.get("progress", 0)), "done": bool(v.get("done", False))}

    # ------------------------------------------------------------------ queries
    def is_done(self, qid: str) -> bool:
        return bool(self.state.get(qid, {}).get("done"))

    def is_active(self, qid: str) -> bool:
        s = self.state.get(qid)
        return bool(s) and not s["done"]

    def active_ids(self) -> list[str]:
        order = {"main": 0, "side": 1}
        ids = [q for q, s in self.state.items() if not s["done"]]
        return sorted(ids, key=lambda q: (order.get((self.cat.quest(q) or {}).get("track", "side"), 1), q))

    def stage(self, qid: str) -> dict | None:
        q = self.cat.quest(qid)
        s = self.state.get(qid)
        if not q or not s or s["done"]:
            return None
        return q["stages"][min(s["stage"], len(q["stages"]) - 1)]

    def requirement_met(self, game, qid: str) -> bool:
        q = self.cat.quest(qid)
        if q is None:
            return False
        req = q.get("requires") or {}
        if "quest" in req and not self.is_done(req["quest"]):
            return False
        if "flag" in req and not game.flags.get(req["flag"]):
            return False
        if "unlock" in req and not game.has_unlock(req["unlock"]):
            return False
        return True

    def offerable(self, game, giver: str) -> list[str]:
        out = []
        for q in self.cat.quests():
            qid = q["id"]
            if q["giver"] != giver or qid in self.state:
                continue
            if self.requirement_met(game, qid):
                out.append(qid)
        return out

    def progress_text(self, game, qid: str) -> str:
        st = self.stage(qid)
        if st is None:
            return ""
        s = self.state[qid]
        k = st["kind"]
        n = st.get("count", 1)
        if k in ("kill", "lamps"):
            return f"{st['text']} ({min(s['progress'], n)}/{n})"
        if k == "have":
            return f"{st['text']} ({min(game.count(st['target']), n)}/{n})"
        if k == "talk" and st.get("give"):
            have = ", ".join(f"{game.cat.item(i)['name']} {min(game.count(i), c)}/{c}" for i, c in st["give"].items())
            return f"{st['text']} [{have}]"
        return st["text"]

    # ------------------------------------------------------------------ transitions
    def start(self, game, qid: str) -> bool:
        q = self.cat.quest(qid)
        if q is None or qid in self.state or not self.requirement_met(game, qid):
            return False
        self.state[qid] = {"stage": 0, "progress": 0, "done": False}
        game.toast(f"Quest: {q['title']}")
        game.hook("verdant.quest_started", quest=qid)
        self._enter_stage(game, qid)
        self._auto(game, qid)
        return True

    def _enter_stage(self, game, qid: str) -> None:
        st = self.stage(qid)
        if st is None:
            return
        self.state[qid]["progress"] = 0
        for it, n in (st.get("grant") or {}).items():
            game.give(it, n)
        if st["kind"] == "kill":
            self.state[qid]["base"] = game.kills.get(st["target"], 0)

    def _advance(self, game, qid: str) -> None:
        q = self.cat.quest(qid)
        s = self.state[qid]
        s["stage"] += 1
        s["progress"] = 0
        if s["stage"] >= len(q["stages"]):
            self._complete(game, qid)
            return
        self._enter_stage(game, qid)
        game.toast(f"{q['title']}: {q['stages'][s['stage']]['text']}")
        self._auto(game, qid)

    def _complete(self, game, qid: str) -> None:
        q = self.cat.quest(qid)
        s = self.state[qid]
        s["done"] = True
        r = q.get("reward") or {}
        if r.get("gold"):
            game.add_gold(int(r["gold"]))
        for it, n in (r.get("items") or {}).items():
            game.give(it, int(n))
        for sk, xp in (r.get("skill") or {}).items():
            game.add_skill_xp(sk, float(xp))
        for fac, amt in (r.get("rep") or {}).items():
            game.hook("rep", faction=fac, amount=int(amt))
        if q.get("flag"):
            game.set_flag(q["flag"])
        if q.get("lore"):
            game.hook("lore", id=q["lore"])
        game.toast(f"Quest complete: {q['title']}")
        game.hook("verdant.quest_completed", quest=qid)
        game.sfx("verdant_quest")

    def _auto(self, game, qid: str) -> None:
        """Advance stages that are satisfied without any player action (have / flag / visit with prior progress)."""
        for _ in range(8):
            st = self.stage(qid)
            if st is None:
                return
            k = st["kind"]
            s = self.state[qid]
            ok = False
            if k == "have":
                ok = game.count(st["target"]) >= st.get("count", 1)
            elif k == "flag":
                ok = bool(game.flags.get(st["target"]))
            elif k == "kill":
                ok = game.kills.get(st["target"], 0) - s.get("base", 0) >= st.get("count", 1)
            elif k == "lamps":
                ok = s["progress"] >= st.get("count", 1)
            if not ok:
                return
            self._advance(game, qid)

    # ------------------------------------------------------------------ target tracking
    def target_pos(self, game, qid: str) -> tuple[str, float, float] | None:
        """Rough world position of the active stage target as ``(area, x, y)`` tile coords, or None."""
        st = self.stage(qid)
        if st is None:
            return None
        k, tgt = st["kind"], st.get("target")
        r = None
        if k == "visit":
            r = self._visit_pos(game, tgt)
        elif k == "talk":
            r = self._npc_pos(game, tgt)
        elif k == "use":
            r = self._obj_pos(game, tgt)
        elif k == "lamps":
            r = self._unlit_lamp(game)
        elif k == "kill" or k == "flag":
            kind = tgt.split(".", 1)[-1] if k == "flag" else tgt
            r = self._enemy_pos(game, kind)
        elif k == "have":
            r = self._item_source_pos(game, tgt)
        return None if r is None else self._resolve_marker_pos(game, r)

    def _resolve_marker_pos(self, game, tgt: tuple[str, float, float]) -> tuple[str, float, float] | None:
        """Map a target in another area onto the approach point the player can actually reach."""
        area, x, y = tgt
        if area == game.area:
            return tgt
        if game.area == "overworld" and (area.startswith("d:") or area.startswith("b:")):
            if area.startswith("d:"):
                site = game.over.sites.get(area[2:])        # dungeons are entered through their world sites
                if site is not None:
                    return ("overworld", site.front[0] + 0.5, site.front[1] + 0.5)
                return None
            b = next((b for b in game.over.buildings if b.id == area[2:]), None)
            if b is not None:
                return ("overworld", b.front[0] + 0.5, b.front[1] + 0.5)
            return None
        if game.area.startswith("d:") and area == "overworld":
            b = next((b for b in game.over.buildings if b.id == game.area[2:]), None)
            if b is not None:                                # head back out through the door
                return (game.area, b.front[0] + 0.5, b.front[1] + 0.5)
        return None

    def _visit_pos(self, game, sid: str) -> tuple[str, float, float] | None:
        site = game.over.sites.get(sid)
        if site is None:
            return None        # the quest itself names the place, so hidden sites resolve too
        return ("overworld", site.front[0] + 0.5, site.front[1] + 0.5)

    def _npc_pos(self, game, npc_id: str) -> tuple[str, float, float] | None:
        st = game.npcs.get(npc_id)
        if st is None:
            return None
        resolved = npcs.resolve(game, st, npcs.place_for(st.defn, game.clock), game.clock)
        if resolved is None:
            return None
        area, x, y = resolved
        if area == game.area:
            return (area, x, y)
        if area.startswith("b:") and game.area == "overworld":       # they are indoors; head for the door
            bid = area.split(":", 1)[1]
            b = next((b for b in game.over.buildings if b.id == bid), None)
            if b is not None:
                return ("overworld", b.front[0] + 0.5, b.front[1] + 0.5)
        return None

    def _obj_pos(self, game, name: str) -> tuple[str, float, float] | None:
        oid = T.O.get(name)
        if oid is None:
            return None
        r = self._nearest_obj(game, game.area, oid)
        if r is not None:
            return r
        if game.area != "overworld":
            return None
        # the object lives elsewhere: check known/memorable interiors (dungeons + the hollow hall)
        cands = self._cross_area_objs(game, oid)
        return min(cands, key=lambda c: (c[1] - game.p.x) ** 2 + (c[2] - game.p.y) ** 2) if cands else None

    def _nearest_obj(self, game, area: str, oid: int) -> tuple[str, float, float] | None:
        m = game.over if area == "overworld" else game.area_map(area)
        cache = self._obj_cache = getattr(self, "_obj_cache", {})
        key = (area, oid)
        hits = cache.get(key)
        if hits is None:
            ys, xs = np.nonzero(m.obj == oid)
            hits = list(zip(xs.tolist(), ys.tolist()))
            cache[key] = hits
        if not hits:
            return None
        px, py = game.p.x, game.p.y
        x, y = min(hits, key=lambda c: (c[0] - px) ** 2 + (c[1] - py) ** 2)
        return (area, x + 0.5, y + 0.5)

    def _cross_area_objs(self, game, oid: int) -> list[tuple[str, float, float]]:
        out = []
        for key in interiors.DUNGEONS:
            r = self._nearest_obj(game, "d:" + key, oid)
            if r is not None:
                out.append(r)
        for b in game.over.buildings:                    # the Hollow Hall stands out among the town ruins
            if interiors.KIND_OF.get(b.enter) != "hollow":
                continue
            r = self._nearest_obj(game, "b:" + b.id, oid)
            if r is not None:
                out.append(r)
        return out

    def _unlit_lamp(self, game) -> tuple[str, float, float] | None:
        if game.area != "overworld" or not game.over.lamps:
            return None
        px, py = game.p.x, game.p.y
        lamps = [l for l in game.over.lamps if (l["x"], l["y"]) not in game.lit]
        if not lamps:
            return None
        l = min(lamps, key=lambda l: (l["x"] + 0.5 - px) ** 2 + (l["y"] + 0.5 - py) ** 2)
        return ("overworld", l["x"] + 0.5, l["y"] + 0.5)

    def _zone_pos(self, game, kinds: set[str]) -> tuple[str, float, float] | None:
        """Nearest spawn zone of any ``kind`` in the player's area or in the four dungeons (cached)."""
        px, py = game.p.x, game.p.y
        zs = [(game.area, z["x"], z["y"]) for z in game.zones() if z.get("enemy") in kinds]
        zs += [(a, x, y) for a, x, y, eid in self._dungeon_zones(game) if eid in kinds]
        if not zs:
            return None
        a, x, y = min(zs, key=lambda z: (z[1] + 0.5 - px) ** 2 + (z[2] + 0.5 - py) ** 2)
        return (a, x + 0.5, y + 0.5)

    def _enemy_pos(self, game, kind: str) -> tuple[str, float, float] | None:
        """Nearest living foe of ``kind``, or its spawn zone if it has not been woken yet."""
        px, py = game.p.x, game.p.y
        prey = [e for e in game.enemies if not e.dead and e.kind == kind]
        if prey:
            e = min(prey, key=lambda e: (e.x - px) ** 2 + (e.y - py) ** 2)
            return (game.area, e.x, e.y)
        return self._zone_pos(game, {kind})

    def _item_source_pos(self, game, item_id: str) -> tuple[str, float, float] | None:
        """For ``have`` stages: the enemy that drops the item, else its spawn zone, else the shopkeeper selling it."""
        px, py = game.p.x, game.p.y
        bearers = {d["id"] for d in game.cat.db.all("verdant.enemy")
                   if any(x.get("item") == item_id for x in d.get("drops", []))}
        # 1. nearest living bearer (e.g. a boss holding the quest item)
        prey = [e for e in game.enemies if not e.dead and e.kind in bearers]
        if prey:
            e = min(prey, key=lambda e: (e.x - px) ** 2 + (e.y - py) ** 2)
            return (game.area, e.x, e.y)
        # 2. nearest spawn zone of a bearer, in the player's area or in a dungeon
        pos = self._zone_pos(game, bearers)
        if pos is not None:
            return pos
        # 3. nearest shopkeeper who stocks it
        sellers = {s["id"] for s in game.cat.db.all("verdant.shop")
                   if any(st["item"] == item_id for st in s.get("stock", []))}
        shops = [self._npc_pos(game, nd["id"]) for nd in game.cat.db.all("verdant.npc") if nd.get("shop") in sellers]
        shops = [c for c in shops if c is not None and c[0] == game.area]
        if shops:
            return min(shops, key=lambda c: (c[1] - px) ** 2 + (c[2] - py) ** 2)
        return None

    def _dungeon_zones(self, game) -> list[tuple[str, float, float, str]]:
        """Zone entries of all four dungeons, ``(area, x, y, enemy)``; built once and cached."""
        cache = self._dz_cache = getattr(self, "_dz_cache", [])
        if cache:
            return cache
        for key in interiors.DUNGEONS:
            try:
                wm = game.area_map("d:" + key)
            except Exception:
                continue
            cache.extend(("d:" + z.get("area", key), z["x"], z["y"], z["enemy"]) for z in wm.spawns if z.get("enemy"))
        return cache

    # ------------------------------------------------------------------ events
    def on_item_change(self, game) -> None:
        for qid in list(self.active_ids()):
            self._auto(game, qid)

    def on_flag(self, game) -> None:
        for qid in list(self.active_ids()):
            self._auto(game, qid)

    def on_kill(self, game, enemy: str) -> None:
        for qid in list(self.active_ids()):
            st = self.stage(qid)
            if st and st["kind"] == "kill" and st["target"] == enemy:
                self._auto(game, qid)

    def on_lamp(self, game) -> None:
        for qid in list(self.active_ids()):
            st = self.stage(qid)
            if st and st["kind"] == "lamps":
                self.state[qid]["progress"] += 1
                self._auto(game, qid)

    def on_use(self, game, what: str) -> None:
        for qid in list(self.active_ids()):
            st = self.stage(qid)
            if st and st["kind"] == "use" and st["target"] == what:
                self._advance(game, qid)

    def on_visit_tick(self, game) -> None:
        """Called about once a second: 'visit' stages complete when the player is near the named site or area."""
        for qid in list(self.active_ids()):
            st = self.stage(qid)
            if not st or st["kind"] != "visit":
                continue
            tgt = st["target"]
            if game.area == tgt:
                self._advance(game, qid)
                continue
            site = game.over.sites.get(tgt)
            if site and game.area == "overworld":
                fx, fy = site.front
                if math.hypot(game.p.x - fx, game.p.y - fy) < 11:
                    self._advance(game, qid)

    def try_talk(self, game, npc_id: str) -> tuple[bool, str]:
        """Player finished a conversation with ``npc_id``.  Returns (progressed, message)."""
        msg = ""
        progressed = False
        for qid in list(self.active_ids()):
            st = self.stage(qid)
            if not st or st["kind"] != "talk" or st["target"] != npc_id:
                continue
            need = st.get("give") or {}
            lacking = [it for it, c in need.items() if game.count(it) < c]
            if lacking:
                names = ", ".join(f"{need[i]} x {game.cat.item(i)['name']}" for i in lacking)
                msg = f"You still need: {names}."
                continue
            for it, c in need.items():
                game.take(it, c)
            q = self.cat.quest(qid)
            if st.get("say"):
                msg = st["say"]
            elif self.state[qid]["stage"] == len(q["stages"]) - 1:
                msg = q.get("complete", "")
            progressed = True
            self._advance(game, qid)
        return progressed, msg
