"""The SHARDLIGHT score: ten original looping tracks, each rendered as three phase-locked layers.

Every track is a function ``build_<name>() -> Song`` (see ``music.py`` for the engine).  Notes are written in scale
*degrees*, so everything is in key by construction; chords are stacked in scale-thirds and voice-led.  A small
leitmotif of the Lens (``music.LENS_DEGREES``: up a fifth, step back, lift) is stated in every track on a different
instrument and in the track's own mode, so it recurs as the thread between the worlds.

Layer roles (the game fades them in with ``AudioManager.set_intensity``): ``bed`` always sounds (harmony, ambience,
and for some tracks the main theme), ``rhythm`` is pulse and percussion, ``lead`` is melody / tension.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import instruments as ins
from . import synth
from .music import P, Scale, Song, TrackSpec, euclid, hz
from .synth import SR


@dataclass(frozen=True)
class TrackDef:
    name: str
    build: Callable[[], Song]
    intent: str
    key: str
    meter: str
    scale_check: bool = True            # tonal-centre tracks: tests verify pitch-class adherence


# ---------------------------------------------------------------------------------------------- helpers
def _chords(song: Song, layer: str, inst: str, prog: list[int], *, size: int = 3, steps: float | None = None, vel: float = 0.5,
            lo: int = 54, hi: int = 77, bars=None, **kw) -> list[list[int]]:
    """Voice-led chord per bar (one chord per bar); returns the voicings."""
    steps = steps if steps is not None else song.steps_per_bar
    voicings, prev = [], None
    for bar in (bars if bars is not None else range(song.bars)):
        prev = song.chord_pad(layer, inst, bar, song.scale.chord(prog[bar % len(prog)], size), steps, prev, vel, lo, hi, **kw)
        voicings.append(prev)
    return voicings


def _arp(song: Song, layer: str, inst: str, bar: int, degs: list[int], spacing: float, length: float, vel: float,
         start: float = 0.0, **kw) -> None:
    for i, d in enumerate(degs):
        song.add(layer, inst, song.scale.midi(d), song.S(bar, start + i * spacing), length, vel, deg=d, **kw)


def _counter_line(song: Song, layer: str, inst: str, bars, prog: list[int], cells: list[tuple[float, float]], lo: int, hi: int,
                  vel: float = 0.5, strong: tuple[int, ...] = (0,), start: int | None = None, **kw) -> None:
    """Chord-aware wandering line: notes on ``strong`` cell indices land on a chord tone, the rest move by scale steps.
    Direction persists with some probability; bounces off [lo, hi] (degrees).  Uses the song RNG (deterministic)."""
    sc = song.scale
    cur = start if start is not None else (lo + hi) // 2
    direction = 1
    for bar in bars:
        root = prog[bar % len(prog)]
        tones = {(root + k) % sc.size for k in (0, 2, 4)}
        for ci, (st, ln) in enumerate(cells):
            if ci in strong:
                cands = [d for d in range(cur - 3, cur + 4) if d % sc.size in tones and lo <= d <= hi]
                if cands:
                    cands.sort(key=lambda d: (abs(d - cur), song.rng.random()))
                    cur = cands[0]
            else:
                if song.rng.random() < 0.3:
                    direction = -direction
                cur += direction * (1 if song.rng.random() < 0.8 else 2)
            if cur >= hi:
                cur, direction = hi, -1
            elif cur <= lo:
                cur, direction = lo, 1
            song.add(layer, inst, sc.midi(cur), song.S(bar, st), ln, vel * (1.0 if ci in strong else 0.85), deg=cur, **kw)


def _bass_walk(song: Song, layer: str, inst: str, prog: list[int], octave: int, vel: float, **kw) -> None:
    """Half-bar roots with an approach tone into the next bar's root (continuo-style)."""
    sc = song.scale
    half = song.steps_per_bar / 2
    for bar in range(song.bars):
        r, nxt = prog[bar % len(prog)], prog[(bar + 1) % len(prog)]
        song.add(layer, inst, sc.midi(r + octave), song.S(bar), half, vel, deg=r + octave, **kw)
        app = nxt + octave + (1 if nxt < r else -1)
        song.add(layer, inst, sc.midi(app), song.S(bar, half), half, vel * 0.8, deg=app, **kw)


