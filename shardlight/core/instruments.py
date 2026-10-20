"""Instrument voices for the procedural score (pure numpy, deterministic, band-limited additive synthesis).

Two kinds of voice:

* pitched  ``fn(freq, dur, vel, seed, **kw) -> float32``  (``dur`` = held time in seconds; the array also
  contains the release tail, so its length is ``dur + release``)
* percussive ``fn(vel, seed, **kw) -> float32``  (fixed length one-shots; tuned drums accept ``freq=``)

Every voice is peak-normalised to a loudness constant of its own so that the arranger only has to think
in musical velocities.  Partials are generated additively and never exceed 0.46 * sample rate, so nothing
aliases (a naive saw/square at 22 kHz would).  ``vel`` only steers *timbre* here (brightness); the
arranger applies the continuous velocity gain itself.
"""
from __future__ import annotations

import numpy as np

from . import synth
from .synth import SR, shaped_noise

TWO_PI = 2.0 * np.pi


# ---------------------------------------------------------------------------------------------- helpers
def _n(seconds: float) -> int:
    return max(1, int(round(seconds * SR)))


def _fin(x: np.ndarray, peak: float = 0.5) -> np.ndarray:
    m = float(np.abs(x).max())
    return (x * (peak / m)).astype(np.float32) if m > 1e-9 else x.astype(np.float32)


def env_ar(hold: int, attack: float, release: float) -> np.ndarray:
    """Raised-cosine attack, flat hold, raised-cosine release.  Length ``hold + release`` samples."""
    a = min(int(round(attack * SR)), hold)
    r = _n(release)
    e = np.ones(hold + r)
    if a > 0:
        e[:a] = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    if r > 0:
        e[hold:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(r) / r)
    return e


