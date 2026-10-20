import json

import pytest

from shardlight.core import save as S


@pytest.fixture
def sm(tmp_path):
    return S.SaveManager(tmp_path)


def test_roundtrip(sm):
    p = S.new_profile("Ada")
    p["flags"]["x"] = True
    p["modes"]["cinder"] = {"v": 1, "best": 4}
    sm.write(0, p)
    q = sm.read(0)
    assert q["name"] == "Ada" and q["flags"]["x"] is True and q["modes"]["cinder"]["best"] == 4


def test_backup_rotation_keeps_three(sm):
    for i in range(6):
        p = S.new_profile(f"n{i}")
        sm.write(1, p)
    baks = sorted(f.name for f in sm.root.glob("slot1.bak*"))
    assert baks == ["slot1.bak1", "slot1.bak2", "slot1.bak3"]
    assert sm.read(1)["name"] == "n5"


def test_corrupt_primary_recovers_from_backup(sm):
    sm.write(0, S.new_profile("first"))
    sm.write(0, S.new_profile("second"))
    sm.path(0).write_text("{ this is not json", encoding="utf-8")
    p = sm.read(0)
    assert p["name"] == "first"
    assert sm.recovered and "restored from backup" in sm.recovered[0]
    assert sm.path(0).with_suffix(".corrupt").exists()


def test_tampered_payload_detected(sm):
    sm.write(0, S.new_profile("a"))
    sm.write(0, S.new_profile("b"))
    env = json.loads(sm.path(0).read_text())
    env["payload"]["currency"]["glint"] = 99999
    sm.path(0).write_text(json.dumps(env))
    assert sm.read(0)["name"] == "a"            # falls back to the last intact backup


def test_all_copies_corrupt_raises(sm):
    sm.write(0, S.new_profile())
    sm.path(0).write_text("garbage")
    with pytest.raises(S.SaveError):
        sm.read(0)


def test_migration_from_v1(sm):
    old = {"name": "Old", "created": 1, "playtime": 5, "seed": 3, "flags": {}, "counters": {}, "unlocks": [],
           "facets": [], "currency": {"glint": 3}, "reputation": [["lamplighters", 10]], "modes": {}}
    env = {"format": 1, "schema": 1, "sha256": S._digest(old), "payload": old}
    sm.path(2).write_text(json.dumps(env))
    p = sm.read(2)
    assert p["reputation"] == {"lamplighters": 10}
    assert p["lore"] == [] and p["tutorial"] == {} and p["echoes_fired"] == []


def test_newer_schema_refused(sm):
    p = S.new_profile()
    env = {"format": 1, "schema": S.SCHEMA_VERSION + 1, "sha256": S._digest(p), "payload": p}
    sm.path(0).write_text(json.dumps(env))
    with pytest.raises(S.SaveError):
        sm.read(0)


def test_no_tmp_left_and_summaries(sm):
    sm.write(0, S.new_profile("z"))
    assert not list(sm.root.glob("*.tmp"))
    summ = sm.summaries()
    assert summ[0]["name"] == "z" and summ[1] is None


def test_bad_slot(sm):
    with pytest.raises(S.SaveError):
        sm.path(9)