# ---------------------------------------------------------------------------------------------- TITLE
def build_title() -> Song:
    s = Song("title", Scale.of("d4", "dorian"), bpm=60, beats=4, sub=4, bars=8, seed=101, loudness=0.13)
    prog = [0, 2, 3, 4, 6, 3, 0, 4]
    s.configure("bed", reverb=(3.8, 0.38, 0.5), delay=None, human=(8, 0.05), send=0.5)
    s.configure("rhythm", reverb=(2.4, 0.28, 0.55), human=(5, 0.07), gain=0.85)
    s.configure("lead", reverb=(3.4, 0.38, 0.5), delay=(0.75, 0.38, 0.22, 3200), human=(8, 0.05), gain=0.8)
    # bed: strings, sub root, then the main theme on brass with bell doublings
    _chords(s, "bed", "pad", prog, vel=0.55, lo=55, hi=74, release=2.0, attack=0.9)
    for bar, r in enumerate(prog):
        s.add("bed", "sub_bass", s.scale.midi(r - 14), s.S(bar), 15.5, 0.65, deg=r - 14, send=0.2)
    theme = {
        1: P("0:7:6 6:6:2 8:4:4 12:2:4"), 2: P("0:5:8 8:4:4 12:3:4"), 3: P("0:4:12 12:5:2 14:6:2"),
        4: P("0:8:8 8:7:4 12:6:4"), 5: P("0:7:8 8:5:4 12:7:4"), 6: P("0:7:12 12:6:2 14:5:2"), 7: P("0:4:10 10:3:2 12:2:2 14:1:2"),
    }
    s.lens("bed", "brass", 0, root=0, vel=0.62, release=0.5)
    s.lens("bed", "fm_bell", 0, root=7, vel=0.3, send=0.7)
    for bar, notes in theme.items():
        s.phrase("bed", "brass", bar, notes, vel=0.74, release=0.5)
        for st, deg, ln, v in notes:
            if st in (0, 8):
                s.add("bed", "fm_bell", s.scale.midi(deg + 7), s.S(bar, st), 8, 0.3 * v, deg=deg + 7, send=0.7)
    # rhythm: timpani heartbeat, soft toms, shaker and swells
    for bar in range(s.bars):
        s.hit("rhythm", "timpani", s.S(bar), 0.9 if bar % 4 == 0 else 0.7, midi=38 if prog[bar] in (0, 4) else 43)
        if bar < 4:
            s.hit("rhythm", "tom", s.S(bar, 8), 0.4, freq=62.0)
        else:
            s.pattern("rhythm", "shaker", [bar], "x.o.x.o.x.o.x.o.", 0.55)
            s.hit("rhythm", "tom", s.S(bar, 8), 0.55, freq=70.0)
            s.hit("rhythm", "tom", s.S(bar, 12), 0.45, freq=82.0)
    for st, v in ((12, 0.5), (14, 0.7), (15, 0.9)):
        s.hit("rhythm", "timpani", s.S(3, st), v, midi=45)
        s.hit("rhythm", "timpani", s.S(7, st), v, midi=45)
    s.hit("rhythm", "cymbal", s.S(3, 4), 0.8, swell=3.0, length=3.2)
    s.hit("rhythm", "cymbal", s.S(4, 0), 0.7, length=3.0)
    s.hit("rhythm", "cymbal", s.S(7, 4), 0.8, swell=3.0, length=3.2)
    s.hit("rhythm", "gong", s.S(0, 0), 0.45, freq=73.4, length=6.0)
    # lead: choir swell, harp arpeggios, high echo of the theme
    for bar, r in enumerate(prog):
        lift = 7 if bar >= 4 else 0
        _arp(s, "lead", "pluck", bar, [r + lift + d for d in (0, 2, 4, 2, 0, 2, 4, 7)], 2, 6, 0.42, kind="harp")
    prev = None
    for bar in range(2, 8):
        prev = s.chord_pad("lead", "choir", bar, s.scale.chord(prog[bar]), 16, prev, 0.5, 62, 82, vowel="ah", attack=1.0, release=1.6)
    s.lens("lead", "bell", 6, step=8, root=7, vel=0.45, kind="glass", send=0.8)
    return s


# ---------------------------------------------------------------------------------------------- HUB
def build_hub() -> Song:
    s = Song("hub", Scale.of("f4", "lydian"), bpm=90, beats=3, sub=2, bars=16, seed=202, loudness=0.12)
    prog = [0, 1, 0, 4, 5, 1, 0, 4, 0, 2, 5, 1, 0, 1, 4, 0]
    s.configure("bed", reverb=(3.2, 0.36, 0.45), human=(10, 0.05), send=0.55)
    s.configure("rhythm", reverb=(1.8, 0.22, 0.5), human=(7, 0.07), gain=0.7)
    s.configure("lead", reverb=(2.8, 0.34, 0.5), delay=(1.0, 0.35, 0.2, 3000), human=(10, 0.05), gain=0.8)
    _chords(s, "bed", "pad", prog, vel=0.5, lo=53, hi=72, slope=(3.0, 1.8), release=1.6, attack=0.8)
    for bar, r in enumerate(prog):
        s.add("bed", "sub_bass", s.scale.midi(r - 14), s.S(bar), 4, 0.6, deg=r - 14, send=0.2)
        s.add("bed", "sub_bass", s.scale.midi(r - 10), s.S(bar, 4), 2, 0.35, deg=r - 10, send=0.2)
    theme = {
        0: P("0:2:4 4:4:2"), 1: P("0:5:4 4:3:2"), 2: P("0:4:6"), 3: P("0:6:4 4:4:2"),
        4: P("0:5:4 4:7:2"), 5: P("0:5:4 4:3:2"), 6: P("0:4:4 4:2:2"), 7: P("0:6:6"),
        8: P("0:7:4 4:4:2"), 9: P("0:6:4 4:4:2"), 10: P("0:5:4 4:2:2"), 11: P("0:3:4 4:5:2"),
        12: P("0:7:6"), 13: P("0:5:4 4:3:2"), 14: P("0:4:4 4:6:2"), 15: P("0:4:3 3:2:3"),
    }
    for bar, notes in theme.items():
        s.phrase("bed", "brass", bar, notes, vel=0.62, attack=0.14, release=0.45, dark=0.4)
        for st, deg, ln, v in notes:
            if st == 0:
                s.add("bed", "bell", s.scale.midi(deg + 7), s.S(bar), 6, 0.32 * v, deg=deg + 7, kind="glass", send=0.75)
    s.lens("bed", "bell", 6, step=0, root=0, vel=0.4, kind="glass", send=0.8)
    for bar in (0, 8):                       # bell arpeggio of the chord on the downbeat of each phrase
        _arp(s, "bed", "bell", bar, [prog[bar] + d for d in (7, 9, 11)], 2, 6, 0.22, kind="glass", send=0.8)
    # rhythm: very soft waltz
    for bar in range(s.bars):
        s.hit("rhythm", "tom", s.S(bar), 0.5, freq=87.0, tau=0.3)
        s.pattern("rhythm", "shaker", [bar], "X.o.o.", 0.55)
        if bar % 2 == 1:
            s.hit("rhythm", "woodblock", s.S(bar, 4), 0.28, freq=980.0)
    s.pattern("rhythm", "brush", range(8, 16), "..x...", 0.6)
    # lead: flute answering, harp
    _counter_line(s, "lead", "flute", range(4, 16), prog, [(0, 2), (2, 1), (3, 1), (4, 2)], 4, 12, vel=0.5, start=7, vib=14.0, breath=0.1)
    for bar, r in enumerate(prog):
        if bar >= 2:
            _arp(s, "lead", "pluck", bar, [r + d for d in (0, 2, 4, 6, 4, 2)], 1, 3, 0.3, kind="harp")
    return s