def additive(freq, n: int, kmax: int = 24, slope=1.5, weights=None, odd: bool = False, phase: float = 0.0,
             inharm: float = 0.0) -> np.ndarray:
    """Sum of harmonics ``k ** -slope`` (``freq`` and ``slope`` may be scalars or per-sample arrays, so a
    falling ``slope`` behaves like an opening low-pass filter).  Band-limited to 0.46 * SR."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    ph = TWO_PI * np.cumsum(f) / SR + phase
    kk = int(max(1, min(kmax, 0.46 * SR / float(f.max()))))
    out = np.zeros(n, dtype=np.float32)
    sl = np.asarray(slope, dtype=np.float64)
    for k in range(1, kk + 1):
        if odd and k % 2 == 0:
            continue
        w = 1.0 if weights is None else (weights[k - 1] if k - 1 < len(weights) else 0.0)
        if w <= 1e-4:
            continue
        amp = w * np.exp(-sl * np.log(k)) if sl.ndim else w * k ** (-float(sl))
        mult = k * np.sqrt(1.0 + inharm * k * k) if inharm else k
        out += (amp * np.sin(mult * ph)).astype(np.float32)
    return out


def _vib(n: int, rate: float, cents: float, delay: float = 0.25, ramp: float = 0.5, phase: float = 0.0) -> np.ndarray:
    """Per-sample frequency multiplier for a vibrato that fades in after ``delay`` seconds."""
    t = np.arange(n) / SR
    depth = np.clip((t - delay) / max(ramp, 1e-3), 0.0, 1.0) * cents
    return 2.0 ** (depth * np.sin(TWO_PI * rate * t + phase) / 1200.0)


def _seeded(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


# ---------------------------------------------------------------------------------------------- pitched
def pad(freq, dur, vel, seed, voices=3, detune=8.0, attack=0.7, release=1.4, slope=(2.4, 1.3), sweep=1.2,
        odd=False, trem=0.0, trem_rate=0.3, kmax=14):
    """Detuned additive pad whose brightness opens over ``sweep`` seconds (string/synth pad)."""
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    s = np.clip(t / sweep, 0, 1)
    s = s * s * (3 - 2 * s)
    sl = slope[0] + (slope[1] - slope[0]) * s
    rng = _seeded(seed)
    out = np.zeros(n, dtype=np.float32)
    for v in range(voices):
        cents = 0.0 if voices == 1 else (v / (voices - 1) - 0.5) * 2 * detune
        out += additive(freq * 2 ** (cents / 1200), n, kmax=kmax, slope=sl, odd=odd, phase=rng.uniform(0, TWO_PI))
    out *= env_ar(hold, attack, release)
    if trem:
        out *= 1 - trem * 0.5 * (1 + np.sin(TWO_PI * trem_rate * t + rng.uniform(0, TWO_PI)))
    return _fin(out)


def brass(freq, dur, vel, seed, attack=0.09, release=0.3, dark=0.0, vib=10.0, scoop=35.0):
    """Horn/brass section: bright-to-mellow spectral decay on the attack, scooped entry, late vibrato, breath."""
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    f = freq * 2 ** (-scoop * np.exp(-t / 0.045) / 1200.0) * _vib(n, 5.1, vib, delay=0.35, ramp=0.5)
    sl = 1.25 + dark + (1.0 + 0.8 * vel) * np.exp(-t / 0.16)
    body = additive(f, n, kmax=22, slope=sl)
    body += 0.55 * additive(f * 2 ** (6 / 1200), n, kmax=22, slope=sl, phase=1.3)
    breath = shaped_noise(n / SR, seed, 700, 3200) * 0.05 * np.exp(-t / 0.12)
    return _fin((body * 0.5 + breath) * env_ar(hold, attack, release))


def bell(freq, dur, vel, seed, kind="glass", tau_scale=0.3):
    """Inharmonic struck-metal partial set.  kind: glass (bright, short top), church (hum + tierce), tubular."""
    sets = {
        "glass": ([1.0, 2.756, 5.404, 8.933], [1.0, 0.55, 0.28, 0.12], [1.0, 0.5, 0.25, 0.12]),
        "church": ([0.5, 1.0, 1.183, 1.506, 2.0, 2.514, 2.662, 3.011, 4.166],
                   [0.6, 1.0, 0.7, 0.5, 0.55, 0.35, 0.3, 0.25, 0.15], [1.0, 1.0, 0.8, 0.7, 0.6, 0.5, 0.45, 0.4, 0.3]),
        "tubular": ([1.0, 2.0, 3.0, 4.1, 5.43, 6.8], [1.0, 0.7, 0.5, 0.35, 0.2, 0.12], [1.0, 0.8, 0.6, 0.45, 0.3, 0.2]),
    }
    ratios, amps, taus = sets[kind]
    n = _n(dur)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for r, a, tk in zip(ratios, amps, taus):
        fr = freq * r
        if fr > 0.46 * SR:
            continue
        out += (a * np.exp(-t / (dur * tau_scale * tk)) * np.sin(TWO_PI * fr * t + 0.7 * r)).astype(np.float32)
    out *= np.minimum(1.0, t / 0.0015) * np.minimum(1.0, (dur - t) / min(0.2, dur * 0.2))
    return _fin(out)


def fm_bell(freq, dur, vel, seed, ratio=3.5, index=3.0, tau_scale=0.3):
    """Two-operator FM bell (index decays with the amplitude, so the strike is bright and the ring pure)."""
    n = _n(dur)
    t = np.arange(n) / SR
    index = min(index, 0.3 * SR / max(freq * ratio, 1.0) * 4.0)
    idx = index * np.exp(-t / (dur * tau_scale * 0.6))
    mod = np.sin(TWO_PI * freq * ratio * t)
    out = np.sin(TWO_PI * freq * t + idx * mod) + 0.25 * np.sin(TWO_PI * 2 * freq * t)
    out *= np.exp(-t / (dur * tau_scale)) * np.minimum(1.0, t / 0.001) * np.minimum(1.0, (dur - t) / min(0.2, dur * 0.2))
    return _fin(out)


_PLUCKS = {
    #            decay s  upper-damp  slope  pick-pos click  octave-register  inharmonicity
    "harp":        dict(tau=1.7, damp=0.7, slope=1.2, pos=0.22, click=0.05, octave=0.0, inharm=0.0),
    "guitar":      dict(tau=1.2, damp=1.0, slope=1.0, pos=0.15, click=0.12, octave=0.0, inharm=0.0),
    "lute":        dict(tau=0.9, damp=1.3, slope=1.1, pos=0.18, click=0.10, octave=0.25, inharm=0.0),
    "harpsichord": dict(tau=0.8, damp=0.5, slope=0.55, pos=0.11, click=0.30, octave=0.5, inharm=0.0),
    "pizz":        dict(tau=0.25, damp=1.2, slope=1.0, pos=0.3, click=0.06, octave=0.0, inharm=0.0),
    "kalimba":     dict(tau=0.7, damp=1.5, slope=1.4, pos=0.5, click=0.04, octave=0.0, inharm=0.04),
    "celesta":     dict(tau=1.1, damp=1.8, slope=0.9, pos=0.35, click=0.02, octave=0.0, inharm=0.006),
    "clock":       dict(tau=0.35, damp=2.5, slope=0.7, pos=0.4, click=0.2, octave=0.0, inharm=0.012),
}


def _pluck_core(freq, n, p):
    t = np.arange(n) / SR
    kk = int(max(1, min(26, 0.46 * SR / freq)))
    out = np.zeros(n, dtype=np.float32)
    for k in range(1, kk + 1):
        w = abs(np.sin(np.pi * k * p["pos"])) / k ** p["slope"]
        if w < 2e-3:
            continue
        tk = p["tau"] / (1.0 + p["damp"] * (k - 1) * 0.5)
        mult = k * np.sqrt(1.0 + p["inharm"] * k * k)
        out += (w * np.exp(-t / tk) * np.sin(TWO_PI * freq * mult * t)).astype(np.float32)
    return out


def pluck(freq, dur, vel, seed, kind="harp", tau_scale=1.0):
    """Plucked/struck string family.  Upper partials die faster (string physics); pick position notches the
    spectrum; optional extra octave register (harpsichord 4' stop) and a noisy jack/pick click."""
    p = dict(_PLUCKS[kind])
    p["tau"] *= tau_scale
    rel = 0.09
    hold = _n(dur)
    n = hold + _n(rel)
    out = _pluck_core(freq, n, p)
    if p["octave"] and freq * 2 < 0.45 * SR:
        out += p["octave"] * _pluck_core(freq * 2, n, p)
    if p["click"]:
        c = shaped_noise(0.012, seed, 1200, 7000)
        out[:len(c)] += p["click"] * 0.6 * c * np.exp(-np.arange(len(c)) / (0.003 * SR))
    out *= env_ar(hold, 0.0012, rel)
    return _fin(out)


def organ(freq, dur, vel, seed, levels=(0.6, 1.0, 0.5, 0.7, 0.35, 0.3, 0.12, 0.1, 0.08), leslie=0.12, attack=0.025,
          release=0.09):
    """Drawbar organ: footages 16' 8' 5 1/3' 4' 2 2/3' 2' 1 3/5' 1 1/3' 1', key click, slow rotary shimmer."""
    ratios = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for r, lv in zip(ratios, levels):
        if freq * r < 0.46 * SR and lv > 0:
            out += (lv * np.sin(TWO_PI * freq * r * t)).astype(np.float32)
    out *= 1 - leslie * 0.5 * (1 + np.sin(TWO_PI * 6.1 * t))
    chiff = shaped_noise(0.03, seed, 1500, 5000)
    out[:len(chiff)] += 0.12 * chiff * np.exp(-np.arange(len(chiff)) / (0.007 * SR))
    return _fin(out * env_ar(hold, attack, release))


def flute(freq, dur, vel, seed, breath=0.12, vib=12.0, attack=0.07, release=0.16, overblow=0.0):
    """Breathy flute / whistle: near-sine body, band-limited breath noise around the pitch, scooped entry."""
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    f = freq * 2 ** (-22 * np.exp(-t / 0.04) / 1200.0) * _vib(n, 5.2, vib, delay=0.3, ramp=0.5, phase=(seed % 7) * 0.3)
    body = additive(f, n, kmax=6, slope=2.3 - overblow)
    nz = shaped_noise(n / SR, seed, min(freq * 1.5, 6000), min(freq * 5.0, 9500))
    env = env_ar(hold, attack, release) * (1.0 + 0.35 * np.exp(-t / 0.05))
    return _fin((body + breath * 2.5 * nz) * env)


_VOWELS = {"ah": ((700, 1.0, 130), (1150, 0.55, 160), (2600, 0.2, 250)),
           "oo": ((350, 1.0, 90), (780, 0.35, 140), (2400, 0.08, 250)),
           "ee": ((310, 1.0, 100), (2200, 0.5, 200), (3000, 0.3, 250)),
           "oh": ((500, 1.0, 110), (900, 0.5, 150), (2500, 0.1, 250))}


def choir(freq, dur, vel, seed, vowel="ah", voices=4, attack=0.9, release=1.3, spread=14.0):
    """Formant-filtered detuned voices with independent vibrato: a synthetic vocal pad."""
    hold = _n(dur)
    n = hold + _n(release)
    rng = _seeded(seed)
    kmax = int(min(40, 0.45 * SR / freq))
    ks = np.arange(1, kmax + 1) * freq
    w = np.full(len(ks), 0.05)
    for fc, amp, bw in _VOWELS[vowel]:
        w = w + amp * np.exp(-0.5 * ((ks - fc) / bw) ** 2)
    out = np.zeros(n, dtype=np.float32)
    for v in range(voices):
        cents = rng.uniform(-spread, spread)
        f = freq * 2 ** (cents / 1200.0) * _vib(n, rng.uniform(4.6, 5.8), 9.0, delay=0.5, ramp=1.0, phase=rng.uniform(0, 6))
        out += additive(f, n, kmax=kmax, slope=0.0, weights=w / ks.clip(1) * ks[0], phase=rng.uniform(0, TWO_PI))
    return _fin(out * env_ar(hold, attack, release))


def sub_bass(freq, dur, vel, seed, harm=0.3, drive=1.4, attack=0.008, release=0.1):
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    out = np.sin(TWO_PI * freq * t) + harm * np.sin(TWO_PI * 2 * freq * t + 0.5) + 0.08 * np.sin(TWO_PI * 3 * freq * t)
    out = np.tanh(out * drive) * env_ar(hold, attack, release)
    return _fin(out)


def saw_bass(freq, dur, vel, seed, detune=0.0, bright=(0.8, 2.4), decay=0.16, drive=1.6, attack=0.004, release=0.07):
    """Filtered-saw bass; the (virtual) filter starts open and closes over ``decay`` seconds."""
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    sl = bright[1] + (bright[0] - bright[1]) * np.exp(-t / decay)
    out = additive(freq, n, kmax=18, slope=sl)
    if detune:
        out += additive(freq * 2 ** (detune / 1200), n, kmax=18, slope=sl, phase=1.1)
        out += additive(freq * 2 ** (-detune / 1200), n, kmax=18, slope=sl, phase=2.2)
    out = np.tanh(out * drive * (0.6 if detune else 1.0))
    return _fin(out * env_ar(hold, attack, release))


def synth_pluck(freq, dur, vel, seed, bright=(0.7, 2.6), decay=0.11, voices=2, detune=9.0, odd=False, attack=0.002,
                release=0.05):
    """Bright arpeggio synth: detuned saws with a fast closing filter."""
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    sl = bright[1] + (bright[0] - bright[1]) * np.exp(-t / decay)
    out = np.zeros(n, dtype=np.float32)
    for v in range(voices):
        cents = 0.0 if voices == 1 else (v / (voices - 1) - 0.5) * 2 * detune
        out += additive(freq * 2 ** (cents / 1200), n, kmax=16, slope=sl, odd=odd, phase=1.7 * v)
    return _fin(out * env_ar(hold, attack, release) * (0.45 + 0.55 * np.exp(-t / (decay * 4 + dur))))


def saw_lead(freq, dur, vel, seed, voices=3, detune=10.0, bright=(1.0, 1.7), vib=8.0, attack=0.02, release=0.14,
             drive=1.0):
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    f = freq * _vib(n, 5.6, vib, delay=0.2, ramp=0.4)
    sl = bright[1] + (bright[0] - bright[1]) * np.exp(-t / 0.25)
    out = np.zeros(n, dtype=np.float32)
    for v in range(voices):
        cents = 0.0 if voices == 1 else (v / (voices - 1) - 0.5) * 2 * detune
        out += additive(f * 2 ** (cents / 1200), n, kmax=18, slope=sl, phase=2.1 * v)
    if drive != 1.0:
        out = np.tanh(out * drive * 0.5)
    return _fin(out * env_ar(hold, attack, release))


def glass_pad(freq, dur, vel, seed, attack=0.9, release=1.6, shimmer=0.4):
    """Airy pad of stacked octaves/fifths with an inharmonic sparkle; used for shimmering textures."""
    hold = _n(dur)
    n = hold + _n(release)
    t = np.arange(n) / SR
    rng = _seeded(seed)
    out = np.zeros(n, dtype=np.float32)
    for r, a in ((1.0, 1.0), (2.0, 0.6), (3.0, 0.35), (4.0, 0.3), (6.0, 0.12)):
        if freq * r > 0.45 * SR:
            continue
        for cents in (-6.0, 6.0):
            ph = rng.uniform(0, TWO_PI)
            lfo = 1 - shimmer * 0.5 * (1 + np.sin(TWO_PI * rng.uniform(0.15, 0.6) * t + rng.uniform(0, 6)))
            out += (a * lfo * np.sin(TWO_PI * freq * r * 2 ** (cents / 1200) * t + ph)).astype(np.float32)
    return _fin(out * env_ar(hold, attack, release))


def drone_tone(freq, n, seed, beat=0.0, roughness=0.3, slope=2.0):
    """Sustained sinusoid stack of exactly ``n`` samples (no envelope).  Used for periodic loop drones."""
    t = np.arange(n) / SR
    out = additive(freq, n, kmax=10, slope=slope)
    if beat:
        out += roughness * additive(freq + beat, n, kmax=10, slope=slope, phase=0.9)
    return out


# ---------------------------------------------------------------------------------------------- percussion
def kick(vel, seed, f0=135.0, f1=46.0, pitch_tau=0.035, tau=0.2, click=0.25, drive=1.6, length=0.45, level=0.9):
    n = _n(length)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t / pitch_tau)
    body = np.sin(TWO_PI * np.cumsum(f) / SR)
    body = np.tanh(body * drive) * np.exp(-t / tau)
    c = shaped_noise(length, seed, 800, 5000) * click * np.exp(-t / 0.004)
    out = (body + c) * np.minimum(1.0, t / 0.0012) * np.minimum(1.0, (length - t) / 0.05)
    return _fin(out, level)


