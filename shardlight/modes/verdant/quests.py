"""Quest engine: data-driven stages (talk / kill / have / visit / lamps / flag / use) with event notifications.

``QuestLog`` holds only primitives (saved as JSON).  It reads quest definitions from the :class:`Catalog` and acts on
the :class:`~shardlight.modes.verdant.sim.Game` through a tiny surface: ``game.count(item)``, ``game.take(item, n)``,
``game.give(item, n)``, ``game.add_gold``, ``game.add_skill_xp``, ``game.flags``, ``game.kills``, ``game.hook`` and
``game.say``.
"""
from __future__ import annotations

import math
from typing import Any


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