# ---------------------------------------------------------------------------------------------- CINDER
def build_cinder() -> Song:
    s = Song("cinder", Scale.of("e3", "phrygian"), bpm=120, beats=4, sub=4, bars=16, seed=303, loudness=0.15)
    prog = [0, 0, 1, 0, 0, 1, 0, 6, 5, 6, 1, 0, 3, 1, 6, 0]
    s.configure("bed", reverb=(2.8, 0.34, 0.45), delay=(0.75, 0.4, 0.28, 3600), human=(6, 0.06))
    s.configure("rhythm", reverb=(1.5, 0.18, 0.5), human=(3, 0.07), gain=0.95)
    s.configure("lead", reverb=(2.0, 0.24, 0.5), delay=(0.75, 0.3, 0.18, 3000), human=(4, 0.05), gain=0.8)
    for bar in range(16):
        sec = bar // 8
        _chords(s, "bed", "pad", prog, vel=0.5 + 0.1 * sec, lo=40, hi=64, bars=[bar], slope=(3.4 - 0.8 * sec, 2.0 - 0.6 * sec),
                sweep=3.0, release=1.2, attack=0.5)
    for bar, r in enumerate(prog):
        s.add("bed", "sub_bass", s.scale.midi(r - 7), s.S(bar), 15, 0.7, deg=r - 7, send=0.15)
    ember = [0, 2, 4, 5, 6]                  # pentatonic-ish subset of the mode, high register
    for bar in range(16):
        n_notes = 1 + bar // 3
        for _ in range(n_notes):
            deg = 14 + int(s.rng.choice(ember)) + 7 * int(s.rng.integers(0, 2)) - 7
            s.add("bed", "fm_bell", s.scale.midi(deg), s.S(bar, float(s.rng.choice([2, 6, 10, 14, 3, 11]))), 10, 0.22 + 0.02 * bar,
                  deg=deg, ratio=3.5, index=3.0, send=0.7, dsend=0.6)
    s.lens("bed", "fm_bell", 7, step=8, root=14, vel=0.45, send=0.8, dsend=0.4)
    s.lens("bed", "fm_bell", 15, step=8, root=14, vel=0.5, send=0.8, dsend=0.4)
    # rhythm: build
    for bar in range(16):
        if bar < 4:
            s.pattern("rhythm", "kick", [bar], "X... .... x... ....", 0.8)
        elif bar < 8:
            s.pattern("rhythm", "kick", [bar], "X... ..x. X... ..x.", 0.85)
        else:
            s.pattern("rhythm", "kick", [bar], "X..x ..x. X.x. ..x.", 0.9)
        if bar >= 4:
            s.pattern("rhythm", "snare", [bar], "....X.......X...", 0.8, send=0.55, tone=170.0)
        if bar >= 2:
            s.pattern("rhythm", "hat", [bar], "x.x.x.x.x.x.x.x." if bar < 8 else "xoxoxoxoxoxoxoxo", 0.5)
        if bar >= 8:
            s.hit("rhythm", "hat", s.S(bar, 14), 0.6, open_=True)
        s.hit("rhythm", "taiko", s.S(bar), 0.85 if bar % 4 == 0 else 0.55, freq=62.0)
        if bar % 4 == 3:
            for i, st in enumerate((12, 13, 14, 15)):
                s.hit("rhythm", "tom", s.S(bar, st), 0.55 + 0.1 * i, freq=150.0 - 22 * i)
        # saw bass pulse
        r = prog[bar]
        for st in range(0, 16, 2):
            if bar < 2 and st % 4:
                continue
            acc = 0.9 if st % 4 == 0 else 0.6
            s.add("rhythm", "saw_bass", s.scale.midi(r - 7), s.S(bar, st), 1.7, acc * (0.55 + 0.03 * min(bar, 10)), deg=r - 7, send=0.1)
    s.hit("rhythm", "cymbal", s.S(8, 0), 0.7, length=3.0)
    s.hit("rhythm", "cymbal", s.S(0, 0), 0.5, length=3.0)
    s.hit("rhythm", "riser", s.S(6, 0), 0.7, length=s.dur_s(32))
    # lead
    riff = P("0:7:3 3:8:1 4:7:2 6:11:2 8:7:3 11:8:1 12:7:2 14:6:2")
    sparse = P("0:7:6 8:8:2 12:7:4")
    for bar in range(16):
        r = prog[bar]
        if bar < 4:
            s.phrase("lead", "saw_lead", bar, sparse, transpose=r, vel=0.55, voices=2, drive=1.6, vib=6.0)
        elif bar < 8:
            s.phrase("lead", "saw_lead", bar, riff[:5] if bar % 2 else riff, transpose=r, vel=0.6, voices=3, drive=2.0)
        else:
            s.phrase("lead", "saw_lead", bar, riff, transpose=r, vel=0.7, voices=3, drive=2.4)
        if bar >= 12:
            for st in (0, 10):
                for d in s.scale.chord(r + 7):
                    s.add("lead", "brass", s.scale.midi(d), s.S(bar, st), 3, 0.35, deg=d, dark=0.5)
    s.lens("lead", "saw_lead", 3, step=0, root=7, vel=0.55, voices=2, drive=1.6)
    return s