def snare(vel, seed, tone=190.0, noise_tau=0.11, tone_tau=0.07, snap=0.9, length=0.4, level=0.6, band=(1400, 7500)):
    n = _n(length)
    t = np.arange(n) / SR
    body = (np.sin(TWO_PI * tone * t * (1 + 0.25 * np.exp(-t / 0.02))) + 0.5 * np.sin(TWO_PI * tone * 1.62 * t)) * np.exp(-t / tone_tau)
    nz = shaped_noise(length, seed, *band) * np.exp(-t / noise_tau) * snap
    out = (body * 0.7 + nz) * np.minimum(1.0, t / 0.0008) * np.minimum(1.0, (length - t) / 0.06)
    return _fin(out, level)


def clap(vel, seed, length=0.35, level=0.55):
    n = _n(length)
    t = np.arange(n) / SR
    nz = shaped_noise(length, seed, 900, 4200)
    env = np.exp(-t / 0.09) * 0.8
    for off in (0.0, 0.011, 0.022):
        i = int(off * SR)
        env[i:] += 1.0 * np.exp(-np.arange(n - i) / (0.004 * SR))
    return _fin(nz * env * np.minimum(1.0, t / 0.0006) * np.minimum(1.0, (length - t) / 0.05), level)


_HAT_PARTIALS = (1.0, 1.4471, 1.6170, 1.9265, 2.5028, 2.6637)


