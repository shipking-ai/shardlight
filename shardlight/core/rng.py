"""Deterministic seeded randomness. Child streams are derived from labels so that
changing one generator never perturbs another (reproducible bug reports)."""
from __future__ import annotations

import hashlib
import random
from typing import Sequence, TypeVar

T = TypeVar("T")


def derive_seed(seed: int | str, *labels: object) -> int:
    h = hashlib.blake2b(digest_size=8)
    h.update(str(seed).encode())
    for lab in labels:
        h.update(b"\x1f")
        h.update(str(lab).encode())
    return int.from_bytes(h.digest(), "big")


class Rng(random.Random):
    """random.Random with a few game-oriented helpers and child derivation."""

    def __init__(self, seed: int | str = 0):
        self.root_seed = seed
        super().__init__(derive_seed(seed, "root"))

    def child(self, *labels: object) -> "Rng":
        return Rng(derive_seed(self.root_seed, *labels))

    def chance(self, p: float) -> bool:
        return self.random() < p

    def pick(self, seq: Sequence[T]) -> T:
        return seq[self.randrange(len(seq))]

    def weighted(self, items: Sequence[T], weights: Sequence[float]) -> T:
        return self.choices(items, weights=weights, k=1)[0]

    def shuffled(self, seq: Sequence[T]) -> list[T]:
        out = list(seq)
        self.shuffle(out)
        return out

    def jitter(self, v: float, amt: float) -> float:
        return v + self.uniform(-amt, amt)


def seed_to_words(seed: int) -> str:
    """Human friendly seed string for sharing runs."""
    a = ["ash", "bell", "cairn", "dusk", "ember", "fen", "gale", "hush", "iris", "juno", "kiln", "lark",
         "moss", "nox", "opal", "pyre", "quill", "rime", "sable", "tarn", "umber", "vale", "wren", "yarrow"]
    return f"{a[seed % 24]}-{a[(seed // 24) % 24]}-{(seed // 576) % 1000:03d}"
