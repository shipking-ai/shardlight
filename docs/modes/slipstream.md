# Slipstream - futuristic racing ("Salt, speed and one more corner")

Seeded salt-flat circuits with drift-to-boost, drafting, risky shortcuts, upgrades, ghosts and a championship. One or two players (split screen).

Code: `shardlight/modes/slipstream/` (about 3,000 lines): `track.py` (generation), `physics.py` + `vehicle.py`, `race.py` (rules, laps, ghosts), `ai.py`, `scene.py`, `art.py`, `sfx.py`.

## Controls
**UP / A** accelerate - **B** brake / reverse - **X** handbrake (drift) - **Y** boost - **R** rewind (Chronograph) - **SELECT** reset to track. Player 2 uses keyboard scheme B or a second pad.

## Implemented and verified (`tests/modes/test_slipstream.py`)
* Tracks are deterministic and valid over many seeds; geometry properties are checked (see `test_track_geometry_properties`); shortcuts rejoin the track and never contain a required checkpoint.
* Physics: top speed matches the vehicle spec, brakes stop the car, salt has less grip than tarmac, oil is slippery.
* Drift builds boost, commits when clean and cancels on a crash; boost exceeds top speed; drafting refills the meter; car-to-car collisions are symmetric and stable.
* Upgrades change stats with trade-offs (5 vehicles, garage purchases persisted).
* The AI field completes laps *without cheating speed* and uses the same limits as the player; rivals overtake and recover from spins; adaptation is bounded, scaled by the setting and observable.
* Skipping checkpoints does not count a lap; the Chronograph vehicle rewinds once per lap and is gated by the echo `slipstream.vehicle.chronograph`.
* Ghost packs round-trip; single-player scene with a bot driver completes a lap; split-screen has separate viewports and inputs; controller loss pauses and the race resumes.
* Winning the Salt Cup emits `slipstream.championship_won{cup:"salt_cup"}` (unlocks the Salt Runner hull in Orrery) and repairs the facet; best times and credits persist.

Frame cost in a race: ~2.3 ms average (`tools/perf.py`).

## Partial / not implemented
* One championship cup; no online play; no track editor.
* Handling was validated by tests and bot laps, not by human feel; expect to tune `data/slipstream.vehicle`.
* Two humans share one screen on one machine only.

## Data kinds
`slipstream.vehicle`, `slipstream.cup`.
