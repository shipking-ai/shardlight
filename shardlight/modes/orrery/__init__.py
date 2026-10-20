"""Orrery - space exploration and civilization sim (mode 8).

``galaxy`` seeded galaxy and orbits, ``civsim`` the living economy and politics, ``signals`` bearings and puzzles,
``game`` rules (ship, trade, missions, Last Lamp), ``flight`` real-time system flight and combat,
``art`` / ``scene`` / ``screens`` presentation.
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers orrery_* sound recipes)
from .defs import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .scene import OrreryScene
    return OrreryScene(app, **opts)
