import json

from shardlight.core.content import ContentDB
from shardlight.core.save import new_profile
from shardlight.core.settings import Settings
from shardlight.core.world import ECHO_SCHEMA, Economy, World


def make_world(echoes):
    db = ContentDB()
    db.register_kind("echo", ECHO_SCHEMA)
    for e in echoes:
        assert db.add_entry("echo", e, "base"), db.problems
    return World(new_profile(), db)


def test_echo_chain_across_modes():
    w = make_world([
        {"id": "a", "on": "orrery.signal_decoded", "where": {"signal": "choir"},
         "effects": [{"unlock": "verdant.site.x"}, {"set_flag": "sig"}]},
        {"id": "b", "on": "verdant.site_explored", "where": {"site": "x"}, "require": {"unlocks": ["verdant.site.x"]},
         "effects": [{"unlock": "cinder.boss.y"}, {"emit": "custom.ping", "payload": {"n": 1}}]},
        {"id": "c", "on": "custom.ping", "effects": [{"counter": "pings", "add": 2}]},
    ])
    assert w.emit("verdant.site_explored", site="x") == []           # requirement not met yet
    assert w.emit("orrery.signal_decoded", signal="other") == []      # payload mismatch
    assert w.emit("orrery.signal_decoded", signal="choir") == ["a"]
    assert w.has_unlock("verdant.site.x") and w.flag("sig")
    assert w.emit("verdant.site_explored", site="x") == ["b", "c"]
    assert w.has_unlock("cinder.boss.y") and w.counter("pings") == 2
    assert w.emit("orrery.signal_decoded", signal="choir") == []      # once only


def test_echo_cascade_is_bounded():
    w = make_world([{"id": "loop", "on": "ping", "once": False, "effects": [{"emit": "ping"}]}])
    fired = w.emit("ping")
    assert 0 < len(fired) <= 64


def test_requirements_counters_and_facets():
    w = make_world([{"id": "e", "on": "go", "require": {"counters": {"n": 3}, "facets": ["cinder"]},
                     "effects": [{"toast": "hi"}]}])
    assert w.emit("go") == []
    w.add_counter("n", 3)
    assert w.emit("go") == []
    w.complete_facet("cinder")
    assert w.emit("go") == ["e"]
    assert "hi" in w.toasts


def test_complete_facet_once_and_emits():
    w = make_world([{"id": "g", "on": "cinder.facet_repaired", "effects": [{"grant": 25}]}])
    assert w.complete_facet("cinder") is True
    assert w.complete_facet("cinder") is False
    assert w.profile["currency"]["glint"] == 25


def test_economy_caps_per_mode():
    w = make_world([])
    eco = Economy(w)
    assert eco.grant("cinder", 30) == 30
    assert eco.grant("cinder", 30) == 10          # cap 40
    assert eco.grant("verdant", 5) == 5
    eco.reset_session()
    assert eco.grant("cinder", 5) == 5


def test_settings_clamp_validate_and_corruption(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(p)
    s.set("audio.master", 7)
    assert s.get("audio.master") == 1.0
    try:
        s.set("access.colorblind", "purple")
        assert False
    except ValueError:
        pass
    s.save()
    t = Settings(p)
    t.load()
    assert t.get("audio.master") == 1.0
    p.write_text(json.dumps({"audio": {"master": "loud", "music": 5}, "difficulty": {"preset": "nope"}}))
    u = Settings(p)
    u.load()
    assert u.get("audio.master") == 0.8 and u.get("audio.music") == 1.0 and u.get("difficulty.preset") == "standard"
    p.write_text("{{{")
    v = Settings(p)
    v.load()
    assert v.get("audio.master") == 0.8 and p.with_suffix(".corrupt").exists()