def hat(vel, seed, open_=False, tau=None, level=0.28, lo=6000.0):
    tau = tau or (0.2 if open_ else 0.028)
    length = tau * 6 + 0.01
    n = _n(length)
    t = np.arange(n) / SR
    nz = shaped_noise(length, seed, lo, 10500)
    metal = sum(np.sign(np.sin(TWO_PI * 1250.0 * r * t)) for r in _HAT_PARTIALS) / 6.0
    metal = synth.highpass_fast(metal.astype(np.float32), 5000)
    out = (nz * 0.8 + metal * 0.35) * np.exp(-t / tau) * np.minimum(1.0, t / 0.0008) * np.minimum(1.0, (length - t) / 0.01)
    return _fin(out, level)


def shaker(vel, seed, tau=0.05, level=0.25, attack=0.012):
    length = tau * 6
    n = _n(length)
    t = np.arange(n) / SR
    nz = shaped_noise(length, seed, 3500, 9500)
    return _fin(nz * np.exp(-t / tau) * np.minimum(1.0, t / attack) * np.minimum(1.0, (length - t) / 0.01), level)


def brush(vel, seed, level=0.22):
    """Soft brushed snare: low-passed noise with a swell, no tone."""
    length = 0.28
    n = _n(length)
    t = np.arange(n) / SR
    nz = shaped_noise(length, seed, 1200, 6500)
    env = np.minimum(1.0, t / 0.03) * np.exp(-t / 0.1)
    return _fin(nz * env * np.minimum(1.0, (length - t) / 0.04), level)


