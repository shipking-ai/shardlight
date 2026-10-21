"""Make pygame importable in the browser build.

The wasm build of pygame-ce published on the pygame-web CDN is missing
``pygame/constants.py``, while its own ``pygame/__init__.py`` does
``from pygame.constants import *``.  Importing pygame therefore dies with
``No module named 'pygame.constants'`` and the game never starts.

Registering a pure-python stand-in under that name before pygame is imported
fixes it.  The stand-in is generated from a normal pygame-ce install by
``tools/gen_pygame_constants.py``.
"""
from __future__ import annotations

import sys


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
    try:
        from . import pygame_constants
    except Exception:
        return False
    sys.modules["pygame.constants"] = pygame_constants
    return True
