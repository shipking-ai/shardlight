"""Procedural composition engine: scales, chords, patterns, humanised events, instruments and mixing.

A *track* is built as a :class:`Song`: you declare tempo / metre / mode and the number of bars, then add notes
and drum hits to three **layers** (``bed`` = always-on harmony/ambience, ``rhythm`` = pulse and percussion,
``lead`` = melody/tension).  :meth:`Song.render` returns three float32 arrays of *exactly* the same length,
``bars * beats * samples_per_beat`` samples, that loop sample-perfectly:

* the tempo is quantised so a beat is a whole number of samples (``Song.bpm`` is the effective tempo),
* notes, reverb and delay tails that run past the end of the loop are folded back onto its start
  (``synth.make_loop``), and the reverb/delay/EQ are applied as *circular* convolutions in the frequency
  domain, so a sound that rings across the loop point continues seamlessly into bar one,
* the three layers share one common gain curve (loudness normalisation + look-ahead limiter computed from the
  full mix) so they stay phase- and level-locked however they are cross-faded by the game.

All randomness (velocity / timing humanisation, noise in percussion) comes from seeded generators, so rendering
is bit-for-bit repeatable.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np

from . import instruments as ins
from . import synth
from .synth import SR

LAYERS = ("bed", "rhythm", "lead")

# ---------------------------------------------------------------------------------------------- theory
MODES: dict[str, tuple[int, ...]] = {
    "ionian": (0, 2, 4, 5, 7, 9, 11), "dorian": (0, 2, 3, 5, 7, 9, 10), "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11), "mixolydian": (0, 2, 4, 5, 7, 9, 10), "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10), "minor_pentatonic": (0, 3, 5, 7, 10), "major_pentatonic": (0, 2, 4, 7, 9),
    "in_sen": (0, 1, 5, 7, 10),      # five-note scale with a flat second (dark, taut)
}

_NOTE_PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def midi_of(name: str) -> int:
    """'d4' -> 62, 'f#3' -> 54, 'eb2' -> 39."""
    s = name.lower()
    n = _NOTE_PC[s[0]]
    i = 1
    if i < len(s) and s[i] in "#b":
        n += 1 if s[i] == "#" else -1
        i += 1
    return 12 * (int(s[i:]) + 1) + n


def hz(midi: float) -> float:
    return synth.midi_to_hz(midi)


@dataclass(frozen=True)
class Scale:
    """A mode on a tonic.  ``midi(d)`` maps a (possibly negative / > octave) scale degree to a MIDI note, so
    anything addressed by degree is in key by construction."""
    name: str
    tonic: int
    steps: tuple[int, ...]

    @classmethod
    def of(cls, tonic: str, mode: str) -> "Scale":
        return cls(f"{tonic} {mode}", midi_of(tonic), MODES[mode])

    @property
    def size(self) -> int:
        return len(self.steps)

    def midi(self, deg: int) -> int:
        return self.tonic + self.steps[deg % self.size] + 12 * (deg // self.size)

    def chord(self, root: int, size: int = 3, step: int = 2) -> list[int]:
        """Degrees of a chord stacked in scale-thirds on ``root`` (triad=3, seventh=4, ninth=5)."""
        return [root + step * i for i in range(size)]

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset((self.tonic + s) % 12 for s in self.steps)


def voice_lead(prev: list[int] | None, degs: list[int], scale: Scale, lo: int = 54, hi: int = 77) -> list[int]:
    """Choose octaves for the chord degrees (low->high) that move the least from ``prev`` inside [lo, hi]."""
    options = []
    for d in degs:
        base = scale.midi(d % scale.size)
        options.append([m for m in range(lo, hi + 1) if (m - base) % 12 == 0])
    best, best_cost = None, 1e9
    centre = (lo + hi) / 2

    def rec(i: int, chosen: list[int]) -> None:
        nonlocal best, best_cost
        if i == len(options):
            notes = sorted(chosen)
            if len(set(notes)) < len(notes) or notes[-1] - notes[0] > 17:
                return
            if prev is None:
                cost = sum(abs(m - centre) for m in notes)
            else:
                cost = sum(abs(a - b) for a, b in zip(notes, sorted(prev))) + 0.2 * abs(sum(notes) / len(notes) - centre)
            if cost < best_cost:
                best, best_cost = notes, cost
            return
        for m in options[i]:
            rec(i + 1, chosen + [m])

    rec(0, [])
    return best if best is not None else sorted(scale.midi(d) for d in degs)


def parse_pattern(text: str) -> list[tuple[int, float]]:
    """Step pattern string -> [(step, level)].  ``X`` accent 1.0, ``x`` normal 0.75, ``o`` ghost 0.4, ``.``/``-`` rest;
    spaces and ``|`` are ignored (they only help reading)."""
    levels = {"X": 1.0, "x": 0.75, "o": 0.4}
    out, i = [], 0
    for ch in text:
        if ch in " |":
            continue
        if ch in levels:
            out.append((i, levels[ch]))
        i += 1
    return out


def P(text: str) -> list[tuple[float, int, float, float]]:
    """Melody mini-language: ``"step:degree:length[:velocity]"`` tokens, e.g. ``"0:4:8 8:5:4:0.9"``."""
    notes = []
    for tok in text.split():
        parts = tok.split(":")
        notes.append((float(parts[0]), int(parts[1]), float(parts[2]), float(parts[3]) if len(parts) > 3 else 0.8))
    return notes


def euclid(hits: int, steps: int, rotate: int = 0) -> list[int]:
    """Bjorklund-style evenly spread onsets."""
    idx = sorted({int(np.floor(i * steps / hits)) for i in range(hits)}) if hits else []
    return [(i + rotate) % steps for i in idx]


LENS_DEGREES = (0, 4, 3, 5)             # the Lens motif: up a fifth, step back, lift (relative to chosen root degree)
LENS_ONSETS = (0.0, 1.0, 2.0, 2.5)      # in beats
LENS_LENGTHS = (1.0, 1.0, 0.5, 2.0)

# loudness trims so that different instruments sit in a similar place for the same musical velocity
INST_TRIM = {"pad": 0.9, "brass": 0.8, "bell": 1.5, "fm_bell": 1.4, "pluck": 1.0, "organ": 0.65, "flute": 0.8,
             "choir": 1.1, "sub_bass": 0.7, "saw_bass": 0.65, "synth_pluck": 1.0, "saw_lead": 0.8, "glass_pad": 1.1}


# ---------------------------------------------------------------------------------------------- fx
def room_ir(seconds: float, damp: float = 0.5, seed: int = 1, predelay: float = 0.012) -> np.ndarray:
    """Synthetic room impulse response: dense noise whose highs decay ``damp`` times faster than its lows, plus a few
    early reflections; unit energy so the wet level is controlled by the caller."""
    n = synth.n_samples(seconds)
    t = np.arange(n) / SR
    low = synth.shaped_noise(seconds, seed, None, 1800) * np.exp(-6.9 * t / seconds)
    high = synth.shaped_noise(seconds, seed + 1, 1800, None) * np.exp(-6.9 * t / (seconds * damp)) * 0.6
    ir = low / max(low.std(), 1e-9) + high / max(high.std(), 1e-9) * 0.5 * np.exp(-6.9 * t / (seconds * damp))
    ir = ir * np.exp(-6.9 * t / seconds) * np.minimum(1.0, t / 0.02)
    rng = np.random.default_rng(seed + 7)
    for ms in (7, 13, 19, 29, 41, 53, 67):
        i = int(ms * SR / 1000)
        if i < n:
            ir[i] += rng.choice([-1.0, 1.0]) * 3.0 * np.exp(-ms / 60.0)
    pre = int(predelay * SR)
    ir = np.concatenate([np.zeros(pre), ir])
    return (ir / np.sqrt(np.sum(ir ** 2))).astype(np.float64)


def _onepole_response(cutoff: float, n_bins: int, size: int) -> np.ndarray:
    a = 1.0 - np.exp(-2 * np.pi * cutoff / SR)
    w = 2 * np.pi * np.arange(n_bins) / size
    return a / (1.0 - (1.0 - a) * np.exp(-1j * w))


def _fold(x: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(n, dtype=np.float64)
    for k in range(0, len(x), n):
        seg = x[k:k + n]
        out[:len(seg)] += seg
    return out


@dataclass
class LayerCfg:
    gain: float = 1.0
    reverb: tuple[float, float, float] = (2.2, 0.3, 0.5)         # (seconds, wet/dry, damp: highs decay faster when <1)
    delay: tuple[float, float, float, float] | None = None       # (beats, feedback, wet, damp_hz)
    highpass: float = 24.0
    lowpass: float | None = None
    send: float = 0.5                                            # default reverb send of a note
    human: tuple[float, float] = (6.0, 0.06)                     # timing jitter (ms std), velocity jitter (fraction std)
    pump: tuple[float, float] | None = None                      # (depth, tau seconds): sidechain duck from kicks


@dataclass
class Event:
    layer: str
    inst: str
    midi: float | None
    t: int
    dur: int
    vel: float
    tag: str = ""
    deg: int | None = None


class Song:
    """Arranger + renderer for one looping, three-layer track."""

    def __init__(self, name: str, scale: Scale, bpm: float, beats: int, sub: int, bars: int, seed: int,
                 swing: float = 0.0, tail: float = 8.0, loudness: float = 0.13):
        self.name, self.scale, self.beats, self.sub, self.bars, self.seed = name, scale, beats, sub, bars, seed
        self.spb = int(round(SR * 60.0 / bpm))                       # samples per beat, exact integer
        self.bpm = 60.0 * SR / self.spb
        self.step_len = self.spb / sub                               # samples per step (float)
        self.steps_per_bar = beats * sub
        self.bar_len = beats * self.spb
        self.loop_len = self.bar_len * bars
        self.swing = swing
        self.loudness = loudness
        self.rng = np.random.default_rng(seed)
        self.cfg = {layer: LayerCfg() for layer in LAYERS}
        self._len = self.loop_len + int(tail * SR)
        self.bufs = {layer: {k: np.zeros(self._len, dtype=np.float32) for k in ("dry", "rev", "dly")} for layer in LAYERS}
        self.events: list[Event] = []
        self._cache: dict[tuple, np.ndarray] = {}
        self.sections: list[tuple[str, int, int]] = []

    # -- addressing -----------------------------------------------------------------------------
    @property
    def seconds(self) -> float:
        return self.loop_len / SR

    def S(self, bar: float, step: float = 0.0) -> float:
        """Absolute step index of ``step`` inside ``bar``."""
        return bar * self.steps_per_bar + step

    def _t(self, step: float) -> int:
        s = step
        if self.swing and abs(s - round(s)) < 1e-6 and int(round(s)) % 2 == 1:
            s += self.swing
        return int(round(s * self.step_len))

    def dur_s(self, steps: float) -> float:
        return steps * self.step_len / SR

    # -- configuration --------------------------------------------------------------------------
    def configure(self, layer: str, **kw) -> None:
        for k, v in kw.items():
            if not hasattr(self.cfg[layer], k):
                raise AttributeError(k)
            setattr(self.cfg[layer], k, v)

    # -- event insertion ------------------------------------------------------------------------
    def _jitter(self, layer: str, vel: float, human: bool) -> tuple[int, float]:
        tms, vfrac = self.cfg[layer].human
        if not human:
            return 0, vel
        dt = int(np.clip(self.rng.normal(0, tms), -2.5 * tms, 2.5 * tms) * SR / 1000.0)
        v = float(np.clip(vel * (1.0 + self.rng.normal(0, vfrac)), 0.05, 1.0))
        return dt, v

    def _render_cached(self, kind: str, name: str, key: tuple, fn, args: tuple, kw: dict) -> np.ndarray:
        full = (kind, name) + key + tuple(sorted(kw.items()))
        arr = self._cache.get(full)
        if arr is None:
            seed = zlib.crc32(repr(full).encode()) & 0x7FFFFFFF
            arr = fn(*args, seed=seed, **kw) if kind == "p" else fn(args[0], seed, **kw)
            self._cache[full] = arr
        return arr

    def _place(self, layer: str, arr: np.ndarray, t: int, gain: float, send: float | None, dsend: float) -> None:
        t %= self.loop_len
        end = min(self._len, t + len(arr))
        seg = arr[:end - t] * gain
        b = self.bufs[layer]
        b["dry"][t:end] += seg
        s = self.cfg[layer].send if send is None else send
        if s:
            b["rev"][t:end] += seg * s
        if dsend:
            b["dly"][t:end] += seg * dsend

    def add(self, layer: str, inst: str, midi: float, step: float, steps: float, vel: float = 0.7, *, send: float | None = None,
            dsend: float = 0.0, tag: str = "", human: bool = True, gain: float = 1.0, deg: int | None = None, **kw) -> None:
        """Play a pitched instrument.  ``step`` is absolute (use :meth:`S`), ``steps`` the held length in steps."""
        dt, v = self._jitter(layer, vel, human)
        dur = max(0.04, self.dur_s(steps))
        tv = round(v * 4) / 4
        arr = self._render_cached("p", inst, (round(midi * 20), round(dur * SR), tv), ins.PITCHED[inst],
                                  (hz(midi), dur, tv), kw)
        t = self._t(step) + dt
        self._place(layer, arr, t, v * gain * INST_TRIM.get(inst, 1.0), send, dsend)
        self.events.append(Event(layer, inst, float(midi), t % self.loop_len, int(dur * SR), v, tag, deg))

    def hit(self, layer: str, perc: str, step: float, vel: float = 0.8, *, send: float | None = None, dsend: float = 0.0,
            tag: str = "", human: bool = True, gain: float = 1.0, midi: float | None = None, **kw) -> None:
        """Play a percussion one-shot (3 seeded timbre variants avoid machine-gun repeats)."""
        dt, v = self._jitter(layer, vel, human)
        if midi is not None:
            kw["freq"] = hz(midi)
        variant = int(self.rng.integers(0, 3))
        tv = round(v * 3) / 3
        arr = self._render_cached("d", perc, (variant, tv), ins.PERCUSSION[perc], (tv,), kw)
        t = self._t(step) + dt
        self._place(layer, arr, t, v * gain, send, dsend)
        self.events.append(Event(layer, perc, midi, t % self.loop_len, len(arr), v, tag))

    def raw(self, layer: str, arr: np.ndarray, t: int = 0, gain: float = 1.0, send: float | None = None, dsend: float = 0.0,
            inst: str = "raw", midi: float | None = None) -> None:
        """Place a custom pre-rendered array (periodic drones)."""
        self._place(layer, arr.astype(np.float32), t, gain, send, dsend)
        self.events.append(Event(layer, inst, midi, t % self.loop_len, len(arr), gain, "raw"))

    # -- musical helpers --------------------------------------------------------------------------
    def phrase(self, layer: str, inst: str, bar: float, notes: list[tuple[float, int, float, float]], transpose: int = 0,
               vel: float = 1.0, **kw) -> None:
        """Play a ``P(...)`` melody starting at ``bar``; degrees are shifted by ``transpose`` scale steps."""
        for st, deg, ln, v in notes:
            self.add(layer, inst, self.scale.midi(deg + transpose), self.S(bar, st), ln, v * vel, deg=deg + transpose, **kw)

    def lens(self, layer: str, inst: str, bar: float, step: float = 0.0, root: int = 0, stretch: float = 1.0, vel: float = 0.7,
             **kw) -> None:
        """State the Lens motif (leitmotif) starting at ``bar``/``step`` on scale degree ``root`` (rising fifth, step back, lift)."""
        u = self.sub * stretch
        for onset, ln, d in zip(LENS_ONSETS, LENS_LENGTHS, LENS_DEGREES):
            self.add(layer, inst, self.scale.midi(root + d), self.S(bar, step) + onset * u, ln * u * 0.95, vel,
                     tag="lens", deg=root + d, **kw)

    def pattern(self, layer: str, perc: str, bars, pat: str, vel: float = 0.8, *, prob: float = 1.0, every: int = 1, offset: int = 0,
                **kw) -> None:
        """Repeat a drum pattern string over ``bars`` (an iterable of bar numbers)."""
        cells = parse_pattern(pat)
        for i, bar in enumerate(bars):
            if i % every != offset % every and every > 1:
                continue
            for st, lvl in cells:
                if prob < 1.0 and self.rng.random() > prob:
                    continue
                self.hit(layer, perc, self.S(bar, st), vel * lvl, **kw)

    def chord_pad(self, layer: str, inst: str, bar: float, degs: list[int], steps: float, prev: list[int] | None, vel: float = 0.6,
                  lo: int = 54, hi: int = 77, **kw) -> list[int]:
        """Voice-led chord; returns the voicing so the next chord can be led from it."""
        v = voice_lead(prev, degs, self.scale, lo, hi)
        for m in v:
            self.add(layer, inst, m, self.S(bar), steps, vel, **kw)
        return v

    def snap_freq(self, f: float) -> float:
        """Nearest frequency with a whole number of cycles in the loop (so a free-running oscillator is periodic)."""
        cycles = max(1, round(f * self.loop_len / SR))
        return cycles * SR / self.loop_len

    # -- rendering ------------------------------------------------------------------------------
    def _layer_spectrum_fx(self, layer: str, cfg: LayerCfg, N: int) -> np.ndarray:
        b = {k: synth.make_loop(v, N) if len(v) > N else v for k, v in self.bufs[layer].items()}
        F = np.fft.rfft(b["dry"].astype(np.float64))
        nb = F.shape[0]
        if cfg.reverb and cfg.reverb[1] > 0 and np.abs(b["rev"]).max() > 0:
            secs, wet, damp = cfg.reverb
            ir = _fold(room_ir(secs, damp, seed=zlib.crc32(layer.encode()) % 997 + self.seed % 13), N)
            F += np.fft.rfft(b["rev"].astype(np.float64)) * np.fft.rfft(ir) * wet
        if cfg.delay and np.abs(b["dly"]).max() > 0:
            beats, fb, wet, damp_hz = cfg.delay
            d = int(round(beats * self.spb)) % N
            lp = _onepole_response(damp_hz, nb, N)
            k = np.arange(nb)
            h = np.zeros(nb, dtype=np.complex128)
            g = 1.0
            for i in range(1, 12):
                g *= fb
                if g < 0.02:
                    break
                h += g * lp ** i * np.exp(-2j * np.pi * k * ((d * i) % N) / N)
            F += np.fft.rfft(b["dly"].astype(np.float64)) * h * wet
        if cfg.highpass:
            F *= 1.0 - _onepole_response(cfg.highpass, nb, N)
        if cfg.lowpass:
            F *= _onepole_response(cfg.lowpass, nb, N) ** 2
        return F

    def _duck_curve(self, depth: float, tau: float) -> np.ndarray:
        N = self.loop_len
        duck = np.ones(N)
        m = int(min(N, tau * 7 * SR))
        ramp = np.minimum(1.0, np.arange(m) / (0.003 * SR))
        seg = 1.0 - depth * np.exp(-np.arange(m) / (tau * SR)) * ramp
        for ev in self.events:
            if ev.inst == "kick":
                idx = (ev.t + np.arange(m)) % N
                duck[idx] = np.minimum(duck[idx], seg)
        return duck

    def render(self) -> dict[str, np.ndarray]:
        """Mix all events into three equal-length, loop-seamless, level-normalised layers."""
        N = self.loop_len
        out: dict[str, np.ndarray] = {}
        for layer in LAYERS:
            cfg = self.cfg[layer]
            y = np.fft.irfft(self._layer_spectrum_fx(layer, cfg, N), N)
            if cfg.pump:
                y *= self._duck_curve(*cfg.pump)
            out[layer] = y * cfg.gain
        full = sum(out.values())
        rms = float(np.sqrt(np.mean(full ** 2)))
        scale = self.loudness / max(rms, 1e-9)
        for layer in LAYERS:
            out[layer] = out[layer] * scale
        full = full * scale
        g = _limiter_gain(full, ceil=0.9)
        for layer in LAYERS:
            out[layer] = (out[layer] * g).astype(np.float32)
        self._cache.clear()
        return out

    # -- analysis aids -----------------------------------------------------------------------------
    def pitched_events(self) -> list[Event]:
        return [e for e in self.events if e.midi is not None and e.inst in ins.PITCHED]

    def pitch_class_weights(self, layers=LAYERS) -> np.ndarray:
        w = np.zeros(12)
        for e in self.pitched_events():
            if e.layer in layers:
                w[int(round(e.midi)) % 12] += e.dur * e.vel
        return w


def _limiter_gain(x: np.ndarray, ceil: float = 0.9, block: int = 64, reach: int = 4) -> np.ndarray:
    """Smooth, circular, look-ahead peak limiter gain curve (1.0 where the signal stays below ``ceil``).

    Per-block peaks -> required gain -> minimum over +-``reach`` blocks -> moving average over the same span (so the
    average at any peak block is still <= its required gain) -> held per block and lightly smoothed."""
    n = len(x)
    pad = (-n) % block
    a = np.abs(np.concatenate([x, x[:pad]])) if pad else np.abs(x)
    need = np.minimum(1.0, ceil / np.maximum(a.reshape(-1, block).max(axis=1), 1e-9))
    ext = np.concatenate([need[-reach:], need, need[:reach]])
    held = np.lib.stride_tricks.sliding_window_view(ext, 2 * reach + 1).min(axis=1)
    ext2 = np.concatenate([held[-reach:], held, held[:reach]])
    sm = np.convolve(ext2, np.ones(2 * reach + 1) / (2 * reach + 1), mode="valid")
    g = np.repeat(sm, block)
    g = np.convolve(np.concatenate([g[-block:], g, g[:block]]), np.ones(block) / block, mode="same")[block:-block][:n]
    peak = float(np.abs(x * g).max())
    return g * (ceil / peak) if peak > ceil else g


@dataclass
class TrackSpec:
    """Metadata recorded in the manifest next to the rendered layers."""
    name: str
    key: str
    bpm: float
    meter: str
    bars: int
    seed: int
    notes: str = ""
    extras: dict = field(default_factory=dict)