def tom(vel, seed, freq=110.0, tau=0.28, level=0.7, slap=0.25):
    length = tau * 5
    n = _n(length)
    t = np.arange(n) / SR
    f = freq * (1.0 + 0.4 * np.exp(-t / 0.03))
    body = np.sin(TWO_PI * np.cumsum(f) / SR) + 0.35 * np.sin(TWO_PI * np.cumsum(f * 1.58) / SR) * np.exp(-t / (tau * 0.4))
    s = shaped_noise(length, seed, 500, 3500) * slap * np.exp(-t / 0.012)
    out = (body * np.exp(-t / tau) + s) * np.minimum(1.0, t / 0.001) * np.minimum(1.0, (length - t) / 0.05)
    return _fin(out, level)


def taiko(vel, seed, freq=76.0, tau=0.5, level=0.95, hard=1.0):
    """Large lacquered drum: heavy sine with a downward pitch snap, inharmonic membrane modes, wooden slap and
    a long sub tail, so a hit rings rather than thuds."""
    length = tau * 4.5
    n = _n(length)
    t = np.arange(n) / SR
    f = freq * (1.0 + 0.9 * np.exp(-t / 0.035))
    ph = np.cumsum(f) / SR
    body = np.sin(TWO_PI * ph) * np.exp(-t / tau)
    body += 0.55 * np.sin(TWO_PI * ph * 1.59) * np.exp(-t / (tau * 0.55))
    body += 0.3 * np.sin(TWO_PI * ph * 2.14) * np.exp(-t / (tau * 0.4))
    body += 0.4 * np.sin(TWO_PI * freq * 0.5 * t) * np.exp(-t / (tau * 1.6))
    slap = shaped_noise(length, seed, 300, 2600) * np.exp(-t / 0.02) * 0.9 * hard
    out = np.tanh((body + slap) * 1.3) * np.minimum(1.0, t / 0.001) * np.minimum(1.0, (length - t) / 0.12)
    return _fin(out, level)


