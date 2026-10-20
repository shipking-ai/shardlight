"""Terrace - sandbox survival and construction (mode 6).

``worldgen`` seeded world + validation, ``world`` tiles and edit rules, ``light`` / ``fluids`` simulations,
``ecology`` the food web, ``player`` physics and actions, ``inventory`` crafting, ``structures`` the Beacon and the
Keystone, ``game`` the integrated simulation, ``art`` / ``scene`` presentation.
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers terrace_* sound recipes)
from .info import INFO
from .registry import register_kinds


def register_content(db) -> None:
    register_kinds(db)


def create(app, **opts):
    from .scene import TerraceScene
    return TerraceScene(app, **opts)