# ---------------------------------------------------------------------------------------------- VERDANT
def build_verdant() -> Song:
    s = Song("verdant", Scale.of("g4", "mixolydian"), bpm=60, beats=2, sub=3, bars=16, seed=404, loudness=0.12)
    prog = [0, 6, 3, 0, 0, 6, 3, 4, 5, 3, 0, 6, 0, 6, 3, 4]
    s.configure("bed", reverb=(2.4, 0.3, 0.5), human=(12, 0.08), send=0.4)
    s.configure("rhythm", reverb=(1.4, 0.2, 0.5), human=(9, 0.09), gain=0.8)
    s.configure("lead", reverb=(2.6, 0.32, 0.5), delay=(1.0, 0.3, 0.16, 2800), human=(12, 0.07), gain=0.85)
    for bar, r in enumerate(prog):
        _arp(s, "bed", "pluck", bar, [r - 7 + d for d in (0, 2, 4, 7, 4, 2)], 1, 4.5, 0.46, kind="guitar")
    _chords(s, "bed", "pad", prog, vel=0.3, lo=45, hi=64, voices=2, slope=(3.0, 2.0), release=1.4, attack=0.9)
    s.lens("bed", "pluck", 7, step=0, root=7, vel=0.5, kind="kalimba", send=0.7)
    s.lens("bed", "pluck", 15, step=0, root=7, vel=0.5, kind="kalimba", send=0.7)
    # rhythm: frame drum + shaker + pizzicato bass, 6/8
    for bar, r in enumerate(prog):
        s.hit("rhythm", "tom", s.S(bar, 0), 0.65, freq=100.0, tau=0.16, slap=0.45)
        s.hit("rhythm", "tom", s.S(bar, 3), 0.5, freq=100.0, tau=0.16, slap=0.45)
        s.pattern("rhythm", "shaker", [bar], "o.xo.x", 0.55)
        s.add("rhythm", "pluck", s.scale.midi(r - 14), s.S(bar, 0), 2.5, 0.7, deg=r - 14, kind="pizz")
        s.add("rhythm", "pluck", s.scale.midi(r - 14 + 4), s.S(bar, 3), 2.5, 0.5, deg=r - 10, kind="pizz")
        if bar % 2:
            s.hit("rhythm", "woodblock", s.S(bar, 5), 0.3, freq=1100.0)
    # lead: folk flute
    tune = {
        0: P("0:2:3 3:4:2 5:2:1"), 1: P("0:3:3 3:1:3"), 2: P("0:5:3 3:4:2 5:3:1"), 3: P("0:2:6"),
        4: P("0:2:3 3:4:2 5:5:1"), 5: P("0:3:3 3:5:3"), 6: P("0:4:3 3:3:2 5:2:1"), 7: P("0:4:4 4:1:2"),
        8: P("0:5:3 3:7:3"), 9: P("0:7:3 3:5:3"), 10: P("0:4:3 3:7:3"), 11: P("0:6:6"),
        12: P("0:2:3 3:4:2 5:2:1"), 13: P("0:3:3 3:1:3"), 14: P("0:5:3 3:4:3"), 15: P("0:1:6"),
    }
    for bar, notes in tune.items():
        s.phrase("lead", "flute", bar, notes, vel=0.75, breath=0.13, vib=16.0)
    for bar in range(8, 16):
        s.add("lead", "pluck", s.scale.midi(prog[bar] + 7), s.S(bar, 3), 3, 0.3, deg=prog[bar] + 7, kind="harp", send=0.6)
    return s


# ---------------------------------------------------------------------------------------------- UMBRA
def build_umbra() -> Song:
    s = Song("umbra", Scale.of("f3", "locrian"), bpm=75, beats=5, sub=4, bars=8, seed=505, loudness=0.065)
    s.configure("bed", reverb=(5.0, 0.5, 0.35), human=(0, 0.0), highpass=18.0, send=0.5)
    s.configure("rhythm", reverb=(4.0, 0.45, 0.4), human=(15, 0.1), gain=0.9, send=0.8)
    s.configure("lead", reverb=(6.0, 0.55, 0.35), delay=(1.5, 0.45, 0.25, 2400), human=(25, 0.1), gain=0.9, send=0.8)
    N = s.loop_len
    t = np.arange(N) / SR
    T = N / SR
    # bed: loop-periodic drone cluster.  Every oscillator is snapped to a whole number of cycles per loop, as is every
    # slow amplitude modulation, so the drone is continuous across the loop point by construction.
    def am(cycles: int, phase: float, depth: float = 0.5) -> np.ndarray:
        return 1 - depth + depth * np.sin(2 * np.pi * cycles * t / T + phase)
    f_root = s.snap_freq(hz(29))             # F1
    f_oct = s.snap_freq(hz(41))              # F2
    f_cluster = s.snap_freq(hz(42))          # Gb2: minor second above F2 -> slow beating
    f_tri = s.snap_freq(hz(47))              # B2: tritone above F2
    low = ins.drone_tone(f_root, N, 1, slope=1.4) * 1.0
    mid = (ins.drone_tone(f_oct, N, 2, slope=2.0) * am(2, 0.0, 0.45)
           + ins.drone_tone(f_cluster, N, 3, slope=2.2) * am(3, 1.7, 0.5) * 0.7
           + ins.drone_tone(f_tri, N, 4, slope=2.6) * am(5, 3.1, 0.6) * 0.25)
    air = synth.shaped_noise(s.seconds, 77, 250, 1100) * am(2, 2.0, 0.8) * 0.06
    s.raw("bed", low * 0.30 + mid * 0.22 + air, 0, 1.0, send=0.3, inst="drone")
    s.raw("bed", synth.shaped_noise(s.seconds, 78, 60, 220, tilt_db_oct=-6) * am(1, 0.5, 0.9) * 0.18, 0, 1.0, send=0.0, inst="rumble")
    # rhythm: sub heartbeat (lub-dub) with gaps, the stopped clock
    for bar in range(8):
        if bar in (3, 7):
            continue
        s.hit("rhythm", "tom", s.S(bar, 0), 0.8, freq=48.0, tau=0.22, slap=0.05)
        s.hit("rhythm", "tom", s.S(bar, 3), 0.5, freq=44.0, tau=0.2, slap=0.03)
        if bar in (1, 5):
            s.hit("rhythm", "tom", s.S(bar, 10), 0.6, freq=48.0, tau=0.22, slap=0.05)
            s.hit("rhythm", "tom", s.S(bar, 13), 0.4, freq=44.0, tau=0.2, slap=0.03)
    for bar in range(8):
        beats = range(5) if bar != 6 else (0, 1, 3, 4)        # the clock skips a beat in bar 6
        for b in beats:
            if bar in (2, 3, 6, 7) or b % 2 == 0:
                s.hit("rhythm", "tick", s.S(bar, b * 4), 0.25 if b else 0.4, freq=2400.0 if b % 2 else 3100.0, send=0.9)
    s.hit("rhythm", "boom", s.S(0, 0), 0.5, freq=34.0, length=4.0)
    s.hit("rhythm", "gong", s.S(4, 0), 0.25, freq=58.0, length=6.5)
    # lead: fragments of the Lens motif (tritone included), cluster voices, risers
    s.lens("lead", "bell", 1, step=6, root=14, vel=0.5, kind="glass", send=0.9, dsend=0.6, stretch=1.3)
    s.lens("lead", "bell", 5, step=2, root=12, vel=0.45, kind="glass", send=0.9, dsend=0.6, stretch=1.6)
    for st, deg in ((8, 21), (13, 22), (18, 19)):
        s.add("lead", "bell", s.scale.midi(deg), s.S(2, st), 14, 0.3, deg=deg, kind="glass", send=0.9, dsend=0.7)
    prev = None
    for bar, degs in ((4, [14, 15]), (6, [17, 18])):
        for d in degs:
            s.add("lead", "choir", s.scale.midi(d), s.S(bar), s.steps_per_bar * 1.6, 0.4, deg=d, vowel="oo", voices=3, attack=2.2,
                  release=2.0, spread=30.0, send=0.9)
    s.hit("lead", "riser", s.S(3, 0), 0.8, length=s.dur_s(s.steps_per_bar))
    s.hit("lead", "riser", s.S(6, 0), 0.9, length=s.dur_s(s.steps_per_bar * 2))
    s.hit("lead", "boom", s.S(7, 0), 0.0001, length=0.1)    # (inaudible placeholder removed below)
    s.events.pop()
    return s


