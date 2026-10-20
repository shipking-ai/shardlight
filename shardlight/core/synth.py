"""Small numpy synthesis toolkit used to *author* all original sound (SFX recipes and music stems).

Everything returns float32 mono arrays in [-1, 1] at ``SR``.  The build tool ``tools/gen_audio.py`` renders
recipes to WAV files in ``assets/audio``; the game loads those files (and falls back to the recipes if a file
is missing).  Keep every function deterministic: noise takes an explicit seed.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 22050


# ------------------------------------------------------------------ basics
def n_samples(dur: float) -> int:
    return max(1, int(round(dur * SR)))


def midi_to_hz(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


_NOTE = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def note(name: str) -> float:
    """'a4' -> 440.0, 'c#3', 'eb5'."""
    s = name.lower()
    n = _NOTE[s[0]]
    i = 1
    if i < len(s) and s[i] in "#b":
        n += 1 if s[i] == "#" else -1
        i += 1
    octave = int(s[i:])
    return midi_to_hz(12 * (octave + 1) + n)


def _phase(freq, n: int) -> np.ndarray:
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    return np.cumsum(f) / SR


def sine(freq, dur: float) -> np.ndarray:
    return np.sin(2 * np.pi * _phase(freq, n_samples(dur))).astype(np.float32)


def square(freq, dur: float, duty: float = 0.5) -> np.ndarray:
    p = _phase(freq, n_samples(dur)) % 1.0
    return np.where(p < duty, 1.0, -1.0).astype(np.float32)


def saw(freq, dur: float) -> np.ndarray:
    p = _phase(freq, n_samples(dur)) % 1.0
    return (2 * p - 1).astype(np.float32)


def tri(freq, dur: float) -> np.ndarray:
    p = _phase(freq, n_samples(dur)) % 1.0
    return (4 * np.abs(p - 0.5) - 1).astype(np.float32)


def noise(dur: float, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-1, 1, n_samples(dur)).astype(np.float32)


def sweep(f0: float, f1: float, dur: float, shape: str = "sine", curve: float = 1.0) -> np.ndarray:
    n = n_samples(dur)
    t = (np.linspace(0, 1, n) ** curve)
    f = f0 + (f1 - f0) * t
    fn = {"sine": sine, "square": square, "saw": saw, "tri": tri}[shape]
    return fn(f, dur)


# ------------------------------------------------------------------ envelopes
def adsr(n: int, a: float = 0.01, d: float = 0.05, s: float = 0.7, r: float = 0.1) -> np.ndarray:
    ai, di, ri = int(a * SR), int(d * SR), int(r * SR)
    si = max(0, n - ai - di - ri)
    env = np.concatenate([np.linspace(0, 1, max(1, ai), endpoint=False), np.linspace(1, s, max(1, di), endpoint=False),
                          np.full(si, s), np.linspace(s, 0, max(1, ri))])
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    return env[:n].astype(np.float32)


def decay(n: int, tau: float) -> np.ndarray:
    """Exponential decay with time constant ``tau`` seconds."""
    return np.exp(-np.arange(n) / (tau * SR)).astype(np.float32)


def fade_edges(x: np.ndarray, ms: float = 4.0) -> np.ndarray:
    k = min(len(x) // 2, int(ms * SR / 1000))
    if k > 0:
        x = x.copy()
        x[:k] *= np.linspace(0, 1, k)
        x[-k:] *= np.linspace(1, 0, k)
    return x


# ------------------------------------------------------------------ filters / fx
def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """One-pole low-pass (6 dB/oct); cheap and stable."""
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    out = np.empty_like(x)
    y = 0.0
    for i, v in enumerate(x):
        y += a * (v - y)
        out[i] = y
    return out


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - lowpass(x, cutoff)


def bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return lowpass(highpass(x, lo), hi)


def delay(x: np.ndarray, seconds: float, feedback: float = 0.4, mix: float = 0.3, taps: int = 4) -> np.ndarray:
    d = int(seconds * SR)
    out = np.pad(x, (0, d * taps)).astype(np.float32)
    wet = np.zeros_like(out)
    for i in range(1, taps + 1):
        wet[i * d:i * d + len(x)] += x * (feedback ** i)
    return out + wet * mix


def reverb(x: np.ndarray, seconds: float = 0.8, mix: float = 0.25, seed: int = 1) -> np.ndarray:
    n = int(seconds * SR)
    ir = np.random.default_rng(seed).normal(0, 1, n) * np.exp(-np.arange(n) / (0.28 * seconds * SR))
    ir[0] = 0
    size = 1 << (len(x) + n - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x) + n]
    wet /= max(1e-6, np.abs(wet).max())
    out = np.pad(x, (0, n)).astype(np.float64)
    return (out * (1 - mix * 0.5) + wet * mix * np.abs(x).max()).astype(np.float32)


def distort(x: np.ndarray, amount: float = 2.0) -> np.ndarray:
    return np.tanh(x * amount).astype(np.float32)


def bitcrush(x: np.ndarray, bits: int = 6, hold: int = 2) -> np.ndarray:
    q = 2 ** (bits - 1)
    y = np.round(x * q) / q
    if hold > 1:
        y = np.repeat(y[::hold], hold)[:len(x)]
    return y.astype(np.float32)


def tremolo(x: np.ndarray, rate: float, depth: float = 0.5) -> np.ndarray:
    t = np.arange(len(x)) / SR
    return (x * (1 - depth + depth * 0.5 * (1 + np.sin(2 * np.pi * rate * t)))).astype(np.float32)


# ------------------------------------------------------------------ mixing helpers
def mixdown(*parts: np.ndarray, gains: tuple[float, ...] | None = None) -> np.ndarray:
    n = max(len(p) for p in parts)
    out = np.zeros(n, dtype=np.float32)
    for i, p in enumerate(parts):
        out[:len(p)] += p * (gains[i] if gains else 1.0)
    return out


def place(buf: np.ndarray, clip: np.ndarray, at: float, gain: float = 1.0) -> None:
    """Add ``clip`` into ``buf`` starting at ``at`` seconds (clipped to buffer length)."""
    i = int(at * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(clip))
    buf[i:j] += clip[:j - i] * gain


def normalize(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.abs(x).max())
    return x if m < 1e-9 else (x * (peak / m)).astype(np.float32)


def make_loop(x: np.ndarray, loop_len: int) -> np.ndarray:
    """Fold the reverb/delay tail beyond ``loop_len`` back onto the start so the loop is seamless."""
    out = x[:loop_len].copy()
    tail = x[loop_len:]
    if len(tail):
        out[:len(tail)] += tail[:loop_len]
    return out


def write_wav(path: str | Path, x: np.ndarray) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------ fast (FFT based) filters  [additive API]
# The original ``lowpass`` is a Python loop (fine for tiny SFX, far too slow for minutes of music).  These
# variants build the filter's impulse response and convolve through the FFT; same sound, ~1000x faster.
def _fast_len(n: int) -> int:
    """Smallest 2^a * 3^b * 5^c >= n (FFT-friendly size)."""
    best = 1 << (max(1, n) - 1).bit_length()
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            m = p35
            while m < n:
                m *= 2
            best = min(best, m)
            p35 *= 3
        p5 *= 5
    return best


def fft_convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Full linear convolution of ``x`` with ``ir`` (length len(x)+len(ir)-1), float32."""
    n = len(x) + len(ir) - 1
    size = _fast_len(n)
    out = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:n]
    return out.astype(np.float32)


