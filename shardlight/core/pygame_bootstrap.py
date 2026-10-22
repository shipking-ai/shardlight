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

import importlib.util
import sys
from pathlib import Path


def _note(message: str) -> None:
    try:
        import js  # type: ignore[import-not-found]  # provided by pygbag

        js.console.log(f"[shardlight] {message}")
    except Exception:
        pass


def _patch_dir() -> Path | None:
    try:
        from . import pygame_patch

        base = Path(pygame_patch.__file__).resolve().parent
        candidate = base / "pygame"
        return candidate if candidate.is_dir() else None
    except Exception:
        return None


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
    """Put the files the wasm wheel lost back into the installed pygame package."""
    source = _stand_in_source()
    patch = _patch_dir()
    if not source or patch is None:
        return False
    for entry in list(sys.path):
        if not entry:
            continue
        package = Path(entry) / "pygame"
        try:
            if not (package / "__init__.py").is_file():
                continue
            wrote = False
            if not (package / "constants.py").is_file():
                (package / "constants.py").write_text(source, encoding="utf-8")
                wrote = True
            for extra in sorted(patch.glob("*.py")):
                target = package / extra.name
                if not target.is_file():
                    target.write_bytes(extra.read_bytes())
                    wrote = True
            if wrote:
                _note(f"bootstrap: patched the installed pygame at {package}")
            return True
        except OSError:
            continue
    return False


def _register_patch_modules() -> list[str]:
    """Expose the patched modules under their pygame names.

    The wasm wheel may not be installed yet when this runs, so the modules are
    registered in ``sys.modules`` as well: pygame's own ``__init__`` then finds
    them whichever way it looks.
    """
    patch = _patch_dir()
    if patch is None:
        return []
    registered: list[str] = []
    for path in sorted(patch.glob("*.py")):
        name = f"pygame.{path.stem}"
        if name in sys.modules:
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            registered.append(name)
        except Exception:
            sys.modules.pop(name, None)
    if registered:
        _note(f"bootstrap: registered {', '.join(registered)}")
    return registered


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
    _register_patch_modules()
    return True
