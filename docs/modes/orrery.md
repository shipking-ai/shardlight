# Orrery - space exploration and civilisation simulation ("A galaxy that keeps its own books")

Fly a salvage ship through a seeded galaxy of eighty-odd systems. Five civilisations trade, expand and fight whether or not you watch. Triangulate stray signals, solve their locks, and wind the five gears of the Last Lamp.

Code: `shardlight/modes/orrery/` (about 6,000 lines): `orbits.py` (Kepler), `galaxy.py`, `civsim.py` (economy and expansion with level-of-detail and a conserved-goods ledger), `flight.py` (Newtonian ship combat), `signals.py` (triangulation and puzzles), `game.py`, `defs.py`, `scene.py`, `screens.py`, `art.py`, `sfx.py`.

## Controls
**UP / LEFT / RIGHT** thrust and turn - **A** pulse cannon - **B** hold: lock a missile - **X** hold: beam - **Y** boost - **L** decoy - **R** hold: dock / scan / gear - **SELECT** star chart.

## Implemented and verified (`tests/modes/test_orrery.py`)
* Galaxy generation is seeded and validated (connected lanes, homes, a reachable start and Last Lamp, signal sources, extra hidden lanes). Kepler orbits drive body positions.
* **Civilisation simulation** - five civs with economies, trade routes, expansion and war; level-of-detail stepping; a goods ledger that conserves quantities; a state hash used to verify save/load equality; trading does not allow instant arbitrage.
* Ship flight and combat (pulse, missiles with lock, beam, decoys, boost cost), module/hull outfitting, station services, missions, diplomacy, and a log.
* **Signals** - detect, triangulate between systems, then decode with sequence/lock puzzles; decoding emits `orrery.signal_decoded{signal}` (the Choir Signal unlocks Verdant's stones).
* Cross-mode effects *consumed*: the Concord treaty adds an envoy barge to the galaxy (`orrery.contact.concord_envoys`), the Terrace beacon adds a new signal source (`orrery.signal.beacon_echo`), and the Salt Runner hull is gated by the Slipstream cup (all three are exercised in `tests/test_echo_web.py`).
* Supply missions come from real shortages in the simulated economy; the pursuing hunter adapts but stays bounded; spawns follow the menace level deterministically.
* The Last Lamp (three signals decoded and lit in the right order) repairs the facet; save/load of a voyage, and corrupt saves are rejected rather than crashing.

Frame cost: ~0.7 ms average in flight (`tools/perf.py`).

## Partial / not implemented
* Planet surfaces are not playable; landing is docking at stations.
* The civilisation simulation is aggregate (no individual ships outside the player's region).
* The Last Lamp trial was verified by scripted play, not by a human.

## Data kinds
`orrery.civ`, `orrery.good`, `orrery.hull`, `orrery.module`, `orrery.signal`, `orrery.tech`, `orrery.weapon`.
