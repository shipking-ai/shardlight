"""Hollowmere simulation core: world/areas, clock, player, inventory and economy, spawn zones, persistence.

Pure Python + numpy (no pygame).  The scene drives ``Game.update(dt, intent)`` at a fixed 60 Hz and reads state to
draw.  Interactions live in :mod:`actions`, creatures in :mod:`combat`, townsfolk schedules in :mod:`npcs`.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ...core import log
from ...core.ai import Adaptation, AdaptiveController, PlayerModel
from ...core.nav import Grid, astar, smooth_path
from ...core.rng import Rng
from . import combat, npcs
from . import tiles as T
from .actions import ActionsMixin
from .catalog import Catalog
from .interiors import DUNGEONS, build_dungeon, build_interior
from .phys import fits, line_clear, move
from .quests import QuestLog
from .worldgen import generate
from .worldmap import WorldMap

LOG = log.get("verdant.sim")
HOUR_RATE = 24.0 / 600.0           # game hours per real second (a day lasts ten minutes)
START_HOUR = 7.5
SAVE_VERSION = 1
SKILLS = ("blade", "bow", "forage", "delve", "vigor")
SKILL_LABEL = {"blade": "Blade", "bow": "Bow", "forage": "Foraging", "delve": "Delving", "vigor": "Vigor"}
PLAYER_R = 0.28
WALK = 3.7
ROLL_SPEED = 8.0
ROLL_TIME = 0.28


def skill_level(xp: float) -> int:
    return min(10, int(math.sqrt(max(0.0, xp) / 12.0)))


@dataclass
class Intent:
    dx: float = 0.0
    dy: float = 0.0
    attack: bool = False
    roll: bool = False
    shoot: bool = False
    interact: bool = False
    quick: bool = False          # use the quick-slot consumable
    cycle: int = 0               # -1 / +1 cycles the quick slot
    hold_interact: bool = False


@dataclass
class Player:
    x: float = 0.0
    y: float = 0.0
    facing: float = 90.0         # degrees; 0 = east, 90 = south (screen space)
    hp: float = 60.0
    stamina: float = 100.0
    gold: int = 20
    inv: dict[str, int] = field(default_factory=dict)
    equip: dict[str, str] = field(default_factory=lambda: {"weapon": "rusty_sword", "body": "", "bow": ""})
    xp: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in SKILLS})
    quick: str = ""
    atk_t: float = 0.0
    atk_total: float = 0.4
    atk_hit: bool = False
    roll_t: float = 0.0
    roll_dx: float = 0.0
    roll_dy: float = 0.0
    inv_t: float = 0.0
    hurt_t: float = 0.0
    shoot_cd: float = 0.0
    stam_delay: float = 0.0
    fever: bool = False
    kx: float = 0.0
    ky: float = 0.0
    walk_phase: float = 0.0
    moving: bool = False
    gather: dict | None = None
    knock_t: float = 0.0


class Game(ActionsMixin):
    """Complete game state for one Hollowmere save."""

    def __init__(self, cat: Catalog, seed: int, diff: str = "standard", adapt_strength: float = 1.0, world: WorldMap | None = None):
        self.cat = cat
        self.seed = int(seed)
        self.diff = {"story": 0.65, "standard": 1.0, "hard": 1.35}.get(diff, 1.0)
        self.diff_name = diff
        self.rng = Rng(self.seed).child("verdant.game")
        self.over: WorldMap = world if world is not None else generate(self.seed, cat.templates)
        self.areas: dict[str, WorldMap] = {}
        self.area = "overworld"
        self.wm: WorldMap = self.over
        self.dirty_chunks: set[tuple[str, int, int]] = set()
        self._walkb: dict[str, bytearray] = {}
        self._grids: dict[str, Grid] = {}
        self.t = 0.0
        self.clock = START_HOUR
        self.day = 1
        self.flags: dict[str, Any] = {}
        self.kills: dict[str, int] = {}
        self.opened: set[str] = set()
        self.lit: set[tuple[int, int]] = set()
        self.depleted: dict[str, dict] = {}
        self.shop_stock: dict[str, dict[str, int]] = {}
        self.zone_state: dict[str, dict] = {}
        self.discovered = np.zeros((self.over.H, self.over.W), dtype=bool)
        self.known_sites: set[str] = set()
        self.respawn_point: tuple[float, float, str] = (0.0, 0.0, "overworld")
        self.ret: tuple[float, float] = (0.0, 0.0)
        self.hooks: list[tuple[str, dict]] = []
        self.toasts: list[str] = []
        self.sfx_queue: list[str] = []
        self.fx: list[dict] = []
        self.texts: list[dict] = []
        self.enemies: list[combat.Enemy] = []
        self.hazards: list[combat.Hazard] = []
        self.projectiles: list[combat.Projectile] = []
        self.drops: list[dict] = []
        self.npcs: dict[str, npcs.NpcState] = {}
        self.player_locked = False
        self.dead = False
        self.death_count = 0
        self.stats = {"steps": 0.0, "kills": 0, "gold_earned": 0, "lamps": 0, "chests": 0, "days": 1}
        self.p = Player()
        self.quests = QuestLog(cat)
        self.unlocks: Callable[[str], bool] = lambda _u: False
        self.model = PlayerModel(half_life=40.0)
        self.adapt = AdaptiveController(self.model, [
            Adaptation("guard", "melee", ("melee", "ranged"), 0.62, 5.0, 0.6),
            Adaptation("rush", "ranged", ("melee", "ranged"), 0.62, 5.0, 0.6),
        ], strength=adapt_strength, cooldown=10.0)
        self._timers = {"zones": 0.0, "visit": 0.0, "unlock": 0.0, "hour": -1}
        self._interact_cache: dict | None = None
        self.talking: str = ""
        self.last_msg = ""
        self.quest_flag_applied: set[str] = set()
        self._make_chest_index()
        npcs.init(self)

    # ------------------------------------------------------------------ construction
    @classmethod
    def new(cls, cat: Catalog, seed: int, diff: str = "standard", adapt_strength: float = 1.0, unlocks=None) -> "Game":
        g = cls(cat, seed, diff, adapt_strength)
        if unlocks:
            g.unlocks = unlocks
        sx, sy = g.over.start
        g.p.x, g.p.y = sx + 0.5, sy + 0.5
        g.respawn_point = (g.p.x, g.p.y, "overworld")
        g.p.hp = g.max_hp()
        for it, n in (("rusty_sword", 1), ("bread", 3), ("bandage", 2)):
            g.p.inv[it] = n
        g.p.quick = "bread"
        g.reveal(g.p.x, g.p.y, 10)
        g.refresh_unlocks()
        npcs.place_all(g)
        return g

    def has_unlock(self, u: str) -> bool:
        return bool(self.unlocks(u))

    # ------------------------------------------------------------------ world access
    def _make_chest_index(self) -> None:
        self.chests: dict[tuple[str, int, int], dict] = {}
        for m in self.over.markers:
            if m.kind == "chest":
                self.chests[("overworld", m.x, m.y)] = {"id": m.data.get("id", f"{m.site}.{m.x},{m.y}"), "loot": m.data.get("loot", "ruin_chest")}
        for c in self.over.caches:
            self.chests[("overworld", c["x"], c["y"])] = {"id": c["id"], "loot": c["loot"], "kind": c["kind"]}

    def area_map(self, area: str) -> WorldMap:
        if area == "overworld":
            return self.over
        wm = self.areas.get(area)
        if wm is not None:
            return wm
        if area.startswith("b:"):
            bid = area[2:]
            b = next((b for b in self.over.buildings if b.id == bid), None)
            wm = build_interior(b.enter if b else "cottage", self.seed, b.label if b else "")
            wm.name = wm.name
            wm.building_id = bid  # type: ignore[attr-defined]
        elif area.startswith("d:"):
            wm = build_dungeon(area[2:], self.seed)
            for m in wm.markers:
                if m.kind == "chest":
                    self.chests[(area, m.x, m.y)] = {"id": m.data["id"], "loot": m.data["loot"]}
        else:
            raise KeyError(area)
        self.areas[area] = wm
        self._apply_opened(area, wm)
        return wm

    def _apply_opened(self, area: str, wm: WorldMap) -> None:
        for m in wm.markers:
            if m.kind == "chest":
                self.chests[(area, m.x, m.y)] = {"id": m.data.get("id", f"{area}.{m.x},{m.y}"), "loot": m.data.get("loot", "ruin_chest")}

    def walkb(self, area: str | None = None) -> bytearray:
        area = area or self.area
        b = self._walkb.get(area)
        if b is None:
            b = bytearray(self.area_map(area).walk.astype(np.uint8).ravel().tobytes())
            self._walkb[area] = b
        return b

    def cell_changed(self, area: str, x: int, y: int) -> None:
        self.dirty_chunks.add((area, x >> 4, y >> 4))
        wm = self.area_map(area)
        wm.walk[y, x] = bool(T.GROUND_WALK[wm.ground[y, x]] and not T.OBJ_BLOCKS[wm.obj[y, x]] and not wm.bmask[y, x])
        b = self._walkb.get(area)
        if b is not None:
            b[y * wm.W + x] = 1 if wm.walk[y, x] else 0
        g = self._grids.get(area)
        if g is not None:
            g.blocked[y][x] = 0 if wm.walk[y, x] else 1

    def grid(self, area: str | None = None) -> Grid:
        area = area or self.area
        g = self._grids.get(area)
        if g is None:
            wm = self.area_map(area)
            g = Grid(wm.W, wm.H)
            walk = wm.walk
            for y in range(wm.H):
                row = g.blocked[y]
                wy = walk[y]
                for x in range(wm.W):
                    if not wy[x]:
                        row[x] = 1
                crow = g.cost[y]
                gr = wm.ground[y]
                for x in range(wm.W):
                    if wy[x]:
                        crow[x] = float(T.GROUND_COST_ARR[gr[x]]) if gr[x] < len(T.GROUND_NAMES) else 1.0
            self._grids[area] = g
        return g

    def invalidate_walk(self, area: str) -> None:
        self._walkb.pop(area, None)
        self._grids.pop(area, None)

    def path(self, area: str, a: tuple[float, float], b: tuple[float, float], max_nodes: int = 2500) -> list[tuple[float, float]] | None:
        g = self.grid(area)
        sa = g.nearest_walkable((int(a[0]), int(a[1])), 3)
        sb = g.nearest_walkable((int(b[0]), int(b[1])), 3)
        if sa is None or sb is None:
            return None
        pth = astar(g, sa, sb, True, max_nodes)
        if not pth:
            return None
        pth = smooth_path(g, pth)
        return [(c[0] + 0.5, c[1] + 0.5) for c in pth[1:]]

    def los(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        wm = self.wm
        return line_clear(self.walkb(), wm.W, wm.H, a[0], a[1], b[0], b[1])

    # ------------------------------------------------------------------ time
    @property
    def hour(self) -> float:
        return self.clock

    def abs_time(self) -> float:
        return (self.day - 1) * 24.0 + self.clock

    def daylight(self) -> float:
        h = self.clock
        if self.wm.dark and self.area != "overworld":
            return 0.0
        if h < 5.0 or h >= 20.5:
            return 0.0
        if h < 7.5:
            return (h - 5.0) / 2.5
        if h < 18.0:
            return 1.0
        return 1.0 - (h - 18.0) / 2.5

    def is_night(self) -> bool:
        return self.daylight() < 0.35

    def time_text(self) -> str:
        h = int(self.clock)
        m = int((self.clock - h) * 60) // 10 * 10
        return f"Day {self.day}  {h:02d}:{m:02d}"

    def advance_hours(self, hours: float) -> None:
        end = self.abs_time() + hours
        while self.abs_time() < end - 1e-6:
            step = min(0.25, end - self.abs_time())
            self._advance_clock(step)
            npcs.update(self, 0.0, teleport=True)

    def _advance_clock(self, hrs: float) -> None:
        prev = self.clock
        self.clock += hrs
        if self.clock >= 24.0:
            self.clock -= 24.0
            self.day += 1
            self.stats["days"] = self.day
            self.on_new_day()
        for mark, fn in ((6.0, self._dawn), (18.5, self._dusk)):
            if (prev < mark <= self.clock) or (prev > self.clock and (mark > prev or mark <= self.clock)):
                fn()

    def on_new_day(self) -> None:
        for sid, stock in self.shop_stock.items():
            sh = self.cat.shop(sid)
            if not sh:
                continue
            for e in sh["stock"]:
                base = e["qty"]
                cur = stock.get(e["item"], base)
                if cur < base:
                    stock[e["item"]] = min(base, cur + max(1, math.ceil(base * 0.34)))
        for k in list(self.depleted):
            pass

    def _dawn(self) -> None:
        for (x, y) in list(self.lit):
            self.set_obj("overworld", x, y, T.O["lamp"])
        self.lit.clear()
        self.toast("Dawn. The lamps go out.")

    def _dusk(self) -> None:
        if self.flags.get("debt_repaid"):
            n = 0
            for lamp in self.over.lamps:
                if self.over.obj[lamp["y"], lamp["x"]] == T.O["lamp"]:
                    self.set_obj("overworld", lamp["x"], lamp["y"], T.O["lamp_lit"])
                    self.lit.add((lamp["x"], lamp["y"]))
                    n += 1
            if n:
                self.toast("The Lamplighters light the lamps.")

    def set_obj(self, area: str, x: int, y: int, oid: int) -> None:
        wm = self.area_map(area)
        wm.obj[y, x] = oid
        self.cell_changed(area, x, y)

    # ------------------------------------------------------------------ messaging
    def hook(self, name: str, **payload: Any) -> None:
        self.hooks.append((name, payload))

    def toast(self, text: str) -> None:
        self.toasts.append(text)
        self.last_msg = text

    def sfx(self, name: str) -> None:
        self.sfx_queue.append(name)

    def float_text(self, text: str, x: float, y: float, color=(255, 255, 255)) -> None:
        self.texts.append({"t": text, "x": x, "y": y, "c": color, "age": 0.0})

    def fx_add(self, kind: str, x: float, y: float, **kw: Any) -> None:
        if len(self.fx) < 200:
            self.fx.append({"k": kind, "x": x, "y": y, **kw})

    def set_flag(self, name: str, value: Any = True) -> None:
        self.flags[name] = value
        self.quests.on_flag(self)
        if name == "bridge_built":
            self.apply_flags()

    def apply_flags(self) -> None:
        if self.flags.get("bridge_built") and "kestrel_bridge" in self.over.features:
            self.over.apply_feature("kestrel_bridge", "built")
            f = self.over.features["kestrel_bridge"]
            for (x, y) in f.cells:
                self.cell_changed("overworld", x, y)
        elif "kestrel_bridge" in self.over.features:
            self.over.apply_feature("kestrel_bridge", "broken")
            for (x, y) in self.over.features["kestrel_bridge"].cells:
                self.cell_changed("overworld", x, y)

    def refresh_unlocks(self) -> None:
        if self.has_unlock("verdant.site.listening_stones") and not self.flags.get("stones_revealed"):
            self.flags["stones_revealed"] = True
            st = self.over.sites.get("listening_stones")
            if st:
                st.hidden = False
            if "listening_stones" in self.over.features:
                self.over.apply_feature("listening_stones", "revealed")
                x0, y0, w, h = self.over.sites["listening_stones"].rect
                self.over.recompute_walk(x0, y0, x0 + w, y0 + h)
                self.invalidate_walk("overworld")
            self.toast("The Listening Stones can now be found on the high moor.")
        if self.has_unlock("verdant.trade.beacon_caravans") and not self.flags.get("caravans"):
            self.flags["caravans"] = True
            self.toast("Beacon caravans now visit the shops.")

    # ------------------------------------------------------------------ player stats
    def skill(self, name: str) -> int:
        return skill_level(self.p.xp.get(name, 0.0))

    def max_hp(self) -> float:
        base = 60.0 + 5.0 * self.skill("vigor")
        return base * (0.85 if self.p.fever else 1.0)

    def armor(self) -> float:
        a = self.p.equip.get("body") or ""
        return float(self.cat.item(a).get("armor", 0)) if a else 0.0

    def weapon(self) -> dict:
        w = self.p.equip.get("weapon") or ""
        return self.cat.item(w) if w else {"name": "Fists", "dmg": 2, "reach": 1.0, "swing": 0.4}

    def bow(self) -> dict | None:
        w = self.p.equip.get("bow") or ""
        return self.cat.item(w) if w else None

    def add_skill_xp(self, name: str, xp: float) -> None:
        if name not in self.p.xp:
            return
        before = self.skill(name)
        self.p.xp[name] += xp
        after = self.skill(name)
        if after > before:
            self.toast(f"{SKILL_LABEL.get(name, name)} reached level {after}")
            self.sfx("verdant_levelup")
            if name == "vigor":
                self.p.hp = min(self.max_hp(), self.p.hp + 5)

    # ------------------------------------------------------------------ inventory
    def count(self, item: str) -> int:
        return int(self.p.inv.get(item, 0))

    def give(self, item: str, n: int = 1) -> None:
        if n <= 0:
            return
        self.p.inv[item] = self.count(item) + n
        d = self.cat.item(item)
        if d["kind"] == "consumable" and not self.p.quick:
            self.p.quick = item
        self.quests.on_item_change(self)

    def take(self, item: str, n: int = 1) -> bool:
        if self.count(item) < n:
            return False
        left = self.count(item) - n
        if left > 0:
            self.p.inv[item] = left
        else:
            self.p.inv.pop(item, None)
            if self.p.quick == item:
                self.p.quick = ""
            for slot in ("weapon", "body", "bow"):
                if self.p.equip.get(slot) == item and self.count(item) == 0:
                    pass
        return True

    def add_gold(self, n: int) -> None:
        self.p.gold += n
        if n > 0:
            self.stats["gold_earned"] += n

    def consumables(self) -> list[str]:
        return sorted(i for i, n in self.p.inv.items() if n > 0 and self.cat.item(i)["kind"] == "consumable")

    def cycle_quick(self, d: int) -> None:
        cs = self.consumables()
        if not cs:
            self.p.quick = ""
            return
        try:
            i = cs.index(self.p.quick)
        except ValueError:
            i = -1
        self.p.quick = cs[(i + d) % len(cs)]

    def use_item(self, item: str) -> str:
        d = self.cat.item(item)
        if self.count(item) <= 0:
            return ""
        k = d["kind"]
        if k == "consumable":
            if d.get("cure") == "fever" and not self.p.fever and self.p.hp >= self.max_hp() - 0.5 and not d.get("heal"):
                return "You are not ill."
            if self.p.hp >= self.max_hp() - 0.01 and not d.get("stamina") and d.get("cure") != "fever" or (
                    self.p.hp >= self.max_hp() - 0.01 and d.get("cure") == "fever" and not self.p.fever):
                return "You are already in good health."
            self.take(item, 1)
            heal = float(d.get("heal", 0))
            self.p.hp = min(self.max_hp(), self.p.hp + heal)
            self.p.stamina = min(100.0, self.p.stamina + float(d.get("stamina", 0)))
            if d.get("cure") == "fever" and self.p.fever:
                self.p.fever = False
                self.toast("The fever breaks.")
            self.float_text(f"+{int(heal)}", self.p.x, self.p.y - 0.8, (120, 255, 150))
            self.sfx("verdant_heal")
            return f"Used {d['name']}."
        if k in ("weapon", "armor"):
            slot = d.get("slot", "weapon")
            old = self.p.equip.get(slot, "")
            self.p.equip[slot] = item
            self.sfx("verdant_equip")
            return f"Equipped {d['name']}." + (f" ({self.cat.item(old)['name']} stowed.)" if old and old != item else "")
        return f"{d['name']}: nothing to do with it here."

    def unequip(self, slot: str) -> None:
        self.p.equip[slot] = ""

    def sell_price(self, item: str, shop: dict) -> int:
        d = self.cat.item(item)
        if d["kind"] == "quest" or d.get("value", 0) <= 0:
            return 0
        if d["kind"] not in shop.get("buys", []):
            return 0
        return max(1, int(d["value"] * 0.5))

    def buy_price(self, item: str, shop: dict) -> int:
        d = self.cat.item(item)
        return max(1, int(round(d.get("value", 1) * shop.get("markup", 1.2))))

    def item_ok(self, iid: str) -> bool:
        u = self.cat.item(iid).get("unlock")
        return not u or self.has_unlock(u)

    def shop_items(self, sid: str) -> list[tuple[str, int, int]]:
        sh = self.cat.shop(sid)
        if not sh:
            return []
        stock = self.shop_stock.setdefault(sid, {e["item"]: e["qty"] for e in sh["stock"]})
        out = [(e["item"], stock.get(e["item"], 0), self.buy_price(e["item"], sh)) for e in sh["stock"]]
        if self.flags.get("caravans"):
            for it in sh.get("caravan", []):
                stock.setdefault(it, 2)
                if self.item_ok(it):
                    out.append((it, stock.get(it, 0), self.buy_price(it, sh)))
        return out

    def buy(self, sid: str, item: str) -> str:
        sh = self.cat.shop(sid)
        if not sh:
            return "Closed."
        for it, qty, price in self.shop_items(sid):
            if it == item:
                if qty <= 0:
                    return "Sold out."
                if self.p.gold < price:
                    return "Not enough gold."
                self.p.gold -= price
                self.shop_stock[sid][item] = qty - 1
                self.give(item, 1)
                self.sfx("verdant_coin")
                return f"Bought {self.cat.item(item)['name']} for {price}."
        return "Not sold here."

    def sell(self, sid: str, item: str) -> str:
        sh = self.cat.shop(sid)
        if not sh:
            return "Closed."
        price = self.sell_price(item, sh)
        if price <= 0:
            return "They will not buy that."
        if self.count(item) <= 0:
            return "You have none."
        if self.p.equip.get(self.cat.item(item).get("slot", "")) == item and self.count(item) == 1:
            return "Unequip it first."
        self.take(item, 1)
        self.add_gold(price)
        stock = self.shop_stock.setdefault(sid, {e["item"]: e["qty"] for e in sh["stock"]})
        stock[item] = stock.get(item, 0) + 1
        self.sfx("verdant_coin")
        return f"Sold {self.cat.item(item)['name']} for {price}."

    def craft_ok(self, r: dict) -> bool:
        return all(self.count(i) >= n for i, n in r["inputs"].items()) and self.skill("delve") + self.skill("forage") >= 0 and (
            self.craft_level() >= r.get("skill", 0))

    def craft_level(self) -> int:
        return max(self.skill("delve"), self.skill("forage"), self.skill("blade") // 2)

    def craft(self, rid: str) -> str:
        r = self.cat.db.get("verdant.recipe", rid)
        if not r:
            return "Unknown recipe."
        if self.craft_level() < r.get("skill", 0):
            return f"Needs skill level {r['skill']}."
        if not all(self.count(i) >= n for i, n in r["inputs"].items()):
            return "Missing materials."
        for i, n in r["inputs"].items():
            self.take(i, n)
        self.give(r["out"], r.get("count", 1))
        self.add_skill_xp("delve" if r["station"] == "forge" else "forage", 4)
        self.sfx("verdant_craft")
        return f"Made {r.get('count', 1)} x {self.cat.item(r['out'])['name']}."

    # ------------------------------------------------------------------ fog of war
    def reveal(self, x: float, y: float, r: int = 9) -> None:
        if self.area != "overworld":
            return
        x0, x1 = max(0, int(x) - r), min(self.over.W, int(x) + r + 1)
        y0, y1 = max(0, int(y) - r), min(self.over.H, int(y) + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        self.discovered[y0:y1, x0:x1] |= (xx - x) ** 2 + (yy - y) ** 2 <= r * r

    def discovered_fraction(self) -> float:
        return float(self.discovered.mean())

    # ------------------------------------------------------------------ areas
    def enter_area(self, area: str, pos: tuple[float, float] | None = None) -> None:
        if self.area == "overworld" and area != "overworld":
            self.ret = (self.p.x, self.p.y)
        self.area = area
        self.wm = self.area_map(area)
        self.enemies = []
        self.hazards = []
        self.projectiles = []
        self.drops = [d for d in self.drops if d.get("area") == area]
        if pos is None:
            pos = (self.wm.start[0] + 0.5, self.wm.start[1] + 0.5)
        self.p.x, self.p.y = pos
        self.p.gather = None
        self._timers["zones"] = 0.0
        self.sfx("verdant_door")
        self.activate_zones(force=True)

    def leave_area(self) -> None:
        if self.area == "overworld":
            return
        self.enter_area("overworld", self.ret)

    # ------------------------------------------------------------------ spawn zones
    def zones(self) -> list[dict]:
        return self.wm.spawns if self.area != "overworld" else self.over.spawns

    def activate_zones(self, force: bool = False) -> None:
        night = self.is_night()
        P = self.p
        dungeon = self.area.startswith("d:")
        for z in self.zones():
            st = self.zone_state.setdefault(z["id"], {"active": False, "killed": 0, "respawn": 0.0, "dead": False})
            d = math.hypot(z["x"] + 0.5 - P.x, z["y"] + 0.5 - P.y)
            cfg = self.cat.enemy(z["enemy"])
            night_only = bool(cfg.get("night")) and not dungeon
            if st["active"]:
                if d > (60 if not dungeon else 999) or (night_only and not night):
                    self.enemies = [e for e in self.enemies if e.zone != z["id"] or e.hurt_total > 0 and False]
                    st["active"] = False
                continue
            if st["dead"]:
                if z.get("unique") or self.abs_time() < st["respawn"]:
                    continue
                st["dead"] = False
                st["killed"] = 0
            if (d <= 34 or dungeon and d <= 26) and (not night_only or night):
                n = max(0, int(z["count"]) - st["killed"])
                if n <= 0:
                    continue
                if z["enemy"] in ("bandit", "bandit_archer") and not z.get("unique"):
                    pass
                self._spawn_zone(z, n)
                st["active"] = True

    def _spawn_zone(self, z: dict, n: int) -> None:
        r = self.rng.child("spawn", z["id"], self.day)
        wm = self.wm
        for i in range(n):
            for _ in range(12):
                ang = r.random() * math.tau
                rad = r.random() * max(0.6, z.get("radius", 3))
                x, y = z["x"] + 0.5 + math.cos(ang) * rad, z["y"] + 0.5 + math.sin(ang) * rad
                if fits(self.walkb(), wm.W, wm.H, x, y, 0.35):
                    break
            else:
                x, y = z["x"] + 0.5, z["y"] + 0.5
            e = combat.Enemy(self, z["enemy"], x, y, z["id"], i, n)
            e.home = (z["x"] + 0.5, z["y"] + 0.5)
            self.enemies.append(e)
        # bounded adaptation: a melee-heavy player meets a few shielded bandits, handled in combat.assign_guard

    def enemy_died(self, e: "combat.Enemy") -> None:
        st = self.zone_state.get(e.zone)
        if st is not None:
            st["killed"] += 1
            alive = [o for o in self.enemies if o.zone == e.zone and not o.dead and o is not e]
            if not alive:
                st["dead"] = True
                st["active"] = False
                st["respawn"] = self.abs_time() + 36.0
        self.kills[e.kind] = self.kills.get(e.kind, 0) + 1
        self.stats["kills"] += 1
        if e.d["ai"] == "boss":
            self.flags[f"killed.{e.kind}"] = True
            self.toast(f"{e.d['name']} defeated.")
            self.sfx("verdant_boss_down")
        self.quests.on_kill(self, e.kind)
        self.quests.on_flag(self)

    # ------------------------------------------------------------------ update
    def update(self, dt: float, intent: Intent) -> None:
        if self.dead:
            return
        dt = min(dt, 0.05)
        self.t += dt
        P = self.p
        self._advance_clock(dt * HOUR_RATE)
        self._player_update(dt, intent)
        npcs.update(self, dt)
        combat.update(self, dt)
        self._pickups(dt)
        tm = self._timers
        tm["zones"] += dt
        if tm["zones"] >= 0.5:
            tm["zones"] = 0.0
            self.activate_zones()
        tm["visit"] += dt
        if tm["visit"] >= 1.0:
            tm["visit"] = 0.0
            self.quests.on_visit_tick(self)
            self._check_sites()
            self._regrow()
            self.adapt.update(self.t, 1.0)
            if self.p.fever:
                self.p.hp = max(1.0, self.p.hp - 0.4)
        tm["unlock"] += dt
        if tm["unlock"] >= 2.0:
            tm["unlock"] = 0.0
            self.refresh_unlocks()
        for t in self.texts:
            t["age"] += dt
        self.texts = [t for t in self.texts if t["age"] < 1.0]
        self.fx = [f for f in self.fx if (f.__setitem__("age", f.get("age", 0.0) + dt) or f["age"] < f.get("life", 0.5))]
        self.reveal(P.x, P.y, 9)

    def _check_sites(self) -> None:
        if self.area != "overworld":
            return
        for sid, s in self.over.sites.items():
            if s.hidden or sid in self.known_sites:
                continue
            fx, fy = s.front
            if math.hypot(self.p.x - fx, self.p.y - fy) < 14:
                self.known_sites.add(sid)
                self.toast(f"Discovered: {s.name}")
                self.hook("verdant.site_discovered", site=sid)

    def _player_update(self, dt: float, it: Intent) -> None:
        P = self.p
        wm = self.wm
        if self.player_locked:
            return
        P.atk_t = max(0.0, P.atk_t - dt)
        P.roll_t = max(0.0, P.roll_t - dt)
        P.inv_t = max(0.0, P.inv_t - dt)
        P.hurt_t = max(0.0, P.hurt_t - dt)
        P.shoot_cd = max(0.0, P.shoot_cd - dt)
        P.stam_delay = max(0.0, P.stam_delay - dt)
        P.knock_t = max(0.0, P.knock_t - dt)
        if P.stam_delay <= 0:
            P.stamina = min(100.0, P.stamina + (11.0 if P.fever else 24.0) * dt)
        if it.cycle:
            self.cycle_quick(it.cycle)
        if it.quick and P.quick:
            msg = self.use_item(P.quick)
            if msg:
                self.toast(msg)
        # input -> velocity
        mx, my = it.dx, it.dy
        mag = math.hypot(mx, my)
        if mag > 1:
            mx, my = mx / mag, my / mag
        walkb = self.walkb()
        speed = 0.0
        if P.roll_t > 0:
            dx, dy = P.roll_dx * ROLL_SPEED * dt, P.roll_dy * ROLL_SPEED * dt
            P.x, P.y, _ = move(walkb, wm.W, wm.H, P.x, P.y, dx, dy, PLAYER_R)
            speed = ROLL_SPEED
        else:
            if it.roll and P.stamina >= 18 and P.atk_t <= 0.12 and P.gather is None:
                dxr, dyr = (mx, my) if mag > 0.1 else (math.cos(math.radians(P.facing)), math.sin(math.radians(P.facing)))
                n = math.hypot(dxr, dyr) or 1
                P.roll_dx, P.roll_dy = dxr / n, dyr / n
                P.roll_t = ROLL_TIME
                P.inv_t = max(P.inv_t, ROLL_TIME + 0.05)
                P.stamina -= 18
                P.stam_delay = 0.5
                self.sfx("verdant_roll")
                self.model.record("roll", self.t)
            else:
                g = self.wm.speed_at(int(P.x), int(P.y)) or 1.0
                s = WALK * g * (0.45 if P.atk_t > 0 else 1.0) * (0.8 if P.fever else 1.0)
                if P.gather is not None:
                    s = 0.0
                if P.knock_t > 0:
                    P.x, P.y, _ = move(walkb, wm.W, wm.H, P.x, P.y, P.kx * dt, P.ky * dt, PLAYER_R)
                else:
                    P.x, P.y, _ = move(walkb, wm.W, wm.H, P.x, P.y, mx * s * dt, my * s * dt, PLAYER_R)
                speed = s * mag
            if mag > 0.1 and P.atk_t <= 0 and P.gather is None:
                P.facing = math.degrees(math.atan2(my, mx))
        P.moving = speed > 0.2 and mag > 0.1 or P.roll_t > 0
        if P.moving:
            P.walk_phase += dt * (9 if P.roll_t <= 0 else 14)
            self.stats["steps"] += speed * dt
        if P.gather is not None and (mag > 0.3 or P.roll_t > 0 or P.hurt_t > 0.3):
            P.gather = None
        # attacks
        if it.attack and P.atk_t <= 0 and P.roll_t <= 0 and P.stamina >= 8 and P.gather is None:
            w = self.weapon()
            P.atk_total = float(w.get("swing", 0.45))
            P.atk_t = P.atk_total
            P.atk_hit = False
            P.stamina -= 10 + float(w.get("dmg", 4)) * 0.4
            P.stam_delay = 0.55
            self.sfx("verdant_swing")
        if P.atk_t > 0 and not P.atk_hit and P.atk_t <= P.atk_total * 0.62:
            P.atk_hit = True
            combat.player_melee(self)
        if it.shoot and P.shoot_cd <= 0 and P.roll_t <= 0:
            combat.player_shoot(self)
        if it.interact:
            self.last_action = self.do_interact()
        if P.gather is not None:
            P.gather["t"] += dt
            if P.gather["t"] >= P.gather["need"]:
                self._finish_gather()
        # leave by stepping on a door
        if self.area != "overworld":
            ex = self.wm.exits.get("door")
            if ex and int(P.x) == ex[0] and int(P.y) == ex[1]:
                b = self.building_of(self.area)
                self.leave_area()
                if b:
                    self.p.x, self.p.y = b.front[0] + 0.5, b.front[1] + 0.5
                    self.p.facing = 90
        if self.p.hp <= 0 and not self.dead:
            self._die()

    last_action: dict | None = None

    def building_of(self, area: str):
        if not area.startswith("b:"):
            return None
        return next((b for b in self.over.buildings if b.id == area[2:]), None)

    def _pickups(self, dt: float) -> None:
        P = self.p
        keep = []
        for d in self.drops:
            d["age"] = d.get("age", 0.0) + dt
            if d.get("area") != self.area:
                keep.append(d)
                continue
            if d["age"] > 0.4 and math.hypot(d["x"] - P.x, d["y"] - P.y) < 0.9:
                if d["item"] == "gold":
                    self.add_gold(d["n"])
                    self.float_text(f"+{d['n']}g", P.x, P.y - 0.9, (255, 220, 100))
                else:
                    self.give(d["item"], d["n"])
                    self.float_text(f"+{d['n']} {self.cat.item(d['item'])['name']}", P.x, P.y - 0.9, (230, 230, 255))
                self.sfx("verdant_pickup")
                continue
            if d["age"] < 90:
                keep.append(d)
        self.drops = keep

    # ------------------------------------------------------------------ damage / death
    def hurt_player(self, dmg: float, sx: float, sy: float, knock: float = 3.5) -> bool:
        P = self.p
        if P.inv_t > 0 or self.dead:
            return False
        eff = max(1.0, dmg * self.diff * (1.0 - min(0.6, self.armor() * 0.055)))
        P.hp -= eff
        P.inv_t = 0.55
        P.hurt_t = 0.4
        ang = math.atan2(P.y - sy, P.x - sx)
        P.kx, P.ky = math.cos(ang) * knock * 2.4, math.sin(ang) * knock * 2.4
        P.knock_t = 0.14
        P.gather = None
        self.float_text(str(int(round(eff))), P.x, P.y - 0.9, (255, 90, 80))
        self.fx_add("hit", P.x, P.y, life=0.3, color=(255, 90, 80))
        self.sfx("verdant_hurt")
        self.model.record("hurt", self.t, 0.5)
        self.add_skill_xp("vigor", 0.8)
        if P.hp <= 0:
            P.hp = 0
        return True

    def _die(self) -> None:
        self.dead = True
        self.death_count += 1
        self.sfx("verdant_death")

    def respawn(self) -> None:
        P = self.p
        self.dead = False
        loss = int(P.gold * 0.1)
        P.gold -= loss
        x, y, area = self.respawn_point
        self.enter_area("overworld" if area == "overworld" else area, (x, y))
        P.hp = self.max_hp() * 0.6
        P.stamina = 100.0
        P.inv_t = 1.5
        P.fever = False
        P.gather = None
        self.advance_hours(2.0)
        self.toast(f"You wake near the last shrine. {loss} gold lost.")

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        P = self.p
        disc = np.packbits(self.discovered.ravel())
        return {
            "v": SAVE_VERSION, "seed": self.seed, "diff": self.diff_name, "area": self.area,
            "clock": round(self.clock, 4), "day": self.day, "t": round(self.t, 3),
            "p": {"x": P.x, "y": P.y, "facing": P.facing, "hp": P.hp, "stamina": P.stamina, "gold": P.gold, "inv": dict(P.inv),
                  "equip": dict(P.equip), "xp": dict(P.xp), "quick": P.quick, "fever": P.fever},
            "flags": dict(self.flags), "kills": dict(self.kills), "opened": sorted(self.opened),
            "lit": [list(c) for c in sorted(self.lit)], "depleted": self.depleted,
            "shops": {k: dict(v) for k, v in self.shop_stock.items()}, "zones": self.zone_state,
            "disc": base64.b64encode(disc.tobytes()).decode("ascii"), "known": sorted(self.known_sites),
            "respawn": list(self.respawn_point), "ret": list(self.ret), "stats": dict(self.stats),
            "quests": self.quests.to_dict(), "npcs": npcs.to_dict(self),
            "adapt": {"w": dict(self.model.weights), "t": self.model.t},
            "deaths": self.death_count,
        }

    @classmethod
    def from_dict(cls, cat: Catalog, raw: dict, unlocks=None, adapt_strength: float = 1.0) -> "Game | None":
        try:
            if raw.get("v") != SAVE_VERSION:
                return None
            g = cls(cat, int(raw["seed"]), raw.get("diff", "standard"), adapt_strength)
            if unlocks:
                g.unlocks = unlocks
            g.clock, g.day, g.t = float(raw["clock"]), int(raw["day"]), float(raw.get("t", 0))
            p = raw["p"]
            P = g.p
            P.x, P.y, P.facing, P.hp, P.stamina, P.gold = p["x"], p["y"], p["facing"], p["hp"], p["stamina"], int(p["gold"])
            P.inv = {k: int(v) for k, v in p["inv"].items() if cat.has_item(k)}
            P.equip = {s: (i if i in P.inv or not i else "") for s, i in p["equip"].items()}
            for s in ("weapon", "body", "bow"):
                P.equip.setdefault(s, "")
            P.xp = {k: float(p["xp"].get(k, 0.0)) for k in SKILLS}
            P.quick, P.fever = p.get("quick", ""), bool(p.get("fever", False))
            g.flags = dict(raw["flags"])
            g.kills = {k: int(v) for k, v in raw["kills"].items()}
            g.opened = set(raw["opened"])
            g.shop_stock = {k: {i: int(n) for i, n in v.items()} for k, v in raw["shops"].items()}
            g.zone_state = raw["zones"]
            g.known_sites = set(raw["known"])
            g.respawn_point = tuple(raw["respawn"])  # type: ignore[assignment]
            g.ret = tuple(raw["ret"])  # type: ignore[assignment]
            g.stats = dict(raw["stats"])
            g.death_count = int(raw.get("deaths", 0))
            bits = np.unpackbits(np.frombuffer(base64.b64decode(raw["disc"]), dtype=np.uint8))[: g.over.H * g.over.W]
            g.discovered = bits.reshape(g.over.H, g.over.W).astype(bool)
            g.depleted = {k: dict(v) for k, v in raw["depleted"].items()}
            g.quests.load(raw["quests"])
            g.refresh_unlocks()
            g.apply_flags()
            for k, v in g.depleted.items():
                a, x, y = k.split(":")
                g.set_obj(a, int(x), int(y), 0) if a == "overworld" else None
            for (x, y) in raw["lit"]:
                g.lit.add((x, y))
                g.set_obj("overworld", x, y, T.O["lamp_lit"])
            for k in g.opened:
                pass
            ad = raw.get("adapt", {})
            g.model.weights.update({k: float(v) for k, v in ad.get("w", {}).items()})
            g.model.t = float(ad.get("t", 0.0))
            g.area = "overworld"
            g.wm = g.over
            npcs.from_dict(g, raw.get("npcs", {}))
            area = raw.get("area", "overworld")
            try:
                if area != "overworld":
                    g.enter_area(area, (P.x, P.y))
                    g.p.x, g.p.y = p["x"], p["y"]
                    g.ret = tuple(raw["ret"])  # type: ignore[assignment]
                else:
                    g.activate_zones(force=True)
            except Exception:
                LOG.exception("could not restore area %s", area)
                g.area, g.wm = "overworld", g.over
                P.x, P.y = g.ret
            if g.p.hp <= 0:
                g.p.hp = g.max_hp()
            return g
        except Exception:
            LOG.exception("verdant save failed to load")
            return None
