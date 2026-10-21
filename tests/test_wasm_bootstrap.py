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


@pytest.fixture
def clean_pygame():
    """Keep sys.modules honest: the bootstrap touches pygame.constants."""
    saved = {k: v for k, v in sys.modules.items() if k == "pygame" or k.startswith("pygame.")}
    for k in list(saved):
        sys.modules.pop(k, None)
    yield
    for k in [k for k in sys.modules if k == "pygame" or k.startswith("pygame.")]:
        sys.modules.pop(k, None)
    sys.modules.update(saved)


def test_install_registers_a_stand_in_when_pygame_is_broken(clean_pygame, monkeypatch):
    from shardlight.core.pygame_bootstrap import install_pygame_constants

    blocker = _BlockConstants()
    monkeypatch.setattr(sys, "meta_path", [blocker] + list(sys.meta_path))
    try:
        assert install_pygame_constants() is True
        assert "pygame.constants" in sys.modules
    finally:
        sys.meta_path.remove(blocker)


def test_stand_in_carries_the_constants_pygame_needs():
    from shardlight.core import pygame_constants

    for name in ("QUIT", "K_a", "K_RETURN", "RESIZABLE", "SRCALPHA", "KEYDOWN", "MOUSEBUTTONDOWN"):
        assert hasattr(pygame_constants, name), name
    assert pygame_constants.__all__


def test_install_is_a_noop_when_pygame_is_fine(clean_pygame):
    from shardlight.core.pygame_bootstrap import install_pygame_constants

    assert install_pygame_constants() is True
    import pygame

    assert pygame.QUIT is not None
    assert "pygame.constants" not in sys.modules or sys.modules["pygame.constants"] is not None


def test_missing_module_is_written_into_the_installed_package(tmp_path, monkeypatch):
    """The wasm wheel is missing pygame/constants.py: the bootstrap puts it back."""
    from shardlight.core import pygame_bootstrap

    package = tmp_path / "pygame"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "meta_path", [_BlockConstants()] + list(sys.meta_path))
    assert pygame_bootstrap._write_into_installed_pygame() is True
    written = package / "constants.py"
    assert written.is_file()
    assert "QUIT" in written.read_text(encoding="utf-8")
