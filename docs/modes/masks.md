# Masks - 2D fighting game ("The Gauntlet of Masks")

Six fighters, frame-data combat, a training mode, arcade ladder, CPU opponents with a reaction model, and local two-player versus.

Code: `shardlight/modes/masks/` (about 3,800 lines): `sim/` (deterministic fixed-step simulation and frame data), `cpu.py`, `replay.py`, `render.py`, `scene.py`.

## Controls
**A** light - **B** medium - **X** heavy - **Y** parry (tight) - **R / L** forward / back dash - **SELECT** training options - **PAUSE** pause and move list. Player 2: keyboard scheme B or a second controller.

## Implemented and verified (`tests/modes/test_masks_sim.py`, `test_masks_integration.py`)
* Every character passes frame-data validation; the six archetypes are distinct; start-up frames match the data; hit advantage is recorded for the on-screen frame-data display.
* Blocking needs the correct height; throws beat blocks and can be teched; parry punishes the attacker and spam is penalised; combo proration and a damage cap apply; projectiles travel, hit and are limited; zones slow only the opponent; counter stances answer matching heights; supers cost meter; KO / timeout / round / match flow is right.
* The simulation is **deterministic** over random inputs, and every character pair survives random play.
* CPU matches finish deterministically; the CPU has a reaction delay (it cannot block a jab on reaction) and punishes unsafe moves using real frame data; its adaptation raises anti-air within a bound.
* Replays round-trip and detect tampering; training settings and replays persist across saves.
* Two simultaneous human inputs are independent; losing a controller pauses with a clear message and the keyboard can resume.
* Arcade clear repairs the facet and emits rival defeats; the locked fighter (Toki) appears only after `masks.rival.warden_of_hours` (Umbra's stopped clock) and mods can add fighters. Defeating the rival emits `masks.rival_defeated{rival}` (unlocks the Chronograph in Slipstream).

Frame cost in a match: ~0.9 ms average (`tools/perf.py`).

## Partial / not implemented
* Six fighters only; no rollback netcode (local play only).
* CPU difficulty (4 levels) was checked by simulation, not by human opponents.
* No story cut-scenes.

## Data kinds
`masks.character`.
