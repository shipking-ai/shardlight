"""Load and validate data/prism.tour/tour.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...core import log
from ...core.paths import DATA_DIR
import shardlight.modes as modes_pkg

LOG = log.get("prism.tour")
LEG_KINDS: set[str] = set()          # populated by legs module at import
LEG_CLASSES: dict[str, type] = {}


def _register() -> None:
    global LEG_KINDS, LEG_CLASSES
    from . import legs as _legs
    # collect every Leg subclass defined in legs module
    for name in dir(_legs):
        obj = getattr(_legs, name)
        if isinstance(obj, type) and issubclass(obj, _legs.Leg) and obj is not _legs.Leg:
            LEG_CLASSES[name] = obj
    LEG_KINDS = set(LEG_CLASSES)


_register()

REQUIRED_LEG = ("id", "shard", "kind", "seed", "config")
VALID_SHARDS = set(modes_pkg.MODE_IDS)


def validate(tour: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(tour, dict):
        return ["tour: not an object"]
    if not isinstance(tour.get("id"), str):
        problems.append("tour.id missing")
    if not isinstance(tour.get("title"), str):
        problems.append("tour.title missing")
    legs = tour.get("legs")
    if not isinstance(legs, list) or not legs:
        problems.append("tour.legs must be a non-empty list")
        return problems
    seen: set[str] = set()
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            problems.append(f"leg[{i}]: not an object")
            continue
        for k in REQUIRED_LEG:
            if k not in leg:
                problems.append(f"leg[{i}]: missing {k}")
        if leg.get("id") in seen:
            problems.append(f"leg[{i}]: duplicate id {leg.get('id')}")
        seen.add(leg.get("id"))
        if leg.get("shard") not in VALID_SHARDS:
            problems.append(f"leg[{i}]: unknown shard {leg.get('shard')!r}")
        if leg.get("kind") not in LEG_KINDS:
            problems.append(f"leg[{i}]: unknown kind {leg.get('kind')!r}")
        if not isinstance(leg.get("seed"), int):
            problems.append(f"leg[{i}]: seed must be int")
        if not isinstance(leg.get("config"), dict):
            problems.append(f"leg[{i}]: config must be dict")
    fin = tour.get("finale")
    if not isinstance(fin, dict) or fin.get("kind") not in LEG_KINDS:
        problems.append("finale: invalid")
    return problems


def load(app) -> tuple[dict, list[str]]:
    path = DATA_DIR / "prism.tour" / "tour.json"
    try:
        tour = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"prism.tour: unreadable ({exc})"]
    problems = validate(tour)
    if problems:
        for p in problems:
            LOG.warning("prism.tour: %s", p)
    return tour, problems
