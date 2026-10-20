# Modding Shardlight

Mods are **data only**. The game never imports or executes code from a mod folder, so a mod cannot do anything beyond adding or replacing validated JSON content.

## Layout

```
mods/
  my_mod/
    mod.json
    data/
      <kind>/anything.json        e.g. data/cinder.weapon/frost_axe.json, data/echo/my_echo.json
```

Kinds are defined by the game (and its modes): `echo`, `lore`, plus per-mode kinds such as `cinder.weapon`, `cinder.boon`, `cinder.enemy`, `cinder.modifier`, `verdant.item`, `verdant.enemy`, `verdant.npc`, `verdant.quest`, `verdant.shop`, `verdant.recipe`, `verdant.loot`, `verdant.template`, `slipstream.vehicle`, `masks.character`, `concord.tech`, `terrace.recipe`, ... (see each `docs/modes/<id>.md` for the exact schema). Each file is either a list of entries or `{"entries": [...]}`; every entry needs a unique lowercase `id` (`a-z 0-9 _ . -`).

## mod.json

```json
{
  "id": "my_mod",                 // lowercase, 2-32 chars, starts with a letter
  "name": "My Mod",
  "version": "1.0.0",             // semantic version
  "api": 1,                       // this build supports api 1
  "author": "you",
  "description": "What it does",
  "depends": [{"id": "other_mod", "version": ">=1.0.0"}],   // optional
  "conflicts": ["incompatible_mod"],                        // optional
  "overrides": ["cinder.weapon/ember_blade"]               // optional: base/other-mod entries you may replace
}
```

(Comments are shown for explanation; real JSON has none.)

## Load order and conflicts

* Mods load after the base game, in dependency order, ties broken alphabetically by id (deterministic).
* A mod whose dependency is missing/too old, whose `api` differs, or that conflicts with a loaded mod is skipped as a whole and reported.
* An entry whose id already exists is **rejected** unless the mod lists `"<kind>/<id>"` in `overrides`. Replacing something silently never happens.
* Invalid entries (schema violations, bad ids, unknown fields) are skipped individually with a message; valid entries of the same mod still load.
* Everything is reported in the hub **Archive -> Mods** tab and in `userdata/shardlight.log`.

## Writing an echo (cross-mode consequence)

```json
{"entries": [{
  "id": "my_mod_signal",
  "title": "A Friendly Answer",
  "on": "orrery.signal_decoded", "where": {"signal": "choir"},
  "require": {"flags": [], "unlocks": [], "facets": ["cinder"], "counters": {"treaties": 1}},
  "once": true,
  "effects": [{"lore": "my_lore"}, {"unlock": "my.unlock.id"}, {"grant": 5},
              {"toast": "Hello from my mod"}, {"emit": "my_mod.followup", "payload": {"n": 1}}]
}]}
```

Events emitted by the base game are listed in `docs/MODE_CONTRACT.md` (section 4). Other effects: `set_flag`, `counter`, `rep`, `repair`.

## Sample

`examples/sample_pack` is a complete working example: an echo and lore entry, a Verdant traveller with a kill quest, two items and a hearth recipe, and an Umbra note. It is shipped disabled so the base game stays untouched; copy the folder into `mods/` (or set `SHARDLIGHT_MODS`) to enable it. It is loaded by the tests against every registered content kind, so it stays valid. Copy it, rename the id, and edit.

## Security model and limits

No code execution, no file access outside `data/`, size limit 2 MB per JSON file, schema-validated values, bounded echo cascades (64 steps). Mods cannot weaken the save format. Mod content is namespaced by id in reports; removing a mod removes its content, but unlocks/flags it granted remain in saves (harmlessly ignored when absent).
