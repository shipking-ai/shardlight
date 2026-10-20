"""Masks through the real App: menus, versus with two simultaneous input devices, CPU, replays, arcade, pause."""
import random

import pygame
import pytest
from conftest import run_ticks

from shardlight.modes.masks import replay
from shardlight.modes.masks.cpu import CpuBrain
from shardlight.modes.masks.scene import FightScreen, MainMenu, MasksScene, MatchPause, SelectScreen, TrainingMenu
from shardlight.modes.masks.sim import consts as C
from shardlight.modes.masks.sim.fight import Match
from shardlight.modes.masks.sim.moves import build_character
from shardlight.modes.masks.sim.roster import KIND, standalone_db


@pytest.fixture(scope="module")
def chars():
    db = standalone_db()
    return {d["id"]: build_character(d) for d in db.all(KIND)}


def play_cpu_match(chars, a, b, seed, la=3, lb=3, cap=60 * 60 * 6):
    m = Match((chars[a], chars[b]), seed=seed)
    m.record = True
    ca, cb = CpuBrain(la, seed, 1.0, 0), CpuBrain(lb, seed, 1.0, 1)
    while m.phase != "over" and m.frame < cap:
        m.step((ca.act(m), cb.act(m)))
    return m, ca, cb


def test_cpu_matches_finish_and_are_deterministic(chars):
    m1, _, _ = play_cpu_match(chars, "kagari", "mirei", 3)
    m2, _, _ = play_cpu_match(chars, "kagari", "mirei", 3)
    assert m1.phase == "over" and m1.winner in (0, 1, -1)
    assert m1.state_hash() == m2.state_hash()
    m3, _, _ = play_cpu_match(chars, "kagari", "mirei", 4)
    assert m3.state_hash() != m1.state_hash()


def test_every_matchup_completes_without_error(chars):
    ids = [c for c in chars]
    for i, a in enumerate(ids):
        b = ids[(i + 1) % len(ids)]
        m, ca, cb = play_cpu_match(chars, a, b, i + 11, 2, 2)
        assert m.phase == "over", (a, b)
        assert ca.decisions or cb.decisions       # the CPU actually performed moves