# ---------------------------------------------------------------------------------------------- SLIPSTREAM
def build_slipstream() -> Song:
    s = Song("slipstream", Scale.of("a3", "ionian"), bpm=150, beats=4, sub=4, bars=20, seed=606, loudness=0.15)
    prog = [0, 4, 5, 3] * 2 + [3, 4, 2, 5] + [3, 4, 0, 4] + [0, 4, 5, 3]
    s.configure("bed", reverb=(1.8, 0.24, 0.5), human=(1, 0.03), pump=(0.6, 0.11), delay=(0.75, 0.3, 0.14, 4500))
    s.configure("rhythm", reverb=(1.1, 0.14, 0.5), human=(1, 0.04), gain=0.95, send=0.2)
    s.configure("lead", reverb=(1.6, 0.22, 0.5), delay=(0.75, 0.38, 0.28, 5200), human=(1, 0.03), gain=0.8)
    _chords(s, "bed", "pad", prog, vel=0.5, lo=57, hi=76, voices=3, detune=15.0, slope=(1.7, 1.1), sweep=0.8, attack=0.05, release=0.3, steps=15.5)
    for bar, r in enumerate(prog):
        for st in (2, 6, 10, 14):
            s.add("bed", "saw_bass", s.scale.midi(r - 7), s.S(bar, st), 1.6, 0.8, deg=r - 7, detune=9.0, send=0.1)
        _arp(s, "bed", "synth_pluck", bar, [r + d for d in (0, 2, 4, 2) * 4], 1, 1.4, 0.2, bright=(0.6, 2.4), decay=0.09, send=0.3)
    # rhythm
    for bar in range(20):
        if bar >= 1:
            s.pattern("rhythm", "kick", [bar], "X...X...X...X...", 0.9, level=0.9)
        else:
            s.pattern("rhythm", "kick", [bar], "X.......X.......", 0.9)
        if bar >= 2:
            s.pattern("rhythm", "clap", [bar], "....X.......X...", 0.8, send=0.35)
        s.pattern("rhythm", "hat", [bar], "..x...x...x...x.", 0.55, open_=True, tau=0.07)
        s.pattern("rhythm", "hat", [bar], "o.o.o.o.o.o.o.o.", 0.35, offset=0)
        if bar >= 4:
            s.pattern("rhythm", "shaker", [bar], "xoxoxoxoxoxoxoxo", 0.4, tau=0.03)
        if bar % 4 == 3 and bar > 2:
            for i in range(8):
                s.hit("rhythm", "snare", s.S(bar, 8 + i), 0.35 + 0.08 * i, tone=210.0, noise_tau=0.07)
    for bar in (0, 4, 8, 12, 16):
        s.hit("rhythm", "cymbal", s.S(bar, 0), 0.7, length=2.0)
    s.hit("rhythm", "riser", s.S(6, 0), 0.7, length=s.dur_s(32))
    s.hit("rhythm", "riser", s.S(18, 0), 0.7, length=s.dur_s(32))
    # lead
    for bar, r in enumerate(prog):
        if bar < 2:
            continue
        seq = [0, 1, 2, 3, 2, 1, 0, 1] * 2 if bar % 2 == 0 else [0, 2, 1, 3, 2, 4, 3, 2] * 2
        degs = [r + 7 + [0, 2, 4, 7, 9][i % 5] if False else r + 7 + (0, 2, 4, 7, 9)[i % 5] for i in seq]
        _arp(s, "lead", "synth_pluck", bar, degs, 1, 1.2, 0.34, bright=(0.7, 2.8), decay=0.12, voices=2, detune=11.0, dsend=0.5, send=0.3)
    hook = {
        8: P("0:10:3 3:12:3 6:10:2 8:14:4 12:12:2 14:11:2"), 9: P("0:11:3 3:13:3 6:11:2 8:13:4 12:11:2 14:9:2"),
        10: P("0:9:3 3:11:3 6:9:2 8:13:4 12:11:2 14:9:2"), 11: P("0:12:6 6:11:2 8:9:4 12:7:4"),
        16: P("0:14:6 6:12:2 8:11:4 12:9:4"), 17: P("0:13:6 6:11:2 8:11:4 12:8:4"), 18: P("0:12:6 6:12:2 8:11:4 12:10:4"),
        19: P("0:11:6 6:9:2 8:7:4 12:7:4"),
    }
    for bar, notes in hook.items():
        s.phrase("lead", "saw_lead", bar, notes, vel=0.55, voices=3, detune=12.0, drive=1.5, vib=5.0)
    s.lens("lead", "saw_lead", 12, step=0, root=7, vel=0.6, stretch=0.5, voices=3, drive=1.5)
    s.lens("lead", "saw_lead", 14, step=0, root=9, vel=0.6, stretch=0.5, voices=3, drive=1.5)
    return s