def lowpass_fast(x: np.ndarray, cutoff: float, order: int = 1) -> np.ndarray:
    """One-pole low-pass applied ``order`` times (6 dB/oct each) through an FFT convolution."""
    a = 1.0 - np.exp(-2 * np.pi * min(cutoff, SR * 0.49) / SR)
    length = int(min(len(x), max(8, np.ceil(11.5 / max(a, 1e-6)))))
    h = (a * (1.0 - a) ** np.arange(length)).astype(np.float64)
    y = x
    for _ in range(order):
        y = fft_convolve(y, h)[:len(x)]
    return y.astype(np.float32)


def highpass_fast(x: np.ndarray, cutoff: float, order: int = 1) -> np.ndarray:
    y = x
    for _ in range(order):
        y = y - lowpass_fast(y, cutoff)
    return y.astype(np.float32)


def bandpass_fast(x: np.ndarray, lo: float, hi: float, order: int = 1) -> np.ndarray:
    return lowpass_fast(highpass_fast(x, lo, order), hi, order)


def resonator(x: np.ndarray, freq: float, q: float = 8.0, ir_len: int | None = None) -> np.ndarray:
    """Constant-peak-gain two-pole band-pass (RBJ biquad) for ringing metallic / vocal-ish resonances."""
    w0 = 2 * np.pi * min(freq, SR * 0.45) / SR
    alpha = np.sin(w0) / (2 * q)
    b0, b2 = alpha, -alpha
    a0, a1, a2 = 1 + alpha, -2 * np.cos(w0), 1 - alpha
    length = ir_len or int(min(len(x), max(64, 8 * q * SR / max(freq, 20.0))))
    h = np.zeros(length)
    y1 = y2 = 0.0
    for i in range(length):                # short loop (the impulse response only), not the signal
        xin = b0 if i == 0 else (b2 if i == 2 else 0.0)
        y = (xin - a1 * y1 - a2 * y2) / a0
        h[i] = y
        y2, y1 = y1, y
    return fft_convolve(x, h)[:len(x)]


def shaped_noise(dur: float, seed: int = 0, lo: float | None = None, hi: float | None = None,
                 tilt_db_oct: float = 0.0) -> np.ndarray:
    """White noise shaped in the frequency domain: brick-wall-ish band [lo, hi] (soft 5% skirts) and a
    spectral tilt in dB/octave around 1 kHz.  Normalised to a peak of 1.  Deterministic per ``seed``."""
    n = n_samples(dur)
    spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    gain = np.ones_like(f)
    if lo:
        gain *= 1.0 / (1.0 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi:
        gain *= 1.0 / (1.0 + (np.maximum(f, 1e-3) / hi) ** 4)
    if tilt_db_oct:
        gain *= 10 ** (tilt_db_oct * np.log2(np.maximum(f, 20.0) / 1000.0) / 20.0)
    out = np.fft.irfft(spec * gain, n)
    m = float(np.abs(out).max())
    return (out / m if m > 1e-12 else out).astype(np.float32)


def remove_dc(x: np.ndarray) -> np.ndarray:
    return (x - float(np.mean(x))).astype(np.float32)
