"""Synthesised effects for Umbra (prefix ``umbra_``): quiet, close, dry sounds - the silence is the instrument."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _d(x, tau):
    return x * S.decay(len(x), tau)


def _step(freq, noise_lo, noise_hi, dur, seed, vol=0.5, ring=0.0):
    n = _d(S.bandpass(S.noise(dur, seed), noise_lo, noise_hi), dur * 0.35)
    t = _d(S.sweep(freq, freq * 0.5, dur), dur * 0.25) * 0.6
    out = n * 0.8 + t
    if ring:
        out = out + _d(S.sine(ring, dur), dur * 0.5) * 0.15
    return S.normalize(S.fade_edges(out), vol)


def step_wood():
    return _step(150, 300, 1500, 0.09, 1, 0.5)


def step_tile():
    return _step(220, 1200, 4500, 0.07, 2, 0.5, 1800)


def step_stone():
    return _step(170, 400, 2400, 0.08, 3, 0.5)


def step_carpet():
    return S.normalize(S.fade_edges(_d(S.lowpass(S.noise(0.09, 4), 500), 0.04)), 0.3)


def step_gravel():
    d = 0.14
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i in range(5):
        S.place(buf, _d(S.highpass(S.noise(0.025, 5 + i), 1500), 0.006), i * 0.02, 0.7)
    return S.normalize(S.fade_edges(buf), 0.5)


def step_glass():
    d = 0.12
    return S.normalize(S.fade_edges(_d(S.highpass(S.noise(d, 6), 3500), 0.03) + _d(S.sine(2600, d), 0.04) * 0.2), 0.55)


def step_water():
    return S.normalize(S.fade_edges(_d(S.bandpass(S.noise(0.14, 7), 300, 1800), 0.06)), 0.4)


def door():
    d = 0.5
    return S.normalize(S.fade_edges(_d(S.sweep(130, 90, d, "saw"), 0.25) * 0.4 + _d(S.bandpass(S.noise(d, 8), 200, 1200), 0.15) * 0.6), 0.55)


def bang():
    d = 0.3
    return S.normalize(S.fade_edges(_d(S.sweep(110, 50, d), 0.1) + _d(S.lowpass(S.noise(d, 9), 600), 0.06)), 0.9)


def breaks():
    d = 0.7
    return S.normalize(S.fade_edges(_d(S.sweep(120, 40, d), 0.2) + _d(S.bandpass(S.noise(d, 10), 150, 3000), 0.18)), 0.95)


def unlock():
    buf = np.zeros(S.n_samples(0.35), dtype=np.float32)
    S.place(buf, _d(S.sine(1800, 0.05), 0.012), 0.0, 0.6)
    S.place(buf, _d(S.sine(1300, 0.08), 0.02), 0.09, 0.6)
    S.place(buf, _d(S.sine(900, 0.1), 0.03), 0.2, 0.5)
    return S.normalize(S.fade_edges(buf), 0.5)


def click():
    return S.normalize(S.fade_edges(S.mixdown(_d(S.sine(2400, 0.03), 0.006), _d(S.highpass(S.noise(0.02, 11), 3000), 0.004))), 0.45)


def match():
    d = 0.4
    return S.normalize(S.fade_edges(_d(S.highpass(S.noise(d, 12), 2500), 0.12) * np.linspace(0.2, 1, S.n_samples(d)) ** 0.5), 0.45)


def pickup():
    return S.normalize(S.fade_edges(_d(S.sine(S.note("a5"), 0.12), 0.04) * 0.5 + _d(S.sine(S.note("e6"), 0.12), 0.03) * 0.3), 0.3)


def drawer():
    d = 0.25
    return S.normalize(S.fade_edges(_d(S.bandpass(S.noise(d, 13), 200, 900), 0.1) + _d(S.sweep(90, 70, d), 0.1) * 0.4), 0.5)


def breath():
    d = 0.7
    n = S.bandpass(S.noise(d, 14), 300, 1800)
    return S.normalize(S.fade_edges(n * np.sin(np.linspace(0, np.pi, len(n))) ** 2), 0.25)


def gasp():
    d = 0.45
    n = S.bandpass(S.noise(d, 15), 400, 2600)
    return S.normalize(S.fade_edges(n * np.linspace(0.2, 1, len(n)) * S.decay(len(n), 0.3)), 0.4)


def fuse():
    d = 0.4
    return S.normalize(S.fade_edges(_d(S.sweep(600, 300, d, "square"), 0.1) * 0.3 + _d(S.highpass(S.noise(d, 16), 2500), 0.05)), 0.5)


def generator():
    d = 2.2
    n = S.n_samples(d)
    base = S.sweep(40, 62, d, "saw")
    return S.normalize(S.fade_edges(S.lowpass(base, 400) * np.linspace(0.3, 1, n) + S.lowpass(S.noise(d, 17), 300) * 0.4), 0.85)


def lever():
    d = 0.5
    return S.normalize(S.fade_edges(S.mixdown(_d(S.sweep(200, 90, d), 0.15), _d(S.highpass(S.noise(0.05, 18), 2000), 0.01), S.reverb(_d(S.sine(S.note("g3"), d), 0.3), 0.4, 0.2) * 0.5)), 0.7)


def crank():
    d = 1.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i in range(10):
        S.place(buf, S.mixdown(_d(S.sweep(180, 110, 0.06), 0.02), _d(S.highpass(S.noise(0.03, 19 + i), 1800), 0.006)), i * 0.13, 0.7)
    return S.normalize(S.fade_edges(buf), 0.7)


def ward():
    d = 1.0
    return S.normalize(S.fade_edges(S.reverb(S.tremolo(S.sine(S.note("a4"), d), 6, 0.3) * S.adsr(S.n_samples(d), 0.1, 0.1, 0.7, 0.4) * 0.5 + S.sine(S.note("e5"), d) * 0.2, 0.7, 0.3)), 0.45)


def hit():
    d = 0.25
    return S.normalize(S.fade_edges(_d(S.sweep(180, 50, d), 0.08) + _d(S.lowpass(S.noise(d, 20), 800), 0.06)), 0.85)


def clatter():
    d = 0.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, at in enumerate((0.0, 0.07, 0.13, 0.2, 0.27)):
        S.place(buf, S.mixdown(_d(S.sine(1500 - i * 150, 0.06), 0.02) * 0.6, _d(S.highpass(S.noise(0.03, 21 + i), 2500), 0.008)), at, 0.8 - i * 0.12)
    return S.normalize(S.fade_edges(buf), 0.7)


def cloth():
    return S.normalize(S.fade_edges(_d(S.bandpass(S.noise(0.3, 22), 800, 3000), 0.1)), 0.3)


def heart():
    buf = np.zeros(S.n_samples(0.5), dtype=np.float32)
    S.place(buf, _d(S.sweep(70, 40, 0.18), 0.06), 0.0, 1.0)
    S.place(buf, _d(S.sweep(60, 35, 0.2), 0.07), 0.2, 0.7)
    return S.normalize(S.fade_edges(buf), 0.9)


def note():
    return S.normalize(S.fade_edges(S.mixdown(_d(S.bandpass(S.noise(0.25, 23), 1500, 5000), 0.09) * 0.6, _d(S.sine(S.note("d5"), 0.3), 0.12) * 0.2)), 0.35)


def death():
    d = 1.6
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(200, 35, d, "saw"), 0.6) * 0.5 + _d(S.noise(d, 24), 0.25) * 0.15, 1.0, 0.35)), 0.8)


def safe():
    d = 1.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("d4", "a4", "d5")):
        S.place(buf, _d(S.tri(S.note(n), 0.8), 0.4), i * 0.15, 0.5)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.9, 0.35)), 0.5)


def locked():
    return S.normalize(S.fade_edges(S.mixdown(_d(S.sweep(160, 110, 0.12), 0.04), _d(S.highpass(S.noise(0.05, 25), 2000), 0.008))), 0.5)


def clock():
    d = 1.2
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.sine(S.note("c4"), 0.9), 0.5) + _d(S.sine(S.note("g5"), 0.9), 0.3) * 0.4, 0.0, 0.7)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.9, 0.4)), 0.7)


def throw():
    d = 0.2
    n = S.bandpass(S.noise(d, 26), 800, 4000)
    return S.normalize(S.fade_edges(n * np.sin(np.linspace(0, np.pi, len(n)))), 0.3)


def glass():
    d = 0.6
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.highpass(S.noise(0.25, 27), 2500), 0.08), 0.0, 1.0)
    for i, f in enumerate((2400, 3100, 3900, 2900)):
        S.place(buf, _d(S.sine(f, 0.2), 0.05), 0.02 + i * 0.05, 0.3)
    return S.normalize(S.fade_edges(buf), 0.8)


def mimic():
    d = 0.5
    return S.normalize(S.fade_edges(S.reverb(S.tremolo(S.sweep(220, 205, d, "saw"), 14, 0.6) * S.decay(S.n_samples(d), 0.25) * 0.4
                                             + _d(S.bandpass(S.noise(d, 28), 400, 1200), 0.1) * 0.3, 0.7, 0.3)), 0.4)


for _n, _f in {"step_wood": step_wood, "step_tile": step_tile, "step_stone": step_stone, "step_carpet": step_carpet, "step_gravel": step_gravel,
               "step_glass": step_glass, "step_water": step_water, "door": door, "bang": bang, "break": breaks, "unlock": unlock, "click": click,
               "match": match, "pickup": pickup, "drawer": drawer, "breath": breath, "gasp": gasp, "fuse": fuse, "generator": generator,
               "lever": lever, "crank": crank, "ward": ward, "hit": hit, "clatter": clatter, "cloth": cloth, "heart": heart, "note": note,
               "death": death, "safe": safe, "locked": locked, "clock": clock, "throw": throw, "glass": glass, "mimic": mimic}.items():
    register_sfx(f"umbra_{_n}", _f)
