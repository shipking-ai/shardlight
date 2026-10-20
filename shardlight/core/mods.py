"""Mod loader.  Mods are *data only*: a folder containing ``mod.json`` plus ``data/<kind>/*.json``.

No third-party code is ever imported or executed.  ``mod.json``::

    {"id": "my_mod", "name": "...", "version": "1.0.0", "api": 1, "author": "...",
     "description": "...", "depends": [{"id": "other_mod", "version": ">=1.0"}],
     "overrides": ["cinder.weapon/ember_blade"],       # base/other-mod entries this mod may replace
     "conflicts": ["incompatible_mod"]}

Loading order is topological by dependency, then alphabetical by id (deterministic).  A mod that
fails validation is skipped as a whole and the problems are reported; the game always starts.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import log
from .content import ContentDB

LOG = log.get("mods")
API_VERSION = 1
MOD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def _satisfies(version: str, spec: str) -> bool:
    m = re.match(r"^(>=|<=|==|>|<)?\s*(\d+(?:\.\d+){0,2})$", spec.strip())
    if not m:
        return False
    op, want = m.group(1) or ">=", _ver(m.group(2))
    have = _ver(version)
    return {">=": have >= want, "<=": have <= want, "==": have == want, ">": have > want, "<": have < want}[op]


@dataclass
class Mod:
    id: str
    name: str
    version: str
    path: Path
    depends: list[dict] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    description: str = ""
    author: str = ""
    enabled: bool = True
    errors: list[str] = field(default_factory=list)


class ModManager:
    def __init__(self, mods_dir: Path):
        self.dir = mods_dir
        self.mods: dict[str, Mod] = {}
        self.report: list[str] = []
        self.loaded: list[str] = []

    # -- discovery ------------------------------------------------------------------------
    # TODO(#16): mods/sample_pack is loaded by default and alters the base game; make examples opt-in.
    def discover(self) -> None:
        self.mods.clear()
        self.report.clear()
        if not self.dir.is_dir():
            return
        for folder in sorted(p for p in self.dir.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
            manifest = folder / "mod.json"
            if not manifest.exists():
                continue
            mod = self._read_manifest(folder, manifest)
            if mod is None:
                continue
            if mod.id in self.mods:
                self.report.append(f"{folder.name}: duplicate mod id {mod.id!r}; ignored")
                continue
            self.mods[mod.id] = mod

    def _read_manifest(self, folder: Path, manifest: Path) -> Mod | None:
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.report.append(f"{folder.name}/mod.json: unreadable ({exc})")
            return None
        errs: list[str] = []
        if not isinstance(doc, dict):
            self.report.append(f"{folder.name}/mod.json: must be an object")
            return None
        mid = doc.get("id")
        if not isinstance(mid, str) or not MOD_ID_RE.match(mid):
            errs.append("id must be lowercase letters/digits/underscore, 2-32 chars, starting with a letter")
        if not isinstance(doc.get("name"), str) or not doc.get("name"):
            errs.append("name is required")
        ver = doc.get("version")
        if not isinstance(ver, str) or not SEMVER_RE.match(ver):
            errs.append("version must look like 1.2.3")
        if doc.get("api") != API_VERSION:
            errs.append(f"unsupported api {doc.get('api')!r}; this build supports api {API_VERSION}")
        for key in ("depends", "overrides", "conflicts"):
            if key in doc and not isinstance(doc[key], list):
                errs.append(f"{key} must be a list")
        if errs:
            self.report.append(f"{folder.name}/mod.json: " + "; ".join(errs))
            return None
        deps = [d if isinstance(d, dict) else {"id": d} for d in doc.get("depends", [])]
        return Mod(id=mid, name=doc["name"], version=ver, path=folder, depends=deps,
                   overrides=[str(x) for x in doc.get("overrides", [])],
                   conflicts=[str(x) for x in doc.get("conflicts", [])],
                   description=str(doc.get("description", "")), author=str(doc.get("author", "")))

    # -- resolution -----------------------------------------------------------------------
    def resolve(self, disabled: set[str] | None = None) -> list[Mod]:
        """Return mods in load order, dropping any with missing/incompatible dependencies."""
        disabled = disabled or set()
        active = {m.id: m for m in self.mods.values() if m.id not in disabled}
        changed = True
        while changed:
            changed = False
            for m in list(active.values()):
                for d in m.depends:
                    dep = active.get(d.get("id"))
                    if dep is None:
                        self.report.append(f"{m.id}: missing dependency {d.get('id')!r}; mod skipped")
                    elif "version" in d and not _satisfies(dep.version, d["version"]):
                        self.report.append(
                            f"{m.id}: needs {dep.id} {d['version']} but {dep.version} is installed; mod skipped")
                    else:
                        continue
                    del active[m.id]
                    changed = True
                    break
                else:
                    for c in m.conflicts:
                        if c in active:
                            self.report.append(f"{m.id} conflicts with {c}; {m.id} skipped")
                            del active[m.id]
                            changed = True
                            break
        order: list[Mod] = []
        state: dict[str, int] = {}

        def visit(mid: str) -> bool:
            if state.get(mid) == 2:
                return True
            if state.get(mid) == 1:
                return False
            state[mid] = 1
            for d in active[mid].depends:
                if d["id"] in active and not visit(d["id"]):
                    return False
            state[mid] = 2
            order.append(active[mid])
            return True

        for mid in sorted(active):
            if not visit(mid):
                self.report.append(f"dependency cycle involving {mid}; skipped")
                state[mid] = 2
        return order

    # -- application ----------------------------------------------------------------------
    def apply(self, content: ContentDB, disabled: set[str] | None = None) -> list[str]:
        self.loaded = []
        for mod in self.resolve(disabled):
            before = len(content.problems)
            data_dir = mod.path / "data"
            count = content.load_dir(data_dir, source=mod.id, overrides=mod.overrides)
            new_problems = content.problems[before:]
            if new_problems:
                self.report.append(f"{mod.id}: {len(new_problems)} problem(s) while loading content")
            self.loaded.append(mod.id)
            LOG.info("mod %s v%s loaded (%d entries)", mod.id, mod.version, count)
        return self.loaded
