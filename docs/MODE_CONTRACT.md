# Mode Contract

Every shard (mode) is a self-contained subpackage `shardlight/modes/<id>/`. Read `shardlight/core/*` before writing code — it is the shared engine. This document is the binding contract between the engine and a mode.

Mode ids: `cinder` (action roguelike), `verdant` (open-world RPG), `umbra` (psychological horror survival), `slipstream` (racing), `concord` (strategy / empire sim), `terrace` (sandbox survival & construction), `masks` (2D fighting game), `orrery` (space exploration & civilization sim).

## 1. Package layout

```
shardlight/modes/<id>/
    __init__.py     INFO (ModeInfo), create(app, **opts) -> Scene, register_content(db)
    scene.py        the ModeScene subclass (thin: input -> sim, sim -> render)
    sim/ or *.py    PURE game logic with no pygame drawing: deterministic, unit-testable
    art.py          procedural sprite/tile baking (cached), palettes
    sfx.py          register_sfx recipes, names prefixed "<id>_"
data/<kind>/<id>_*.json     content (weapons, quests, tracks ...). Kinds are registered as "<id>.<thing>"
tests/modes/test_<id>_*.py  tests (see section 7)
docs/modes/<id>.md          design notes, systems, VERIFIED vs NOT VERIFIED list, known issues
```

Touch ONLY these paths. Do not edit other modes. If you need a change in `shardlight/core/` that is **additive or a bug fix**, make it minimal, keep every existing test green (`pytest tests -q`), and append one line to `docs/CORE_CHANGES.md` (`- <id>: <file>: <what/why>`). Never make breaking changes to core APIs.

## 2. Required module API

```python
# shardlight/modes/<id>/__init__.py
from ...core.scene import ModeInfo
INFO = ModeInfo(id="<id>", title=..., genre=..., tagline=..., blurb=..., color=(r,g,b), dark=(r,g,b),
                max_players=1, controls=(("A","Attack"), ...), options=({"key":"seed","label":"Seed","choices":[...],"default":...},))
def register_content(db): db.register_kind("<id>.weapon", SCHEMA)   # optional, called before data is loaded
def create(app, **opts): return MyModeScene(app, **opts)            # opts come from the shard card (players=, options)
```

`INFO.controls` use logical button names (`UP A B X Y L R SELECT PAUSE`), the hub shows device-appropriate labels.
`INFO.options` entries: `{"key", "label", "choices": [...], "default"}`; chosen values arrive in `create(..., key=value)`.

