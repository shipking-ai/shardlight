"""Original synthesised sound effects for Masks (prefix ``masks_``)."""
from __future__ import annotations

import numpy as np

from ...core import synth as S
from ...core.audio import register_sfx


def _env(x: np.ndarray, tau: float) -> np.ndarray:
    return x * S.decay(len(x), tau)


def hit(weight: float = 1.0, seed: int = 1) -> np.ndarray:
    dur = 0.14 + 0.08 * weight
    n = S.noise(dur, seed)
    crack = _env(S.highpass(S.lowpass(n, 5200), 900), 0.02 * weight)
    thump = _env(S.sweep(180 / weight ** 0.5, 52, dur, "sine", 0.6), 0.05 * weight) * 1.2
    body = _env(S.lowpass(n, 700 / weight), 0.04) * 0.5
    return S.normalize(S.fade_edges(S.mixdown(crack, thump, body)), 0.9)


def block(seed: int = 2) -> np.ndarray:
    dur = 0.22
    tick = _env(S.highpass(S.noise(0.05, seed), 2500), 0.01)
    ring = sum(_env(S.sine(f, dur), 0.07) * g for f, g in ((880, 0.5), (1320, 0.3), (2110, 0.18)))
    return S.normalize(S.fade_edges(S.mixdown(tick, ring)), 0.8)


def parry() -> np.ndarray:
    dur = 0.55
    ring = sum(_env(S.sine(f, dur), 0.18) * g for f, g in ((1760, 0.6), (2637, 0.35), (3520, 0.2), (1320, 0.3)))
    click = _env(S.highpass(S.noise(0.04, 5), 3000), 0.008)
    return S.normalize(S.fade_edges(S.mixdown(ring, click * 1.2)), 0.85)


def swing(weight: float = 1.0, seed: int = 3) -> np.ndarray:
    dur = 0.12 + 0.08 * weight
    n = S.noise(dur, seed)
    t = np.linspace(0, 1, len(n))
    band = S.bandpass(n, 700 / weight, 4200 / weight)
    env = np.sin(np.pi * t) ** 1.5
    return S.normalize(S.fade_edges(band * env), 0.55)


def superflash() -> np.ndarray:
    dur = 0.9
    up = S.sweep(220, 1760, dur, "saw", 2.0) * np.linspace(0.2, 1, S.n_samples(dur)) ** 1.5
    shimmer = S.tremolo(S.sine(1320, dur), 18, 0.7) * 0.4
    boom = _env(S.sweep(110, 40, dur, "sine", 0.5), 0.4) * 0.8
    out = S.mixdown(S.lowpass(up, 4200) * 0.5, shimmer, boom)
    return S.normalize(S.fade_edges(S.reverb(out, 0.5, 0.2)), 0.85)


def throw() -> np.ndarray:
    a = swing(1.4, 7)
    b = _env(S.sweep(120, 45, 0.18, "sine", 0.5), 0.07)
    out = np.concatenate([a * 0.7, b])
    return S.normalize(S.fade_edges(out), 0.8)


def thud() -> np.ndarray:
    d = 0.18
    return S.normalize(S.fade_edges(_env(S.sweep(110, 42, d), 0.06) + _env(S.lowpass(S.noise(d, 9), 400), 0.03) * 0.6), 0.8)


def ko() -> np.ndarray:
    dur = 1.1
    boom = _env(S.sweep(90, 28, dur, "sine", 0.4), 0.35)
    crack = _env(S.highpass(S.noise(0.25, 11), 800), 0.05)
    bell = _env(S.sine(392, dur), 0.4) * 0.3
    return S.normalize(S.fade_edges(S.reverb(S.mixdown(boom, crack, bell), 0.7, 0.25)), 0.9)


def gong() -> np.ndarray:
    dur = 1.5
    parts = [(110, 1.0, 0.7), (165.4, 0.6, 0.6), (231, 0.5, 0.5), (284, 0.3, 0.4), (396, 0.25, 0.3)]
    out = sum(_env(S.sine(f, dur), tau) * g for f, g, tau in parts)
    out = out * (1 - np.exp(-np.arange(len(out)) / (0.01 * S.SR)))
    return S.normalize(S.fade_edges(S.reverb(out, 0.8, 0.2)), 0.8)


register_sfx("masks_hit", lambda: hit(1.0, 1))
register_sfx("masks_hit_heavy", lambda: hit(1.8, 2))
register_sfx("masks_block", block)
register_sfx("masks_parry", parry)
register_sfx("masks_swing", lambda: swing(1.0, 3))
register_sfx("masks_swing_heavy", lambda: swing(1.7, 4))
register_sfx("masks_super", superflash)
register_sfx("masks_throw", throw)
register_sfx("masks_thud", thud)
register_sfx("masks_ko", ko)
register_sfx("masks_gong", gong)
