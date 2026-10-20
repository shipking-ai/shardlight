# The Grand Tour — final world of the restored Lens (design)

Date: 2026-10-20 · Status: approved-in-conversation → spec

## What this is

When all eight shard facets are repaired, the central Lens becomes a final world: **"The Grand Tour."**
A single continuous run through the eight shards — one emblematic challenge each — ending with the
player flying INTO the Lens itself in a three-dimensional cinematic finale, a closing scene, credits,
and a permanent epilogue state for the hub and title screen.

Decisions recorded from the design conversation:

- **Structure:** All 8 playable legs (Grand Tour), each 1–2 minutes, reusing each shard's existing sim
  with authored (fixed) layouts. Death = **retry the current leg only**; earlier legs stay banked.
- **Graphics:** Pixel art everywhere, as today — except inside the Lens finale, which renders
  **flat-shaded retro-3D** (software renderer, perspective camera, depth fog, glow sprites, sky
  gradient — PSX-era character) finished with a 2D post pass (bloom halo, grade, vignette, grain).
  The post pass runs only inside prism scenes; nothing else changes.
- **Ending chosen:** Full epilogue — cinematic + credits, then the hub keeps the gold Lens, shard
  **cameos** stand near their stations, shards stay replayable, and the title save slot gains a
  "LAMP RESTORED" tag.

## Context (repo facts this design stands on)

- Renderer: every scene composites into one 480×270 frame (`shardlight/core/app.py:29` RENDER_SIZE,
  `app.py:61` self.frame, SCALED window) — all draw calls target that surface.
- Modes are subpackages exposing `INFO`, `create(app, **opts)`, optional `register_content(db)`;
  `MODE_IDS` (`shardlight/modes/__init__.py:19`) drives hub stations, the orbiting facet prisms and
  the 8/8 facet count; every mode calls `world.complete_facet(mode_id)` at its climax
  (e.g. `verdant/scene.py:124`).
- `world.repair_facet` / `complete_facet` / profile `facets` list and flags
  (`shardlight/core/world.py:109-119,77`); hub counts `len(facets) >= 8` and sets the
  `lens_restored` flag with its one dialogue today (`shardlight/hub/hub.py:182-188`).
- Title save-slot line already shows `Lens 8/8` (`shardlight/hub/title.py:177`).
- Hub has a lighting painter (`hub.lighting`) used for the lens glow; the Prism Forge / Archive /
  Control Desk are plain `Station` entries (`hub.py:174-176`).

## Non-goals

- No photos, no 3D models, no GPU engine, no new window/process. The 3D is a **software rasteriser
  inside pygame**. Painterly retro-3D is the style ceiling, agreed with the user.
- No changes to the eight shards' gameplay or their `complete_facet` logic.
- No mouse controls inside prism legs (menus prompt with the usual prompt bar only).

## Architecture

### New mode package `shardlight/modes/prism/` (not in MODE_IDS)

Loaded explicitly by the hub's Lens entry (see wiring below) so the 8-station/facet systems are
untouched. Package contents:

- `info.py` — `ModeInfo` (title "The Grand Tour", color gilded, controls line).
- `__init__.py` — `create(app)` → `TourRoot`; `register_content` registers one validated kind
  `prism.tour` ("data-only, schema-checked") read from `data/prism.tour/tour.json`.
- `tourspec.py` — loads + validates the tour JSON (schema-validated like other kinds; problems abort
  scene construction).
- `tourroot.py` — `TourRoot` sequences legs, owns the retry overlay, saves progress, hands off to
  the finale, and returns to the hub.
- `legs.py` — the eight leg scenes. Each leg is a class with the contract:
  `update(dt) -> state`, `draw(surf)`, `state ∈ {"run", "won", "lost"}`. Legs import **sim modules**
  of their shard (engines, not scenes), receive an authored `config` dict + seed, and own a
  small HUD band (leg name, control reminder splash for 3 s, retry hint on loss).
- `tri.py` — the software 3D renderer used by the finale (see below).
- `finale.py` — the 3D flight-into-the-Lens sequence and the white-out transition into the epilogue.
- `epilogue.py` — cinematic dialogue, credits scene (rendered over frugal 3D stills), post-state flag
  writes, return to hub.

Each pixel leg reuses its shard's control mappings verbatim; the finale uses orrery flight verbs
(thrust/turn; no firing — dodging only).

### Tour data and its schema (`data/prism.tour/tour.json`)

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

Order is authored and fixed as shown (climb → carry → unseen → drive → duel → grow → ledger →
swarm → the hall). `seed` per leg keeps everything deterministic and replayable.

### Leg meanings (one emblematic verb per shard)

| # | leg | shard | verb | win |
|---|---|---|---|---|
| 1 | spire | Cinder | outclimb a short self-rebuilding spire | reach the top before the seam rebuilds |
| 2 | wisp | Verdant | carry a lamp through one bog clearing | clear the exit past one woken enemy alive |
| 3 | crossing | Umbra | cross 3 visibility beats unseen | reach the far dark before nightfall |
| 4 | lap | Slipstream | one lap on a fixed short oval | all checkpoints inside par time |
| 5 | duel | Masks | one gauntlet-of-masks duel round | win the round |
| 6 | bloom | Terrace | compressed terrace vigil (clock ×8) | first bloom |
| 7 | market | Concord | six-turn market play | open the goal ledger (100→140) |
| 8 | swarm | Orrery | one wave dogfight | survive, and the jump window opens |

Leg 2 (wisp) — carry the lamp from the clearing entrance to its exit; one bog-tar beast guards the
route and must be dodged or baited; no player combat is required.

### Failure, retry, progress