The scene subclasses `shardlight.core.scene.ModeScene`:
* `on_enter(**kw)`: start music (`self.app.audio.play_music("<id>")`), set up state.
* `update(dt)`: `dt` is a fixed 1/60 s. Read input from `self.app.input.player(slot)` (see `core/input.py`: `held`, `just_pressed`, `move`, `aim`, `buffered(b, frames)`). Never read pygame keys directly (menus' text entry excepted).
* `draw(surf)`: draw into the 480x270 `surf`. All text via `self.app.font` (pixel font, ASCII only!).
* PAUSE button -> `self.open_pause_menu()`. `on_pad_lost(slot)` -> open the pause menu.
* Leave with `self.finish(**summary)` (saves and returns to hub).
* Persistent mode save data: `self.data` (a JSON-serialisable dict inside the profile, saved by `app.save_now()`; call that at meaningful checkpoints). Never pickle. Version your own sub-schema (`self.data["v"]`) and tolerate missing/old keys.
* `dormant/unavailable` content must degrade gracefully (missing asset or unknown id -> skip with a log warning, never crash).

## 3. Shared services (via `self.app`)

| need | use |
|---|---|
| input | `app.input.player(slot)`; local MP: `opts["players"]` has been applied by the card (`input.assign_local(n)`), slot 0 = kb1(WASD+JIKU) + first pad, slot 1 = kb2 (arrows + , . M N) or second pad |
| randomness | `core.rng.Rng(seed)`; `rng.child("label")` for independent streams. Everything procedural must be reproducible from a seed (show/accept the seed; `seed_to_words`) |
| content / mods | `app.content.all("<id>.kind")`; entries are plain dicts validated against your schema; mods may add/override entries, so never hard-code lists of ids |
| world / cross-mode | `app.world` (see `core/world.py`): `emit(event, **payload)`, `flag/has_unlock/has_lore/rep/counter`, `unlock`, `add_lore`, `complete_facet(mode_id)`. NEVER import another mode |
| economy | `app.economy.grant("<id>", amount)` (capped per session) |
| audio | `app.audio.play(sfx_name, volume, pan)`, `play_music(track)`, `set_intensity(0..1)` drives layered music |
| feel | `core.fx`: `Camera` (trauma shake), `FEEL.add_hitstop(frames)`, `FEEL.flash(...)`, `ParticleSystem`, `Lighting`, `FloatingTexts`, easing. They respect accessibility settings; use them rather than rolling your own shake/flash |
| art helpers | `core.art` (outline, ramp, shade, dither, prisms, shadows); UI frames `core.ui.draw_panel`, `Menu`, `Dialogue` |
| AI / nav | `core.ai` (behaviour trees, utility, perception+memory, NoiseBus, PlayerModel + AdaptiveController), `core.nav` (A*, LOS, FlowField, SpatialHash) |
| settings | `app.settings.get("difficulty.preset")` (story/standard/hard), `difficulty.adaptive_ai` (0..1.5), `access.*` (respect them) |
| debug | `app.debug` (F3) -> draw AI/pathing/hitbox overlays |

## 4. Cross-mode hooks (data-driven echoes in `data/echo/spine.json`)

Each mode MUST emit these and consume these unlock ids (check `self.app.world.has_unlock("<id>")` at run/world creation time). Consuming means: the content really appears/changes in your mode and is clearly communicated (toast / UI badge / dialogue).

| mode | emits (payload) | consumes unlock ids (effect in this mode) |
|---|---|---|
| cinder | `cinder.boss_defeated{boss}` (boss `choir_warden` = new optional boss), `cinder.run_completed{depth, won}`, `cinder.facet_repaired` | `cinder.boss.choir_warden` (a new boss door in the tower with its own phases) |
| verdant | `verdant.site_explored{site}` (site `listening_stones`), `verdant.quest_completed{quest}` (quest `lamplighters_debt`), `verdant.facet_repaired` | `verdant.site.listening_stones` (new explorable ruin appears on the map), `verdant.trade.beacon_caravans` (new trade goods/caravans) |
| umbra | `umbra.relic_found{relic}` (relic `stopped_clock`), `umbra.night_survived{night}`, `umbra.facet_repaired` | `umbra.item.lantern_ward` (a craftable/placed light item that holds enemies at bay with cost) |
| slipstream | `slipstream.championship_won{cup}` (cup `salt_cup`), `slipstream.facet_repaired` | `slipstream.vehicle.chronograph` (a distinct unlockable vehicle) |
| concord | `concord.treaty_signed{faction}`, `concord.tech_researched{tech}`, `concord.facet_repaired` | `concord.tech.resonant_forging` (a tech/unit upgrade becomes researchable) |
| terrace | `terrace.structure_built{kind}` (kind `beacon` = a buildable beacon), `terrace.facet_repaired` | `terrace.recipe.choir_alloy`, `terrace.material.cinder_iron` (new craftable materials/recipes) |
| masks | `masks.rival_defeated{rival}` (rival `warden_of_hours` = extra unlockable challenger), `masks.facet_repaired` | `masks.rival.warden_of_hours` |
| orrery | `orrery.signal_decoded{signal}` (signals `choir` always findable; `beacon_echo` when unlocked), `orrery.facet_repaired` | `orrery.ship.salt_runner` (hull blueprint), `orrery.signal.beacon_echo` (new signal source), `orrery.contact.concord_envoys` (a contact/event) |

`complete_facet(id)` is called exactly once when the player completes the mode's **Facet Trial** (the mode's main goal; define it and show progress toward it in the UI). Modes also emit `<id>.entered` / `<id>.finished` automatically.
Extra echoes/lore for your own mode: add `data/echo/<id>.json` and `data/lore/<id>.json` (kinds `echo`, `lore`; see `data/echo/spine.json` for format; ids prefixed `<id>_`). Lore text must be original, ASCII, and short (<400 chars).

