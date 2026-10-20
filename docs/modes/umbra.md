# Umbra - psychological horror survival ("Three nights in the Gloaming Ward")

Top-down stealth in a generated building. Light and sound are the whole game: the **Hark** listens, the **Stillwatch** only sees what is lit, and the **Understudy** learns where you hide. Each night has an objective (restore power, find keys, escape), safe rooms, and a pacing director.

Code: `shardlight/modes/umbra/` (about 4,600 lines): `levelgen.py` (BSP building + solvable objective chains), `sim.py`, `consts.py`, `enemies.py`, `director.py`, `view.py` (shadow-casting renderer), `scene.py`, `catalog.py`, `props.py`, `sfx.py`.

## Controls
Move - **A** run (loud) - **L** sneak (quiet) - **B** interact / search / hide / read - **X** use or throw item - **R** next item - **Y** flashlight / lamp / off - **SELECT** bag and journal.

## Implemented and verified (`tests/modes/test_umbra.py`)
* **Level generation** - seeded BSP buildings with room roles from `umbra.room` templates, doors, locks, hiding places and safe rooms; a *solvability fixed point* proves keys and fuses are reachable without needing something behind their own lock. Many seeds validated.
* **Light and sound** - noise propagates through doors and walls with occlusion; the flashlight, lamp and room lights drive visibility; a multiply-lit shadow-casting renderer draws what you can see.
* **Three enemy senses** - the Hark hears (running, throwing, doors), the Stillwatch sees only lit cells, the Understudy remembers hiding spots; all use memory with decay and reaction delays (core `ai.Memory`, `NoiseBus`).
* **Director** - a calm / build / peak / relax state machine bounds how much pressure the player receives; adaptation is bounded and observable (the Understudy checks lockers you use habitually).
* Objectives, crafting (3 recipes), 22 items, 36 notes, 11 story dressings, checkpoints/respawn, hide mechanics, save/restore of a night, and the night-by-night flow with the stopped clock relic.
* Echoes: finishing the nights repairs the facet; `umbra.relic_found{relic:"stopped_clock"}` unlocks Masks' Warden of Hours; `umbra.night_survived{night}` is emitted; the Lantern Ward item appears after Verdant's debt echo.

Frame cost in a night: ~1.8 ms average (`tools/perf.py`).

## Partial / not implemented
* Three nights only. No voice acting; audio is synthesised.
* The enemies were tuned with bot runs; whether the dread *works* is a human judgement not yet made.
* Hiding spots are limited to lockers, cabinets, beds and coffins.

## Data kinds
`umbra.item`, `umbra.note`, `umbra.enemy`, `umbra.room`, `umbra.story`, `umbra.night`, `umbra.recipe`.
