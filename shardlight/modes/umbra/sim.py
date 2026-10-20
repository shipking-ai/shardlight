"""The Gloaming Ward simulation: the player, doors, light, sound, hiding, items, objectives and checkpoints.

Pure logic.  ``Game.update(dt, Controls)`` advances one fixed step; the scene draws what it exposes.  Enemies live in
``enemies.py`` and the pacing director in ``director.py``; both talk to the game only through the public helpers
here (``los``, ``path``, ``light_at``, ``emit_noise``, ``events``).
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np

from ...core.ai import Noise
from ...core.nav import Grid, astar
from ...core.rng import Rng, derive_seed
from .catalog import Catalog
from .consts import (DOOR, FLOOR, HEALTH_MAX, NOISE, PLAYER_RADIUS, REACH, RUN, SNEAK, SPEED, STAMINA_MAX, STEP_LOUDNESS, STRIDE,
                     SURFACE_LOUDNESS, TILE, WALK, WALL)
from .levelgen import Level, generate
from .props import HIDE_RULES, PROP_DEFS

BAG_SLOTS = 8
FLASH_DRAIN = 100.0 / 150.0
LAMP_DRAIN = 100.0 / 240.0
FLASH_RANGE = 11.0 * TILE
FLASH_HALF = 22.0
LAMP_RADIUS = 3.6 * TILE
MATCH_TIME = 8.0
MATCH_RADIUS = 2.3 * TILE
SAVE_V = 1


@dataclass
class Controls:
    move: tuple[float, float] = (0.0, 0.0)
    run: bool = False
    sneak: bool = False
    interact: bool = False          # pressed
    use: bool = False               # pressed
    light: bool = False             # pressed (cycle flashlight / lamp / off)
    cycle: bool = False             # pressed (next item)
    aim: tuple[float, float] | None = None


@dataclass
class DoorState:
    id: int
    open: float = 0.0
    want: float = 0.0
    broken: bool = False
    bangs: int = 0
    locks: list = field(default_factory=list)
    gate: bool = False
    last_actor: str = ""

    @property
    def passable(self) -> bool:
        return self.broken or self.open >= 0.6


@dataclass
class Ward:
    x: float
    y: float
    t: float
    radius: float


@dataclass
class FloorItem:
    item: str
    x: float
    y: float
    count: int = 1


class Player:
    def __init__(self, x: float, y: float):
        self.x, self.y = x, y
        self.facing = 90.0
        self.stance = WALK
        self.stamina = STAMINA_MAX
        self.exhausted = 0.0
        self.hp = HEALTH_MAX
        self.bag: list[list] = []                    # [item_id, count] for non-pocket items
        self.pocket: dict[str, int] = {}             # keys and objective items
        self.sel = 0
        self.battery = 100.0
        self.oil = 40.0
        self.mode = "off"                            # off | flash | lamp
        self.match = 0.0
        self.hiding: int | None = None               # prop index
        self.hide_t = 0.0
        self.step_acc = 0.0
        self.busy = 0.0                              # seconds left in an action (searching, bandaging ...)
        self.busy_what = ""
        self.invuln = 0.0
        self.dead = False
        self.last_noise = 0.0
        self.footfalls = 0
        self.moved = False

    @property
    def cell(self) -> tuple[int, int]:
        return int(self.x // TILE), int(self.y // TILE)


class Game:
    def __init__(self, cat: Catalog, night: int, seed: int, difficulty: str = "standard", adapt: float = 1.0, journal: dict | None = None,
                 unlocks=lambda u: False):
        self.cat = cat
        self.night = night
        self.seed = seed
        self.difficulty = difficulty
        self.adapt = adapt
        self.has_unlock = unlocks
        self.rng = Rng(derive_seed(seed, "umbra-sim", night))
        self.lv: Level = generate(night, seed, cat)
        lv = self.lv
        self.nd = cat.night(night)
        self.time = 0.0
        self.events: list[tuple[str, dict]] = []         # consumed by the scene (sound, UI, hooks)
        self.hooks: list[tuple[str, dict]] = []          # cross-mode events
        self.journal = journal if journal is not None else {"notes": [], "facts": [], "relics": []}
        self.doors = [DoorState(d.id, locks=list(d.locks), gate=d.gate) for d in lv.doors]
        self.door_at: dict[tuple[int, int], int] = {c: d.id for d in lv.doors for c in d.cells}
        self.floor_items: list[FloorItem] = [FloorItem(it, (c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE, n) for it, c, n in lv.items_floor]
        self.props = lv.props
        self.prop_cell: dict[tuple[int, int], int] = {}
        for i, p in enumerate(self.props):
            for c in p.cells:
                self.prop_cell[c] = i
        self.wards: list[Ward] = []
        self.noise_log: list[Noise] = []
        self.obj = {"type": lv.objective["type"], "stage": 0, "fuses_in": 0, "generator_on": False, "power": False, "gate_open": False,
                    "crank_t": 0.0, "have_all": False, "done": False, "winch_t": 0.0, "archive_open": False}
        self.power_on = False
        sx, sy = lv.start
        self.p = Player((sx + 0.5) * TILE, (sy + 0.5) * TILE)
        start_inv = self.nd.get("start", {})
        for it, n in start_inv.items():
            self.add_item(it, int(n))
        self.p.battery, self.p.oil = 100.0, 60.0
        self.checkpoint: dict | None = None
        self.deaths = 0
        self.complete = False
        self.failed_reason = ""
        self.seen_rooms: set[int] = set()
        self.version = 0                               # bumps when doors/props change (renderer / nav caches)
        self._nav = {}
        self._light_cache: tuple | None = None
        self.hide_log = {"locker": 0, "bed": 0, "table": 0}
        self.stats = {"steps": 0, "runs": 0, "throws": 0, "hides": 0, "searches": 0, "doors": 0}
        # enemies and director
        from .director import Director
        from .enemies import make_enemy
        self.enemies = []
        self.director = Director(self)
        self._spawn_enemies(make_enemy)
        self.take_checkpoint("start")

    # ------------------------------------------------------------------ helpers
    def say(self, _ev: str, **kw) -> None:
        self.events.append((_ev, kw))

    def pop_events(self) -> list[tuple[str, dict]]:
        ev, self.events = self.events, []
        return ev

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        return int(x // TILE), int(y // TILE)

    def room_at(self, x: float, y: float):
        c = self.cell_of(x, y)
        return self.lv.room_of(c)

    def in_safe_room(self, x: float | None = None, y: float | None = None) -> bool:
        r = self.room_at(self.p.x if x is None else x, self.p.y if y is None else y)
        return bool(r and r.role == "safe")

    # ------------------------------------------------------------------ solidity, doors, line of sight
    def solid_cell(self, c: tuple[int, int], actor: str = "player") -> bool:
        x, y = c
        lv = self.lv
        if not (0 <= x < lv.w and 0 <= y < lv.h):
            return True
        g = lv.grid[y, x]
        if g == WALL or g == 0:
            return True
        if g == DOOR:
            d = self.doors[self.door_at[c]]
            return not d.passable
        i = self.prop_cell.get(c)
        if i is not None and PROP_DEFS[self.props[i].kind].solid:
            return True
        return False

    def opaque_cell(self, c: tuple[int, int]) -> bool:
        x, y = c
        lv = self.lv
        if not (0 <= x < lv.w and 0 <= y < lv.h):
            return True
        g = lv.grid[y, x]
        if g == WALL or g == 0:
            return True
        if g == DOOR:
            return self.doors[self.door_at[c]].open < 0.35 and not self.doors[self.door_at[c]].broken
        i = self.prop_cell.get(c)
        if i is not None:
            d = PROP_DEFS[self.props[i].kind]
            return d.solid and d.opaque
        return False

    def los(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        """Clear line between two pixel positions (walls, closed doors and tall props block it)."""
        x0, y0 = int(a[0] // TILE), int(a[1] // TILE)
        x1, y1 = int(b[0] // TILE), int(b[1] // TILE)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        first = True
        while True:
            if not first and (x0, y0) != (x1, y1) and self.opaque_cell((x0, y0)):
                return False
            first = False
            if x0 == x1 and y0 == y1:
                return True
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def occlusion(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        """Extra distance (px) sound loses between two points: walls muffle it, closed doors a little."""
        x0, y0 = int(a[0] // TILE), int(a[1] // TILE)
        x1, y1 = int(b[0] // TILE), int(b[1] // TILE)
        n = max(abs(x1 - x0), abs(y1 - y0))
        pen = 0.0
        seen = set()
        for i in range(1, n):
            c = (round(x0 + (x1 - x0) * i / n), round(y0 + (y1 - y0) * i / n))
            if c in seen:
                continue
            seen.add(c)
            g = self.lv.grid[c[1], c[0]] if 0 <= c[0] < self.lv.w and 0 <= c[1] < self.lv.h else WALL
            if g == WALL or g == 0:
                pen += 2.2 * TILE
            elif g == DOOR:
                d = self.doors[self.door_at[c]]
                pen += 0.4 * TILE if d.open >= 0.35 or d.broken else 1.6 * TILE
        return pen

    def nav_grid(self, can_open: bool, breaker: bool = False, enemy: bool = True, keys: frozenset | None = None) -> Grid:
        key = (self.version, can_open, breaker, enemy, keys)
        g = self._nav.get(key)
        if g is None:
            if len(self._nav) > 6:
                self._nav.clear()
            g = Grid(self.lv.w, self.lv.h, False)
            for y in range(self.lv.h):
                for x in range(self.lv.w):
                    gv = self.lv.grid[y, x]
                    ok = gv == FLOOR
                    if gv == DOOR:
                        d = self.doors[self.door_at[(x, y)]]
                        if d.passable:
                            ok = True
                        elif can_open and not d.locks and not d.gate:
                            ok = True
                        elif breaker and not d.gate:
                            ok = True
                        elif keys is not None and d.locks and not d.gate and all(k in keys for k in d.locks):
                            ok = True
                    if ok:
                        i = self.prop_cell.get((x, y))
                        if i is not None and PROP_DEFS[self.props[i].kind].solid:
                            ok = False
                    g.blocked[y][x] = 0 if ok else 1
            for r in (self.lv.rooms if enemy else []):
                if r.role == "safe":                            # enemies never enter the safe rooms (or stand in their doors)
                    for (cx, cy) in r.cells():
                        g.blocked[cy][cx] = 1
                    for did in r.doors:
                        for (cx, cy) in self.lv.doors[did].cells:
                            g.blocked[cy][cx] = 1
            self._nav[key] = g
        return g

    def path(self, a: tuple[float, float], b: tuple[float, float], can_open: bool = True, max_nodes: int = 6000, breaker: bool = False, enemy: bool = True,
             keys: frozenset | None = None):
        """Cell path (list of cells) from pixel a to pixel b, or None.  ``enemy`` paths avoid the safe rooms;
        ``keys`` lets locked doors count as open for someone holding those keys."""
        g = self.nav_grid(can_open, breaker, enemy, keys)
        s = g.nearest_walkable(self.cell_of(*a), 3)
        e = g.nearest_walkable(self.cell_of(*b), 3)
        if s is None or e is None:
            return None
        return astar(g, s, e, diagonal=False, max_nodes=max_nodes)

    def touch(self) -> None:
        self.version += 1

    # ------------------------------------------------------------------ light
    def lamp_cells(self) -> list[tuple[int, int]]:
        return self.lv.lamps if (self.power_on or self.night != 1) else [c for c in self.lv.lamps if self.lv.room_of(c) and self.lv.room_of(c).role == "safe"]

    def light_at(self, x: float, y: float) -> float:
        """Illumination 0..1 of a point: the lit cone, lamps, wall lamps, windows, wards."""
        key = (round(x), round(y), self.version, int(self.time * 10), self.p.mode, int(self.p.match > 0))
        if self._light_cache and self._light_cache[0] == key:
            return self._light_cache[1]
        v = 0.02
        for (cx, cy) in self.lamp_cells():
            px, py = (cx + 0.5) * TILE, (cy + 0.5) * TILE
            d = math.hypot(x - px, y - py)
            if d < 6.0 * TILE and self.los((px, py), (x, y)):
                v = max(v, 0.75 * (1 - d / (6.0 * TILE)))
        for (cx, cy) in self.lv.windows:
            px, py = (cx + 0.5) * TILE, (cy + 0.5) * TILE
            d = math.hypot(x - px, y - py)
            if d < 4.5 * TILE and self.los((px, py), (x, y)):
                v = max(v, 0.28 * (1 - d / (4.5 * TILE)))
        v = max(v, self.player_light(x, y))
        for w in self.wards:
            d = math.hypot(x - w.x, y - w.y)
            if d < w.radius * TILE * 1.2:
                v = max(v, 0.8 * (1 - d / (w.radius * TILE * 1.2)))
        self._light_cache = (key, v)
        return v

    def player_light(self, x: float, y: float) -> float:
        p = self.p
        if p.dead or p.hiding is not None:
            return 0.0
        d = math.hypot(x - p.x, y - p.y)
        best = 0.0
        if p.match > 0 and d < MATCH_RADIUS and self.los((p.x, p.y), (x, y)):
            best = max(best, 0.7 * (1 - d / MATCH_RADIUS))
        if p.mode == "lamp" and p.oil > 0 and d < LAMP_RADIUS and self.los((p.x, p.y), (x, y)):
            best = max(best, 0.85 * (1 - d / LAMP_RADIUS))
        if p.mode == "flash" and p.battery > 0 and 0 < d < FLASH_RANGE and self.in_flash_cone(x, y) and self.los((p.x, p.y), (x, y)):
            best = max(best, 1.0 * (1 - d / FLASH_RANGE) ** 0.6)
        return best

    def in_flash_cone(self, x: float, y: float) -> bool:
        p = self.p
        if p.mode != "flash" or p.battery <= 0:
            return False
        ang = math.degrees(math.atan2(y - p.y, x - p.x))
        diff = abs((ang - p.facing + 180) % 360 - 180)
        return diff <= FLASH_HALF

    def player_lit(self) -> float:
        """How visible the player is to a watcher (their own lights and the lamps around them)."""
        p = self.p
        v = 0.02
        for (cx, cy) in self.lamp_cells():
            px, py = (cx + 0.5) * TILE, (cy + 0.5) * TILE
            d = math.hypot(p.x - px, p.y - py)
            if d < 6.0 * TILE and self.los((px, py), (p.x, p.y)):
                v = max(v, 0.75 * (1 - d / (6.0 * TILE)))
        if p.hiding is not None:
            return 0.0
        if p.mode == "flash" and p.battery > 0:
            v = max(v, 0.9)
        if p.mode == "lamp" and p.oil > 0:
            v = max(v, 0.7)
        if p.match > 0:
            v = max(v, 0.6)
        return v

    def in_ward(self, x: float, y: float) -> bool:
        return any(math.hypot(x - w.x, y - w.y) < w.radius * TILE for w in self.wards)

    # ------------------------------------------------------------------ noise
    def emit_noise(self, kind: str, x: float, y: float, loud_tiles: float | None = None, source: str = "player") -> None:
        loud = NOISE.get(kind, 3.0) if loud_tiles is None else loud_tiles
        n = Noise((x, y), loud * TILE, kind, source, self.time)
        self.noise_log.append(n)
        if len(self.noise_log) > 80:
            del self.noise_log[:40]
        self.say("noise", kind=kind, x=x, y=y, loud=loud, source=source)
        for e in self.enemies:
            e.hear(n)
        if source == "player":
            self.p.last_noise = max(self.p.last_noise, loud)

    # ------------------------------------------------------------------ inventory
    def item_def(self, iid: str) -> dict:
        return self.cat.item(iid)

    def bag_count(self, iid: str) -> int:
        return sum(s[1] for s in self.p.bag if s[0] == iid) + self.p.pocket.get(iid, 0)

    def add_item(self, iid: str, n: int = 1) -> int:
        """Add; returns how many did not fit (bag has BAG_SLOTS slots)."""
        d = self.item_def(iid)
        if d.get("pocket"):
            self.p.pocket[iid] = self.p.pocket.get(iid, 0) + n
            return 0
        stack = int(d.get("stack", 1))
        for s in self.p.bag:
            if s[0] == iid and s[1] < stack:
                take = min(n, stack - s[1])
                s[1] += take
                n -= take
        while n > 0 and len(self.p.bag) < BAG_SLOTS:
            take = min(n, stack)
            self.p.bag.append([iid, take])
            n -= take
        return n

    def remove_item(self, iid: str, n: int = 1) -> bool:
        if self.bag_count(iid) < n:
            return False
        if self.p.pocket.get(iid, 0) >= n:
            self.p.pocket[iid] -= n
            if self.p.pocket[iid] == 0:
                del self.p.pocket[iid]
            return True
        for s in list(self.p.bag):
            if s[0] == iid:
                take = min(n, s[1])
                s[1] -= take
                n -= take
                if s[1] == 0:
                    self.p.bag.remove(s)
                if n == 0:
                    break
        self.p.sel = min(self.p.sel, max(0, len(self.p.bag) - 1))
        return True

    def selected(self) -> str | None:
        if not self.p.bag:
            return None
        self.p.sel %= len(self.p.bag)
        return self.p.bag[self.p.sel][0]

    def combine(self, a: str, b: str) -> bool:
        r = self.cat.find_recipe(a, b)
        if not r:
            return False
        if a == b:
            if self.bag_count(a) < 2:
                return False
        elif self.bag_count(a) < 1 or self.bag_count(b) < 1:
            return False
        self.remove_item(r["a"], 1)
        self.remove_item(r["b"], 1)
        left = self.add_item(r["out"], int(r.get("count", 1)))
        if left:
            self.floor_items.append(FloorItem(r["out"], self.p.x, self.p.y, left))
        self.say("combined", out=r["out"])
        return True

    # ------------------------------------------------------------------ checkpoints
    def snapshot(self) -> dict:
        p = self.p
        return {"time": self.time,
                "player": {"x": p.x, "y": p.y, "hp": p.hp, "bag": copy.deepcopy(p.bag), "pocket": dict(p.pocket), "battery": p.battery, "oil": p.oil,
                           "mode": p.mode, "facing": p.facing},
                "floor": [[f.item, f.x, f.y, f.count] for f in self.floor_items],
                "props": [[pr.searched, copy.deepcopy(pr.contents), dict(pr.state)] for pr in self.props],
                "doors": [[d.open, d.want, d.broken, d.bangs, list(d.locks), d.gate] for d in self.doors],
                "obj": dict(self.obj), "power": self.power_on, "wards": [[w.x, w.y, w.t, w.radius] for w in self.wards],
                "hide_log": dict(self.hide_log), "stats": dict(self.stats)}

    def take_checkpoint(self, why: str = "") -> None:
        self.checkpoint = self.snapshot()
        self.checkpoint["why"] = why

    def restore(self, s: dict) -> None:
        p = self.p
        pd = s["player"]
        p.x, p.y, p.hp, p.battery, p.oil, p.mode, p.facing = pd["x"], pd["y"], pd["hp"], pd["battery"], pd["oil"], pd["mode"], pd["facing"]
        p.bag = copy.deepcopy(pd["bag"])
        p.pocket = dict(pd["pocket"])
        p.hiding, p.dead, p.busy, p.match, p.invuln = None, False, 0.0, 0.0, 1.5
        p.stamina = STAMINA_MAX
        self.floor_items = [FloorItem(i, x, y, n) for i, x, y, n in s["floor"]]
        for pr, (searched, contents, state) in zip(self.props, s["props"]):
            pr.searched, pr.contents, pr.state = searched, copy.deepcopy(contents), dict(state)
        for d, (o, w, br, bangs, locks, gate) in zip(self.doors, s["doors"]):
            d.open, d.want, d.broken, d.bangs, d.locks, d.gate = o, w, br, bangs, list(locks), gate
        self.obj = dict(s["obj"])
        self.power_on = s["power"]
        self.wards = [Ward(*w) for w in s["wards"]]
        self.hide_log = dict(s.get("hide_log", self.hide_log))
        self.touch()

    def die(self, by: str) -> None:
        p = self.p
        if p.dead:
            return
        p.dead = True
        p.hiding = None
        self.deaths += 1
        self.say("died", by=by)
        self.director.on_death()

    def respawn(self) -> None:
        self.restore(self.checkpoint)
        for e in self.enemies:
            e.reset()
        self.director.reset()
        self.say("respawn")

    # ------------------------------------------------------------------ enemies
    def _spawn_enemies(self, make_enemy) -> None:
        lv = self.lv
        safe_ids = set(lv.safe_rooms)
        rooms = [r for r in lv.rooms if not r.hall and r.id not in safe_ids]
        cx, cy = lv.rooms[lv.safe_rooms[0]].center if lv.safe_rooms else lv.start
        far = sorted(rooms, key=lambda r: -(abs(r.center[0] - cx) + abs(r.center[1] - cy)))
        for i, kind in enumerate(lv.enemies):
            room = far[(i * 3) % len(far)]
            cell = self._free_cell(room)
            self.enemies.append(make_enemy(self, kind, i, (cell[0] + 0.5) * TILE, (cell[1] + 0.5) * TILE))

    def _free_cell(self, room) -> tuple[int, int]:
        cells = [c for c in room.cells() if not self.solid_cell(c)]
        return cells[len(cells) // 2] if cells else room.center

    # ------------------------------------------------------------------ main update
    def update(self, dt: float, ctl: Controls) -> None:
        p = self.p
        self.time += dt
        if self.complete:
            return
        if p.dead:
            return
        p.invuln = max(0.0, p.invuln - dt)
        self._lights(dt, ctl)
        self._doors(dt)
        if p.busy > 0:
            p.busy -= dt
            if p.busy <= 0:
                self._finish_action()
        elif p.hiding is not None:
            self._hiding(dt, ctl)
        else:
            self._move(dt, ctl)
            if ctl.interact:
                self._interact()
            elif ctl.use:
                self.use_selected()
        if ctl.cycle and p.bag:
            p.sel = (p.sel + 1) % len(p.bag)
        # wards and long-running objective actions
        for w in list(self.wards):
            w.t -= dt
            if w.t <= 0:
                self.wards.remove(w)
        self._objective_tick(dt)
        for e in self.enemies:
            e.update(dt)
        self.director.update(dt)
        # entering a safe room: checkpoint and progress
        r = self.room_at(p.x, p.y)
        if r is not None and r.role == "safe" and r.id not in self.seen_rooms:
            self.seen_rooms.add(r.id)
            if self.time > 5:
                self.take_checkpoint("safe")
                self.say("checkpoint")
        self._check_complete()
        if p.hp <= 0:
            self.die("wounds")

    # ------------------------------------------------------------------ lights
    def _lights(self, dt: float, ctl: Controls) -> None:
        p = self.p
        if p.match > 0:
            p.match = max(0.0, p.match - dt)
        if p.mode == "flash":
            p.battery = max(0.0, p.battery - FLASH_DRAIN * dt)
            if p.battery <= 0:
                p.mode = "off"
                self.say("light_died", which="flash")
        elif p.mode == "lamp":
            p.oil = max(0.0, p.oil - LAMP_DRAIN * dt)
            if p.oil <= 0:
                p.mode = "off"
                self.say("light_died", which="lamp")
        if ctl.light and p.hiding is None:
            order = ["off", "flash", "lamp"]
            for _ in range(3):
                p.mode = order[(order.index(p.mode) + 1) % 3]
                if p.mode == "flash" and p.battery <= 0 or p.mode == "lamp" and p.oil <= 0:
                    continue
                break
            self.emit_noise("flashlight", p.x, p.y)
            self.say("light_toggle", mode=p.mode)

    # ------------------------------------------------------------------ movement
    def _blocked_at(self, x: float, y: float) -> bool:
        r = PLAYER_RADIUS
        for (ox, oy) in ((-r, -r), (r, -r), (-r, r), (r, r)):
            if self.solid_cell(self.cell_of(x + ox, y + oy)):
                return True
        return False

    def _move(self, dt: float, ctl: Controls) -> None:
        p = self.p
        mx, my = ctl.move
        mag = math.hypot(mx, my)
        p.moved = False
        stance = WALK
        if ctl.sneak:
            stance = SNEAK
        elif ctl.run and p.stamina > 0 and p.exhausted <= 0:
            stance = RUN
        p.stance = stance
        if mag > 0.15:
            mx, my = mx / mag, my / mag
            speed = SPEED[stance] * min(1.0, mag)
            nx, ny = p.x + mx * speed * dt, p.y + my * speed * dt
            moved = False
            if not self._blocked_at(nx, p.y):
                p.x = nx
                moved = True
            if not self._blocked_at(p.x, ny):
                p.y = ny
                moved = True
            if moved:
                p.moved = True
                p.facing = math.degrees(math.atan2(my, mx))
                if ctl.aim is None:
                    pass
                p.step_acc += speed * dt
                if p.step_acc >= STRIDE[stance]:
                    p.step_acc -= STRIDE[stance]
                    self._footstep(stance)
        if ctl.aim is not None and math.hypot(*ctl.aim) > 0.3:
            p.facing = math.degrees(math.atan2(ctl.aim[1], ctl.aim[0]))
        if p.stance == RUN and p.moved:
            p.stamina = max(0.0, p.stamina - dt)
            if p.stamina <= 0:
                p.exhausted = 2.5
                self.emit_noise("pant", p.x, p.y)
                self.say("gasp")
        else:
            p.stamina = min(STAMINA_MAX, p.stamina + dt * 0.7)
        p.exhausted = max(0.0, p.exhausted - dt)

    def _footstep(self, stance: str) -> None:
        p = self.p
        c = p.cell
        if not (0 <= c[0] < self.lv.w and 0 <= c[1] < self.lv.h):
            return
        surf = int(self.lv.surface[c[1], c[0]])
        loud = STEP_LOUDNESS[stance] * SURFACE_LOUDNESS[surf]
        p.footfalls += 1
        self.stats["steps"] += 1
        if stance == RUN:
            self.stats["runs"] += 1
        self.say("step", surface=surf, stance=stance)
        self.emit_noise("step", p.x, p.y, loud)
        self.director.player_model.record("run" if stance == RUN else "sneak" if stance == SNEAK else "walk", self.time)

    # ------------------------------------------------------------------ doors
    def nearest_door(self, reach: float = REACH) -> DoorState | None:
        p = self.p
        best, bd = None, reach
        for d in self.lv.doors:
            for (x, y) in d.cells:
                dist = math.hypot((x + 0.5) * TILE - p.x, (y + 0.5) * TILE - p.y)
                if dist < bd:
                    best, bd = self.doors[d.id], dist
        return best

    def _actor_in_door(self, d: DoorState) -> bool:
        cells = set(self.lv.doors[d.id].cells)
        if self.cell_of(self.p.x, self.p.y) in cells:
            return True
        return any(self.cell_of(e.x, e.y) in cells for e in self.enemies)

    def _doors(self, dt: float) -> None:
        for d in self.doors:
            if d.open != d.want:
                step = dt * 3.0
                if d.want > d.open:
                    d.open = min(d.want, d.open + step)
                else:
                    if self._actor_in_door(d):
                        d.want = 1.0
                    else:
                        d.open = max(d.want, d.open - step)
                self.version += 1 if abs(d.open - round(d.open)) < 0.05 else 0

    def set_door(self, d: DoorState, open_: bool, sneak: bool, who: str) -> bool:
        dd = self.lv.doors[d.id]
        if open_ and (d.locks or d.gate) and not d.broken:
            return False
        if d.broken:
            return False
        if bool(d.want) == open_:
            return True
        d.want = 1.0 if open_ else 0.0
        d.last_actor = who
        kind = ("door_open" if open_ else "door_close") + ("_sneak" if sneak else "")
        cx, cy = dd.cells[0]
        self.emit_noise(kind, (cx + 0.5) * TILE, (cy + 0.5) * TILE, source=who)
        self.say("door", open=open_, who=who, id=d.id)
        self.stats["doors"] += 1
        self.touch()
        return True

    def try_unlock(self, d: DoorState) -> bool:
        if not d.locks:
            return True
        if all(self.p.pocket.get(k, 0) > 0 for k in d.locks):
            d.locks = []
            dd = self.lv.doors[d.id]
            self.emit_noise("unlock", (dd.cells[0][0] + 0.5) * TILE, (dd.cells[0][1] + 0.5) * TILE)
            self.say("unlocked", id=d.id)
            self.touch()
            if self.obj["type"] == "keys":
                self.obj["archive_open"] = True
            return True
        missing = [k for k in d.locks if self.p.pocket.get(k, 0) <= 0]
        self.say("locked", id=d.id, missing=[self.item_def(k)["name"] for k in missing])
        return False

    # ------------------------------------------------------------------ interaction
    def _pickup(self, fi) -> None:
        left = self.add_item(fi.item, fi.count)
        if left < fi.count:
            self.say("pickup", item=fi.item)
            self.emit_noise("pickup", fi.x, fi.y)
            self._after_pickup(fi.item)
        if left == 0:
            self.floor_items.remove(fi)
        else:
            fi.count = left
            self.say("bag_full")

    def _interact(self) -> None:
        p = self.p
        # something lying right at your feet comes first; then objective props, containers, notes and hiding places; then doors
        fi = self._nearest_floor_item()
        if fi is not None and math.hypot(fi.x - p.x, fi.y - p.y) < REACH * 0.6:
            self._pickup(fi)
            return
        target = self._nearest_prop()
        if target is not None:
            i, pr = target
            k = pr.kind
            if k in ("fuse_box", "generator", "lever", "winch", "clock"):
                if self._use_objective_prop(i, pr):
                    return
            if PROP_DEFS[k].reads and pr.note:
                self.read_note(pr.note)
                return
            if PROP_DEFS[k].container and not pr.searched:
                p.busy, p.busy_what = 0.8, f"search:{i}"
                self.say("search", i=i)
                return
            h = PROP_DEFS[k].hide
            if h:
                self.enter_hide(i)
                return
        if fi is not None:
            self._pickup(fi)
            return
        d = self.nearest_door()
        if d is not None:
            if d.locks or d.gate:
                if d.gate:
                    self.say("gate_stuck")
                else:
                    self.try_unlock(d)
                    if not d.locks:
                        self.set_door(d, True, p.stance == SNEAK, "player")
            else:
                self.set_door(d, d.want < 0.5, p.stance == SNEAK, "player")
            return

    def context(self) -> str | None:
        """Label of what the interact button would do right now (for the on-screen prompt)."""
        p = self.p
        if p.dead or p.busy > 0:
            return None
        if p.hiding is not None:
            return "Leave hiding place"
        fi0 = self._nearest_floor_item()
        if fi0 is not None and math.hypot(fi0.x - p.x, fi0.y - p.y) < REACH * 0.6:
            return f"Take {self.item_def(fi0.item)['name']}"
        t = self._nearest_prop()
        if t is not None:
            i, pr = t
            k = pr.kind
            if k == "fuse_box" and self.obj["type"] == "power":
                return "Fit fuse" if self.bag_count("fuse") and not pr.state.get("fused") else "Fuse socket"
            if k == "generator" and self.obj["type"] == "power":
                return "Start generator" if not self.obj["generator_on"] else "Generator"
            if k == "lever" and self.obj["type"] == "power":
                return "Throw lever"
            if k == "winch" and self.obj["type"] == "escape":
                return "Turn winch" if not self.obj["gate_open"] else "Winch"
            if k == "clock":
                return "Take the clock" if not pr.state.get("taken") else "Stopped clock"
            if PROP_DEFS[k].reads and pr.note:
                return "Read"
            if PROP_DEFS[k].container and not pr.searched:
                return f"Search {PROP_DEFS[k].name.lower()}"
            h = PROP_DEFS[k].hide
            if h:
                return HIDE_RULES[h]["label"]
        fi = self._nearest_floor_item()
        if fi is not None:
            return f"Take {self.item_def(fi.item)['name']}"
        d = self.nearest_door()
        if d is not None:
            if d.gate:
                return "Gate is shut"
            if d.locks:
                missing = [self.item_def(k)["name"] for k in d.locks if self.p.pocket.get(k, 0) <= 0]
                return "Unlock door" if not missing else "Locked: " + ", ".join(missing)
            return "Close door" if d.want >= 0.5 else "Open door"
        return None

    def _nearest_prop(self):
        """Closest interactable prop; near-ties favour objective props, then unsearched containers, notes, hiding places."""
        p = self.p
        best, bk = None, None
        for i, pr in enumerate(self.props):
            d = PROP_DEFS[pr.kind]
            if d.deco:
                continue
            objective = pr.kind in ("fuse_box", "generator", "lever", "winch", "clock")
            if not (d.container or d.hide or d.reads or objective):
                continue
            prio = 0 if objective else 1 if (d.container and not pr.searched) else 2 if (d.reads and pr.note) else 3
            for (x, y) in pr.cells:
                dist = math.hypot((x + 0.5) * TILE - p.x, (y + 0.5) * TILE - p.y)
                if dist < REACH:
                    key = (prio if objective else 1, round(dist / 4.0), prio, dist)          # objective props always win in reach
                    if bk is None or key < bk:
                        best, bk = (i, pr), key
        return best

    def _nearest_floor_item(self):
        p = self.p
        best, bd = None, REACH * 0.9
        for f in self.floor_items:
            d = math.hypot(f.x - p.x, f.y - p.y)
            if d < bd:
                best, bd = f, d
        return best

    def read_note(self, nid: str) -> None:
        n = self.cat.note(nid)
        if n is None:
            return
        if nid not in self.journal["notes"]:
            self.journal["notes"].append(nid)
            self.say("note_new", id=nid)
        self.say("read", id=nid)

    def _after_pickup(self, iid: str) -> None:
        self.say("got", item=iid)

    def _finish_action(self) -> None:
        p = self.p
        what = p.busy_what
        p.busy_what = ""
        if what.startswith("search:"):
            i = int(what.split(":")[1])
            pr = self.props[i]
            pr.searched = True
            self.stats["searches"] += 1
            self.emit_noise("drawer" if pr.kind not in ("locker", "wardrobe") else "locker", (pr.cells[0][0] + 0.5) * TILE, (pr.cells[0][1] + 0.5) * TILE)
            found = []
            for it, n in pr.contents:
                left = self.add_item(it, n)
                if left < n:
                    found.append(it)
                if left:
                    self.floor_items.append(FloorItem(it, (pr.cells[0][0] + 0.5) * TILE, (pr.cells[0][1] + 1.5) * TILE, left))
            pr.contents = []
            self.say("searched", i=i, found=found)
            for it in found:
                self._after_pickup(it)
            self.touch()
        elif what == "bandage":
            if self.remove_item("bandage"):
                p.hp = min(HEALTH_MAX, p.hp + 1)
                self.say("healed")
        elif what.startswith("light:"):
            pass

    # ------------------------------------------------------------------ hiding
    def enter_hide(self, i: int) -> None:
        pr = self.props[i]
        kind = PROP_DEFS[pr.kind].hide
        rules = HIDE_RULES[kind]
        p = self.p
        p.hiding = i
        p.hide_t = 0.0
        p.mode = "off"
        p.x, p.y = (pr.cells[0][0] + 0.5) * TILE, (pr.cells[0][1] + 0.5) * TILE
        self.hide_log[kind] += 1
        self.stats["hides"] += 1
        self.director.player_model.record("hide_" + kind, self.time, 1.0)
        self.emit_noise("drawer", p.x, p.y, rules["noise"])
        self.say("hide", kind=kind, i=i)

    def _hiding(self, dt: float, ctl: Controls) -> None:
        p = self.p
        p.hide_t += dt
        if p.hide_t > 3.5 and int(p.hide_t * 2) % 5 == 0 and self.rng.random() < dt * 0.6:
            self.emit_noise("breath", p.x, p.y)
        if ctl.interact and p.hide_t > 0.5:
            self.leave_hide()

    def leave_hide(self) -> None:
        p = self.p
        if p.hiding is None:
            return
        pr = self.props[p.hiding]
        kind = PROP_DEFS[pr.kind].hide
        # step out to a free neighbouring cell
        for (x, y) in pr.cells:
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                c = (x + dx, y + dy)
                if not self.solid_cell(c) and c not in pr.cells:
                    p.x, p.y = (c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE
                    p.hiding = None
                    self.emit_noise("drawer", p.x, p.y, HIDE_RULES[kind]["noise"] * 0.6)
                    self.say("unhide")
                    return
        p.hiding = None

    # ------------------------------------------------------------------ item use
    def use_selected(self) -> None:
        p = self.p
        it = self.selected()
        if it is None:
            return
        d = self.item_def(it)
        kind = d.get("kind")
        use = d.get("use", {})
        if "battery" in use:
            if p.battery >= 99:
                self.say("full", what="flash")
                return
            self.remove_item(it)
            p.battery = min(100.0, p.battery + use["battery"])
            self.emit_noise("lamp_refill", p.x, p.y)
            self.say("recharged")
        elif "oil" in use:
            if p.oil >= 99:
                self.say("full", what="lamp")
                return
            self.remove_item(it)
            p.oil = min(100.0, p.oil + use["oil"])
            self.emit_noise("lamp_refill", p.x, p.y)
            self.say("refilled")
        elif "heal" in use:
            if p.hp >= HEALTH_MAX:
                self.say("full", what="health")
                return
            p.busy, p.busy_what = 1.2, "bandage"
            self.emit_noise("bandage", p.x, p.y)
        elif it == "matches":
            self.remove_item("matches")
            p.match = MATCH_TIME
            self.emit_noise("match", p.x, p.y)
            self.say("match")
        elif kind == "throwable":
            self.throw(it)
        elif kind == "ward":
            self.remove_item(it)
            self.wards.append(Ward(p.x, p.y, d["use"]["ward_seconds"], d["use"]["ward_radius"]))
            self.emit_noise("ward_hum", p.x, p.y)
            self.say("ward")

    def throw(self, it: str) -> None:
        p = self.p
        d = self.item_def(it)
        th = d.get("throw", {})
        rng_t = float(th.get("range", 8)) * TILE
        a = math.radians(p.facing)
        x, y = p.x, p.y
        step = 3.0
        dist = 0.0
        while dist < rng_t:
            nx, ny = x + math.cos(a) * step, y + math.sin(a) * step
            if self.opaque_cell(self.cell_of(nx, ny)) or self.solid_cell(self.cell_of(nx, ny)):
                break
            x, y = nx, ny
            dist += step
        self.remove_item(it)
        self.stats["throws"] += 1
        self.director.player_model.record("throw", self.time)
        breaks = th.get("breaks", 0)
        self.emit_noise("thrown_default", x, y, float(th.get("noise", 5)))
        self.say("thrown", item=it, x=x, y=y, broke=bool(breaks))
        if not breaks:
            self.floor_items.append(FloorItem(it, x, y, 1))

    # ------------------------------------------------------------------ objectives
    def _use_objective_prop(self, i: int, pr) -> bool:
        p, o = self.p, self.obj
        k = pr.kind
        if k == "fuse_box" and o["type"] == "power":
            if pr.state.get("fused"):
                self.say("info", text="The fuse is seated.")
                return True
            if self.bag_count("fuse") > 0:
                self.remove_item("fuse")
                pr.state["fused"] = True
                o["fuses_in"] += 1
                self.emit_noise("fuse", (pr.cells[0][0] + 0.5) * TILE, (pr.cells[0][1] + 0.5) * TILE)
                self.say("fuse_in", n=o["fuses_in"])
                return True
            self.say("info", text="An empty fuse socket.")
            return True
        if k == "generator" and o["type"] == "power":
            if o["fuses_in"] < self.lv.objective.get("fuses", 2):
                self.say("info", text="It needs both fuses before it will turn over.")
                return True
            if not o["generator_on"]:
                o["generator_on"] = True
                o["gen_t"] = 8.0
                self.emit_noise("generator", (pr.cells[0][0] + 1) * TILE, (pr.cells[0][1] + 1) * TILE)
                self.say("generator_on")
                self.director.force_peak("generator")
            return True
        if k == "lever" and o["type"] == "power":
            if not o["generator_on"]:
                self.say("info", text="The lever is dead without the generator.")
            elif not o["power"]:
                o["power"] = True
                self.power_on = True
                self.emit_noise("clock", (pr.cells[0][0] + 0.5) * TILE, (pr.cells[0][1] + 0.5) * TILE, 8.0)
                self.say("power_on")
                self.touch()
            return True
        if k == "winch" and o["type"] == "escape":
            if o["gate_open"]:
                self.say("info", text="The gate is already open.")
            elif self.bag_count("crank") > 0 and self.bag_count("gate_wheel") > 0:
                if o["winch_t"] <= 0:
                    o["winch_t"] = 7.0
                    p.busy, p.busy_what = 7.0, "winch"
                    self.emit_noise("crank", (pr.cells[0][0] + 0.5) * TILE, (pr.cells[0][1] + 0.5) * TILE)
                    self.say("winch_start")
                    self.director.force_peak("winch")
            else:
                self.say("info", text="The winch is missing " + (" and ".join(n for n, it in (("its crank", "crank"), ("its wheel", "gate_wheel")) if self.bag_count(it) == 0)) + ".")
            return True
        if k == "clock":
            if not pr.state.get("taken"):
                pr.state["taken"] = True
                if "stopped_clock" not in self.journal["relics"]:
                    self.journal["relics"].append("stopped_clock")
                self.hooks.append(("umbra.relic_found", {"relic": "stopped_clock"}))
                self.add_item("stopped_clock")
                self.say("relic")
                self.say("pickup", item="stopped_clock")
            else:
                self.say("info", text="The clock is stopped. It would like to start again.")
            return True
        return False

    def _objective_tick(self, dt: float) -> None:
        o = self.obj
        if o["type"] == "power" and o.get("generator_on") and o.get("gen_t", 0) > 0:
            o["gen_t"] -= dt
        p = self.p
        if o["type"] == "escape" and o["winch_t"] > 0:
            o["winch_t"] -= dt
            # the winch only turns while the player stays at it
            if p.busy <= 0 and o["winch_t"] > 0:
                o["winch_t"] = 0.0
                self.say("info", text="You let go of the crank.")
            elif o["winch_t"] <= 0:
                o["gate_open"] = True
                self.remove_item("crank")
                self.remove_item("gate_wheel")
                for d in self.doors:
                    if d.gate:
                        d.gate = False
                        d.want = 1.0
                self.touch()
                self.say("gate_open")
        if o["type"] == "keys":
            o["have_all"] = self.bag_count("cellar_key") > 0

    def objective_text(self) -> str:
        o = self.obj
        if o["done"]:
            return "The night is over."
        if o["type"] == "power":
            if not o["power"]:
                if o["fuses_in"] < self.lv.objective.get("fuses", 2):
                    return f"Find fuses for the generator ({o['fuses_in']}/{self.lv.objective.get('fuses', 2)} fitted)"
                if not o["generator_on"]:
                    return "Start the generator"
                return "Throw the lever"
            return "Return to the Linen Room"
        if o["type"] == "keys":
            if not o["have_all"]:
                got = sum(1 for k in ("brass_key", "bone_key", "iron_key") if self.bag_count(k) > 0) if not o["archive_open"] else 3
                if o["archive_open"]:
                    return "Take the cellar key from the Archive"
                return f"Gather the three keys ({got}/3), open the Archive"
            return "Return to the Linen Room"
        if not o["gate_open"]:
            have = sum(1 for k in ("crank", "gate_wheel") if self.bag_count(k) > 0)
            return f"Recover the crank and wheel ({have}/2), turn the winch"
        return "Reach the stairs"

    def _check_complete(self) -> None:
        o, p = self.obj, self.p
        r = self.room_at(p.x, p.y)
        if o["done"] or r is None:
            return
        if o["type"] == "power" and o["power"] and r.role == "safe":
            self._finish_night()
        elif o["type"] == "keys" and self.bag_count("cellar_key") > 0 and r.role == "safe":
            self._finish_night()
        elif o["type"] == "escape" and o["gate_open"] and r.role == "exit":
            self._finish_night()

    def _finish_night(self) -> None:
        self.obj["done"] = True
        self.complete = True
        self.hooks.append(("umbra.night_survived", {"night": self.night}))
        self.say("night_complete", night=self.night)

    # ------------------------------------------------------------------ persistence of session progress
    def to_dict(self) -> dict:
        """JSON-safe snapshot at the last checkpoint (the level is regenerated from night + seed)."""
        return {"v": SAVE_V, "night": self.night, "seed": self.seed, "difficulty": self.difficulty, "deaths": self.deaths,
                "seen_rooms": sorted(self.seen_rooms), "checkpoint": self.checkpoint, "journal": self.journal,
                "hooks": [[n, p] for n, p in self.hooks]}

    @classmethod
    def from_dict(cls, cat: Catalog, d: dict, adapt: float = 1.0, unlocks=lambda u: False) -> "Game | None":
        try:
            if d.get("v") != SAVE_V:
                return None
            g = cls(cat, d["night"], d["seed"], d.get("difficulty", "standard"), adapt, d.get("journal"), unlocks)
            g.restore(d["checkpoint"])
            g.checkpoint = d["checkpoint"]
            g.deaths = d.get("deaths", 0)
            g.seen_rooms = set(d.get("seen_rooms", []))
            g.time = d["checkpoint"].get("time", 0.0)
            return g
        except (KeyError, TypeError, ValueError, IndexError):
            return None
