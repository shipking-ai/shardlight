"""Umbra - psychological horror survival (mode 3): the Gloaming Ward.

``levelgen`` seeded buildings with solvable objective chains, ``sim`` the player/doors/light/sound/objectives,
``enemies`` the Hark, Stillwatch and Understudy, ``director`` pacing and bounded adaptation, ``view`` shadow-casting
renderer, ``scene`` screens.
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers umbra_* sound recipes)
from .catalog import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .scene import UmbraScene
    return UmbraScene(app, **opts)
