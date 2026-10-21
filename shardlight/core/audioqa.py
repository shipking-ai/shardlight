"""Signal-analysis helpers used to verify generated audio without listening to it (tests and tools/audio_report.py).

Nothing here is needed at game run time.  All functions take mono float arrays at ``SR``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .synth import SR

try:  # the browser build (pygbag) has no wave module; these helpers are tools-only
    import wave
except ImportError:  # pragma: no cover - platform dependent
    wave = None  # type: ignore[assignment]


def load_wav(path: str | Path) -> np.ndarray:
    """16-bit mono WAV -> float32 in [-1, 1)."""
    if wave is None:
        raise RuntimeError("the wave module is unavailable in this build")
    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1, "expected 16-bit mono"
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return (data.astype(np.float32) / 32768.0)


def wav_info(path: str | Path) -> dict:
    if wave is None:
        raise RuntimeError("the wave module is unavailable in this build")
    with wave.open(str(path), "rb") as w:
        return {"channels": w.getnchannels(), "width": w.getsampwidth(), "rate": w.getframerate(), "frames": w.getnframes()}


def peak(x: np.ndarray) -> float:
    return float(np.abs(x).max()) if len(x) else 0.0


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def dbfs(v: float) -> float:
    return 20 * np.log10(max(v, 1e-9))


def clipped_samples(x: np.ndarray) -> int:
    """Number of samples at (or within one LSB of) full scale in the 16-bit domain."""
    return int(np.count_nonzero(np.abs(x) >= 32766.0 / 32768.0))


def seam_ratio(x: np.ndarray) -> float:
    """Loop-point discontinuity relative to the file's own sample-to-sample movement.

    ``|x[0] - x[-1]|`` divided by the 99.9th percentile of ``|diff(x)|`` elsewhere.  A seamless loop is on the
    order of 1 or below (the jump is an ordinary step of the waveform); a click is many times larger."""
    d = np.abs(np.diff(x.astype(np.float64)))
    ref = max(float(np.percentile(d, 99.9)), 1.0 / 32768.0)
    return float(abs(float(x[0]) - float(x[-1])) / ref)


def spectral_centroid(x: np.ndarray) -> float:
    spec = np.abs(np.fft.rfft(x.astype(np.float64) * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float((f * spec).sum() / max(spec.sum(), 1e-12))


def band_energy(x: np.ndarray, edges=(0, 150, 600, 2400, 11025)) -> list[float]:
    """Fraction of spectral energy in consecutive bands [edges[i], edges[i+1])."""
    spec = np.abs(np.fft.rfft(x.astype(np.float64))) ** 2
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    total = max(spec.sum(), 1e-18)
    return [float(spec[(f >= lo) & (f < hi)].sum() / total) for lo, hi in zip(edges[:-1], edges[1:])]


def chroma(x: np.ndarray, n_fft: int = 16384, hop: int = 8192, fmin: float = 50.0, fmax: float = 4000.0,
           tol_semitones: float = 0.3, rel_thresh: float = 0.02) -> np.ndarray:
    """Energy per pitch class (C=0 .. B=11), from tonal spectral peaks only.

    Peaks within ``tol_semitones`` of an equal-tempered pitch (A=440) are accumulated, so noise, drums and
    strongly inharmonic partials mostly drop out.  Harmonics of a note land on other pitch classes (3rd harmonic =
    a fifth, 5th = a major third...), which is why scale-adherence thresholds are set below 100 %."""
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / SR)
    out = np.zeros(12)
    xx = x.astype(np.float64)
    if len(xx) < n_fft:
        xx = np.pad(xx, (0, n_fft - len(xx)))
    for start in range(0, len(xx) - n_fft + 1, hop):
        mag = np.abs(np.fft.rfft(xx[start:start + n_fft] * win))
        m0 = mag.max()
        if m0 < 1e-6:
            continue
        i = np.arange(1, len(mag) - 1)
        pk = i[(mag[i] > mag[i - 1]) & (mag[i] >= mag[i + 1]) & (mag[i] > rel_thresh * m0)]
        pk = pk[(freqs[pk] >= fmin) & (freqs[pk] <= fmax)]
        if not len(pk):
            continue
        a, b, c = np.log(mag[pk - 1] + 1e-12), np.log(mag[pk] + 1e-12), np.log(mag[pk + 1] + 1e-12)
        delta = 0.5 * (a - c) / (a - 2 * b + c - 1e-12)
        f = (pk + np.clip(delta, -0.5, 0.5)) * (SR / n_fft)
        midi = 69 + 12 * np.log2(f / 440.0)
        near = np.round(midi)
        ok = np.abs(midi - near) <= tol_semitones
        np.add.at(out, (near[ok].astype(int)) % 12, mag[pk][ok] ** 2)
    total = out.sum()
    return out / total if total > 0 else out


def scale_fraction(chroma_vec: np.ndarray, pitch_classes) -> float:
    return float(sum(chroma_vec[pc] for pc in pitch_classes))


def onset_envelope(x: np.ndarray, hop: int = 256) -> np.ndarray:
    """Half-wave-rectified energy flux (one value per ``hop`` samples)."""
    n = len(x) // hop
    e = np.sqrt(np.mean(x[:n * hop].reshape(n, hop).astype(np.float64) ** 2, axis=1))
    return np.maximum(np.diff(e, prepend=e[0]), 0.0)


def autocorr_at(env: np.ndarray, lag: int) -> float:
    """Circular normalised autocorrelation of an onset envelope at ``lag`` envelope samples (loops are periodic)."""
    e = env - env.mean()
    denom = float(np.dot(e, e))
    return float(np.dot(e, np.roll(e, lag)) / denom) if denom > 0 else 0.0
