"""Masks: The Gauntlet of Masks - 2D fighting game (mode 7).

Pure deterministic combat core in ``sim/``; ``render`` draws articulated fighters posed from frame data;
``cpu`` is a fair, adaptive opponent; ``scene`` holds menus, arcade ladder, versus, training and replays.
"""
from __future__ import annotations

from . import sfx as _sfx  # noqa: F401  (registers the masks_* sound recipes)
from .info import INFO
from .sim.roster import KIND
from .sim.schema import CHARACTER_SCHEMA


def register_content(db) -> None:
    db.register_kind(KIND, CHARACTER_SCHEMA)


def create(app, **opts):
    from .scene import MasksScene
    return MasksScene(app, **opts)
