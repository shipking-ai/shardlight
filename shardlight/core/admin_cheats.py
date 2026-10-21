"""Admin-only cheats: max out a shard, aimbot, one-shot.

Everything in here is reachable only through the token-gated admin panel (F9).
Each handler is defensive on purpose: a cheat must never crash the game it cheats in.
"""
from __future__ import annotations

from typing import Any

ONESHOT_DAMAGE = 9999.0


def _content_ids(app, kind: str) -> list[str]:
    """All content ids of a kind, from the shared content database."""
    try:
        return sorted({str(x["id"]) for x in app.content.all(kind) if x.get("id")})
    except Exception:
        return []


def _cat_ids(cat, kind: str) -> list[str]:
    try:
        return sorted({str(x["id"]) for x in cat.db.all(kind) if x.get("id")})
    except Exception:
        return []


# ------------------------------------------------------------------ per shard max-outs

def _cinder(app, scene) -> str:
    notes: list[str] = []
    lib = getattr(scene, "lib", None)
    data = getattr(scene, "data", None)
    if lib is not None and isinstance(data, dict):
        u = data.setdefault("unlocked", {"weapons": [], "boons": [], "mods": []})
        for key, ids in (("boons", list(lib.boons)), ("weapons", list(lib.weapons)), ("mods", list(lib.mods))):
            have = set(u.setdefault(key, []))
            u[key] = sorted(have | set(ids))
        data["soot"] = max(int(data.get("soot", 0)), 999999)
        data["best_floor"] = max(int(data.get("best_floor", 0)), 7)
        notes.append("every boon, weapon and modifier unlocked")
    run = getattr(scene, "run", None) or getattr(getattr(scene, "screen", None), "run", None)
    if run is not None and getattr(run, "perks", None) is not None:
        for bid in list(getattr(run.lib, "boons", {}).keys()):
            try:
                run.perks.add(bid)
            except Exception:
                pass
        try:
            run.perks.rebuild()
        except Exception:
            pass
        room = getattr(getattr(scene, "screen", None), "room", None)
        p = getattr(room, "player", None)
        if p is not None:
            p.hp = getattr(p, "hp_max", p.hp)
        notes.append("every boon active")
    app.save_now()
    return "Cinder: " + (", ".join(notes) if notes else "nothing to change")


def _verdant(app, scene) -> str:
    game = getattr(scene, "game", None)
    if game is None:
        return "Verdant: no world loaded"
    p = game.p
    p.hp = 9999.0
    p.stamina = 100.0
    p.gold = 99999
    for k in list(p.xp.keys()):
        p.xp[k] = 1200.0
    try:
        for it in game.cat.db.all("verdant.item"):
            iid = it["id"]
            stack = int(it.get("stack", 1) or 1)
            p.inv[iid] = max(p.inv.get(iid, 0), stack * 99)
        for slot, kind in (("weapon", "weapon"), ("body", "body"), ("bow", "bow")):
            if not p.equip.get(slot):
                ids = [i["id"] for i in game.cat.db.all("verdant.item") if i.get("slot") == kind]
                if ids:
                    p.equip[slot] = ids[0]
    except Exception:
        pass
    try:
        game.covered[:] = True
    except Exception:
        pass
    try:
        game.known_sites = set()
        for wm in [game.over] + list(game.areas.values()):
            game.known_sites.update(wm.sites.keys())
    except Exception:
        pass
    try:
        for q in game.cat.quests():
            qid = q["id"]
            st = game.quests.state.setdefault(qid, {"stage": 0, "progress": 0, "done": False})
            st["done"] = True
            st["stage"] = len(q.get("stages", []))
    except Exception:
        pass
    game.dead = False
    app.save_now()
    return "Verdant: stats, skills, every item, whole map and every quest"


def _umbra(app, scene) -> str:
    data = getattr(scene, "data", None)
    cat = getattr(scene, "cat", None)
    if not isinstance(data, dict):
        return "Umbra: nothing to change"
    cleared = data.setdefault("cleared", [])
    nights = _cat_ids(cat, "umbra.night") if cat is not None else []
    for n in nights:
        if n not in cleared:
            cleared.append(n)
    journal = data.setdefault("journal", {"notes": [], "facts": [], "relics": []})
    for key, kind in (("notes", "umbra.note"), ("facts", "umbra.story"), ("relics", "umbra.item")):
        have = set(journal.setdefault(key, []))
        for iid in (_cat_ids(cat, kind) if cat is not None else []):
            if iid not in have:
                journal[key].append(iid)
    data["summary"] = f"Nights cleared: {len(cleared)}/{len(nights) or len(cleared)}"
    app.save_now()
    return f"Umbra: {len(cleared)} nights cleared, journal complete"


