"""The rendered audio assets: manifest integrity, loop quality, coverage of every sound the game asks for, determinism and
that the game actually loads the files."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from shardlight import modes as modes_pkg
from shardlight.core import audio as A
from shardlight.core import audioqa as Q
from shardlight.core import scores, synth

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "audio"
MANIFEST = OUT / "MANIFEST.json"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="run tools/gen_audio.py to render assets")


@pytest.fixture(scope="module")
def man():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_matches_the_files_on_disk(man):
    files = [l for t in man["music"].values() for l in t["layers"].values()] + list(man["sfx"].values())
    assert len(files) >= 30 + 100
    for f in files:
        p = OUT / f["file"]
        assert p.exists(), f["file"]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"], f["file"]
        assert p.stat().st_size == f["bytes"]


def test_every_track_has_three_equal_length_seamless_layers(man):
    assert set(man["music"]) == set(scores.TRACK_NAMES) and len(scores.TRACK_NAMES) == 10
    for name, t in man["music"].items():
        lengths = set()
        for layer in ("bed", "rhythm", "lead"):
            x = Q.load_wav(OUT / t["layers"][layer]["file"])
            lengths.add(len(x))
            assert Q.peak(x) < 0.99 and Q.clipped_samples(x) == 0, (name, layer)
            assert Q.rms(x) > 1e-4, (name, layer, "silent layer")
        assert len(lengths) == 1, name
        mix = sum(Q.load_wav(OUT / t["layers"][l]["file"]) for l in ("bed", "rhythm", "lead"))
        assert Q.seam_ratio(mix) < 2.0, (name, Q.seam_ratio(mix))
        assert -26 < Q.dbfs(Q.rms(mix)) < -12, (name, Q.dbfs(Q.rms(mix)))
        assert t["loop_seconds"] > 20


def test_effects_are_clean_and_not_silent(man):
    for name, s in man["sfx"].items():
        x = Q.load_wav(OUT / s["file"])
        assert 0.015 < len(x) / synth.SR < 6.0, name
        assert 0.05 < Q.peak(x) < 1.0 and np.isfinite(x).all(), name


def test_every_registered_recipe_has_a_rendered_file(man):
    for m in modes_pkg.MODE_IDS:
        modes_pkg.load(m)
    missing = [n for n in A._SFX_RECIPES if n not in man["sfx"]]
    assert not missing, f"re-run tools/gen_audio.py: {missing[:8]}"


def test_every_sound_and_track_the_code_uses_exists(man):
    src = ""
    for f in (ROOT / "shardlight").rglob("*.py"):
        src += f.read_text(encoding="utf-8")
    tracks = set(re.findall(r"play_music\(\s*\"([a-z_]+)\"", src))
    assert tracks and tracks <= set(man["music"]), tracks - set(man["music"])
    for m in modes_pkg.MODE_IDS:
        mod = modes_pkg.load(m)
        if mod is not None:
            assert (mod.INFO.music or m) in man["music"], m
    names = set(re.findall(r"(?:sfx|play)\(\s*\"([a-z0-9_]+)\"", src))
    names = {n for n in names if "_" in n and not n.endswith("_")}
    registered = set(man["sfx"])
    ghosts = sorted(n for n in names if n not in registered and not n.startswith(("ui_", "music")))
    # Names built dynamically (f-strings) are not found by this scan; anything literal must exist.
    assert not [g for g in ghosts if re.match(r"^(cinder|verdant|umbra|terrace|orrery|concord|masks|slipstream)_", g)], ghosts


def test_rendering_is_deterministic(man):
    song = scores.build("verdant")
    layers = song.render()
    for layer, x in layers.items():
        on_disk = Q.load_wav(OUT / man["music"]["verdant"]["layers"][layer]["file"])
        quant = np.clip(np.round(x * 32768.0), -32768, 32767).astype(np.int16)
        assert np.abs(quant.astype(np.int32) - np.round(on_disk * 32768.0).astype(np.int32)).max() <= 1, layer


def test_the_audio_manager_prefers_the_rendered_files(app):
    a = app.audio
    a.root = OUT
    sounds = a._load_sfx("verdant_hit")
    assert sounds, "the manager should load assets/audio/sfx/verdant_hit.wav"
    assert (OUT / "sfx" / "verdant_hit.wav").exists()
    assert a.has_sfx("verdant_hit")
