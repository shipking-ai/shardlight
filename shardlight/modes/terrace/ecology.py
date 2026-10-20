"""Terrace ecology: creatures with needs, a living food web and density-limited breeding.

* herbivores (hopper, woolback) graze the tall grass and flowers that regrow on grass tiles; woolbacks also eat
  ripe crops; they flee wolves and the player, breed when well fed and not crowded, and can be tamed with food;
* ridgewolves hunt herbivores when hungry (with a reaction delay and a stamina limit), eat carcasses, and bite
  the player when hungry and cornered;
* bumblets feed on flowers and pollinate: crops and flowers near them grow faster;
* gleaners eat carcasses; crawlers live in dark caves and avoid light; gloams spawn in the dark at night and burn
  in daylight.

Every species obeys the same loop (hunger, age, reproduction with a per-patch cap), so populations regulate
themselves: kill the wolves and the herbivores boom until grazing limits them; overhunt and the wolves starve.
Creatures far from the player are only aged and fed (abstract level of detail).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ...core.rng import Rng
from . import constants as K
from .world import Drop, World

T = K.TILE
GRAVITY = 700.0
PATCH = 48                          # tiles: the window used for density and food counts
LOD_RADIUS = 110                    # tiles
MAX_CREATURES = 160
CARCASS_DAYS = 1.2


@dataclass
class Creature:
    id: int
    kind: str
    x: float
    y: float                         # feet
    vx: float = 0.0
    vy: float = 0.0
    hp: float = 10.0
    hunger: float = 80.0
    age: float = 0.0                 # days
    repro_cd: float = 0.0            # days
    facing: int = 1
    state: str = "idle"
    timer: float = 0.0
    target: tuple | None = None
    tamed: bool = False
    flash: float = 0.0
    alive: bool = True
    seen_t: float = 0.0
    stamina: float = 1.0
    atk_cd: float = 0.0
    on_ground: bool = False
    anim: float = 0.0
    fed_t: float = 0.0               # seconds since last meal (animation / tests)
    wool: float = 0.0                # days until a sheared woolback has wool again


@dataclass
class Carcass:
    x: float
    y: float
    kind: str
    age: float = 0.0


class Ecology:
    def __init__(self, world: World, seed: int = 1, difficulty: str = "standard"):
        self.world = world
        self.reg = world.reg
        self.rng = Rng(seed).child("ecology")
        self.creatures: list[Creature] = []
        self.carcasses: list[Carcass] = []
        self.next_id = 1
        self.difficulty = difficulty
        self.night_cap = {"story": 2, "standard": 4, "hard": 6}.get(difficulty, 4)
        self.events: list[tuple[str, dict]] = []
        self._grow_t = 0.0
        self._acc = 0.0
        self.pollinated: dict[tuple[int, int], float] = {}
        self._regrow_acc = 0.0

    # ------------------------------------------------------------------ queries
    def defs(self, kind: str) -> dict:
        return self.reg.creatures[kind]

    def alive(self, kind: str | None = None) -> list[Creature]:
        return [c for c in self.creatures if c.alive and (kind is None or c.kind == kind)]

    def count(self, kind: str) -> int:
        return sum(1 for c in self.creatures if c.alive and c.kind == kind)

    def near(self, x: float, y: float, r_px: float, kind: str | None = None) -> list[Creature]:
        r2 = r_px * r_px
        return [c for c in self.creatures if c.alive and (kind is None or c.kind == kind)
                and (c.x - x) ** 2 + (c.y - y) ** 2 <= r2]

    def forage(self, tx: int, radius: int = PATCH // 2) -> int:
        """Grazable tiles (tall grass and flowers on the surface band) around column ``tx``."""
        w = self.world
        x0, x1 = max(0, tx - radius), min(w.w, tx + radius)
        s = int(w.surf[max(0, min(w.w - 1, tx))])
        band = w.grid.blocks[max(0, s - 6):s + 2, x0:x1]
        return int(((band == K.TALLGRASS) | (band == K.FLOWER)).sum())

    def flowers(self, tx: int, radius: int = 30) -> int:
        w = self.world
        x0, x1 = max(0, tx - radius), min(w.w, tx + radius)
        s = int(w.surf[max(0, min(w.w - 1, tx))])
        return int((w.grid.blocks[max(0, s - 6):s + 2, x0:x1] == K.FLOWER).sum())

    # ------------------------------------------------------------------ spawning
    def spawn(self, kind: str, x: float, y: float, age: float | None = None, hunger: float | None = None) -> Creature | None:
        if len([c for c in self.creatures if c.alive]) >= MAX_CREATURES:
            return None
        d = self.defs(kind)
        c = Creature(self.next_id, kind, x, y, hp=float(d["hp"]), hunger=hunger if hunger is not None else self.rng.uniform(60, 95),
                     age=age if age is not None else d.get("maturity_days", 1.0) + self.rng.uniform(0, 3.0))
        c.facing = 1 if self.rng.random() < 0.5 else -1
        self.next_id += 1
        self.creatures.append(c)
        return c

    def populate(self) -> None:
        """Initial wildlife: grazers and wolves on grass biomes, bumblets near flowers, crawlers in caves."""
        w = self.world
        r = self.rng.child("populate")
        surf = w.surf
        for x in range(8, w.w - 8, 6):
            biome = w.biome_name(x)
            top = int(surf[x])
            if w.liquid(x, top - 1)[0]:
                continue
            fx = x * T + T / 2
            fy = top * T
            if biome in ("meadow", "forest"):
                if r.chance(0.30):
                    self.spawn("hopper", fx, fy)
                if r.chance(0.12):
                    self.spawn("woolback", fx, fy)
                if r.chance(0.035) and abs(x - w.spawn[0]) > 40:
                    self.spawn("ridgewolf", fx, fy, hunger=80)
                if r.chance(0.10):
                    self.spawn("bumblet", fx, fy - 40)
            elif biome == "frozen":
                if r.chance(0.10):
                    self.spawn("hopper", fx, fy)
                if r.chance(0.03):
                    self.spawn("ridgewolf", fx, fy)
            if r.chance(0.04):
                self.spawn("gleaner", fx, fy - 70)
        # cave dwellers
        tries = 0
        while self.count("crawler") < 26 and tries < 400:
            tries += 1
            x = r.randint(8, w.w - 8)
            y = r.randint(int(surf[x]) + 25, w.h - 50)
            if w.get(x, y) == K.AIR and w.solid(x, y + 1) and not w.liquid(x, y)[0]:
                self.spawn("crawler", x * T + T / 2, (y + 1) * T)

    # ------------------------------------------------------------------ simulation
    def update(self, dt: float, px: float, py: float, player=None, light_at=None) -> None:
        """Advance by ``dt`` seconds around the player at pixel position (px, py)."""
        w = self.world
        self.events.clear()
        day = dt / K.DAY_LEN
        self._grow_t += dt
        if self._grow_t >= 1.0:
            self._regrow(self._grow_t, px)
            self._grow_t = 0.0
        for cz in self.carcasses:
            cz.age += day
        self.carcasses = [c for c in self.carcasses if c.age < CARCASS_DAYS]
        ptx = px / T
        for c in list(self.creatures):
            if not c.alive:
                continue
            near = abs(c.x / T - ptx) <= LOD_RADIUS
            c.age += day
            c.repro_cd = max(0.0, c.repro_cd - day)
            c.wool = max(0.0, c.wool - day)
            c.flash = max(0.0, c.flash - dt)
            c.atk_cd = max(0.0, c.atk_cd - dt)
            d = self.defs(c.kind)
            c.hunger -= d["hunger_rate"] * dt * (1.0 if near else 0.6)
            c.fed_t += dt
            if c.age > d["lifespan_days"]:
                self._die(c, "old")
                continue
            if c.hunger <= 0:
                c.hp -= 1.5 * dt
                if c.hp <= 0:
                    self._die(c, "starved")
                    continue
            if near:
                self._behave(c, d, dt, px, py, player, light_at)
                self._body(c, d, dt)
            else:
                self._abstract(c, d, dt)
            self._breed(c, d)
        self.creatures = [c for c in self.creatures if c.alive]
        if player is not None:
            self._night_spawns(dt, player, light_at)

    # -- environment ---------------------------------------------------------------------------
    def _regrow(self, dt: float, px: float) -> None:
        w = self.world
        r = self.rng
        self._regrow_acc += dt * 0.35                        # about one new tuft per three seconds across the loaded area
        n = int(self._regrow_acc)
        self._regrow_acc -= n
        cx = int(px / T)
        for _ in range(n):
            x = cx + r.randint(-LOD_RADIUS, LOD_RADIUS)
            if not (2 <= x < w.w - 2):
                continue
            if w.biome_name(x) not in ("meadow", "forest"):
                continue
            top = int(w.surf[x])
            if w.get(x, top) == K.GRASS and w.get(x, top - 1) == K.AIR:
                flowers = self.flowers(x, 14)
                bumble = len(self.near(x * T, top * T, 40 * T, "bumblet"))
                w.set(x, top - 1, K.FLOWER if r.random() < 0.06 + 0.02 * min(5, bumble) and flowers < 40 else K.TALLGRASS)

    # -- needs ----------------------------------------------------------------------------------
    def _die(self, c: Creature, why: str, by_player: bool = False) -> list[tuple[str, int]]:
        if not c.alive:
            return []
        c.alive = False
        d = self.defs(c.kind)
        drops: list[tuple[str, int]] = []
        if why in ("killed", "burned"):
            for e in d.get("drops", []):
                if self.rng.random() <= e.get("p", 1.0):
                    n = self.rng.randint(e.get("min", 1), max(e.get("min", 1), e.get("max", 1)))
                    if n > 0:
                        drops.append((e["item"], n))
        if d["role"] in ("herbivore", "predator") and why != "burned":
            self.carcasses.append(Carcass(c.x, c.y, c.kind))
        self.events.append(("died", {"id": c.id, "kind": c.kind, "why": why, "x": c.x, "y": c.y}))
        return drops

    def damage(self, c: Creature, amount: float, kx: float = 0.0, source: str = "player") -> list[tuple[str, int]]:
        """Hurt a creature; returns the item drops if it dies (the caller places them in the world)."""
        if not c.alive:
            return []
        c.hp -= amount
        c.flash = 0.25
        c.vx += kx
        c.vy = -80 if c.on_ground else c.vy
        c.state = "flee" if self.defs(c.kind)["role"] in ("herbivore", "pollinator", "scavenger") else c.state
        c.timer = 4.0
        c.seen_t = 1.0
        if c.hp <= 0:
            return self._die(c, "killed", by_player=source == "player")
        return []

    def _abstract(self, c: Creature, d: dict, dt: float) -> None:
        """Far from the player: no movement.  Animals graze or hunt statistically so they neither starve nor boom."""
        tx = int(c.x / T)
        role = d["role"]
        if role == "herbivore":
            if self.forage(tx) > 10:
                c.hunger = min(100.0, c.hunger + d["hunger_rate"] * dt * 1.2)
        elif role == "predator":
            prey = sum(1 for o in self.creatures if o.alive and o.kind in d["diet"] and abs(o.x - c.x) < 90 * T)
            if prey >= 2:
                c.hunger = min(100.0, c.hunger + d["hunger_rate"] * dt * 1.1)
        elif role in ("pollinator",):
            if self.flowers(tx) > 3:
                c.hunger = min(100.0, c.hunger + d["hunger_rate"] * dt * 1.2)
        elif role == "scavenger":
            if self.carcasses:
                c.hunger = min(100.0, c.hunger + d["hunger_rate"] * dt * 0.8)
        elif role == "cave":
            c.hunger = min(100.0, c.hunger + d["hunger_rate"] * dt * 1.1)

    # -- reproduction ---------------------------------------------------------------------------
    # TODO(#14): herds cluster and over-graze near the player; add spacing/territory (and irrigation for farms).
    def _breed(self, c: Creature, d: dict) -> None:
        if d["litter"][1] <= 0 or c.age < d["maturity_days"] or c.repro_cd > 0 or c.hunger < d["food_min"]:
            return
        mates = [o for o in self.creatures if o.alive and o.kind == c.kind and o is not c and o.age >= d["maturity_days"]
                 and abs(o.x - c.x) < 14 * T and abs(o.y - c.y) < 14 * T]
        if not mates:
            return
        if self.count(c.kind) >= d["patch_cap"] * 6:                                  # world-wide carrying limit
            c.repro_cd = d["repro_cooldown_days"] * 0.5
            return
        same_patch = [o for o in self.creatures if o.alive and o.kind == c.kind and abs(o.x - c.x) < PATCH * T / 2]
        if len(same_patch) >= d["patch_cap"]:
            c.repro_cd = d["repro_cooldown_days"] * 0.5               # crowded: try again later
            return
        if d["role"] == "herbivore":
            food = self.forage(int(c.x / T))
            if food < 12 or food / (len(same_patch) + 1) < 4.0:               # grazing, not the cap alone, limits herds
                return
        n = min(self.rng.randint(d["litter"][0], d["litter"][1]), d["patch_cap"] * 6 - self.count(c.kind))
        c.repro_cd = d["repro_cooldown_days"]
        mates[0].repro_cd = max(mates[0].repro_cd, d["repro_cooldown_days"] * 0.7)
        c.hunger -= 22
        for _ in range(n):
            b = self.spawn(c.kind, c.x + self.rng.uniform(-6, 6), c.y, age=0.0, hunger=70.0)
            if b:
                b.tamed = c.tamed
                self.events.append(("born", {"kind": c.kind, "x": b.x, "y": b.y}))

    # -- behaviour -------------------------------------------------------------------------------
    def _nearest(self, c: Creature, kinds, r_px: float):
        best, bd = None, r_px * r_px
        for o in self.creatures:
            if o.alive and o is not c and o.kind in kinds:
                dd = (o.x - c.x) ** 2 + (o.y - c.y) ** 2
                if dd < bd:
                    best, bd = o, dd
        return best

    def _behave(self, c: Creature, d: dict, dt: float, px: float, py: float, player, light_at) -> None:
        role = d["role"]
        dpx, dpy = px - c.x, py - c.y
        dist_p = math.hypot(dpx, dpy)
        c.timer = max(0.0, c.timer - dt)
        c.anim += dt
        speed = d["speed"]
        flee_p = "player" in d.get("flee", []) and not c.tamed and player is not None
        if role == "herbivore":
            threat = self._nearest(c, d.get("flee", []), d["perception"] * 0.9)
            fear = threat is not None or (flee_p and dist_p < d["perception"] * 0.6 and player is not None and not player.dead)
            if c.state == "flee" and c.timer > 0:
                fear = True
            if fear:
                c.state = "flee"
                c.timer = max(c.timer, 1.2)
                src = (threat.x, threat.y) if threat else (px, py)
                c.facing = -1 if src[0] > c.x else 1
                c.vx = c.facing * speed * 1.45
                self._hop(c, d)
                return
            c.state = "idle" if c.state == "flee" else c.state
            if c.tamed and player is not None and dist_p > 60 and dist_p < 600:
                c.facing = 1 if dpx > 0 else -1
                c.vx = c.facing * speed * 0.7
                self._hop(c, d)
                return
            if c.hunger < 55:
                tgt = self._food_tile(c, d)
                if tgt is not None:
                    tx, ty = tgt
                    gx = tx * T + T / 2
                    if abs(gx - c.x) < 5:
                        self._eat_tile(c, tx, ty)
                    else:
                        c.facing = 1 if gx > c.x else -1
                        c.vx = c.facing * speed * 0.7
                        self._hop(c, d)
                    return
            self._wander(c, d, speed * 0.4)
        elif role == "predator":
            prey = self._nearest(c, d["diet"], d["perception"]) if c.hunger < 62 else None
            carc = None
            if c.hunger < 62 and prey is None:
                carc = min((k for k in self.carcasses if abs(k.x - c.x) < d["perception"]), key=lambda k: abs(k.x - c.x), default=None)
            if prey is not None:
                c.seen_t += dt
                if c.seen_t > 0.45:                                       # reaction delay before the chase begins
                    c.state = "hunt"
                    c.stamina = max(0.0, c.stamina - dt / 9.0)
                    spd = speed * (1.0 if c.stamina > 0.05 else 0.35)
                    c.facing = 1 if prey.x > c.x else -1
                    c.vx = c.facing * spd
                    self._hop(c, d)
                    if abs(prey.x - c.x) < 9 and abs(prey.y - c.y) < 8 and c.atk_cd <= 0:
                        c.atk_cd = 1.0
                        drops = self.damage(prey, d["damage"], c.facing * 80, "wolf")
                        if not prey.alive:
                            c.hunger = min(100.0, c.hunger + 55)
                            c.stamina = 1.0
                            c.fed_t = 0.0
                    return
            else:
                c.seen_t = 0.0
                c.stamina = min(1.0, c.stamina + dt / 14.0)
            if carc is not None:
                c.facing = 1 if carc.x > c.x else -1
                c.vx = c.facing * speed * 0.7
                self._hop(c, d)
                if abs(carc.x - c.x) < 8:
                    self.carcasses.remove(carc)
                    c.hunger = min(100.0, c.hunger + 35)
                    c.fed_t = 0.0
                return
            if player is not None and not player.dead and c.hunger < 40 and dist_p < d["perception"] * 0.8:
                c.state = "hunt"
                c.facing = 1 if dpx > 0 else -1
                c.vx = c.facing * speed * 0.95
                self._hop(c, d)
                if abs(dpx) < 10 and abs(dpy) < 12 and c.atk_cd <= 0:
                    c.atk_cd = 1.2
                    player.hurt(d["damage"], "creature")
                    player.vx += c.facing * 70
                return
            self._wander(c, d, speed * 0.35)
        elif role == "pollinator":
            if flee_p and dist_p < 50:
                c.vx = (-1 if dpx > 0 else 1) * speed
                c.vy = -20
                return
            if self.world.daylight() < 0.4:
                c.vx *= 0.8
                c.vy = 12
                return
            fl = self._flower_near(c)
            if fl is not None:
                gx, gy = fl[0] * T + 4, fl[1] * T
                c.vx = max(-speed, min(speed, (gx - c.x) * 3))
                c.vy = max(-speed, min(speed, (gy - 6 - c.y) * 3))
                if abs(gx - c.x) < 5 and abs(gy - 6 - c.y) < 5:
                    c.hunger = min(100.0, c.hunger + 20 * dt)
                    self._pollinate(fl, dt)
            else:
                c.vx += self.rng.uniform(-30, 30) * dt * 4
                c.vy = (self._hover_y(c) - c.y) * 1.5
                c.vx = max(-speed, min(speed, c.vx))
        elif role == "scavenger":
            if flee_p and dist_p < 50:
                c.vx = (-1 if dpx > 0 else 1) * speed
                c.vy = -speed * 0.5
                return
            carc = min((k for k in self.carcasses if abs(k.x - c.x) < d["perception"]), key=lambda k: abs(k.x - c.x), default=None)
            if carc is not None and c.hunger < 70:
                c.vx = max(-speed, min(speed, (carc.x - c.x) * 2))
                c.vy = max(-speed, min(speed, (carc.y - 4 - c.y) * 2))
                if abs(carc.x - c.x) < 6 and abs(carc.y - 4 - c.y) < 6:
                    self.carcasses.remove(carc)
                    c.hunger = min(100.0, c.hunger + 45)
                    c.fed_t = 0.0
            else:
                c.timer = c.timer or 2.0
                c.vx = math.cos(c.anim * 0.6 + c.id) * speed * 0.6
                c.vy = (self._hover_y(c, 90) - c.y) * 1.2 + math.sin(c.anim * 1.3) * 12
        elif role == "cave":
            lit = light_at(int(c.x / T), int((c.y - 4) / T)) if light_at else 0
            if lit >= 8:
                c.facing = -c.facing if c.timer <= 0 else c.facing
                c.timer = 1.0
                c.vx = c.facing * speed * 1.1
                self._hop(c, d)
            elif player is not None and not player.dead and dist_p < d["perception"]:
                c.seen_t += dt
                if c.seen_t > 0.5:
                    c.facing = 1 if dpx > 0 else -1
                    c.vx = c.facing * speed
                    self._hop(c, d)
                    if abs(dpx) < 10 and abs(dpy) < 10 and c.atk_cd <= 0:
                        c.atk_cd = 1.0
                        player.hurt(d["damage"], "creature")
                        player.vx += c.facing * 60
            else:
                c.seen_t = 0.0
                c.hunger = min(100.0, c.hunger + 8 * dt)
                self._wander(c, d, speed * 0.4)
        elif role == "night":
            day = self.world.daylight()
            lit = light_at(int(c.x / T), int((c.y - 6) / T)) if light_at else 0
            if (day > 0.6 and lit >= 12 and self.world.sky_exposed(int(c.x / T), int(c.y / T) - 1)) or lit >= 13 and day > 0.6:
                c.hp -= 3.5 * dt
                c.flash = 0.1
                if c.hp <= 0:
                    self._die(c, "burned")
                    return
            if player is not None and not player.dead and dist_p < d["perception"] * (1.5 if self.world.keystone_state == "vigil" else 1.0):
                c.seen_t += dt
                if c.seen_t > 0.35:
                    c.facing = 1 if dpx > 0 else -1
                    c.vx = c.facing * speed * (1.3 if self.world.keystone_state == "vigil" else 1.0)
                    self._hop(c, d)
                    if abs(dpx) < 9 and abs(dpy) < 14 and c.atk_cd <= 0:
                        c.atk_cd = 1.1
                        player.hurt(d["damage"], "creature")
                        player.vx += c.facing * 80
            else:
                c.seen_t = 0.0
                self._wander(c, d, speed * 0.3)

    def _wander(self, c: Creature, d: dict, speed: float) -> None:
        crowd = [o for o in self.creatures if o.alive and o.kind == c.kind and o is not c and abs(o.x - c.x) < 6 * T]
        if len(crowd) >= 3 and d.get("habitat") != "air":                         # herds spread out instead of stacking up
            cx = sum(o.x for o in crowd) / len(crowd)
            c.facing = 1 if c.x >= cx else -1
            c.state = "walk"
            c.timer = max(c.timer, 1.0)
        elif c.timer <= 0:
            c.timer = self.rng.uniform(1.0, 4.0)
            c.state = "idle" if self.rng.random() < 0.45 else "walk"
            if c.state == "walk":
                c.facing = 1 if self.rng.random() < 0.5 else -1
        c.vx = c.facing * speed if c.state == "walk" else 0.0
        if c.state == "walk":
            self._hop(c, d)

    def _hop(self, c: Creature, d: dict) -> None:
        """Jump over a ledge in front of a ground walker (up to the species' jump height)."""
        if d.get("habitat") == "air" or not c.on_ground or d.get("jump", 0) <= 0:
            return
        w = self.world
        fx = int((c.x + c.facing * (d["size"][0] / 2 + 2)) // T)
        fy = int((c.y - 2) // T)
        if w.solid(fx, fy) and not w.solid(fx, fy - 1):
            c.vy = -math.sqrt(2 * GRAVITY * (T * (d["jump"] + 0.6)))
        elif w.solid(fx, fy) and not w.solid(fx, fy - 2) and d["jump"] >= 2:
            c.vy = -math.sqrt(2 * GRAVITY * (T * 2.6))
        elif not w.solid(fx, fy + 1) and not w.solid(fx, fy + 2) and not w.solid(fx, fy + 3) and d["jump"] >= 1 and c.state != "flee":
            c.vx = 0.0                                                    # a cliff edge: turn around instead of falling
            c.facing = -c.facing

    def _food_tile(self, c: Creature, d: dict):
        w = self.world
        cx = int(c.x / T)
        top = int(w.surf[max(0, min(w.w - 1, cx))])
        best, bd = None, 10 ** 9
        crops = "crops" in d["diet"]
        for x in range(max(0, cx - 22), min(w.w, cx + 23)):
            for y in (int(w.surf[x]) - 1,):
                b = w.get(x, y)
                good = b in (K.TALLGRASS, K.FLOWER) or (crops and b in (K.WHEAT0 + 3, K.TUBER0 + 3, K.WHEAT0 + 2, K.TUBER0 + 2))
                if good and abs(x - cx) < bd:
                    best, bd = (x, y), abs(x - cx)
        return best

    def _eat_tile(self, c: Creature, tx: int, ty: int) -> None:
        w = self.world
        b = w.get(tx, ty)
        if b in (K.TALLGRASS, K.FLOWER) or w.reg.block(b).get("crop"):
            w.set(tx, ty, K.AIR)
            w.crops.pop((tx, ty), None)
            c.hunger = min(100.0, c.hunger + (26 if b != K.FLOWER else 16))
            c.fed_t = 0.0
            self.events.append(("graze", {"x": tx * T, "y": ty * T}))

    def _flower_near(self, c: Creature):
        w = self.world
        cx = int(c.x / T)
        best, bd = None, 99
        for x in range(max(0, cx - 14), min(w.w, cx + 15)):
            y = int(w.surf[x]) - 1
            if w.get(x, y) == K.FLOWER and abs(x - cx) < bd:
                best, bd = (x, y), abs(x - cx)
        return best

    def _pollinate(self, fl: tuple[int, int], dt: float) -> None:
        self.pollinated[fl] = self.pollinated.get(fl, 0.0) + dt
        if len(self.pollinated) > 200:
            self.pollinated.clear()

    def pollination_bonus(self, x: int, y: int) -> float:
        """Growth multiplier for a crop at tile (x, y) from bumblets working flowers nearby."""
        n = len(self.near(x * T, y * T, 18 * T, "bumblet"))
        return 1.0 + 0.25 * min(3, n)

    def _hover_y(self, c: Creature, h: float = 40.0) -> float:
        tx = int(c.x / T)
        return int(self.world.surf[max(0, min(self.world.w - 1, tx))]) * T - h

    # -- physics ---------------------------------------------------------------------------------
    def _body(self, c: Creature, d: dict, dt: float) -> None:
        w = self.world
        sw, sh = d["size"]
        air = d.get("habitat") == "air"
        if not air:
            c.vy = min(360.0, c.vy + GRAVITY * dt)
        else:
            c.vx = max(-80, min(80, c.vx))
            c.vy = max(-80, min(80, c.vy))

        def hit(x: float, y: float) -> bool:
            x0, x1 = int((x - sw / 2) // T), int((x + sw / 2 - 0.01) // T)
            y0, y1 = int((y - sh) // T), int((y - 0.01) // T)
            for ty in range(y0, y1 + 1):
                for tx in range(x0, x1 + 1):
                    if w.solid(tx, ty):
                        return True
            return False

        dx = c.vx * dt
        steps = max(1, int(abs(dx)) + 1)
        for _ in range(steps):
            nx = c.x + dx / steps
            if not hit(nx, c.y):
                c.x = nx
            else:
                c.vx = 0.0
                if not air and c.state in ("walk",):
                    c.facing = -c.facing
                break
        dy = c.vy * dt
        steps = max(1, int(abs(dy)) + 1)
        c.on_ground = False
        for _ in range(steps):
            ny = c.y + dy / steps
            if not hit(c.x, ny):
                c.y = ny
            else:
                if dy > 0:
                    c.on_ground = True
                c.vy = 0.0
                break
        if not air and c.vy == 0.0 and hit(c.x, c.y + 0.5):
            c.on_ground = True
        if not air and c.on_ground:
            c.vx *= 0.8 if c.state == "idle" else 1.0
        c.x = max(sw, min(w.w * T - sw, c.x))
        if c.y > w.h * T - 2 * T:
            c.y = w.h * T - 3 * T
        # liquids: lava kills, water is swum
        tx, ty = int(c.x // T), int((c.y - 3) // T)
        a, lava = w.liquid(tx, ty)
        if a and lava and c.alive:
            self._die(c, "burned")

    # -- night -----------------------------------------------------------------------------------
    def _night_spawns(self, dt: float, player, light_at) -> None:
        w = self.world
        if not w.is_night() and w.keystone_state != "vigil":
            return
        cap = self.night_cap + (4 if w.keystone_state == "vigil" else 0)
        n = len([c for c in self.creatures if c.alive and c.kind == "gloam" and abs(c.x - player.x) < 80 * T])
        if n >= cap or self.rng.random() > dt * (0.5 if w.keystone_state != "vigil" else 1.4):
            return
        for _ in range(8):
            side = 1 if self.rng.random() < 0.5 else -1
            x = int(player.x / T) + side * self.rng.randint(26, 46)
            if not (3 <= x < w.w - 3):
                continue
            y = int(w.surf[x]) - 1
            if light_at and light_at(x, y) > 6:
                continue
            if w.get(x, y) == K.AIR and w.solid(x, y + 1) and not w.liquid(x, y)[0]:
                self.spawn("gloam", x * T + T / 2, (y + 1) * T, age=1.0, hunger=100.0)
                self.events.append(("gloam_spawn", {"x": x}))
                return

    # ------------------------------------------------------------------ taming / shearing
    def feed(self, c: Creature, item: str) -> bool:
        d = self.defs(c.kind)
        if item in d.get("tame_food", []):
            c.tamed = True
            c.hunger = min(100.0, c.hunger + 30)
            c.fed_t = 0.0
            return True
        return False

    def shear(self, c: Creature) -> int:
        """Shearing a grown woolback yields wool; it grows back in a day."""
        if c.kind != "woolback" or c.age < 1.0 or c.wool > 0:
            return 0
        c.wool = 1.0
        return self.rng.randint(1, 2)

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"next": self.next_id,
                "creatures": [[c.id, c.kind, round(c.x, 1), round(c.y, 1), round(c.hp, 2), round(c.hunger, 2), round(c.age, 3),
                               round(c.repro_cd, 3), int(c.tamed), c.facing] for c in self.creatures if c.alive],
                "carcasses": [[k.x, k.y, k.kind, round(k.age, 3)] for k in self.carcasses]}

    @classmethod
    def from_dict(cls, world: World, d: dict, seed: int = 1, difficulty: str = "standard") -> "Ecology":
        e = cls(world, seed, difficulty)
        e.next_id = int(d.get("next", 1))
        for row in d.get("creatures", []):
            cid, kind, x, y, hp, hunger, age, rcd, tamed, facing = row
            if kind in world.reg.creatures:
                c = Creature(cid, kind, x, y, hp=hp, hunger=hunger, age=age, repro_cd=rcd, tamed=bool(tamed), facing=facing)
                e.creatures.append(c)
        e.carcasses = [Carcass(*r) for r in d.get("carcasses", [])]
        return e
