import pygame
import pytest

from shardlight.core.input import (DEFAULT_BINDINGS, InputManager, PadDevice, VirtualDevice, pad_family)


def key_event(down: bool, key: int):
    return pygame.event.Event(pygame.KEYDOWN if down else pygame.KEYUP, key=key, unicode="", mod=0)


@pytest.fixture
def inp():
    pygame.init()
    return InputManager()


def make_pad(inp, iid=5, name="Xbox Wireless Controller"):
    dev = PadDevice(iid, name, {k: list(v) for k, v in DEFAULT_BINDINGS["pad"].items()})
    inp.pads[iid] = dev
    inp._attach_pad(dev)
    return dev


def test_keyboard_edges_and_hold(inp):
    inp.process([key_event(True, pygame.K_j)])
    inp.begin_tick()
    p = inp.player(0)
    assert p.just_pressed("A") and p.held("A") and p.just_pressed("CONFIRM")
    inp.begin_tick()
    assert not p.just_pressed("A") and p.held("A")
    inp.process([key_event(False, pygame.K_j)])
    inp.begin_tick()
    assert p.just_released("A") and not p.held("A")


def test_tap_shorter_than_a_tick_is_not_lost(inp):
    inp.process([key_event(True, pygame.K_k), key_event(False, pygame.K_k)])
    inp.begin_tick()
    p = inp.player(0)
    assert p.just_pressed("B") and not p.held("B")


def test_two_players_use_separate_schemes(inp):
    inp.assign_local(2)
    inp.process([key_event(True, pygame.K_j), key_event(True, pygame.K_COMMA), key_event(True, pygame.K_LEFT)])
    inp.begin_tick()
    p1, p2 = inp.player(0), inp.player(1)
    assert p1.held("A") and not p1.held("LEFT")
    assert p2.held("A") and p2.held("LEFT") and p2.move.x < 0


def test_solo_accepts_both_schemes(inp):
    inp.process([key_event(True, pygame.K_UP), key_event(True, pygame.K_a)])
    inp.begin_tick()
    p = inp.player(0)
    assert p.held("UP") and p.held("LEFT")
    assert p.move.length() <= 1.0001


def test_buffering(inp):
    p = inp.player(0)
    inp.process([key_event(True, pygame.K_u)])
    inp.begin_tick()
    inp.process([key_event(False, pygame.K_u)])
    for _ in range(4):
        inp.begin_tick()
    assert p.buffered("X", 6)
    assert not p.buffered("X", 6)          # consumed
    inp.process([key_event(True, pygame.K_u)])
    inp.begin_tick()
    inp.process([key_event(False, pygame.K_u)])
    for _ in range(10):
        inp.begin_tick()
    assert not p.buffered("X", 6)          # too old


def test_gamepad_buttons_stick_deadzone_and_prompts(inp):
    pad = make_pad(inp)
    inp.process([pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=5, button=pygame.CONTROLLER_BUTTON_A)])
    inp.begin_tick()
    p = inp.player(0)
    assert p.just_pressed("A") and p.last_kind == "gamepad"
    assert p.prompt("A") == "A"
    inp.process([pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=5,
                                    axis=pygame.CONTROLLER_AXIS_LEFTX, value=3000)])   # inside deadzone
    inp.begin_tick()
    assert p.move.length() == 0
    inp.process([pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=5,
                                    axis=pygame.CONTROLLER_AXIS_LEFTX, value=32767)])
    inp.begin_tick()
    assert p.move.x > 0.99 and p.held("RIGHT")
    assert pad_family("PS5 DualSense Wireless") == "ps"
    pad.family = "ps"
    assert p.prompt("A") == "Cross"


def test_hotplug_removal_marks_slot_lost_and_reclaims(inp):
    inp.assign_local(2)
    pad0 = make_pad(inp, 1)
    pad1 = make_pad(inp, 2)
    inp.notices.clear()
    slot_of_pad1 = next(s for s in inp.slots if pad1 in s.devices).slot
    inp.process([pygame.event.Event(pygame.CONTROLLERDEVICEREMOVED, instance_id=2)])
    assert ("pad_lost", slot_of_pad1) in inp.pop_notices()
    assert inp.slots[slot_of_pad1].lost_pad or slot_of_pad1 == 0
    new = make_pad(inp, 3)
    assert any(new in s.devices for s in inp.slots)


def test_virtual_device_drives_a_slot(inp):
    dev = inp.attach_virtual(1)
    inp.assign_local(2) if False else None
    dev.hold("A", "LEFT")
    inp.begin_tick()
    assert inp.player(1).held("A") and inp.player(1).move.x < 0
    dev.release_all()
    inp.begin_tick()
    assert not inp.player(1).held("A")


def test_remap_capture_and_reset():
    class FakeSettings:
        def __init__(self):
            self.data = {"input": {"bindings": {}}}
            self.dirty = False

        def get(self, k):
            return {"input.bindings": self.data["input"]["bindings"], "input.deadzone": 0.25,
                    "input.trigger_threshold": 0.5}[k]

    st = FakeSettings()
    pygame.init()
    inp = InputManager(st)
    inp.begin_capture()
    inp.process([key_event(True, pygame.K_h)])
    kind, raw = inp.end_capture()
    assert (kind, raw) == ("keyboard", "h")
    inp.rebind("kb1", "A", raw)
    assert inp.keyboards["kb1"].bindings["A"] == ["h"]
    assert st.data["input"]["bindings"]["kb1"]["A"] == ["h"]
    inp2 = InputManager(st)                 # persisted override is applied on next start
    assert inp2.keyboards["kb1"].bindings["A"] == ["h"]
    inp.reset_bindings()
    assert inp.keyboards["kb1"].bindings["A"] == DEFAULT_BINDINGS["kb1"]["A"]


def test_focus_loss_releases_everything(inp):
    inp.process([key_event(True, pygame.K_d)])
    inp.begin_tick()
    assert inp.player(0).held("RIGHT")
    inp.process([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
    inp.begin_tick()
    assert not inp.player(0).held("RIGHT")
