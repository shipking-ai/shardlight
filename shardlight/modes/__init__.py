"""Mode registry.  Each mode is a subpackage ``shardlight.modes.<id>`` exposing:

    INFO: ModeInfo                      static description (see core.scene.ModeInfo)
    create(app, **opts) -> Scene        build the mode's root scene (a ModeScene)
    register_content(db) -> None        optional: register ContentDB kinds this mode understands

A mode that is not (yet) implemented simply fails to import and is shown as *dormant* in the hub.
"""
from __future__ import annotations

import importlib
from types import ModuleType

from ..core import log

LOG = log.get("modes")

# TODO(#1): None of these shards has been played by hand yet; expect to retune data/<kind>/*.json after a playtest pass.
MODE_IDS = ["cinder", "verdant", "umbra", "slipstream", "concord", "terrace", "masks", "orrery"]


def load(mode_id: str) -> ModuleType | None:
    try:
        mod = importlib.import_module(f"{__name__}.{mode_id}")
    except ModuleNotFoundError as exc:
        if exc.name == f"{__name__}.{mode_id}":
            return None      # not implemented yet
        LOG.exception("mode %s failed to import", mode_id)
        return None
    except Exception:
        LOG.exception("mode %s failed to import", mode_id)
        return None
    if not hasattr(mod, "INFO") or not hasattr(mod, "create"):
        LOG.error("mode %s lacks INFO/create", mode_id)
        return None
    return mod
