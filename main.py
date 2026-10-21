# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
# ///
"""Shared entry point for the browser build (pygbag) and desktop bundles (PyInstaller).

Exactly equivalent to ``python -m shardlight``; every CLI argument is forwarded.
The async ``main`` is re-exported here because pygbag boots the archive by awaiting
``main`` at this path. Run it directly on desktop (after rendering the audio once)::

    python main.py

The ``import pygame`` below is not decoration: the browser build installs its
packages by scanning this file for imports, so pygame has to appear here or the
wasm runtime has no pygame at all.
"""
from __future__ import annotations

import asyncio
import sys

import pygame  # noqa: F401  (imported so the browser build installs pygame)

from shardlight.__main__ import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
