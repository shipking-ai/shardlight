"""Synthesised sound effects for Slipstream (prefix ``slipstream_``)."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def put() -> np.ndarray:
    d = 0.05
    t = S.tri(70, d) * S.decay(S.n_samples(d), 0.012)
    n = S.lowpass(S.noise(d, 3), 500) * S.decay(S.n_samples(d), 0.01) * 0.5
    return S.normalize(S.fade_edges(t + n), 0.7)


def skid() -> np.ndarray:
    d = 0.16
    n = S.bandpass(S.noise(d, 5), 1400, 3600)
    return S.normalize(S.fade_edges(n * np.sin(np.linspace(0, np.pi, len(n))) ** 0.5), 0.5)


def boost() -> np.ndarray:
    d = 0.3
    up = S.sweep(180, 620, d, "saw", 1.0) * np.linspace(0.3, 1, S.n_samples(d))
    n = S.highpass(S.noise(d, 8), 1200) * 0.4
    return S.normalize(S.fade_edges(S.lowpass(up, 3000) * 0.7 + n), 0.65)


def bump() -> np.ndarray:
    d = 0.2
    thud = S.sweep(140, 50, d, "sine", 0.6) * S.decay(S.n_samples(d), 0.05)
    crunch = S.bandpass(S.noise(d, 2), 400, 3000) * S.decay(S.n_samples(d), 0.035) * 0.8
    return S.normalize(S.fade_edges(thud + crunch), 0.85)


def rewind() -> np.ndarray:
    d = 0.7
    sw = S.sweep(1400, 160, d, "saw", 0.7) * np.linspace(1, 0.2, S.n_samples(d))
    trem = S.tremolo(sw, 22, 0.6)
    return S.normalize(S.fade_edges(S.reverb(S.lowpass(trem, 2600), 0.4, 0.2)), 0.7)


register_sfx("slipstream_put", put)
register_sfx("slipstream_skid", skid)
register_sfx("slipstream_boost", boost)
register_sfx("slipstream_bump", bump)
register_sfx("slipstream_rewind", rewind)
