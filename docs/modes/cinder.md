# Cinder - action roguelike ("The spire that rebuilds itself")

Climb five floors of a tower whose rooms are rebuilt every run. Combat is readable: every enemy attack has a telegraph, dodging gives i-frames, and a well-timed parry opens a riposte. Weapons evolve according to how you fight; boons trade power for risk.

Code: `shardlight/modes/cinder/` (about 6,500 lines; `sim/` holds the pure simulation: rooms, combat, enemies, bosses, boons, statuses, run flow).

## Controls
**A** light attack / chain - **X** heavy (hold to charge) - **B** dodge roll - **Y** parry - **R** interact - **L** Ember Flare - **SELECT** boon list.

## Implemented and verified (`tests/modes/test_cinder.py`)
* Content (9 weapons, 29 boons, 15 modifiers, 7 enemies + 3 bosses) is JSON, schema-checked; invalid mod content is rejected without crashing.
* Seeded floor generation is deterministic and valid; difficulty and *heat* change encounters.
* Hit shapes, dodge i-frames (no damage inside, damage outside), parry window (too early / too late fails), unparryable attacks, charge armour; heavy attacks with charge tiers; weapon attacks hit in an arc and not behind.
* Status synergies with loop protection; Flashover damages neighbours in the room; kindled-edge and vampiric boons.
* Enemies do nothing without perception and have an explicit reaction delay; shield bearers block frontal but not flank hits; archers lead shots honestly and keep their distance; chargers telegraph and stun themselves on walls; bombers have fuses; summoners are capped; snipers show a beam line.
* **Adaptation is bounded** - counters change aim only within a limit, respect the adaptive-AI setting, and measurably alter an archer's aim when the player always dodges one way.
* Weapons evolve when their counters are met and change moves. Bosses have phases, telegraph everything and can be beaten.
* A scripted bot clears a room and the run saves and loads; death ends the run, awards soot and returns to the foot of the spire; the final boss repairs the facet and emits the cross-mode events; a big fight stays inside the frame budget.
* Echo: the optional **Choir Warden** only appears after `cinder.boss.choir_warden` is unlocked (Verdant's Listening Stones); defeating it emits `cinder.boss_defeated{boss:"choir_warden"}`.

Frame cost with the bot in a fight: ~0.9 ms average (`tools/perf.py`, headless).

## Partial / not implemented
* Balance was tuned only by bot and arithmetic - no human playtest.
* No co-op. No controller rumble.
* Meta progression (soot unlocks) is a single currency with weapon/boon/mod unlock lists; there is no skill tree.

## Data kinds
`cinder.weapon`, `cinder.boon`, `cinder.enemy`, `cinder.modifier`.
