"""Townsfolk: daily schedules, building entry/exit, lightweight walking (only near the player; elsewhere they snap).

An NPC's ``schedule`` maps hour ranges to places: ``in:<building id>`` (inside a house), ``at:<spot name>`` (a named
overworld spot) or ``m:<npc id>`` (a marker the template placed).  ``resolve`` turns a place into (area, x, y).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .phys import move

ANCHORS = ("npc", "seat", "hearth", "seat2", "bench", "forge", "bed2")
NPC_R = 0.28
NPC_SPEED = 1.7
TELEPORT_DIST = 46.0


@dataclass
class NpcState:
    id: str
    defn: dict
    area: str = "overworld"
    x: float = 0.0
    y: float = 0.0
    place: str = ""
    dest: tuple[str, float, float] | None = None
    path: list[tuple[float, float]] | None = None
    facing: float = 90.0
    moving: bool = False
    phase: float = 0.0
    slot: int = 0
    repath: float = 0.0
    sleeping: bool = False


def init(game) -> None:
    """Assign every NPC a stable slot among the people sharing a place so they do not stack on one tile."""
    game.npcs = {}
    users: dict[str, list[dict]] = {}
    for d in game.cat.npcs():
        for e in d["schedule"]:
            users.setdefault(e["at"], []).append(d)
    for d in game.cat.npcs():
        st = NpcState(d["id"], d)
        game.npcs[d["id"]] = st
    game._npc_slots = {}
    for place, lst in users.items():
        uniq = sorted({x["id"]: x for x in lst}.values(), key=lambda d: (0 if d.get("shop") else 1, d["id"]))
        for i, d in enumerate(uniq):
            game._npc_slots[(place, d["id"])] = i


def place_for(d: dict, hour: float) -> str:
    for e in d["schedule"]:
        a, b = e["from"], e["to"]
        if (a <= hour < b) or (a > b and (hour >= a or hour < b)):
            return e["at"]
    return d["schedule"][0]["at"]


def resolve(game, st: NpcState, place: str, hour: float) -> tuple[str, float, float] | None:
    slot = game._npc_slots.get((place, st.id), 0)
    kind, _, key = place.partition(":")
    if kind == "in":
        b = next((b for b in game.over.buildings if b.id == key), None)
        if b is None:
            return None
        area = f"b:{key}"
        wm = game.area_map(area)
        asleep = (hour >= 22 or hour < 6) and st.defn.get("home") == key
        st.sleeping = asleep
        names = ["bed"] if asleep else [a for a in ANCHORS if a in wm.spots]
        if asleep and "bed" not in wm.spots:
            names = [a for a in ANCHORS if a in wm.spots]
        spot = wm.spots.get(names[slot % len(names)]) if names else wm.start
        if spot is None:
            spot = wm.start
        return area, spot[0] + 0.5, spot[1] + 0.5
    st.sleeping = False
    if kind == "at":
        pos = game.over.spots.get(key)
        if pos is None:
            return None
        ang = slot * 1.9
        r = 0.0 if slot == 0 else 1.1 + 0.3 * slot
        for k in range(8):
            x, y = pos[0] + 0.5 + math.cos(ang + k) * r, pos[1] + 0.5 + math.sin(ang + k) * r
            if game.over.is_walk(int(x), int(y)):
                return "overworld", x, y
        return "overworld", pos[0] + 0.5, pos[1] + 0.5
    if kind == "m":
        for m in game.over.markers:
            if m.data.get("npc") == key:
                return "overworld", m.x + 0.5, m.y + 0.5
    return None


def place_all(game) -> None:
    for st in game.npcs.values():
        _retarget(game, st, force=True)
        if st.dest:
            st.area, st.x, st.y = st.dest


def _retarget(game, st: NpcState, force: bool = False) -> None:
    place = place_for(st.defn, game.clock)
    if place != st.place or force:
        st.place = place
        st.dest = resolve(game, st, place, game.clock)
        st.path = None


def update(game, dt: float, teleport: bool = False) -> None:
    P = game.p
    for st in game.npcs.values():
        _retarget(game, st)
        dest = st.dest
        if dest is None:
            continue
        darea, dx, dy = dest
        visible = st.area == game.area
        far = visible and math.hypot(st.x - P.x, st.y - P.y) > TELEPORT_DIST
        if teleport or (not visible and not (darea == game.area)) or far:
            if (st.area, round(st.x, 1), round(st.y, 1)) != (darea, round(dx, 1), round(dy, 1)):
                st.area, st.x, st.y = darea, dx, dy
            st.moving = False
            continue
        if game.talking == st.id:
            st.moving = False
            continue
        if st.area == darea:
            if math.hypot(dx - st.x, dy - st.y) < 0.35:
                st.moving = False
                _face_player(game, st)
                continue
            _walk_to(game, st, dx, dy, dt)
        else:
            _transit(game, st, darea, dt)


def _face_player(game, st: NpcState) -> None:
    if st.area == game.area and not st.sleeping:
        d = math.hypot(game.p.x - st.x, game.p.y - st.y)
        if d < 3.0:
            st.facing = math.degrees(math.atan2(game.p.y - st.y, game.p.x - st.x))


def _walk_to(game, st: NpcState, tx: float, ty: float, dt: float) -> None:
    wm = game.area_map(st.area)
    if st.area != game.area:
        st.x, st.y = tx, ty
        return
    st.repath -= dt
    direct = game.los((st.x, st.y), (tx, ty))
    if direct:
        st.path = None
        wx, wy = tx, ty
    else:
        if st.path is None or st.repath <= 0:
            st.path = game.path(st.area, (st.x, st.y), (tx, ty), 6000)
            st.repath = 3.0
            if not st.path:
                st.x, st.y = tx, ty
                return
        while st.path and math.hypot(st.path[0][0] - st.x, st.path[0][1] - st.y) < 0.4:
            st.path.pop(0)
        if not st.path:
            st.path = None
            return
        wx, wy = st.path[0]
    # Cheap separation keeps NPCs from stacking on one tile or in a doorway.
    sx = sy = 0.0
    for other in game.npcs.values():
        if other is st or other.area != st.area:
            continue
        ox, oy = st.x - other.x, st.y - other.y
        d0 = math.hypot(ox, oy)
        if 0.0 < d0 < 1.0:
            w = (1.0 - d0)
            sx += ox / d0 * w
            sy += oy / d0 * w
    for e in game.enemies:
        if e.dead or game.area != st.area:
            continue
        ox, oy = st.x - e.x, st.y - e.y
        d0 = math.hypot(ox, oy)
        if 0.0 < d0 < 1.0:
            w = (1.0 - d0)
            sx += ox / d0 * w
            sy += oy / d0 * w
    if sx or sy:
        n = math.hypot(sx, sy)
        wx += sx / n * 0.35
        wy += sy / n * 0.35
    d = math.hypot(wx - st.x, wy - st.y) or 1.0
    sp = NPC_SPEED * (wm.speed_at(int(st.x), int(st.y)) or 1.0) * dt
    st.x, st.y, blocked = move(game.walkb(st.area), wm.W, wm.H, st.x, st.y, (wx - st.x) / d * sp, (wy - st.y) / d * sp, NPC_R)
    st.facing = math.degrees(math.atan2(wy - st.y, wx - st.x))
    st.moving = True
    st.phase += dt * 7
    if blocked and st.repath <= 0:
        st.path = None


def _transit(game, st: NpcState, darea: str, dt: float) -> None:
    """Walk to the door (inside) or to the building's front (outside), then change area."""
    if st.area.startswith("b:"):
        wm = game.area_map(st.area)
        ex = wm.exits["door"]
        tx, ty = ex[0] + 0.5, ex[1] - 0.2
        if math.hypot(tx - st.x, ty - st.y) < 0.6:
            b = game.building_of(st.area)
            st.area = "overworld"
            if b:
                st.x, st.y = b.front[0] + 0.5, b.front[1] + 0.5
            return
        _walk_to(game, st, tx, ty, dt)
    else:
        b = next((b for b in game.over.buildings if f"b:{b.id}" == darea), None)
        if b is None:
            st.area, st.x, st.y = game.dest_fallback(st) if hasattr(game, "dest_fallback") else (darea, st.x, st.y)
            return
        tx, ty = b.front[0] + 0.5, b.front[1] + 0.5
        if math.hypot(tx - st.x, ty - st.y) < 0.7:
            wm = game.area_map(darea)
            st.area = darea
            st.x, st.y = wm.start[0] + 0.5, wm.start[1] - 0.2
            return
        _walk_to(game, st, tx, ty, dt)


def to_dict(game) -> dict:
    return {k: {"a": s.area, "x": round(s.x, 2), "y": round(s.y, 2)} for k, s in game.npcs.items()}


def from_dict(game, raw: dict) -> None:
    for k, v in raw.items():
        s = game.npcs.get(k)
        if s:
            s.area, s.x, s.y = v["a"], float(v["x"]), float(v["y"])
            s.place = ""
    for s in game.npcs.values():
        _retarget(game, s, force=True)
        if s.dest and s.area not in (game.over.sites, ) and not raw:
            s.area, s.x, s.y = s.dest
