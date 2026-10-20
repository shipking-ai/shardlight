# Terrace - sandbox survival and construction ("Dig, build, and keep the vigil")

A side-on world of meadow, forest, salt flats and ice with caves down to lava. Craft up the tool tiers, tame the grazers, outlast the night, and raise the Keystone on its plinth.

Code: `shardlight/modes/terrace/` (about 5,100 lines): `grid.py`, `world.py`, `worldgen.py` (512x256 tiles, validated), `registry.py`, `light.py`, `fluids.py`, `inventory.py`, `player.py`, `ecology.py`, `structures.py`, `game.py`, `scene.py`, `art.py`, `sfx.py`.

## Controls
Move - **A** jump - **X** mine / attack (hold) - **Y** place / use - **B** interact (doors, beds, chests, shrines) - **L / R** hotbar - **SELECT** pack and crafting - **UP / DOWN** aim.

## Implemented and verified (`tests/modes/test_terrace.py`)
* 512x256 numpy tile world with biomes, caves, ores, lakes, trees, ruins and a protected Keystone site; generation is seeded, deterministic and validated (cliffs, obstructed plinth, overlapping features are repaired).
* Chunked render cache; **light propagation** (sun and torch light flood-filled, with correct blocking); a **conservative fluid cellular automaton** (water and lava conserve volume; obsidian forms where they meet).
* 60 block types, 116 items, 86 recipes, crafting with stations and a fuel buffer, tool tiers, drops, placement/breaking rules.
* Platformer physics (fall damage, ladders, swimming), day/night with danger at night, beds and respawn.
* **Ecology** - a density-limited food web (grazers, predators) with breeding, per-capita forage, species caps and level-of-detail stepping far from the player.
* Structures: the Beacon and the Keystone stencils with a Vigil; edited chunks persist, so only changed terrain is saved; save/load round-trips.
* Echoes: building a beacon emits `terrace.structure_built{kind:"beacon"}` (Orrery signal); lighting the Keystone repairs the facet; Cinder Iron and the Choir Alloy recipe are gated by unlocks.

Frame cost: ~2.2 ms average, p95 3.2 ms (`tools/perf.py`).

## Partial / not implemented
* **Known balance caveat:** herbivores cluster and can graze an area bare near the player; breeding is capped but the distribution is not natural.
* No multiplayer, no wiring/redstone-like logic, no boss creature beyond the night threats.
* Farming exists for a small crop set (see `terrace.recipe`); there is no irrigation.

## Data kinds
`terrace.block`, `terrace.item`, `terrace.recipe`, `terrace.creature`, `terrace.structure`.
