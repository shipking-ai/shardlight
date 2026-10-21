"""Audio manager: layered adaptive music with crossfades, SFX with variants, graceful no-device mode.

Music lives in ``assets/audio/music/<track>/<layer>.wav`` (layers: bed, rhythm, lead).  All layers of a
track are looped in sync on dedicated channels; ``intensity`` (0..1) smoothly fades the rhythm and
lead layers in and out, so the score follows the action without hard cuts.

SFX are looked up as ``assets/audio/sfx/<name>.wav`` (or ``<name>_0.wav``, ``<name>_1.wav`` variants).  If a
file is missing, a recipe registered with :func:`register_sfx` is synthesised on demand.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable

import numpy as np
import pygame

from . import log
from .paths import ASSETS_DIR

LOG = log.get("audio")

SAMPLE_RATE = 22050                      # sample rate of generated assets and recipes
MUSIC_CHANNELS = 12                      # channels 0..11 reserved for music layers
LAYERS = ("bed", "rhythm", "lead")
LAYER_THRESHOLDS = {"bed": (0.0, 0.0), "rhythm": (0.15, 0.45), "lead": (0.5, 0.85)}   # intensity ramp (start, full)

_SFX_RECIPES: dict[str, Callable[[], np.ndarray]] = {}


def register_sfx(name: str, recipe: Callable[[], np.ndarray]) -> None:
    """Register a procedural recipe returning float32 mono samples in [-1, 1] at SAMPLE_RATE."""
    _SFX_RECIPES[name] = recipe


class _MusicTrack:
    def __init__(self, name: str, layers: dict[str, pygame.mixer.Sound], channels: dict[str, pygame.mixer.Channel], indices: dict[str, int]):
        self.name = name
        self.layers = layers
        self.channels = channels
        self.indices = indices
        self.level = {k: 0.0 for k in layers}       # current smoothed layer gain
        self.fade = 0.0                             # track-level fade (crossfade)
        self.fade_target = 1.0
        self.fade_rate = 0.5                        # per second


class AudioManager:
    def __init__(self, settings, assets_dir: Path | None = None):
        self.settings = settings
        self.root = assets_dir or ASSETS_DIR / "audio"
        self.enabled = False
        self.tracks: list[_MusicTrack] = []
        self.current: str | None = None
        self.intensity = 0.0
        self._intensity_smooth = 0.0
        self._sfx_cache: dict[str, list[pygame.mixer.Sound]] = {}
        self._missing: set[str] = set()
        self._rng = random.Random(7)
        self._next_channel = 0
        self.mixer_rate = 44100
        self.stats = {"sfx_played": 0, "music_changes": 0}

    # -- lifecycle ------------------------------------------------------------------------
    def init(self) -> bool:
        if not self.settings.get("audio.enabled"):
            return False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 512)
            pygame.mixer.set_num_channels(32)
            pygame.mixer.set_reserved(MUSIC_CHANNELS)
            self.mixer_rate = pygame.mixer.get_init()[0]
            self.enabled = True
        except pygame.error as exc:
            LOG.warning("audio device unavailable (%s); running silent", exc)
            self.enabled = False
        return self.enabled

    def shutdown(self) -> None:
        if self.enabled:
            pygame.mixer.stop()
            pygame.mixer.quit()
        self.enabled = False

    # -- volumes --------------------------------------------------------------------------
    @property
    def music_gain(self) -> float:
        return self.settings.get("audio.master") * self.settings.get("audio.music")

    @property
    def sfx_gain(self) -> float:
        return self.settings.get("audio.master") * self.settings.get("audio.sfx")

    # -- music ----------------------------------------------------------------------------
    def _load_track(self, name: str) -> _MusicTrack | None:
        folder = self.root / "music" / name
        files: dict[str, Path] = {}
        # WAV is what we render locally; OGG is what the browser build ships (far smaller).
        for p in list(folder.glob("*.wav")) + list(folder.glob("*.ogg")):
            files[p.stem] = p
        if not files:
            if name not in self._missing:
                LOG.warning("music track %r not found in %s", name, folder)
                self._missing.add(name)
            return None
        layers: dict[str, pygame.mixer.Sound] = {}
        for layer in LAYERS:
            if layer in files:
                try:
                    layers[layer] = pygame.mixer.Sound(str(files[layer]))
                except pygame.error as exc:
                    LOG.warning("bad music file %s: %s", files[layer], exc)
        if not layers:
            return None
        used = {i for t in self.tracks for i in t.indices.values()}
        free = [i for i in range(MUSIC_CHANNELS) if i not in used]
        if len(free) < len(layers):
            return None
        indices = dict(zip(layers, free))
        channels = {k: pygame.mixer.Channel(i) for k, i in indices.items()}
        return _MusicTrack(name, layers, channels, indices)

    def play_music(self, name: str | None, fade: float = 1.5, intensity: float | None = None) -> None:
        """Crossfade to ``name`` (None fades to silence). No-op if already current."""
        if intensity is not None:
            self.intensity = intensity
        if not self.enabled or name == self.current:
            return
        for t in self.tracks:
            t.fade_target = 0.0
            t.fade_rate = 1.0 / max(0.05, fade)
        self.current = name
        self.stats["music_changes"] += 1
        if name is None:
            return
        track = self._load_track(name)
        if track is None:
            return
        track.fade = 0.0
        track.fade_target = 1.0
        track.fade_rate = 1.0 / max(0.05, fade)
        # start all layers together (muted) so they stay phase-locked
        for layer, snd in track.layers.items():
            snd.set_volume(1.0)
            track.channels[layer].set_volume(0.0)
            track.channels[layer].play(snd, loops=-1)
        self.tracks.append(track)

    def set_intensity(self, value: float) -> None:
        self.intensity = max(0.0, min(1.0, value))

    def update(self, dt: float) -> None:
        if not self.enabled:
            return
        self._intensity_smooth += (self.intensity - self._intensity_smooth) * min(1.0, dt * 2.0)
        alive: list[_MusicTrack] = []
        for t in self.tracks:
            if t.fade < t.fade_target:
                t.fade = min(t.fade_target, t.fade + t.fade_rate * dt)
            elif t.fade > t.fade_target:
                t.fade = max(t.fade_target, t.fade - t.fade_rate * dt)
            if t.fade <= 0.0 and t.fade_target <= 0.0:
                for ch in t.channels.values():
                    ch.stop()
                continue
            for layer in t.layers:
                lo, hi = LAYER_THRESHOLDS[layer]
                target = 1.0 if hi <= lo else max(0.0, min(1.0, (self._intensity_smooth - lo) / (hi - lo)))
                t.level[layer] += (target - t.level[layer]) * min(1.0, dt * 3.0)
                t.channels[layer].set_volume(t.level[layer] * t.fade * self.music_gain)
            alive.append(t)
        self.tracks = alive

    def stop_music(self, fade: float = 0.5) -> None:
        self.play_music(None, fade)

    # -- sfx ------------------------------------------------------------------------------
    def _to_sound(self, mono: np.ndarray) -> pygame.mixer.Sound:
        data = np.clip(mono, -1.0, 1.0)
        if self.mixer_rate != SAMPLE_RATE:
            n = int(len(data) * self.mixer_rate / SAMPLE_RATE)
            data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
        pcm = (data * 32767).astype(np.int16)
        return pygame.mixer.Sound(buffer=np.ascontiguousarray(np.repeat(pcm[:, None], 2, axis=1)).tobytes())

    def _load_sfx(self, name: str) -> list[pygame.mixer.Sound]:
        sounds: list[pygame.mixer.Sound] = []
        folder = self.root / "sfx"
        for p in sorted(folder.glob(f"{name}.wav")) + sorted(folder.glob(f"{name}_[0-9].wav")) \
                + sorted(folder.glob(f"{name}.ogg")) + sorted(folder.glob(f"{name}_[0-9].ogg")):
            try:
                sounds.append(pygame.mixer.Sound(str(p)))
            except pygame.error as exc:
                LOG.warning("bad sfx file %s: %s", p, exc)
        if not sounds and name in _SFX_RECIPES:
            try:
                sounds.append(self._to_sound(_SFX_RECIPES[name]()))
            except Exception as exc:    # a bad recipe must never crash gameplay
                LOG.warning("sfx recipe %s failed: %s", name, exc)
        return sounds

    def play(self, name: str, volume: float = 1.0, pan: float = 0.0) -> None:
        """Play an effect.  ``pan`` in [-1, 1]."""
        if not self.enabled:
            return
        sounds = self._sfx_cache.get(name)
        if sounds is None:
            sounds = self._load_sfx(name)
            self._sfx_cache[name] = sounds
            if not sounds:
                LOG.warning("sfx %r has no file or recipe", name)
        if not sounds:
            return
        snd = self._rng.choice(sounds)
        ch = pygame.mixer.find_channel()
        if ch is None:
            return
        ch.set_volume(*self._stereo(volume * self.sfx_gain, pan))
        ch.play(snd)
        self.stats["sfx_played"] += 1

    @staticmethod
    def _stereo(vol: float, pan: float) -> tuple[float, float]:
        pan = max(-1.0, min(1.0, pan))
        return vol * min(1.0, 1 - pan), vol * min(1.0, 1 + pan)

    def has_sfx(self, name: str) -> bool:
        if not self.enabled:
            return name in _SFX_RECIPES or (self.root / "sfx" / f"{name}.wav").exists()
        if name not in self._sfx_cache:
            self._sfx_cache[name] = self._load_sfx(name)
        return bool(self._sfx_cache[name])
