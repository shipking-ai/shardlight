import json
from pathlib import Path

from shardlight.core.content import ContentDB, validate_fields
from shardlight.core.mods import ModManager

SCHEMA = {
    "name": {"type": "str", "required": True},
    "dmg": {"type": "int", "min": 0, "max": 100},
    "tags": {"type": "list", "items": {"type": "str"}},
    "color": {"type": "color"},
    "kind": {"type": "str", "choices": ["blade", "hammer"]},
}


def make_db():
    db = ContentDB()
    db.register_kind("t.weapon", SCHEMA)
    return db


def test_validate_reports_problems():
    errs = validate_fields({"name": 3, "dmg": 500, "extra": 1, "color": [1, 2]}, SCHEMA)
    joined = " | ".join(errs)
    assert "name: expected string" in joined and "above maximum" in joined
    assert "extra: unknown field" in joined and "color" in joined


def test_add_and_conflict_rules():
    db = make_db()
    assert db.add_entry("t.weapon", {"id": "a", "name": "A"}, "base")
    assert not db.add_entry("t.weapon", {"id": "a", "name": "A2"}, "modx")          # conflict w/o override
    assert db.get("t.weapon", "a")["name"] == "A"
    assert db.add_entry("t.weapon", {"id": "a", "name": "A2"}, "modx", allow_override=True)
    assert db.get("t.weapon", "a")["name"] == "A2" and db.source_of("t.weapon", "a") == "modx"
    assert not db.add_entry("t.weapon", {"id": "Bad Id", "name": "x"}, "base")
    assert not db.add_entry("nope", {"id": "x"}, "base")
    assert len(db.problems) >= 3


def write(p: Path, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_mod_loading_order_deps_and_errors(tmp_path):
    mods = tmp_path / "mods"
    write(mods / "base_pack" / "mod.json", {"id": "base_pack", "name": "B", "version": "1.0.0", "api": 1})
    write(mods / "base_pack" / "data" / "t.weapon" / "w.json", {"entries": [{"id": "blade1", "name": "Blade"}]})
    write(mods / "addon" / "mod.json", {"id": "addon", "name": "Addon", "version": "1.2.0", "api": 1,
                                         "depends": [{"id": "base_pack", "version": ">=1.0.0"}],
                                         "overrides": ["t.weapon/blade1"]})
    write(mods / "addon" / "data" / "t.weapon" / "w.json", [{"id": "blade1", "name": "Better Blade"},
                                                           {"id": "bad", "name": 5}])
    write(mods / "orphan" / "mod.json", {"id": "orphan", "name": "O", "version": "1.0.0", "api": 1,
                                          "depends": [{"id": "missing_mod"}]})
    write(mods / "wrongapi" / "mod.json", {"id": "wrongapi", "name": "W", "version": "1.0.0", "api": 99})
    (mods / "broken").mkdir()
    (mods / "broken" / "mod.json").write_text("{nope", encoding="utf-8")
    db = make_db()
    mm = ModManager(mods)
    mm.discover()
    mm.apply(db)
    assert mm.loaded == ["base_pack", "addon"]
    assert db.get("t.weapon", "blade1")["name"] == "Better Blade"
    report = "\n".join(mm.report)
    assert "missing dependency" in report and "unsupported api" in report and "unreadable" in report
    assert any("bad" in p for p in db.problems)


def test_version_constraint_and_conflict(tmp_path):
    mods = tmp_path / "mods"
    write(mods / "a" / "mod.json", {"id": "aa", "name": "A", "version": "0.9.0", "api": 1})
    write(mods / "b" / "mod.json", {"id": "bb", "name": "B", "version": "1.0.0", "api": 1,
                                     "depends": [{"id": "aa", "version": ">=1.0.0"}]})
    write(mods / "c" / "mod.json", {"id": "cc", "name": "C", "version": "1.0.0", "api": 1, "conflicts": ["aa"]})
    mm = ModManager(mods)
    mm.discover()
    order = [m.id for m in mm.resolve()]
    assert "bb" not in order
    assert order.count("aa") + order.count("cc") == 1       # conflicting pair cannot both load


def test_dependency_cycle_is_reported(tmp_path):
    mods = tmp_path / "mods"
    write(mods / "a" / "mod.json", {"id": "aa", "name": "A", "version": "1.0.0", "api": 1, "depends": [{"id": "bb"}]})
    write(mods / "b" / "mod.json", {"id": "bb", "name": "B", "version": "1.0.0", "api": 1, "depends": [{"id": "aa"}]})
    mm = ModManager(mods)
    mm.discover()
    assert mm.resolve() == [] or all(m.id in ("aa", "bb") for m in mm.resolve())
    assert any("cycle" in r for r in mm.report)


def test_sample_mod_in_repo_loads():
    """The shipped sample mod must stay valid against the real game content kinds."""
    from shardlight.core.paths import EXAMPLES_DIR as MODS_DIR
    from shardlight.core.world import ECHO_SCHEMA
    db = ContentDB()
    db.register_kind("echo", ECHO_SCHEMA)
    db.register_kind("lore", {"title": {"type": "str", "required": True}, "text": {"type": "str", "required": True},
                              "shard": {"type": "str"}, "tags": {"type": "list", "items": {"type": "str"}}})
    from shardlight import modes as modes_pkg
    for mid in modes_pkg.MODE_IDS:
        mod = modes_pkg.load(mid)
        if mod is not None and hasattr(mod, "register_content"):
            mod.register_content(db)
    mm = ModManager(MODS_DIR)
    mm.discover()
    mm.apply(db)
    assert "sample_pack" in mm.loaded, mm.report
    assert db.get("echo", "sample_pack_wave") is not None
    for kind, eid in (("verdant.item", "sample_pack_charm"), ("verdant.recipe", "sample_pack_tea"), ("verdant.npc", "sample_pack_traveller"),
                      ("verdant.quest", "sample_pack_errand"), ("umbra.note", "sample_pack_note")):
        assert db.get(kind, eid) is not None, (kind, eid, db.problems[:3])
    assert not [p for p in db.problems if "sample_pack" in p], db.problems