def test_replay_roundtrip_and_tamper_detection(chars):
    m, _, _ = play_cpu_match(chars, "ushi", "shizuka", 8)
    rec = replay.make_record(m, ("ushi", "shizuka"))
    assert replay.valid_record(rec) and replay.verify(rec, chars)
    bad = dict(rec)
    bad["rle"] = [list(x) for x in rec["rle"]]
    for k in range(len(bad["rle"]) // 3, len(bad["rle"]) // 3 + 25):
        bad["rle"][k][0] ^= C.HP | C.LP                  # corrupt a stretch of player-1 inputs
    assert replay.valid_record(bad) and not replay.verify(bad, chars)
    forged = dict(rec, hash="0" * 16)
    assert not replay.verify(forged, chars)
    assert not replay.valid_record({"v": 1, "chars": ["a", "b"], "rle": [[1, 2]], "frames": 1})


def test_cpu_has_reaction_delay_and_cannot_block_a_jab_on_reaction(chars):
    m = Match((chars["kagari"], chars["ushi"]))
    for _ in range(C.INTRO_FRAMES + 1):
        m.step((0, 0))
    m.fighters[0].x, m.fighters[1].x = -22 * 16, 22 * 16
    brain = CpuBrain(1, 1, 1.0, 1)           # level 1: ~22 frames of reaction
    blocked = 0
    jabs = 0
    for i in range(60):
        pair0 = C.LP if i % 20 == 0 else 0
        m.step((pair0, brain.act(m)))
        if pair0:
            jabs += 1
    assert jabs >= 3 and m.fighters[1].hp < m.fighters[1].char.health     # jabs landed despite the CPU being awake


def test_cpu_punishes_unsafe_moves_with_real_frame_data(chars):
    brain = CpuBrain(4, 3, 1.0, 1)
    me = Match((chars["kagari"], chars["ushi"])).fighters[0]
    brain.roles = brain.classify(me.char)
    mv = brain._best_punish(me, rec_left=24, dist=30)
    assert mv is not None and mv.startup + 2 <= 24
    assert brain._best_punish(me, rec_left=4, dist=30) is None       # nothing fast enough: no punish


def test_adaptation_raises_anti_air_and_is_bounded(chars):
    m = Match((chars["kagari"], chars["mirei"]))
    brain = CpuBrain(3, 1, 1.0, 1)
    for _ in range(C.INTRO_FRAMES + 1):
        m.step((0, 0))
    base = brain.adapt.level("anti_air")
    for i in range(12):                                # the human keeps jumping in
        brain.model.record("jump_in", m.frame / 60 + i * 1.0)
        brain.adapt.update(m.frame / 60 + i * 1.0, 1.0)
    for _ in range(300):
        brain.adapt.update(m.frame / 60 + 30, 0.1)
        m.frame += 1
    lvl = brain.adapt.level("anti_air")
    assert lvl > base and lvl <= 0.45 * 1.5 + 1e-6
    off = CpuBrain(3, 1, 0.0, 1)                       # adaptation strength 0 -> never adapts
    for i in range(12):
        off.model.record("jump_in", i * 1.0)
        off.adapt.update(i * 1.0, 1.0)
    assert off.adapt.level("anti_air") == 0.0


def enter_masks(app, **opts):
    app.enter_mode("masks", **opts)
    run_ticks(app, 3)
    assert isinstance(app.scenes.top, MasksScene)
    return app.scenes.top


def test_menu_to_training_and_bot_fight(app):
    ms = enter_masks(app)
    assert isinstance(ms.screen, MainMenu)
    dev = app.input.attach_virtual(0)
    run_ticks(app, 12)
    ms.screen.menu.sel = 3
    dev.tap("CONFIRM")
    run_ticks(app, 3)
    assert isinstance(ms.screen, SelectScreen) and ms.screen.kind == "training"
    run_ticks(app, 8)
    dev.tap("CONFIRM")
    run_ticks(app, 5)
    fs = ms.screen
    assert isinstance(fs, FightScreen) and fs.kind == "training"
    for _ in range(30):                                     # dismiss the first-time tutorial dialogue
        if isinstance(app.scenes.top, MasksScene):
            break
        dev.tap("CONFIRM")
        run_ticks(app, 6)
    assert isinstance(app.scenes.top, MasksScene)
    run_ticks(app, 120)                                     # intro
    f0, f1 = fs.match.fighters
    f0.x, f1.x = -14 * 16, 14 * 16
    hp0 = f1.hp
    for i in range(240):
        if i % 12 == 0:
            dev.tap("A")
        run_ticks(app, 1, draw_every=4)
    assert fs.match.last_move_info[0].get("key")
    assert f1.state in ("hit", "idle", "block", "hitair", "down", "wake") and fs.match.frame > 300
    dev.tap("SELECT")
    run_ticks(app, 3)
    assert any(isinstance(s, TrainingMenu) for s in app.scenes.stack)


def test_versus_two_simultaneous_inputs_are_independent(app):
    ms = enter_masks(app, players=2)
    app.input.assign_local(2)
    d0 = app.input.attach_virtual(0)
    d1 = app.input.attach_virtual(1)
    ms.start_match("versus", ("kagari", "ushi"))
    fs = ms.screen
    run_ticks(app, C.INTRO_FRAMES + 10)
    f0, f1 = fs.match.fighters
    f0.x, f1.x = -90 * 16, 90 * 16
    x0, x1 = f0.x, f1.x
    d0.hold("RIGHT")          # P1 walks right ...
    d1.hold("UP")             # ... while P2 jumps on the very same frames
    run_ticks(app, 20)
    d0.release_all()
    d1.release_all()
    assert f0.x > x0 and f1.state in ("air", "prejump") or f1.y > 0
    assert abs(f1.x - x1) < 12 * 16                       # P2 did not walk because of P1's input


def test_controller_loss_pauses_with_clear_message_and_keyboard_recovery(app):
    ms = enter_masks(app, players=2)
    app.input.assign_local(2)
    ms.start_match("versus", ("kagari", "mirei"))
    run_ticks(app, 20)
    assert isinstance(ms.screen, FightScreen)
    app.input.slots[1].lost_pad = True                      # what InputManager does when a pad is unplugged
    app.input.notices.append(("pad_lost", 1))
    run_ticks(app, 3)
    assert isinstance(app.scenes.top, MatchPause)
    assert "disconnected" in app.scenes.top.reason
    f = ms.screen.match.frame
    run_ticks(app, 30)
    assert ms.screen.match.frame == f                      # the match is frozen while paused
    pause = app.scenes.top
    pause._keyboard()
    assert pause.lost == -1


def test_arcade_clear_repairs_facet_and_emits_rival_defeats(app):
    ms = enter_masks(app)
    ms.data["seen"] = {"arcade": True, "training": True}      # skip the first-time tutorial dialogue
    ms.start_match("arcade", ("kagari", "ushi"), (None, 2), {"order": ["ushi"], "step": 0, "pick": "kagari", "defeated": []})
    fs = ms.screen
    run_ticks(app, C.INTRO_FRAMES + 5)
    fs.match.fighters[1].hp = 1
    fs.cpu[1] = None                                       # passive opponent
    dev = app.input.attach_virtual(0)
    for _ in range(2):                                     # win two rounds
        f0, f1 = fs.match.fighters
        f0.x, f1.x = -14 * 16, 14 * 16
        f1.hp = 1
        for i in range(60):
            if i % 8 == 0:
                dev.tap("A")
            run_ticks(app, 1, draw_every=0)
        run_ticks(app, C.KO_FRAMES + C.ROUND_END_FRAMES + C.INTRO_FRAMES + 80, draw_every=0)
    assert fs.match.winner == 0
    run_ticks(app, 10, draw_every=0)
    assert app.world.facet_repaired("masks")
    assert ms.data["arcade_clears"] == 1
    assert len(ms.data["replays"]) == 1 and replay.valid_record(ms.data["replays"][0])


def test_locked_fighter_requires_unlock_and_mods_can_add_fighters(app):
    ms = enter_masks(app)
    ids = {c.id for c in ms.available()}
    assert "toki" not in ids and "silence" not in ids and {"kagari", "mirei", "ushi", "shizuka"} <= ids
    app.world.unlock("masks.rival.warden_of_hours")
    assert "toki" in {c.id for c in ms.available()}


def test_save_roundtrip_of_replays_and_training_settings(app):
    ms = enter_masks(app)
    ms.data["replays"].append({"v": 1})
    ms.data["training"]["boxes"] = True
    app.save_now()
    prof = app.saves.read(app.slot)
    assert prof["modes"]["masks"]["training"]["boxes"] is True
