"""The Terrace player: platformer physics, mining, placing, tools, survival stats and respawn.

Pure logic against a ``World``; the scene feeds an ``Intent`` each tick.  Positions are pixels (8 px tiles):
``x`` is the horizontal centre, ``y`` the feet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...core.rng import Rng
from . import constants as K
from . import fluids
from .inventory import HOTBAR, Inventory
from .world import Drop, World

T = K.TILE
W_PX, H_PX = 6, 14
GRAVITY = 900.0
WALK = 74.0
ACCEL = 700.0
JUMP_V = 232.0
MAX_FALL = 420.0
SWIM_UP = 70.0
CLIMB = 52.0
REACH = 5.5                  # tiles
MAX_HP = 100.0
MAX_HUNGER = 100.0
HUNGER_RATE = 0.16           # per second
ATTACK_CD = 0.42


@dataclass
class Intent:
    move: float = 0.0
    jump: bool = False           # pressed this tick
    jump_held: bool = False
    up: bool = False
    down: bool = False
    mine: bool = False           # held
    use: bool = False            # pressed this tick
    interact: bool = False       # pressed this tick
    target: tuple[int, int] | None = None     # tile under the cursor / aim


@dataclass
class Player:
    world: World
    inv: Inventory
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    hp: float = MAX_HP
    hunger: float = MAX_HUNGER
    facing: int = 1
    on_ground: bool = False
    in_water: bool = False
    in_lava: bool = False
    climbing: bool = False
    dead: bool = False
    spawn: tuple[float, float] = (0.0, 0.0)
    mine_pos: tuple[int, int] | None = None
    mine_t: float = 0.0
    attack_cd: float = 0.0
    invuln: float = 0.0
    fall_peak: float = 0.0
    coyote: float = 0.0
    jump_buf: float = 0.0
    events: list = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"mined": 0, "placed": 0, "crafted": 0, "kills": 0, "deaths": 0})
    rng: Rng = field(default_factory=lambda: Rng(7))

    def __post_init__(self) -> None:
        self.fall_peak = self.y

    # ------------------------------------------------------------------ helpers
    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x - W_PX / 2, self.y - H_PX, self.x + W_PX / 2, self.y)

    @property
    def tile(self) -> tuple[int, int]:
        return int(self.x // T), int((self.y - H_PX / 2) // T)

    def emit(self, kind: str, **kw) -> None:
        self.events.append((kind, kw))

    def tool(self) -> dict | None:
        item = self.inv.held()
        if not item:
            return None
        it = self.world.reg.items[item]
        return it.get("tool")

    def _solid_at(self, x: float, y: float) -> bool:
        x0, x1 = int((x - W_PX / 2) // T), int((x + W_PX / 2 - 0.001) // T)
        y0, y1 = int((y - H_PX) // T), int((y - 0.001) // T)
        w = self.world
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if w.solid(tx, ty):
                    return True
        return False

    def _overlaps(self, pred) -> bool:
        x0, x1 = int((self.x - W_PX / 2) // T), int((self.x + W_PX / 2 - 0.001) // T)
        y0, y1 = int((self.y - H_PX) // T), int((self.y - 0.001) // T)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if pred(tx, ty):
                    return True
        return False

    # ------------------------------------------------------------------ main update
    def update(self, dt: float, it: Intent) -> None:
        if self.dead:
            return
        w = self.world
        reg = w.reg
        self.attack_cd = max(0.0, self.attack_cd - dt)
        self.invuln = max(0.0, self.invuln - dt)
        # environment
        def liq_frac(tx, ty):
            a, lava = w.liquid(tx, ty)
            return a, lava
        body = (int(self.x // T), int((self.y - H_PX * 0.5) // T))
        feet = (int(self.x // T), int((self.y - 2) // T))
        a_body, lava_body = liq_frac(*body)
        a_feet, lava_feet = liq_frac(*feet)
        self.in_water = (a_body >= 3 and not lava_body) or (a_feet >= 5 and not lava_feet)
        self.in_lava = (a_body > 0 and lava_body) or (a_feet > 0 and lava_feet)
        climb_block = self._overlaps(lambda tx, ty: bool(reg.block(w.get(tx, ty)).get("climb")))
        # horizontal
        target = it.move * WALK * (0.55 if self.in_water else 0.5 if self.in_lava else 1.0)
        a = ACCEL * dt * (1.0 if self.on_ground or climb_block else 0.7)
        if self.vx < target:
            self.vx = min(target, self.vx + a)
        elif self.vx > target:
            self.vx = max(target, self.vx - a * (1.4 if it.move == 0 else 1.0))
        if it.move:
            self.facing = 1 if it.move > 0 else -1
        # vertical
        self.coyote = 0.1 if self.on_ground else max(0.0, self.coyote - dt)
        self.jump_buf = 0.12 if it.jump else max(0.0, self.jump_buf - dt)
        self.climbing = False
        if self.in_lava:
            self.vy += (GRAVITY * 0.25) * dt
            self.vy = min(self.vy, 40.0)
            if it.jump_held or it.up:
                self.vy = -55.0
        elif self.in_water:
            self.vy += GRAVITY * 0.3 * dt
            self.vy = max(-SWIM_UP, min(self.vy, 55.0))
            if it.jump_held or it.up:
                self.vy = -SWIM_UP
            self.fall_peak = self.y
        elif climb_block and (it.up or it.down or not self.on_ground and self.vy > -50):
            self.climbing = True
            self.vy = -CLIMB if it.up else CLIMB if it.down else 0.0
            self.fall_peak = self.y
        else:
            self.vy = min(MAX_FALL, self.vy + GRAVITY * dt)
        if self.jump_buf > 0 and (self.coyote > 0 or (climb_block and not self.on_ground)) and not self.in_water and not self.in_lava:
            self.vy = -JUMP_V
            self.jump_buf = 0.0
            self.coyote = 0.0
            self.on_ground = False
            self.emit("jump")
        if not it.jump_held and self.vy < -90 and not self.climbing and not self.in_water:
            self.vy += GRAVITY * 1.6 * dt                      # variable jump height
        self._move(dt)
        # survival
        self._survival(dt)
        # world bounds
        self.x = max(W_PX, min(w.w * T - W_PX, self.x))
        if self.y > w.h * T:
            self.hurt(9999, "void")

    def _move(self, dt: float) -> None:
        # horizontal: 1 px sub-steps, auto-stepping onto a one-tile ledge while walking on the ground
        dx = self.vx * dt
        sx = 1.0 if dx > 0 else -1.0
        left = abs(dx)
        while left > 1e-6:
            step = min(1.0, left)
            nx = self.x + sx * step
            if not self._solid_at(nx, self.y):
                self.x = nx
            elif self.on_ground and not self._solid_at(nx, self.y - T) and not self._solid_at(self.x, self.y - T):
                self.x, self.y = nx, self.y - T
            else:
                self.vx = 0.0
                break
            left -= step
        # vertical
        dy = self.vy * dt
        sy = 1.0 if dy > 0 else -1.0
        left = abs(dy)
        landed = False
        while left > 1e-6:
            step = min(1.0, left)
            ny = self.y + sy * step
            if not self._solid_at(self.x, ny):
                self.y = ny
            else:
                if sy > 0:
                    landed = True
                self.vy = 0.0
                break
            left -= step
        was_ground = self.on_ground
        self.on_ground = landed or (self.vy >= 0 and self._solid_at(self.x, self.y + 0.5))
        if landed and not was_ground:
            self._land()
        elif self.on_ground:
            self.fall_peak = self.y
        elif self.vy < 0:
            self.fall_peak = self.y

    def _land(self) -> None:
        fell = (self.y - self.fall_peak) / T
        if fell > 9.5 and not self.in_water:
            dmg = (fell - 9.5) * 5.5
            self.hurt(dmg, "fall")
            self.emit("thud", power=min(1.0, fell / 20))
        elif fell > 1.5:
            self.emit("land")
        self.fall_peak = self.y

    # ------------------------------------------------------------------ survival
    def _survival(self, dt: float) -> None:
        w = self.world
        if self.in_lava:
            self.hurt(32.0 * dt * (1.0 - self.inv.lava_resist()), "lava", silent=True)
        # touching a damaging block (cactus)
        x0, x1 = int((self.x - W_PX / 2 - 1) // T), int((self.x + W_PX / 2 + 1) // T)
        y0, y1 = int((self.y - H_PX) // T), int((self.y - 1) // T)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                d = w.reg.block(w.get(tx, ty)).get("damage")
                if d:
                    self.hurt(d * dt * 1.6, "cactus", silent=True, force=True)
        self.hunger = max(0.0, self.hunger - HUNGER_RATE * dt)
        if self.hunger <= 0:
            self.hurt(1.2 * dt, "hunger", silent=True, force=True)
        elif self.hunger > 55 and self.hp < MAX_HP:
            self.hp = min(MAX_HP, self.hp + 1.2 * dt)

    def hurt(self, amount: float, source: str = "", silent: bool = False, force: bool = False) -> None:
        if self.dead or amount <= 0:
            return
        if not force and self.invuln > 0 and source in ("creature",):
            return
        if source in ("creature", "fall"):
            amount = max(1.0, amount - self.inv.defense() * (0.9 if source == "creature" else 0.3))
        self.hp -= amount
        if not silent:
            self.invuln = 0.5 if source == "creature" else self.invuln
            self.emit("hurt", amount=amount, source=source)
        if self.hp <= 0:
            self.die(source)

    def die(self, source: str) -> None:
        self.dead = True
        self.stats["deaths"] += 1
        lost = []
        for i, s in enumerate(self.inv.slots):
            if s:
                n = max(1, int(s[1] * 0.3)) if s[1] > 1 else (1 if self.rng.chance(0.3) else 0)
                if n:
                    lost.append((s[0], n))
                    s[1] -= n
                    if s[1] <= 0:
                        self.inv.slots[i] = None
        for item, n in lost:
            self.world.drops.append(Drop(self.x, self.y - 6, item, n, self.rng.uniform(-30, 30), -60))
        self.emit("died", source=source, lost=len(lost))

    def respawn(self) -> None:
        self.dead = False
        self.hp = MAX_HP * 0.6
        self.hunger = max(self.hunger, 45.0)
        self.x, self.y = self.spawn
        self.vx = self.vy = 0.0
        self.fall_peak = self.y
        self.invuln = 1.5
        self.mine_pos = None

    def eat(self, item: str) -> bool:
        food = self.world.reg.items[item].get("food")
        if not food or self.hunger >= MAX_HUNGER - 1 and food.get("heal", 0) <= 0:
            return False
        self.hunger = min(MAX_HUNGER, self.hunger + food["hunger"])
        self.hp = max(1.0, min(MAX_HP, self.hp + food.get("heal", 0)))
        return True

    # ------------------------------------------------------------------ actions on the world
    def tile_in_reach(self, tx: int, ty: int) -> bool:
        cx, cy = self.x / T, (self.y - H_PX / 2) / T
        return (tx + 0.5 - cx) ** 2 + (ty + 0.5 - cy) ** 2 <= REACH ** 2

    def mine(self, dt: float, tx: int, ty: int) -> list[tuple[str, int]]:
        """Hold-to-mine: progress accumulates while the same tile is targeted.  Returns dropped items on completion."""
        w = self.world
        if not self.tile_in_reach(tx, ty):
            self.mine_pos, self.mine_t = None, 0.0
            return []
        tool = self.tool()
        ok, why = w.can_break(tx, ty, tool)
        if not ok:
            if self.mine_pos != (tx, ty):
                self.emit("cannot_mine", why=why)
            self.mine_pos = (tx, ty)
            self.mine_t = 0.0
            return []
        if self.mine_pos != (tx, ty):
            self.mine_pos, self.mine_t = (tx, ty), 0.0
        need = w.break_time(tx, ty, tool)
        self.mine_t += dt
        if self.mine_t >= need:
            block = w.reg.block(w.get(tx, ty))
            drops = w.break_block(tx, ty, self.rng)
            self.stats["mined"] += 1
            self.emit("broke", x=tx, y=ty, block=block["id"], sound=block.get("sound", "stone"))
            for item, n in drops:
                w.drops.append(Drop(tx * T + 4, ty * T + 4, item, n, self.rng.uniform(-24, 24), -50))
            self.mine_pos, self.mine_t = None, 0.0
            return drops
        return []

    def mine_progress(self) -> float:
        if not self.mine_pos:
            return 0.0
        need = self.world.break_time(*self.mine_pos, self.tool())
        return min(1.0, self.mine_t / need) if need > 0 else 1.0

    def use(self, tx: int, ty: int, blockers=()) -> str:
        """Use the held item on a tile: place a block, plant, till, eat, scoop or pour water.  Returns what happened."""
        w = self.world
        reg = w.reg
        item = self.inv.held()
        if not item:
            return ""
        it = reg.items[item]
        if it.get("food"):
            if self.eat(item):
                self.inv.take_slot(self.inv.selected)
                self.emit("eat", item=item)
                return "eat"
            return ""
        if not self.tile_in_reach(tx, ty):
            return ""
        if it.get("liquid") is not None:
            return self._bucket(it, tx, ty)
        tool = it.get("tool")
        if tool and tool.get("type") == "hoe":
            name = w.name(tx, ty)
            if name in ("dirt", "grass") and w.get(tx, ty - 1) in (K.AIR, K.TALLGRASS, K.FLOWER):
                w.set(tx, ty, K.FARMLAND)
                if w.get(tx, ty - 1) in (K.TALLGRASS, K.FLOWER):
                    w.set(tx, ty - 1, K.AIR)
                self.emit("till", x=tx, y=ty)
                return "till"
            return ""
        place = it.get("place")
        if place:
            n = reg.bid(place)
            if w.place_block(tx, ty, n, blockers):
                self.inv.take_slot(self.inv.selected)
                self.stats["placed"] += 1
                self.emit("placed", x=tx, y=ty, block=place, sound=reg.block(n).get("sound", "stone"))
                return "place"
            return ""
        return ""

    def _bucket(self, it: dict, tx: int, ty: int) -> str:
        w = self.world
        kind = it["liquid"]
        if kind == "empty":
            a, lava = w.liquid(tx, ty)
            if a > 0 and not lava:
                # scoop the whole connected column cell: one cell must hold a full bucket (8 units)
                if a >= 8 or self._gather(tx, ty):
                    w.set_liquid(tx, ty, 0)
                    self.inv.slots[self.inv.selected] = ["water_bucket", 1]
                    self.emit("scoop")
                    return "scoop"
            return ""
        if kind == "water":
            cur = w.reg.block(w.get(tx, ty))
            if not cur["solid"] and not w.liquid(tx, ty)[1]:
                w.set_liquid(tx, ty, 8)
                self.inv.slots[self.inv.selected] = ["bucket", 1]
                self.emit("pour")
                return "pour"
        return ""

    def _gather(self, tx: int, ty: int) -> bool:
        """Combine neighbouring partial water cells into a full bucket (leaves the pond a little lower)."""
        w = self.world
        total = 0
        cells = []
        for dx in (-2, -1, 0, 1, 2):
            a, lava = w.liquid(tx + dx, ty)
            if a and not lava:
                cells.append((tx + dx, a))
                total += a
        if total < 8:
            return False
        need = 8
        for x, a in sorted(cells, key=lambda c: abs(c[0] - tx)):
            take = min(a, need)
            w.set_liquid(x, ty, a - take)
            need -= take
            if need == 0:
                break
        w.set_liquid(tx, ty, w.liquid(tx, ty)[0])
        return True

    def attack_damage(self) -> float:
        item = self.inv.held()
        if not item:
            return 1.5
        tool = self.world.reg.items[item].get("tool")
        return float(tool.get("damage", 1.5)) if tool else 1.5

    def interact_block(self, tx: int, ty: int) -> str | None:
        """Which interaction a click on tile (tx, ty) would trigger, if any."""
        if not self.tile_in_reach(tx, ty):
            return None
        return self.world.reg.block(self.world.get(tx, ty)).get("interact")

    def toggle_door(self, tx: int, ty: int) -> bool:
        w = self.world
        n = w.get(tx, ty)
        if n == K.DOOR_CLOSED:
            w.set(tx, ty, K.DOOR_OPEN)
            return True
        if n == K.DOOR_OPEN:
            r = (tx * T, ty * T, tx * T + T, ty * T + T)
            px0, py0, px1, py1 = self.rect
            if px0 < r[2] and px1 > r[0] and py0 < r[3] and py1 > r[1]:
                return False
            w.set(tx, ty, K.DOOR_CLOSED)
            return True
        return False

    def sleep(self, tx: int, ty: int) -> str:
        """Use a bed: set the respawn point; at night skip to dawn when nothing hostile is near."""
        self.spawn = (tx * T + T / 2, (ty + 1) * T)
        return "spawn_set"
