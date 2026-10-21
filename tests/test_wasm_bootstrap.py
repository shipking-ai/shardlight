"""Tests for the browser build's pygame bootstrap."""
import importlib.abc
import sys

import pytest


class _BlockConstants(importlib.abc.MetaPathFinder):
    """Pretend the wasm pygame has no constants module."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pygame.constants":
            raise ModuleNotFoundError("No module named 'pygame.constants'")
        return None


def test_install_registers_a_stand_in_when_pygame_is_broken(monkeypatch):
    from shardlight.core.pygame_bootstrap import install_pygame_constants

    for name in ("pygame.constants", "pygame"):
        sys.modules.pop(name, None)
    blocker = _BlockConstants()
    monkeypatch.setattr(sys, "meta_path", [blocker] + list(sys.meta_path))
    try:
        assert install_pygame_constants() is True
        assert "pygame.constants" in sys.modules
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.pop("pygame.constants", None)


def test_stand_in_carries_the_constants_pygame_needs():
    from shardlight.core import pygame_constants

    for name in ("QUIT", "K_a", "K_RETURN", "RESIZABLE", "SRCALPHA", "KEYDOWN", "MOUSEBUTTONDOWN"):
        assert hasattr(pygame_constants, name), name
    assert pygame_constants.__all__


def test_install_is_a_noop_when_pygame_is_fine():
    from shardlight.core.pygame_bootstrap import install_pygame_constants

    assert install_pygame_constants() is True
    import pygame

    assert pygame.QUIT is not None
