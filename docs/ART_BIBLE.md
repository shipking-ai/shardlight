# SHARDLIGHT Art Bible

## Pillars
1. **One lens, eight refractions.** The game is a single broken lens; each shard refracts it into a different palette, light behaviour and shape language. Within a shard everything obeys that shard's rules; across shards the *UI language* stays constant (brass-notched panels, pixel font, ink backgrounds) so the player always knows where they are.
2. **Light is the main drawing tool.** Dark values carry shape, a single warm key light carries focus. Lighting (`core.fx.Lighting`) is used where it adds mood; don't light everything.
3. **Readability first.** Player, hazards and interactables must read at 480x270 in under 200 ms. Silhouette > detail. Projectiles are brighter than their background by at least 40% value. VFX never cover the player.
4. **Pixel integrity.** Internal resolution 480x270, integer scale only, no antialiased scaling, no rotated sprites unless pre-rotated by bake (rotation of tiny sprites turns to mush; bake N angles).

## Global rules
* Outline: 1px, colour = darkest shade of the sprite's palette (not pure black) for characters/props; terrain has no outline, uses edge highlights.
* Ramps: 4 steps (shadow, base, light, highlight): **cool shadows, warm highlights**; light comes from the upper-left.
* Dither: ordered Bayer dither for gradients (`art.dither_vertical`); no smooth gradients in sprites.
* Animation: anticipation (2-4 f) / action (1-3 f) / recovery (6+ f). Squash on landing, hit flash of 2-3 frames (`art.white_flash`), hit-stop 2-6 frames (`FEEL.add_hitstop`), trauma shake <= 0.5 for normal hits.
* Typography: only the built-in 5x8 pixel font. 1x for body, 2x for headers. Light text (`PARCHMENT`) on dark panels with a 1px dark outline.
* Colour: `INK (16,15,28)`, `PARCHMENT (238,228,200)`, `BRASS (222,168,70)`, `LENS (130,214,255)`, `DANGER (240,100,90)`, `GOOD (130,230,150)` are reserved UI colours; gameplay palettes avoid using them for hazards so UI stays unambiguous.
* Effects budget: <= 1500 particles, < 8 additive glows on screen; screen flashes respect `FEEL.flash` (reduce_flash) and shake respects `Camera.add_trauma` (reduce_shake).
* Procedural variety: variants differ in **silhouette and structure** (proportions, parts, animation timing), not just hue. Recolour-only variants are rejected.

## Shard identities
| shard | genre | palette (dark -> key -> accent) | shape language | light | camera/view |
|---|---|---|---|---|---|
| Cinder | action roguelike | charcoal `#17141c`, ash `#3a3340`, ember `#ff7a3c`, gold `#ffc25a` | sharp angles, shards, chevrons; telegraphs are radial and bright | hard rim lights from braziers, orange-vs-violet | top-down, 3/4 |
| Verdant | open-world RPG | moss `#2c4a34`, leaf `#78c85a`, parchment `#e9dcae`, dusk rose `#d98a7a` | round, soft, hand-drawn; ink-green outlines instead of black | warm daylight with day/night tint cycle | top-down overworld |
| Umbra | psychological horror | near-black `#07090e`, sick teal `#2f5a5a`, bone `#c9c3b0`, one warm lamp `#ffb060` | tall narrow verticals, silhouettes, negative space | darkness is the default; one flickering lamp; cone flashlight | top-down, light-driven |
| Slipstream | futuristic racing | salt white `#f1efe6`, vermilion `#ef4b33`, ultramarine `#2a3fb0`, ink `#14152a` | long horizontals, speed wedges, flat colour blocks | low sun, long shadows | top-down, chase camera, split-screen |
| Concord | strategy / empire sim | vellum `#d9c9a0`, ink `#2b2438`, wax red `#a8323a`, four house colours | cartographic: hex tiles, flat shapes, hatching | none (paper lighting), subtle texture | map view + battle view |
| Terrace | sandbox survival | soil `#5a3d2b`, stone `#8a8590`, grass `#6fa84a`, sky `#8fd0e8`, ore accents | blocky 8px tiles with bevelled edges; layered depth | sun/moon cycle, torch light, caves dark | side view scrolling |
| Masks | 2D fighting | rice paper `#ece3cf`, ink wash `#262234`, vermilion `#d63a2c`, lacquer gold `#d9a441` | bold brush silhouettes, mask faces, paper lanterns | stage-lit, rim light per fighter colour | side view, fixed stage camera with zoom |
| Orrery | space exploration & civ sim | deep indigo `#0e0c24`, brass `#c9a24a`, star white `#f4f1ff`, signal cyan `#6fe0ff` | concentric orbits, clockwork gears, thin lines | star-lit, planet terminators | top-down space + system/galaxy map |

## Asset provenance
Everything is generated procedurally by code in this repository (no third-party art or audio). Fonts: original 5x8 pixel font in `core/font.py`. Audio: synthesised with `core/synth.py`. See `docs/ASSETS.md`.
