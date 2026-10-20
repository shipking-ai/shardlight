"""Original sound recipes for Concord (all names prefixed ``concord_``), synthesised with core.synth."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _quill() -> np.ndarray:
    """Three scratchy pen strokes."""
    out = np.zeros(S.n_samples(0.5), dtype=np.float32)
    for i, (at, dur) in enumerate(((0.0, 0.14), (0.16, 0.10), (0.30, 0.16))):
        n = S.noise(dur, seed=10 + i)
        n = S.bandpass(n, 1800, 5200)
        env = S.adsr(len(n), 0.01, 0.04, 0.5, dur * 0.5)
        mod = 0.6 + 0.4 * np.sin(np.linspace(0, 9 + 4 * i, len(n)))
        S.place(out, n * env * mod, at, 0.8)
    return S.normalize(S.fade_edges(out), 0.5)


def _seal() -> np.ndarray:
    """Wet wax thud: low drop, a squeak of release."""
    thud = S.sweep(150, 55, 0.22, "sine", 0.6) * S.decay(S.n_samples(0.22), 0.07)
    wax = S.lowpass(S.noise(0.12, seed=3), 700) * S.decay(S.n_samples(0.12), 0.03)
    squeak = S.sweep(900, 1500, 0.07, "sine") * S.decay(S.n_samples(0.07), 0.025) * 0.25
    out = np.zeros(S.n_samples(0.42), dtype=np.float32)
    S.place(out, thud, 0.0, 1.0)
    S.place(out, wax, 0.0, 0.8)
    S.place(out, squeak, 0.17, 1.0)
    return S.normalize(S.fade_edges(out), 0.8)


def _march() -> np.ndarray:
    """Four soft footfalls with a drum tick on the beat."""
    out = np.zeros(S.n_samples(0.86), dtype=np.float32)
    for i in range(4):
        at = i * 0.2
        step = S.lowpass(S.noise(0.12, seed=20 + i), 380) * S.decay(S.n_samples(0.12), 0.04)
        S.place(out, step, at, 1.0 if i % 2 == 0 else 0.7)
    tick = S.sweep(220, 120, 0.09, "tri") * S.decay(S.n_samples(0.09), 0.03)
    S.place(out, tick, 0.0, 0.6)
    S.place(out, tick, 0.4, 0.6)
    return S.normalize(S.fade_edges(out), 0.55)


def _clash() -> np.ndarray:
    """Steel on steel: noise crack over inharmonic ringing partials."""
    n = S.n_samples(0.55)
    crack = S.highpass(S.noise(0.55, seed=5), 1500) * S.decay(n, 0.025)
    ring = np.zeros(n, dtype=np.float32)
    for f, g, tau in ((1180, 1.0, 0.16), (1710, 0.7, 0.12), (2330, 0.5, 0.09), (3170, 0.3, 0.06)):
        ring += S.sine(f, 0.55) * S.decay(n, tau) * g
    thump = S.sweep(180, 70, 0.1, "sine") * S.decay(S.n_samples(0.1), 0.03)
    out = crack * 0.8 + ring * 0.35
    S.place(out, thump, 0.0, 0.7)
    return S.normalize(S.fade_edges(out), 0.7)


def _bell() -> np.ndarray:
    """Tower bell: strike tone plus inharmonic partials, lightly reverberated."""
    dur = 1.6
    n = S.n_samples(dur)
    out = np.zeros(n, dtype=np.float32)
    for ratio, g, tau in ((1.0, 1.0, 0.6), (2.0, 0.6, 0.45), (2.76, 0.5, 0.3), (5.4, 0.25, 0.18), (8.9, 0.12, 0.1)):
        out += S.sine(196 * ratio, dur) * S.decay(n, tau) * g
    out *= S.adsr(n, 0.002, 0.02, 1.0, 0.05)
    return S.normalize(S.reverb(out, 0.7, 0.2, seed=4), 0.65)


def _horn() -> np.ndarray:
    """Low war-horn note that swells and fades."""
    dur = 0.9
    n = S.n_samples(dur)
    f = np.linspace(116, 124, n)
    tone = S.saw(f, dur) * 0.5 + S.square(f * 2.0, dur, 0.4) * 0.15
    tone = S.lowpass(tone, 900)
    out = tone * S.adsr(n, 0.18, 0.1, 0.8, 0.4)
    return S.normalize(S.fade_edges(out), 0.6)


def _coin() -> np.ndarray:
    out = np.zeros(S.n_samples(0.35), dtype=np.float32)
    for at, f in ((0.0, 1760.0), (0.07, 2349.0)):
        t = S.sine(f, 0.25) * S.decay(S.n_samples(0.25), 0.06)
        S.place(out, t, at, 0.7)
    return S.normalize(S.fade_edges(out), 0.5)


def _page() -> np.ndarray:
    """Paper turning: short filtered noise sweep."""
    n = S.bandpass(S.noise(0.2, seed=44), 900, 3500)
    return S.normalize(S.fade_edges(n * S.adsr(len(n), 0.03, 0.05, 0.4, 0.1)), 0.35)


for _name, _fn in (("concord_quill", _quill), ("concord_seal", _seal), ("concord_march", _march),
                   ("concord_clash", _clash), ("concord_bell", _bell), ("concord_horn", _horn),
                   ("concord_coin", _coin), ("concord_page", _page)):
    register_sfx(_name, _fn)
