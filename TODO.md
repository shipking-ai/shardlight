# TODO

Every open item is a GitHub issue; the code carries a matching `TODO(#n)` marker at the place to start (`python tools/todos.py` lists them, `tests/test_todos.py` keeps the convention honest). Older notes of what is not done live in [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

Open issues: https://github.com/shipking-ai/shardlight/issues

## Verify with people and hardware

| issue | what | start here |
|---|---|---|
| [#1](https://github.com/shipking-ai/shardlight/issues/1) | Hand-play every shard and retune the numbers | `docs/STATUS.md` |
| [#2](https://github.com/shipking-ai/shardlight/issues/2) | Listening pass for the music and sound effects | `tools/gen_audio.py` |
| [#3](https://github.com/shipking-ai/shardlight/issues/3) | Test with physical game controllers | `shardlight/core/input.py` |
| [#4](https://github.com/shipking-ai/shardlight/issues/4) | Run in a real window on Linux, macOS, and high-DPI / multi-monitor setups | `shardlight/core/app.py` |
| [#5](https://github.com/shipking-ai/shardlight/issues/5) | Measure real frame times with a window, vsync and on low-end hardware | `tools/perf.py` |

## Verdant

| issue | what | start here |
|---|---|---|
| [#6](https://github.com/shipking-ai/shardlight/issues/6) | Verdant: make reputation matter | `shardlight/modes/verdant/sim.py` |
| [#7](https://github.com/shipking-ai/shardlight/issues/7) | Verdant: branching dialogue | `shardlight/modes/verdant/actions.py` |
| [#8](https://github.com/shipking-ai/shardlight/issues/8) | Verdant: authored, per-building interiors | `shardlight/modes/verdant/interiors.py` |
| [#9](https://github.com/shipking-ai/shardlight/issues/9) | Verdant: separation steering for NPCs and enemies | `shardlight/modes/verdant/combat.py` |
| [#10](https://github.com/shipking-ai/shardlight/issues/10) | Verdant: more world - fast travel, felling trees, weather | `shardlight/modes/verdant/tiles.py` |
| [#11](https://github.com/shipking-ai/shardlight/issues/11) | Verdant: remove the first-draw chunk hitch | `shardlight/modes/verdant/scene.py` |
| [#12](https://github.com/shipking-ai/shardlight/issues/12) | Verdant: save migration framework and tests | `shardlight/modes/verdant/sim.py` |

## Other shards

| issue | what | start here |
|---|---|---|
| [#13](https://github.com/shipking-ai/shardlight/issues/13) | Concord: balance the four houses for a human and test the large map | `shardlight/modes/concord/info.py` |
| [#14](https://github.com/shipking-ai/shardlight/issues/14) | Terrace: herbivores cluster and over-graze near the player; add irrigation | `shardlight/modes/terrace/ecology.py` |
| [#15](https://github.com/shipking-ai/shardlight/issues/15) | More content: cups, fighters, nights, planets | `shardlight/modes/slipstream/defs.py` |

## Engineering

| issue | what | start here |
|---|---|---|
| [#17](https://github.com/shipking-ai/shardlight/issues/17) | Speed up the test suite (about 5 minutes) | `tests/test_modes_smoke.py` |
| [#18](https://github.com/shipking-ai/shardlight/issues/18) | CI: update GitHub Actions versions and add dependency caching for audio | `.github/workflows/ci.yml` |

## Convention

* A TODO in code is written `# TODO(#12): short reason`, and the issue holds the detail and the definition of done.
* New work item: open the issue first, then add the marker.
* When an issue is closed, remove its markers in the same change.
