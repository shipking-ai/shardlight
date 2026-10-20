# Research ledger and dependency inventory

Date of research: 2026-10-19. Environment audited first: Windows 11, Python 3.11.15 (default) / 3.12.10 / 3.14 installed, NVIDIA RTX 2080 Super Max-Q, 32 GB RAM, one audio device (mixer init OK at 44.1 kHz stereo), no game controller attached, empty workspace, no git repository.

## Verification legend
* **fetched** - read from the primary source (PyPI JSON or official docs page) during this project.
* **probed** - verified by running code in this environment.
* **recalled** - background knowledge, not re-verified here (marked so on purpose).

## Ledger

| # | candidate | source | finding | status | licence | decision |
|---|---|---|---|---|---|---|
| 1 | **pygame-ce 2.5.8** | pypi.org/pypi/pygame-ce, pyga.me | actively maintained fork of pygame; requires Python >=3.10; installs wheels for 3.12 on Windows; SDL 2.32.10 | fetched + probed | LGPL-2.1-or-later | **adopted** (renderer, input, mixer). Pinned in requirements.txt |
| 2 | pygame (original) | recalled | slower release cadence than the CE fork; CE adds `SCALED` improvements, `Window` API, bug fixes | recalled | LGPL-2.1 | not used; pygame-ce is API-compatible |
| 3 | **NumPy 2.5.4** | pypi.org/pypi/numpy | requires Python >=3.12; licence expression BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | fetched + probed | BSD-3-Clause family | **adopted**: audio synthesis, colour-assist filter, chunk arrays, tests |
| 4 | pytest 9.1.1 | pypi.org/pypi/pytest | requires Python >=3.10 | fetched | MIT | **adopted** (dev) |
| 5 | pygame display `SCALED` flag | pyga.me/docs/ref/display.html | logical-resolution window, mouse coordinates auto-scaled, labelled experimental, `vsync=1` available without SCALED since 2.2.0 | fetched | - | **adopted**: fixed 480x270 logical surface, crisp scaling; headless tests use a plain surface. Risk (experimental flag) mitigated by try/except fallback in `App._create_window` |
| 6 | `pygame._sdl2.controller` (SDL GameController API) | docs page not found (404 at pyga.me/docs/ref/controller.html); module and constants probed locally | provides standardised button/axis names across pads and device add/remove events (`CONTROLLERDEVICEADDED/REMOVED`, `CONTROLLERBUTTON*`, `CONTROLLERAXISMOTION`) | probed (module present; no physical pad to test) | LGPL | **adopted** with fallback to keyboard-only if init fails. Hot-plug/remap logic is unit-tested with synthetic events; **real hardware is unverified** |
| 7 | moderngl 5.13.0 | pypi.org/pypi/moderngl | OpenGL wrapper, requires Python >=3.7 | fetched | MIT | **rejected**: shader post-processing would add a hard GPU/driver dependency and a second render path; all required effects (lighting, glow, colour assist) are achieved in software at 480x270 within budget. Revisit only if profiling demands |
| 8 | pymunk 7.3.1 | pypi.org/pypi/pymunk | Chipmunk2D physics, requires Python >=3.9 | fetched | MIT | **rejected**: modes need deterministic, controllable kinematics (fighting game integer sim, tile platformer, arcade car model); a general rigid-body engine adds nondeterminism and tuning cost without solving a stated problem |
| 9 | pygame-gui 0.6.14 | pypi.org/pypi/pygame-gui | UI toolkit for pygame-ce, Python >=3.10 | fetched | MIT | **rejected**: the game needs a bespoke pixel UI language and gamepad-first navigation; a custom ~400-line UI module (`core/ui.py`) is simpler and consistent |
| 10 | Pathfinding libs (e.g. `pathfinding`) | recalled | exist | recalled | MIT | **rejected**: grid A*/flow fields are small and are implemented/tested in `core/nav.py` |
| 11 | Behaviour tree libs (py_trees etc.) | recalled | exist | recalled | various | **rejected**: tiny custom BT/utility/perception kit in `core/ai.py`, deterministic and dependency-free |
| 12 | Audio synthesis (pyo, FluidSynth, soundfile...) | recalled | exist | recalled | various | **rejected**: native-library installation burden; NumPy synthesis renders original WAV assets offline (`core/synth.py`, `core/music.py`) |
| 13 | Save format | design | JSON only (never pickle) with sha256 envelope, schema version, atomic `os.replace`, 3 backups, migrations | probed (tests) | - | **adopted** |
| 14 | Mod format | design | data-only JSON mods with manifest, dependency/conflict resolution, schema validation, explicit overrides | probed (tests) | - | **adopted**; scripting mods deliberately not offered (no safe sandbox in CPython) |
| 15 | Fonts | design | pygame's default font is TTF-based and platform-dependent; an original 5x8 bitmap font keeps text crisp at integer scales and is licence-free | probed (specimen reviewed) | project | **adopted** |

## Open uncertainties and plans
1. **Real controller hardware** is not available in this environment: input logic is verified with synthetic SDL events only. Plan: manual pass with Xbox/PlayStation pads when available; behaviour bugs would most likely be in axis dead zones and hot-plug slot reclaim.
2. **Audio listening** has not been performed: audio is validated structurally (loop seams, clipping, spectra, scale statistics) - see AUDIO.md. A human listening pass is outstanding.
3. **Experimental `SCALED`**: fallback exists; verify on multi-monitor and high-DPI setups.
4. **Performance on lower-end GPUs/CPUs**: measured only on this machine (see per-mode docs for numbers).
