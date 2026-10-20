"""Unified input: keyboard schemes, SDL game controllers (hot-plug), virtual devices for tests/bots.

Gameplay code never sees raw keys.  Each *player slot* exposes logical buttons:

    UP DOWN LEFT RIGHT  A B X Y  L R  SELECT PAUSE  CONFIRM BACK

plus an analog ``move`` vector (left stick or digital directions) and ``aim`` vector (right stick).
Edge detection is exact per fixed update tick (``begin_tick``), so a tap shorter than one frame is
never lost and a long frame never double-fires.
"""
from __future__ import annotations

import copy
from collections import deque
from typing import Iterable

import pygame
from pygame import Vector2

from . import log

LOG = log.get("input")

BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "L", "R", "SELECT", "PAUSE", "CONFIRM", "BACK")
REMAPPABLE = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "L", "R", "SELECT", "PAUSE")

DEFAULT_BINDINGS: dict[str, dict[str, list[str]]] = {
    "kb1": {   # left-hand movement, right-hand actions
        "UP": ["w"], "DOWN": ["s"], "LEFT": ["a"], "RIGHT": ["d"],
        "A": ["j"], "B": ["k"], "X": ["u"], "Y": ["i"], "L": ["q"], "R": ["e"],
        "SELECT": ["tab"], "PAUSE": ["escape", "p"],
        "CONFIRM": ["return", "space", "j"], "BACK": ["escape", "backspace", "k"],
    },
    "kb2": {   # arrows + right-hand cluster; works on laptops without a numpad
        "UP": ["up"], "DOWN": ["down"], "LEFT": ["left"], "RIGHT": ["right"],
        "A": [","], "B": ["."], "X": ["m"], "Y": ["n"], "L": ["["], "R": ["]"],
        "SELECT": ["right shift"], "PAUSE": ["escape"],
        "CONFIRM": ["return", "keypad enter", ","], "BACK": ["escape", "."],
    },
    "pad": {
        "UP": ["dpup", "stick_up"], "DOWN": ["dpdown", "stick_down"],
        "LEFT": ["dpleft", "stick_left"], "RIGHT": ["dpright", "stick_right"],
        "A": ["a"], "B": ["b"], "X": ["x"], "Y": ["y"], "L": ["leftshoulder"], "R": ["rightshoulder"],
        "SELECT": ["back"], "PAUSE": ["start"], "CONFIRM": ["a"], "BACK": ["b"],
    },
}

_PAD_BUTTONS = {
    "a": "CONTROLLER_BUTTON_A", "b": "CONTROLLER_BUTTON_B", "x": "CONTROLLER_BUTTON_X",
    "y": "CONTROLLER_BUTTON_Y", "back": "CONTROLLER_BUTTON_BACK", "start": "CONTROLLER_BUTTON_START",
    "guide": "CONTROLLER_BUTTON_GUIDE", "leftstick": "CONTROLLER_BUTTON_LEFTSTICK",
    "rightstick": "CONTROLLER_BUTTON_RIGHTSTICK", "leftshoulder": "CONTROLLER_BUTTON_LEFTSHOULDER",
    "rightshoulder": "CONTROLLER_BUTTON_RIGHTSHOULDER", "dpup": "CONTROLLER_BUTTON_DPAD_UP",
    "dpdown": "CONTROLLER_BUTTON_DPAD_DOWN", "dpleft": "CONTROLLER_BUTTON_DPAD_LEFT",
    "dpright": "CONTROLLER_BUTTON_DPAD_RIGHT",
}
_PAD_BUTTON_BY_ID = {getattr(pygame, v): k for k, v in _PAD_BUTTONS.items()}

PAD_LABELS = {
    "xbox": {"a": "A", "b": "B", "x": "X", "y": "Y", "leftshoulder": "LB", "rightshoulder": "RB",
             "back": "View", "start": "Menu", "dpup": "D-Up", "dpdown": "D-Down", "dpleft": "D-Left",
             "dpright": "D-Right", "triggerleft": "LT", "triggerright": "RT"},
    "ps": {"a": "Cross", "b": "Circle", "x": "Square", "y": "Triangle", "leftshoulder": "L1",
           "rightshoulder": "R1", "back": "Share", "start": "Options", "dpup": "D-Up", "dpdown": "D-Down",
           "dpleft": "D-Left", "dpright": "D-Right", "triggerleft": "L2", "triggerright": "R2"},
    "switch": {"a": "B", "b": "A", "x": "Y", "y": "X", "leftshoulder": "L", "rightshoulder": "R",
               "back": "-", "start": "+", "dpup": "D-Up", "dpdown": "D-Down", "dpleft": "D-Left",
               "dpright": "D-Right", "triggerleft": "ZL", "triggerright": "ZR"},
}
PAD_LABELS["generic"] = PAD_LABELS["xbox"]


