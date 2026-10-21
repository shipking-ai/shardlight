"""Make pygame importable in the browser build.

The wasm build of pygame-ce published on the pygame-web CDN is missing
``pygame/constants.py``, while its own ``pygame/__init__.py`` does
``from pygame.constants import *``.  Importing pygame therefore dies with
``No module named 'pygame.constants'`` and the game never starts.

The wheel is installed lazily, the first time something imports pygame, and it
overwrites the interpreter's own (working) pygame with the broken one.  So the
missing file is written into the installed package before pygame is imported,
and a pure-python stand-in is registered as a backstop.

The stand-in is generated from a normal pygame-ce install by
``tools/gen_pygame_constants.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _note(message: str) -> None:
    try:
        import js  # type: ignore[import-not-found]  # provided by pygbag

        js.console.log(f"[shardlight] {message}")
    except Exception:
        pass


def _stand_in_source() -> str | None:
    try:
        from . import pygame_constants

        path = getattr(pygame_constants, "__file__", None)
        if not path:
            return None
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return None


def _write_into_installed_pygame() -> bool:
    """Drop the missing constants module into the installed pygame package."""
    source = _stand_in_source()
    if not source:
        return False
    for entry in list(sys.path):
        if not entry:
            continue
        package = Path(entry) / "pygame"
        try:
            if not (package / "__init__.py").is_file():
                continue
            target = package / "constants.py"
            if target.is_file():
                return True
            target.write_text(source, encoding="utf-8")
        except OSError:
            continue
        else:
            _note(f"bootstrap: wrote pygame/constants.py into {package}")
            return True
    return False


def install_pygame_constants() -> bool:
    """Make sure ``pygame.constants`` resolves.  Returns True if it is in place."""
    if "pygame.constants" in sys.modules:
        return True
    try:
        import pygame.constants  # noqa: F401

        return True
    except Exception:
        # a failed parent import leaves a half-initialised package behind
        sys.modules.pop("pygame", None)
        sys.modules.pop("pygame.constants", None)
    _write_into_installed_pygame()
    try:
        from . import pygame_constants
    except Exception:
        return False
    sys.modules["pygame.constants"] = pygame_constants
    _note("bootstrap: registered the pygame.constants stand-in")
    return True
