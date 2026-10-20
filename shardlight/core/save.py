"""Versioned, checksummed, atomic save slots with rolling backups and corruption recovery.

Format: JSON envelope {"format": 1, "schema": N, "sha256": hex, "payload": {...}}.
Only JSON is ever parsed - never pickle. Schema migrations are pure functions
registered in MIGRATIONS and applied in order on load.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from . import log
from .paths import user_dir

LOG = log.get("save")
SCHEMA_VERSION = 3
FORMAT_VERSION = 1
SLOT_COUNT = 3
BACKUPS = 3


def new_profile(name: str = "Lampwright") -> dict[str, Any]:
    return {
        "name": name,
        "created": time.time(),
        "playtime": 0.0,
        "seed": int(time.time()) & 0xFFFFFFF,
        "flags": {},            # world flags set by echoes and modes (str -> bool|int|str)
        "counters": {},         # str -> number
        "unlocks": [],          # sorted list of unlock ids
        "lore": [],             # discovered lore ids
        "facets": [],           # repaired shard (mode) ids
        "achievements": [],
        "currency": {"glint": 0},
        "reputation": {},       # faction id -> int
        "echoes_fired": [],     # echo ids already resolved (one-shot echoes)
        "modes": {},            # mode id -> private JSON dict
        "tutorial": {},         # tutorial id -> seen
    }


# ---- migrations -------------------------------------------------------------------------------
def _m1_to_2(p: dict) -> dict:
    p.setdefault("lore", [])
    p.setdefault("achievements", [])
    return p


def _m2_to_3(p: dict) -> dict:
    p.setdefault("tutorial", {})
    p.setdefault("echoes_fired", [])
    rep = p.get("reputation")
    if isinstance(rep, list):  # v2 stored [[faction, value], ...]
        p["reputation"] = {k: v for k, v in rep}
    return p


MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: _m1_to_2, 2: _m2_to_3}


def migrate(payload: dict, from_schema: int) -> dict:
    p = copy.deepcopy(payload)
    v = from_schema
    while v < SCHEMA_VERSION:
        fn = MIGRATIONS.get(v)
        if fn is None:
            raise ValueError(f"no migration from schema {v}")
        p = fn(p)
        v += 1
    for k, val in new_profile().items():  # fill any field an older build never wrote
        p.setdefault(k, val)
    return p


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SaveError(Exception):
    pass


class SaveManager:
    def __init__(self, root: Path | None = None):
        self.root = (root or user_dir()) / "saves"
        self.root.mkdir(parents=True, exist_ok=True)
        self.recovered: list[str] = []   # human-readable recovery notes shown by the UI

    def path(self, slot: int) -> Path:
        if not 0 <= slot < SLOT_COUNT:
            raise SaveError(f"bad slot {slot}")
        return self.root / f"slot{slot}.json"

    def _backup_paths(self, slot: int) -> list[Path]:
        return [self.root / f"slot{slot}.bak{i}" for i in range(1, BACKUPS + 1)]

    def exists(self, slot: int) -> bool:
        return self.path(slot).exists() or any(b.exists() for b in self._backup_paths(slot))

    # -- writing ---------------------------------------------------------------------------
    def write(self, slot: int, payload: dict) -> None:
        envelope = {"format": FORMAT_VERSION, "schema": SCHEMA_VERSION,
                    "sha256": _digest(payload), "saved": time.time(), "payload": payload}
        text = json.dumps(envelope, indent=1)
        target = self.path(slot)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if target.exists():                      # rotate backups only once the new data is safely on disk
            baks = self._backup_paths(slot)
            for i in range(len(baks) - 1, 0, -1):
                if baks[i - 1].exists():
                    os.replace(baks[i - 1], baks[i])
            os.replace(target, baks[0])
        os.replace(tmp, target)

    # -- reading ---------------------------------------------------------------------------
    @staticmethod
    def _read_file(path: Path) -> dict:
        try:
            env = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SaveError(f"{path.name}: unreadable ({exc})") from exc
        if not isinstance(env, dict) or "payload" not in env or "schema" not in env:
            raise SaveError(f"{path.name}: not a save envelope")
        if not isinstance(env["payload"], dict) or not isinstance(env["schema"], int):
            raise SaveError(f"{path.name}: malformed envelope")
        if env.get("sha256") != _digest(env["payload"]):
            raise SaveError(f"{path.name}: checksum mismatch")
        if env["schema"] > SCHEMA_VERSION:
            raise SaveError(f"{path.name}: written by a newer version (schema {env['schema']})")
        try:
            return migrate(env["payload"], env["schema"])
        except ValueError as exc:
            raise SaveError(f"{path.name}: {exc}") from exc

    def read(self, slot: int) -> dict:
        """Load a slot, falling back through backups if the primary file is damaged."""
        candidates = [self.path(slot), *self._backup_paths(slot)]
        errors: list[str] = []
        for i, path in enumerate(candidates):
            if not path.exists():
                continue
            try:
                payload = self._read_file(path)
            except SaveError as exc:
                errors.append(str(exc))
                LOG.warning("save problem: %s", exc)
                if i == 0:
                    try:
                        os.replace(path, path.with_suffix(".corrupt"))
                    except OSError:
                        pass
                continue
            if i > 0:
                self.recovered.append(f"Slot {slot + 1} was damaged; restored from backup {i}.")
                LOG.warning("slot %d restored from %s", slot, path.name)
            return payload
        raise SaveError("; ".join(errors) or f"slot {slot} is empty")

    def delete(self, slot: int) -> None:
        for p in [self.path(slot), *self._backup_paths(slot)]:
            p.unlink(missing_ok=True)

    def summaries(self) -> list[dict | None]:
        out: list[dict | None] = []
        for s in range(SLOT_COUNT):
            if not self.exists(s):
                out.append(None)
                continue
            try:
                p = self.read(s)
                out.append({"name": p["name"], "playtime": p["playtime"], "facets": len(p["facets"]),
                            "glint": p["currency"].get("glint", 0)})
            except SaveError:
                out.append({"name": "(unrecoverable)", "playtime": 0, "facets": 0, "glint": 0, "broken": True})
        return out
