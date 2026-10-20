"""Pacing director for the Gloaming Ward.

A small state machine (calm -> build -> peak -> relax) that decides *when* an enemy is sent to look for the player,
never *where the player is*: it nudges an enemy toward the player's neighbourhood and lets the enemy's own senses
take over.  Rules it enforces (and the tests check): an opening calm, a minimum calm between peaks, a cap on peaks
per night and on simultaneous hunters, no peaks while the player is in a safe room, and a hard time limit on a
peak.  It also owns the bounded adaptation of the Understudy to the player's habits (``core.ai``).
"""
from __future__ import annotations

import math

from ...core.ai import Adaptation, AdaptiveController, PlayerModel
from .consts import TILE


class Director:
    def __init__(self, game):
        self.g = game
        cfg = game.nd.get("director", {})
        self.cfg = {"opening_calm": 40.0, "calm_min": 24.0, "relax_min": 20.0, "build_min": 16.0, "max_peaks": 5, "peak_max": 60.0, "max_hunters": 2}
        self.cfg.update({k: float(v) for k, v in cfg.items()})
        self.state = "calm"
        self.t = 0.0
        self.peaks = 0
        self.last_peak_end = -1e9
        self.timeline: list[tuple[float, str]] = [(0.0, "calm")]
        self.tension = 0.0
        self.peak_start = 0.0
        self.quiet_t = 0.0
        self.player_model = PlayerModel(half_life=35.0)
        kinds = ("hide_locker", "hide_bed", "hide_table")
        self.ctl = AdaptiveController(self.player_model, [
            Adaptation("habit_locker", "hide_locker", kinds, 0.5, 2.0, 0.4),
            Adaptation("habit_bed", "hide_bed", kinds, 0.5, 2.0, 0.4),
            Adaptation("habit_table", "hide_table", kinds, 0.5, 2.0, 0.4),
            Adaptation("listen_runs", "run", ("run", "sneak", "walk"), 0.55, 6.0, 0.25),
        ], strength=game.adapt, cooldown=10.0)

    def level(self, name: str) -> float:
        return self.ctl.level(name)

    # ------------------------------------------------------------------ state machine
    def _go(self, state: str) -> None:
        self.state = state
        self.t = 0.0
        self.timeline.append((self.g.time, state))

    def reset(self) -> None:
        self.state = "calm"
        self.t = 0.0
        self.last_peak_end = self.g.time
        self.timeline.append((self.g.time, "calm"))
        self.quiet_t = 0.0

    def on_death(self) -> None:
        pass

    def hunters(self):
        return [e for e in self.g.enemies if e.hunting()]

    def update(self, dt: float) -> None:
        g = self.g
        self.ctl.update(g.time, dt)
        self.t += dt
        p = g.p
        # smoothed tension from what the enemies are doing and how close they are
        raw = 0.0
        for e in g.enemies:
            d = math.hypot(e.x - p.x, e.y - p.y) / TILE
            w = 1.0 if e.state in ("hunt", "rush") else 0.55 if e.state in ("investigate", "stalk", "check", "search") else 0.12
            raw = max(raw, w * max(0.0, 1.0 - d / 22.0))
        self.tension += (raw - self.tension) * min(1.0, dt * 1.4)
        in_safe = g.in_safe_room()
        cfg = self.cfg
        if self.state == "calm":
            gap = g.time - self.last_peak_end
            first = self.peaks == 0
            if self.t >= (cfg["opening_calm"] if first else cfg["calm_min"]) and gap >= cfg["calm_min"] and not in_safe:
                self._go("build")
        elif self.state == "build":
            if in_safe:
                self._go("calm")
            elif self.t >= cfg["build_min"] and self.peaks < cfg["max_peaks"]:
                if self._start_peak():
                    self._go("peak")
                    self.peak_start = g.time
                    self.peaks += 1
                else:
                    self.t = cfg["build_min"] - 3.0
        elif self.state == "peak":
            # keep the pressure fair: never more simultaneous hunters than allowed
            hs = self.hunters()
            while len(hs) > cfg["max_hunters"]:
                far = max(hs, key=lambda e: math.hypot(e.x - p.x, e.y - p.y))
                far.calm()
                hs.remove(far)
            if in_safe:
                self.quiet_t += dt
                if self.quiet_t > 4.0:
                    for e in hs:
                        e.calm()
            else:
                self.quiet_t = 0.0
            if (not self.hunters() and self.t > 5.0) or self.t >= cfg["peak_max"]:
                for e in self.g.enemies:
                    if e.directed and e.state not in ("hunt", "rush"):
                        e.directed = False
                self.last_peak_end = g.time
                self.quiet_t = 0.0
                self._go("relax")
        elif self.state == "relax":
            if self.t >= cfg["relax_min"]:
                self._go("calm")

    def _start_peak(self) -> bool:
        g = self.g
        p = g.p
        cands = [e for e in g.enemies if not e.hunting()]
        if not cands:
            return False
        # prefer an enemy that is not already close: it needs time to arrive
        far = [e for e in cands if math.hypot(e.x - p.x, e.y - p.y) > 11 * TILE]
        pool = far or cands
        e = min(pool, key=lambda q: (q.rng.random() * 0.3 - min(math.hypot(q.x - p.x, q.y - p.y), 30 * TILE) / (30 * TILE)))
        room = g.room_at(p.x, p.y)
        if room is None or room.role == "safe":
            return False
        # head for the player's neighbourhood (their room centre or the last place they made noise), not their exact position
        tgt = ((room.center[0] + 0.5) * TILE, (room.center[1] + 0.5) * TILE)
        last = next((n for n in reversed(g.noise_log) if n.source == "player"), None)
        if last is not None and math.hypot(last.pos[0] - p.x, last.pos[1] - p.y) < 8 * TILE:
            tgt = last.pos
        e.director_investigate(tgt)
        g.say("peak", who=e.kind)
        return True

    def force_peak(self, reason: str) -> None:
        """A loud objective action starts a peak at once (the noise itself draws the enemies)."""
        g = self.g
        if self.state == "peak":
            return
        if self.peaks >= self.cfg["max_peaks"] + 2:
            return
        self.peaks += 1
        self.peak_start = g.time
        self._go("peak")
        g.say("peak", who=reason)

    def music_intensity(self) -> float:
        base = {"calm": 0.15, "build": 0.4, "peak": 0.9, "relax": 0.3}[self.state]
        return max(base * 0.6, min(1.0, self.tension * 1.1 + base * 0.4))
