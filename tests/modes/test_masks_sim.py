"""Deterministic combat core: frame data, blocking, throws, parry, combos, projectiles, zones, rounds."""
import random

import pytest

from shardlight.modes.masks.sim import consts as C
from shardlight.modes.masks.sim.fight import Match
from shardlight.modes.masks.sim.moves import build_character
from shardlight.modes.masks.sim.roster import KIND, standalone_db
from shardlight.modes.masks.sim.validate import validate_character

R, L, U, D = C.RIGHT, C.LEFT, C.UP, C.DOWN
LP, MP, HP, PAR = C.LP, C.MP, C.HP, C.PAR


@pytest.fixture(scope="module")
def chars():
    db = standalone_db()
    out = {d["id"]: build_character(d) for d in db.all(KIND)}
    assert len(out) >= 6
    return out


def fight(chars, a="kagari", b="ushi", gap=40, **kw):
    m = Match((chars[a], chars[b]), **kw)
    for _ in range(C.INTRO_FRAMES + 1):
        m.step((0, 0))
    assert m.phase == "fight"
    m.fighters[0].x = -gap * 8
    m.fighters[1].x = gap * 8
    return m


def run(m, seq0=(), seq1=(), n=None):
    n = n or max(len(seq0), len(seq1))
    for i in range(n):
        m.step((seq0[i] if i < len(seq0) else 0, seq1[i] if i < len(seq1) else 0))


def ev(m, kind):
    return [e for e in m.events if e[0] == kind]


def first_event_frame(m, kind, seq0, seq1=(), limit=120):
    for i in range(limit):
        m.step((seq0[i] if i < len(seq0) else 0, seq1[i] if i < len(seq1) else 0))
        if ev(m, kind):
            return i
    return None


def test_all_characters_pass_frame_data_validation(chars):
    for ch in chars.values():
        assert validate_character(ch) == [], ch.id


def test_roster_has_distinct_archetypes(chars):
    assert {c.archetype for c in chars.values()} >= {"rushdown", "zoner", "grappler", "counter", "time", "boss"}
    assert any(m.projectile for m in chars["mirei"].moves.values())
    assert any(m.throw and not m.throw.tech for m in chars["ushi"].moves.values())
    assert any(m.counter for m in chars["shizuka"].moves.values())
    assert any(m.zone for m in chars["toki"].moves.values()) and any(m.echo for m in chars["toki"].moves.values())


def test_startup_frames_match_data(chars):
    m = fight(chars, "kagari", "ushi")
    mv = chars["kagari"].moves["5L"]
    i = first_event_frame(m, "hit", [LP])
    assert i == mv.startup - 1               # the press frame is frame 1 of the move


def test_hit_advantage_is_recorded_for_frame_data_display(chars):
    m = fight(chars, "kagari", "ushi")
    mv = chars["kagari"].moves["5L"]
    run(m, [LP], n=mv.startup)
    assert m.last_move_info[0]["adv_hit"] == mv.adv_on(True)


def test_block_requires_correct_height(chars):
    low = chars["kagari"].moves["2M"]
    assert low.hit.height == "low"
    m = fight(chars, "kagari", "ushi")
    run(m, [D | MP] + [D] * 20, [R] * 40)            # standing block (back = right for the P2 side) loses to a low
    assert m.fighters[1].hp < m.fighters[1].char.health
    m2 = fight(chars, "kagari", "ushi")
    run(m2, [D | MP] + [D] * 20, [D | R] * 40)       # crouch block
    assert m2.fighters[1].hp == m2.fighters[1].char.health


def test_throw_beats_block_and_can_be_teched(chars):
    m = fight(chars, "kagari", "ushi", gap=22)
    run(m, [LP | MP] + [0] * 80, [R] * 82)
    assert m.fighters[1].hp < m.fighters[1].char.health
    m2 = fight(chars, "kagari", "ushi", gap=22)
    run(m2, [LP | MP] + [0] * 40, [0, LP | MP] + [0] * 40)
    assert m2.fighters[1].hp == m2.fighters[1].char.health          # teched, no damage


def test_parry_punishes_attacker_and_spam_is_penalised(chars):
    m = fight(chars, "kagari", "mirei")
    parried = 0
    for i in range(14):
        m.step((LP if i == 0 else 0, PAR if i < 2 else 0))
        parried += len(ev(m, "parry"))
    assert parried == 1 and m.fighters[1].hp == m.fighters[1].char.health
    assert m.fighters[0].state == "block"             # attacker is held in recoil
    m2 = fight(chars, "kagari", "mirei", gap=120)
    durations = []
    for _ in range(3):
        m2.step((0, PAR))
        t = 1
        while m2.fighters[1].state == "parry" and t < 300:
            m2.step((0, 0))
            t += 1
        durations.append(t)
        for _ in range(4):
            m2.step((0, 0))
    assert m2.fighters[1].parry_tries == 3
    assert durations[0] < durations[1] < durations[2]       # whiffed parries get progressively more punishing
    assert durations[2] - durations[0] >= C.PARRY_PENALTY