- On "lost": `TourRoot` pushes a retry overlay (pixel UI, BRASS panel "The seam closes... again?") —
  CONFIRM restarts the leg from its same seed, BACK returns to the hub (banked progress kept);
  nothing else resets. `world.profile["tour"]["leg"]` never regresses.
- Leg completion stamp (`world.profile["tour"]["done_legs"]`) is monotonic; quitting at any point
  resumes on entry at the banked leg (entry always from the hub).
- If a leg's sim objects can't persist across a quit, it doesn't need to: legs are short by
  construction and restart cleanly from seed.

### The 3D finale (`tri.py`, `finale.py`)

- **Renderer:** pure pygame + numpy perspective rasteriser.
  - Camera: yaw/pitch + position, target-following behind the ship (chase cam, eased).
  - Geometry: low poly triangles (hall = authored procedural: floor tiles, wall arcs, eight plinths,
    the colossal hexagonal Lens), ship = authored ~120-triangle hull; total budget ≤ ~2 500
    triangles/frame at 480×270.
  - Pipeline: transform → near-clip → perspective divide → painter's algorithm z-sort → flat shade
    (surface normal, one warm key light + cool fill) → fog blend toward the sky color by depth →
    draw polys via `pygame.draw.polygon` on a dedicated surface (not numpy per-pixel).
  - Sprites (glow, dust motes) alpha-blitted after the polys.
  - Post pass: bright-pass halo (additive blit of a blurred bright layer), warm grade overlay,
    vignette, grain — via `pygame.surfarray` numpy ops, budget ≤ 3 ms/frame.
- **The finale game:** the ship glides into the hall; the only rule is *fly the seam*: gate slaloms
  and drifting light-debris to steer around (forgiving, untimed, cannot hard-fail — touching debris
  slows and shakes, never kills). Ends at the Lens: fly into it → white-out (2 s) → epilogue.
- **Letterbox + text:** cinematic 2D chrome — thin letterbox bars, prompt texts and dialogue rendered
  onto the post-processed image; fonts stay the game's pixel font inside the 480×270 canvas, except
  the closing dialogue card which uses a graded color treatment.

### Epilogue

- Dialogue: the restored-Lens lines exist (`hub.py:184-188`); the finale adds a longer closing
  exchange, text cards summarizing the run (legs completed, deaths, time), then **credits**:
  a slow vertical scroll listing shard casts + the tour's own roles, keyed music.
- After credits the world persists the epilogue state:
  - `world.profile["tour"]["done"] = True`
  - hub: the gold Lens already follows the facet count; **cameos**: one idle pixel sprite per shard
    cast member standing beside its shard prism, with a one-line greeting on CONFIRM.
  - title save-slot tag: "LAMP RESTORED" printed after `Lens 8/8` (gold color).
- The tour can be replayed at any time from the Lens; replays run with the same rules, but they only
  advance the leg index in profile — completion flags are never touched twice.

### Entry wiring in the hub

- `HubScene.update` gains one station-like interaction registered only when
  `world.flag("lens_restored")` and the player stands near `lens_c` within ~14 px: prompt
  "CONFIRM Enter the Lens". Pressing it: if not `tour.done` → `TourRoot` scene; if `tour.done` → a
  short scene offering "Run the Grand Tour again" or "Walk the hall" (epilogue free-walk with cameos).
- Before restoration the lens shows a one-line "You and what lamp?" toast when CONFIRM spam nears it
  (existing behavior today is inertness; keep gentle).

## Persistence

- `world.profile` gains one nested object `{"tour": {"leg": int, "done_legs": [id...], "done": bool}}`
  saved by the existing profile save path; version-tolerant (missing → default).
- Flags stay `lens_restored` (existing) + nothing new required.

## Performance budget (targets, esp. desktop Windows + GPU-less headless CI)

- Pixel legs reuse their shard sims: no new overhead beyond the HUD band (≤ 1 ms).
- Finale: ≤ 2 500 polys, ≤ 8 ms/frame update+draw at 480×270 on the dev machine, ≤ 3 ms post pass.
- Frame-budget smoke checks run headless with fixed seeds, so CI perf drift is visible.

## Testing plan (pytest conventions in `tests/modes/test_prism.py`)

1. Tour data loads + schema-validates; every `kind` maps to an implemented leg class (guard against
   silent data rot).
2. `TourRoot` walks legs in order; simulated wins advance `tour.leg`; failure keeps it; retry resets
   only the failing leg.
3. Every leg completable by a scripted update sequence module-level helper (fixture `game`-style):
   each leg class exposes `debug_force_win()` used ONLY by tests (clearly named, no production calls).
4. Finale renderer properties: camera math (perspective divide invariants), z-sort order, fog blend
   extremes, poly count under budget at seeded layouts.
5. Epilogue flag writes after credits; title text includes "LAMP RESTORED" once `tour.done`.
6. Hub wiring: CONFIRM on the inert vs restored lens paths; dormant-before-restored.
7. Full suite stays green (422+ currently; add these, keep all pass).

## Risks / mitigations

- **Per-shard sim reuse may surprise** (each shard's internals differ): mitigate by speccing leg
  implementation order with a spike first (shortest leg, Masks duel, then the rest); every leg is
  small and isolated in `legs.py`.
- **Software 3D performance**: poly budget fixed; degrade by dropping post pass before geometry;
  usage is limited to the finale so worst case is a bounded feature.
- **Fonts/text in the finale** must not re-introduce the pixel grid — solved: text lives in the 2D
  chrome layer drawn after the 3D image at 480×270 (it will be pixel-ish font, but the *scene* is
  smooth; agreed trade-off).
- **Determinism** for all seeded layouts — verified in tests (2, 4, 6 above).
