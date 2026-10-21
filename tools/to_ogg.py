"""Convert the rendered WAV audio to OGG/Vorbis.

OGG is roughly a tenth the size of the WAVs, which matters a lot for the browser
build (the whole wasm bundle is downloaded in full) and plays fine everywhere.
The WAV originals are removed once they are converted.

Needs ffmpeg on PATH (the CI web build installs it; on Windows grab it from
https://ffmpeg.org/download.html).

    python tools/to_ogg.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "assets" / "audio"


def main() -> int:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg is not on PATH; install it to convert the audio")
        return 1
    if not AUDIO.is_dir():
        print("no assets/audio folder; nothing to convert")
        return 0
    wavs = sorted(AUDIO.rglob("*.wav"))
    if not wavs:
        print("no wav files found; nothing to convert")
        return 0
    for wav in wavs:
        out = wav.with_suffix(".ogg")
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libvorbis", "-q:a", "3", str(out)],
            check=True,
        )
        wav.unlink()
    total = sum(p.stat().st_size for p in AUDIO.rglob("*.ogg"))
    print(f"converted {len(wavs)} wav files to ogg ({total / 1_000_000:.1f} MB total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
