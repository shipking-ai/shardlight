"""Tests for the admin cheats: max out a shard, aimbot, one-shot."""
from __future__ import annotations

import os

import pytest

from shardlight.core import admin_cheats


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARDLIGHT_HOME", str(tmp_path))
    from shardlight.core.app import App

    app = App(headless=True, seed=7, audio=False)
    app.new_game(0, "Tester")
    return app


def test_max_out_reports_a_summary_for_a_known_shard(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    scene = type("S", (), {"mode_id": "slipstream", "data": {}})()
    summary = admin_cheats.max_out(app, scene)
    assert "Slipstream" in summary
    assert scene.data["credits"] == 999999
    assert scene.data["cups_won"]


def test_max_out_is_safe_for_an_unknown_shard(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    scene = type("S", (), {"mode_id": "nope", "data": {}})()
    assert "Nothing to max out" in admin_cheats.max_out(app, scene)


def test_max_out_never_raises(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)

    class Broken:
        mode_id = "cinder"

        @property
        def lib(self):
            raise RuntimeError("boom")

    assert "failed" in admin_cheats.max_out(app, Broken()).lower()


def test_cinder_max_out_unlocks_everything(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    from shardlight.modes.cinder.scene import CinderScene

    cs = CinderScene(app)
    cs.on_enter()
    summary = admin_cheats.max_out(app, cs)
    assert "Cinder" in summary
    u = cs.data["unlocked"]
    assert set(cs.lib.boons) <= set(u["boons"])
    assert set(cs.lib.mods) <= set(u["mods"])
    assert cs.data["soot"] >= 999999


def test_admin_flags_default_off(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    assert app.admin_god is False
    assert app.admin_aimbot is False
    assert app.admin_oneshot is False


def test_admin_panel_lists_the_cheats(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app.admin = True
    from shardlight.core.admin import AdminPanel

    panel = AdminPanel(app)
    labels = [getattr(i, "label", "") for i in panel._items()]
    assert any("Aimbot" in s for s in labels)
    assert any("One-shot" in s for s in labels)
    assert any("God mode" in s for s in labels)
