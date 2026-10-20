"""The cross-mode web (data/echo/spine.json): every unlock an echo grants has a consumer somewhere, and the chains run end to
end through the real echo engine and the real consumers."""
import json
import re
from pathlib import Path

import pytest
from conftest import run_ticks

ROOT = Path(__file__).resolve().parent.parent
SPINE = json.loads((ROOT / "data" / "echo" / "spine.json").read_text(encoding="utf-8"))["entries"]


def _unlocks():
    out = []
    for e in SPINE:
        for eff in e["effects"]:
            if "unlock" in eff:
                out.append((e["id"], eff["unlock"]))
    return out


def _consumer_text():
    parts = []
    for p in (ROOT / "shardlight" / "modes").rglob("*.py"):
        parts.append(p.read_text(encoding="utf-8"))
    for p in (ROOT / "data").rglob("*.json"):
        if p.parent.name not in ("echo", "lore"):
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_every_unlock_an_echo_grants_is_consumed_by_some_shard():
    text = _consumer_text()
    assert len(_unlocks()) >= 9
    for echo_id, uid in _unlocks():
        prefix = uid.rsplit(".", 1)[0] + "."
        assert uid in text or (prefix in text and uid.split(".")[-1] in text), (echo_id, uid)


def test_every_echo_trigger_is_emitted_by_some_shard():
    text = _consumer_text()
    for e in SPINE:
        ev = e["on"]
        if ev.endswith("facet_repaired"):
            continue                                   # emitted by World.complete_facet
        mode, _, name = ev.partition(".")
        assert f'"{ev}"' in text or f"'{ev}'" in text or (f"{mode}." in text and name in text), (e["id"], ev)


def test_orrery_galaxy_changes_when_the_shard_is_told_about_other_worlds():
    from shardlight.modes.orrery import galaxy
    base = galaxy.generate(7)
    both = galaxy.generate(7, ("concord_envoys", "beacon_echo"))
    assert base.envoy_system is None and both.envoy_system is not None
    assert both.systems[both.envoy_system].tags.count("envoys") == 1
    assert "beacon_echo" in both.signal_sources or any("beacon" in k for k in both.signal_sources)
    # deterministic: the same unlocks give the same galaxy
    again = galaxy.generate(7, ("concord_envoys", "beacon_echo"))
    assert again.envoy_system == both.envoy_system and again.signal_sources == both.signal_sources


def test_chain_across_five_shards_through_the_real_echo_engine(app):
    w = app.world
    # Orrery decodes the Choir Signal -> Verdant's Listening Stones can be found
    w.emit("orrery.signal_decoded", signal="choir")
    assert w.has_unlock("verdant.site.listening_stones")
    # Verdant: the stones are explored -> Cinder's Choir Warden appears
    assert app.enter_mode("verdant", seed=5)
    run_ticks(app, 10)
    vs = app.scenes.top
    vs.new_world()
    run_ticks(app, 5)
    g = vs.game
    assert not g.over.sites["listening_stones"].hidden
    g.hook("verdant.site_explored", site="listening_stones")
    vs.drain_hooks()
    assert w.has_unlock("cinder.boss.choir_warden")
    # Cinder: the Warden falls -> Concord and Terrace learn from it
    w.emit("cinder.boss_defeated", boss="choir_warden")
    assert w.has_unlock("concord.tech.resonant_forging") and w.has_unlock("terrace.recipe.choir_alloy")
    # Umbra / Masks / Slipstream / Orrery
    w.emit("umbra.relic_found", relic="stopped_clock")
    assert w.has_unlock("masks.rival.warden_of_hours")
    w.emit("masks.rival_defeated", rival="warden_of_hours")
    assert w.has_unlock("slipstream.vehicle.chronograph")
    w.emit("slipstream.championship_won", cup="salt_cup")
    assert w.has_unlock("orrery.ship.salt_runner")
    # Concord's first treaty opens Orrery contact; a Terrace beacon is eventually decoded and brings Verdant caravans
    w.emit("concord.treaty_signed")
    assert w.has_unlock("orrery.contact.concord_envoys")
    w.emit("terrace.structure_built", kind="beacon")
    w.emit("orrery.signal_decoded", signal="beacon_echo")
    assert w.has_unlock("verdant.trade.beacon_caravans")
    g.refresh_unlocks()
    assert g.flags.get("caravans") and "star_salt" in {i for i, _, _ in g.shop_items("general")}
    # Verdant's debt is repaid -> Umbra can carry the Lantern Ward
    g.hook("verdant.quest_completed", quest="lamplighters_debt")
    vs.drain_hooks()
    assert w.has_unlock("umbra.item.lantern_ward")
    # every facet can be repaired exactly once through its own event
    assert not w.facet_repaired("verdant")
    g.hook("verdant.quest_completed", quest="kindle_the_hollow")
    vs.drain_hooks()
    assert w.facet_repaired("verdant")
