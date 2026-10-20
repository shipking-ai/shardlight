"""Synthesised effects for Verdant (prefix ``verdant_``): steel, bows, coins, lamps and bells."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _d(x, tau):
    return x * S.decay(len(x), tau)


def _norm(x, peak=0.6):
    return S.normalize(S.fade_edges(x), peak)


def swing():
    d = 0.16
    return _norm(_d(S.bandpass(S.noise(d, 3), 700, 3200), 0.06) * np.linspace(0.3, 1.0, S.n_samples(d)) ** 0.7, 0.35)


def hit():
    d = 0.14
    return _norm(_d(S.sweep(210, 90, d), 0.05) * 0.8 + _d(S.lowpass(S.noise(d, 5), 2600), 0.04) * 0.7, 0.6)


def kill():
    d = 0.35
    return _norm(_d(S.sweep(180, 60, d), 0.12) * 0.7 + _d(S.noise(d, 7) * 0.4, 0.08), 0.6)


def block():
    d = 0.2
    return _norm(_d(S.sine(S.note("a5"), d), 0.05) * 0.5 + _d(S.sine(S.note("e6"), d), 0.04) * 0.4 + _d(S.highpass(S.noise(d, 9), 3000), 0.02) * 0.5, 0.5)


def hurt():
    d = 0.22
    return _norm(_d(S.sweep(260, 110, d, "saw"), 0.08) * 0.6 + _d(S.lowpass(S.noise(d, 11), 1400), 0.07) * 0.5, 0.6)


def roll():
    d = 0.22
    return _norm(_d(S.lowpass(S.noise(d, 13), 900), 0.1) * np.linspace(0.2, 1.0, S.n_samples(d)), 0.3)


def bow():
    d = 0.18
    return _norm(_d(S.sweep(420, 160, d, "tri"), 0.05) * 0.6 + _d(S.bandpass(S.noise(d, 15), 1500, 4500), 0.03) * 0.5, 0.45)


def pickup():
    return _norm(_d(S.sine(S.note("e6"), 0.12), 0.05) * 0.6, 0.35)


def coin():
    d = 0.3
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.sine(S.note("b5"), 0.12), 0.04), 0.0, 0.6)
    S.place(buf, _d(S.sine(S.note("e6"), 0.2), 0.08), 0.06, 0.6)
    return _norm(buf, 0.45)


def heal():
    d = 0.5
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("c5", "e5", "g5")):
        S.place(buf, _d(S.tri(S.note(n), 0.3), 0.12), i * 0.07, 0.5)
    return _norm(S.reverb(buf, 0.4, 0.2), 0.45)


def equip():
    d = 0.14
    return _norm(_d(S.sweep(300, 500, d, "square"), 0.05) * 0.4 + _d(S.noise(d, 17), 0.03) * 0.4, 0.35)


def craft():
    d = 0.3
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.sine(S.note("c4"), 0.1), 0.04), 0.0, 0.6)
    S.place(buf, S.mixdown(_d(S.sine(S.note("c5"), 0.15), 0.06), _d(S.highpass(S.noise(0.1, 19), 2500), 0.03) * 0.5), 0.12, 0.6)
    return _norm(buf, 0.45)


def door():
    d = 0.3
    return _norm(_d(S.sweep(160, 90, d, "saw"), 0.1) * 0.5 + _d(S.lowpass(S.noise(d, 21), 700), 0.1) * 0.6, 0.4)


def lamp():
    d = 0.7
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.bandpass(S.noise(0.25, 23), 900, 5000), 0.07), 0.0, 0.5)
    for i, n in enumerate(("g5", "d6")):
        S.place(buf, _d(S.sine(S.note(n), 0.5), 0.25), 0.1 + i * 0.07, 0.4)
    return _norm(S.reverb(buf, 0.5, 0.25), 0.5)


def greatlamp():
    d = 2.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("g3", "d4", "g4", "b4", "d5", "g5")):
        S.place(buf, S.mixdown(_d(S.sine(S.note(n), 1.6), 0.7), 0.3 * _d(S.tri(S.note(n), 1.2), 0.5)), i * 0.22, 0.5)
    return _norm(S.reverb(buf, 1.4, 0.45), 0.75)


def quest():
    d = 0.9
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("g4", "b4", "d5", "g5")):
        S.place(buf, _d(S.tri(S.note(n), 0.45), 0.2), i * 0.11, 0.55)
    return _norm(S.reverb(buf, 0.7, 0.3), 0.6)


def levelup():
    d = 0.7
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("d5", "f#5", "a5", "d6")):
        S.place(buf, _d(S.square(S.note(n), 0.2, 0.3), 0.08), i * 0.08, 0.3)
    return _norm(buf, 0.4)


def drink():
    d = 0.35
    return _norm(_d(S.bandpass(S.noise(d, 25), 300, 1400), 0.12) * S.tremolo(S.noise(d, 26), 18, 0.8), 0.3)


def shrine():
    d = 1.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("d4", "a4", "d5")):
        S.place(buf, _d(S.sine(S.note(n), 1.0), 0.5), i * 0.15, 0.55)
    return _norm(S.reverb(buf, 1.0, 0.4), 0.6)


def chest():
    d = 0.5
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.lowpass(S.noise(0.15, 27), 1000), 0.06), 0.0, 0.6)
    for i, n in enumerate(("e5", "g5", "c6")):
        S.place(buf, _d(S.sine(S.note(n), 0.25), 0.1), 0.1 + i * 0.07, 0.45)
    return _norm(buf, 0.5)


def knock():
    d = 0.14
    return _norm(_d(S.sweep(140, 80, d), 0.04) * 0.9 + _d(S.lowpass(S.noise(d, 29), 600), 0.03), 0.5)


def secret():
    d = 1.0
    return _norm(S.reverb(_d(S.sweep(70, 45, d, "saw"), 0.4) * 0.6 + _d(S.lowpass(S.noise(d, 31), 500), 0.35) * 0.5, 0.5, 0.25), 0.6)


def gather():
    d = 0.2
    return _norm(_d(S.bandpass(S.noise(d, 33), 1500, 5500), 0.05) * 0.8 + _d(S.sine(S.note("a5"), d), 0.05) * 0.2, 0.35)


def slam():
    d = 0.4
    return _norm(_d(S.sweep(110, 38, d), 0.14) * 0.9 + _d(S.lowpass(S.noise(d, 35), 800), 0.1) * 0.6, 0.75)


def bell():
    d = 1.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for k, (f, g) in enumerate(((220, 0.8), (373, 0.5), (547, 0.35), (834, 0.2))):
        buf += g * _d(S.sine(f, d), 0.55 / (1 + k * 0.4))
    return _norm(S.reverb(buf, 0.8, 0.3), 0.65)


def boss_down():
    d = 1.6
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    S.place(buf, _d(S.sweep(160, 40, 0.8), 0.35), 0.0, 0.7)
    for i, n in enumerate(("d4", "f4", "a4", "d5")):
        S.place(buf, _d(S.tri(S.note(n), 0.9), 0.4), 0.5 + i * 0.16, 0.5)
    return _norm(S.reverb(buf, 1.0, 0.4), 0.75)


def death():
    d = 1.3
    return _norm(S.reverb(_d(S.sweep(330, 70, d, "saw"), 0.5) * 0.5 + _d(S.sine(110, d), 0.6) * 0.5, 0.8, 0.35), 0.6)


for _n, _f in {"swing": swing, "hit": hit, "kill": kill, "block": block, "hurt": hurt, "roll": roll, "bow": bow, "pickup": pickup,
               "coin": coin, "heal": heal, "equip": equip, "craft": craft, "door": door, "lamp": lamp, "greatlamp": greatlamp,
               "quest": quest, "levelup": levelup, "drink": drink, "shrine": shrine, "chest": chest, "knock": knock,
               "secret": secret, "gather": gather, "slam": slam, "bell": bell, "boss_down": boss_down, "death": death}.items():
    register_sfx(f"verdant_{_n}", _f)
