"""The combat room: tiles, entities, hit resolution, projectiles, hazards, statuses, waves, rewards and props.

All simulation is tick based and deterministic given the room's RNG and the player's intents.  The scene only
feeds ``Intent`` objects, drains ``events`` for feedback (audio / particles / camera) and draws.
"""
from __future__ import annotations

import math
from collections import deque

from ....core import nav
from ....core.rng import Rng
from ..defs import Library
from . import levelgen as LG
from .brains import Enemy
from .entities import (ENEMY_TEAM, PLAYER_TEAM, Door, Entity, Ev, Hazard, Hitbox, Pickup, Projectile, Prop)
from .geometry import (angle_diff, angle_to, arc_hit, circle_hit, dist, move_and_collide, rect_hit, ring_hit,
                       segment_blocked, unit)
from .player import Intent, Player
from .run import Run
from .squad import Squad
from .status import STATUS_COLORS

TILE = LG.TILE
W_PX, H_PX = LG.W_T * TILE, LG.H_T * TILE
PERFECT_DODGE_WINDOW = 7
PERFECT_PARRY_WINDOW = 3
SHOCK_ARC_RANGE = 58.0


class Room:
    def __init__(self, run: Run, spec: LG.RoomSpec, floor: int, unlocked: dict | None = None, entry: str | None = None,
                 boss_factory=None) -> None:
        self.run = run
        self.lib: Library = run.lib
        self.spec = spec
        self.floor = floor
        self.rng = Rng(spec.seed).child("room", run.seed)
        self.unlocked = unlocked or {"boons": set(), "weapons": set(), "mods": set(), "flags": set()}
        self.t = 0
        self.tiles = spec.layout
        self.enemies: list[Enemy] = []
        self.hitboxes: list[Hitbox] = []
        self.projectiles: list[Projectile] = []
        self.hazards: list[Hazard] = []
        self.pickups: list[Pickup] = []
        self.props: list[Prop] = []
        self.events: list[Ev] = []
        self.telegraphs: list[tuple] = []
        self.ui_requests: list[tuple] = []
        self.hitstop = 0
        self.next_id = 1
        self.squad = Squad(self)
        self.trigger_cd: dict[tuple, int] = {}
        self.wave_idx = 0
        self.wave_timer = 60
        self.pending_spawns: list[tuple[str, bool, float, float, int]] = []
        self.combat_started = False
        self.cleared = spec.cleared or not (spec.waves or spec.boss)
        self.player_dead = False
        self.exit_request: tuple[str, int] | None = None
        self.boss: Enemy | None = None
        self.boss_defeated = False
        self.shield_t = 0
        self.last_dodge_side = 0
        self.recent_damage = 0.0
        self.stats = {"damage_dealt": 0.0, "kills": 0, "perfect_dodges": 0, "parries": 0, "hits_taken": 0}
        self.doors: dict[str, Door] = {}
        self.door_cells: dict[tuple[int, int], Door] = {}
        for side, target in spec.doors.items():
            d = Door(side, list(LG.DOOR_CELLS[side]), target, locked=False, hidden=side in spec.hidden,
                     kind="secret" if side in spec.hidden else "normal")
            self.doors[side] = d
            for c in d.cells:
                self.door_cells[c] = d
        self.nav_grid = self._build_nav()
        # player
        sx, sy = self._entry_pos(entry)
        self.player = Player(sx, sy, run)
        self.player.hp = run.hp
        self.player.max_hp = run.max_hp()
        self.player.id = self._id()
        self.player.facing = angle_to(sx, sy, W_PX / 2, H_PX / 2)
        self.weapon_seen = run.weapon.id
        self._populate(boss_factory)

    # ------------------------------------------------------------------------------------ properties
    @property
    def mods(self):
        return self.run.mods

    @property
    def difficulty(self):
        return self.run.difficulty

    @property
    def adapt(self):
        return self.run.adapt

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    # ------------------------------------------------------------------------------------ tiles and nav
    def solid(self, tx: int, ty: int) -> bool:
        if tx < 0 or ty < 0 or tx >= LG.W_T or ty >= LG.H_T:
            return True
        ch = self.tiles[ty][tx]
        if ch in "#o":
            return True
        if ch == "D":
            d = self.door_cells.get((tx, ty))
            return d is None or d.locked or d.hidden
        return False

    proj_solid = solid

    def _build_nav(self) -> nav.Grid:
        g = nav.Grid(LG.W_T, LG.H_T)
        for y in range(LG.H_T):
            for x in range(LG.W_T):
                if self.tiles[y][x] in "#o":
                    g.set_blocked(x, y)
        return g

    def find_path(self, x: float, y: float, tx: float, ty: float) -> list[tuple[float, float]]:
        a = self.nav_grid.nearest_walkable((int(x // TILE), int(y // TILE)), 3)
        b = self.nav_grid.nearest_walkable((int(tx // TILE), int(ty // TILE)), 3)
        if a is None or b is None:
            return []
        path = nav.astar(self.nav_grid, a, b, diagonal=True, max_nodes=900)
        if not path:
            return []
        path = nav.smooth_path(self.nav_grid, path)
        return [(cx * TILE + TILE / 2, cy * TILE + TILE / 2) for cx, cy in path[1:]]

    def free_cells(self, min_from_player: float = 80.0, margin: int = 2) -> list[tuple[float, float]]:
        out = []
        for (cx, cy) in LG.spawn_cells(self.tiles, set(self.spec.doors)):
            x, y = cx * TILE + TILE / 2, cy * TILE + TILE / 2
            if dist(x, y, self.player.x, self.player.y) >= min_from_player:
                out.append((x, y))
        return out

    def _entry_pos(self, entry: str | None) -> tuple[float, float]:
        if entry in LG.DOOR_INNER:
            ix, iy = LG.DOOR_INNER[entry]
            return ix * TILE + TILE / 2, iy * TILE + TILE / 2
        return W_PX / 2, H_PX / 2 + 24

    # ------------------------------------------------------------------------------------ entities
    def emit(self, kind: str, x: float = 0.0, y: float = 0.0, **data) -> None:
        self.events.append(Ev(kind, x, y, data))

    def add_hitbox(self, hb: Hitbox) -> None:
        hb.id = self._id()
        self.hitboxes.append(hb)

    def add_projectile(self, p: Projectile) -> None:
        p.id = self._id()
        self.projectiles.append(p)

    def add_hazard(self, h: Hazard) -> None:
        h.id = self._id()
        if len(self.hazards) > 80:
            self.hazards.pop(0)
        self.hazards.append(h)

    def separation(self, e: Entity) -> tuple[float, float]:
        sx = sy = 0.0
        for o in self.enemies:
            if o is e or not o.alive:
                continue
            d = dist(e.x, e.y, o.x, o.y)
            lim = (e.r + o.r) * 1.35
            if 0 < d < lim:
                sx += (e.x - o.x) / d * (lim - d) / lim
                sy += (e.y - o.y) / d * (lim - d) / lim
        return sx, sy

    def lateral_sign(self, e: Entity, p: Entity) -> float:
        """+1 if the player is currently moving clockwise around ``e`` (screen space), -1 counter-clockwise."""
        rx, ry = p.x - e.x, p.y - e.y
        cross = rx * p.vy - ry * p.vx
        return 1.0 if cross >= 0 else -1.0

    def move_entity(self, e: Entity, dx: float, dy: float, through_enemies: bool = False):
        x, y, hx, hy = move_and_collide(self.solid, e.x, e.y, dx, dy, e.r, TILE)
        e.x, e.y = x, y
        return x, y, hx, hy

    def spawn_enemy(self, eid: str, x: float, y: float, elite: bool = False, instant: bool = False) -> Enemy | None:
        d = self.lib.enemies.get(eid)
        if d is None:
            return None
        hp_scale = (1 + 0.12 * (self.floor - 1)) * self.mods["enemy_hp"] * self.difficulty.enemy_hp
        e = Enemy(d, x, y, self, elite, hp_scale)
        e.id = self._id()
        if instant:
            e.spawn_t = 0
            e.untargetable = False
        self.enemies.append(e)
        return e

    def nearest_threat(self, x: float, y: float):
        best, bd = None, 1e9
        for e in self.enemies:
            if e.alive and not e.untargetable:
                d = dist(x, y, e.x, e.y)
                if d < bd and d < 90:
                    best, bd = (e.x, e.y), d
        for hb in self.hitboxes:
            if hb.team == ENEMY_TEAM and not hb.done and hb.damage > 0:
                d = dist(x, y, hb.x, hb.y)
                if d < bd and d < 90:
                    best, bd = (hb.x, hb.y), d
        for p in self.projectiles:
            if p.team == ENEMY_TEAM and p.alive:
                d = dist(x, y, p.x, p.y)
                if d < bd and d < 90:
                    best, bd = (p.x, p.y), d
        return best

    def note_dodge(self, player: Player, dx: float, dy: float) -> None:
        """Record which way the player rolls around the nearest enemy (feeds adaptive counters)."""
        near = None
        bd = 120.0
        for e in self.enemies:
            if e.alive:
                d = dist(player.x, player.y, e.x, e.y)
                if d < bd:
                    near, bd = e, d
        now = self.run.time / 60
        m = self.adapt.model
        m.record("dodge_any", now)
        if near is not None:
            rx, ry = player.x - near.x, player.y - near.y
            cross = rx * dy - ry * dx
            if abs(cross) > 0.2 * math.hypot(rx, ry):
                m.record("dodge_cw" if cross > 0 else "dodge_ccw", now)
                self.last_dodge_side = 1 if cross > 0 else -1

    # ------------------------------------------------------------------------------------ population
    def _populate(self, boss_factory) -> None:
        s = self.spec
        c = (W_PX / 2, H_PX / 2)
        if s.kind in ("reward", "secret"):
            self.props.append(Prop("altar" if s.kind == "reward" else "chest", c[0], c[1] - 10, 10,
                                   {"secret": s.kind == "secret"}, used=s.reward_taken))
        elif s.kind == "forge":
            self.props.append(Prop("anvil", c[0] - 40, c[1] - 6, 10, {}))
            self.props.append(Prop("stall", c[0] + 40, c[1] - 6, 10, {"stock": None}))
        elif s.kind == "rest":
            self.props.append(Prop("campfire", c[0], c[1] - 6, 10, {}, used=s.reward_taken))
        elif s.kind == "choir":
            self.props.append(Prop("choir_door", c[0], 38, 12, {}))
        for (vx, vy) in s.vents:
            self.add_hazard(Hazard(vx * TILE + 8, vy * TILE + 8, 13, 10 ** 9, dps=14, team=ENEMY_TEAM, kind="vent",
                                   harms_all=False, period=210, on_frames=45, warn=50, phase=self.rng.randrange(210)))
        for ch_y, row in enumerate(self.tiles):
            for ch_x, ch in enumerate(row):
                if ch == "o":
                    self.props.append(Prop("brazier", ch_x * TILE + 8, ch_y * TILE + 8, 6, {}))
        if s.kind in ("stair",) and s.cleared:
            self._place_stair()
        if s.kind == "boss":
            self.combat_started = False
            if boss_factory is not None:
                self.boss = boss_factory(self)
                self.enemies.append(self.boss)
            if s.cleared:
                self.cleared = True
                self.boss.alive = False if self.boss else None
        if self.cleared and s.kind in ("arena", "elite", "boss", "stair"):
            self._unlock_doors()

    def _place_stair(self) -> None:
        if not any(p.kind == "stair" for p in self.props):
            self.props.append(Prop("stair", W_PX / 2, H_PX / 2 - 12, 12, {}))

    # ------------------------------------------------------------------------------------ doors
    def _lock_doors(self) -> None:
        for d in self.doors.values():
            if not d.hidden:
                d.locked = True
        self.emit("doors", 0, 0, locked=True)

    def _unlock_doors(self) -> None:
        for d in self.doors.values():
            d.locked = False

    # ------------------------------------------------------------------------------------ main update
    def update(self, intent: Intent) -> None:
        self.t += 1
        run = self.run
        run.tick()
        p = self.player
        # fix up player's max hp if boons changed it
        if p.alive:
            self._sync_player()
        if "flare" in intent.pressed and run.flare >= 100 and p.alive:
            self._flare()
        if "interact" in intent.pressed and p.alive:
            self._interact()
        p.update(self, intent)
        self._start_combat()
        self._spawn_waves()
        for e in list(self.enemies):
            if e.alive:
                self._update_enemy(e)
        self.squad.update((p.x, p.y))
        self._bodies()
        self._hitboxes()
        self._projectiles()
        self._hazards()
        self._statuses()
        self._pickups()
        self._doors()
        for k in list(self.trigger_cd):
            self.trigger_cd[k] -= 1
            if self.trigger_cd[k] <= 0:
                del self.trigger_cd[k]
        if self.shield_t > 0:
            self.shield_t -= 1
        self.adapt.ctl.update(run.time / 60, 1 / 60)
        self.enemies = [e for e in self.enemies if e.alive or e.dead_t < 40]
        for e in self.enemies:
            if not e.alive:
                e.dead_t += 1
        self._check_clear()
        if p.alive and p.hp <= 0 and not getattr(self, "admin_god", False):
            self._player_down()
        self.run.hp = max(0.0, p.hp)

    def _sync_player(self) -> None:
        p = self.player
        mx = self.run.max_hp()
        if abs(mx - p.max_hp) > 0.01:
            ratio = p.hp / max(1.0, p.max_hp)
            p.max_hp = mx
            p.hp = min(mx, max(p.hp, ratio * mx)) if mx > 0 else p.hp
        if self.run.weapon.id != self.weapon_seen:
            self.weapon_seen = self.run.weapon.id

    # ------------------------------------------------------------------------------------ combat flow
    def _start_combat(self) -> None:
        if self.combat_started or self.cleared or not self.player.alive:
            return
        spec = self.spec
        if self.t < 24:
            return
        # the player must step off the entry landing before the doors seal
        if min((dist(self.player.x, self.player.y, LG.DOOR_INNER[s][0] * TILE, LG.DOOR_INNER[s][1] * TILE)
                for s in self.doors), default=99) < 26 and self.t < 90:
            return
        self.combat_started = True
        self._lock_doors()
        if spec.kind == "boss":
            self.emit("boss_start", self.boss.x if self.boss else 0, self.boss.y if self.boss else 0)
            if self.boss:
                self.boss.untargetable = False
                self.boss.spawn_t = 0
        else:
            self.wave_timer = 20

    def _spawn_waves(self) -> None:
        spec = self.spec
        if not self.combat_started or spec.kind == "boss" or self.cleared:
            return
        for sp in list(self.pending_spawns):
            if self.t >= sp[4]:
                self.pending_spawns.remove(sp)
                self.spawn_enemy(sp[0], sp[2], sp[3], sp[1])
        alive = [e for e in self.enemies if e.alive and not e.untargetable or (e.alive and e.spawn_t > 0)]
        if self.wave_idx < len(spec.waves) and not self.pending_spawns and not any(e.alive for e in self.enemies):
            self.wave_timer -= 1
            if self.wave_timer <= 0:
                wave = spec.waves[self.wave_idx]
                self.wave_idx += 1
                cells = self.free_cells(90.0)
                self.rng.shuffle(cells)
                used: list[tuple[float, float]] = []
                for k, (eid, elite) in enumerate(wave):
                    pos = next((c for c in cells if all(dist(c[0], c[1], u[0], u[1]) > 28 for u in used)), None)
                    if pos is None:
                        pos = cells[k % len(cells)] if cells else (W_PX / 2, H_PX / 2)
                    used.append(pos)
                    self.pending_spawns.append((eid, elite, pos[0], pos[1], self.t + 6 + k * 3))
                    self.emit("spawn_mark", pos[0], pos[1])
                self.wave_timer = 50

    def _update_enemy(self, e: Enemy) -> None:
        e.age += 1
        if e.flash > 0:
            e.flash -= 1
        if e.spawn_t > 0:
            e.spawn_t -= 1
            if e.spawn_t == 0:
                e.untargetable = False
                self.emit("spawned", e.x, e.y)
            return
        # poise recovers when idle
        if e.poise > 0:
            if e.poise_wait > 0:
                e.poise_wait -= 1
            else:
                e.poise = max(0.0, e.poise - 0.25)
        e.brain.update(self, e)
        kx, ky = e.kx, e.ky
        if abs(kx) > 0.05 or abs(ky) > 0.05:
            self.move_entity(e, kx, ky)
            e.kx *= 0.8
            e.ky *= 0.8

    def _bodies(self) -> None:
        """Soft body collision between the player and enemies (the player's dodge passes through)."""
        p = self.player
        if not p.alive:
            return
        for e in self.enemies:
            if not e.alive or e.spawn_t > 0:
                continue
            d = dist(p.x, p.y, e.x, e.y)
            lim = p.r + e.r - 1
            if 0 < d < lim:
                if p.state == "dodge":
                    continue
                push = (lim - d) * 0.5
                ux, uy = (p.x - e.x) / d, (p.y - e.y) / d
                self.move_entity(p, ux * push, uy * push)
                self.move_entity(e, -ux * push * 0.6, -uy * push * 0.6)

    # ------------------------------------------------------------------------------------ hitboxes
    def _hitboxes(self) -> None:
        p = self.player
        for hb in self.hitboxes:
            if hb.done:
                continue
            o = hb.owner
            if hb.follow and o is not None:
                if o is p or o.alive:
                    hb.x, hb.y = o.x, o.y
                    if o is p:
                        hb.facing = p.facing
                    if hb.shape == "circle" and hb.follow_offset:
                        hb.x += math.cos(hb.facing) * hb.follow_offset
                        hb.y += math.sin(hb.facing) * hb.follow_offset
                elif o is not None and not o.alive:
                    hb.done = True
                    continue
            if hb.track_fn is not None and hb.t < hb.track:
                hb.facing = hb.track_fn()
                if hb.owner is not None and hb.owner is not p:
                    hb.owner.facing = hb.facing
            if hb.is_active and hb.damage > 0:
                if hb.team == ENEMY_TEAM:
                    if p.alive and self._hb_touches(hb, p):
                        self._hb_hits_player(hb)
                    if hb.friendly:
                        for e in self.enemies:
                            if e.alive and e is not hb.owner and self._hb_touches(hb, e) and e.id not in hb.hit:
                                hb.hit[e.id] = hb.t
                                self._damage_enemy(e, hb.damage * 0.6, hb, hb.facing)
                else:
                    for e in list(self.enemies):
                        if not e.alive or e.untargetable:
                            continue
                        last = hb.hit.get(e.id)
                        if last is not None and not (hb.multi and hb.t - last >= hb.multi):
                            continue
                        if self._hb_touches(hb, e):
                            hb.hit[e.id] = hb.t
                            self._hb_hits_enemy(hb, e)
                    self._hb_hits_door(hb)
            if hb.t == hb.windup and hb.team == ENEMY_TEAM and hb.damage > 0:
                self._perfect_dodge_check(hb)
            hb.t += 1
            if hb.t >= hb.windup + hb.active:
                hb.done = True
        self.hitboxes = [h for h in self.hitboxes if not h.done]

    def _hb_touches(self, hb: Hitbox, e: Entity) -> bool:
        if hb.shape == "arc":
            return arc_hit(hb.x, hb.y, hb.facing, hb.reach, hb.arc, e.x, e.y, e.r, hb.inner)
        if hb.shape == "thrust":
            return rect_hit(hb.x, hb.y, hb.facing, hb.reach, hb.width, e.x, e.y, e.r)
        if hb.shape == "circle":
            return circle_hit(hb.x, hb.y, hb.reach, e.x, e.y, e.r)
        if hb.shape == "ring":
            cur = hb.cur_reach
            return ring_hit(hb.x, hb.y, max(0.0, cur - 14), cur, e.x, e.y, e.r)
        return False

    def _hb_hits_door(self, hb: Hitbox) -> None:
        for d in self.doors.values():
            if not d.hidden:
                continue
            for (cx, cy) in d.cells:
                if circle_hit(hb.x, hb.y, hb.reach if hb.shape != "arc" else hb.reach * 0.9, cx * TILE + 8, cy * TILE + 8, 8):
                    if hb.damage >= 8 and d.hits < 99 and hb.t == hb.windup:
                        d.hits += 1
                        self.emit("crack", cx * TILE + 8, cy * TILE + 8)
                        if d.hits >= 2:
                            d.hidden = False
                            d.kind = "normal"
                            self.run.secrets += 1
                            self.emit("secret", cx * TILE + 8, cy * TILE + 8)
                    break

    def _perfect_dodge_check(self, hb: Hitbox) -> None:
        p = self.player
        if p.state == "dodge" and p.iframes > 0 and p.t <= PERFECT_DODGE_WINDOW and self._hb_touches(hb, p):
            self.stats["perfect_dodges"] += 1
            self.run.add_counter("perfect_dodges")
            self.emit("perfect_dodge", p.x, p.y)
            self.hitstop = max(self.hitstop, 5)
            self.fire("perfect_dodge", x=p.x, y=p.y)

    # ---- enemy hit by player ---------------------------------------------------------------------------
    def _hb_hits_enemy(self, hb: Hitbox, e: Enemy) -> None:
        ang = angle_to(hb.x, hb.y, e.x, e.y)
        self._damage_enemy(e, hb.damage, hb, ang)

    def _damage_enemy(self, e: Enemy, dmg: float, src, ang: float, direct: bool = True) -> float:
        run = self.run
        apply = getattr(src, "apply", ())
        poise_dmg = getattr(src, "poise", 0.0)
        knock = getattr(src, "knock", 0.0)
        stop = getattr(src, "stop", 0)
        shake = getattr(src, "shake", 0.1)
        tags = getattr(src, "tags", ())
        crit = getattr(src, "crit", False)
        guard_broken = False
        if e.guard_front and e.alive and direct and not getattr(src, "unblockable", False):
            front_dir = e.facing
            from_dir = angle_to(e.x, e.y, src.x, src.y)
            if abs(angle_diff(from_dir, front_dir)) <= e.guard_arc / 2:
                if poise_dmg >= 45 or "riposte" in tags:
                    guard_broken = True
                    e.stun = max(e.stun, 70)
                    e.brain.on_stagger()
                    e.guard_front = False
                    self.emit("guard_break", e.x, e.y)
                    run.add_counter("poise_breaks")
                    self.fire("poise_break", x=e.x, y=e.y, target=e)
                else:
                    dmg *= (1.0 - e.guard_cut)
                    apply = ()
                    poise_dmg *= 0.2
                    knock *= 0.3
                    self.emit("block", e.x, e.y, ang=from_dir)
                    self.hitstop = max(self.hitstop, 3)
                    e.hp -= dmg
                    self._after_damage(e, dmg, crit)
                    return dmg
        if e.stun > 0:
            dmg *= 1.3
        if e.trait == "armored":
            dmg *= 0.8
        dmg *= e.status.brittle_mult()
        if self.run.perks.get("damage_mul") != 1.0 and getattr(src, "owner", None) is self.player and False:
            pass
        e.hp -= dmg
        e.flash = 5
        e.last_hit_by = getattr(src, "source", "")
        e.last_tags = tuple(tags)
        self.stats["damage_dealt"] += dmg
        if knock:
            e.add_knock(ang, knock * (0.5 if e.max_poise > 50 else 1.0))
        # poise
        if poise_dmg and not guard_broken:
            e.poise += poise_dmg
            e.poise_wait = 90
            if e.poise >= e.max_poise and e.stun <= 0 and e.hp > 0:
                e.poise = 0
                e.stun = 56
                e.brain.on_stagger()
                run.add_counter("poise_breaks")
                self.emit("stagger", e.x, e.y)
                self.fire("poise_break", x=e.x, y=e.y, target=e)
        # statuses
        for (name, stacks, chance) in apply:
            if self.rng.random() <= chance:
                self._apply_status(e, name, stacks)
        if direct and e.status.has("shock") and getattr(src, "owner", None) is self.player:
            run.add_counter("shock_hits")
            self._shock_arc(e, dmg * 0.35)
        if stop:
            self.hitstop = max(self.hitstop, stop)
        self.emit("hit", e.x, e.y, ang=ang, dmg=dmg, shake=shake, crit=crit, stop=stop)
        self.fire("hit", x=e.x, y=e.y, target=e, dmg=dmg)
        self._after_damage(e, dmg, crit)
        return dmg

    def _after_damage(self, e: Enemy, dmg: float, crit: bool) -> None:
        self.emit("damage", e.x, e.y - e.r, amount=dmg, crit=crit)
        if e.hp <= 0 and e.alive:
            self._kill(e)

    def _shock_arc(self, src: Enemy, dmg: float) -> None:
        count = 0
        for o in self.enemies:
            if o is src or not o.alive or o.untargetable:
                continue
            if dist(src.x, src.y, o.x, o.y) <= SHOCK_ARC_RANGE and count < 2:
                count += 1
                o.hp -= dmg
                o.flash = 3
                self.emit("arc", src.x, src.y, tx=o.x, ty=o.y)
                self.emit("damage", o.x, o.y - o.r, amount=dmg, crit=False)
                if o.hp <= 0 and o.alive:
                    self._kill(o)

    def _apply_status(self, e: Entity, name: str, stacks: int) -> None:
        power = self.run.perks.get("status_power_mul") if e.team == ENEMY_TEAM else 1.0
        events = e.status.apply(name, stacks, power=power)
        self._status_events(e, events)

    def _status_events(self, e: Entity, events) -> None:
        perks = self.run.perks
        for ev in events:
            if ev.kind == "flashover":
                r = ev.radius * perks.get("flashover_radius_mul")
                self.run.add_counter("flashovers")
                self.emit("flashover", e.x, e.y, radius=r)
                for o in self.enemies:
                    if o.alive and not o.untargetable and dist(e.x, e.y, o.x, o.y) <= r + o.r:
                        o.hp -= ev.amount
                        o.flash = 4
                        o.last_hit_by = "flashover"
                        self.emit("damage", o.x, o.y - o.r, amount=ev.amount, crit=False)
                        if o.hp <= 0 and o.alive:
                            self._kill(o)
                if perks.get("flashover_self") and dist(e.x, e.y, self.player.x, self.player.y) <= r:
                    self._hurt_player(perks.get("flashover_self") * 1.6, angle_to(e.x, e.y, self.player.x, self.player.y), 2.0, "flashover", ignore_iframes=False)
                self.hitstop = max(self.hitstop, 4)
                self.fire("flashover", x=e.x, y=e.y)
            elif ev.kind == "nova":
                self.emit("nova", e.x, e.y, radius=ev.radius)
                self.run.add_counter("novas")
                for o in self.enemies:
                    if o.alive and not o.untargetable and dist(e.x, e.y, o.x, o.y) <= ev.radius + o.r:
                        o.hp -= ev.amount
                        o.flash = 4
                        o.last_hit_by = "nova"
                        o.status.apply("shock", 1)
                        self.emit("damage", o.x, o.y - o.r, amount=ev.amount, crit=False)
                        if o.hp <= 0 and o.alive:
                            self._kill(o)
                if perks.get("shock_self") and dist(e.x, e.y, self.player.x, self.player.y) <= ev.radius:
                    self._hurt_player(perks.get("shock_self"), angle_to(e.x, e.y, self.player.x, self.player.y), 1.5, "nova")
                self.fire("chain_nova", x=e.x, y=e.y)
            elif ev.kind == "sear":
                e.hp -= ev.amount
                self.emit("damage", e.x, e.y - e.r, amount=ev.amount, crit=False)
                if e.hp <= 0 and e.alive and e.team == ENEMY_TEAM:
                    self._kill(e)
            elif ev.kind == "dot":
                amt = ev.amount * (perks.get("burn_taken_mul") if (e is self.player and ev.status == "burn") else 1.0)
                if e is self.player:
                    self._hurt_player(amt, 0.0, 0.0, "burn", stagger=False, ignore_iframes=True)
                else:
                    e.hp -= amt
                    e.flash = max(e.flash, 1)
                    e.last_hit_by = ev.status
                    if e.hp <= 0 and e.alive:
                        self._kill(e)

    def _statuses(self) -> None:
        for e in [self.player, *self.enemies]:
            if not e.alive:
                continue
            events = e.status.tick()
            if events:
                self._status_events(e, events)

    def _kill(self, e: Enemy) -> None:
        e.alive = False
        e.hp = 0
        e.dead_t = 0
        run = self.run
        self.stats["kills"] += 1
        run.register_kill()
        run.add_counter("kills")
        if e.status.has("burn") or e.last_hit_by in ("flashover",):
            run.add_counter("burn_kills")
        if e.status.has("rend"):
            run.add_counter("rend_kills")
        if getattr(e, "last_projectile_bounced", False):
            run.add_counter("ricochet_kills")
        self.squad.release(e)
        e.brain.cancel_attack()
        self.emit("kill", e.x, e.y, big=e.max_hp > 40, elite=e.elite)
        slag = int(round(e.slag * run.perks.get("slag_mul") * self.mods["slag_mul"]))
        for _ in range(max(1, min(6, slag))):
            ang = self.rng.uniform(0, math.tau)
            self.pickups.append(Pickup("slag", e.x, e.y, max(1, slag // max(1, min(6, slag))), math.cos(ang) * 1.4, math.sin(ang) * 1.4))
        if self.rng.chance(0.07 if not e.elite else 0.25):
            self.pickups.append(Pickup("heart", e.x, e.y, 15))
        run.flare = min(100.0, run.flare + 5 * run.perks.get("flare_gain_mul"))
        if e.trait == "volatile" or self.mods["death_burst"] > 0:
            self.add_hazard(Hazard(e.x, e.y, 24, 100, dps=10, team=ENEMY_TEAM, kind="ember", warmup=30))
            self.emit("burst", e.x, e.y)
        if e.trait == "twin" and not e.owner_id:
            m = self.spawn_enemy(e.edef.id, e.x + 8, e.y, False)
            if m:
                m.hp *= 0.5
                m.owner_id = -1
        self.fire("kill", x=e.x, y=e.y, target=e)
        ev = run.evolution_ready()
        if ev:
            w = run.evolve(ev)
            self.emit("evolve", self.player.x, self.player.y, weapon=w.id, name=w.name, text=ev.get("text", ""))
            self.hitstop = max(self.hitstop, 16)
        if e is self.boss:
            self.boss_defeated = True
            self.emit("boss_dead", e.x, e.y)
            self.hitstop = max(self.hitstop, 24)
            for h in self.hazards:
                if h.team == ENEMY_TEAM:
                    h.life = 0
            for hb in self.hitboxes:
                if hb.team == ENEMY_TEAM:
                    hb.done = True
            for pr in self.projectiles:
                if pr.team == ENEMY_TEAM:
                    pr.alive = False

    def on_enemy_removed(self, e: Enemy, killed: bool = False) -> None:
        self.squad.release(e)

    # ---- player hit by enemies --------------------------------------------------------------------------
    def _hb_hits_player(self, hb: Hitbox) -> None:
        p = self.player
        if p.id in hb.hit:
            return
        if hb.multi and hb.hit.get(p.id) is not None and hb.t - hb.hit[p.id] < hb.multi:
            return
        # parry
        if p.parry_active and hb.parryable and hb.owner is not None and hb.owner.alive:
            ang_to = angle_to(p.x, p.y, hb.owner.x, hb.owner.y)
            if abs(angle_diff(ang_to, p.facing)) < math.radians(105):
                hb.hit[p.id] = hb.t
                self._parry_success(hb.owner, hb)
                return
        if p.iframes > 0:
            return
        hb.hit[p.id] = hb.t
        ang = angle_to(hb.x, hb.y, p.x, p.y) if hb.shape not in ("thrust",) else hb.facing
        self._hurt_player(hb.damage, ang, hb.knock, hb.move_name or "hit", stagger=hb.poise > 12 and not p.armor,
                          src_owner=hb.owner)

    def _parry_success(self, owner, src) -> None:
        p = self.player
        perfect = p.parry_t <= PERFECT_PARRY_WINDOW
        self.stats["parries"] += 1
        self.run.add_counter("parries")
        self.adapt.model.record("parry_try", self.run.time / 60)
        p.parry_success(self, perfect)
        if isinstance(owner, Enemy):
            owner.brain.on_parried()
            owner.stun = 70 if perfect else 52
            if getattr(src, "damage", 0) > 0:
                owner.add_knock(angle_to(p.x, p.y, owner.x, owner.y), 3.0)
        sw = float(p.weapon.parry.get("shockwave", 0))
        if sw > 0:
            for e in self.enemies:
                if e.alive and not e.untargetable and dist(p.x, p.y, e.x, e.y) <= sw:
                    e.stun = max(e.stun, 40)
                    e.brain.on_stagger()
                    e.add_knock(angle_to(p.x, p.y, e.x, e.y), 4.0)
        self.hitstop = max(self.hitstop, 10 if perfect else 7)
        self.emit("parry", p.x, p.y, perfect=perfect, ang=p.facing)
        self.fire("parry", x=p.x, y=p.y, perfect=perfect)

    def _hurt_player(self, dmg: float, ang: float, knock: float, source: str, stagger: bool = True,
                     ignore_iframes: bool = False, src_owner=None) -> None:
        p = self.player
        if not p.alive:
            return
        if not ignore_iframes and p.iframes > 0:
            return
        if self.shield_t > 0:
            self.emit("block", p.x, p.y, ang=ang)
            return
        dmg *= self.run.perks.get("damage_taken_mul")
        if not getattr(self, "admin_god", False):
            p.hp -= dmg
            self.run.damage_taken += dmg
            self.stats["hits_taken"] += 1
            self.recent_damage += dmg
        if dmg >= 2:
            p.take_hit(ang, knock, 14 if stagger else 0)
            self.hitstop = max(self.hitstop, 5)
        self.emit("player_hit", p.x, p.y, ang=ang, dmg=dmg)
        self.emit("damage", p.x, p.y - 8, amount=dmg, crit=False, player=True)
        if dmg >= 2:
            self.fire("damaged", x=p.x, y=p.y, dmg=dmg)

    def _player_down(self) -> None:
        p = self.player
        if self.run.perks.get("revive") > 0 and not self.run.revive_used:
            self.run.revive_used = True
            p.hp = p.max_hp / 3
            p.iframes = 120
            self.emit("revive", p.x, p.y)
            self.hitstop = max(self.hitstop, 12)
            for e in self.enemies:
                if e.alive and dist(p.x, p.y, e.x, e.y) < 70:
                    e.add_knock(angle_to(p.x, p.y, e.x, e.y), 7.0)
                    e.stun = max(e.stun, 30)
            return
        p.hp = 0
        p.die()
        self.player_dead = True
        self.emit("player_dead", p.x, p.y)

    # ------------------------------------------------------------------------------------ projectiles
    def _projectiles(self) -> None:
        p = self.player
        for pr in self.projectiles:
            if not pr.alive:
                continue
            pr.life -= 1
            if pr.life <= 0:
                pr.alive = False
                if pr.kind == "glob":                       # slag globs leave an ember puddle where they land
                    self.add_hazard(Hazard(pr.x, pr.y, 14, 160, dps=11, team=ENEMY_TEAM, kind="ember", warmup=18))
                continue
            if pr.homing > 0 and pr.team == PLAYER_TEAM:
                tgt = min((e for e in self.enemies if e.alive and not e.untargetable),
                          key=lambda e: dist(pr.x, pr.y, e.x, e.y), default=None)
                if tgt is not None:
                    sp = math.hypot(pr.vx, pr.vy)
                    a = math.atan2(pr.vy, pr.vx)
                    da = angle_diff(angle_to(pr.x, pr.y, tgt.x, tgt.y), a)
                    a += max(-0.08, min(0.08, da)) * pr.homing
                    pr.vx, pr.vy = math.cos(a) * sp, math.sin(a) * sp
            nx, ny = pr.x + pr.vx, pr.y + pr.vy
            if self.solid(int(nx // TILE), int(ny // TILE)):
                if pr.ricochet > 0:
                    pr.ricochet -= 1
                    pr.bounces += 1
                    if self.solid(int(nx // TILE), int(pr.y // TILE)):
                        pr.vx = -pr.vx
                    if self.solid(int(pr.x // TILE), int(ny // TILE)):
                        pr.vy = -pr.vy
                    if not self.solid(int(nx // TILE), int(pr.y // TILE)) and not self.solid(int(pr.x // TILE), int(ny // TILE)):
                        pr.vx, pr.vy = -pr.vx, -pr.vy
                    self.emit("ricochet", pr.x, pr.y)
                    nx, ny = pr.x + pr.vx, pr.y + pr.vy
                else:
                    pr.alive = False
                    self.emit("spark", pr.x, pr.y)
                    continue
            pr.x, pr.y = nx, ny
            pr.trail.append((pr.x, pr.y))
            del pr.trail[:-6]
            if pr.team == ENEMY_TEAM:
                if p.alive:
                    if p.parry_active and pr.parryable and circle_hit(pr.x, pr.y, pr.r + 10, p.x, p.y, p.r):
                        self._reflect(pr)
                        continue
                    if circle_hit(pr.x, pr.y, pr.r, p.x, p.y, p.r) and p.iframes <= 0:
                        pr.alive = False
                        self._hurt_player(pr.damage, math.atan2(pr.vy, pr.vx), pr.knock, "arrow", stagger=pr.poise > 10)
                        self.emit("spark", pr.x, pr.y)
                    elif circle_hit(pr.x, pr.y, pr.r, p.x, p.y, p.r) and p.state == "dodge" and p.t <= PERFECT_DODGE_WINDOW \
                            and pr.id not in getattr(self, "_pd_seen", set()):
                        self._pd_seen = getattr(self, "_pd_seen", set()) | {pr.id}
                        self.stats["perfect_dodges"] += 1
                        self.run.add_counter("perfect_dodges")
                        self.emit("perfect_dodge", p.x, p.y)
                        self.fire("perfect_dodge", x=p.x, y=p.y)
            else:
                for e in self.enemies:
                    if not e.alive or e.untargetable or e.id in pr.hit_ids:
                        continue
                    if circle_hit(pr.x, pr.y, pr.r, e.x, e.y, e.r):
                        pr.hit_ids.add(e.id)
                        ang = math.atan2(pr.vy, pr.vx)
                        dmg = pr.damage
                        src = _ProjSrc(pr, ang, dmg)
                        self._damage_enemy(e, dmg, src, ang)
                        if pr.bounces and not e.alive:
                            e.last_projectile_bounced = True
                        if pr.chain > 0:
                            self._chain(pr, e)
                        if pr.pierce > 0:
                            pr.pierce -= 1
                        else:
                            pr.alive = False
                            break
        self.projectiles = [x for x in self.projectiles if x.alive]

    def _chain(self, pr: Projectile, src: Enemy) -> None:
        nxt = [o for o in self.enemies if o.alive and not o.untargetable and o is not src and dist(src.x, src.y, o.x, o.y) < 70]
        nxt.sort(key=lambda o: dist(src.x, src.y, o.x, o.y))
        for o in nxt[:pr.chain]:
            o.hp -= pr.damage * 0.5
            o.status.apply("shock", 1)
            self.emit("arc", src.x, src.y, tx=o.x, ty=o.y)
            self.emit("damage", o.x, o.y - o.r, amount=pr.damage * 0.5, crit=False)
            if o.hp <= 0 and o.alive:
                self._kill(o)

    def _reflect(self, pr: Projectile) -> None:
        p = self.player
        perfect = p.parry_t <= PERFECT_PARRY_WINDOW
        refl = float(p.weapon.parry.get("reflect", 2.0)) * self.run.perks.get("reflect_mul")
        ang = p.facing if perfect else math.atan2(-pr.vy, -pr.vx)
        sp = math.hypot(pr.vx, pr.vy) * refl
        pr.vx, pr.vy = math.cos(ang) * sp, math.sin(ang) * sp
        pr.team = PLAYER_TEAM
        pr.owner = p
        pr.damage *= refl
        pr.reflected = True
        pr.parryable = False
        pr.life = 100
        pr.pierce = max(pr.pierce, 1)
        pr.color = (255, 255, 255)
        self.stats["parries"] += 1
        self.run.add_counter("parries")
        self.adapt.model.record("parry_try", self.run.time / 60)
        p.parry_success(self, perfect)
        self.hitstop = max(self.hitstop, 8)
        self.emit("parry", p.x, p.y, perfect=perfect, ang=p.facing)
        self.fire("parry", x=p.x, y=p.y, perfect=perfect)

    # ------------------------------------------------------------------------------------ hazards
    def _hazards(self) -> None:
        p = self.player
        for h in self.hazards:
            h.t += 1
            h.life -= 1
            if h.life <= 0:
                continue
            if h.kind == "ash":
                for e in self.enemies:
                    if e.alive and not e.untargetable and dist(h.x, h.y, e.x, e.y) <= h.r + e.r and h.t % 20 == 0:
                        self._apply_status(e, "ash", 1)
                continue
            if not h.armed:
                continue
            h.tick_t += 1
            if h.tick_t < 12:
                continue
            h.tick_t = 0
            amt = h.dps * 12 / 60
            hurts_player = (h.team == ENEMY_TEAM or h.harms_all)
            hurts_enemies = (h.team == PLAYER_TEAM or h.harms_all)
            if hurts_player and p.alive and dist(h.x, h.y, p.x, p.y) <= h.r + p.r - 2 and p.state != "dodge":
                self._hurt_player(amt, angle_to(h.x, h.y, p.x, p.y), 0.5, h.kind, stagger=False, ignore_iframes=False)
                if h.kind in ("ember", "vent", "fire"):
                    self._apply_status(p, "burn", 1)
            if hurts_enemies:
                for e in self.enemies:
                    if e.alive and not e.untargetable and dist(h.x, h.y, e.x, e.y) <= h.r + e.r:
                        e.hp -= amt
                        e.flash = 2
                        e.last_hit_by = h.kind
                        for (name, stacks, chance) in h.apply:
                            self._apply_status(e, name, stacks)
                        if e.hp <= 0 and e.alive:
                            self._kill(e)
        self.hazards = [h for h in self.hazards if h.life > 0]

    # ------------------------------------------------------------------------------------ pickups
    def _pickups(self) -> None:
        p = self.player
        for k in self.pickups:
            k.age += 1
            if not k.alive:
                continue
            d = dist(k.x, k.y, p.x, p.y)
            if k.age > 18 and d < 70 and p.alive:
                k.magnet = True
            if k.magnet and p.alive:
                ux, uy = unit(p.x - k.x, p.y - k.y)
                k.vx += ux * 0.35
                k.vy += uy * 0.35
            k.x += k.vx
            k.y += k.vy
            k.vx *= 0.9
            k.vy *= 0.9
            if p.alive and d < 9 and k.age > 10:
                k.alive = False
                self._collect(k)
        self.pickups = [k for k in self.pickups if k.alive]

    def _collect(self, k: Pickup) -> None:
        run = self.run
        p = self.player
        if k.kind == "slag":
            run.slag += k.value
            self.emit("pickup", k.x, k.y, what="slag")
        elif k.kind == "heart":
            heal = run.heal_amount(k.value)
            p.hp = min(p.max_hp, p.hp + heal)
            self.emit("heal", p.x, p.y, amount=heal)
        elif k.kind == "soot":
            run.soot += k.value
            self.emit("pickup", k.x, k.y, what="soot")
        elif k.kind == "flare":
            run.flare = min(100, run.flare + k.value)

    # ------------------------------------------------------------------------------------ doors / clear
    def _doors(self) -> None:
        p = self.player
        if not p.alive or self.exit_request is not None:
            return
        for side, d in self.doors.items():
            if d.locked or d.hidden:
                continue
            for (cx, cy) in d.cells:
                if abs(p.x - (cx * TILE + 8)) < 10 and abs(p.y - (cy * TILE + 8)) < 10:
                    self.exit_request = (side, d.target)
                    return

    def _check_clear(self) -> None:
        if self.cleared or not self.combat_started:
            return
        spec = self.spec
        if spec.kind == "boss":
            if self.boss_defeated and not any(e.alive for e in self.enemies):
                self._cleared()
            return
        if self.wave_idx >= len(spec.waves) and not self.pending_spawns and not any(e.alive for e in self.enemies):
            self._cleared()

    def _cleared(self) -> None:
        self.cleared = True
        self.spec.cleared = True
        self._unlock_doors()
        self.run.rooms_cleared += 1
        self.run.add_counter("rooms_cleared")
        self.emit("room_clear", self.player.x, self.player.y)
        self.fire("room_clear", x=self.player.x, y=self.player.y)
        if self.spec.kind in ("stair", "boss"):
            self._place_stair()
        elif self.spec.kind == "elite" or self.rng.chance(0.4):
            self.props.append(Prop("chest", W_PX / 2, H_PX / 2, 9, {"secret": False, "elite": self.spec.kind == "elite"}))
        self.run.flare = min(100, self.run.flare + 10)

    # ------------------------------------------------------------------------------------ props / interaction
    def interact_target(self) -> Prop | None:
        p = self.player
        best, bd = None, 28.0
        for pr in self.props:
            if not pr.interactable:
                continue
            d = dist(p.x, p.y, pr.x, pr.y)
            if d < bd + pr.r:
                best, bd = pr, d
        return best

    def _interact(self) -> None:
        pr = self.interact_target()
        if pr is None:
            return
        k = pr.kind
        if k in ("altar", "chest"):
            pr.used = True
            self.spec.reward_taken = True
            n = 3
            opts = self.run.offer(self.rng, self.unlocked["boons"], n)
            self.emit("open", pr.x, pr.y, what=k)
            if pr.data.get("secret"):
                self.run.soot += 12
                self.emit("pickup", pr.x, pr.y, what="soot")
            self.ui_requests.append(("boons", opts, pr))
        elif k == "campfire":
            pr.used = True
            self.spec.reward_taken = True
            heal = self.run.heal_amount(self.player.max_hp * 0.4)
            self.player.hp = min(self.player.max_hp, self.player.hp + heal)
            self.emit("heal", self.player.x, self.player.y, amount=heal)
        elif k == "anvil":
            self.ui_requests.append(("anvil", None, pr))
        elif k == "stall":
            self.ui_requests.append(("stall", None, pr))
        elif k == "stair":
            pr.used = True
            self.exit_request = ("return", -3) if pr.data.get("kind") == "return" else ("stair", -1)
        elif k == "choir_door":
            pr.used = True
            self.exit_request = ("choir", -2)

    # ------------------------------------------------------------------------------------ boons: triggers
    def fire(self, event: str, **kw) -> None:
        perks = self.run.perks
        for tr in perks.triggers(event):
            key = (tr.boon, tr.index)
            if key in self.trigger_cd:
                continue
            tgt = kw.get("target")
            if tr.needs_status and not (tgt is not None and tgt.status.has(tr.needs_status)):
                continue
            if tr.chance < 1.0 and self.rng.random() > tr.chance:
                continue
            if tr.cooldown:
                self.trigger_cd[key] = tr.cooldown
            self._run_action(tr, kw)

    def _run_action(self, tr, kw: dict) -> None:
        p = self.player
        a = tr.args
        do = tr.do
        n = max(1, tr.stacks)
        x, y = kw.get("x", p.x), kw.get("y", p.y)
        if do == "flame_trail":
            p.trail_t = max(p.trail_t, 16)
            p.trail_args = a
        elif do == "apply_status_near":
            status, stacks, radius = a.get("status", "burn"), int(a.get("stacks", 1)), float(a.get("radius", 0))
            tgt = kw.get("target")
            if radius <= 0 and tgt is not None and tgt.alive:
                self._apply_status(tgt, status, stacks)
            elif radius > 0:
                for e in self.enemies:
                    if e.alive and not e.untargetable and dist(p.x, p.y, e.x, e.y) <= radius + e.r:
                        self._apply_status(e, status, stacks)
        elif do == "heal":
            amt = a.get("amount", 0) + a.get("fraction", 0) * p.max_hp
            heal = self.run.heal_amount(amt * n)
            p.hp = min(p.max_hp, p.hp + heal)
            self.emit("heal", p.x, p.y, amount=heal)
        elif do == "gold":
            self.run.slag += int(a.get("amount", 5) * n)
        elif do == "nova":
            dmg, rad = float(a.get("damage", 10)) * n, float(a.get("radius", 50))
            self.emit("nova", x, y, radius=rad)
            for e in self.enemies:
                if e.alive and not e.untargetable and dist(x, y, e.x, e.y) <= rad + e.r:
                    e.hp -= dmg
                    e.flash = 4
                    if a.get("status"):
                        self._apply_status(e, a["status"], 1)
                    self.emit("damage", e.x, e.y - e.r, amount=dmg, crit=False)
                    if e.hp <= 0 and e.alive:
                        self._kill(e)
        elif do == "refresh_dodge":
            p.dodge_cd = 0
        elif do == "buff":
            self.run.perks.add_buff(a.get("stat", "damage_mul"), float(a.get("value", 1.2)), int(a.get("frames", 180)))
            self.emit("buff", p.x, p.y)
        elif do == "shield":
            self.shield_t = int(a.get("frames", 100))
            self.emit("shield", p.x, p.y)
        elif do == "burst_bolts":
            cnt = int(a.get("count", 6))
            for i in range(cnt):
                ang = math.tau * i / cnt
                self.add_projectile(Projectile(p.x, p.y, math.cos(ang) * 3.4, math.sin(ang) * 3.4, 3.0, float(a.get("damage", 6)) * n,
                                               PLAYER_TEAM, p, life=45, kind="bolt", parryable=False, poise=3, knock=1.0,
                                               source="spite", color=(255, 190, 90)))
        elif do == "flare_charge":
            self.run.flare = min(100, self.run.flare + float(a.get("amount", 4)) * n)
        elif do == "explode_target":
            tgt = kw.get("target")
            if tgt is not None:
                self._explode_at(tgt.x, tgt.y, float(a.get("damage", 12)) * n, float(a.get("radius", 40)))
        elif do == "ash_cloud":
            self.add_hazard(Hazard(x if kw.get("x") is not None else p.x, y, float(a.get("radius", 30)), int(a.get("duration", 150)),
                                   dps=0, team=PLAYER_TEAM, kind="ash"))
            self.emit("ash_cloud", p.x, p.y)

    def _explode_at(self, x: float, y: float, dmg: float, radius: float) -> None:
        self.emit("explode", x, y, radius=radius)
        for e in self.enemies:
            if e.alive and not e.untargetable and dist(x, y, e.x, e.y) <= radius + e.r:
                e.hp -= dmg
                e.flash = 5
                self._apply_status(e, "burn", 2)
                self.emit("damage", e.x, e.y - e.r, amount=dmg, crit=False)
                if e.hp <= 0 and e.alive:
                    self._kill(e)

    def _flare(self) -> None:
        p = self.player
        self.run.flare = 0
        self.emit("flare", p.x, p.y)
        self.hitstop = max(self.hitstop, 8)
        for e in self.enemies:
            if e.alive and not e.untargetable and dist(p.x, p.y, e.x, e.y) < 90:
                e.hp -= 14
                e.add_knock(angle_to(p.x, p.y, e.x, e.y), 7.0)
                self._apply_status(e, "burn", 2)
                e.stun = max(e.stun, 26)
                e.brain.on_stagger()
                self.emit("damage", e.x, e.y - e.r, amount=14, crit=False)
                if e.hp <= 0 and e.alive:
                    self._kill(e)
        for pr in self.projectiles:
            if pr.team == ENEMY_TEAM and dist(p.x, p.y, pr.x, pr.y) < 100:
                pr.alive = False
        p.iframes = max(p.iframes, 20)

    # ------------------------------------------------------------------------------------ misc helpers
    def alive_enemies(self) -> list[Enemy]:
        return [e for e in self.enemies if e.alive]

    def drain_events(self) -> list[Ev]:
        out, self.events = self.events, []
        return out


class _ProjSrc:
    """Adapter so projectiles can use the same damage path as hitboxes."""

    def __init__(self, pr: Projectile, ang: float, dmg: float) -> None:
        self.x, self.y = pr.x, pr.y
        self.apply = pr.apply
        self.poise = pr.poise
        self.knock = pr.knock
        self.stop = pr.stop
        self.shake = 0.1
        self.tags = ("proj",)
        self.crit = False
        self.owner = pr.owner
        self.source = pr.source
        self.unblockable = False
