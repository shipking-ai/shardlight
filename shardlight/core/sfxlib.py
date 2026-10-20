"""Shared sound effects (UI and common game events), synthesised from ``core.synth``.

Names: ui_move ui_confirm ui_back ui_error ui_open pickup coin heal power_up unlock error click bell
lap_checkpoint countdown_beep victory_sting defeat_sting thud whoosh.
"""
from __future__ import annotations

import numpy as np

from . import synth as S
from .audio import register_sfx


def _env(x, tau):
    return x * S.decay(len(x), tau)


def _arp(notes, step=0.07, dur=0.35, wave=S.tri, gain=0.55):
    total = step * len(notes) + dur
    buf = np.zeros(S.n_samples(total), dtype=np.float32)
    for i, n in enumerate(notes):
        tone = wave(S.note(n), dur) * S.adsr(S.n_samples(dur), 0.004, 0.06, 0.4, dur * 0.5)
        S.place(buf, tone, i * step, gain)
    return S.normalize(S.fade_edges(buf), 0.7)


def ui_move():
    d = 0.05
    return S.normalize(S.fade_edges(_env(S.sine(880, d), 0.015)), 0.35)


def ui_confirm():
    return _arp(["e5", "b5"], 0.05, 0.16, S.tri, 0.6)


def ui_back():
    return _arp(["b4", "e4"], 0.05, 0.14, S.tri, 0.55)


def ui_error():
    d = 0.18
    return S.normalize(S.fade_edges(S.square(150, d) * S.decay(S.n_samples(d), 0.08) * 0.6), 0.5)


def ui_open():
    return _arp(["c5", "g5", "c6"], 0.04, 0.2, S.sine, 0.5)


def pickup():
    return _arp(["g5", "c6"], 0.04, 0.12, S.sine, 0.6)


def coin():
    return _arp(["b5", "e6"], 0.05, 0.18, S.square, 0.25)


def heal():
    return _arp(["c5", "e5", "g5", "c6"], 0.05, 0.22, S.sine, 0.5)


def power_up():
    return _arp(["c4", "e4", "g4", "c5", "e5"], 0.05, 0.25, S.saw, 0.25)


def unlock():
    return S.normalize(S.fade_edges(S.reverb(_arp(["e5", "g#5", "b5", "e6"], 0.09, 0.45, S.tri, 0.5), 0.6, 0.3)), 0.75)


def click():
    d = 0.02
    return S.normalize(_env(S.highpass(S.noise(d, 3), 2000), 0.004), 0.5)


def bell():
    d = 1.0
    out = sum(_env(S.sine(f, d), t) * g for f, g, t in ((660, 1.0, 0.3), (1320, 0.4, 0.2), (1770, 0.25, 0.15)))
    return S.normalize(S.fade_edges(S.reverb(out, 0.6, 0.25)), 0.7)


def lap_checkpoint():
    return _arp(["a5", "e6"], 0.04, 0.12, S.sine, 0.5)


def countdown_beep():
    d = 0.18
    return S.normalize(S.fade_edges(S.sine(880, d) * S.adsr(S.n_samples(d), 0.005, 0.03, 0.8, 0.06)), 0.6)


def victory_sting():
    return S.normalize(S.fade_edges(S.reverb(_arp(["c5", "e5", "g5", "c6", "e6", "g6"], 0.08, 0.5, S.tri, 0.5), 0.8, 0.3)), 0.85)


def defeat_sting():
    return S.normalize(S.fade_edges(S.reverb(_arp(["e4", "c4", "a3", "e3"], 0.14, 0.6, S.saw, 0.25), 0.8, 0.3)), 0.8)


def thud():
    d = 0.18
    return S.normalize(S.fade_edges(_env(S.sweep(120, 45, d), 0.06) + _env(S.lowpass(S.noise(d, 5), 400), 0.03) * 0.6), 0.8)


def whoosh():
    d = 0.25
    return S.normalize(S.fade_edges(S.bandpass(S.noise(d, 7), 300, 3000) * np.sin(np.linspace(0, np.pi, S.n_samples(d)))), 0.5)


for _name, _fn in list(globals().items()):
    if callable(_fn) and _name in ("ui_move", "ui_confirm", "ui_back", "ui_error", "ui_open", "pickup", "coin", "heal",
                                   "power_up", "unlock", "click", "bell", "lap_checkpoint", "countdown_beep",
                                   "victory_sting", "defeat_sting", "thud", "whoosh"):
        register_sfx(_name, _fn)