def pad_family(name: str) -> str:
    n = name.lower()
    if "xbox" in n or "xinput" in n:
        return "xbox"
    if any(s in n for s in ("playstation", "dualshock", "dualsense", "ps4", "ps5", "ps3")):
        return "ps"
    if any(s in n for s in ("nintendo", "switch", "pro controller", "joy-con")):
        return "switch"
    return "generic"


class Device:
    kind = "virtual"

    def __init__(self, dev_id: str, bindings: dict[str, list[str]]):
        self.id = dev_id
        self.bindings = bindings
        self.raw_down: set[str] = set()
        self.edge_down: set[str] = set()       # logical buttons pressed since last tick
        self.edge_up: set[str] = set()
        self.stick_l = Vector2()
        self.stick_r = Vector2()
        self.analog: dict[str, float] = {}
        # TODO(#3): dead zone and stick feel are untested on real hardware; verify on physical pads.
        self.deadzone = 0.25
        self.trigger_threshold = 0.5

    def set_bindings(self, bindings: dict[str, list[str]]) -> None:
        self.bindings = bindings

    def _logical_for(self, raw: str) -> list[str]:
        return [b for b, raws in self.bindings.items() if raw in raws]

    def raw_press(self, raw: str) -> None:
        if raw in self.raw_down:
            return
        self.raw_down.add(raw)
        self.edge_down.update(self._logical_for(raw))

    def raw_release(self, raw: str) -> None:
        if raw not in self.raw_down:
            return
        self.raw_down.discard(raw)
        self.edge_up.update(self._logical_for(raw))

    def logical_down(self) -> set[str]:
        down = {b for b, raws in self.bindings.items() if any(r in self.raw_down for r in raws)}
        return down

    def move_vector(self) -> Vector2:
        down = self.logical_down()
        v = Vector2((("RIGHT" in down) - ("LEFT" in down)), (("DOWN" in down) - ("UP" in down)))
        if v.length_squared() > 1:
            v.scale_to_length(1)
        if self.stick_l.length_squared() > 0:
            return Vector2(self.stick_l)
        return v

    def clear_edges(self) -> None:
        self.edge_down.clear()
        self.edge_up.clear()

    def label(self, button: str) -> str:
        raws = self.bindings.get(button, [])
        return raws[0].upper() if raws else "?"


class KeyboardDevice(Device):
    kind = "keyboard"


class VirtualDevice(Device):
    """Scripted device used by tests, bots, replays and demo recordings."""
    kind = "virtual"

    def __init__(self, dev_id: str = "virtual"):
        super().__init__(dev_id, {b: [b] for b in BUTTONS})

    def hold(self, *buttons: str) -> None:
        for b in buttons:
            self.raw_press(b)

    def release(self, *buttons: str) -> None:
        for b in buttons:
            self.raw_release(b)

    def release_all(self) -> None:
        for b in list(self.raw_down):
            self.raw_release(b)

    def tap(self, *buttons: str) -> None:
        for b in buttons:
            self.raw_press(b)
            self.raw_release(b)

    def set_stick(self, x: float, y: float) -> None:
        self.stick_l = Vector2(x, y)


