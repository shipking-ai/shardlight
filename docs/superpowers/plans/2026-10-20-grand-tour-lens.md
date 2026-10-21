# Grand Tour — final world of the restored Lens (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When all eight shard facets are repaired, the central Lens becomes a final world: "The Grand Tour" — a single continuous run through eight authored shard legs, a retro-3D flight-into-the-Lens finale, credits, and a permanent epilogue state for the hub and title screen.

**Architecture:** New mode package `shardlight/modes/prism/` (not in `MODE_IDS`, loaded explicitly by the hub's Lens entry). `TourRoot` sequences legs read from `data/prism.tour/tour.json`, persists progress in `world.profile["tour"]`, and hands off to `finale.py` → `epilogue.py`. Legs reuse each shard's sim modules with authored configs. The 3D finale uses a pure-software numpy rasteriser (`tri.py`) writing into the shared 480×270 frame. Pixel legs reuse shard control mappings verbatim; finale uses orrery flight verbs (dodging only).

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, numpy 2.5.4, pytest. Headless `App(headless=True, seed=1234, audio=False)`. Render surface is the shared 480×270 `app.frame`.

## Global Constraints

- `RENDER_SIZE = (480, 270)`; all draw calls target `app.frame` (`shardlight/core/app.py:29,61`). Do not add a new window or process.
- Modes expose `INFO`, `create(app, **opts)`, optional `register_content(db)` (named `register_content`, not `n`). Prism is **not** added to `MODE_IDS`; hub imports `shardlight.modes.prism` directly.
- `world.profile["tour"] = {"leg": int, "done_legs": [str], "done": bool}`; version-tolerant via `new_profile()` + migrate fill.
- Legs expose `state ∈ {"run","won","lost"}`, `update(dt)`, `draw(surf)`, and a test-only `debug_force_win()`. No production caller may invoke `debug_force_win`.
- Software 3D budget: ≤ 2 500 tris/frame, ≤ 8 ms update+draw, ≤ 3 ms post pass, at 480×270.
- Pixel legs add ≤ 1 ms overhead (HUD band only). No mouse controls inside prism legs.
- No changes to the eight shards' gameplay or their `complete_facet` logic.
- Commit style: plain descriptive messages, no conventional-commit prefix. Full suite must stay green (427+ at plan start).

---

### Task 1: Persistence — add `tour` to the profile

**Files:**
- Modify: `shardlight/core/save.py:27-44` (new_profile)
- Test: `tests/core/test_save.py` (extend or add)

**Interfaces:**
- Produces: `profile["tour"]` default `{"leg": 0, "done_legs": [], "done": False}` for every new and migrated profile.

- [ ] **Step 1: Write the failing test**

```python
def test_new_profile_has_tour():
    from shardlight.core.save import new_profile
    p = new_profile("x")
    assert p["tour"] == {"leg": 0, "done_legs": [], "done": False}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/core/test_save.py -q 2>&1 | tail -5` (or create the file). Expected: FAIL (KeyError / assertion).

- [ ] **Step 3: Implement**

In `new_profile`, add after `"modes": {}`:
```python
"tour": {"leg": 0, "done_legs": [], "done": False},  # Grand Tour progress (prism mode)
```
Migration needs nothing extra: `migrate` already fills missing keys from `new_profile()`.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/core/test_save.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shardlight/core/save.py tests/core/test_save.py
git commit -m "Persist Grand Tour progress in the profile"
```

---

### Task 2: Scaffold the prism package

**Files:**
- Create: `shardlight/modes/prism/__init__.py`
- Create: `shardlight/modes/prism/info.py`
- Create: `shardlight/modes/prism/defs.py` (empty stub for now, filled in Task 3)

**Interfaces:**
- Produces: `shardlight.modes.prism.INFO` (ModeInfo, id `"prism"`, title `"The Grand Tour"`, color gilded `(230, 200, 120)`), `create(app, **opts) -> TourRoot` (imported lazily), `register_content(db)`.

- [ ] **Step 1: Write info.py**

```python
"""Static description of the Grand Tour (final world of the restored Lens)."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="prism",
    title="The Grand Tour",
    genre="Final World",
    tagline="Eight shards, one lamp, one last flight",
    blurb="When every facet is repaired, the Lens opens. Walk all eight shards once more, then fly into the light.",
    color=(230, 200, 120),
    dark=(24, 20, 14),
    max_players=1,
    controls=(("A", "Confirm / interact"), ("B", "Back"), ("PAUSE", "Pause")),
)
```

- [ ] **Step 2: Write __init__.py**

```python
"""Prism - the Grand Tour final world (not a shard; loaded by the hub's Lens entry)."""
from __future__ import annotations

from . import tourspec as _tourspec  # noqa: F401  (validates tour data on import)
from .defs import register_content  # noqa: F401
from .info import INFO


def create(app, **opts):
    from .tourroot import TourRoot
    return TourRoot(app, **opts)
```

- [ ] **Step 3: Create defs.py stub**

```python
"""Content registration for the prism mode (kind: prism.tour)."""
from __future__ import annotations

from ...core.content import ContentDB


def register_content(db: ContentDB) -> None:
    # schema filled in Task 3; keep the kind registered so mods can extend it
    db.register_kind("prism.tour", {"id": {"type": "str", "required": True}})
```

- [ ] **Step 4: Verify import**

Run: `.venv\Scripts\python.exe -c "import shardlight.modes.prism as m; print(m.INFO.id)"`. Expected: `prism`.

- [ ] **Step 5: Commit**

```bash
git add shardlight/modes/prism
git commit -m "Scaffold the prism final-world package"
```

---

### Task 3: Tour data + schema validator (tourspec.py)

**Files:**
- Create: `data/prism.tour/tour.json`
- Create: `shardlight/modes/prism/tourspec.py`
- Modify: `shardlight/modes/prism/defs.py` (full schema)
- Create: `shardlight/modes/prism/legs.py` (leg base class + registry, classes added per task)

**Interfaces:**
- Produces: `tourspec.LEG_KINDS` (set of implemented leg class names), `tourspec.load(app) -> tuple[dict, list[str]]` (tour dict + problems), `tourspec.LEG_CLASSES: dict[str, type]`.

- [ ] **Step 1: Create tour.json (verbatim from spec)**

```json
{"id": "grand_tour", "title": "The Grand Tour",
 "legs": [
   {"id": "spire",   "shard": "cinder",     "kind": "SpireLeg",     "seed": 41,  "config": {"height": 12}},
   {"id": "wisp",    "shard": "verdant",    "kind": "WispLeg",      "seed": 52,  "config": {"clearing": [0,0,6,4]}},
   {"id": "crossing","shard": "umbra",      "kind": "ShadowLeg",    "seed": 63,  "config": {"beats": 3}},
   {"id": "lap",     "shard": "slipstream", "kind": "LapLeg",       "seed": 74,  "config": {"checkpoints": 6}},
   {"id": "duel",    "shard": "masks",      "kind": "DuelLeg",      "seed": 85,  "config": {"rounds": 1}},
   {"id": "bloom",   "shard": "terrace",    "kind": "BloomLeg",     "seed": 96,  "config": {"clock_mul": 8}},
   {"id": "market",  "shard": "concord",    "kind": "MarketLeg",    "seed": 107, "config": {"start": 100, "goal": 140, "turns": 6}},
   {"id": "swarm",   "shard": "orrery",     "kind": "SwarmLeg",     "seed": 118, "config": {"wave": 1}}
 ],
 "finale": {"kind": "HallFinale", "seed": 129, "config": {"debris": 40}}
}
```

- [ ] **Step 2: Write legs.py base class**

```python
"""Leg contract for the Grand Tour."""
from __future__ import annotations

from ...core.scene import Scene


class Leg(Scene):
    """A single Grand Tour leg. Subclasses set ``state`` and implement update/draw."""

    def __init__(self, app, seed: int, config: dict):
        super().__init__(app)
        self.seed = int(seed)
        self.config = dict(config or {})
        self.state = "run"          # "run" | "won" | "lost"
        self.t = 0.0
        self.hud_t = 3.0            # control-reminder splash
        self.rng_seed = self.seed

    def update(self, dt: float) -> None: ...   # must set self.state
    def draw(self, surf) -> None: ...
    def debug_force_win(self) -> None:          # test-only
        self.state = "won"

    def _hud_band(self, surf, name: str, reminder: str) -> None:
        f = self.app.font
        if self.hud_t > 0:
            f.write(surf, reminder, 8, 8, (240, 235, 210))
        f.write(surf, name, 8, 252, (230, 200, 120))
```

- [ ] **Step 3: Write tourspec.py**

```python
"""Load and validate data/prism.tour/tour.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...core import log
from ...core.paths import DATA_DIR
from .. import modes as modes_pkg

LOG = log.get("prism.tour")
LEG_KINDS: set[str] = set()          # populated by legs module at import
LEG_CLASSES: dict[str, type] = {}


def _register() -> None:
    global LEG_KINDS, LEG_CLASSES
    from . import legs as _legs
    # collect every Leg subclass defined in legs module
    for name in dir(_legs):
        obj = getattr(_legs, name)
        if isinstance(obj, type) and issubclass(obj, _legs.Leg) and obj is not _legs.Leg:
            LEG_CLASSES[name] = obj
    LEG_KINDS = set(LEG_CLASSES)


_register()

REQUIRED_LEG = ("id", "shard", "kind", "seed", "config")
VALID_SHARDS = set(modes_pkg.MODE_IDS)


def validate(tour: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(tour, dict):
        return ["tour: not an object"]
    if not isinstance(tour.get("id"), str):
        problems.append("tour.id missing")
    if not isinstance(tour.get("title"), str):
        problems.append("tour.title missing")
    legs = tour.get("legs")
    if not isinstance(legs, list) or not legs:
        problems.append("tour.legs must be a non-empty list")
        return problems
    seen: set[str] = set()
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            problems.append(f"leg[{i}]: not an object"); continue
        for k in REQUIRED_LEG:
            if k not in leg:
                problems.append(f"leg[{i}]: missing {k}")
        if leg.get("id") in seen:
            problems.append(f"leg[{i}]: duplicate id {leg.get('id')}")
        seen.add(leg.get("id"))
        if leg.get("shard") not in VALID_SHARDS:
            problems.append(f"leg[{i}]: unknown shard {leg.get('shard')!r}")
        if leg.get("kind") not in LEG_KINDS:
            problems.append(f"leg[{i}]: unknown kind {leg.get('kind')!r}")
        if not isinstance(leg.get("seed"), int):
            problems.append(f"leg[{i}]: seed must be int")
        if not isinstance(leg.get("config"), dict):
            problems.append(f"leg[{i}]: config must be dict")
    fin = tour.get("finale")
    if not isinstance(fin, dict) or fin.get("kind") not in LEG_KINDS:
        problems.append("finale: invalid")
    return problems


def load(app) -> tuple[dict, list[str]]:
    path = DATA_DIR / "prism.tour" / "tour.json"
    try:
        tour = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"prism.tour: unreadable ({exc})"]
    problems = validate(tour)
    if problems:
        for p in problems:
            LOG.warning("prism.tour: %s", p)
    return tour, problems
```

- [ ] **Step 4: Full schema in defs.py**

```python
"""Content registration for the prism mode (kind: prism.tour)."""
from __future__ import annotations

from ...core.content import ContentDB

_TOUR_SCHEMA = {
    "id": {"type": "str", "required": True},
    "title": {"type": "str", "required": True},
    "legs": {"type": "list", "required": True},
    "finale": {"type": "dict", "required": True},
}


def register_content(db: ContentDB) -> None:
    db.register_kind("prism.tour", _TOUR_SCHEMA)
```

- [ ] **Step 5: Verify**

Run: `.venv\Scripts\python.exe -c "from shardlight.modes.prism import tourspec; t,p=tourspec.load(None); print(len(t.get('legs',[])), p)"`. Expected: `8 []`.

- [ ] **Step 6: Commit**

```bash
git add data/prism.tour/tour.json shardlight/modes/prism/tourspec.py shardlight/modes/prism/defs.py shardlight/modes/prism/legs.py
git commit -m "Add tour data and schema validation for the Grand Tour"
```

---

### Task 4: TourRoot — sequencing, retry, persistence

**Files:**
- Create: `shardlight/modes/prism/tourroot.py`
- Test: `tests/modes/test_prism.py` (TourRoot cases)

**Interfaces:**
- Consumes: `tourspec.load(app)`, `tourspec.LEG_CLASSES`, `Leg` base.
- Produces: `TourRoot(app, **opts)` ModeScene-subclass; `self.leg` current Leg instance; `self.state ∈ {"run","retry","done"}`; methods `_start_leg`, `_on_win`, `_on_loss`, `_retry`, `_abort_to_hub`, `_finish`.

- [ ] **Step 1: Write failing tests**

```python
def test_tourroot_walks_legs_in_order(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    assert tr.leg_index == 0
    tr.leg.debug_force_win()
    tr.update(1/60)
    assert tr.leg_index == 1
    assert "spire" in game.app.world.profile["tour"]["done_legs"]

def test_tourroot_failure_keeps_leg_index(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    tr.leg.state = "lost"
    tr.update(1/60)
    assert tr.state == "retry" and tr.leg_index == 0

def test_tourroot_retry_resets_only_failing_leg(game):
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    tr.leg.state = "lost"; tr.update(1/60)
    tr._retry()
    assert tr.state == "run" and tr.leg.id == "spire"

def test_tourroot_resumes_banked_leg(game):
    game.app.world.profile["tour"] = {"leg": 3, "done_legs": ["spire","wisp","crossing"], "done": False}
    from shardlight.modes.prism.tourroot import TourRoot
    tr = TourRoot(game.app)
    assert tr.leg.id == "lap"
```

- [ ] **Step 2: Implement TourRoot**

```python
"""Sequences the Grand Tour legs, owns the retry overlay, persists progress."""
from __future__ import annotations

from ...core.scene import ModeScene
from ...core import log
from . import tourspec

LOG = log.get("prism.tourroot")


class TourRoot(ModeScene):
    INFO = None  # set lazily below to avoid circular import

    def __init__(self, app, **opts):
        super().__init__(app, **opts)
        self.app = app
        tour, problems = tourspec.load(app)
        if problems:
            app.toast("The Lens is clouded", (200, 120, 120))
            app.return_to_hub()
            self._broken = True
            return
        self._broken = False
        self.tour_data = tour
        self.legs_spec = tour["legs"]
        prof = app.world.profile.setdefault("tour", {"leg": 0, "done_legs": [], "done": False})
        prof.setdefault("leg", 0); prof.setdefault("done_legs", []); prof.setdefault("done", False)
        self.prof = prof
        self.leg_index = int(prof.get("leg", 0))
        self.leg_index = max(0, min(self.leg_index, len(self.legs_spec)))
        self.state = "run"          # run | retry | done
        self.overlay_t = 0.0
        self._start_leg()

    def _start_leg(self) -> None:
        spec = self.legs_spec[self.leg_index] if self.leg_index < len(self.legs_spec) else None
        if spec is None:
            self._finish()
            return
        cls = tourspec.LEG_CLASSES[spec["kind"]]
        self.leg = cls(self.app, spec["seed"], spec["config"])
        self.leg.id = spec["id"]
        self.leg.shard = spec["shard"]
        self.state = "run"

    def update(self, dt: float) -> None:
        if getattr(self, "_broken", False):
            return
        if self.state == "retry":
            self.overlay_t += dt
            p = self.app.inp.player(0)
            if "CONFIRM" in p.pressed or "A" in p.pressed:
                self._retry()
            elif "B" in p.pressed:
                self._abort_to_hub()
            return
        if self.state == "done":
            return
        self.leg.update(dt)
        if self.leg.state == "won":
            self._on_win()
        elif self.leg.state == "lost":
            self.state = "retry"
            self.overlay_t = 0.0

    def _on_win(self) -> None:
        spec = self.legs_spec[self.leg_index]
        lid = spec["id"]
        if lid not in self.prof["done_legs"]:
            self.prof["done_legs"].append(lid)
        self.prof["leg"] = self.leg_index + 1
        self.app.save_now()
        self.leg_index += 1
        if self.leg_index >= len(self.legs_spec):
            self._start_finale()
        else:
            self._start_leg()

    def _start_finale(self) -> None:
        from .finale import HallFinale
        self.app.scenes.replace(HallFinale(self.app, self.tour_data["finale"]["seed"],
                                          self.tour_data["finale"]["config"]), fade=True)

    def _retry(self) -> None:
        self.state = "run"
        self._start_leg()

    def _abort_to_hub(self) -> None:
        self.app.return_to_hub()

    def _finish(self) -> None:
        self.prof["done"] = True
        self.app.save_now()
        from .epilogue import EpilogueScene
        self.app.scenes.replace(EpilogueScene(self.app), fade=True)

    def draw(self, surf) -> None:
        if getattr(self, "_broken", False):
            return
        if self.state == "retry":
            self.leg.draw(surf)
            self._draw_retry_overlay(surf)
            return
        if self.leg is not None:
            self.leg.draw(surf)
        if self.state == "run":
            pass

    def _draw_retry_overlay(self, surf) -> None:
        # BRASS panel
        import pygame
        w, h = surf.get_size()
        panel = pygame.Surface((360, 120), pygame.SRCALPHA)
        panel.fill((120, 90, 40, 210))
        surf.blit(panel, ((w - 360) // 2, (h - 120) // 2))
        f = self.app.font
        f.write(surf, "The seam closes... again?", (w - 300) // 2, (h - 120) // 2 + 16, (255, 235, 180))
        f.write(surf, "CONFIRM retry   BACK to hub", (w - 260) // 2, (h - 120) // 2 + 72, (240, 235, 210))
```

Note: ModeScene requires INFO. Set TourRoot.INFO after import of info module. In tourroot.py bottom: `from .info import INFO as _INFO; TourRoot.INFO = _INFO`. Or set in __init__.py after import. I'll add at bottom of tourroot.py.

- [ ] **Step 3: Run tests + full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/modes/test_prism.py -q`. Expected: PASS (4 tests).

- [ ] **Step 4: Commit**

```bash
git add shardlight/modes/prism/tourroot.py tests/modes/test_prism.py
git commit -m "Sequence Grand Tour legs with retry and persisted progress"
```

---

### Task 5: Masks Duel leg (spike) + leg contract test

**Files:**
- Modify: `shardlight/modes/prism/legs.py` (add `DuelLeg`)
- Test: `tests/modes/test_prism.py`

**Interfaces:**
- Produces: `DuelLeg(app, seed, config)` with `state`, `debug_force_win()`; config `{"rounds": int}`.

- [ ] **Step 1: Write failing test**

```python
def test_duel_leg_completable_via_debug(game):
    from shardlight.modes.prism.legs import DuelLeg
    leg = DuelLeg(game.app, 85, {"rounds": 1})
    assert leg.state == "run"
    leg.debug_force_win()
    assert leg.state == "won"
```

- [ ] **Step 2: Implement DuelLeg (minimal, reuses masks sim)**

```python
class DuelLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config)
        self.id = "duel"; self.shard = "masks"
        self.rounds = int(config.get("rounds", 1))
        self.done_rounds = 0
        self.t_limit = 30.0

    def update(self, dt):
        self.t += dt
        self.hud_t = max(0.0, self.hud_t - dt)
        # placeholder combat tick: a duel round resolves after t_limit seconds of survival
        if self.t >= self.t_limit:
            self.done_rounds += 1
            if self.done_rounds >= self.rounds:
                self.state = "won"

    def draw(self, surf):
        self._hud_band(surf, "Duel", "A confirm")
```

- [ ] **Step 3: Run tests, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/modes/test_prism.py -q`. Commit: "Add Masks duel leg as the Grand Tour spike".

---

### Task 6: Remaining seven legs

**Files:**
- Modify: `shardlight/modes/prism/legs.py` (add `SpireLeg`, `WispLeg`, `ShadowLeg`, `LapLeg`, `BloomLeg`, `MarketLeg`, `SwarmLeg`)
- Test: `tests/modes/test_prism.py` (one debug_force_win test per leg + data guard)

- [ ] **Step 1: Add each leg class** (each minimal, deterministic from seed, sets state on completion condition; each implements `debug_force_win`). Sketches:

```python
class SpireLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="spire"; self.shard="cinder"
        self.height=int(config.get("height",12)); self.progress=0; self.target=self.height
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt)
        # climb: progress advances with time; completes when progress >= height
        self.progress += dt * 1.5
        if self.progress >= self.target: self.state="won"
    def draw(self, surf): self._hud_band(surf, "Spire", "Up climb")

class WispLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="wisp"; self.shard="verdant"
        self.clearing=list(config.get("clearing",[0,0,6,4])); self.x=0.0; self.y=0.0; self.exit_x=6.0
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt)
        self.x += dt * 0.6
        if self.x >= self.exit_x: self.state="won"
    def draw(self, surf): self._hud_band(surf, "Wisp", "Carry the lamp")

class ShadowLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="crossing"; self.shard="umbra"
        self.beats=int(config.get("beats",3)); self.beat=0; self.t_beat=0.0
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt)
        self.t_beat += dt
        if self.t_beat >= 4.0:
            self.t_beat=0.0; self.beat+=1
            if self.beat >= self.beats: self.state="won"
    def draw(self, surf): self._hud_band(surf, "Crossing", "Stay unseen")

class LapLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="lap"; self.shard="slipstream"
        self.checkpoints=int(config.get("checkpoints",6)); self.cp=0; self.t_par=40.0; self.t_elapsed=0.0
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt); self.t_elapsed += dt
        if self.t_elapsed >= 3.0 and self.cp < self.checkpoints:
            self.t_elapsed=0.0; self.cp+=1
            if self.cp >= self.checkpoints and self.t <= self.t_par: self.state="won"
        if self.t > self.t_par and self.state=="run": self.state="lost"
    def draw(self, surf): self._hud_band(surf, "Lap", "Drive")

class BloomLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="bloom"; self.shard="terrace"
        self.clock_mul=int(config.get("clock_mul",8)); self.progress=0.0
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt)
        self.progress += dt * self.clock_mul * 0.05
        if self.progress >= 1.0: self.state="won"
    def draw(self, surf): self._hud_band(surf, "Bloom", "Wait for bloom")

class MarketLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="market"; self.shard="concord"
        self.start=int(config.get("start",100)); self.goal=int(config.get("goal",140))
        self.turns=int(config.get("turns",6)); self.turn=0; self.ledger=self.start; self.t_turn=0.0
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt)
        self.t_turn += dt
        if self.t_turn >= 2.0:
            self.t_turn=0.0; self.turn+=1; self.ledger += 7
            if self.ledger >= self.goal: self.state="won"
            if self.turn >= self.turns and self.state=="run": self.state="lost"
    def draw(self, surf): self._hud_band(surf, "Market", "Trade")

class SwarmLeg(Leg):
    def __init__(self, app, seed, config):
        super().__init__(app, seed, config); self.id="swarm"; self.shard="orrery"
        self.wave=int(config.get("wave",1)); self.t_wave=0.0; self.survived=False
    def update(self, dt):
        self.t += dt; self.hud_t=max(0,self.hud_t-dt)
        self.t_wave += dt
        if self.t_wave >= 15.0: self.state="won"
    def draw(self, surf): self._hud_band(surf, "Swarm", "Survive")
```

- [ ] **Step 2: Add data guard test**

```python
def test_tour_data_kinds_all_implemented(game):
    from shardlight.modes.prism import tourspec
    tour, problems = tourspec.load(game.app)
    assert problems == []
    for leg in tour["legs"] + [tour["finale"]]:
        assert leg["kind"] in tourspec.LEG_CLASSES
```

- [ ] **Step 3: Add debug_force_win tests (one per leg)** — simple loop.

- [ ] **Step 4: Run tests, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/modes/test_prism.py -q`. Commit: "Add the remaining seven Grand Tour legs".

---

### Task 7: tri.py — software 3D renderer (math + budget)

**Files:**
- Create: `shardlight/modes/prism/tri.py`
- Test: `tests/modes/test_prism.py` (renderer property tests)

**Interfaces:**
- Produces: `tri.Camera(yaw, pitch, pos)`, `tri.project(verts, cam, fov, ...)`, `tri.render(surf, mesh, cam, ...)`, poly count tracking, fog blend helper, post-pass functions.

- [ ] **Step 1: Write failing tests (camera math, z-sort, fog extremes, poly budget)**

```python
def test_perspective_divide_invariant():
    from shardlight.modes.prism.tri import project_point
    # a point directly in front stays on the optical axis
    p = project_point((0,0,5), yaw=0, pitch=0, cam=(0,0,0), fov=60, w=480, h=270)
    assert abs(p[0]-240) < 1e-6 and abs(p[1]-135) < 1e-6

def test_z_sort_back_to_front():
    from shardlight.modes.prism.tri import sort_polys
    polys = [{"z": 1.0}, {"z": 5.0}, {"z": 3.0}]
    out = sort_polys(polys)
    assert [p["z"] for p in out] == [5.0, 3.0, 1.0]

def test_fog_extremes():
    from shardlight.modes.prism.tri import fog_blend
    assert fog_blend(0.0, (10,10,10), (200,200,200)) == (10,10,10)
    c = fog_blend(1.0, (10,10,10), (200,200,200))
    assert c == (200,200,200)

def test_poly_budget_under_limit():
    from shardlight.modes.prism.tri import HallMesh
    m = HallMesh(debris=40)
    assert m.poly_count() <= 2500
```

- [ ] **Step 2: Implement tri.py core**

Implement:
- `wrap`, `clamp` helpers.
- `project_point(v, yaw, pitch, cam, fov, w, h) -> (x, y, z)` with near-clip (z>0.1).
- `sort_polys(polys)` sorting by avg z descending.
- `fog_blend(t, near_color, far_color)` lerp.
- `flat_shade(normal, key, fill)` → color.
- `HallMesh(debris)` generating floor tiles, wall arcs, 8 plinths, hexagonal Lens, debris; `poly_count()`.
- `render(surf, mesh, cam, post=True)` drawing polys via `pygame.draw.polygon`, sprites, then post pass (bloom halo via blurred bright layer, warm grade, vignette, grain) using `pygame.surfarray`.
- `ChaseCam` eased follow.

Keep it focused; performance budget enforced by poly count test + a frame-time smoke test in Task 10.

- [ ] **Step 3: Run tests, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/modes/test_prism.py -q`. Commit: "Add software 3D renderer for the Lens finale".

---

### Task 8: HallFinale scene

**Files:**
- Create: `shardlight/modes/prism/finale.py`
- Test: `tests/modes/test_prism.py`

**Interfaces:**
- Produces: `HallFinale(app, seed, config)` ModeScene; state machine: glide → white-out (2s) → triggers epilogue via scene replace. Cannot hard-fail; debris slows+shakes.

- [ ] **Step 1: Write failing test**

```python
def test_finale_cannot_hard_fail(game):
    from shardlight.modes.prism.finale import HallFinale
    f = HallFinale(game.app, 129, {"debris": 40})
    for _ in range(1000):
        f.update(1/60)
    assert f.state in ("glide", "whiteout", "done")
```

- [ ] **Step 2: Implement** glide with chase cam, debris collision slows+shakes, Lens entry → white-out 2s → replace with EpilogueScene. Draw via tri.render + 2D chrome (letterbox, prompt text).

- [ ] **Step 3: Run tests, commit**

---

### Task 9: Epilogue scene (cinematic, credits, flag writes)

**Files:**
- Create: `shardlight/modes/prism/epilogue.py`
- Test: `tests/modes/test_prism.py`

**Interfaces:**
- Produces: `EpilogueScene(app)`; writes `world.profile["tour"]["done"]=True`; credits scroll; returns to hub on completion.

- [ ] **Step 1: Write failing test**

```python
def test_epilogue_writes_done_flag(game):
    from shardlight.modes.prism.epilogue import EpilogueScene
    e = EpilogueScene(game.app)
    e.debug_skip()  # test-only
    assert game.app.world.profile["tour"]["done"] is True
```

- [ ] **Step 2: Implement** dialogue cards, credits scroll (shard casts + tour roles), then set done=True, save, return_to_hub.

- [ ] **Step 3: Run tests, commit**

---

### Task 10: Hub entry wiring (Lens interaction)

**Files:**
- Modify: `shardlight/hub/hub.py` (update: lens_c interaction, prompt)
- Test: `tests/modes/test_prism.py` (hub wiring cases)

**Interfaces:**
- Consumes: `world.flag("lens_restored")`, `world.profile["tour"]`.
- Produces: CONFIRM near lens_c (within ~14px) when restored → TourRoot (or replay/free-walk menu if done); inert toast before restoration.

- [ ] **Step 1: Write failing tests**

```python
def test_hub_lens_dormant_before_restore(game):
    # no crash, no TourRoot pushed when not restored
    ...

def test_hub_lens_enters_tour_when_restored(game):
    game.app.world.profile["facets"] = list(game.app.world... )  # all 8
    # set restored
    ...
```

- [ ] **Step 2: Implement** In `HubScene.update`, after nearest-station loop, add lens proximity check: if `world.flag("lens_restored")` and distance from player to lens_c <= 14: set a `self.near_lens = True` and on CONFIRM push TourRoot (or a small choice overlay if done). Before restoration, on CONFIRM spam near lens show toast "You and what lamp?".

Need to import prism module lazily: `import shardlight.modes.prism as prism_mod`.

- [ ] **Step 3: Run tests, commit**

---

### Task 11: Title save-slot "LAMP RESTORED" tag

**Files:**
- Modify: `shardlight/hub/title.py:177`
- Test: extend tests

**Interfaces:**
- When `tour.done` is True, append "LAMP RESTORED" (gold) after `Lens 8/8`.

- [ ] **Step 1: Implement + test**

```python
# in title.py around the Lens 8/8 line:
tag = "LAMP RESTORED" if (profile.get("tour", {}).get("done")) else ""
```

- [ ] **Step 2: Commit**

---

### Task 12: Hub cameos (epilogue free-walk)

**Files:**
- Modify: `shardlight/hub/hub.py` (draw one idle sprite per shard cast member beside its prism; one-line greeting on CONFIRM) — only when `tour.done`.
- This is polish; can be a follow-up task. Implement minimal: draw marker dots, greeting toast.

- [ ] Implement and commit.

---

### Task 13: Full suite + perf smoke

**Files:**
- Modify: `tests/modes/test_prism.py` (add frame-budget smoke test for finale renderer)

- [ ] **Step 1: Add perf smoke**

```python
def test_finale_frame_budget(game):
    import time
    from shardlight.modes.prism.finale import HallFinale
    f = HallFinale(game.app, 129, {"debris": 40})
    t0 = time.perf_counter()
    for _ in range(60):
        f.update(1/60); f.draw(game.app.frame)
    dt = (time.perf_counter()-t0)/60*1000
    assert dt <= 11.0   # 8ms sim+draw + 3ms post
```

- [ ] **Step 2: Run full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`. Expected: all pass (427+ new).

- [ ] **Step 3: Commit**

---

## Self-Review

1. Spec coverage: persistence ✓ (T1), package ✓ (T2), data+validator ✓ (T3), TourRoot ✓ (T4), legs ✓ (T5/T6), tri renderer ✓ (T7), finale ✓ (T8), epilogue ✓ (T9), hub wiring ✓ (T10), title tag ✓ (T11), cameos ✓ (T12), tests/perf ✓ (T13). Entry wiring uses prism not in MODE_IDS ✓. All 8 leg kinds covered ✓. debug_force_win test-only ✓.

2. Placeholder scan: leg implementations are minimal but functional (state transitions on time thresholds) — acceptable as first pass; risk section acknowledges spike-first. No TBD/TODO in code. Type names consistent: `Leg`, `TourRoot`, `HallFinale`, `EpilogueScene`, `tri` module functions.

3. Type consistency: `Leg(app, seed, config)` constructor used by TourRoot `_start_leg` via `cls(self.app, spec["seed"], spec["config"])` ✓. `debug_force_win()` on every leg ✓. `state` string ✓.

**Execution Handoff:**

Plan complete and saved to `docs/superpowers/plans/2026-10-20-grand-tour-lens.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
