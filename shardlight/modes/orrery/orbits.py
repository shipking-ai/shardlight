"""Analytic orbit maths: every body's position is a pure function of time (no integration drift).

Orbits are Keplerian ellipses (parent body at one focus).  ``orbit_state`` solves Kepler's equation with a few
Newton steps, so a planet's place at ``t`` is exact whether the player has watched it or not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TAU = math.tau
PERIOD_K = 70.0        # seconds per orbit at a = 500 world units around a mass-1 parent (before the 1.5 power)
AU_WU = 1000.0         # world units that stand for 1 AU when computing temperature


@dataclass(frozen=True)
class Orbit:
    a: float            # semi-major axis (world units)
    e: float            # eccentricity
    w: float            # argument of periapsis (radians)
    m0: float           # mean anomaly at t = 0
    period: float       # seconds per orbit; <= 0 means "fixed point" (a, w give a static offset)

    def to_list(self) -> list[float]:
        return [self.a, self.e, self.w, self.m0, self.period]

    @staticmethod
    def from_list(v: list[float]) -> "Orbit":
        return Orbit(float(v[0]), float(v[1]), float(v[2]), float(v[3]), float(v[4]))


def kepler_period(a: float, parent_mass: float = 1.0, ref_a: float = 500.0) -> float:
    """Kepler's third law in game units: T = K * (a / ref)^1.5 / sqrt(mass)."""
    return PERIOD_K * (max(a, 1.0) / ref_a) ** 1.5 / math.sqrt(max(parent_mass, 0.05))


def solve_kepler(m: float, e: float) -> float:
    """Eccentric anomaly E with E - e sin E = M (Newton iteration, converges in < 8 steps for e < 0.9)."""
    m = (m + math.pi) % TAU - math.pi
    ecc = m if e < 0.8 else math.pi
    for _ in range(12):
        f = ecc - e * math.sin(ecc) - m
        d = f / (1.0 - e * math.cos(ecc))
        ecc -= d
        if abs(d) < 1e-10:
            break
    return ecc


def orbit_state(o: Orbit, t: float) -> tuple[float, float, float, float]:
    """(x, y, vx, vy) relative to the parent at time ``t``."""
    if o.period <= 0:
        return (math.cos(o.w) * o.a, math.sin(o.w) * o.a, 0.0, 0.0)
    n = TAU / o.period
    ecc = solve_kepler(o.m0 + n * t, o.e)
    ce, se = math.cos(ecc), math.sin(ecc)
    b = o.a * math.sqrt(1.0 - o.e * o.e)
    px, py = o.a * (ce - o.e), b * se
    de = n / (1.0 - o.e * ce)
    pvx, pvy = -o.a * se * de, b * ce * de
    cw, sw = math.cos(o.w), math.sin(o.w)
    return (px * cw - py * sw, px * sw + py * cw, pvx * cw - pvy * sw, pvx * sw + pvy * cw)


def orbit_position(o: Orbit, t: float) -> tuple[float, float]:
    x, y, _, _ = orbit_state(o, t)
    return x, y


def orbit_radius(o: Orbit, t: float) -> float:
    x, y = orbit_position(o, t)
    return math.hypot(x, y)


def equilibrium_temp(luminosity: float, a_wu: float, albedo: float = 0.3, greenhouse: float = 0.0) -> float:
    """Kelvin: T = 278 * L^0.25 / sqrt(a_AU) * (1 - albedo)^0.25, plus a greenhouse bump."""
    a_au = max(a_wu, 20.0) / AU_WU
    t = 278.0 * (max(luminosity, 0.001) ** 0.25) / math.sqrt(a_au) * ((1.0 - albedo) / 0.7) ** 0.25
    return t * (1.0 + greenhouse)


def habitable_zone_wu(luminosity: float) -> float:
    """Orbit radius (world units) where an Earth-like albedo gives ~288 K."""
    return AU_WU * math.sqrt(max(luminosity, 0.001))
