"""Render SHARDLIGHT's procedural audio to ``assets/audio`` and write the manifest and QA report.

    python tools/gen_audio.py              # render everything (music + sfx), write MANIFEST.json and docs/AUDIO_REPORT.md
    python tools/gen_audio.py --music-only
    python tools/gen_audio.py --sfx-only
    python tools/gen_audio.py --tracks verdant,umbra
    python tools/gen_audio.py --check      # verify files against MANIFEST.json (hashes, lengths) without rendering

Rendering is deterministic: the same code produces byte-identical files (the manifest records SHA-256 digests, and the
tests re-render a track to prove it).  The game plays the files when present and falls back to the same recipes when
they are not, so deleting ``assets/audio`` never breaks anything - it only costs start-up time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shardlight import modes as modes_pkg  # noqa: E402
from shardlight.core import audio as A  # noqa: E402
from shardlight.core import audioqa as Q  # noqa: E402
from shardlight.core import scores  # noqa: E402
from shardlight.core import sfxlib  # noqa: E402,F401
from shardlight.core import synth  # noqa: E402

OUT = ROOT / "assets" / "audio"
MANIFEST = OUT / "MANIFEST.json"
REPORT = ROOT / "docs" / "AUDIO_REPORT.md"
# TODO(#2): the rendered audio has been measured but never listened to; do a listening pass and fix the worst tracks/effects.
VERSION = 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_music(names: list[str]) -> dict:
    out = {}
    for name in names:
        t0 = time.time()
        song = scores.build(name)
        layers = song.render()
        folder = OUT / "music" / name
        folder.mkdir(parents=True, exist_ok=True)
        spec = scores.spec(name, song)
        entry = {"key": spec.key, "bpm": spec.bpm, "meter": spec.meter, "bars": spec.bars, "seed": spec.seed, "notes": spec.notes,
                 "loop_seconds": spec.extras["loop_seconds"], "layers": {}}
        for layer, x in layers.items():
            p = folder / f"{layer}.wav"
            synth.write_wav(p, x)
            back = Q.load_wav(p)
            entry["layers"][layer] = {"file": str(p.relative_to(OUT)).replace("\\", "/"), "sha256": sha256(p), "bytes": p.stat().st_size,
                                      "samples": int(len(back)), "peak_dbfs": round(Q.dbfs(Q.peak(back)), 2),
                                      "rms_dbfs": round(Q.dbfs(Q.rms(back)), 2), "clipped": Q.clipped_samples(back),
                                      "seam_ratio": round(Q.seam_ratio(back), 3)}
        mix = sum(Q.load_wav(folder / f"{l}.wav") for l in layers)
        entry["mix"] = {"peak_dbfs": round(Q.dbfs(Q.peak(mix)), 2), "rms_dbfs": round(Q.dbfs(Q.rms(mix)), 2),
                        "centroid_hz": round(Q.spectral_centroid(mix[: 1 << 18]), 1), "seam_ratio": round(Q.seam_ratio(mix), 3)}
        entry["render_seconds"] = round(time.time() - t0, 1)
        out[name] = entry
        print(f"  music {name:<11} {entry['loop_seconds']:>6.1f}s loop  peak {entry['mix']['peak_dbfs']:>6.1f} dBFS  "
              f"rms {entry['mix']['rms_dbfs']:>6.1f}  seam {entry['mix']['seam_ratio']:.2f}  ({entry['render_seconds']}s)")
    return out


def load_all_modes() -> None:
    for m in modes_pkg.MODE_IDS:
        modes_pkg.load(m)


def render_sfx() -> dict:
    load_all_modes()
    folder = OUT / "sfx"
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    bad = []
    for name, recipe in sorted(A._SFX_RECIPES.items()):
        try:
            x = np.asarray(recipe(), dtype=np.float32)
        except Exception as exc:        # a broken recipe is reported, never silently skipped
            bad.append((name, repr(exc)))
            continue
        if not np.isfinite(x).all() or len(x) < 64:
            bad.append((name, "empty or non-finite"))
            continue
        x = np.clip(x, -1.0, 1.0)
        p = folder / f"{name}.wav"
        synth.write_wav(p, x)
        back = Q.load_wav(p)
        out[name] = {"file": str(p.relative_to(OUT)).replace("\\", "/"), "sha256": sha256(p), "bytes": p.stat().st_size,
                     "seconds": round(len(back) / synth.SR, 3), "peak_dbfs": round(Q.dbfs(Q.peak(back)), 2),
                     "rms_dbfs": round(Q.dbfs(Q.rms(back)), 2), "clipped": Q.clipped_samples(back)}
    print(f"  sfx   {len(out)} files, {sum(v['bytes'] for v in out.values()) / 1024:.0f} KiB")
    for n, why in bad:
        print(f"  !! sfx {n} failed: {why}")
    if bad:
        raise SystemExit(f"{len(bad)} sound recipes failed")
    return out


def write_manifest(music: dict, sfx: dict) -> None:
    prev = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    man = {"version": VERSION, "sample_rate": synth.SR, "format": "16-bit mono PCM WAV",
           "generator": "tools/gen_audio.py (procedural: shardlight.core.music / scores / synth / sfxlib + per-mode sfx.py)",
           "music": music or prev.get("music", {}), "sfx": sfx or prev.get("sfx", {})}
    man["totals"] = {"music_tracks": len(man["music"]), "music_files": sum(len(t["layers"]) for t in man["music"].values()),
                     "sfx_files": len(man["sfx"]),
                     "bytes": sum(l["bytes"] for t in man["music"].values() for l in t["layers"].values()) + sum(s["bytes"] for s in man["sfx"].values())}
    MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True), encoding="utf-8")
    write_report(man)


def write_report(man: dict) -> None:
    L = ["# Audio report (generated)", "",
         "Generated by `tools/gen_audio.py` from procedural code - no samples, recordings or third-party audio. Regenerate with that tool; "
         "`MANIFEST.json` carries the SHA-256 of every file and tests verify them.", "",
         f"Format: {man['format']} at {man['sample_rate']} Hz. Total {man['totals']['bytes'] / 1048576:.1f} MiB in "
         f"{man['totals']['music_files']} music layers and {man['totals']['sfx_files']} effects.", "",
         "## Music", "", "| Track | Key | Tempo | Meter | Bars | Loop | Mix peak | Mix RMS | Seam | Intent |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n, t in sorted(man["music"].items()):
        m = t["mix"]
        L.append(f"| {n} | {t['key']} | {t['bpm']:.1f} | {t['meter']} | {t['bars']} | {t['loop_seconds']:.1f}s | {m['peak_dbfs']} dBFS | "
                 f"{m['rms_dbfs']} dBFS | {m['seam_ratio']} | {t['notes']} |")
    L += ["", "Layers per track: `bed` (always on), `rhythm` (pulse and percussion), `lead` (melody / tension); the game cross-fades them with "
          "`AudioManager.set_intensity`. All three layers of a track are exactly the same length and loop sample-perfectly.", "",
          "## Effects", "", "| Name | Length | Peak | RMS |", "|---|---|---|---|"]
    for n, s in sorted(man["sfx"].items()):
        L.append(f"| {n} | {s['seconds']:.2f}s | {s['peak_dbfs']} dBFS | {s['rms_dbfs']} dBFS |")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")


def check() -> int:
    if not MANIFEST.exists():
        print("no manifest")
        return 1
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = 0
    files = [l for t in man["music"].values() for l in t["layers"].values()] + list(man["sfx"].values())
    for f in files:
        p = OUT / f["file"]
        if not p.exists() or sha256(p) != f["sha256"]:
            print("MISMATCH", f["file"])
            bad += 1
    print(f"checked {len(files)} files, {bad} problems")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--music-only", action="store_true")
    ap.add_argument("--sfx-only", action="store_true")
    ap.add_argument("--tracks", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check()
    OUT.mkdir(parents=True, exist_ok=True)
    music: dict = {}
    sfx: dict = {}
    prev = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"music": {}, "sfx": {}}
    if not a.sfx_only:
        names = [n for n in a.tracks.split(",") if n] or list(scores.TRACK_NAMES)
        music = dict(prev.get("music", {}))
        music.update(render_music(names))
    if not a.music_only:
        sfx = render_sfx()
    write_manifest(music, sfx)
    print("manifest written:", MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
