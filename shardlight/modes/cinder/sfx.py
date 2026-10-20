"""Synthesised effects for Cinder (prefix ``cinder_``): blades, embers, stone, brass."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _d(x, tau):
    return x * S.decay(len(x), tau)


def swish(dur=0.14, lo=900, hi=5200, seed=1, vol=0.55):
    n = S.noise(dur, seed)
    band = S.bandpass(n, lo, hi)
    env = np.sin(np.linspace(0, np.pi, len(band))) ** 1.4
    return S.normalize(S.fade_edges(band * env), vol)


def slash(): return swish(0.13, 1200, 6000, 1)
def stab(): return swish(0.1, 1800, 7000, 2, 0.5)
def heavy(): return S.normalize(S.fade_edges(swish(0.22, 400, 3000, 3, 0.7) + _d(S.sweep(160, 70, 0.22), 0.07) * 0.5), 0.75)
def smash():
    d = 0.35
    return S.normalize(S.fade_edges(_d(S.sweep(120, 38, d), 0.12) + _d(S.lowpass(S.noise(d, 4), 500), 0.06) * 0.8), 0.9)
def blast():
    d = 0.5
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(220, 40, d), 0.15) + _d(S.bandpass(S.noise(d, 5), 200, 3000), 0.1), 0.4, 0.2)), 0.85)
def cast():
    d = 0.2
    return S.normalize(S.fade_edges(S.mixdown(S.sweep(500, 1400, d, "sine") * np.linspace(1, 0.2, S.n_samples(d)), swish(0.18, 2000, 7000, 6, 0.3))), 0.6)
def hit():
    d = 0.12
    return S.normalize(S.fade_edges(_d(S.highpass(S.noise(d, 7), 900), 0.025) + _d(S.sweep(220, 70, d), 0.04)), 0.85)
def hit_heavy():
    d = 0.2
    return S.normalize(S.fade_edges(_d(S.highpass(S.noise(d, 8), 600), 0.04) + _d(S.sweep(160, 45, d), 0.07) * 1.2), 0.95)
def kill():
    d = 0.3
    return S.normalize(S.fade_edges(S.reverb(_d(S.bandpass(S.noise(d, 9), 300, 4000), 0.08) + _d(S.sine(330, d), 0.1) * 0.3, 0.3, 0.2)), 0.7)
def hurt():
    d = 0.3
    return S.normalize(S.fade_edges(_d(S.sweep(300, 90, d, "saw"), 0.09) * 0.6 + _d(S.lowpass(S.noise(d, 10), 800), 0.05)), 0.9)
def parry():
    d = 0.5
    ring = sum(_d(S.sine(f, d), 0.14) * g for f, g in ((1568, 0.6), (2349, 0.4), (3136, 0.25)))
    return S.normalize(S.fade_edges(S.mixdown(ring, _d(S.highpass(S.noise(0.04, 11), 3000), 0.01))), 0.85)
def perfect():
    d = 0.35
    return S.normalize(S.fade_edges(_d(S.sweep(700, 2100, d), 0.12) + _d(S.sine(2800, d), 0.1) * 0.4), 0.6)
def roll():
    d = 0.2
    return S.normalize(S.fade_edges(S.bandpass(S.noise(d, 12), 200, 1600) * np.linspace(0.4, 1, S.n_samples(d)) ** 2), 0.4)
def boom():
    d = 0.7
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(200, 30, d), 0.22) + _d(S.bandpass(S.noise(d, 13), 100, 2500), 0.16), 0.6, 0.25)), 0.95)
def clear():
    parts = [S.sine(f, 0.5) * S.adsr(S.n_samples(0.5), 0.01, 0.1, 0.5, 0.3) for f in (S.note("e5"), S.note("g#5"), S.note("b5"))]
    buf = np.zeros(S.n_samples(0.9), dtype=np.float32)
    for i, p in enumerate(parts):
        S.place(buf, p, i * 0.1, 0.5)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.5, 0.3)), 0.7)
def door():
    d = 0.4
    return S.normalize(S.fade_edges(_d(S.sweep(90, 60, d, "square"), 0.12) * 0.5 + _d(S.bandpass(S.noise(d, 14), 200, 1200), 0.1)), 0.7)
def boss():
    d = 1.2
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(80, 36, d, "saw"), 0.5) * 0.6 + _d(S.sine(S.note("a2"), d), 0.6) * 0.5, 0.9, 0.3)), 0.95)
def evolve():
    buf = np.zeros(S.n_samples(1.4), dtype=np.float32)
    for i, n in enumerate(("c4", "e4", "g4", "c5", "e5", "g5")):
        S.place(buf, S.tri(S.note(n), 0.5) * S.adsr(S.n_samples(0.5), 0.01, 0.1, 0.5, 0.25), i * 0.09, 0.45)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.9, 0.35)), 0.85)
def block():
    d = 0.18
    return S.normalize(S.fade_edges(_d(S.sine(660, d), 0.05) * 0.5 + _d(S.highpass(S.noise(d, 15), 2000), 0.02) + _d(S.sine(1320, d), 0.04) * 0.3), 0.7)
def shoot():
    d = 0.15
    return S.normalize(S.fade_edges(S.mixdown(S.sweep(1100, 280, d, "square") * S.decay(S.n_samples(d), 0.05) * 0.5, swish(0.12, 1500, 6000, 16, 0.3))), 0.5)
def fuse():
    d = 0.4
    return S.normalize(S.fade_edges(S.tremolo(S.highpass(S.noise(d, 17), 2500), 30, 0.8) * 0.5 + S.sweep(600, 1400, d, "square") * 0.15), 0.5)
def charge():
    d = 0.3
    return S.normalize(S.fade_edges(S.sweep(80, 160, d, "saw") * 0.5 + S.lowpass(S.noise(d, 18), 600) * 0.5), 0.7)
def stagger():
    d = 0.25
    return S.normalize(S.fade_edges(S.mixdown(_d(S.sine(S.note("b4"), d), 0.07), _d(S.sine(S.note("f#5"), d), 0.05) * 0.5, _d(S.highpass(S.noise(0.05, 19), 3000), 0.01))), 0.7)
def death():
    d = 1.4
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(300, 40, d, "saw"), 0.5) * 0.5 + _d(S.sine(110, d), 0.6) * 0.4, 1.0, 0.35)), 0.9)
def note():
    d = 0.7
    return S.normalize(S.fade_edges(S.reverb(S.sine(S.note("d5"), d) * S.adsr(S.n_samples(d), 0.02, 0.1, 0.6, 0.3) * 0.7 + S.sine(S.note("a5"), d) * 0.3 * S.decay(S.n_samples(d), 0.3), 0.8, 0.35)), 0.7)
def floor():
    d = 0.9
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(110, 55, d), 0.4) + _d(S.bandpass(S.noise(d, 20), 80, 800), 0.3) * 0.5, 0.7, 0.3)), 0.8)
def boon():
    buf = np.zeros(S.n_samples(0.8), dtype=np.float32)
    for i, n in enumerate(("g4", "b4", "d5")):
        S.place(buf, S.sine(S.note(n), 0.4) * S.adsr(S.n_samples(0.4), 0.005, 0.08, 0.4, 0.2), i * 0.07, 0.6)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.5, 0.3)), 0.7)


for name, fn in {"slash": slash, "stab": stab, "heavy": heavy, "smash": smash, "blast": blast, "cast": cast, "hit": hit,
                 "hit_heavy": hit_heavy, "kill": kill, "hurt": hurt, "parry": parry, "perfect": perfect, "roll": roll,
                 "boom": boom, "clear": clear, "door": door, "boss": boss, "evolve": evolve, "block": block,
                 "shoot": shoot, "fuse": fuse, "charge": charge, "stagger": stagger, "death": death, "note": note,
                 "floor": floor, "boon": boon}.items():
    register_sfx(f"cinder_{name}", fn)