def test_combo_proration_and_damage_cap(chars):
    m = fight(chars, "kagari", "ushi")
    d = m.fighters[1]
    seq = [LP] + [0] * 3 + [MP] + [0] * 15 + [HP] + [0] * 24      # L > M > H chain: a real combo
    run(m, seq, [0] * len(seq))
    assert d.combo_hits == 3
    raw = sum(chars["kagari"].moves[k].hit.damage for k in ("5L", "5M", "5H"))
    assert 0 < d.combo_dmg < raw                      # the third hit is prorated
    assert d.combo_dmg <= C.COMBO_DAMAGE_CAP


def test_projectile_travels_hits_and_is_limited(chars):
    m = fight(chars, "mirei", "kagari", gap=100)
    run(m, [D, D | R, R | LP] + [0] * 100, [0] * 103)
    assert m.fighters[1].hp < m.fighters[1].char.health
    m2 = fight(chars, "mirei", "kagari", gap=200)
    seq = [D, D | R, R | LP] + [0] * 20 + [D, D | R, R | LP] + [0] * 10
    run(m2, seq, [0] * len(seq))
    assert sum(1 for p in m2.projs if p.mkey == "needleL") <= 1


def test_zone_slows_opponent_only(chars):
    m = fight(chars, "toki", "kagari", gap=90)
    run(m, [D, D | R, R | LP] + [0] * 30, [0] * 33)
    assert m.zones, "Slow Hour should create a zone"
    m.fighters[1].x = m.zones[0].x
    slowed_opp = slowed_self = 0
    for _ in range(60):
        m.step((0, 0))
        slowed_opp += int(m.fighters[1].slowed)
        slowed_self += int(m.fighters[0].slowed)
    assert slowed_opp >= 10 and slowed_self == 0


def test_counter_stance_answers_matching_height(chars):
    m = fight(chars, "kagari", "shizuka", gap=34)
    run(m, [], [D, D | R, R | MP])                    # River Stance: counters mid attacks (P2 faces left; back = RIGHT)
    run(m, [0] * 2, [0] * 2)
    run(m, [LP], [0])
    for _ in range(40):
        m.step((0, 0))
    assert m.fighters[1].hp == m.fighters[1].char.health         # answered, not hit
    assert m.fighters[0].hp < m.fighters[0].char.health          # and punished


def test_super_requires_and_spends_meter(chars):
    seq = [D, D | R, R, D, D | R, R | HP]
    m = fight(chars, "kagari", "ushi", gap=90)
    run(m, seq, [0] * len(seq))
    assert m.fighters[0].meter == 0 and not (m.fighters[0].move and m.fighters[0].move.kind == "super")
    m2 = fight(chars, "kagari", "ushi", gap=90)
    m2.fighters[0].meter = 500
    run(m2, seq, [0] * len(seq))
    assert m2.fighters[0].meter < 500


def test_ko_round_and_match_flow(chars):
    m = fight(chars, "kagari", "ushi", gap=30)
    m.fighters[1].hp = 5
    run(m, [LP] + [0] * 30, [0] * 31)
    assert m.phase in ("ko", "roundend") and m.wins[0] == 1
    for _ in range(C.KO_FRAMES + C.ROUND_END_FRAMES + C.INTRO_FRAMES + 5):
        m.step((0, 0))
    assert m.round_no == 2 and m.phase in ("intro", "fight")
    for _ in range(C.INTRO_FRAMES + 2):
        m.step((0, 0))
    m.fighters[1].hp = 3
    m.fighters[0].x, m.fighters[1].x = -240, 240
    run(m, [LP] + [0] * 20, [0] * 21)
    for _ in range(C.KO_FRAMES + C.ROUND_END_FRAMES + 5):
        m.step((0, 0))
    assert m.winner == 0 and m.phase == "over"


def test_timeout_awards_round_to_higher_health(chars):
    m = fight(chars, "kagari", "ushi", round_frames=60)
    m.fighters[1].hp -= 100
    for _ in range(80):
        m.step((0, 0))
    assert m.round_winner == 0


def test_determinism_over_random_inputs(chars):
    def play(seed):
        rng = random.Random(seed)
        m = Match((chars["kagari"], chars["toki"]), seed=seed)
        for _ in range(2500):
            m.step((rng.choice([0, R, L, D, U, LP, MP, HP, R | LP, D | R | MP, PAR]),
                    rng.choice([0, R, L, D, U, LP, MP, HP, L | HP, D | L | LP, PAR])))
        return m.state_hash()
    for seed in (1, 2, 3):
        assert play(seed) == play(seed)
    assert play(1) != play(2)


def test_every_character_pair_survives_random_play(chars):
    ids = list(chars)
    for i, a in enumerate(ids):
        b = ids[(i + 2) % len(ids)]
        rng = random.Random(i)
        m = Match((chars[a], chars[b]), seed=i)
        for _ in range(1500):
            m.step((rng.randrange(0, 256), rng.randrange(0, 256)))
        for f in m.fighters:
            assert 0 <= f.hp <= f.char.health and abs(f.x) <= C.STAGE_HALF and f.y >= 0