class PadDevice(Device):
    kind = "gamepad"

    def __init__(self, instance_id: int, name: str, bindings: dict[str, list[str]], controller=None):
        super().__init__(f"pad{instance_id}", bindings)
        self.instance_id = instance_id
        self.name = name
        self.family = pad_family(name)
        self.controller = controller
        self.axes = {"leftx": 0.0, "lefty": 0.0, "rightx": 0.0, "righty": 0.0,
                     "triggerleft": 0.0, "triggerright": 0.0}

    def on_axis(self, axis: int, value: int) -> None:
        names = {pygame.CONTROLLER_AXIS_LEFTX: "leftx", pygame.CONTROLLER_AXIS_LEFTY: "lefty",
                 pygame.CONTROLLER_AXIS_RIGHTX: "rightx", pygame.CONTROLLER_AXIS_RIGHTY: "righty",
                 pygame.CONTROLLER_AXIS_TRIGGERLEFT: "triggerleft",
                 pygame.CONTROLLER_AXIS_TRIGGERRIGHT: "triggerright"}
        name = names.get(axis)
        if not name:
            return
        v = max(-1.0, min(1.0, value / 32767.0))
        self.axes[name] = v
        if name.startswith("trigger"):
            if v > self.trigger_threshold:
                self.raw_press(name)
            else:
                self.raw_release(name)
            return
        self._update_sticks()

    def _update_sticks(self) -> None:
        def radial(x: float, y: float) -> Vector2:
            vec = Vector2(x, y)
            m = vec.length()
            if m < self.deadzone:
                return Vector2()
            vec.scale_to_length(min(1.0, (m - self.deadzone) / (1 - self.deadzone)))
            return vec

        self.stick_l = radial(self.axes["leftx"], self.axes["lefty"])
        self.stick_r = radial(self.axes["rightx"], self.axes["righty"])
        # digital direction presses from the left stick so menus work with it
        for raw, active in (("stick_up", self.stick_l.y < -0.5), ("stick_down", self.stick_l.y > 0.5),
                            ("stick_left", self.stick_l.x < -0.5), ("stick_right", self.stick_l.x > 0.5)):
            (self.raw_press if active else self.raw_release)(raw)

    def label(self, button: str) -> str:
        raws = self.bindings.get(button, [])
        if not raws:
            return "?"
        return PAD_LABELS[self.family].get(raws[0], raws[0])


class PlayerState:
    """What a game mode reads for one player slot."""

    def __init__(self, slot: int):
        self.slot = slot
        self.devices: list[Device] = []
        self.down: set[str] = set()
        self.pressed: set[str] = set()
        self.released: set[str] = set()
        self.move = Vector2()
        self.aim = Vector2()
        self.last_kind = "keyboard"       # which device family the player touched last (for prompts)
        self.last_device: Device | None = None
        self.lost_pad = False             # controller assigned to this slot was unplugged
        self.frame = 0
        self._press_frame: dict[str, int] = {}
        self._prev_down: set[str] = set()

    # -- per tick -------------------------------------------------------------------------
    def tick(self) -> None:
        self.frame += 1
        cur: set[str] = set()
        edge_d: set[str] = set()
        edge_u: set[str] = set()
        move = Vector2()
        aim = Vector2()
        for d in self.devices:
            ld = d.logical_down()
            cur |= ld
            edge_d |= d.edge_down
            edge_u |= d.edge_up
            if d.edge_down or ld:
                self.last_kind = d.kind if d.kind != "virtual" else self.last_kind
                self.last_device = d
            m = d.move_vector()
            if m.length_squared() > move.length_squared():
                move = m
            if d.stick_r.length_squared() > aim.length_squared():
                aim = d.stick_r
            d.clear_edges()
        self.pressed = edge_d | (cur - self._prev_down)
        self.released = edge_u | (self._prev_down - cur)
        self.down = cur
        self._prev_down = set(cur)
        self.move = move
        self.aim = aim
        for b in self.pressed:
            self._press_frame[b] = self.frame

    # -- queries --------------------------------------------------------------------------
    def held(self, b: str) -> bool:
        return b in self.down

    def just_pressed(self, b: str) -> bool:
        return b in self.pressed

    def just_released(self, b: str) -> bool:
        return b in self.released

    def any_pressed(self, buttons: Iterable[str]) -> bool:
        return any(b in self.pressed for b in buttons)

    def buffered(self, b: str, frames: int = 6, consume: bool = True) -> bool:
        """True if ``b`` was pressed within the last ``frames`` ticks (input buffering)."""
        f = self._press_frame.get(b)
        if f is not None and self.frame - f <= frames:
            if consume:
                self._press_frame[b] = -10_000
            return True
        return False

    def prompt(self, button: str) -> str:
        """Display label for ``button`` on whichever device the player used last."""
        for d in self.devices:
            if d is self.last_device:
                return d.label(button)
        for d in self.devices:
            if d.kind == self.last_kind:
                return d.label(button)
        return self.devices[0].label(button) if self.devices else "?"

    def menu_dir(self) -> tuple[int, int]:
        """Edge-triggered menu navigation (-1/0/1 per axis)."""
        return (int("RIGHT" in self.pressed) - int("LEFT" in self.pressed),
                int("DOWN" in self.pressed) - int("UP" in self.pressed))


