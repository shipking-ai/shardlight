"""Group tactics: attack tokens, surround slots and alert propagation for one room's enemies."""
from __future__ import annotations

import math

from .geometry import TAU, angle_diff


class Squad:
    """Coordinates how many enemies may attack at once and where the rest wait.

    * Attack tokens cap simultaneous melee attackers (difficulty + adaptive 'pressure').
    * ``slot`` spreads engaged melee enemies around the player.  Tanks (shield-bearers) take the front,
      flankers take the rear, everyone else fills the gaps - which is why a swarm surrounds you and a
      bulwark has to be walked around.
    * ``alert`` spreads awareness to nearby allies so one sighting wakes the group.
    """

    RECOMPUTE = 12

    def __init__(self, room) -> None:
        self.room = room
        self.tokens: set[int] = set()
        self.slots: dict[int, float] = {}
        self._next = 0

    # tokens -------------------------------------------------------------------------------------
    def max_tokens(self) -> int:
        return self.room.difficulty.tokens + self.room.adapt.extra_tokens()

    def request(self, e) -> bool:
        self._prune()
        if e.id in self.tokens:
            return True
        if len(self.tokens) < self.max_tokens():
            self.tokens.add(e.id)
            return True
        return False

    def release(self, e) -> None:
        self.tokens.discard(e.id)

    def _prune(self) -> None:
        alive = {e.id for e in self.room.enemies if e.alive}
        self.tokens &= alive

    # slots --------------------------------------------------------------------------------------
    def update(self, centre: tuple[float, float]) -> None:
        if self.room.t < self._next:
            return
        self._next = self.room.t + self.RECOMPUTE
        members = [e for e in self.room.enemies if e.alive and getattr(e.brain, "uses_slot", False)
                   and e.brain.aware]
        n = len(members)
        self.slots.clear()
        if not n:
            return
        facing = self.room.player.facing
        cx, cy = centre
        step = TAU / max(3, n)
        free = [facing + step * (k + 0.5) for k in range(max(3, n))]
        # tanks take the slot closest to the front, flankers closest to the back, others fill the rest
        order = sorted(members, key=lambda e: {"tank": 0, "flank": 1}.get(e.brain.slot_role, 2))
        for e in order:
            role = e.brain.slot_role
            want = facing if role == "tank" else facing + math.pi if role == "flank" else \
                math.atan2(e.y - cy, e.x - cx)
            best_i, best_d = 0, 9.0
            for i, a in enumerate(free):
                d = abs(angle_diff(a, want))
                if d < best_d:
                    best_i, best_d = i, d
            self.slots[e.id] = free.pop(best_i)
            if not free:
                free = [facing + step * (k + 0.5) for k in range(max(3, n))]

    def slot_pos(self, e, centre: tuple[float, float], ring: float) -> tuple[float, float]:
        a = self.slots.get(e.id)
        if a is None:
            a = math.atan2(e.y - centre[1], e.x - centre[0])
        return centre[0] + math.cos(a) * ring, centre[1] + math.sin(a) * ring

    # awareness ----------------------------------------------------------------------------------
    def alert(self, src, pos: tuple[float, float], radius: float = 150.0) -> None:
        for e in self.room.enemies:
            if e is src or not e.alive:
                continue
            if math.hypot(e.x - src.x, e.y - src.y) <= radius:
                e.brain.hear_ally(pos)
