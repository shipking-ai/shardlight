"""Admin-only cheat tools. Gated behind a verified admin token (see verify_token)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

_ADMIN_TOKEN_HASH = "4c3786edb370a355fdb24367cacb413117891753d6da264ac095f2e85b194145"


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    return hashlib.sha256(token.encode("utf-8")).hexdigest() == _ADMIN_TOKEN_HASH


def resolve_admin_token() -> str | None:
    """Look for an admin token in env, CLI-adjacent files, and the user home."""
    tok = os.environ.get("SHARDLIGHT_ADMIN_TOKEN")
    if tok:
        return tok
    candidates = [
        Path.cwd() / "admin.token",
        Path.home() / ".shardlight" / "admin.token",
    ]
    try:
        from .paths import user_dir
        candidates.append(user_dir() / "admin.token")
    except Exception:
        pass
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return None


from .ui import MenuScene, MenuItem


class AdminPanel(MenuScene):
    def __init__(self, app):
        super().__init__(app, "ADMIN TOOLS", self._items, 260, overlay=True,
                         footer=[("CONFIRM", "Select"), ("BACK", "Close")])

    @property
    def target(self):
        st = self.app.scenes.stack
        return st[-2] if len(st) >= 2 else None

    def _items(self) -> list[MenuItem]:
        a = self.app
        items: list[MenuItem] = []
        top = self.target
        mode_id = getattr(top, "mode_id", None)
        if mode_id is not None and a.world is not None and mode_id in {
                "cinder", "verdant", "umbra", "slipstream", "concord", "terrace", "masks", "orrery"}:
            items.append(MenuItem("Beat this shard", lambda mid=mode_id: self._beat_shard(mid)))
        if a.world is not None:
            items.append(MenuItem("Grant all facets", self._grant_all))
        if top is not None and (hasattr(top, "legs_spec") or hasattr(top, "leg")):
            items.append(MenuItem("Win current tour leg", self._win_leg))
            items.append(MenuItem("Skip tour to finale", self._skip_tour))
        if top is not None and hasattr(top, "fs") and hasattr(getattr(top, "fs", None), "player"):
            items.append(MenuItem("Refill ship", self._refill))
        # cinder: gain every boon/ability
        run = getattr(top, "run", None)
        if run is not None and getattr(run, "perks", None) is not None and getattr(run, "lib", None) is not None:
            items.append(MenuItem("Gain every boon", self._grant_boons))
        # cinder: unlock every boon/ability
        if getattr(top, "lib", None) is not None and getattr(top.lib, "boons", None) is not None:
            items.append(MenuItem("Unlock all boons", self._unlock_cinder_boons))
        items.append(MenuItem(f"God mode: {'ON' if getattr(a, 'admin_god', False) else 'OFF'}", self._toggle_god))
        items.append(MenuItem("Close", a.scenes.pop))
        return items

    def _beat_shard(self, mid: str) -> None:
        a = self.app
        if a.world is None:
            return
        a.world.repair_facet(mid)
        try:
            a.world.emit(f"{mid}.finished", admin=True)
        except Exception:
            pass
        a.save_now()
        a.return_to_hub()
        a.toast(f"{mid} cleared (admin)", (150, 230, 170))

    def _grant_all(self) -> None:
        a = self.app
        if a.world is None:
            return
        for mid in ("cinder", "verdant", "umbra", "slipstream", "concord", "terrace", "masks", "orrery"):
            a.world.repair_facet(mid)
        a.world.set_flag("lens_restored")
        a.save_now()
        a.toast("All facets granted (admin)", (255, 240, 200))

    def _win_leg(self) -> None:
        top = self.target
        leg = getattr(top, "leg", None)
        if leg is not None and hasattr(leg, "debug_force_win"):
            leg.debug_force_win()
            self.app.toast("Leg won (admin)", (150, 230, 170))

    def _skip_tour(self) -> None:
        top = self.target
        if hasattr(top, "legs_spec") and hasattr(top, "_start_finale"):
            top.leg_index = len(top.legs_spec)
            top._start_finale()

    def _refill(self) -> None:
        top = self.target
        fs = getattr(top, "fs", None)
        if fs is None:
            return
        p = fs.player
        p.hull = p.hull_max
        p.shield = p.shield_max
        p.energy = p.energy_max
        p.missiles = int(fs.stats.get("missiles", p.missiles))
        p.decoys = int(fs.stats.get("decoys", p.decoys))
        self.app.toast("Refilled (admin)", (150, 230, 170))

    def _grant_boons(self) -> None:
        top = self.app.scenes.top
        run = getattr(top, "run", None)
        if run is None or run.perks is None or run.lib is None:
            return
        for bid in list(run.lib.lns.keys()):
            run.perks.add(bid)
        try:
            run.perks.rebuild()
        except Exception:
            pass
        self.app.toast("All boons granted (admin)", (255, 240, 200))
        self.rebuild()

    def _unlock_cinder_boons(self) -> None:
        top = self.target
        lib = getattr(top, "lib", None)
        if lib is None:
            return
        data = getattr(top, "data", None)
        if data is None and hasattr(self.app, "world"):
            try:
                data = self.app.world.mode_data("cinder")
                top.data = data
            except Exception:
                data = None
        if isinstance(data, dict):
            u = data.setdefault("unlocked", {"boons": [], "weapons": [], "mods": []})
            u.setdefault("boons", [])
            u.setdefault("mods", [])
            for bid in lib.boons:
                if bid not in u["boons"]:
                    u["boons"].append(bid)
            for mid in lib.mods:
                if mid not in u["mods"]:
                    u["mods"].append(mid)
        # active run: grant stacks
        run = getattr(top, "run", None)
        if run is None:
            sc = getattr(top, "screen", None)
            run = getattr(sc, "run", None) if sc is not None else None
        if run is not None and getattr(run, "perks", None) is not None:
            for bid in lib.boons:
                try:
                    run.perks.add(bid)
                except Exception:
                    pass
        self.app.save_now()
        self.app.toast("All boons unlocked (admin)", (255, 240, 200))
        self.rebuild()

    def _toggle_god(self) -> None:
        self.app.admin_god = not getattr(self.app, "admin_god", False)
        self.app.toast(f"God mode {'ON' if self.app.admin_god else 'OFF'} (admin)", (255, 220, 120))
        self.rebuild()