# ---------------------------------------------------------------------------------------------- CONCORD
def build_concord() -> Song:
    s = Song("concord", Scale.of("d4", "ionian"), bpm=90, beats=2, sub=4, bars=24, seed=707, loudness=0.13)
    prog = [0, 4, 5, 2, 3, 0, 3, 4, 0, 4, 5, 2, 3, 0, 4, 0, 5, 3, 4, 0, 3, 1, 4, 4]
    s.configure("bed", reverb=(2.0, 0.26, 0.5), human=(6, 0.06), send=0.35)
    s.configure("rhythm", reverb=(1.5, 0.2, 0.5), human=(3, 0.08), gain=0.85, send=0.3)
    s.configure("lead", reverb=(2.2, 0.28, 0.5), human=(7, 0.05), gain=0.8, send=0.4)
    _bass_walk(s, "bed", "pluck", prog, -7, 0.7, kind="harpsichord")
    for bar, r in enumerate(prog):
        _arp(s, "bed", "pluck", bar, [r + (0, 2, 4, 2)[i] for i in range(4)], 2, 3.5, 0.34, kind="harpsichord")
    _chords(s, "bed", "organ", prog, vel=0.3, lo=57, hi=76, release=0.12, attack=0.04, steps=7.8, levels=(0.4, 1.0, 0.3, 0.5, 0.1, 0.1, 0, 0, 0))
    # rhythm: military snare, drum, timpani on phrase heads
    for bar in range(24):
        s.pattern("rhythm", "snare", [bar], "X.oxX.ox" if bar % 4 != 3 else "oooxxxXX", 0.7, tone=230.0, noise_tau=0.06, send=0.3,
                  band=(2000, 8000), level=0.5)
        s.hit("rhythm", "kick", s.S(bar, 0), 0.7, f0=95.0, f1=58.0, tau=0.12, click=0.15)
        if bar % 2:
            s.hit("rhythm", "kick", s.S(bar, 4), 0.45, f0=95.0, f1=58.0, tau=0.12, click=0.15)
        if bar % 4 == 0:
            s.hit("rhythm", "timpani", s.S(bar, 0), 0.8, midi=38 + (5 if prog[bar] in (3, 4) else 0))
            s.hit("rhythm", "cymbal", s.S(bar, 0), 0.5, length=1.8)
    # lead: two imitative voices built from chord-relative cells; the alto answers the soprano two bars later an octave down
    cells = {"A": [0, 2, 4, 2], "B": [4, 3, 2, 1], "C": [2, 4, 3, 4], "D": [0, 1, 2, 4], "E": [4, 2, 0, 2]}
    order = ["A", "B", "C", "D", "A", "E", "C", "D", "A", "B", "C", "D", "B", "A", "D", "E", "C", "B", "D", "A", "E", "C", "B", "A"]
    for bar in range(24):
        r = prog[bar]
        _arp(s, "lead", "organ", bar, [r + 7 + c for c in cells[order[bar]]], 2, 2.0, 0.42, levels=(0, 1.0, 0.0, 0.7, 0, 0.25, 0, 0, 0))
        if bar >= 2:
            _arp(s, "lead", "pluck", bar, [r + c for c in cells[order[bar - 2]]], 2, 3.0, 0.5, kind="lute")
    s.lens("lead", "organ", 12, step=0, root=7, stretch=0.5, vel=0.5, levels=(0, 1.0, 0.0, 0.7, 0, 0.25, 0, 0, 0))
    return s


# ---------------------------------------------------------------------------------------------- TERRACE
def build_terrace() -> Song:
    s = Song("terrace", Scale.of("eb3", "ionian"), bpm=90, beats=4, sub=4, bars=12, seed=808, loudness=0.12)
    prog = [0, 4, 5, 3, 0, 4, 3, 4, 5, 3, 0, 4]
    s.configure("bed", reverb=(2.4, 0.28, 0.5), human=(10, 0.07), send=0.4)
    s.configure("rhythm", reverb=(1.4, 0.2, 0.5), human=(8, 0.09), gain=0.8)
    s.configure("lead", reverb=(2.6, 0.3, 0.5), delay=(1.0, 0.3, 0.14, 2800), human=(10, 0.06), gain=0.85)
    for bar, r in enumerate(prog):
        _arp(s, "bed", "pluck", bar, [r - 7 + d for d in (0, 4, 7, 4, 2, 4, 7, 4)], 2, 3.5, 0.4, kind="guitar")
        s.add("bed", "sub_bass", s.scale.midi(r - 14), s.S(bar, 0), 7.5, 0.6, deg=r - 14, send=0.2)
        s.add("bed", "sub_bass", s.scale.midi(r - 10), s.S(bar, 8), 7.5, 0.45, deg=r - 10, send=0.2)
    _chords(s, "bed", "pad", prog, vel=0.42, lo=52, hi=71, slope=(3.0, 2.0), release=1.4, attack=0.8)
    s.lens("bed", "pluck", 3, step=8, root=7, vel=0.45, kind="kalimba", send=0.7)
    s.lens("bed", "pluck", 7, step=8, root=7, vel=0.45, kind="kalimba", send=0.7)
    for bar in range(12):
        s.hit("rhythm", "tom", s.S(bar, 0), 0.55, freq=72.0, tau=0.24)
        s.hit("rhythm", "tom", s.S(bar, 8), 0.45, freq=72.0, tau=0.24)
        s.hit("rhythm", "tom", s.S(bar, 10), 0.3, freq=150.0, tau=0.12)
        s.pattern("rhythm", "shaker", [bar], "x.o.x.o.x.o.x.o.", 0.55)
        s.hit("rhythm", "woodblock", s.S(bar, 4), 0.4, freq=880.0)
        s.hit("rhythm", "woodblock", s.S(bar, 12), 0.4, freq=880.0)
    for st, v in ((12, 0.4), (13, 0.45), (14, 0.5), (15, 0.6)):
        s.hit("rhythm", "tom", s.S(11, st), v, freq=110.0 + (st - 12) * 12, tau=0.14)
    tune = {
        0: P("0:9:4 4:7:2 6:9:2 8:11:6 14:10:2"), 1: P("0:8:6 6:9:2 8:11:8"), 2: P("0:9:3 3:7:1 4:5:4 8:7:8"), 3: P("0:7:6 6:8:2 8:10:8"),
        4: P("0:9:4 4:7:2 6:9:2 8:11:6 14:10:2"), 5: P("0:8:6 6:9:2 8:11:8"), 6: P("0:10:3 3:12:1 4:10:4 8:7:8"), 7: P("0:8:4 4:11:4 8:8:8"),
        8: P("0:12:6 6:11:2 8:9:8"), 9: P("0:10:4 4:12:4 8:10:8"), 10: P("0:11:4 4:9:4 8:7:8"), 11: P("0:8:6 6:6:2 8:8:8"),
    }
    for bar, notes in tune.items():
        s.phrase("lead", "flute", bar, notes, vel=0.8, breath=0.1, vib=12.0)
        s.phrase("lead", "fm_bell", bar, [n for n in notes if n[0] == 0], transpose=7, vel=0.22, send=0.7)
    return s


