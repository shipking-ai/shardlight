"""Real-time ship flight and combat inside a system.

Newtonian-lite physics (thrust, inertia, optional flight-assist dampers), three weapon kinds with different
rules (pulse bolts, locking missiles that decoys can fool, an overcharging beam), shields/hull/energy/heat, and
enemy pilots with distinct behaviour: raiders flank in groups, patrols warn before attacking, drones swarm, and the
hunter adapts to the weapon you favour (bounded, via ``core.ai.AdaptiveController``).

Pure logic: the scene feeds ``FlightControls`` and draws; tests drive it directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...core.ai import Adaptation, AdaptiveController, PlayerModel
from ...core.rng import Rng, derive_seed
from .galaxy import System, belt_rock_state, body_state
from .game import Game

DT = 1.0 / 60.0
PICKUP_RADIUS = 26.0


def wrap(a: float) -> float:
    return (a + math.pi) % math.tau - math.pi


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


@dataclass
class FlightControls:
    turn: float = 0.0
    thrust: float = 0.0
    strafe: float = 0.0
    pulse: bool = False
    missile: bool = False
    beam: bool = False
    boost: bool = False
    decoy: bool = False
    ability: bool = False
    interact: bool = False
    dampers: bool = True


class Ship:
    _ids = 0

    def __init__(self, kind: str, x: float, y: float, stats: dict, team: int, heading: float = 0.0):
        Ship._ids += 1
        self.id = Ship._ids
        self.kind = kind
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.heading = heading
        self.team = team
        self.stats = stats
        self.radius = 9.0
        self.hull_max = self.hull = float(stats["hull"])
        self.shield_max = self.shield = float(stats["shield"])
        self.energy_max = self.energy = float(stats["energy"])
        self.heat = 0.0
        self.alive = True
        self.flash = 0
        self.shield_delay = 0.0
        self.cool = {"pulse": 0.0, "missile": 0.0}
        self.missiles = int(stats.get("missiles", 0))
        self.decoys = int(stats.get("decoys", 0))
        self.overheated = False
        self.age = 0.0
        self.lock_t = 0.0
        self.lock_target: "Ship | None" = None
        self.beam_t = 0.0
        self.beam_on = False
        self.ability_t = 0.0
        self.ability_cd = 0.0
        self.slip = 0.0
        # npc brain data
        self.brain: dict = {}
        self.cargo_id = 0


@dataclass
class Bolt:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    damage: float
    team: int
    owner: int
    shield_mul: float = 1.0
    hull_mul: float = 1.0
    alive: bool = True


@dataclass
class Missile:
    x: float
    y: float
    vx: float
    vy: float
    heading: float
    life: float
    team: int
    owner: int
    target: Ship | None
    damage: float
    blast: float
    turn: float
    shield_mul: float = 0.8
    hull_mul: float = 1.35
    alive: bool = True
    fooled: bool = False


@dataclass
class Decoy:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    team: int


@dataclass
class Crate:
    x: float
    y: float
    kind: str
    amount: float
    good: str = ""
    life: float = 60.0


@dataclass
class FEvent:
    kind: str
    x: float = 0.0
    y: float = 0.0
    data: dict = field(default_factory=dict)


class FlightSim:
    def __init__(self, game: Game, sid: int, difficulty: str = "standard", adapt_strength: float = 1.0,
                 spawn: bool = True):
        self.game = game
        self.defs = game.defs
        self.sid = sid
        self.sys: System = game.g.systems[sid]
        self.rng = Rng(derive_seed(game.seed, "flight", sid, int(game.clock // 600)))
        self.diff = {"story": 0.65, "standard": 1.0, "hard": 1.3}.get(difficulty, 1.0)
        self.stats = game.ship_stats()
        sx, sy = self._arrival_point()
        self.player = Ship("player", sx, sy, self.stats, 0, self.rng.uniform(0, math.tau))
        self.player.hull = min(game.hull_hp, self.player.hull_max)
        self.player.missiles = int(self.stats.get("missiles", 0))
        self.player.decoys = int(self.stats.get("decoys", 0))
        self.enemies: list[Ship] = []
        self.npcs: list[Ship] = []
        self.bolts: list[Bolt] = []
        self.missiles: list[Missile] = []
        self.decoys: list[Decoy] = []
        self.crates: list[Crate] = []
        self.events: list[FEvent] = []
        self.body_pos: list[tuple[float, float]] = []
        self.time = 0.0
        self.player_dead = False
        self.comms: list[str] = []
        self.scan_target = None
        self.scan_t = 0.0
        self.msgs: list[str] = []
        self.dock_request = None
        self.decode_request = None
        self.kills = 0
        self.weapon_model = PlayerModel(half_life=25.0)
        self.adapt = AdaptiveController(self.weapon_model, [
            Adaptation("evade_missiles", "w_missile", ("w_pulse", "w_missile", "w_beam"), 0.5, 3.0, 0.4),
            Adaptation("outrange_beam", "w_beam", ("w_pulse", "w_missile", "w_beam"), 0.5, 4.0, 0.4),
            Adaptation("jink", "w_pulse", ("w_pulse", "w_missile", "w_beam"), 0.55, 6.0, 0.4)],
            strength=adapt_strength, cooldown=10.0)
        self.trap_triggered: set[str] = set()
        self.lamp_hold = 0.0
        self.lamp_gear = -1
        self._update_bodies()
        if spawn:
            self._spawn_for_system()

    # ===================================================================================== setup
    def _arrival_point(self) -> tuple[float, float]:
        """Arrive at the edge of the system on the side facing the previous system (or near a station)."""
        stations = self.sys.stations()
        if stations:
            b = stations[0]
            x, y, _, _ = body_state(self.sys, b.idx, self.game.clock)
            return x + 70, y + 40
        return -self.sys.extent() * 0.6, 0.0

    def _update_bodies(self) -> None:
        t = self.game.clock
        self.body_pos = [body_state(self.sys, b.idx, t)[:2] for b in self.sys.bodies]

    def _spawn_for_system(self) -> None:
        g, sim = self.game, self.game.sim
        m = sim.menace[self.sid] if self.sid < len(sim.menace) else 0.0
        if self.sid == g.g.last_lamp:
            m = max(m, 0.35)
        n = int(m * 5.0 + self.rng.random() * 1.2) if g.sim.day - g.cleared.get(self.sid, -999) > 14 else 0
        n = min(6, n)
        gx, gy = self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)
        for i in range(n):
            a = self.rng.uniform(0, math.tau)
            r = self.rng.uniform(900, 1400)
            e = self._make("raider", math.cos(a) * r + self.player.x * 0.2, math.sin(a) * r + self.player.y * 0.2)
            e.brain["slot"] = i
            e.brain["side"] = 1 if i % 2 else -1
        owner = sim.owner(self.sid)
        if owner and g.sim.player_rep.get(owner, 0) < -30:
            for i in range(2):
                a = self.rng.uniform(0, math.tau)
                e = self._make("patrol", math.cos(a) * 1000, math.sin(a) * 1000)
                e.brain["civ"] = owner
        if g.stats["kills"] >= 6 and m > 0.3 and self.rng.chance(0.4):
            a = self.rng.uniform(0, math.tau)
            self._make("hunter", math.cos(a) * 1500, math.sin(a) * 1500)
        for cv in sim.convoys_in_system(self.sid):
            a = self.rng.uniform(0, math.tau)
            fr = self._make("freighter", math.cos(a) * 700, math.sin(a) * 700)
            fr.cargo_id = cv.id
            fr.brain["gi"] = cv.gi
            fr.brain["amt"] = cv.amt
            fr.brain["civ"] = cv.owner
        if self.sid in g.visited:
            pass

    def _make(self, kind: str, x: float, y: float) -> Ship:
        hs = {"raider": {"hull": 55, "shield": 40, "energy": 100, "missiles": 0, "decoys": 0, "rot": 170, "thrust": 230, "max_speed": 200},
              "patrol": {"hull": 110, "shield": 110, "energy": 100, "missiles": 0, "decoys": 0, "rot": 120, "thrust": 190, "max_speed": 170},
              "drone": {"hull": 22, "shield": 0, "energy": 100, "missiles": 0, "decoys": 0, "rot": 260, "thrust": 340, "max_speed": 260},
              "hunter": {"hull": 130, "shield": 120, "energy": 120, "missiles": 4, "decoys": 4, "rot": 200, "thrust": 250, "max_speed": 215},
              "freighter": {"hull": 90, "shield": 30, "energy": 50, "missiles": 0, "decoys": 0, "rot": 60, "thrust": 90, "max_speed": 90}}[kind]
        st = dict(self.defs.hull_stats("wayfarer"))
        st.update(hs)
        st["hull"] *= (0.8 + 0.2 * self.diff)
        e = Ship(kind, x, y, st, 1 if kind != "freighter" else 2, self.rng.uniform(0, math.tau))
        e.radius = {"drone": 6.0, "freighter": 13.0, "patrol": 11.0}.get(kind, 9.0)
        e.brain = {"state": "approach", "t": 0.0, "side": 1, "slot": 0, "flee": 0.0, "warn": 0.0, "aware": kind != "patrol"}
        (self.npcs if kind == "freighter" else self.enemies).append(e)
        return e

    # ===================================================================================== helpers
    def emit(self, kind: str, x: float = 0.0, y: float = 0.0, **data) -> None:
        self.events.append(FEvent(kind, x, y, data))

    def drain(self) -> list[FEvent]:
        out, self.events = self.events, []
        return out

    def solid_bodies(self):
        for b, (x, y) in zip(self.sys.bodies, self.body_pos):
            if b.kind in ("planet", "moon"):
                yield x, y, b.radius
        yield 0.0, 0.0, self.sys.star.radius

    # ===================================================================================== update
    def update(self, ctl: FlightControls, dt: float = DT) -> None:
        self.time += dt
        g = self.game
        g.advance_clock(dt)
        self._update_bodies()
        p = self.player
        if p.alive:
            self._player(ctl, dt)
        for e in list(self.enemies):
            if e.alive:
                self._npc(e, dt)
        for f in list(self.npcs):
            if f.alive:
                self._freighter(f, dt)
        self._projectiles(dt)
        for s in [p, *self.enemies, *self.npcs]:
            if s.alive:
                self._ship_physics(s, dt)
        self._pickups(dt)
        self._world_interactions(ctl, dt)
        self.adapt.update(self.time, dt)
        self.enemies = [e for e in self.enemies if e.alive or e.age < 0]
        self.npcs = [f for f in self.npcs if f.alive]
        g.hull_hp = max(0.0, p.hull) if p.alive else g.hull_hp
        if p.alive and p.hull <= 0:
            self._player_destroyed()

    # ===================================================================================== player
    def _player(self, ctl: FlightControls, dt: float) -> None:
        p, st = self.player, self.stats
        p.age += dt
        p.heading = wrap(p.heading + ctl.turn * math.radians(st["rot"]) * dt * (1.0 if not p.slip else 0.7))
        ax, ay = math.cos(p.heading), math.sin(p.heading)
        thrust = st["thrust"]
        maxs = st["max_speed"]
        boosting = ctl.boost and p.energy > 8 and not p.overheated
        if boosting:
            thrust *= st["boost"]
            maxs *= st["boost"]
            p.energy -= 38 * dt
            p.heat += 24 * dt
        if p.slip > 0:
            maxs *= 1.5
            thrust *= 1.4
        if ctl.thrust > 0:
            p.vx += ax * thrust * ctl.thrust * dt
            p.vy += ay * thrust * ctl.thrust * dt
        elif ctl.thrust < 0:
            p.vx += ax * thrust * 0.5 * ctl.thrust * dt
            p.vy += ay * thrust * 0.5 * ctl.thrust * dt
        if ctl.strafe:
            p.vx += -ay * thrust * st["strafe"] * ctl.strafe * dt
            p.vy += ax * thrust * st["strafe"] * ctl.strafe * dt
        if ctl.dampers and ctl.thrust == 0 and not ctl.strafe:
            k = math.exp(-0.9 * dt)
            p.vx *= k
            p.vy *= k
        elif ctl.dampers:               # flight assist: bleed sideways drift while thrusting
            fwd = p.vx * ax + p.vy * ay
            lx, ly = p.vx - ax * fwd, p.vy - ay * fwd
            k = math.exp(-1.6 * dt)
            p.vx = ax * fwd + lx * k
            p.vy = ay * fwd + ly * k
        sp = math.hypot(p.vx, p.vy)
        if sp > maxs:
            p.vx *= maxs / sp
            p.vy *= maxs / sp
        # energy / heat / shields
        p.energy = min(p.energy_max, p.energy + st["energy_regen"] * dt)
        p.heat = max(0.0, p.heat - st["cooling"] * dt)
        if p.heat > st["heat_cap"]:
            p.overheated = True
        elif p.overheated and p.heat < st["heat_cap"] * 0.5:
            p.overheated = False
        self._regen_shield(p, st, dt)
        for k in p.cool:
            p.cool[k] = max(0.0, p.cool[k] - dt)
        p.ability_cd = max(0.0, p.ability_cd - dt)
        p.slip = max(0.0, p.slip - dt)
        if ctl.ability and p.ability_cd <= 0:
            self._ability(p)
        self._player_weapons(ctl, dt)
        if ctl.decoy and p.decoys > 0 and p.cool.get("decoy", 0) <= 0:
            p.decoys -= 1
            p.cool["decoy"] = 0.6
            self.decoys.append(Decoy(p.x, p.y, p.vx * 0.5 - math.cos(p.heading) * 40, p.vy * 0.5 - math.sin(p.heading) * 40, 4.0, 0))
            self.emit("decoy", p.x, p.y)

    def _regen_shield(self, s: Ship, st: dict, dt: float) -> None:
        s.shield_delay = max(0.0, s.shield_delay - dt)
        if s.shield_delay <= 0 and s.shield < s.shield_max:
            s.shield = min(s.shield_max, s.shield + st.get("shield_regen", 6) * dt)

    def _ability(self, p: Ship) -> None:
        ab = self.defs.hulls[self.game.hull].get("ability", "")
        if ab == "salt_slip":
            p.slip = 1.2
            p.ability_cd = 10.0
            self.emit("ability", p.x, p.y, name="salt_slip")
        elif ab == "surge":
            p.shield = min(p.shield_max, p.shield + p.shield_max * 0.6)
            p.ability_cd = 22.0
            self.emit("ability", p.x, p.y, name="surge")

    def _player_weapons(self, ctl: FlightControls, dt: float) -> None:
        p, st = self.player, self.stats
        w = self.defs.weapons
        ax, ay = math.cos(p.heading), math.sin(p.heading)
        p.beam_on = False
        if p.overheated:
            p.lock_t = 0.0
            return
        if ctl.pulse and p.cool["pulse"] <= 0 and p.energy >= w["pulse"]["energy"]:
            d = w["pulse"]
            p.cool["pulse"] = 1.0 / d["rate"]
            p.energy -= d["energy"]
            p.heat += d["heat"]
            a = p.heading + math.radians(self.rng.uniform(-d["spread"], d["spread"]))
            self.bolts.append(Bolt(p.x + math.cos(a) * 11, p.y + math.sin(a) * 11, p.vx + math.cos(a) * d["speed"], p.vy + math.sin(a) * d["speed"],
                                   d["life"], d["damage"], 0, p.id, d["shield_mul"], d["hull_mul"]))
            self.weapon_model.record("w_pulse", self.time, 0.5)
            self.emit("pulse", p.x, p.y)
        # missile lock
        d = w["missile"]
        lock_time = st["lock_time"] * d["lock_time"]
        tgt = self._best_lock(p, d["lock_cone"])
        if ctl.missile and tgt is not None and p.missiles > 0:
            if p.lock_target is tgt:
                p.lock_t = min(lock_time, p.lock_t + dt)
            else:
                p.lock_target, p.lock_t = tgt, 0.0
        elif not ctl.missile or tgt is None:
            p.lock_t = max(0.0, p.lock_t - dt * 2)
            if p.lock_t <= 0:
                p.lock_target = None
        if ctl.missile and p.cool["missile"] <= 0 and p.missiles > 0 and p.energy >= d["energy"]:
            locked = p.lock_target is not None and p.lock_t >= lock_time - 1e-6
            if locked or p.lock_t <= 0.001 and tgt is None and ctl.missile and self._fire_dumb_ok(p):
                p.missiles -= 1
                p.cool["missile"] = 1.0 / d["rate"]
                p.energy -= d["energy"]
                p.heat += d["heat"]
                m = Missile(p.x + ax * 12, p.y + ay * 12, p.vx + ax * d["speed"], p.vy + ay * d["speed"], p.heading, d["life"], 0,
                            p.id, p.lock_target if locked else None, d["damage"], d["blast"], d["turn"] * (1.0 if locked else 0.0),
                            d["shield_mul"], d["hull_mul"])
                self.missiles.append(m)
                self.weapon_model.record("w_missile", self.time, 1.5)
                self.emit("missile", p.x, p.y)
                p.lock_t = 0.0
                p.lock_target = None
        # beam
        d = w["beam"]
        if ctl.beam and p.energy > 4:
            p.beam_on = True
            p.beam_t += dt
            over = p.beam_t > d["overcharge_after"] + (0.0 if True else 0.0)
            mul = d["overcharge_mul"] if over else 1.0
            heat_mul = d["overcharge_heat"] if over else 1.0
            p.energy -= d["energy"] * dt
            p.heat += d["heat"] * st["beam_heat"] * heat_mul * dt
            self._beam(p, d, mul, dt)
            self.weapon_model.record("w_beam", self.time, 1.0 * dt * 3)
        else:
            p.beam_t = 0.0

    def _fire_dumb_ok(self, p: Ship) -> bool:
        return False                                   # missiles require a lock: no wasted dumb-fire by accident

    def _best_lock(self, p: Ship, cone_deg: float) -> Ship | None:
        best, bd = None, 520.0
        half = math.radians(cone_deg)
        for e in self.enemies:
            if not e.alive:
                continue
            d = dist(p.x, p.y, e.x, e.y)
            if d > bd:
                continue
            ang = abs(wrap(math.atan2(e.y - p.y, e.x - p.x) - p.heading))
            if ang <= half:
                best, bd = e, d
        return best

    def _beam(self, p: Ship, d: dict, mul: float, dt: float) -> None:
        rng_ = d["range"]
        ax, ay = math.cos(p.heading), math.sin(p.heading)
        best, bt = None, rng_
        for e in [*self.enemies, *self.npcs]:
            if not e.alive:
                continue
            t = self._ray_circle(p.x, p.y, ax, ay, e.x, e.y, e.radius)
            if t is not None and t < bt:
                best, bt = e, t
        for (sx, sy, sr) in self.solid_bodies():
            t = self._ray_circle(p.x, p.y, ax, ay, sx, sy, sr)
            if t is not None and t < bt:
                best, bt = None, t
        self.beam_end = (p.x + ax * bt, p.y + ay * bt)
        if best is not None:
            self._damage(best, d["damage"] * mul * dt, d["shield_mul"], d["hull_mul"], p)

    @staticmethod
    def _ray_circle(ox, oy, dx, dy, cx, cy, r) -> float | None:
        fx, fy = ox - cx, oy - cy
        b = fx * dx + fy * dy
        c = fx * fx + fy * fy - r * r
        disc = b * b - c
        if disc < 0:
            return None
        t = -b - math.sqrt(disc)
        return t if t >= 0 else None

    beam_end: tuple[float, float] = (0.0, 0.0)

    # ===================================================================================== damage
    def _damage(self, s: Ship, amount: float, shield_mul: float, hull_mul: float, src: Ship | None) -> None:
        if not s.alive or amount <= 0:
            return
        if s is self.player and self.player.slip > 0:
            amount *= 0.5
        s.flash = 4
        s.shield_delay = 3.0
        if s.shield > 0:
            absorbed = min(s.shield, amount * shield_mul)
            s.shield -= absorbed
            amount -= absorbed / shield_mul
            self.emit("shield_hit", s.x, s.y)
        if amount > 0:
            s.hull -= amount * hull_mul
            self.emit("hull_hit", s.x, s.y)
        if s.hull <= 0 and s.alive:
            self._destroy(s, src)
        elif s.kind == "patrol":
            s.brain["aware"] = True

    def _destroy(self, s: Ship, src: Ship | None) -> None:
        s.alive = False
        self.emit("explode", s.x, s.y, big=s.kind in ("patrol", "hunter", "freighter"))
        if s is self.player:
            self._player_destroyed()
            return
        if src is self.player or src is None and s.kind != "freighter":
            if s.kind == "freighter":
                loot = self.game.sim.raid_convoy(s.cargo_id, True)
                gid = self.game.sim.goods[s.brain.get("gi", 0)]
                n = max(1, int(loot * 0.45))
                self.crates.append(Crate(s.x, s.y, "goods", n, gid))
                self.emit("convoy_raided", s.x, s.y)
            else:
                self.kills += 1
                self.game.register_kill(s.kind)
                self.crates.append(Crate(s.x, s.y, "credits", self.rng.randint(35, 90) * (2 if s.kind == "hunter" else 1)))
                if self.rng.chance(0.2):
                    self.crates.append(Crate(s.x + 6, s.y, "fuel", self.rng.uniform(1.0, 2.5)))
            if not any(e.alive and e.kind != "freighter" for e in self.enemies):
                self.game.cleared[self.sid] = self.game.sim.day
                self.emit("cleared", s.x, s.y)

    def _player_destroyed(self) -> None:
        self.player.alive = False
        self.player_dead = True
        self.emit("player_dead", self.player.x, self.player.y)

    # ===================================================================================== projectiles
    def _projectiles(self, dt: float) -> None:
        ships = [self.player, *self.enemies, *self.npcs]
        for b in self.bolts:
            b.life -= dt
            b.x += b.vx * dt
            b.y += b.vy * dt
            if b.life <= 0:
                b.alive = False
                continue
            for s in ships:
                if not s.alive or s.id == b.owner or s.team == b.team:
                    continue
                if (s.x - b.x) ** 2 + (s.y - b.y) ** 2 <= (s.radius + 2) ** 2:
                    b.alive = False
                    owner = next((o for o in ships if o.id == b.owner), None)
                    self._damage(s, b.damage, b.shield_mul, b.hull_mul, owner)
                    if s.kind == "freighter" and owner is self.player:
                        s.brain["hostile"] = True
                    break
            else:
                for (sx, sy, sr) in self.solid_bodies():
                    if (sx - b.x) ** 2 + (sy - b.y) ** 2 < sr * sr:
                        b.alive = False
                        break
        self.bolts = [b for b in self.bolts if b.alive]
        for d in self.decoys:
            d.life -= dt
            d.x += d.vx * dt
            d.y += d.vy * dt
            d.vx *= 0.98
            d.vy *= 0.98
        self.decoys = [d for d in self.decoys if d.life > 0]
        for m in self.missiles:
            self._missile(m, ships, dt)
        self.missiles = [m for m in self.missiles if m.alive]

    def _missile(self, m: Missile, ships: list[Ship], dt: float) -> None:
        m.life -= dt
        if m.life <= 0:
            m.alive = False
            return
        # decoys fool seekers: the nearest decoy of the opposing side within range steals the lock
        for d in self.decoys:
            if d.team != m.team and dist(m.x, m.y, d.x, d.y) < 120 and not m.fooled:
                m.fooled = True
                m.target = None
                m.decoy = d
                self.emit("fooled", m.x, m.y)
        tx = ty = None
        dec = getattr(m, "decoy", None)
        if m.fooled and dec is not None and dec.life > 0:
            tx, ty = dec.x, dec.y
        elif m.target is not None and m.target.alive:
            tx, ty = m.target.x, m.target.y
        if tx is not None:
            want = math.atan2(ty - m.y, tx - m.x)
            da = wrap(want - m.heading)
            m.heading += max(-1, min(1, da / 0.1)) * math.radians(m.turn) * dt
        sp = math.hypot(m.vx, m.vy) or 1.0
        sp = min(max(sp, 330.0), 380.0)
        m.vx, m.vy = math.cos(m.heading) * sp, math.sin(m.heading) * sp
        m.x += m.vx * dt
        m.y += m.vy * dt
        for b in self.bolts:                         # missiles can be shot down
            if b.alive and b.team != m.team and (b.x - m.x) ** 2 + (b.y - m.y) ** 2 < 100:
                b.alive = False
                m.alive = False
                self.emit("explode", m.x, m.y, big=False)
                return
        detonate = False
        for s in ships:
            if s.alive and s.team != m.team and (s.x - m.x) ** 2 + (s.y - m.y) ** 2 <= (s.radius + 5) ** 2:
                detonate = True
        for (sx, sy, sr) in self.solid_bodies():
            if (sx - m.x) ** 2 + (sy - m.y) ** 2 < sr * sr:
                detonate = True
        if dec is not None and m.fooled and dec.life > 0 and dist(m.x, m.y, dec.x, dec.y) < 10:
            dec.life = 0
            detonate = True
        if detonate:
            m.alive = False
            self.emit("explode", m.x, m.y, big=True)
            owner = next((o for o in ships if o.id == m.owner), None)
            for s in ships:
                if s.alive and s.team != m.team and dist(s.x, s.y, m.x, m.y) <= m.blast + s.radius:
                    fall = 1.0 - 0.5 * dist(s.x, s.y, m.x, m.y) / (m.blast + s.radius)
                    self._damage(s, m.damage * fall, m.shield_mul, m.hull_mul, owner)

    # ===================================================================================== physics
    def _ship_physics(self, s: Ship, dt: float) -> None:
        s.x += s.vx * dt
        s.y += s.vy * dt
        if s.flash:
            s.flash -= 1
        for (sx, sy, sr) in self.solid_bodies():
            dx, dy = s.x - sx, s.y - sy
            d = math.hypot(dx, dy) or 1e-6
            lim = sr + s.radius
            if d < lim:
                nx, ny = dx / d, dy / d
                s.x, s.y = sx + nx * lim, sy + ny * lim
                vn = s.vx * nx + s.vy * ny
                if vn < 0:
                    s.vx -= 1.6 * vn * nx
                    s.vy -= 1.6 * vn * ny
                    self._damage(s, min(60.0, -vn * 0.18), 0.5, 1.0, None)
            if sr == self.sys.star.radius and sx == 0.0 and sy == 0.0 and d < sr * 2.1 and s is self.player:
                s.heat += (1.0 - d / (sr * 2.1)) * 55 * dt            # flying close to the star cooks the ship
        # belts: rocks chip shields
        for b in self.sys.bodies:
            if b.kind == "belt" and abs(math.hypot(s.x, s.y) - b.orbit.a) < 70 and s is self.player:
                n = b.extra.get("rocks", 26)
                for k in range(n):
                    rx, ry = belt_rock_state(self.sys, b, k, n, self.game.clock)
                    if (rx - s.x) ** 2 + (ry - s.y) ** 2 < (s.radius + 5) ** 2:
                        sp = math.hypot(s.vx, s.vy)
                        if sp > 60:
                            self._damage(s, sp * 0.02, 1.0, 1.0, None)
                            s.vx *= 0.7
                            s.vy *= 0.7
        lim = self.sys.extent() * 1.6
        d = math.hypot(s.x, s.y)
        if d > lim:
            s.x *= lim / d
            s.y *= lim / d
            s.vx *= 0.5
            s.vy *= 0.5

    # ===================================================================================== NPC brains
    def _turn_to(self, s: Ship, ang: float, dt: float, rate: float | None = None) -> float:
        rate = math.radians(rate or s.stats["rot"])
        da = wrap(ang - s.heading)
        s.heading = wrap(s.heading + max(-rate * dt, min(rate * dt, da)))
        return da

    def _thrust(self, s: Ship, amount: float, dt: float, limit: float | None = None) -> None:
        a = s.stats["thrust"] * amount
        s.vx += math.cos(s.heading) * a * dt
        s.vy += math.sin(s.heading) * a * dt
        mx = limit or s.stats["max_speed"]
        sp = math.hypot(s.vx, s.vy)
        if sp > mx:
            s.vx *= mx / sp
            s.vy *= mx / sp

    def _fire_bolt(self, s: Ship, damage: float, speed: float = 380.0, spread: float = 4.0) -> None:
        a = s.heading + math.radians(self.rng.uniform(-spread, spread))
        self.bolts.append(Bolt(s.x + math.cos(a) * 11, s.y + math.sin(a) * 11, s.vx + math.cos(a) * speed, s.vy + math.sin(a) * speed,
                               1.4, damage * self.diff, s.team, s.id, 1.0, 0.8))
        self.emit("npc_pulse", s.x, s.y)

    def _npc(self, e: Ship, dt: float) -> None:
        p = self.player
        b = e.brain
        e.age += dt
        for k in e.cool:
            e.cool[k] = max(0.0, e.cool[k] - dt)
        e.energy = min(e.energy_max, e.energy + 18 * dt)
        self._regen_shield(e, e.stats, dt)
        dx, dy = p.x - e.x, p.y - e.y
        d = math.hypot(dx, dy) or 1e-6
        want = math.atan2(dy, dx)
        if e.kind == "patrol" and not b["aware"]:
            self._patrol_warn(e, d, dt)
            return
        if not p.alive:
            self._thrust(e, 0.0, dt)
            return
        # lead the target: aim where the player will be when the bolt arrives (honest, imperfect)
        lead = d / 380.0
        aim = math.atan2(dy + p.vy * lead * 0.7, dx + p.vx * lead * 0.7)
        if e.kind == "drone":
            self._turn_to(e, want, dt)
            self._thrust(e, 1.0, dt)
            if d < e.radius + p.radius + 6 and e.cool["pulse"] <= 0:
                e.cool["pulse"] = 0.5
                self._damage(p, 6.0 * self.diff, 1.0, 1.0, e)
                e.vx *= -0.3
                e.vy *= -0.3
            return
        pref = 230.0
        jink = 0.0
        if e.kind == "hunter":
            pref += 90 * self.adapt.level("outrange_beam") / 0.4
            jink = 1.0 + 3.0 * self.adapt.level("jink") / 0.4
            if self.adapt.level("evade_missiles") > 0.05 and any(m.target is e for m in self.missiles) and e.decoys > 0 and \
                    e.cool.get("decoy", 0) <= 0:
                e.decoys -= 1
                e.cool["decoy"] = 1.0
                self.decoys.append(Decoy(e.x, e.y, e.vx * 0.3, e.vy * 0.3, 4.0, 1))
        if b["flee"] > 0:
            b["flee"] -= dt
            self._turn_to(e, want + math.pi, dt)
            self._thrust(e, 1.0, dt)
            return
        if e.shield < e.shield_max * 0.15 and e.hull < e.hull_max * 0.5 and e.kind in ("raider",):
            b["flee"] = 3.0
        slot = b.get("slot", 0)
        flank = (slot - 1) * 0.6 * b["side"]
        if d > pref + 60:
            self._turn_to(e, want + flank * 0.3, dt)
            self._thrust(e, 1.0, dt)
        else:
            tang = want + b["side"] * math.pi / 2 * (0.6 + 0.3 * math.sin(self.time * 0.7 + slot))
            if jink:
                tang += math.sin(self.time * 2.3 * jink + e.id) * 0.5
            tgt = want if d < pref - 70 else tang
            self._turn_to(e, aim if abs(wrap(aim - e.heading)) < 0.6 and d < pref + 120 else tgt, dt)
            self._thrust(e, 0.7 if d > pref - 90 else -0.0, dt, limit=e.stats["max_speed"] * 0.8)
            if d < pref - 40:
                e.vx -= math.cos(want) * 60 * dt
                e.vy -= math.sin(want) * 60 * dt
        # fire when roughly aligned with the lead point, with human-like cadence
        if d < 520 and abs(wrap(aim - e.heading)) < math.radians(7) and e.cool["pulse"] <= 0:
            e.cool["pulse"] = (0.42 if e.kind == "raider" else 0.3) / max(0.6, self.diff)
            self._fire_bolt(e, 7.0 if e.kind == "raider" else 9.0 if e.kind == "patrol" else 10.0)
        if e.kind == "hunter" and e.missiles > 0 and d < 500 and e.cool["missile"] <= 0 and abs(wrap(want - e.heading)) < 0.3:
            e.missiles -= 1
            e.cool["missile"] = 5.0
            self.missiles.append(Missile(e.x, e.y, e.vx + math.cos(e.heading) * 330, e.vy + math.sin(e.heading) * 330, e.heading, 4.0,
                                         1, e.id, p, 40 * self.diff, 40, 130))
            self.emit("missile", e.x, e.y)

    def _patrol_warn(self, e: Ship, d: float, dt: float) -> None:
        b = e.brain
        e.age += 0.0
        if d < 700:
            b["warn"] += dt
            if not b.get("said"):
                b["said"] = True
                self.comms.append("Patrol: you are listed hostile. Leave this system or be fired on.")
                self.emit("comms", e.x, e.y)
            if b["warn"] > 5.0:
                b["aware"] = True
        else:
            b["warn"] = max(0.0, b["warn"] - dt)

    def _freighter(self, f: Ship, dt: float) -> None:
        # drifts along a lazy circle; if shot at it flees and does not fight back
        f.age += dt
        a = f.age * 0.05 + f.id
        if f.brain.get("hostile"):
            p = self.player
            self._turn_to(f, math.atan2(f.y - p.y, f.x - p.x), dt)
            self._thrust(f, 1.0, dt)
        else:
            self._turn_to(f, a + math.pi / 2, dt)
            self._thrust(f, 0.4, dt, 70)
        self._regen_shield(f, f.stats, dt)

    # ===================================================================================== world interaction
    def _pickups(self, dt: float) -> None:
        p = self.player
        g = self.game
        for c in self.crates:
            c.life -= dt
            if p.alive and dist(c.x, c.y, p.x, p.y) < PICKUP_RADIUS:
                c.life = 0
                if c.kind == "credits":
                    g.credits += c.amount
                    self.msgs.append(f"+{int(c.amount)} credits")
                elif c.kind == "fuel":
                    g.fuel = min(self.stats["fuel"], g.fuel + c.amount)
                    self.msgs.append("Fuel salvaged")
                elif c.kind == "goods":
                    n = min(int(c.amount), g.cargo_free())
                    if n > 0:
                        g.cargo[c.good] = g.cargo.get(c.good, 0) + n
                        self.msgs.append(f"Looted {n} {self.defs.goods[c.good]['name']}")
                    else:
                        c.life = 30
                self.emit("pickup", c.x, c.y)
        self.crates = [c for c in self.crates if c.life > 0]

    def jump_ready(self) -> bool:
        """The lane drive needs open space: far from the star and nobody hostile close by."""
        p = self.player
        if not p.alive or math.hypot(p.x, p.y) < self.sys.extent() * 0.75:
            return False
        return not any(e.alive and dist(e.x, e.y, p.x, p.y) < 520 for e in self.enemies)

    def nearest_interactive(self):
        """The body the player could interact with right now (docking range, scan range or gear), with its position."""
        p = self.player
        best, bd = None, 1e9
        for b, (x, y) in zip(self.sys.bodies, self.body_pos):
            if b.kind in ("station", "anomaly", "derelict", "lamp"):
                d = dist(p.x, p.y, x, y)
                lim = 56 if b.kind == "station" else 70
                if d < lim + b.radius and d < bd:
                    best, bd = (b, x, y), d
        return best

    def _world_interactions(self, ctl: FlightControls, dt: float) -> None:
        p = self.player
        if not p.alive:
            return
        near = self.nearest_interactive()
        self.scan_target = near[0] if near else None
        # trapped derelicts release drones when approached
        for b, (x, y) in zip(self.sys.bodies, self.body_pos):
            if b.kind == "derelict" and b.extra.get("trapped") and b.id not in self.trap_triggered and dist(p.x, p.y, x, y) < 150 \
                    and b.id not in self.game.looted:
                self.trap_triggered.add(b.id)
                for i in range(3 + (1 if self.diff > 1 else 0)):
                    a = self.rng.uniform(0, math.tau)
                    self._make("drone", x + math.cos(a) * 60, y + math.sin(a) * 60)
                self.comms.append("The wreck was a trap: drones are waking!")
        if not ctl.interact or near is None:
            self.scan_t = 0.0
            self.lamp_hold = 0.0
            return
        b, x, y = near
        if b.kind == "station":
            if math.hypot(p.vx, p.vy) < 90:
                self.dock_request = b
                self.scan_t = 0.0
            else:
                self.msgs.append("Slow down to dock.")
            return
        if b.kind == "anomaly" and b.sub == "emitter":
            sig = b.extra.get("signal")
            if sig and self.game.can_decode(sig):
                self.decode_request = sig
            return
        if b.kind == "lamp":
            self.lamp_hold += dt
            if self.lamp_hold >= 2.0:
                self.lamp_hold = 0.0
                msg = self.game.wind_gear(b.extra.get("order", 0))
                self.msgs.append(msg)
                self.emit("gear", x, y, order=b.extra.get("order", 0), ok="turns" in msg or "catches" in msg)
                if self.game.lamp["done"]:
                    self.emit("lamp_lit", x, y)
            return
        self.scan_t += dt
        if self.scan_t >= 1.4:
            self.scan_t = 0.0
            for line in self.game.interact_body(b, self.rng):
                self.msgs.append(line)
            self.emit("scanned", x, y)
