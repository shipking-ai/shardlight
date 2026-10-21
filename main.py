"""Shared entry point for the browser build (pygbag) and desktop bundles (PyInstaller).

Exactly equivalent to ``python -m shardlight``; every CLI argument is forwarded.
The async ``main`` is re-exported here because pygbag boots the archive by awaiting
``main`` at this path. Run it directly on desktop (after rendering the audio once)::

    python main.py

The PEP 723 block below is what the browser build reads to learn which packages it
must install before the game starts: pygbag only scans this file, so without it
numpy and pygame would be missing at import time.
"""
from __future__ import annotations

# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "pygame"]
# ///

import asyncio
import sys

from shardlight.__main__ import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