def _terrace(app, scene) -> str:
    data = getattr(scene, "data", None)
    game = getattr(scene, "game", None)
    if isinstance(data, dict):
        data["keystones"] = max(int(data.get("keystones", 0)), 999)
        data["worlds"] = max(int(data.get("worlds", 0)), 999)
    if game is not None:
        p = getattr(game, "player", None)
        if p is not None:
            for attr in ("hp", "stamina", "hunger", "thirst", "energy"):
                if hasattr(p, attr):
                    try:
                        setattr(p, attr, 9999.0)
                    except Exception:
                        pass
    app.save_now()
    return "Terrace: 999 keystone worlds, player topped up"


def _slipstream(app, scene) -> str:
    data = getattr(scene, "data", None)
    if not isinstance(data, dict):
        return "Slipstream: nothing to change"
    data["credits"] = 999999
    data["owned"] = sorted(set(data.get("owned", [])) | set(_content_ids(app, "slipstream.vehicle")))
    data["cups_won"] = sorted(set(data.get("cups_won", [])) | set(_content_ids(app, "slipstream.cup")))
    app.save_now()
    return "Slipstream: every car owned, every cup won, 999999 credits"


def _concord(app, scene) -> str:
    data = getattr(scene, "data", None)
    if not isinstance(data, dict):
        return "Concord: nothing to change"
    data["campaigns"] = max(int(data.get("campaigns", 0)), 999)
    wins = data.setdefault("wins", {})
    for house in _content_ids(app, "concord.house"):
        try:
            wins[house] = max(int(wins.get(house, 0)), 999)
        except Exception:
            pass
    app.save_now()
    return "Concord: 999 campaigns, every house at 999 wins"


def _masks(app, scene) -> str:
    data = getattr(scene, "data", None)
    if not isinstance(data, dict):
        return "Masks: nothing to change"
    data["arcade_clears"] = max(int(data.get("arcade_clears", 0)), 999)
    training = data.setdefault("training", {})
    for key in list(training):
        training[key] = True
    app.save_now()
    return "Masks: 999 arcade clears, every training option on"


def _orrery(app, scene) -> str:
    data = getattr(scene, "data", None)
    game = getattr(scene, "game", None)
    if isinstance(data, dict):
        data["voyages"] = max(int(data.get("voyages", 0)), 999)
    if game is not None:
        game.credits = 999999.0
        flags = getattr(game, "flags", None)
        if isinstance(flags, dict):
            unlocks = set(flags.setdefault("unlocks", []))
            for kind in ("orrery.tech", "orrery.hull", "orrery.module", "orrery.signal", "orrery.civ"):
                unlocks.update(_content_ids(app, kind))
            flags["unlocks"] = sorted(unlocks)
            flags["hulls"] = sorted(set(flags.get("hulls", [])) | set(_content_ids(app, "orrery.hull")))
        try:
            hulls = _content_ids(app, "orrery.hull")
            if hulls:
                game.hull = hulls[-1]
        except Exception:
            pass
    app.save_now()
    return "Orrery: every tech, hull, module and signal unlocked, 999999 credits"


_MAX_OUT = {
    "cinder": _cinder,
    "verdant": _verdant,
    "umbra": _umbra,
    "terrace": _terrace,
    "slipstream": _slipstream,
    "concord": _concord,
    "masks": _masks,
    "orrery": _orrery,
}


def max_out(app, scene) -> str:
    """Push the shard in view to its maximum. Returns a short summary for the toast."""
    mode_id = getattr(scene, "mode_id", None)
    handler = _MAX_OUT.get(mode_id)
    if handler is None:
        return f"Nothing to max out for {mode_id or 'this view'}"
    try:
        return handler(app, scene)
    except Exception as exc:  # a broken cheat must not break the game
        return f"Max out failed: {exc}"
