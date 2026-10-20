"""Synthesised effects for Terrace (prefix ``terrace_``): digging, building, creatures and the Keystone."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _d(x, tau):
    return x * S.decay(len(x), tau)


def _thud(freq: float, dur: float, noise_hi: float, seed: int, vol: float = 0.7):
    return S.normalize(S.fade_edges(_d(S.sweep(freq, freq * 0.45, dur), dur * 0.4) * 0.8
                                    + _d(S.lowpass(S.noise(dur, seed), noise_hi), dur * 0.3) * 0.7), vol)


def mine_stone():
    return _thud(190, 0.09, 2600, 1, 0.55)


def mine_dirt():
    return _thud(120, 0.1, 900, 2, 0.5)


def mine_wood():
    d = 0.1
    return S.normalize(S.fade_edges(_d(S.sine(S.note("g4"), d), 0.03) * 0.6 + _d(S.bandpass(S.noise(d, 3), 400, 1800), 0.04)), 0.5)


def mine_plant():
    return S.normalize(S.fade_edges(_d(S.bandpass(S.noise(0.12, 4), 2000, 6000), 0.04)), 0.4)


def mine_glass():
    d = 0.2
    return S.normalize(S.fade_edges(S.mixdown(_d(S.sine(S.note("e6"), d), 0.07) * 0.5, _d(S.sine(S.note("a6"), d), 0.05) * 0.4,
                                              _d(S.highpass(S.noise(0.05, 5), 4000), 0.015))), 0.5)


def break_stone():
    return _thud(150, 0.2, 3000, 6, 0.8)


def place():
    return _thud(260, 0.07, 1500, 7, 0.55)


def land():
    return _thud(90, 0.12, 700, 8, 0.45)


def thud():
    return _thud(60, 0.3, 500, 9, 0.9)


def jump():
    return S.normalize(S.fade_edges(_d(S.sweep(180, 340, 0.09), 0.05)), 0.35)


def hurt():
    d = 0.22
    return S.normalize(S.fade_edges(_d(S.sweep(330, 110, d, "saw"), 0.09) * 0.7 + _d(S.noise(d, 10), 0.05) * 0.3), 0.7)


def splash():
    d = 0.3
    return S.normalize(S.fade_edges(_d(S.lowpass(S.noise(d, 11), 2400), 0.1)), 0.55)


def craft():
    buf = np.zeros(S.n_samples(0.4), dtype=np.float32)
    for i, n in enumerate(("c5", "e5", "g5")):
        S.place(buf, _d(S.tri(S.note(n), 0.2), 0.06), i * 0.06, 0.6)
    S.place(buf, _d(S.highpass(S.noise(0.04, 12), 3000), 0.01), 0.0, 0.5)
    return S.normalize(S.fade_edges(buf), 0.55)


def door():
    return _thud(140, 0.14, 1200, 13, 0.55)


def slash():
    d = 0.12
    n = S.bandpass(S.noise(d, 14), 1200, 5200)
    return S.normalize(S.fade_edges(n * np.sin(np.linspace(0, np.pi, len(n))) ** 1.3), 0.5)


def eat():
    d = 0.3
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i in range(3):
        S.place(buf, _d(S.bandpass(S.noise(0.05, 15 + i), 600, 2400), 0.02), i * 0.09, 0.8)
    return S.normalize(S.fade_edges(buf), 0.5)


def hiss():
    d = 0.5
    return S.normalize(S.fade_edges(_d(S.highpass(S.noise(d, 16), 3000), 0.18)), 0.45)


def shrine():
    d = 1.0
    return S.normalize(S.fade_edges(S.reverb(_d(S.sine(S.note("d5"), d), 0.5) * 0.6 + _d(S.sine(S.note("a5"), d), 0.35) * 0.4, 0.8, 0.35)), 0.6)


def vigil():
    d = 1.6
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("d4", "a4", "d5", "f#5")):
        S.place(buf, _d(S.sine(S.note(n), 1.0), 0.5), i * 0.18, 0.55)
    return S.normalize(S.fade_edges(S.reverb(buf, 1.0, 0.4)), 0.8)


def dawn():
    d = 1.4
    buf = np.zeros(S.n_samples(d), dtype=np.float32)
    for i, n in enumerate(("g4", "b4", "d5", "g5")):
        S.place(buf, _d(S.tri(S.note(n), 0.7), 0.3), i * 0.2, 0.6)
    return S.normalize(S.fade_edges(S.reverb(buf, 0.9, 0.35)), 0.7)


def call_hopper():
    return S.normalize(S.fade_edges(_d(S.sweep(900, 1500, 0.08), 0.04)), 0.3)


def call_woolback():
    d = 0.4
    return S.normalize(S.fade_edges(S.tremolo(S.sweep(300, 240, d, "saw"), 24, 0.6) * S.decay(S.n_samples(d), 0.2)), 0.4)


def call_wolf():
    d = 0.9
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(300, 640, d * 0.6, "sine"), 0.35), 0.5, 0.2)), 0.5)


def call_bumblet():
    d = 0.25
    return S.normalize(S.fade_edges(S.tremolo(S.sine(210, d), 90, 0.8) * S.decay(S.n_samples(d), 0.15)), 0.2)


def call_crawler():
    d = 0.3
    return S.normalize(S.fade_edges(_d(S.bandpass(S.noise(d, 17), 700, 2200), 0.1) * S.tremolo(S.noise(d, 18), 40, 1.0)), 0.35)


def call_gleaner():
    return S.normalize(S.fade_edges(_d(S.sweep(2200, 1400, 0.15), 0.07)), 0.3)


def call_gloam():
    d = 0.8
    return S.normalize(S.fade_edges(S.reverb(_d(S.sweep(120, 70, d, "saw"), 0.35) * 0.6 + _d(S.sine(95, d), 0.4) * 0.4, 0.9, 0.4)), 0.55)


for _n, _f in {"mine_stone": mine_stone, "mine_dirt": mine_dirt, "mine_wood": mine_wood, "mine_plant": mine_plant,
               "mine_glass": mine_glass, "break": break_stone, "place": place, "land": land, "thud": thud, "jump": jump,
               "hurt": hurt, "splash": splash, "craft": craft, "door": door, "slash": slash, "eat": eat, "hiss": hiss,
               "shrine": shrine, "vigil": vigil, "dawn": dawn, "hopper": call_hopper, "woolback": call_woolback,
               "wolf": call_wolf, "bumblet": call_bumblet, "crawler": call_crawler, "gleaner": call_gleaner,
               "gloam": call_gloam}.items():
    register_sfx(f"terrace_{_n}", _f)
