"""Content registration for the prism mode (kind: prism.tour)."""
from __future__ import annotations

from ...core.content import ContentDB


def register_content(db: ContentDB) -> None:
    # schema filled in Task 3; keep the kind registered so mods can extend it
    db.register_kind("prism.tour", {"id": {"type": "str", "required": True}})
