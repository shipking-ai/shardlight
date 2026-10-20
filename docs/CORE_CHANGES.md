# Core changes made by mode work

Append-only, one line each: `- <id>: <file>: <what/why>`

- verdant: core/music.py (`room_ir`): `n = synth.n_samples(seconds)` instead of `int(seconds * SR)` - the impulse response was one sample shorter than the noise it multiplies, so every score failed to render (found by the first run of tools/gen_audio.py).
- verdant: modes/cinder/sfx.py, modes/terrace/sfx.py, modes/umbra/sfx.py: summed clips of different length now use `synth.mixdown` (13 recipes were raising at run time and being swallowed; found by gen_audio.py).
- verdant: tools/perf.py now starts real gameplay in each shard (previously it measured menus); tools/gen_audio.py, tools/contact_sheet.py and tools/gen_verdant_templates.py added.
- verdant: tests/test_core_content_mods.py: the sample-mod test registers every shard's content kinds (the sample mod now contains Verdant and Umbra entries).
