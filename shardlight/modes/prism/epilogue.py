"""Minimal EpilogueScene stub for the Grand Tour (replaced in Task 9)."""
from __future__ import annotations

from ...core.scene import ModeScene


class EpilogueScene(ModeScene):
    INFO = None

    def __init__(self, app, **opts):
        super().__init__(app, **opts)
        self.app = app
        self.state = "run"

    def update(self, dt):
        pass

    def draw(self, surf):
        pass


from .info import INFO as _INFO
EpilogueScene.INFO = _INFO