class InputManager:
    def __init__(self, settings=None):
        self.settings = settings
        self.keyboards = {"kb1": KeyboardDevice("kb1", self._bindings("kb1")),
                          "kb2": KeyboardDevice("kb2", self._bindings("kb2"))}
        self.pads: dict[int, PadDevice] = {}
        self.slots: list[PlayerState] = [PlayerState(i) for i in range(4)]
        self.notices: deque[tuple[str, int]] = deque(maxlen=32)   # ("pad_lost"|"pad_found", slot)
        self.mouse_pos = (0, 0)
        self.mouse_pressed: set[int] = set()
        self.mouse_down: set[int] = set()
        self._pend_mouse: set[int] = set()
        self.wheel = 0
        self._pend_wheel = 0
        self.text_input: list[str] = []
        self.raw_key_events: list[pygame.event.Event] = []
        self.capture_next: bool = False        # used by the remap UI
        self.captured: tuple[str, str] | None = None     # (device kind, raw name)
        self.num_players = 1
        self._controller_ok = False
        self._controllers: dict[int, object] = {}
        self.assign_local(1)

    # -- setup ----------------------------------------------------------------------------
    def _bindings(self, scheme: str) -> dict[str, list[str]]:
        b = copy.deepcopy(DEFAULT_BINDINGS[scheme])
        if self.settings is not None:
            over = self.settings.get("input.bindings").get(scheme, {})
            for k, v in over.items():
                if k in b and isinstance(v, list) and all(isinstance(x, str) for x in v):
                    b[k] = v
        return b

    def rebind(self, scheme: str, button: str, raw: str) -> None:
        """Bind ``raw`` as the only input for ``button`` on ``scheme`` and persist in settings."""
        base = copy.deepcopy(DEFAULT_BINDINGS[scheme])
        cur = self.keyboards[scheme].bindings if scheme in self.keyboards else \
            next((p.bindings for p in self.pads.values()), base)
        cur[button] = [raw]
        if self.settings is not None:
            self.settings.get("input.bindings").setdefault(scheme, {})[button] = [raw]
            self.settings.dirty = True
        for p in self.pads.values():
            if scheme == "pad":
                p.bindings = cur

    def reset_bindings(self) -> None:
        for name, kb in self.keyboards.items():
            kb.bindings = copy.deepcopy(DEFAULT_BINDINGS[name])
        for p in self.pads.values():
            p.bindings = copy.deepcopy(DEFAULT_BINDINGS["pad"])
        if self.settings is not None:
            self.settings.data["input"]["bindings"] = {}
            self.settings.dirty = True

    def init_controllers(self) -> None:
        try:
            from pygame._sdl2 import controller
            controller.init()
            self._controller_ok = True
            for i in range(controller.get_count()):
                if controller.is_controller(i):
                    self._add_pad(i)
        except Exception as exc:  # no controller subsystem: keyboard-only is fine
            LOG.warning("controller support unavailable: %s", exc)

    def _add_pad(self, device_index: int) -> None:
        from pygame._sdl2 import controller
        try:
            c = controller.Controller(device_index)
            inst = c.as_joystick().get_instance_id()
            name = c.name
        except Exception as exc:
            LOG.warning("failed to open controller %s: %s", device_index, exc)
            return
        if inst in self.pads:
            return
        dev = PadDevice(inst, name, copy.deepcopy(DEFAULT_BINDINGS["pad"]), c)
        if self.settings is not None:
            dev.deadzone = float(self.settings.get("input.deadzone"))
            dev.trigger_threshold = float(self.settings.get("input.trigger_threshold"))
            for k, v in self.settings.get("input.bindings").get("pad", {}).items():
                if k in dev.bindings and isinstance(v, list):
                    dev.bindings[k] = v
        self.pads[inst] = dev
        self._attach_pad(dev)
        LOG.info("controller connected: %s (%s)", name, dev.family)

    def _attach_pad(self, dev: PadDevice) -> None:
        # reclaim a slot that lost its controller first, else the first slot lacking a pad
        order = [s for s in self.slots[:max(self.num_players, 1)] if s.lost_pad]
        order += [s for s in self.slots[:max(self.num_players, 1)] if not any(
            d.kind == "gamepad" for d in s.devices)]
        slot = order[0] if order else self.slots[0]
        slot.devices.append(dev)
        slot.lost_pad = False
        self.notices.append(("pad_found", slot.slot))

    def assign_local(self, n: int) -> None:
        """Configure ``n`` local players. P1 = kb1 (+kb2 if solo) (+first pad); P2 = kb2 or a pad..."""
        self.num_players = n
        for s in self.slots:
            s.devices = [d for d in s.devices if d.kind == "virtual"]
            s.lost_pad = False
        pads = list(self.pads.values())
        if n == 1:
            self.slots[0].devices += [self.keyboards["kb1"], self.keyboards["kb2"], *pads]
            return
        self.slots[0].devices.append(self.keyboards["kb1"])
        self.slots[1].devices.append(self.keyboards["kb2"])
        # pads fill players in order, so with two pads each player uses their own controller
        for i, pad in enumerate(pads[:n]):
            self.slots[i].devices.append(pad)

    def attach_virtual(self, slot: int, dev: VirtualDevice | None = None) -> VirtualDevice:
        dev = dev or VirtualDevice(f"virtual{slot}")
        self.slots[slot].devices.append(dev)
        return dev

    def detach_virtual(self, slot: int) -> None:
        self.slots[slot].devices = [d for d in self.slots[slot].devices if d.kind != "virtual"]

    def player(self, slot: int = 0) -> PlayerState:
        return self.slots[slot]

    # -- event pump -----------------------------------------------------------------------
    def process(self, events: Iterable[pygame.event.Event]) -> None:
        for e in events:
            t = e.type
            if t == pygame.KEYDOWN:
                name = pygame.key.name(e.key)
                if self.capture_next and self.captured is None:
                    self.captured = ("keyboard", name)
                self.raw_key_events.append(e)
                for kb in self.keyboards.values():
                    kb.raw_press(name)
                if e.unicode and e.unicode.isprintable():
                    self.text_input.append(e.unicode)
            elif t == pygame.KEYUP:
                name = pygame.key.name(e.key)
                for kb in self.keyboards.values():
                    kb.raw_release(name)
            elif t == pygame.CONTROLLERBUTTONDOWN:
                dev = self.pads.get(e.instance_id)
                name = _PAD_BUTTON_BY_ID.get(e.button)
                if dev and name:
                    if self.capture_next and self.captured is None:
                        self.captured = ("gamepad", name)
                    dev.raw_press(name)
            elif t == pygame.CONTROLLERBUTTONUP:
                dev = self.pads.get(e.instance_id)
                name = _PAD_BUTTON_BY_ID.get(e.button)
                if dev and name:
                    dev.raw_release(name)
            elif t == pygame.CONTROLLERAXISMOTION:
                dev = self.pads.get(e.instance_id)
                if dev:
                    dev.on_axis(e.axis, e.value)
            elif t == pygame.CONTROLLERDEVICEADDED:
                self._add_pad(e.device_index)
            elif t == pygame.CONTROLLERDEVICEREMOVED:
                self._remove_pad(e.instance_id)
            elif t == pygame.MOUSEBUTTONDOWN:
                self._pend_mouse.add(e.button)
                self.mouse_down.add(e.button)
            elif t == pygame.MOUSEBUTTONUP:
                self.mouse_down.discard(e.button)
            elif t == pygame.MOUSEWHEEL:
                self._pend_wheel += e.y
            elif t == pygame.WINDOWFOCUSLOST:
                self.release_everything()
        self.mouse_pos = pygame.mouse.get_pos()

    def _remove_pad(self, instance_id: int) -> None:
        dev = self.pads.pop(instance_id, None)
        if dev is None:
            return
        LOG.info("controller removed: %s", dev.name)
        for s in self.slots:
            if dev in s.devices:
                s.devices.remove(dev)
                s.lost_pad = True
                self.notices.append(("pad_lost", s.slot))
                # keyboard-only slots with no other device would be dead; keep at least a keyboard
                if not s.devices and s.slot == 0:
                    s.devices += [self.keyboards["kb1"], self.keyboards["kb2"]]
                    s.lost_pad = False

    def release_everything(self) -> None:
        for d in [*self.keyboards.values(), *self.pads.values()]:
            for r in list(d.raw_down):
                d.raw_release(r)
        self.mouse_down.clear()

    def begin_tick(self) -> None:
        for s in self.slots:
            s.tick()
        self.mouse_pressed = set(self._pend_mouse)
        self._pend_mouse.clear()
        self.wheel = self._pend_wheel
        self._pend_wheel = 0

    def end_frame(self) -> None:
        self.text_input.clear()
        self.raw_key_events.clear()

    # -- helpers --------------------------------------------------------------------------
    def any_confirm(self) -> bool:
        return any("CONFIRM" in s.pressed for s in self.slots[:self.num_players])

    def pop_notices(self) -> list[tuple[str, int]]:
        out = list(self.notices)
        self.notices.clear()
        return out

    def begin_capture(self) -> None:
        self.capture_next = True
        self.captured = None

    def end_capture(self) -> tuple[str, str] | None:
        res = self.captured
        self.capture_next = False
        self.captured = None
        return res
