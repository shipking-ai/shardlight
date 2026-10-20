from shardlight.core.save import new_profile


def test_new_profile_has_tour():
    p = new_profile("x")
    assert p["tour"] == {"leg": 0, "done_legs": [], "done": False}
