"""User settings: video, audio, accessibility, difficulty, input. JSON, validated and clamped."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from . import log
from .paths import user_dir

LOG = log.get("settings")

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "video": {"fullscreen": False, "window_scale": 3, "vsync": True, "show_fps": False},
    "audio": {"master": 0.8, "music": 0.7, "sfx": 0.9, "enabled": True},
    "access": {
        "reduce_shake": False,      # scales camera shake to 0
        "reduce_flash": False,      # suppresses full-screen flashes and strobing
        "high_contrast": False,     # stronger outlines / HUD backdrops
        "colorblind": "none",       # none | protan | deutan | tritan  (recolour filter)
        "text_scale": 1,            # 1 or 2 (integer scale of pixel font)
        "toggle_hold": False,       # hold-style inputs become toggles where a mode supports it
        "game_speed": 1.0,          # 0.5 - 1.0 global slowdown for assist
        "aim_assist": True,
    },
    "difficulty": {"preset": "standard", "adaptive_ai": 1.0},   # story | standard | hard ; 0..1.5
    "input": {"deadzone": 0.25, "trigger_threshold": 0.5, "bindings": {}},
}

CHOICES = {
    "access.colorblind": ["none", "protan", "deutan", "tritan"],
    "difficulty.preset": ["story", "standard", "hard"],
}
RANGES = {
    "video.window_scale": (1, 6), "audio.master": (0.0, 1.0), "audio.music": (0.0, 1.0),
    "audio.sfx": (0.0, 1.0), "access.text_scale": (1, 2), "access.game_speed": (0.5, 1.0),
    "difficulty.adaptive_ai": (0.0, 1.5), "input.deadzone": (0.05, 0.6),
    "input.trigger_threshold": (0.2, 0.9),
}


def _merge(base: dict, over: dict, path: str = "") -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            continue
        if k == "bindings":
            out[k] = v if isinstance(v, dict) else {}
        elif isinstance(base[k], dict):
            if isinstance(v, dict):
                out[k] = _merge(base[k], v, f"{path}{k}.")
        else:
            key = f"{path}{k}"
            b = base[k]
            ok = (isinstance(b, bool) and isinstance(v, bool)) or \
                 (isinstance(b, (int, float)) and not isinstance(b, bool) and isinstance(v, (int, float))
                  and not isinstance(v, bool)) or \
                 (isinstance(b, str) and isinstance(v, str))
            if not ok:
                LOG.warning("bad type for setting %s, using default", key)
                continue
            if key in CHOICES and v not in CHOICES[key]:
                LOG.warning("bad choice %r for %s", v, key)
                continue
            if key in RANGES:
                lo, hi = RANGES[key]
                v = type(b)(min(max(v, lo), hi))
            out[k] = v
    return out


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or (user_dir() / "settings.json")
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.dirty = False

    def get(self, dotted: str) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            cur = cur[part]
        return cur

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        cur = self.data
        for part in parts[:-1]:
            cur = cur[part]
        if dotted in RANGES:
            lo, hi = RANGES[dotted]
            value = type(cur[parts[-1]])(min(max(value, lo), hi))
        if dotted in CHOICES and value not in CHOICES[dotted]:
            raise ValueError(f"{value!r} not valid for {dotted}")
        cur[parts[-1]] = value
        self.dirty = True

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
            self.data = _merge(DEFAULTS, raw)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            LOG.warning("settings unreadable (%s); using defaults", exc)
            try:
                os.replace(self.path, self.path.with_suffix(".corrupt"))
            except OSError:
                pass
            self.data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError as exc:
            LOG.error("could not save settings: %s", exc)

    def __getitem__(self, dotted: str) -> Any:
        return self.get(dotted)
