"""Structured logging to console and a rotating file in the user directory."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from .paths import user_dir

_configured = False


def setup(level: int = logging.INFO, to_file: bool = True) -> logging.Logger:
    global _configured
    root = logging.getLogger("shardlight")
    if _configured:
        return root
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if to_file:
        try:
            fh = logging.handlers.RotatingFileHandler(
                user_dir() / "shardlight.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            root.warning("log file unavailable; console only")
    _configured = True
    return root


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"shardlight.{name}")
