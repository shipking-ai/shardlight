"""Cinder - action roguelike (mode 1).

``defs`` content schemas, ``sim`` deterministic gameplay (player, enemies, bosses, rooms, generation),
``art`` procedural drawing, ``scene`` screens and feedback.
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers cinder_* sound recipes)
from .defs import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .scene import CinderScene
    return CinderScene(app, **opts)
