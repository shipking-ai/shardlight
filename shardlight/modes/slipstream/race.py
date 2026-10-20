"""Race simulation: cars on a track, laps and checkpoints, collisions, draft, rewind, ghosts and results.

Pure Python and deterministic given the controllers.  ``Race.step`` advances exactly 1/60 s.
"""
from __future__ import annotations

import base64
import math
import struct
from collections import deque
from dataclasses import dataclass, field

from .physics import (OIL, ROUGH, SURFACE_DRAG, SURFACE_MU, Car, Controls, Env, circle_bump, resolve_cars,
                      wall_response)
from .track import SHOULDER, SPACING, Track
from .vehicle import VehicleSpec

DT = 1.0 / 60.0
COUNTDOWN = 3.0
DRAFT_RANGE = 120.0
REWIND_FRAMES = 90
POINTS_DEFAULT = (10, 6, 4, 3, 2, 1)
STUCK_RESET = 3.5


@dataclass
class Racer:
    idx: int
    name: str
    spec: VehicleSpec
    car: Car
    human: int = -1                      # player slot, -1 = AI
    driver: object | None = None         # AI driver (has .control(race, racer) -> Controls)
    color: tuple = (239, 75, 51)
    hint: int = 0
    prev_i: int = 0
    started: bool = False
    laps_done: int = 0
    next_gate: int = 0
    lap_start: float = 0.0
    lap_times: list[float] = field(default_factory=list)
    best_lap: float = 0.0
    finished: bool = False
    finish_time: float = 0.0
    position: int = 0
    prog: float = 0.0
    zone: str = "track"
    ctl: Controls = field(default_factory=Controls)
    history: deque = field(default_factory=lambda: deque(maxlen=REWIND_FRAMES))
    rewind_ready: bool = True
    stuck_t: float = 0.0
    wrong_way_t: float = 0.0
    hits: int = 0
    wall_hits: int = 0
    cut_taken: int = 0
    events: list = field(default_factory=list)       # (kind, data) consumed by the scene each tick
    ghost_samples: list = field(default_factory=list)
    on_cut: bool = False
    drift_total: float = 0.0
    in_dust: bool = False
    best_flag: bool = False
    stall_t: float = 0.0
    stall_prog: float = 0.0


