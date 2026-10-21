"""Admin-only cheat tools. Gated behind ``app.admin`` (debug flag or SHARDLIGHT_ADMIN env)."""
from __future__ import annotations

from .ui import MenuScene, MenuItem


class AdminPanel(MenuScene):
    def __init__(self, app):
        super().__init__(app, "ADMIN TOOLS", self._items, 260, overlay=True,
                         footer=[("CONFIRM", "Select"), ("BACK", "Close")])

    def _items(self) -> list[MenuItem]:
        a = self.app
        items: list[MenuItem] = []
        top = a.scenes.top
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
        top = self.app.scenes.top
        leg = getattr(top, "leg", None)
        if leg is not None and hasattr(leg, "debug_force_win"):
            leg.debug_force_win()
            self.app.toast("Leg won (admin)", (150, 230, 170))

    def _skip_tour(self) -> None:
        top = self.app.scenes.top
        if hasattr(top, "legs_spec") and hasattr(top, "_start_finale"):
            top.leg_index = len(top.legs_spec)
            top._start_finale()

    def _refill(self) -> None:
        top = self.app.scenes.top
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

    def _toggle_god(self) -> None:
        self.app.admin_god = not getattr(self.app, "admin_god", False)
        self.app.toast(f"God mode {'ON' if self.app.admin_god else 'OFF'} (admin)", (255, 220, 120))
        self.rebuild()