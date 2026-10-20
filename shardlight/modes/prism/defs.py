"""Content registration for the prism mode (kind: prism.tour)."""
from __future__ import annotations

from ...core.content import ContentDB

_TOUR_SCHEMA = {
    "id": {"type": "str", "required": True},
    "title": {"type": "str", "required": True},
    "legs": {"type": "list", "required": True},
    "finale": {"type": "dict", "required": True},
}


def register_content(db: ContentDB) -> None:
    db.register_kind("prism.tour", _TOUR_SCHEMA)
