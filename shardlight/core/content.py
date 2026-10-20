"""Data-driven content database with declarative schema validation.

All game content (weapons, quests, tracks, characters, echoes...) is JSON.  Base game data lives in
``data/<kind>/*.json``; mods add or override entries of the same kinds.  Modes register the kinds
they understand together with a schema; entries failing validation are rejected with a readable
error instead of crashing the game.

File format (either form is accepted)::

    {"entries": [{"id": "ember_blade", ...}, ...]}
    [{"id": "ember_blade", ...}, ...]

Schema format: ``{field: {"type": "str|int|float|bool|list|dict|vec2|color|any", "required": bool,
"min": n, "max": n, "choices": [...], "items": <spec>, "fields": <schema>, "ref": "<kind>"}}``
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import log

LOG = log.get("content")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")

Schema = dict[str, dict[str, Any]]


class ContentError(Exception):
    pass


def validate_value(value: Any, spec: dict, path: str) -> list[str]:
    errs: list[str] = []
    t = spec.get("type", "any")
    if t == "any":
        return errs
    if t == "str":
        if not isinstance(value, str):
            return [f"{path}: expected string"]
        if len(value) > spec.get("max_len", 2000):
            errs.append(f"{path}: string too long")
    elif t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path}: expected integer"]
    elif t == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path}: expected number"]
    elif t == "bool":
        if not isinstance(value, bool):
            return [f"{path}: expected true/false"]
    elif t == "vec2":
        if not (isinstance(value, list) and len(value) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
            return [f"{path}: expected [x, y]"]
    elif t == "color":
        if not (isinstance(value, list) and len(value) == 3 and all(
                isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255 for v in value)):
            return [f"{path}: expected [r, g, b] with 0-255"]
    elif t == "list":
        if not isinstance(value, list):
            return [f"{path}: expected list"]
        if len(value) > spec.get("max_items", 5000):
            errs.append(f"{path}: too many items")
        item = spec.get("items")
        if item:
            for i, v in enumerate(value):
                errs += validate_value(v, item, f"{path}[{i}]")
    elif t == "dict":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        if "fields" in spec:
            errs += validate_fields(value, spec["fields"], path)
        elif "values" in spec:
            for k, v in value.items():
                errs += validate_value(v, spec["values"], f"{path}.{k}")
    else:
        return [f"{path}: unknown schema type {t!r}"]
    if t in ("int", "float"):
        if "min" in spec and value < spec["min"]:
            errs.append(f"{path}: {value} below minimum {spec['min']}")
        if "max" in spec and value > spec["max"]:
            errs.append(f"{path}: {value} above maximum {spec['max']}")
    if "choices" in spec and value not in spec["choices"]:
        errs.append(f"{path}: {value!r} not one of {spec['choices']}")
    return errs


def validate_fields(obj: dict, schema: Schema, path: str = "") -> list[str]:
    errs: list[str] = []
    for key, spec in schema.items():
        if key not in obj:
            if spec.get("required"):
                errs.append(f"{path}.{key}: required field missing" if path else f"{key}: required field missing")
            continue
        errs += validate_value(obj[key], spec, f"{path}.{key}" if path else key)
    for key in obj:
        if key not in schema and key != "id" and not key.startswith("_"):
            errs.append(f"{path}.{key}: unknown field" if path else f"{key}: unknown field")
    return errs


@dataclass
class Kind:
    name: str
    schema: Schema
    strict: bool = True


@dataclass
class Entry:
    data: dict
    source: str          # "base" or mod id


@dataclass
class ContentDB:
    kinds: dict[str, Kind] = field(default_factory=dict)
    entries: dict[str, dict[str, Entry]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def register_kind(self, name: str, schema: Schema, strict: bool = True) -> None:
        if name in self.kinds:
            return
        self.kinds[name] = Kind(name, schema, strict)
        self.entries.setdefault(name, {})

    # ------------------------------------------------------------------ loading
    def add_entry(self, kind: str, raw: Any, source: str, allow_override: bool = False,
                  origin: str = "") -> bool:
        where = f"[{source}] {origin or kind}"
        k = self.kinds.get(kind)
        if k is None:
            self.problems.append(f"{where}: unknown content kind {kind!r}")
            return False
        if not isinstance(raw, dict):
            self.problems.append(f"{where}: entry is not an object")
            return False
        eid = raw.get("id")
        if not isinstance(eid, str) or not ID_RE.match(eid):
            self.problems.append(f"{where}: bad or missing id {eid!r} (lowercase letters, digits, _ . -)")
            return False
        errs = validate_fields(raw, k.schema)
        if errs:
            for e in errs[:6]:
                self.problems.append(f"{where}:{eid}: {e}")
            return False
        existing = self.entries[kind].get(eid)
        if existing is not None:
            if existing.source == source:
                self.problems.append(f"{where}:{eid}: duplicate id within same source")
                return False
            if not allow_override:
                self.problems.append(
                    f"{where}:{eid}: conflicts with entry from [{existing.source}] (set \"override\": true in the "
                    f"mod manifest's 'overrides' list to replace it)")
                return False
            LOG.info("%s overrides %s/%s from %s", source, kind, eid, existing.source)
        self.entries[kind][eid] = Entry(raw, source)
        return True

    def load_file(self, path: Path, kind: str, source: str, overrides: Iterable[str] = ()) -> int:
        try:
            if path.stat().st_size > 2_000_000:
                raise ContentError("file larger than 2 MB")
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ContentError) as exc:
            self.problems.append(f"[{source}] {path.name}: cannot read ({exc})")
            return 0
        items = doc.get("entries") if isinstance(doc, dict) else doc
        if not isinstance(items, list):
            self.problems.append(f"[{source}] {path.name}: expected a list or {{\"entries\": [...]}}")
            return 0
        ov = set(overrides)
        n = 0
        for raw in items:
            allow = isinstance(raw, dict) and f"{kind}/{raw.get('id')}" in ov
            n += self.add_entry(kind, raw, source, allow_override=allow, origin=path.name)
        return n

    def load_dir(self, root: Path, source: str = "base", overrides: Iterable[str] = ()) -> int:
        """Load ``root/<kind>/*.json`` and ``root/<kind>.json`` for every registered kind."""
        total = 0
        if not root.exists():
            return 0
        for kind in list(self.kinds):
            sub = root / kind
            files = sorted(sub.glob("*.json")) if sub.is_dir() else []
            single = root / f"{kind}.json"
            if single.exists():
                files.append(single)
            for f in files:
                total += self.load_file(f, kind, source, overrides)
        return total

    # ------------------------------------------------------------------ queries
    def get(self, kind: str, eid: str) -> dict | None:
        e = self.entries.get(kind, {}).get(eid)
        return e.data if e else None

    def require(self, kind: str, eid: str) -> dict:
        d = self.get(kind, eid)
        if d is None:
            raise ContentError(f"missing content {kind}/{eid}")
        return d

    def all(self, kind: str) -> list[dict]:
        return [e.data for e in self.entries.get(kind, {}).values()]

    def ids(self, kind: str) -> list[str]:
        return list(self.entries.get(kind, {}))

    def source_of(self, kind: str, eid: str) -> str | None:
        e = self.entries.get(kind, {}).get(eid)
        return e.source if e else None

    def check_refs(self) -> list[str]:
        """Report schema ``ref`` fields pointing at missing entries."""
        issues: list[str] = []

        def walk(obj: Any, spec: dict, where: str) -> None:
            ref = spec.get("ref")
            if ref and isinstance(obj, str) and obj not in self.entries.get(ref, {}):
                issues.append(f"{where}: references missing {ref}/{obj}")
            if spec.get("type") == "list" and isinstance(obj, list) and spec.get("items"):
                for i, v in enumerate(obj):
                    walk(v, spec["items"], f"{where}[{i}]")
            if spec.get("type") == "dict" and isinstance(obj, dict) and "fields" in spec:
                for k, s in spec["fields"].items():
                    if k in obj:
                        walk(obj[k], s, f"{where}.{k}")

        for kind, k in self.kinds.items():
            for eid, e in self.entries[kind].items():
                for fname, spec in k.schema.items():
                    if fname in e.data:
                        walk(e.data[fname], spec, f"{kind}/{eid}.{fname}")
        return issues
