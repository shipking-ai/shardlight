"""Terrace game state: ties the world, player, ecology, fluids, crops and the Keystone trial into one fixed-step
simulation that the scene drives and the tests run headlessly.  JSON round trip via ``to_dict`` / ``from_dict``."""
from __future__ import annotations

import math

from ...core.rng import Rng, derive_seed
from . import constants as K
from . import fluids, light, structures
from .ecology import Ecology
from .inventory import Inventory
from .player import Intent, Player
from .registry import Registry
from .structures import Vigil
from .world import Drop, World
from .worldgen import generate

T = K.TILE
SAVE_VERSION = 1
PICKUP_R = 11.0
DROP_LIFE = 480.0


class Game:
    def __init__(self, reg: Registry, world: World, difficulty: str = "standard", unlocks=lambda u: False):
        self.reg = reg
        self.world = world
        self.difficulty = difficulty
        self.has_unlock = unlocks
        self.inv = Inventory(reg)
        sx, sy = world.spawn
        self.player = Player(world, self.inv, sx * T + T / 2, (sy + 2) * T, spawn=(sx * T + T / 2, (sy + 2) * T),
                             rng=Rng(derive_seed(world.seed, "player")))
        self.eco = Ecology(world, derive_seed(world.seed, "eco"), difficulty)
        self.vigil = Vigil(world)
        self.tick = 0
        self.t = 0.0
        self._sec = 0.0
        self._fluid_tick = 0
        self.log: list[str] = []
        self.hooks: list[tuple[str, dict]] = []
        self.toasts: list[str] = []
        self.sound: list[tuple[str, dict]] = []
        self.seen_recipes: set[str] = set()
        self.facet_done = False
        self._light_cache = None

    # ------------------------------------------------------------------ construction
    @classmethod
    def new(cls, reg: Registry, seed: int, difficulty: str = "standard", unlocks=lambda u: False) -> "Game":
        w = generate(seed, reg)
        g = cls(reg, w, difficulty, unlocks)
        g.eco.populate()
        g.give_start_kit()
        return g

    def give_start_kit(self) -> None:
        self.inv.add("wood_axe", 1)
        self.inv.add("wood_pickaxe", 1)
        self.inv.add("bread", 3)
        self.inv.add("torch", 4)

    # ------------------------------------------------------------------ helpers
    def light_at(self, x: int, y: int) -> int:
        c = self._light_cache
        if c is None or c[0] != (self.world.grid.version, int(self.world.daylight() * 16), x // 24, y // 24):
            wx, wy = x // 24 * 24 - 16, y // 24 * 24 - 16
            arr = light.compute(self.world, wx, wy, 56, 56)
            c = ((self.world.grid.version, int(self.world.daylight() * 16), x // 24, y // 24), arr, max(0, wx), max(0, wy))
            self._light_cache = c
        arr, ox, oy = c[1], c[2], c[3]
        yy, xx = y - oy, x - ox
        if 0 <= yy < arr.shape[0] and 0 <= xx < arr.shape[1]:
            return int(arr[yy, xx])
        return light.at(self.world, x, y)

    def emit(self, name: str, **payload) -> None:
        self.hooks.append((name, payload))

    # ------------------------------------------------------------------ simulation
    def update(self, dt: float, intent: Intent | None = None, aim: tuple[int, int] | None = None) -> None:
        w, p = self.world, self.player
        it = intent or Intent()
        self.tick += 1
        self.t += dt
        w.advance(dt)
        p.update(dt, it)
        self._player_actions(dt, it, aim)
        self._drops(dt)
        self._fluids()
        self._sec += dt
        if self._sec >= 1.0:
            sec, self._sec = self._sec, 0.0
            self._slow(sec)
        for ev, data in w.events:
            if ev == "dawn":
                if self.vigil.on_dawn() == "done":
                    self._finish_keystone()
                self.toasts.append(f"Day {data['day']}")
            elif ev == "hiss":
                self.sound.append(("hiss", data))
        w.events.clear()
        for ev, data in p.events:
            self.sound.append((ev, data))
        p.events.clear()

    def _fluids(self) -> None:
        if self.world.active_liquid:
            self._fluid_tick += 1
            fluids.step(self.world, 700, self._fluid_tick)

    def _slow(self, dt: float) -> None:
        w, p = self.world, self.player
        px, py = p.x, p.y
        self.eco.update(dt, px, py, p, self.light_at)
        for ev, data in self.eco.events:
            self.sound.append((ev, data))
        structures.grow(w, dt, lambda x, y: (w.sky_exposed(x, y) and w.daylight() > 0.35) or self.light_at(x, y) >= 9,
                        lambda x, y: self.eco.pollination_bonus(x, y))
        structures.hydrate(w)
        res = self.vigil.update(not p.dead)
        if res == "failed":
            self.toasts.append("The vigil is broken.")
            self.emit_log("The Keystone's light fails.")

    def emit_log(self, text: str) -> None:
        self.log.append(text)
        self.log[:] = self.log[-12:]

    # ------------------------------------------------------------------ player actions
    def _player_actions(self, dt: float, it: Intent, aim) -> None:
        p, w = self.player, self.world
        if p.dead:
            return
        if aim is None:
            aim = it.target
        if it.mine and aim is not None:
            tx, ty = aim
            c = self._creature_at(tx, ty)
            if c is not None and p.attack_cd <= 0:
                self._attack(c)
            elif c is None:
                p.mine(dt, tx, ty)
        else:
            p.mine_pos, p.mine_t = None, 0.0
        if it.use and aim is not None:
            tx, ty = aim
            self._use(tx, ty)
        if it.interact and aim is not None:
            self._interact(*aim)

    def _creature_at(self, tx: int, ty: int):
        p = self.player
        for c in self.eco.alive():
            d = self.reg.creatures[c.kind]
            sw, sh = d["size"]
            if abs(c.x - (tx * T + T / 2)) < sw / 2 + T and c.y - sh - T < ty * T + T / 2 < c.y + T and abs(c.x - p.x) < 20 and abs(c.y - p.y) < 20:
                return c
        return None

    def _attack(self, c) -> None:
        p = self.player
        p.attack_cd = 0.42
        dmg = p.attack_damage()
        drops = self.eco.damage(c, dmg, p.facing * 90)
        p.emit("slash")
        for item, n in drops:
            self.world.drops.append(Drop(c.x, c.y - 4, item, n, self.world.rng.uniform(-30, 30), -60))
        if not c.alive:
            p.stats["kills"] += 1
            self.sound.append(("kill", {"kind": c.kind}))

    def _use(self, tx: int, ty: int) -> None:
        p, w = self.player, self.world
        item = self.inv.held()
        if item is None:
            return
        # feed or shear nearby animals
        c = self._creature_at(tx, ty)
        it = self.reg.items[item]
        if c is not None:
            if item == "shears":
                n = self.eco.shear(c)
                if n:
                    self.inv.add("wool", n)
                    p.emit("shear")
                return
            if item in self.reg.creatures[c.kind].get("tame_food", []) and self.eco.feed(c, item):
                self.inv.take_slot(self.inv.selected)
                p.emit("tame")
                self.toasts.append(f"The {self.reg.creatures[c.kind]['name']} trusts you.")
                return
        res = p.use(tx, ty, self._entity_boxes())
        if res == "place" and w.get(tx, ty) == K.CHEST and (tx, ty) not in w.chests:
            w.chests[(tx, ty)] = [None] * 20
        if res == "place":
            for kind, x0, y0 in structures.detect_near(w, tx, ty):
                self._built(kind, x0, y0)

    def _entity_boxes(self):
        boxes = []
        for c in self.eco.alive():
            sw, sh = self.reg.creatures[c.kind]["size"]
            boxes.append((c.x - sw / 2, c.y - sh, c.x + sw / 2, c.y))
        px0, py0, px1, py1 = self.player.rect
        boxes.append((px0, py0, px1, py1))
        return boxes

    def _built(self, kind: str, x0: int, y0: int) -> None:
        w = self.world
        if kind == "keystone":
            if w.keystone_state == "unbuilt":
                w.keystone_state = "assembled"
                self.toasts.append("The Keystone stands. Light its prism and keep vigil until dawn.")
                self.emit("terrace.structure_built", kind="keystone")
                w.built.add("keystone")
            return
        key = f"{kind}@{x0},{y0}"
        if key in w.built:
            return
        w.built.add(key)
        w.built.add(kind)
        self.toasts.append("A beacon burns on the horizon.")
        self.emit("terrace.structure_built", kind=kind)

    def _interact(self, tx: int, ty: int) -> None:
        p, w = self.player, self.world
        kind = p.interact_block(tx, ty)
        n = w.get(tx, ty)
        if kind == "door":
            p.toggle_door(tx, ty)
            p.emit("door")
        elif kind == "bed":
            p.sleep(tx, ty)
            self.toasts.append("Home set.")
            if w.is_night():
                self._sleep_through()
        elif kind == "shrine":
            self.sound.append(("shrine", {}))
            self.toasts.append(self.shrine_hint())
            self.emit("terrace.shrine", x=tx, y=ty)
        elif n == K.PRISM and w.keystone is not None and structures.keystone_top(w) == (tx, ty):
            if w.keystone_state == "assembled":
                if self.vigil.light():
                    self.toasts.append("The prism catches. Hold the night.")
                    self.sound.append(("vigil", {}))
            elif w.keystone_state == "vigil":
                self.toasts.append("It burns. Dawn is the end of it.")
            elif w.keystone_state == "done":
                self.toasts.append("The Keystone is lit for good.")
            else:
                self.toasts.append("It is only a prism. Raise the Keystone around it.")

    def shrine_hint(self) -> str:
        w = self.world
        if w.keystone is None:
            return "The stone is quiet."
        kx = w.keystone[0] + 4
        px = self.player.x / T
        d = int(abs(kx - px))
        side = "east" if kx > px else "west"
        return f"The stone hums toward the {side}. About {d // 10 * 10} paces."

    def _sleep_through(self) -> None:
        """Sleeping skips the night when no hostile is close and no vigil is running."""
        w, p = self.world, self.player
        if w.keystone_state == "vigil":
            self.toasts.append("You cannot sleep during the vigil.")
            return
        if any(c.kind == "gloam" and abs(c.x - p.x) < 60 * T for c in self.eco.alive()):
            self.toasts.append("Something is near. You cannot sleep.")
            return
        w.clock = 0.94
        self.toasts.append("You sleep until dawn.")

    def _finish_keystone(self) -> None:
        if self.facet_done:
            return
        self.facet_done = True
        self.toasts.append("The Keystone is lit. A facet of the Lens answers.")
        self.emit("terrace.keystone_lit")

    # ------------------------------------------------------------------ world items
    def _drops(self, dt: float) -> None:
        w, p = self.world, self.player
        keep = []
        for d in w.drops:
            d.age += dt
            if d.age > DROP_LIFE:
                continue
            d.vy = min(300.0, d.vy + 600 * dt)
            nx, ny = d.x + d.vx * dt, d.y + d.vy * dt
            if w.solid(int(nx // T), int(d.y // T)):
                d.vx = 0.0
                nx = d.x
            if w.solid(int(nx // T), int((ny + 2) // T)):
                d.vy = 0.0
                d.vx *= 0.7
                ny = d.y
            a, lava = w.liquid(int(nx // T), int(ny // T))
            if lava and a:
                continue                                  # burned up
            d.x, d.y = nx, ny
            if not p.dead and d.age > 0.35 and math.hypot(d.x - p.x, d.y - (p.y - 6)) < PICKUP_R:
                left = self.inv.add(d.item, d.count)
                if left < d.count:
                    self.sound.append(("pickup", {"item": d.item}))
                    self._note_new_recipes()
                if left > 0:
                    d.count = left
                    keep.append(d)
                continue
            keep.append(d)
        w.drops[:] = keep

    def _note_new_recipes(self) -> None:
        """Toast when a pickup makes a new recipe craftable for the first time."""
        from .inventory import recipes_for, stations_near
        w = self.world
        stations = stations_near(w, self.player.x / T, self.player.y / T) | {"hand"}
        for r in recipes_for(self.reg, self, stations):
            if r["id"] not in self.seen_recipes and self.inv.has(r["inputs"]):
                self.seen_recipes.add(r["id"])
                if len(self.seen_recipes) > 6:
                    out = next(iter(r["outputs"]))
                    self.toasts.append(f"You can craft {self.reg.items[out]['name']}.")

    # ------------------------------------------------------------------ unlock hooks used by the registry
    def has_unlock_(self, uid: str) -> bool:
        return bool(self.has_unlock(uid))

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        w, p = self.world, self.player
        return {"v": SAVE_VERSION, "seed": w.seed, "difficulty": self.difficulty, "t": self.t,
                "clock": w.clock, "day": w.day, "time": w.time, "keystone_state": w.keystone_state,
                "built": sorted(w.built), "chunks": w.edited_payload(),
                "chests": [[x, y, s] for (x, y), s in w.chests.items()],
                "crops": [[x, y, round(v, 2)] for (x, y), v in w.crops.items()],
                "drops": [[round(d.x, 1), round(d.y, 1), d.item, d.count, round(d.age, 1)] for d in w.drops[:200]],
                "inv": self.inv.to_dict(),
                "player": {"x": round(p.x, 2), "y": round(p.y, 2), "hp": round(p.hp, 2), "hunger": round(p.hunger, 2),
                           "spawn": list(p.spawn), "stats": dict(p.stats), "facing": p.facing},
                "eco": self.eco.to_dict(), "vigil_night": self.vigil.night_seen, "facet_done": self.facet_done,
                "seen_recipes": sorted(self.seen_recipes), "log": self.log[-8:]}

    @classmethod
    def from_dict(cls, reg: Registry, d: dict, unlocks=lambda u: False) -> "Game | None":
        try:
            if d.get("v") != SAVE_VERSION:
                return None
            w = generate(d["seed"], reg)
            w.apply_payload(d.get("chunks", {}))
            w.grid.edited = set(tuple(int(v) for v in k.split(",")) for k in d.get("chunks", {}))
            w.clock, w.day, w.time = d["clock"], d["day"], d["time"]
            w.keystone_state = d.get("keystone_state", "unbuilt")
            w.built = set(d.get("built", []))
            w.chests = {(x, y): [list(s) if s else None for s in slots] for x, y, slots in d.get("chests", [])}
            w.crops = {(x, y): float(v) for x, y, v in d.get("crops", [])}
            w.drops = [Drop(x, y, item, n, age=a) for x, y, item, n, a in d.get("drops", []) if item in reg.items]
            w.active_liquid = {(int(x), int(y)) for y, x in __import__("numpy").argwhere(w.grid.liq > 0)}
            g = cls(reg, w, d.get("difficulty", "standard"), unlocks)
            g.inv = Inventory.from_dict(reg, d["inv"])
            pd = d["player"]
            g.player = Player(w, g.inv, pd["x"], pd["y"], hp=pd["hp"], hunger=pd["hunger"], spawn=tuple(pd["spawn"]),
                              stats=dict(pd["stats"]), facing=pd.get("facing", 1), rng=Rng(derive_seed(w.seed, "player", int(d["t"]))))
            g.player.fall_peak = g.player.y
            g.eco = Ecology.from_dict(w, d["eco"], derive_seed(w.seed, "eco"), g.difficulty)
            g.vigil = Vigil(w)
            g.vigil.night_seen = bool(d.get("vigil_night"))
            g.facet_done = bool(d.get("facet_done"))
            g.seen_recipes = set(d.get("seen_recipes", []))
            g.t = d["t"]
            g.log = list(d.get("log", []))
            return g
        except (KeyError, TypeError, ValueError):
            return None
