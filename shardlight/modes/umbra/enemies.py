"""The three things in the ward, each with its own senses and its own weakness.

* **Hark** - eyeless, hears.  Investigates sound, hunts on loud or repeated noise, can be lured with a throw, recoils
  from very loud noise, pounds locked doors until they break.  Walking slowly makes you nearly inaudible.
* **Stillwatch** - sees only what is *lit*.  Stops dead in a flashlight beam (and recoils if you hold it there), cannot
  open doors, will not cross a Lantern Ward.
* **Understudy** - a patient searcher.  Visits rooms one by one and checks hiding places; notices doors that were
  moved and containers that were emptied; remembers where you hide (bounded adaptation) and occasionally mimics a
  sound you made.

Enemies act on their own senses and memory (``core.ai.Memory``): none of them is told where the player is.
"""
from __future__ import annotations

import math

from ...core.ai import Evidence, Memory, VisionCone
from .consts import TILE
from .props import PROP_DEFS

KILL_RANGE = 1.0


def make_enemy(game, kind: str, idx: int, x: float, y: float):
    cls = {"hark": Hark, "stillwatch": Stillwatch, "understudy": Understudy}[kind]
    return cls(game, kind, idx, x, y)


class Enemy:
    can_open = True
    breaker = False

    def __init__(self, game, kind: str, idx: int, x: float, y: float):
        self.g = game
        self.kind = kind
        self.idx = idx
        self.x, self.y = x, y
        self.home = (x, y)
        self.facing = 0.0
        self.state = "patrol"
        self.timer = 0.0
        self.path: list[tuple[int, int]] = []
        self.path_goal: tuple[float, float] | None = None
        self.repath_t = 0.0
        self.memory = Memory(decay_per_s=game.cat.enemy_stat(kind, "memory_decay", 0.1))
        self.atk_cd = 0.0
        self.windup = 0.0
        self.stun = 0.0
        self.door_t = 0.0
        self.seen_facts: set[str] = set()
        self.stats = dict(game.cat.enemy(kind)["stats"])
        self.rng = game.rng.child("enemy", kind, idx)
        self.directed = False                    # the director sent this one
        self.moving = False
        self.trail: list[tuple[float, float]] = []

    # ------------------------------------------------------------------ plumbing
    def reset(self) -> None:
        self.x, self.y = self.home
        self.state = "patrol"
        self.path = []
        self.timer = 0.0
        self.stun = 0.0
        self.windup = 0.0
        self.directed = False
        self.memory.best = None

    def calm(self) -> None:
        """Stand down (the director fairness valve): give up the chase and go back to patrolling."""
        self.state = "patrol"
        self.path = []
        self.directed = False
        self.memory.best = None
        self.windup = 0.0

    def hunting(self) -> bool:
        return self.state in ("hunt", "rush") or (self.directed and self.state in ("investigate", "stalk"))

    def stat(self, k: str, d: float = 0.0) -> float:
        v = float(self.stats.get(k, d))
        diff = {"story": 0.88, "standard": 1.0, "hard": 1.12}.get(self.g.difficulty, 1.0)
        if k.startswith("speed_"):
            return v * diff
        if k.startswith("reaction"):
            return v / diff
        return v

    def fact(self, event: str) -> None:
        """Record a journal habit line the first time this behaviour is witnessed by the player."""
        e = self.g.cat.enemy(self.kind)
        for f in e.get("facts", []):
            if f["event"] == event and f["id"] not in self.seen_facts:
                self.seen_facts.add(f["id"])
                key = f"{self.kind}:{f['id']}"
                if key not in self.g.journal["facts"]:
                    self.g.journal["facts"].append(key)
                    self.g.say("fact", key=key, text=f["text"], who=self.kind)

    def dist_player(self) -> float:
        p = self.g.p
        return math.hypot(p.x - self.x, p.y - self.y)

    def hear(self, noise) -> None:
        pass

    # ------------------------------------------------------------------ movement
    def goto(self, pos: tuple[float, float]) -> bool:
        self.path_goal = pos
        pth = self.g.path((self.x, self.y), pos, self.can_open, breaker=self.breaker)
        if pth is None:
            self.path = []
            return False
        self.path = pth[1:] if len(pth) > 1 else []
        return True

    def follow(self, dt: float, speed: float) -> bool:
        """Advance along the path; returns True when it has arrived (or has none)."""
        self.moving = False
        if self.stun > 0 or self.windup > 0:
            return False
        if not self.path:
            return True
        cx, cy = self.path[0]
        tx, ty = (cx + 0.5) * TILE, (cy + 0.5) * TILE
        # a closed door in the way
        g = self.g
        if g.lv.grid[cy, cx] == 3 and (cx, cy) in g.door_at:
            d = g.doors[g.door_at[(cx, cy)]]
            if not d.passable:
                return self._at_door(dt, d)
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        step = speed * dt
        if dist <= step:
            self.x, self.y = tx, ty
            self.path.pop(0)
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step
            self.facing = math.degrees(math.atan2(dy, dx))
            self.moving = True
        return not self.path

    def _at_door(self, dt: float, d) -> bool:
        g = self.g
        if d.locks or d.gate:
            if self.breaker and not d.gate:
                self.door_t += dt
                if self.door_t >= 1.1:
                    self.door_t = 0.0
                    d.bangs += 1
                    cx, cy = g.lv.doors[d.id].cells[0]
                    g.emit_noise("door_bang", (cx + 0.5) * TILE, (cy + 0.5) * TILE, source=self.kind)
                    self.fact("hark_locked")
                    if d.bangs >= int(self.stat("bang_to_break", 6)):
                        d.broken = True
                        d.open = 1.0
                        g.emit_noise("door_break", (cx + 0.5) * TILE, (cy + 0.5) * TILE, source=self.kind)
                        g.touch()
            else:
                self.path = []
            return False
        if not self.can_open:
            self.path = []
            self.fact("watch_door")
            return False
        self.door_t += dt
        if self.door_t >= self.stat("door_time", 0.9):
            self.door_t = 0.0
            g.set_door(d, True, False, self.kind)
        return False

    # ------------------------------------------------------------------ the touch
    def try_attack(self, dt: float, reach: float) -> None:
        g, p = self.g, self.g.p
        self.atk_cd = max(0.0, self.atk_cd - dt)
        if p.dead or p.invuln > 0 or self.stun > 0 or g.in_safe_room():
            self.windup = 0.0
            return
        if self.windup > 0:
            self.windup -= dt
            if self.windup <= 0:
                if self.dist_player() <= reach * TILE * 1.45 and p.hiding is None:
                    p.hp -= 1
                    p.invuln = 1.6
                    self.atk_cd = self.stat("attack_cooldown", 4.0)
                    g.say("hit", by=self.kind, hp=p.hp)
                    g.emit_noise("hit", p.x, p.y, source="player")
                    self.stun = 0.6
                    if p.hp <= 0:
                        g.die(self.kind)
                else:
                    self.atk_cd = 0.6
            return
        if self.atk_cd <= 0 and p.hiding is None and self.dist_player() <= reach * TILE:
            self.windup = max(0.2, self.stat("windup", 0.35))
            g.say("windup", by=self.kind)

    # ------------------------------------------------------------------ ward
    def flee_ward(self, dt: float, speed: float) -> bool:
        g = self.g
        for w in g.wards:
            if math.hypot(self.x - w.x, self.y - w.y) < w.radius * TILE * 1.15:
                ang = math.atan2(self.y - w.y, self.x - w.x)
                nx, ny = self.x + math.cos(ang) * speed * dt, self.y + math.sin(ang) * speed * dt
                if not g.solid_cell(g.cell_of(nx, ny)):
                    self.x, self.y = nx, ny
                self.path = []
                self.facing = math.degrees(ang)
                self.fact("watch_warded" if self.kind == "stillwatch" else "hark_ward" if self.kind == "hark" else "under_ward")
                return True
        return False

    def update(self, dt: float) -> None:
        self.stun = max(0.0, self.stun - dt)
        self.memory.update(dt)


