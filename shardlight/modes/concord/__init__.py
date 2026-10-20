"""Concord: Ledger of Crowns - strategy and empire simulation (mode 5).

A seeded campaign map of hex provinces (``campaign``) with a tactical battle layer (``battle``), diplomacy
(``diplomacy``) and house AI (``ai``).  All rules are pure modules; ``scene`` / ``ui_*`` translate input into
orders and orders into pictures.
"""
from __future__ import annotations

from typing import Any

from . import sfx as _sfx  # noqa: F401  (registers the concord_* sound recipes on import)
from .info import INFO
from .schemas import KINDS


def register_content(db) -> None:
    """Register every ``concord.*`` kind with its schema."""
    for kind, schema in KINDS.items():
        db.register_kind(kind, schema)


def create(app, **opts: Any):
    from .scene import ConcordScene
    return ConcordScene(app, **opts)