def rim(vel, seed, freq=1700.0, level=0.5):
    """Drum rim / 'ka' click: short wooden tone plus a band of noise."""
    length = 0.12
    n = _n(length)
    t = np.arange(n) / SR
    tone = np.sin(TWO_PI * freq * t) + 0.5 * np.sin(TWO_PI * freq * 2.4 * t)
    nz = shaped_noise(length, seed, 1500, 6000)
    out = (tone * np.exp(-t / 0.014) + nz * np.exp(-t / 0.01)) * np.minimum(1.0, t / 0.0006) * np.minimum(1.0, (length - t) / 0.02)
    return _fin(out, level)


def timpani(vel, seed, freq=98.0, tau=0.9, level=0.8):
    length = tau * 4
    n = _n(length)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for r, a, tk in ((1.0, 1.0, 1.0), (1.5, 0.7, 0.75), (1.99, 0.55, 0.55), (2.44, 0.35, 0.4), (2.9, 0.2, 0.3)):
        pitch = 1.0 + 0.06 * np.exp(-t / 0.15)
        out += a * np.exp(-t / (tau * tk)) * np.sin(TWO_PI * np.cumsum(freq * r * pitch) / SR)
    out += shaped_noise(length, seed, 200, 2000) * np.exp(-t / 0.015) * 0.5
    return _fin(out * np.minimum(1.0, t / 0.002) * np.minimum(1.0, (length - t) / 0.12), level)


def gong(vel, seed, freq=110.0, length=5.0, level=0.6):
    n = _n(length)
    t = np.arange(n) / SR
    rng = _seeded(seed)
    out = np.zeros(n)
    for r in (1.0, 1.47, 2.09, 2.56, 3.02, 3.92, 4.58, 5.64):
        if freq * r > 0.45 * SR:
            continue
        out += rng.uniform(0.4, 1.0) / r ** 0.5 * np.exp(-t / (length * 0.22 / r ** 0.3)) * np.sin(TWO_PI * freq * r * t + rng.uniform(0, 6)) \
            * (1 + 0.25 * np.sin(TWO_PI * rng.uniform(0.5, 3.0) * t))
    out += shaped_noise(length, seed + 1, 1000, 6000) * np.exp(-t / 0.4) * 0.12
    return _fin(out * np.minimum(1.0, t / 0.004) * np.minimum(1.0, (length - t) / 0.4), level)


