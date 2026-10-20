"""Prism - the Grand Tour final world (not a shard; loaded by the hub's Lens entry)."""
from __future__ import annotations

from . import tourspec as _tourspec  # noqa: F401  (validates tour data on import)
from .defs import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .tourroot import TourRoot
    return TourRoot(app, **opts)
