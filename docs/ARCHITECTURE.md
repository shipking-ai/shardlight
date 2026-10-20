# Architecture

```
shardlight/
  __main__.py        CLI entry (python -m shardlight)
  core/              engine shared by every mode
    app.py           window, fixed-timestep loop, services, profile load/save, toasts, post-process
    scene.py         Scene, ModeScene, ModeInfo, SceneStack (queued push/pop/replace/reset with fades)
    input.py         devices (keyboard schemes, SDL controllers, virtual), per-slot PlayerState, buffering, remap capture
    audio.py         AudioManager: layered music with crossfades & intensity, SFX variants, silent fallback
    synth.py, music.py, sfxlib.py   procedural audio authoring (offline render to assets/audio)
    content.py       ContentDB + declarative schema validation; kinds registered by modes
    mods.py          data-only mod loader (manifest, dependencies, conflicts, overrides, reports)
    world.py         World (flags/unlocks/lore/rep/facets), Echo engine (event -> declarative effects), Economy caps
    save.py          versioned JSON envelope, sha256, atomic write, 3 rolling backups, migrations, recovery
    settings.py      validated/clamped settings with corruption recovery
    fx.py            Camera (trauma), Feel (hit-stop, flash), particles, Lighting, easing
    art.py, font.py  procedural art helpers; original 5x8 pixel font
    ai.py, nav.py    behaviour trees, utility AI, perception+memory, NoiseBus, PlayerModel/AdaptiveController; A*, LOS, flow fields, spatial hash
    ui.py            panels, menus, pause/settings/accessibility/controls screens, dialogue
    rng.py, paths.py, log.py
  hub/               title, slot select, Prism Observatory hub, shard cards, archive, forge, desk
  modes/<id>/        one package per shard; INFO + create() + register_content()
data/                base game content (JSON): echo, lore and every mode's `<id>.*` kinds
mods/                data-only mods (sample_pack included)
assets/audio/        generated WAV music stems and SFX + MANIFEST.json
tests/               unit, integration and per-mode tests
tools/               gen_audio.py (render audio + manifest), perf.py, contact_sheet.py, gen_verdant_templates.py, per-shard *_shot.py headless screenshot scripts
```

## Data flow

1. `App` boots pygame, settings, input (controller hot-plug), audio, saves, then **content**: each available mode registers its kinds, base `data/` is loaded, then mods (dependency-sorted, validated, overrides explicit). Problems are collected, never fatal, and visible in the hub Archive (Mods tab).
2. The loop runs fixed 60 Hz ticks (`TICK`), up to 5 per rendered frame; input edges are exact per tick (sub-frame taps are preserved). `access.game_speed` slows the accumulator, so simulation stays frame-deterministic.
3. Scenes are a stack: Title -> Slots -> Hub -> mode root scene (+ overlays such as pause). Scene changes are queued and applied between ticks with a fade.
4. Modes never import each other. Cross-mode consequences flow through `World.emit(event, **payload)`; `data/echo/*.json` (base or mod) turns events into effects (flags, unlocks, lore, glint grants, reputation, toasts, follow-up events, with a cascade bound). Modes read the results with `world.has_unlock(...)`.
5. Saves: `profile` dict (flags, unlocks, lore, facets, reputation, per-mode private JSON `modes[mode_id]`) -> `SaveManager` (checksummed envelope, atomic replace, backups) -> recovery falls back through backups with a visible notice.
6. Rendering: every scene draws into a 480x270 surface; `App` applies accessibility filters (colour assist), toasts and overlays, then presents with `pygame.SCALED` (integer-scaled, letterboxed, vsync). No OpenGL dependency (see RESEARCH.md for the decision).

## Determinism & reproducibility

All procedural content derives from `core.rng.Rng(seed)` with labelled child streams, so the same seed reproduces the same world, track, floor, galaxy. The Masks combat core is integer-only and replay-verified by state hash. Seeds are surfaced in each mode and accepted through shard-card options for bug reports.

## Extension points

* New content: JSON into `data/<kind>/` or a mod. Kinds + schemas are registered by modes (`register_content`).
* New mode: add `shardlight/modes/<id>/` per `docs/MODE_CONTRACT.md`, append the id to `MODE_IDS`.
* New cross-mode behaviour: author an `echo` entry; no engine change needed.