# ---------------------------------------------------------------------------------------------- MASKS
def build_masks() -> Song:
    s = Song("masks", Scale.of("d4", "in_sen"), bpm=90, beats=6, sub=4, bars=8, seed=909, loudness=0.14)
    s.configure("bed", reverb=(3.0, 0.34, 0.4), human=(12, 0.08), send=0.5)
    s.configure("rhythm", reverb=(2.4, 0.3, 0.45), human=(4, 0.06), gain=1.0, send=0.5)
    s.configure("lead", reverb=(3.0, 0.34, 0.45), delay=(1.5, 0.35, 0.18, 2600), human=(15, 0.06), gain=0.85)
    for bar in range(8):
        for d, v in ((-10, 0.7), (-7, 0.45)):
            s.add("bed", "pad", s.scale.midi(d), s.S(bar), 23.5, v, deg=d, voices=2, detune=6.0, slope=(3.4, 2.2), sweep=4.0,
                  attack=2.0, release=2.0, send=0.35)
    koto = {0: [(12, 4), (18, 3)], 1: [(4, 2), (10, 3), (16, 4)], 2: [(2, 3), (8, 2)], 4: [(6, 4), (12, 3), (20, 2)], 5: [(2, 5), (9, 3)],
            6: [(14, 3), (20, 2)], 7: [(8, 1), (14, 2)]}
    for bar, evs in koto.items():
        for st, deg in evs:
            s.add("bed", "pluck", s.scale.midi(deg), s.S(bar, st), 10, 0.5, deg=deg, kind="lute", tau_scale=1.4, send=0.6)
    s.lens("bed", "pluck", 5, step=14, root=0, vel=0.55, kind="lute", send=0.7)
    # rhythm: taiko with long silences
    hits = {
        0: [(0, "t", 1.0, 70), (12, "r", 0.5, 0), (16, "t", 0.7, 95), (20, "r", 0.4, 0)],
        1: [(0, "t", 0.9, 70), (6, "r", 0.4, 0), (8, "t", 0.6, 95)],
        2: [(0, "t", 1.0, 70), (4, "t", 0.6, 95), (8, "t", 0.6, 95), (12, "t", 0.8, 70), (16, "t", 0.4, 95), (18, "t", 0.5, 95),
            (20, "t", 0.6, 95), (22, "t", 0.7, 95)],
        3: [(0, "t", 0.5, 70), (20, "r", 0.5, 0)],
        4: [(0, "t", 1.0, 62), (12, "t", 0.7, 90), (16, "r", 0.5, 0), (18, "r", 0.4, 0)],
        5: [(0, "t", 0.9, 70), (3, "r", 0.5, 0), (6, "t", 0.6, 95), (12, "t", 0.8, 70), (14, "r", 0.4, 0), (18, "t", 1.0, 62)],
        6: [(0, "t", 1.0, 70), (8, "t", 0.7, 95), (12, "t", 0.7, 95), (16, "t", 0.4, 95), (17, "t", 0.45, 95), (18, "t", 0.5, 95),
            (19, "t", 0.55, 95), (20, "t", 0.6, 95), (21, "t", 0.7, 95), (22, "t", 0.8, 95), (23, "t", 0.9, 95)],
        7: [(0, "t", 0.8, 70), (14, "r", 0.3, 0)],
    }
    for bar, evs in hits.items():
        for st, kind, v, f in evs:
            if kind == "t":
                s.hit("rhythm", "taiko", s.S(bar, st), v, freq=float(f), hard=0.9 + 0.3 * v)
            else:
                s.hit("rhythm", "rim", s.S(bar, st), v, freq=1500.0 + 70 * (st % 5))
    s.hit("rhythm", "gong", s.S(0, 0), 0.5, freq=73.4, length=6.5)
    s.hit("rhythm", "gong", s.S(4, 0), 0.4, freq=69.3, length=6.0)
    # lead: shakuhachi-like flute in the five-note scale
    mel = {
        0: P("4:3:12 16:2:8"), 1: P("0:3:6 6:4:6 14:3:10"), 2: P("6:5:10 16:4:8"), 3: P("0:3:20"),
        4: P("0:2:6 6:3:6 12:4:6 18:5:6"), 5: P("6:6:8 14:5:10"), 6: P("0:4:10 12:3:6 18:2:6"), 7: P("0:1:24"),
    }
    for bar, notes in mel.items():
        s.phrase("lead", "flute", bar, notes, vel=0.8, breath=0.26, vib=22.0, attack=0.12, release=0.3, send=0.6)
    s.lens("lead", "fm_bell", 3, step=0, root=7, vel=0.0, send=0.0)      # placeholder replaced below
    s.events = [e for e in s.events if not (e.tag == "lens" and e.layer == "lead")]
    s.bufs["lead"]["dry"][:] = s.bufs["lead"]["dry"] * 0                    # (rebuilt below)
    for bar, notes in mel.items():
        s.phrase("lead", "flute", bar, notes, vel=0.8, breath=0.26, vib=22.0, attack=0.12, release=0.3, send=0.6)
    s.lens("lead", "fm_bell", 4, step=2, root=7, vel=0.4, send=0.8, stretch=1.4)
    return s


