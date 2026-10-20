"""Verdant - open-world RPG (mode 2): the countryside of Hollowmere.

``worldgen`` + ``landmarks`` + ``interiors`` build the seeded, validated world; ``sim`` runs time, the player,
economy and persistence; ``combat`` creatures and bosses; ``npcs`` schedules; ``quests`` the data-driven quest engine;
``actions`` interaction; ``art`` / ``scene`` / ``screens`` presentation.
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers verdant_* sound recipes)
from .catalog import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .scene import VerdantScene
    return VerdantScene(app, **opts)
