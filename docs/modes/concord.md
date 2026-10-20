# Concord - strategy and empire simulation ("Ledger of Crowns")

Four houses share one hex map and no calendar. March armies along roads you can feed, sign treaties you may regret, and settle borders on the battlefield or on paper.

Code: `shardlight/modes/concord/` (about 6,700 lines): `hexgrid.py`, `mapgen.py`, `rules.py` + `schemas.py` (data), `state.py` / `campaign.py` (turn engine as a generator that yields battle requests), `diplomacy.py`, `ai.py` (strategic planner, `BattleAI`, `auto_resolve`), `battle.py` (tactical grid), `ui_ledger.py` / `ui_battle.py`, `art.py`.

## Controls
**A** select / order - **B** back - **X** province actions - **Y** ledger menu - **L / R** previous / next army - **SELECT** cycle map overlay. Options: house (Ostrel, Karrow, Saline, Wick), map size, seed.

## Implemented and verified (`tests/modes/test_concord.py`)
* Seeded hex map generation with provinces, roads and resources; 13 building types, 20 techs, 25 unit kinds, 12 events, 4 houses - all JSON.
* **Logistics** - armies consume supply along road networks; sieges, attrition and foraging follow from it.
* **Diplomacy** - treaties, alliances, demands, oaths; the AI's acceptance scores are shown (transparent), and breaking an oath costs trust with everyone.
* **Tactical battles** - grid combat with flanking, charges, pike walls, line of sight, walls, morale and abilities; AI-vs-AI fights use the same rules through `auto_resolve`, and a balance test checks that no matchup is one-sided.
* **AI houses** play the same rules, use fog-of-war memory (they only know what they have seen), and adapt within bounds to the player's habits (adaptation levels are exported with the save and normalised).
* Victory by conquest, dominion, or concord; save/load reproduces the campaign exactly (state is not rounded on save, adaptation state is serialised).
* Echoes: `concord.treaty_signed` (opens Orrery envoys), `concord.tech_researched`, the facet on victory, and the `concord.tech.resonant_forging` tech gated behind the Choir Warden echo.

Frame cost: ~1.1 ms average on the campaign map (`tools/perf.py`).

## Partial / not implemented
* Map sizes small / medium / large exist; the large map was exercised less than medium.
* **Balance caveat:** playing as House Ostrel was tuned until bot campaigns finished, but the four houses are not yet balanced against each other for a human.
* No naval warfare, no espionage, no multiplayer.

## Data kinds
`concord.building`, `concord.event`, `concord.house`, `concord.tech`, `concord.unit`.