def woodblock(vel, seed, freq=1500.0, level=0.45):
    length = 0.1
    n = _n(length)
    t = np.arange(n) / SR
    out = (np.sin(TWO_PI * freq * t) + 0.4 * np.sin(TWO_PI * freq * 2.27 * t)) * np.exp(-t / 0.012)
    out += shaped_noise(length, seed, 1500, 5000) * np.exp(-t / 0.004) * 0.4
    return _fin(out * np.minimum(1.0, t / 0.0005) * np.minimum(1.0, (length - t) / 0.02), level)


def tick(vel, seed, freq=3200.0, level=0.3, tau=0.006):
    """Clockwork tick: a tiny resonant click."""
    length = tau * 12
    n = _n(length)
    t = np.arange(n) / SR
    out = np.sin(TWO_PI * freq * t) * np.exp(-t / tau) + shaped_noise(length, seed, 2000, 9000) * np.exp(-t / (tau * 0.5)) * 0.6
    return _fin(out * np.minimum(1.0, t / 0.0004) * np.minimum(1.0, (length - t) / 0.004), level)


def cymbal(vel, seed, length=2.4, level=0.4, swell=0.0):
    """Crash (swell=0) or reverse-style swell (swell>0 = rise time in seconds, then a short decay)."""
    n = _n(length)
    t = np.arange(n) / SR
    nz = shaped_noise(length, seed, 3000, 10500)
    metal = sum(np.sin(TWO_PI * 700 * r * t + r) for r in (1.0, 1.52, 2.17, 2.9, 3.41, 4.4)) / 6.0
    if swell:
        env = np.clip(t / swell, 0, 1) ** 2.2
        env = np.where(t < swell, env, np.exp(-(t - swell) / 0.25))
    else:
        env = np.exp(-t / (length * 0.32)) * np.minimum(1.0, t / 0.002)
    return _fin((nz * 0.8 + metal * 0.3) * env * np.minimum(1.0, (length - t) / 0.08), level)


def boom(vel, seed, freq=42.0, length=3.0, level=0.9, noise=0.35):
    """Low impact: falling sub sine plus a rumble of low-passed noise."""
    n = _n(length)
    t = np.arange(n) / SR
    f = freq * (1.0 + 1.2 * np.exp(-t / 0.18))
    body = np.sin(TWO_PI * np.cumsum(f) / SR) * np.exp(-t / (length * 0.28))
    rumble = shaped_noise(length, seed, 25, 170) * np.exp(-t / (length * 0.22)) * noise
    return _fin((body + rumble) * np.minimum(1.0, t / 0.004) * np.minimum(1.0, (length - t) / 0.3), level)


def riser(vel, seed, length=3.0, level=0.3, lo=300.0, hi=6000.0):
    """Noise swell whose band opens upward (tension builder)."""
    n = _n(length)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    nz = shaped_noise(length, seed, 200, 9000)
    bands = 6
    for b in range(bands):
        centre = lo * (hi / lo) ** (b / (bands - 1))
        env = np.exp(-0.5 * ((t / length - b / (bands - 1)) / 0.22) ** 2)
        out += synth.bandpass_fast(nz, centre * 0.7, centre * 1.4) * env.astype(np.float32)
    out *= (t / length) ** 1.6 * np.minimum(1.0, (length - t) / 0.05)
    return _fin(out, level)


PITCHED = {
    "pad": pad, "brass": brass, "bell": bell, "fm_bell": fm_bell, "pluck": pluck, "organ": organ, "flute": flute,
    "choir": choir, "sub_bass": sub_bass, "saw_bass": saw_bass, "synth_pluck": synth_pluck, "saw_lead": saw_lead,
    "glass_pad": glass_pad,
}
PERCUSSION = {
    "kick": kick, "snare": snare, "clap": clap, "hat": hat, "shaker": shaker, "brush": brush, "tom": tom,
    "taiko": taiko, "rim": rim, "timpani": timpani, "gong": gong, "woodblock": woodblock, "tick": tick,
    "cymbal": cymbal, "boom": boom, "riser": riser,
}
