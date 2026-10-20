"""Shared persistent world state and the data-driven *Echo* engine.

An Echo is a cross-mode consequence defined in JSON (kind ``echo``).  Modes never call each other;
they emit named events with a payload and read flags/unlocks.  The Echo engine matches events
against echo definitions and applies declarative effects.  This is how a signal decoded in space can
reveal a ruin in the RPG, unlock a boss in the roguelike and a technology in the strategy mode,
without any mode importing another.

Echo schema::

    {"id": "...", "on": "space.signal_decoded",
     "where": {"signal": "whisper"},                       # payload fields that must equal
     "require": {"flags": [..], "unlocks": [..], "not_flags": [..], "counters": {"n": 3},
                 "facets": [..]},                          # world-state conditions
     "once": true,
     "effects": [{"set_flag": "x"}, {"unlock": "id"}, {"lore": "id"}, {"grant": 5},
                 {"counter": "name", "add": 1}, {"rep": "faction", "add": 5},
                 {"toast": "text"}, {"emit": "event.name", "payload": {}}]}
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable

from . import log
from .content import ContentDB

LOG = log.get("world")

ECHO_SCHEMA = {
    "on": {"type": "str", "required": True},
    "where": {"type": "dict", "values": {"type": "any"}},
    "require": {"type": "dict", "fields": {
        "flags": {"type": "list", "items": {"type": "str"}},
        "not_flags": {"type": "list", "items": {"type": "str"}},
        "unlocks": {"type": "list", "items": {"type": "str"}},
        "facets": {"type": "list", "items": {"type": "str"}},
        "counters": {"type": "dict", "values": {"type": "float"}},
    }},
    "once": {"type": "bool"},
    "title": {"type": "str"},
    "description": {"type": "str"},      # shown in the Archive once the echo has fired
    "hint": {"type": "str"},             # shown in the Archive before it fires
    "secret": {"type": "bool"},          # hidden from the Archive entirely
    "effects": {"type": "list", "required": True, "items": {"type": "dict", "values": {"type": "any"}}},
}

MAX_CASCADE = 64


class World:
    """Facade over the profile dict with convenient, validated mutation helpers."""

    def __init__(self, profile: dict, content: ContentDB | None = None):
        self.profile = profile
        self.content = content
        self.toasts: deque[str] = deque(maxlen=16)
        self.listeners: list[Callable[[str, dict], None]] = []
        self.event_log: deque[tuple[str, dict]] = deque(maxlen=200)

    # -- reads ------------------------------------------------------------------------------
    def flag(self, name: str, default: Any = False) -> Any:
        return self.profile["flags"].get(name, default)

    def has_unlock(self, uid: str) -> bool:
        return uid in self.profile["unlocks"]

    def has_lore(self, lid: str) -> bool:
        return lid in self.profile["lore"]

    def counter(self, name: str) -> float:
        return self.profile["counters"].get(name, 0)

    def rep(self, faction: str) -> int:
        return self.profile["reputation"].get(faction, 0)

    def facet_repaired(self, mode_id: str) -> bool:
        return mode_id in self.profile["facets"]

    def mode_data(self, mode_id: str) -> dict:
        return self.profile["modes"].setdefault(mode_id, {})

    # -- writes -----------------------------------------------------------------------------
    def set_flag(self, name: str, value: Any = True) -> None:
        self.profile["flags"][name] = value

    def unlock(self, uid: str) -> bool:
        if uid in self.profile["unlocks"]:
            return False
        self.profile["unlocks"].append(uid)
        self.profile["unlocks"].sort()
        return True

    def add_lore(self, lid: str) -> bool:
        if lid in self.profile["lore"]:
            return False
        self.profile["lore"].append(lid)
        return True

    def add_counter(self, name: str, amount: float = 1) -> float:
        self.profile["counters"][name] = self.profile["counters"].get(name, 0) + amount
        return self.profile["counters"][name]

    def add_rep(self, faction: str, amount: int) -> int:
        v = max(-100, min(100, self.profile["reputation"].get(faction, 0) + amount))
        self.profile["reputation"][faction] = v
        return v

    def repair_facet(self, mode_id: str) -> bool:
        if mode_id in self.profile["facets"]:
            return False
        self.profile["facets"].append(mode_id)
        return True

    def complete_facet(self, mode_id: str) -> bool:
        """Mark a shard's main trial complete: repairs its Lens facet and emits ``<mode>.facet_repaired``."""
        first = self.repair_facet(mode_id)
        if first:
            self.emit(f"{mode_id}.facet_repaired")
        return first

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    # -- echo engine ------------------------------------------------------------------------
    def emit(self, event: str, **payload: Any) -> list[str]:
        """Emit an event; returns the ids of echoes that fired. Cascades are bounded."""
        fired: list[str] = []
        queue: deque[tuple[str, dict]] = deque([(event, payload)])
        steps = 0
        while queue and steps < MAX_CASCADE:
            steps += 1
            ev, pl = queue.popleft()
            self.event_log.append((ev, pl))
            for fn in self.listeners:
                fn(ev, pl)
            if self.content is None:
                continue
            for echo in self.content.all("echo"):
                if echo["on"] != ev or not self._matches(echo, pl):
                    continue
                eid = echo["id"]
                if echo.get("once", True) and eid in self.profile["echoes_fired"]:
                    continue
                if not self._requirements_met(echo.get("require", {})):
                    continue
                if echo.get("once", True):
                    self.profile["echoes_fired"].append(eid)
                fired.append(eid)
                self._apply(echo["effects"], queue)
        if queue:
            LOG.warning("echo cascade truncated at %d steps", MAX_CASCADE)
        return fired

    @staticmethod
    def _matches(echo: dict, payload: dict) -> bool:
        return all(payload.get(k) == v for k, v in echo.get("where", {}).items())

    def _requirements_met(self, req: dict) -> bool:
        p = self.profile
        return (all(f in p["flags"] and p["flags"][f] for f in req.get("flags", []))
                and not any(p["flags"].get(f) for f in req.get("not_flags", []))
                and all(u in p["unlocks"] for u in req.get("unlocks", []))
                and all(m in p["facets"] for m in req.get("facets", []))
                and all(p["counters"].get(k, 0) >= v for k, v in req.get("counters", {}).items()))

    def _apply(self, effects: list[dict], queue: deque) -> None:
        for eff in effects:
            if "set_flag" in eff:
                self.set_flag(eff["set_flag"], eff.get("value", True))
            elif "unlock" in eff:
                if self.unlock(eff["unlock"]) and eff.get("announce", True):
                    self.toast(eff.get("text", f"Unlocked: {eff['unlock']}"))
            elif "lore" in eff:
                if self.add_lore(eff["lore"]):
                    self.toast("New lore recorded")
            elif "grant" in eff:
                cur = self.profile["currency"]
                cur["glint"] = cur.get("glint", 0) + int(eff["grant"])
            elif "counter" in eff:
                self.add_counter(eff["counter"], eff.get("add", 1))
            elif "rep" in eff:
                self.add_rep(eff["rep"], int(eff.get("add", 0)))
            elif "toast" in eff:
                self.toast(eff["toast"])
            elif "repair" in eff:
                self.repair_facet(eff["repair"])
            elif "emit" in eff:
                queue.append((eff["emit"], dict(eff.get("payload", {}))))
            else:
                LOG.warning("unknown echo effect %r", eff)


class Economy:
    """Controlled shared currency: each mode may grant at most ``cap`` Glint per session slice."""

    CAPS = {"default": 40}

    def __init__(self, world: World):
        self.world = world
        self.granted: dict[str, int] = {}

    def grant(self, mode_id: str, amount: int, reason: str = "") -> int:
        cap = self.CAPS.get(mode_id, self.CAPS["default"])
        room = max(0, cap - self.granted.get(mode_id, 0))
        amt = max(0, min(int(amount), room))
        if amt:
            cur = self.world.profile["currency"]
            cur["glint"] = cur.get("glint", 0) + amt
            self.granted[mode_id] = self.granted.get(mode_id, 0) + amt
        return amt

    def reset_session(self) -> None:
        self.granted.clear()
