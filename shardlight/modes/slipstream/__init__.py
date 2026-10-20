"""Slipstream - futuristic racing (mode 4).

Physics-lite car model (``physics``), seeded validated tracks (``track``), race rules (``race``), rival drivers
(``ai``), baked art (``art``) and the scene with 1-2 viewports (``scene``).
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers slipstream_* sound recipes)
from .defs import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .scene import SlipScene
    return SlipScene(app, **opts)
