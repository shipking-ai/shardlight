"""Tests for the browser build's pygame bootstrap."""
import sys

import pytest


@pytest.fixture
def clean_pygame():
    saved = {k: v for k, v in sys.modules.items() if k == "pygame" or k.startswith("pygame.")}
    for k in list(saved):
        sys.modules.pop(k, None)
    yield
    for k in [k for k in sys.modules if k == "pygame" or k.startswith("pygame.")]:
        sys.modules.pop(k, None)
    sys.modules.update(saved)


def test_constants_stand_in_carries_what_pygame_needs():
    from shardlight.core import pygame_constants

    for name in ("QUIT", "K_a", "K_RETURN", "RESIZABLE", "SRCALPHA", "KEYDOWN", "MOUSEBUTTONDOWN"):
        assert hasattr(pygame_constants, name), name
    assert pygame_constants.__all__


def test_install_is_safe_on_a_desktop_python(clean_pygame):
    from shardlight.core import pygame_bootstrap

    # The wasm base shared object is not present on a desktop interpreter, so
    # the bootstrap cannot install pygame; it must still leave pygame usable.
    result = pygame_bootstrap.install_pygame_constants()
    assert result in (True, False)
    import pygame

    assert pygame.QUIT is not None