class Race:
    def __init__(self, track: Track, laps: int = 3, seed: int = 0):
        self.track = track
        self.laps = laps
        self.t = -COUNTDOWN
        self.racers: list[Racer] = []
        self.state = "countdown"           # countdown | racing | finished
        self.first_finish = None
        self.results: list[Racer] = []
        self.frame = 0
        self.seed = seed
        self.events: list[tuple] = []
        self.on_pass = None                # callback(passer, passed) for adaptation models

    # ------------------------------------------------------------------ setup
    def add(self, name: str, spec: VehicleSpec, human: int = -1, driver=None, grid_slot: int | None = None,
            color=None) -> Racer:
        slot = len(self.racers) if grid_slot is None else grid_slot
        grid = self.track.start_grid(max(8, slot + 1))
        x, y, h = grid[slot]
        car = Car(spec, x, y, h)
        r = Racer(len(self.racers), name, spec, car, human, driver, color or spec.accent)
        i, _ = self.track.nearest(x, y)
        r.hint = r.prev_i = i
        r.started = False
        self.racers.append(r)
        return r

    # ------------------------------------------------------------------ helpers
    def _env(self, r: Racer, x: float, y: float) -> Env:
        tr = self.track
        zone, i, d, surf = tr.probe(x, y, r.hint)
        r.zone = zone
        env = Env(mu=SURFACE_MU[surf], drag=SURFACE_DRAG[surf], surface=surf)
        hz = tr.hazard_surface(x, y)
        r.in_dust = False
        if hz == OIL:
            env.mu, env.surface = SURFACE_MU[OIL], OIL
            r.car.oil_t = 0.6
        elif hz is not None:
            r.in_dust = True
            env.mu = min(env.mu, 0.8)
            env.drag += 0.1
        return env

    def _draft(self, r: Racer) -> float:
        best = 0.0
        c = r.car
        fx, fy = math.cos(c.heading), math.sin(c.heading)
        for o in self.racers:
            if o is r or o.finished:
                continue
            dx, dy = o.car.x - c.x, o.car.y - c.y
            ahead = dx * fx + dy * fy
            if ahead < 12 or ahead > DRAFT_RANGE:
                continue
            side = abs(-dx * fy + dy * fx)
            if side > 13 + ahead * 0.07:
                continue
            if c.speed < 90:
                continue
            best = max(best, (1 - ahead / DRAFT_RANGE) ** 0.7)
        return best

    def _update_progress(self, r: Racer) -> None:
        tr = self.track
        n = tr.n
        c = r.car
        zone, i, d, surf = tr.probe(c.x, c.y, r.hint)
        if zone == "cut" and tr.cut is not None:
            _, t = tr.cut.lateral(c.x, c.y)
            span = (tr.cut.ib - tr.cut.ia) % n
            i = (tr.cut.ia + int(t * span)) % n
            if not r.on_cut:
                r.on_cut = True
        elif r.on_cut and zone in ("track", "rough"):
            r.on_cut = False
            r.cut_taken += 1
            r.events.append(("shortcut", None))
        r.hint = i
        step = (i - r.prev_i + n // 2) % n - n // 2        # signed samples advanced
        if step > 0 and step < 110:
            # checkpoints are crossed in order; the shortcut removes the gates it skips
            while r.next_gate < len(tr.gates):
                g = tr.gates[r.next_gate]
                rel = (g - r.prev_i) % n
                if 0 < rel <= step:
                    r.next_gate += 1
                    r.events.append(("gate", r.next_gate))
                else:
                    break
            rel_start = (tr.start - r.prev_i) % n
            if 0 < rel_start <= step:                       # crossing the line
                if not r.started:
                    r.started = True
                    r.lap_start = self.t
                elif r.next_gate >= len(tr.gates):
                    self._lap_done(r)
        if step < -3:
            r.wrong_way_t += DT
        elif step > 0:
            r.wrong_way_t = max(0.0, r.wrong_way_t - DT * 2)
        r.prev_i = i
        if r.started:
            off = (i - tr.start) % n
        else:
            off = ((i - tr.start + n // 2) % n) - n // 2
        r.prog = r.laps_done * n + off

    def _lap_done(self, r: Racer) -> None:
        lt = self.t - r.lap_start
        r.lap_times.append(lt)
        r.laps_done += 1
        r.lap_start = self.t
        r.next_gate = 0
        r.rewind_ready = True
        if r.best_lap == 0 or lt < r.best_lap:
            r.best_lap = lt
            r.best_flag = True
        r.events.append(("lap", lt))
        if r.laps_done >= self.laps and not r.finished:
            r.finished = True
            r.finish_time = self.t
            self.results.append(r)
            r.events.append(("finish", len(self.results)))
            if self.first_finish is None:
                self.first_finish = self.t

    # ------------------------------------------------------------------ collisions
    def _walls(self, r: Racer) -> None:
        tr = self.track
        c = r.car
        zone, i, d, _ = tr.probe(c.x, c.y, r.hint)
        if zone == "wall":
            half = tr.width[i] * 0.5 + SHOULDER
            depth = abs(d) - half
            nx, ny = tr.norm[i]
            sgn = -1.0 if d > 0 else 1.0
            imp = wall_response(c, nx * sgn, ny * sgn, depth + 1.5, c.x, c.y)
            if imp > 25:
                r.wall_hits += 1
                lost = c.lose_drift()
                r.events.append(("wall", imp))
        for h in tr.hazards:
            if h.kind == "boulder" and (c.x - h.x) ** 2 + (c.y - h.y) ** 2 < (h.r + 20) ** 2:
                imp = circle_bump(c, h.x, h.y, h.r)
                if imp > 20:
                    r.events.append(("wall", imp))
                    c.lose_drift()

    def _cars(self) -> None:
        rs = self.racers
        for a in range(len(rs)):
            for b in range(a + 1, len(rs)):
                if rs[a].finished and rs[b].finished:
                    continue
                res = resolve_cars(rs[a].car, rs[b].car)
                if res and res[0] > 18:
                    rs[a].hits += 1
                    rs[b].hits += 1
                    rs[a].car.lose_drift()
                    rs[b].car.lose_drift()
                    rs[a].events.append(("bump", res[0]))
                    rs[b].events.append(("bump", res[0]))

    # ------------------------------------------------------------------ main step
    def step(self, dt: float = DT) -> None:
        self.frame += 1
        self.t += dt
        if self.state == "countdown" and self.t >= 0:
            self.state = "racing"
            self.events.append(("go", None))
            for r in self.racers:                 # standing-start grace: no car-to-car contact for a few seconds
                r.car.ghost_t = max(r.car.ghost_t, 3.5)
        order_before = [r.idx for r in sorted(self.racers, key=lambda q: -q.prog)]
        for r in self.racers:
            r.events.clear()
            if r.driver is not None and not r.finished:
                r.ctl = r.driver.control(self, r)
            elif r.finished:
                r.ctl = Controls(throttle=0.0, brake=0.35)
            if self.state == "countdown":
                r.ctl = Controls(throttle=0.0, brake=0.0)
                r.car.vx = r.car.vy = 0.0
                r.car.yaw = 0.0
            env = self._env(r, r.car.x, r.car.y)
            env.draft = self._draft(r)
            if r.ctl.rewind:
                self._rewind(r)
            r.history.append(r.car.snapshot())
            r.car.step(r.ctl, env, dt)
            if r.car.drifting:
                r.drift_total += dt
        self._cars()
        for r in self.racers:
            self._walls(r)
            self._update_progress(r)
            self._stuck(r, dt)
            if self.state == "racing" and not r.finished and r.human >= 0 or False:
                pass
        self._rank(order_before)
        for r in self.racers:
            if len(r.ghost_samples) < 90 * 60 and not r.finished and self.state == "racing":
                if self.frame % 2 == 0:
                    r.ghost_samples.append((r.car.x, r.car.y, r.car.heading))
        humans_done = all(r.finished for r in self.racers if r.human >= 0) if any(r.human >= 0 for r in self.racers) else all(r.finished for r in self.racers)
        timeout = self.first_finish is not None and self.t - self.first_finish > 35
        if self.state == "racing" and (humans_done or timeout or all(r.finished for r in self.racers)):
            self.state = "finished"
            self._finalize()

    def _rank(self, order_before: list[int]) -> None:
        ranked = sorted(self.racers, key=lambda q: (not q.finished, q.finish_time if q.finished else -q.prog))
        # finished cars keep the order they finished; the rest by progress
        fin = [q for q in self.results]
        rest = sorted([q for q in self.racers if not q.finished], key=lambda q: -q.prog)
        for pos, q in enumerate(fin + rest, 1):
            q.position = pos
        if self.state == "racing" and self.on_pass:
            now = [q.idx for q in fin + rest]
            for a_i, a in enumerate(now):
                if a in order_before and now.index(a) < order_before.index(a):
                    for b in order_before[now.index(a):order_before.index(a)]:
                        if b != a and now.index(b) > now.index(a):
                            self.on_pass(self.racers[a], self.racers[b])

    def _finalize(self) -> None:
        done = list(self.results)
        rest = sorted([q for q in self.racers if not q.finished], key=lambda q: -q.prog)
        self.results = done + rest
        for pos, q in enumerate(self.results, 1):
            q.position = pos
        self.events.append(("results", None))

    def _stuck(self, r: Racer, dt: float) -> None:
        c = r.car
        if self.state != "racing" or r.finished:
            return
        if c.speed < 12 and r.ctl.throttle > 0.3 or r.wrong_way_t > 5 or r.zone == "wall":
            r.stuck_t += dt
        else:
            r.stuck_t = max(0.0, r.stuck_t - dt * 2)
        r.stall_t += dt
        if r.stall_t >= 3.0:                      # a jam of cars, or wedged in a corner: no real progress
            if r.driver is not None and r.prog - r.stall_prog < 5 and r.started or r.prog - r.stall_prog < -30:
                r.stuck_t = STUCK_RESET + 1
            r.stall_t = 0.0
            r.stall_prog = r.prog
        manual = r.ctl.reset
        if r.stuck_t > STUCK_RESET or manual:
            self.respawn(r)

    def respawn(self, r: Racer) -> None:
        tr = self.track
        i = r.hint if not r.on_cut else (tr.cut.ia if tr.cut else r.hint)
        i = (i - 4) % tr.n
        x, y = tr.pts[i]
        h = math.atan2(tr.tang[i][1], tr.tang[i][0])
        r.car.place(x, y, h, 40.0)
        r.car.ghost_t = 1.8
        r.stuck_t = 0.0
        r.wrong_way_t = 0.0
        r.hint = r.prev_i = i
        r.on_cut = False
        r.events.append(("respawn", None))

    def _rewind(self, r: Racer) -> None:
        if r.spec.special != "rewind" or not r.rewind_ready or len(r.history) < 20:
            return
        snap = r.history[0]
        r.car.restore(snap)
        r.car.ghost_t = 1.2
        r.rewind_ready = False
        r.history.clear()
        r.events.append(("rewind", None))
        i, _ = self.track.nearest(r.car.x, r.car.y, r.hint, 140)
        r.hint = r.prev_i = i

    # ------------------------------------------------------------------ queries
    def by_human(self, slot: int) -> Racer | None:
        return next((r for r in self.racers if r.human == slot), None)

    def gap_to_leader(self, r: Racer) -> float:
        lead = max(self.racers, key=lambda q: q.prog)
        return (lead.prog - r.prog) * SPACING


# ------------------------------------------------------------------------------------------- ghosts
def pack_ghost(samples: list[tuple[float, float, float]]) -> str:
    out = bytearray()
    for x, y, h in samples:
        out += struct.pack("<hhh", int(max(-8000, min(8000, x * 4))), int(max(-8000, min(8000, y * 4))),
                           int(h * 1000))
    return base64.b64encode(bytes(out)).decode("ascii")


def unpack_ghost(blob: str) -> list[tuple[float, float, float]]:
    try:
        raw = base64.b64decode(blob.encode("ascii"), validate=True)
    except (ValueError, TypeError):
        return []
    n = len(raw) // 6
    return [(a / 4.0, b / 4.0, c / 1000.0) for a, b, c in struct.iter_unpack("<hhh", raw[:n * 6])]


def ghost_pose(samples: list, t: float) -> tuple[float, float, float] | None:
    """Pose at race time ``t`` (samples are every 2 ticks = 1/30 s)."""
    if not samples or t < 0:
        return None
    f = t * 30.0
    i = int(f)
    if i >= len(samples) - 1:
        return None
    a, b = samples[i], samples[i + 1]
    k = f - i
    dh = (b[2] - a[2] + math.pi) % math.tau - math.pi
    return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + dh * k
