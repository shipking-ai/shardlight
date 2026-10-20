"""Filesystem locations. User data location can be overridden with SHARDLIGHT_HOME."""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = PACKAGE_DIR.parent
ASSETS_DIR = Path(os.environ.get("SHARDLIGHT_ASSETS", PROJECT_DIR / "assets"))
DATA_DIR = Path(os.environ.get("SHARDLIGHT_DATA", PROJECT_DIR / "data"))
MODS_DIR = Path(os.environ.get("SHARDLIGHT_MODS", PROJECT_DIR / "mods"))
EXAMPLES_DIR = Path(os.environ.get("SHARDLIGHT_EXAMPLES", PROJECT_DIR / "examples"))


def user_dir() -> Path:
    """Return (and create) the writable directory for saves, settings and logs."""
    home = os.environ.get("SHARDLIGHT_HOME")
    path = Path(home) if home else PROJECT_DIR / "userdata"
    path.mkdir(parents=True, exist_ok=True)
    return path