# ---------------------------------------------------------------------------------------------- ORRERY
def build_orrery() -> Song:
    s = Song("orrery", Scale.of("a3", "lydian"), bpm=105, beats=7, sub=2, bars=8, seed=1001, loudness=0.12)
    prog = [0, 1, 5, 1, 0, 4, 5, 1]
    s.configure("bed", reverb=(5.0, 0.45, 0.4), human=(10, 0.05), send=0.6)
    s.configure("rhythm", reverb=(2.0, 0.22, 0.5), human=(4, 0.05), gain=0.8)
    s.configure("lead", reverb=(4.0, 0.4, 0.45), delay=(1.5, 0.4, 0.22, 4000), human=(5, 0.05), gain=0.85)
    _chords(s, "bed", "glass_pad", prog, size=4, vel=0.5, lo=57, hi=82, attack=1.4, release=2.4, steps=13.5)
    for bar, r in enumerate(prog):
        s.add("bed", "sub_bass", s.scale.midi(r - 14), s.S(bar), 13.5, 0.55, deg=r - 14, send=0.2)
    for bar in range(4, 8):
        prev = None
        s.chord_pad("bed", "choir", bar, s.scale.chord(prog[bar]), 14, prev, 0.3, 60, 80, vowel="oo", attack=2.0, release=2.0)
    for bar in range(8):                       # music-box sparkle
        for st in (3, 7, 10):
            deg = 14 + prog[bar] + (0, 2, 4)[(bar + st) % 3]
            s.add("bed", "bell", s.scale.midi(deg), s.S(bar, st), 10, 0.18, deg=deg, kind="glass", send=0.9, dsend=0.6)
    # rhythm: clockwork 4+3
    for bar, r in enumerate(prog):
        for st in range(14):
            acc = 0.5 if st in (0, 8) else 0.28
            s.hit("rhythm", "tick", s.S(bar, st), acc, freq=3200.0 if st % 2 == 0 else 2300.0)
        s.hit("rhythm", "woodblock", s.S(bar, 8), 0.32, freq=760.0)
        s.hit("rhythm", "tom", s.S(bar, 0), 0.5, freq=55.0, tau=0.3, slap=0.05)
        s.hit("rhythm", "tom", s.S(bar, 8), 0.35, freq=55.0, tau=0.3, slap=0.05)
        s.add("rhythm", "pluck", s.scale.midi(r - 14), s.S(bar, 0), 3, 0.6, deg=r - 14, kind="pizz")
        s.add("rhythm", "pluck", s.scale.midi(r - 14 + 4), s.S(bar, 8), 3, 0.45, deg=r - 10, kind="pizz")
    s.hit("rhythm", "timpani", s.S(0, 0), 0.6, midi=33)
    s.hit("rhythm", "timpani", s.S(4, 0), 0.6, midi=33)
    s.hit("rhythm", "gong", s.S(4, 0), 0.3, freq=110.0, length=6.0)
    # lead: three interlocking gears (cycles of 2, 3 and 7 steps)
    for bar, r in enumerate(prog):
        ch = [r, r + 2, r + 4, r + 6]
        for i, st in enumerate(range(0, 14, 2)):
            d = ch[i % 4] + 7 + (7 if (i // 4) % 2 else 0)
            s.add("lead", "pluck", s.scale.midi(d), s.S(bar, st), 3, 0.42, deg=d, kind="celesta", send=0.7, dsend=0.4)
        for i, st in enumerate(range(1, 14, 3)):
            d = ch[(i * 2 + bar) % 4] + 14
            s.add("lead", "pluck", s.scale.midi(d), s.S(bar, st), 4, 0.3, deg=d, kind="clock", send=0.8, dsend=0.5)
        for st in (0, 7):
            d = ch[(bar + st) % 4]
            s.add("lead", "bell", s.scale.midi(d + 7), s.S(bar, st), 10, 0.3, deg=d + 7, kind="church", send=0.8)
    s.lens("lead", "bell", 3, step=0, root=14, vel=0.5, kind="glass", send=0.9, dsend=0.4, stretch=2.0)
    s.lens("lead", "bell", 7, step=0, root=14, vel=0.55, kind="glass", send=0.9, dsend=0.4, stretch=2.0)
    return s


TRACKS: dict[str, TrackDef] = {t.name: t for t in (
    TrackDef("title", build_title, "Heroic and mysterious; brass theme over strings, timpani heartbeat, harp and choir lift.", "D dorian", "4/4"),
    TrackDef("hub", build_hub, "Calm wonder; slow Lydian waltz of brass and glass bells, soft pulse, flute and harp.", "F lydian", "3/4"),
    TrackDef("cinder", build_cinder, "Driving and dark; Phrygian riff, taiko and snare build over 16 bars, ember-bright FM bells.", "E phrygian", "4/4"),
    TrackDef("verdant", build_verdant, "Pastoral 6/8; plucked guitar and harp, frame drum, folk flute tune.", "G mixolydian", "6/8"),
    TrackDef("umbra", build_umbra, "Near-silent horror; beating cluster drones, sub heartbeat, a stopped clock, glass fragments.", "F locrian (clusters)", "5/4", False),
    TrackDef("slipstream", build_slipstream, "Fast and bright; pumping supersaw, arpeggios, four-on-the-floor at 150 bpm.", "A major", "4/4"),
    TrackDef("concord", build_concord, "Stately march; harpsichord continuo, organ, imitative two-voice counterpoint, march snare.", "D major", "2/4"),
    TrackDef("terrace", build_terrace, "Warm and open; slow guitar ostinato, hand drums, a simple singable flute melody.", "Eb major", "4/4"),
    TrackDef("masks", build_masks, "Tense and ritual; taiko with long silences, lute fragments, breathy flute in a five-note scale.", "D in-sen (D Eb G A C)", "6/4"),
    TrackDef("orrery", build_orrery, "Spacious clockwork; shimmering glass pads, 4+3 ticking pulse, interlocking celesta arpeggios.", "A lydian", "7/4"),
)}

TRACK_NAMES = tuple(TRACKS)


def build(name: str) -> Song:
    return TRACKS[name].build()


def spec(name: str, song: Song) -> TrackSpec:
    t = TRACKS[name]
    return TrackSpec(name=name, key=t.key, bpm=round(song.bpm, 4), meter=t.meter, bars=song.bars, seed=song.seed, notes=t.intent,
                     extras={"samples_per_beat": song.spb, "beats_per_bar": song.beats, "steps_per_beat": song.sub,
                             "loop_samples": song.loop_len, "loop_seconds": round(song.seconds, 4)})
