# Verdant - open-world RPG ("Hollowmere keeps its debts")

A top-down action RPG in a seeded 256x256-tile countryside: four towns, a river with a broken bridge, a high moor, a marsh, a greywood, eleven landmark sites and three dungeons. Townsfolk keep daily schedules, shops keep and restock stock, enemies telegraph, and the great quest is to repay the Lamplighter's debt and kindle the Hollow.

Code: `shardlight/modes/verdant/` (about 7,000 lines): `worldgen.py` + `landmarks.py` + `noise.py` (world), `interiors.py` (rooms and dungeons), `sim.py` (clock, player, economy, persistence), `combat.py`, `npcs.py`, `quests.py`, `actions.py`, `art.py`, `scene.py` + `screens.py`, `sfx.py`.

## Controls
Move (stick / WASD) - **A** attack (arc) - **X** dodge roll (i-frames) - **Y** fire bow - **B** talk / use / enter / pick / light lamp - **L / R** cycle quick consumable - **SELECT** journal (Pack, Quests, Map, Skills, Beasts) - **PAUSE**.

## Implemented and verified by automated tests (`tests/modes/test_verdant.py`, `tests/test_echo_web.py`)
* **World generation** - seeded noise terrain, a routed river with three crossings (ford, the broken Kestrel Bridge, a stone bridge), biome classification, four settlements and eleven sites placed from 14 JSON templates, roads (A*, string-pulled), lamps, decoration, hidden caches (tree ring, chime door, cairn, dig spot) and monster zones. Validated: every site, door, cache and entrance is reachable from the start in *both* bridge states; failures are repaired by carving corridors, then by trying the next attempt. Eight seeds are tested for validity, one for determinism (same seed => identical digest, different seed => different).
* **Templates** are data (`data/verdant.template/`); `tools/gen_verdant_templates.py` is the layout DSL used to compose them (a mod may replace any template).
* **Interiors and dungeons** - nine interior layouts (inn, shop, healer, smithy, lamp house, cottage, hut, hall, the Hollow Hall) serving 19 building types; seeded dungeons (Hollow Roots, Cairn of Debts, Drowned Crypt, Beneath the Stones) with reachability validation, bosses placed in the farthest room, chests, ore and dressing.
* **Time and NPCs** - a ten-minute day. 21 NPCs follow schedules (home, work, inn, front square, field markers), sleep in beds, walk out of buildings when you watch and snap when you do not; shops are only open while the keeper stands at the counter.
* **Combat** - melee arc with hit-stop, roll with i-frames, bow with arrows and mild aim assist. Enemy kinds: melee (wind-up telegraph), ranged (keeps distance, aimed shot), pack (wolves circle then lunge), lurkers (night-only bogwights and shades, weak to lamplight, repelled by lit lamps). Four bosses with telegraphed circle/ring/fan/charge attacks and add phases (Captain Rook, the Collector, the Bell Warden, the Root Mother), each dropping its quest item.
* **Bounded adaptation** (core `AdaptiveController`) - habitual melee makes a few bandits carry a *visible* shield (frontal hits 70% reduced, "Guarded" shown); habitual bow use makes archers close in and wolves circle faster. Level is capped, slew-limited and cooled down; the settings slider scales it and 0 disables it (tested).
* **Economy** - 9 shops with markup, stock, restock each dawn, resale that cannot be arbitraged, caravan goods after the Orrery echo, 14 recipes at hearth / forge / bench with skill gates, five skills (blade, bow, forage, delve, vigor) that change damage, yield, speed and HP.
* **Quests** - data-driven stage engine (talk / kill / have / visit / lamps / flag / use). Eleven quests including the main chain First Light -> The Lamplighter's Debt -> Kindle the Hollow (tested end to end), a bridge repair that really rebuilds the Kestrel crossing, and an echo-gated quest.
* **Lamps** - light them with tapers; they stay lit until dawn and push the night creatures back; after the debt is repaid the Lamplighters light every lamp at dusk.
* **Persistence** - full to/from dict round trip (tested equal), including dungeon location; a shard left through the pause menu is saved; bad saves are rejected.
* **Echoes** - emits `verdant.quest_completed{quest}` (the `lamplighters_debt` echo unlocks Umbra's Lantern Ward), `verdant.site_explored{site:"listening_stones"}`, and the facet through `complete_facet("verdant")` when *Kindle the Hollow* ends. Consumes `verdant.site.listening_stones` (the hidden stones appear on the moor, an extra quest opens) and `verdant.trade.beacon_caravans` (shops stock Star Salt and Beacon Lenses). A five-shard chain through the real echo engine is tested.
* **Rendering** - chunk-cached terrain with blended edges, procedural sprites for every object, building facades, villagers and creatures, day/night lighting with lamp light and lit windows, a minimap and a fog-of-war map. Frame cost measured in the headless harness: about 1.3 ms average, 1.8 ms p95 in the meadow (`tools/perf.py`).
* **Sound** - 27 synthesised effects rendered to `assets/audio/sfx/verdant_*.wav`; the pastoral 6/8 "verdant" track plays.

## Partial
* Reputation is recorded (and visible to echoes) but does not change prices or dialogue.
* Dialogue is menu-based: greeting by time of day, quest offers/turn-ins, topics gated by flags - there are no branching trees.
* Interiors are generated per building *kind* (all inns look alike) rather than authored per building.
* NPCs and enemies do not avoid one another; two people can overlap when their paths cross.
* There is one wayshrine per world (the ford shrine): it heals and sets the respawn point (otherwise you wake near Wickering's arrival road). There is no fast travel.

## Not implemented
Weather, horses/boats, marriage or companions, a full faction-war simulation, branching quest consequences beyond flags and rep, animal husbandry, and tree felling (planks are bought).

## Data kinds (modding)
`verdant.template`, `verdant.item`, `verdant.enemy`, `verdant.npc`, `verdant.quest`, `verdant.shop`, `verdant.recipe`, `verdant.loot`. See `mods/sample_pack` (a new NPC with a quest, an item and a recipe) and `docs/MODDING.md`.

## Balance notes
The 10-minute day, enemy hit points and prices were set by reasoning and bot runs, not by human play; expect to retune `data/verdant.*`.