# ====================================================================================== Hark
class Hark(Enemy):
    breaker = True

    def __init__(self, *a):
        super().__init__(*a)
        self.pending: tuple[tuple[float, float], float, float] | None = None
        self.search_left = 0
        self.search_center = self.home
        self.recent: list[float] = []
        self.route: list[int] = []

    def reset(self) -> None:
        super().reset()
        self.pending = None

    def hear(self, n) -> None:
        if n.source in ("hark",) or self.state == "recoil":
            return
        d = math.hypot(n.pos[0] - self.x, n.pos[1] - self.y)
        d += self.g.occlusion(n.pos, (self.x, self.y))
        reach = n.loudness * self.stat("hearing", 1.0)
        if d > reach:
            return
        inten = 1.0 - d / max(1.0, reach)
        loud_tiles = n.loudness / TILE
        if loud_tiles >= self.stat("panic_loudness", 12.0) and d < n.loudness * 0.7:
            self.state = "recoil"
            self.timer = self.stat("stun", 1.8)
            self.path = []
            self.pending = (n.pos, inten, 0.0)
            self.fact("hark_panic")
            return
        if inten < 0.1:
            if n.kind == "step" and n.source == "player" and d < 2.2 * TILE:
                self.fact("hark_missed")                  # a careful step passed within two tiles and it did not turn
            return
        react = self.rng.uniform(self.stat("reaction_min", 0.45), self.stat("reaction_max", 0.85))
        if self.pending is None or inten > self.pending[1]:
            self.pending = (n.pos, inten, self.g.time + react)
        self.fact("hark_heard")
        if n.kind == "thrown_default":
            self.fact("hark_lured")
        if n.source == "player" and n.kind == "step" and n.loudness < 3.0 * TILE:
            pass

    def update(self, dt: float) -> None:
        super().update(dt)
        g, p = self.g, self.g.p
        if self.flee_ward(dt, self.stat("speed_hunt", 70) * 0.7):
            return
        if self.pending and g.time >= self.pending[2] and self.state != "recoil":
            pos, inten, _ = self.pending
            self.pending = None
            self.memory.observe(Evidence("heard", pos, g.time, inten, "noise"))
            near_player = math.hypot(pos[0] - p.x, pos[1] - p.y) < 2.5 * TILE
            self.recent = [t for t in self.recent if g.time - t < 4.0] + [g.time]
            if (inten > 0.55 and near_player) or len(self.recent) >= 3 and near_player:
                self.state = "hunt"
            else:
                self.state = "investigate"
            self.directed = False
            self.goto(pos)
            self.timer = 0.0
        if self.state == "recoil":
            self.timer -= dt
            if self.timer <= 0:
                self.state = "investigate"
                tgt = self.memory.last_known() or (self.x, self.y)
                self.goto(tgt)
            return
        if self.state in ("hunt", "investigate"):
            speed = self.stat("speed_hunt", 70) if self.state == "hunt" else self.stat("speed_investigate", 38)
            self.repath_t -= dt
            if self.state == "hunt" and self.repath_t <= 0 and self.memory.last_known():
                self.repath_t = 0.5
                self.goto(self.memory.last_known())
            arrived = self.follow(dt, speed)
            if arrived:
                self.state = "listen"
                self.timer = self.stat("listen_time", 2.6)
                self.path = []
            elif self.state == "hunt" and self.g.time - (self.memory.best.time if self.memory.best else 0) > 4.0:
                self.state = "search"
                self.search_left = int(self.stat("search_points", 3))
                self.search_center = (self.x, self.y)
        elif self.state == "listen":
            self.timer -= dt
            self.facing += 90 * dt
            if self.timer <= 0:
                self.state = "search"
                self.search_left = int(self.stat("search_points", 3))
                c = self.memory.last_known() or (self.x, self.y)
                self.search_center = c
        elif self.state == "search":
            if not self.path:
                if self.search_left <= 0:
                    self.state = "patrol"
                    self.directed = False
                else:
                    self.search_left -= 1
                    ang = self.rng.uniform(0, math.tau)
                    r = self.rng.uniform(2.0, self.stat("search_radius", 5.5)) * TILE
                    pt = (self.search_center[0] + math.cos(ang) * r, self.search_center[1] + math.sin(ang) * r)
                    self.goto(pt)
                    if not self.path:
                        self.timer = 0.5
            else:
                self.follow(dt, self.stat("speed_investigate", 38))
        else:                                          # patrol
            if not self.path:
                self.timer -= dt
                if self.timer <= 0:
                    self._next_waypoint()
                    self.timer = self.rng.uniform(1.0, 3.0)
            else:
                self.follow(dt, self.stat("speed_patrol", 25))
        self.try_attack(dt, self.stat("touch_range", 1.05))

    def _next_waypoint(self) -> None:
        g = self.g
        rooms = [r for r in g.lv.rooms if r.role != "safe"]
        r = self.rng.pick(rooms)
        cells = [c for c in r.cells() if not g.solid_cell(c)]
        if cells:
            c = self.rng.pick(cells)
            self.goto(((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE))

    def director_investigate(self, pos: tuple[float, float]) -> None:
        self.directed = True
        self.state = "investigate"
        self.memory.observe(Evidence("heard", pos, self.g.time, 0.6, "director"))
        self.goto(pos)


# ================================================================================== Stillwatch
class Stillwatch(Enemy):
    can_open = False

    def __init__(self, *a):
        super().__init__(*a)
        self.beam_t = 0.0
        self.vision = VisionCone(range=self.stat("range", 14.0) * TILE, fov_deg=self.stat("fov", 130), peripheral_range=1.4 * TILE)
        self.lost_t = 0.0

    def reset(self) -> None:
        super().reset()
        self.beam_t = 0.0

    def hear(self, n) -> None:
        pass                                           # deaf: it only has eyes

    def _beam_on_me(self) -> bool:
        g, p = self.g, self.g.p
        d = self.dist_player()
        return (p.mode == "flash" and p.battery > 0 and d < 11.0 * TILE and g.in_flash_cone(self.x, self.y)
                and g.los((p.x, p.y), (self.x, self.y)) and p.hiding is None)

    def _sees_player(self) -> bool:
        g, p = self.g, self.g.p
        if p.dead or p.hiding is not None:
            return False
        d = self.dist_player()
        lit = g.player_lit()
        thr = self.stat("light_min", 0.16) * (0.5 if d < self.stat("gutter_range", 6.5) * TILE else 1.0)
        if lit < thr:
            return False
        if g.in_ward(p.x, p.y):
            return False
        return self.vision.sees((self.x, self.y), self.facing, (p.x, p.y), g.los, visibility=min(1.0, 0.5 + lit))

    def update(self, dt: float) -> None:
        super().update(dt)
        g, p = self.g, self.g.p
        if self.flee_ward(dt, self.stat("speed_rush", 44)):
            return
        if self.state == "recoil":
            self.timer -= dt
            away = math.atan2(self.y - p.y, self.x - p.x)
            nx, ny = self.x + math.cos(away) * self.stat("speed_rush", 44) * dt, self.y + math.sin(away) * self.stat("speed_rush", 44) * dt
            if not g.solid_cell(g.cell_of(nx, ny)):
                self.x, self.y = nx, ny
            if self.timer <= 0:
                self.state = "patrol"
                self.beam_t = 0.0
            return
        if self._beam_on_me():
            self.beam_t += dt
            self.state = "frozen"
            self.path = []
            self.fact("watch_froze")
            if self.beam_t >= self.stat("recoil_after", 6.5):
                self.state = "recoil"
                self.timer = self.stat("recoil_time", 5.0)
                self.fact("watch_recoiled")
            self.try_attack(dt, self.stat("touch_range", 0.95))
            return
        if self.state == "frozen":
            self.state = "patrol"
        self.beam_t = max(0.0, self.beam_t - dt * 0.6)
        if self._sees_player():
            self.memory.observe(Evidence("seen", (p.x, p.y), g.time, 1.0, "lit"))
            self.fact("watch_saw_lit")
            self.state = "rush"
            self.lost_t = 0.0
            self.repath_t -= dt
            if self.repath_t <= 0:
                self.repath_t = 0.35
                self.goto((p.x, p.y))
            self.facing = math.degrees(math.atan2(p.y - self.y, p.x - self.x))
            self.follow(dt, self.stat("speed_rush", 44))
        else:
            if self.state == "rush":
                self.lost_t += dt
                if self.lost_t > self.stat("unobserved_delay", 0.5) + 2.0:
                    self.state = "stalk"
            if self.state in ("rush", "stalk") and self.memory.last_known():
                if not self.path:
                    self.goto(self.memory.last_known())
                arrived = self.follow(dt, self.stat("speed_creep", 24))
                if arrived and not self.path:
                    self.state = "patrol"
            else:
                self.state = "patrol"
                if not self.path:
                    self.timer -= dt
                    if self.timer <= 0:
                        self._pick_lit_room()
                        self.timer = self.rng.uniform(2.0, 5.0)
                else:
                    self.follow(dt, self.stat("speed_creep", 24))
        self.try_attack(dt, self.stat("touch_range", 0.95))

    def _pick_lit_room(self) -> None:
        g = self.g
        lamps = g.lamp_cells()
        rooms = [r for r in g.lv.rooms if r.role != "safe"]
        weighted = []
        for r in rooms:
            lit = sum(1 for c in lamps if r.contains(c))
            weighted.append((1.0 + 3.0 * self.stat("light_greed", 1.0) * lit, r))
        r = self.rng.weighted([w[1] for w in weighted], [w[0] for w in weighted])
        cells = [c for c in r.cells() if not g.solid_cell(c)]
        if cells:
            c = self.rng.pick(cells)
            self.goto(((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE))

    def director_investigate(self, pos: tuple[float, float]) -> None:
        self.directed = True
        self.state = "stalk"
        self.memory.observe(Evidence("seen", pos, self.g.time, 0.6, "director"))
        self.goto(pos)


# ================================================================================ Understudy
class Understudy(Enemy):
    def __init__(self, *a):
        super().__init__(*a)
        self.vision = VisionCone(range=self.stat("range", 10.0) * TILE, fov_deg=self.stat("fov", 100), peripheral_range=self.stat("peripheral", 2.4) * TILE)
        self.suspicion: dict[int, float] = {}
        self.door_memory: dict[int, float] = {}
        self.room_queue: list[int] = []
        self.todo: list[int] = []                    # hiding prop indices to check in the current room
        self.check_t = 0.0
        self.cur_prop: int | None = None
        self.last_loot: set[int] = set()
        self.mimic_t = self.rng.uniform(25, 55)
        self.pending: tuple[tuple[float, float], float, float] | None = None
        self.checked_log: dict[str, int] = {"locker": 0, "bed": 0, "table": 0}

    def reset(self) -> None:
        super().reset()
        self.todo = []
        self.cur_prop = None
        self.pending = None

    # ------------------------------------------------------------------ adaptation (bounded; see Director)
    def hide_check_prob(self, kind: str) -> float:
        base = self.stat("hide_check_base", 0.3)
        level = self.g.director.level(f"habit_{kind}")
        return min(0.95, base + level)

    def hearing(self) -> float:
        return self.stat("hearing", 0.7) + self.g.director.level("listen_runs")

    def hear(self, n) -> None:
        if n.source in ("understudy",):
            return
        d = math.hypot(n.pos[0] - self.x, n.pos[1] - self.y) + self.g.occlusion(n.pos, (self.x, self.y))
        reach = n.loudness * self.hearing()
        if d > reach:
            return
        inten = 1.0 - d / max(1.0, reach)
        if inten < 0.15:
            return
        room = self.g.lv.room_of(self.g.cell_of(*n.pos))
        if room is not None:
            self.suspicion[room.id] = self.suspicion.get(room.id, 0.0) + 0.5 * inten
        if self.pending is None or inten > self.pending[1]:
            self.pending = (n.pos, inten, self.g.time + self.rng.uniform(0.5, 1.1))

    def _evidence(self) -> None:
        """Notice moved doors, emptied containers and fresh stains within sight."""
        g = self.g
        for d in g.lv.doors:
            cx, cy = d.cells[0]
            pos = ((cx + 0.5) * TILE, (cy + 0.5) * TILE)
            if math.hypot(pos[0] - self.x, pos[1] - self.y) < 8 * TILE and g.los((self.x, self.y), pos):
                st = g.doors[d.id]
                prev = self.door_memory.get(d.id)
                self.door_memory[d.id] = st.want
                if prev is not None and prev != st.want:
                    self.fact("under_door")
                    for rid in (d.a, d.b):
                        self.suspicion[rid] = self.suspicion.get(rid, 0.0) + self.stat("evidence_door", 0.55)
        for i, pr in enumerate(g.props):
            if pr.searched and i not in self.last_loot and PROP_DEFS[pr.kind].container:
                c = pr.cells[0]
                pos = ((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE)
                if math.hypot(pos[0] - self.x, pos[1] - self.y) < 7 * TILE and g.los((self.x, self.y), pos):
                    self.last_loot.add(i)
                    self.fact("under_loot")
                    self.suspicion[pr.room] = self.suspicion.get(pr.room, 0.0) + self.stat("evidence_loot", 0.5)

    def _sees_player(self) -> bool:
        g, p = self.g, self.g.p
        if p.dead or p.hiding is not None or g.in_ward(p.x, p.y):
            return False
        d = self.dist_player()
        lit = max(g.player_lit(), 0.0)
        if d > self.stat("peripheral", 2.4) * TILE and lit < 0.08:
            return False
        return self.vision.sees((self.x, self.y), self.facing, (p.x, p.y), g.los, visibility=min(1.0, 0.6 + lit))

    def update(self, dt: float) -> None:
        super().update(dt)
        g, p = self.g, self.g.p
        self._evidence()
        for rid in list(self.suspicion):
            self.suspicion[rid] = max(0.0, self.suspicion[rid] - dt * 0.01)
        if self.flee_ward(dt, self.stat("speed_hunt", 64) * 0.7):
            return
        # mimic: replay a sound the player made, from here
        self.mimic_t -= dt
        if self.mimic_t <= 0:
            self.mimic_t = self.rng.uniform(30, 70)
            if self.state in ("patrol", "search") and self.rng.random() < self.stat("mimic_chance", 0.12) * 3.0 and g.noise_log:
                kinds = [n.kind for n in g.noise_log if n.source == "player" and n.kind != "step"]
                if kinds:
                    k = self.rng.pick(kinds)
                    g.emit_noise(k, self.x, self.y, source="understudy")
                    g.say("mimic", x=self.x, y=self.y)
                    self.fact("under_habit")
        if self._sees_player():
            self.memory.observe(Evidence("seen", (p.x, p.y), g.time, 1.0, "sight"))
            self.state = "hunt"
            self.todo = []
            self.repath_t -= dt
            if self.repath_t <= 0:
                self.repath_t = 0.35
                self.goto((p.x, p.y))
            self.facing = math.degrees(math.atan2(p.y - self.y, p.x - self.x))
            self.follow(dt, self.stat("speed_hunt", 64))
            self.try_attack(dt, self.stat("touch_range", 1.0))
            return
        if self.pending and g.time >= self.pending[2]:
            pos, inten, _ = self.pending
            self.pending = None
            if self.state != "hunt":
                self.state = "investigate"
                self.todo = []
                self.memory.observe(Evidence("heard", pos, g.time, inten, "noise"))
                self.goto(pos)
        if self.state == "hunt":
            self.state = "search"
            last = self.memory.last_known() or (self.x, self.y)
            self.room_queue = self._rooms_near(last)
            self.path = []
        if self.state == "investigate":
            arrived = self.follow(dt, self.stat("speed_search", 36))
            if arrived:
                self._begin_room_search(g.lv.room_of(g.cell_of(self.x, self.y)))
        elif self.state == "check":
            self._check_hide(dt)
        elif self.state == "search":
            self._search(dt)
        else:
            self._patrol(dt)
        self.try_attack(dt, self.stat("touch_range", 1.0))

    # ------------------------------------------------------------------ room by room
    def _rooms_near(self, pos) -> list[int]:
        g = self.g
        rooms = [r for r in g.lv.rooms if not r.hall and r.role != "safe"]
        rooms.sort(key=lambda r: abs(r.center[0] * TILE - pos[0]) + abs(r.center[1] * TILE - pos[1]))
        return [r.id for r in rooms[:4]]

    def _patrol(self, dt: float) -> None:
        g = self.g
        self.state = "patrol"
        if not self.path:
            self.timer -= dt
            if self.timer > 0:
                return
            if not self.room_queue:
                rooms = [r.id for r in g.lv.rooms if not r.hall and r.role != "safe"]
                self.room_queue = self.rng.shuffled(rooms)
            # strongest suspicion first, else the route
            if self.suspicion and max(self.suspicion.values()) > 0.5:
                rid = max(self.suspicion, key=lambda k: self.suspicion[k])
                self.suspicion[rid] = 0.0
                if g.lv.rooms[rid].hall or g.lv.rooms[rid].role == "safe":
                    return
            else:
                rid = self.room_queue.pop(0)
            room = g.lv.rooms[rid]
            cells = [c for c in room.cells() if not g.solid_cell(c)]
            if cells:
                c = self.rng.pick(cells)
                self.goto(((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE))
                self.state = "patrol"
                self._target_room = rid
            self.timer = 0.5
        else:
            arrived = self.follow(dt, self.stat("speed_patrol", 29))
            if arrived:
                self._begin_room_search(g.lv.room_of(g.cell_of(self.x, self.y)))

    def _begin_room_search(self, room) -> None:
        g = self.g
        if room is None:
            self.state = "patrol"
            return
        props = [(i, pr) for i, pr in enumerate(g.props) if pr.room == room.id and PROP_DEFS[pr.kind].hide]
        todo = []
        for i, pr in props:
            kind = PROP_DEFS[pr.kind].hide
            if self.rng.random() < self.hide_check_prob(kind):
                todo.append(i)
        # the ones the player favours come first
        todo.sort(key=lambda i: -self.g.hide_log.get(PROP_DEFS[g.props[i].kind].hide, 0))
        self.todo = todo
        self.state = "check" if todo else "patrol"
        self.timer = 0.4
        if todo:
            self.fact("under_search")
            self.cur_prop = None

    def _check_hide(self, dt: float) -> None:
        g = self.g
        if self.cur_prop is None:
            if not self.todo:
                self.state = "patrol"
                return
            self.cur_prop = self.todo.pop(0)
            pr = g.props[self.cur_prop]
            c = pr.cells[0]
            self.goto(((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE + TILE * 0.0))
            self.check_t = 0.0
            return
        if self.path:
            self.follow(dt, self.stat("speed_search", 36))
            return
        self.check_t += dt
        self.facing += 120 * dt
        if self.check_t >= self.stat("search_time", 3.0) * 0.45:
            i = self.cur_prop
            self.cur_prop = None
            pr = g.props[i]
            kind = PROP_DEFS[pr.kind].hide
            self.checked_log[kind] = self.checked_log.get(kind, 0) + 1
            g.say("checked", i=i)
            if g.p.hiding == i:
                g.p.hp -= 1
                g.say("hit", by=self.kind, hp=g.p.hp)
                g.leave_hide()
                g.p.invuln = 1.2
                self.memory.observe(Evidence("seen", (g.p.x, g.p.y), g.time, 1.0, "found"))
                self.state = "hunt"
                if g.p.hp <= 0:
                    g.die(self.kind)

    def _search(self, dt: float) -> None:
        g = self.g
        if not self.path:
            if not self.room_queue:
                self.state = "patrol"
                return
            rid = self.room_queue.pop(0)
            room = g.lv.rooms[rid]
            cells = [c for c in room.cells() if not g.solid_cell(c)]
            if cells:
                c = self.rng.pick(cells)
                self.goto(((c[0] + 0.5) * TILE, (c[1] + 0.5) * TILE))
            self.timer = 0.0
        else:
            arrived = self.follow(dt, self.stat("speed_search", 36))
            if arrived:
                self._begin_room_search(g.lv.room_of(g.cell_of(self.x, self.y)))
                if self.state != "check":
                    self.state = "search"

    def director_investigate(self, pos: tuple[float, float]) -> None:
        self.directed = True
        self.state = "investigate"
        self.todo = []
        self.memory.observe(Evidence("heard", pos, self.g.time, 0.6, "director"))
        self.goto(pos)
