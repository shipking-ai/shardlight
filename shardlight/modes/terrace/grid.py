"""Chunked tile storage and connectivity helpers.

Justification of the layout: world generation, lighting and fluids are all vectorised numpy passes over large
rectangles, so the authoritative storage is ONE contiguous ``(H, W)`` array per layer.  A *chunk* is a 32x32 view
into that array plus bookkeeping (render dirty flag, edited flag).  This gives chunk-granular rendering caches
and chunk-granular persistence (only edited chunks are saved) without paying a gather/scatter cost every time a
vectorised pass crosses a chunk border.
"""
from __future__ import annotations

import numpy as np

from .constants import CHUNK


class ChunkedGrid:
    """Two uint8 layers (blocks, liquid) addressed by tile or by 32x32 chunk."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.cw = -(-w // CHUNK)
        self.ch = -(-h // CHUNK)
        self.blocks = np.zeros((h, w), dtype=np.uint8)
        self.liq = np.zeros((h, w), dtype=np.uint8)
        self.render_dirty: set[tuple[int, int]] = {(cx, cy) for cx in range(self.cw) for cy in range(self.ch)}
        self.edited: set[tuple[int, int]] = set()       # chunks touched since generation
        self.version = 0                                # bumps on any block change (light/minimap caches)

    # ------------------------------------------------------------------ chunk views
    def chunk_slice(self, cx: int, cy: int) -> tuple[slice, slice]:
        return (slice(cy * CHUNK, min(self.h, (cy + 1) * CHUNK)), slice(cx * CHUNK, min(self.w, (cx + 1) * CHUNK)))

    def chunk_blocks(self, cx: int, cy: int) -> np.ndarray:
        return self.blocks[self.chunk_slice(cx, cy)]

    def chunk_liq(self, cx: int, cy: int) -> np.ndarray:
        return self.liq[self.chunk_slice(cx, cy)]

    def pack_chunk(self, cx: int, cy: int) -> bytes:
        """Raw bytes of one chunk (blocks then liquid, row-major)."""
        return self.chunk_blocks(cx, cy).tobytes() + self.chunk_liq(cx, cy).tobytes()

    def unpack_chunk(self, cx: int, cy: int, raw: bytes) -> None:
        sl = self.chunk_slice(cx, cy)
        shape = self.blocks[sl].shape
        n = shape[0] * shape[1]
        if len(raw) != 2 * n:
            raise ValueError("chunk payload has the wrong size")
        self.blocks[sl] = np.frombuffer(raw[:n], dtype=np.uint8).reshape(shape)
        self.liq[sl] = np.frombuffer(raw[n:], dtype=np.uint8).reshape(shape)
        self.render_dirty.add((cx, cy))
        self.edited.add((cx, cy))
        self.version += 1

    # ------------------------------------------------------------------ marking
    def mark(self, x: int, y: int, neighbours: bool = True) -> None:
        """Record that tile (x, y) changed: render + edited flags, plus border neighbours (autotile bevels)."""
        cx, cy = x // CHUNK, y // CHUNK
        self.render_dirty.add((cx, cy))
        self.edited.add((cx, cy))
        if neighbours:
            lx, ly = x % CHUNK, y % CHUNK
            for dx in ((-1,) if lx == 0 else ()) + ((1,) if lx == CHUNK - 1 else ()):
                if 0 <= cx + dx < self.cw:
                    self.render_dirty.add((cx + dx, cy))
            for dy in ((-1,) if ly == 0 else ()) + ((1,) if ly == CHUNK - 1 else ()):
                if 0 <= cy + dy < self.ch:
                    self.render_dirty.add((cx, cy + dy))
            if lx in (0, CHUNK - 1) and ly in (0, CHUNK - 1):
                ddx = -1 if lx == 0 else 1
                ddy = -1 if ly == 0 else 1
                if 0 <= cx + ddx < self.cw and 0 <= cy + ddy < self.ch:
                    self.render_dirty.add((cx + ddx, cy + ddy))
        self.version += 1


# ---------------------------------------------------------------------------------------- connectivity
def label4(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """4-connected component labelling of a boolean mask using run-length union-find.

    Returns ``(labels, sizes)``: ``labels`` is int32 with 0 for blocked cells and 1..N for components;
    ``sizes[k]`` is the number of cells of component k (``sizes[0]`` counts blocked cells).
    """
    h, w = mask.shape
    parent: list[int] = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    rows: list[list[tuple[int, int, int]]] = []
    prev: list[tuple[int, int, int]] = []
    for y in range(h):
        d = np.diff(mask[y].astype(np.int8), prepend=0, append=0)
        starts = np.flatnonzero(d == 1).tolist()
        ends = np.flatnonzero(d == -1).tolist()
        runs: list[tuple[int, int, int]] = []
        for s, e in zip(starts, ends):
            rid = len(parent)
            parent.append(rid)
            runs.append((s, e, rid))
        i = j = 0
        while i < len(prev) and j < len(runs):
            ps, pe, pid = prev[i]
            cs, ce, cid = runs[j]
            if ps < ce and cs < pe:
                a, b = find(pid), find(cid)
                if a != b:
                    parent[a] = b
            if pe < ce:
                i += 1
            else:
                j += 1
        rows.append(runs)
        prev = runs
    remap: dict[int, int] = {}
    labels = np.zeros((h, w), dtype=np.int32)
    for y, runs in enumerate(rows):
        for s, e, rid in runs:
            root = find(rid)
            lab = remap.get(root)
            if lab is None:
                lab = len(remap) + 1
                remap[root] = lab
            labels[y, s:e] = lab
    sizes = np.bincount(labels.ravel(), minlength=len(remap) + 1)
    return labels, sizes


def dilate4(mask: np.ndarray) -> np.ndarray:
    """4-neighbourhood dilation (cells adjacent to or inside ``mask``)."""
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out
