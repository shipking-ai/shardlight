# Status (verified claims only)

Last full test run: **419 tests, all passing** (about 5 minutes; `python -m pytest tests -q`). Last perf and screenshot pass: most recent pass, Windows 11, Python 3.12.10, pygame-ce 2.5.8, NumPy 2.x.

"Verified" below means an automated test asserts it, a headless screenshot of it was inspected, or a tool measured it. "Not verified by a human" applies to **every** shard: nobody has played or listened to the game (see `KNOWN_ISSUES.md`).

![contact sheet: hub and the eight shards in real gameplay](screens/contact_sheet.png)

## The eight shards

| shard | genre | state | what is solid | partial / missing |
|---|---|---|---|---|
| **Cinder** | action roguelike | complete, bot-verified | 5 floors, 9 weapons, 29 boons, 15 modifiers, 7 enemy types + 3 bosses; parry/dodge/charge; evolutions; bounded adaptive enemies; run/save flow; facet + cross-shard events | balance by arithmetic and bots only; no co-op |
| **Verdant** | open-world RPG | complete, bot-verified | seeded 256x256 world with 4 towns and 11 sites, validated reachable in both bridge states; 21 scheduled NPCs; 11 quests incl. a main chain that ends the facet; combat with 4 bosses; economy, crafting, 5 skills; bounded visible adaptation; lamps and night; fog map; save/load; echo in and out | reputation unused by prices/dialogue; menu dialogue; per-kind interiors; no fast travel/weather/mounts |
| **Umbra** | psychological horror | complete, bot-verified | solvable seeded buildings; noise/light stealth; three enemy senses; pacing director; bounded Understudy adaptation; 3 nights; relic echo | three nights only; whether it is frightening is a human call |
| **Slipstream** | racing | complete, bot-verified | seeded tracks with shortcuts; drift/draft/boost; rival AI under the player's limits; ghosts; garage; Salt Cup; 2-player split screen | one cup; handling not hand-tuned |
| **Concord** | strategy | complete, bot-verified | hex campaign, supply logistics, diplomacy with explained AI acceptance, tactical battles, fog-limited AI that adapts within bounds, three victory types, exact save round trip | house balance for a human; large map least tested |
| **Terrace** | sandbox survival | complete, bot-verified | 512x256 world, light, conservative fluids, density-limited ecology, crafting (86 recipes), Beacon and Keystone, edited-chunk persistence | herd clustering; no irrigation/wiring |
| **Masks** | fighting game | complete, bot-verified | 6 fighters with validated frame data, deterministic integer sim, training mode, replay with tamper detection, CPU with reaction delay, arcade, 2-player versus | six fighters; local play only |
| **Orrery** | space / civ sim | complete, bot-verified | ~80-system galaxy, conserved-goods civ sim with LOD, flight combat, trade, signal triangulation and decoding puzzles, Last Lamp trial | no planet surfaces |

Per-shard pages: [cinder](modes/cinder.md), [verdant](modes/verdant.md), [umbra](modes/umbra.md), [slipstream](modes/slipstream.md), [concord](modes/concord.md), [terrace](modes/terrace.md), [masks](modes/masks.md), [orrery](modes/orrery.md).

## Shared systems

| system | state |
|---|---|
| Fixed 60 Hz loop, scene stack with fades, 480x270 scaled output | verified (tests, runs) |
| Walkable hub, title, three save slots | verified by `test_app_flow`, `test_boot`, contact sheet; the hub's look was only inspected in screenshots |
| Save: versioned, checksummed, atomic, 3 backups, migrations, recovery | verified (`test_core_save`) |
| Content DB with schemas; data-only mods with dependencies/conflicts/overrides | verified; the sample mod adds quest/NPC/item/recipe/note content across two shards |
| Echoes (event -> declarative effects) and the cross-shard web | 19 echoes; `test_echo_web` runs the chain Orrery -> Verdant -> Cinder -> Concord/Terrace, Umbra -> Masks -> Slipstream -> Orrery, Concord -> Orrery, Terrace -> Orrery -> Verdant, Verdant -> Umbra through the real engine, and checks every unlock has a consumer |
| Input: two keyboard schemes, SDL controllers, remap, hot-plug, 2 players | verified with synthetic/virtual devices; **no physical controller tested** |
| Accessibility: reduce shake/flash, high contrast, colour assist, large text, speed, difficulty, adaptive-AI slider | implemented and unit-tested; not evaluated by users |
| Adaptive AI kit (`core/ai.py`): behaviour trees, utility, perception+memory, noise bus, bounded adaptation | used by Cinder, Slipstream, Masks, Concord, Umbra, Orrery, Verdant; bounds/cooldown/disable are tested in each |
| Procedural audio | 10 tracks x 3 layers + 167 effects rendered with a hashed manifest; **never listened to** (`AUDIO.md`) |
| Procedural content with validation | every shard validates and repairs its generated content; seed sweeps are in the tests |

## Measurements (headless; `python tools/perf.py`)

Average / p95 milliseconds for update + draw of one frame while a scripted bot plays the real game (no vsync or window presentation included):

| hub | cinder | verdant | umbra | slipstream | concord | terrace | masks | orrery |
|---|---|---|---|---|---|---|---|---|
| 2.0 / 2.8 | 0.9 / 1.1 | 1.3 / 1.8 | 1.8 / 2.4 | 2.3 / 2.6 | 1.1 / 1.4 | 2.2 / 3.2 | 0.9 / 1.1 | 0.7 / 0.9 |

Generation: Verdant world 0.8-1.0 s per seed (once, at "new journey"), dungeons ~10 ms. Audio render: ~40 s for everything.

## Content size
757 JSON entries in 41 kinds (`data/`); ~50,000 lines of Python in `shardlight/`, ~6,600 in `tests/`.

## How to reproduce the claims
```
python -m pytest tests -q                 # 419 tests
python tools/perf.py                      # frame costs
python tools/contact_sheet.py             # screenshots in docs/screens
python tools/gen_audio.py --check         # audio manifest integrity
python tools/ver_shot.py shots/v town     # one Verdant view (also night, interior, dungeon, combat, shop, map...)
```