## 5. Quality bar (read this twice)

The project is judged on *depth and polish of a few interacting systems*, not on feature counts. A mode must have:
1. A complete, understandable core loop with a skill ceiling and multiple viable strategies, a Facet Trial win condition, and a failure state with consequences.
2. First-time onboarding: contextual tutorial prompts the first time (use `app.profile["tutorial"]`), not a wall of text.
3. Responsive controls (input buffered where it matters, no mushy acceleration), readable feedback (hit-stop, shake via `Camera`, flashes via `FEEL`, floating numbers, audio) and a coherent visual identity from `docs/ART_BIBLE.md`. Procedural art must be carefully composed: outlines, ramps, consistent light, animation timing; do not ship flat coloured rectangles as final art. Bake sprites once and cache surfaces; never rebuild surfaces per frame.
4. Distinct enemy/opponent/agent behaviours (not stat swaps) using `core.ai` / `core.nav`, with perception limits, reaction times and no cheating (no omniscience, no hidden damage multipliers). Adaptive behaviour must go through `AdaptiveController` (bounded, cooled down, scaled by `difficulty.adaptive_ai`) and have a test proving an observable effect.
5. Procedural generation seeded and validated (reachability, objective placement, balance); on validation failure repair or regenerate, deterministically. Tests prove determinism and validity across many seeds.
6. Save/load of mode progress inside `self.data` and a tested round trip.
7. Difficulty presets and accessibility settings honoured; `toggle_hold` for held inputs where relevant.
8. Performance: average update+draw <= 8 ms/frame at 480x270 in your busiest realistic scene (measure with `time.perf_counter` in a test or tool and record the number in your doc). Optimise from measurements only.
9. No placeholder text, no debug labels in normal play, no missing textures, ASCII text only, no stub menu entries. If something is not implemented, it is not in the UI.
10. Honest docs: `docs/modes/<id>.md` with design, systems list, controls, how to test, and **Verified / Partially verified / Not implemented / Known issues** sections. Never claim what you did not run.

## 6. Anti-slop checklist (self-review before finishing)
Weapons/units/enemies differ in behaviour not just numbers; maps are not recolours; every system interacts with at least one other; no dead menu items; progression expands options rather than inflating stats; effects never obscure gameplay; text is wrapped inside its panel; nothing overflows the 480x270 frame.

## 7. Testing requirements
* Pure logic tests (no display needed): determinism, rules, collision/hit data, pathfinding, AI decisions, generation validity (many seeds), save round-trip, content validation of your data files.
* Integration test through the real `App` with the fixtures in `tests/conftest.py` (`app`, `run_ticks`): `app.enter_mode("<id>")`, run 600+ ticks with a scripted `VirtualDevice` bot exercising the core loop (not random mashing only), draw every 4th frame, assert no exception, assert the loop progressed (e.g. an enemy died, a lap completed), leave via `finish()`.
* Run `python -m pytest tests -q` before reporting; all core + your tests must pass. You can screenshot with `python tools/shot.py <id> out.png [frames]` and should look at the images (use the Read tool on the PNG) to review composition, readability and polish; iterate.
* Windows paths; Python 3.12; use `.venv\Scripts\python.exe`.

## 8. Report format (your final message)
Short: what exists and works (with evidence: test counts, measured ms/frame), what is partial, what is missing, files touched, core changes, known issues, and what you would do next. No marketing language.
