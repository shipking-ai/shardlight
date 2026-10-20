"""Synthesised effects for the Orrery (prefix ``orrery_``): pulses, shields, locks, drives, brass gears."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _d(x, tau):
    return x * S.decay(len(x), tau)


def pulse():
    d = 0.12
    return S.normalize(S.fade_edges(_d(S.sweep(1500, 420, d, "square"), 0.05) * 0.5 + _d(S.highpass(S.noise(d, 31), 2500), 0.02) * 0.3), 0.5)


def missile():
    d = 0.5
    return S.normalize(S.fade_edges(S.lowpass(S.noise(d, 32), 1800) * np.linspace(0.2, 1, S.n_samples(d)) ** 0.5 * 0.6
                                    + S.sweep(180, 520, d, "saw") * 0.25 * S.decay(S.n_samples(d), 0.4)), 0.7)


def shield():
    d = 0.22
    return S.normalize(S.fade_edges(_d(S.sweep(1900, 700, d), 0.07) * 0.6 + S.tremolo(S.sine(1200, d), 40, 0.7) * 0.3 * S.decay(S.n_samples(d), 0.1)), 0.6)


def hull():
    d = 0.18
    return S.normalize(S.fade_edges(_d(S.highpass(S.noise(d, 33), 500), 0.04) + _d(S.sweep(180, 60, d), 0.06) * 1.1), 0.85)


def boom():
    d = 0.8
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(160, 32, d), 0.25) + _d(S.bandpass(S.noise(d, 34), 80, 2200), 0.18) * 0.9, 0.5, 0.25)), 0.9)


def decoy():
    d = 0.3
    return S.normalize(S.fade_edges(S.tremolo(S.sweep(900, 1500, d), 18, 0.6) * S.decay(S.n_samples(d), 0.15)), 0.55)


def scan():
    d = 0.5
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("e5", "g5", "b5", "e6")):
        S.place(buf, S.sine(S.note(n), 0.18) * S.decay(S.n_samples(0.18), 0.07), i * 0.07, 0.5)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.4, 0.3)), 0.55)


def gear():
    d = 0.9
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i in range(6):
        S.place(buf, _d(S.highpass(S.noise(0.04, 40 + i), 1800), 0.01), i * 0.05, 0.6)
    S.place(buf, _d(S.sine(S.note("g3"), 0.7), 0.3), 0.3, 0.6)
    S.place(buf, _d(S.sine(S.note("d4"), 0.7), 0.35), 0.3, 0.35)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.7, 0.3)), 0.75)


def dock():
    d = 0.45
    return S.normalize(S.fade_edges(_d(S.sweep(200, 90, d), 0.2) * 0.6 + _d(S.bandpass(S.noise(d, 35), 300, 1400), 0.08) * 0.5
                                    + _d(S.sine(S.note("c5"), d), 0.12) * 0.3), 0.7)


def jump():
    d = 1.1
    n = S.n_samples(d)
    up = S.sweep(60, 1800, d, "saw", 2.0) * np.linspace(0, 1, n) ** 1.6
    return S.normalize(S.fade_edges(S.reverb(up * 0.35 + S.lowpass(S.noise(d, 36), 900) * np.sin(np.linspace(0, np.pi, n)) * 0.5, 0.6, 0.3)), 0.85)


for name, fn in {"pulse": pulse, "missile": missile, "shield": shield, "hull": hull, "boom": boom, "decoy": decoy,
                 "scan": scan, "gear": gear, "dock": dock, "jump": jump}.items():
    register_sfx(f"orrery_{name}", fn)
