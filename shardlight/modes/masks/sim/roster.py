"""Load validated characters from the content database (base game + mods)."""
from __future__ import annotations

from ....core import log
from .moves import Character, build_character
from .schema import CHARACTER_SCHEMA
from .validate import validate_character

LOG = log.get("masks")
KIND = "masks.character"


def load_roster(db, unlocked=lambda uid: True) -> dict[str, Character]:
    """Return id -> Character for every entry that parses and passes frame-data validation."""
    out: dict[str, Character] = {}
    for d in db.all(KIND):
        try:
            ch = build_character(d)
        except Exception as exc:             # a malformed mod must not crash the game
            LOG.warning("masks character %s skipped: %s", d.get("id"), exc)
            continue
        errs = validate_character(ch)
        if errs:
            for e in errs[:5]:
                LOG.warning("masks character %s: %s", ch.id, e)
            LOG.warning("masks character %s skipped (%d frame-data problems)", ch.id, len(errs))
            continue
        out[ch.id] = ch
    return out


def standalone_db():
    """ContentDB with only masks content loaded (used by tests and tools)."""
    from ....core.content import ContentDB
    from ....core.paths import DATA_DIR
    db = ContentDB()
    db.register_kind(KIND, CHARACTER_SCHEMA)
    db.load_dir(DATA_DIR, "base")
    return db
