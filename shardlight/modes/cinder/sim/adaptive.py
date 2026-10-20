"""Adaptive enemy behaviour built on ``core.ai.AdaptiveController``.

What the model watches (all recorded by the room, never hidden from the player):
    dodge_cw / dodge_ccw      which way the player rolls around the nearest enemy
    atk_melee / atk_ranged    what kind of attack was started
    atk_light / atk_heavy     tapped versus charged attacks
    parry_try / dodge_any     reaching for the parry versus the dodge

What enemies may do about it (every counter is bounded, slew-limited and cooled down by the controller;
``difficulty.adaptive_ai`` scales it, 0 disables it):
    lead_cw / lead_ccw  aimed attacks (arrows, lunges, charges) are rotated up to ``MAX_LEAD`` toward the habit
    keep_distance       ranged enemies hold ``MAX_SPACING`` px further away from a melee-only player
    pressure            ranged-only players are rushed: one more attack token, quicker approach
    bait_parry          strikes may be held for up to ``MAX_FEINT`` extra frames after the telegraph fills
    punish_charge       attack cooldowns shrink up to ``MAX_QUICKEN`` while the player habitually charges

None of these changes damage numbers.  The telegraph stays honest: feints are shown as a held, pulsing
telegraph.
"""
from __future__ import annotations

from ....core.ai import Adaptation, AdaptiveController, PlayerModel

MAX_LEAD = 0.20          # radians at level == max_bonus (about 11 degrees); strength 1.5 => 0.30
MAX_SPACING = 34.0       # pixels
MAX_FEINT = 10           # frames
MAX_QUICKEN = 0.30       # fraction of cooldown removed
MAX_BONUS = 0.35         # Adaptation.max_bonus: the level that maps to the maxima above


def build(strength: float, half_life: float = 22.0) -> AdaptiveController:
    model = PlayerModel(half_life=half_life)
    ad = [
        Adaptation("lead_cw", "dodge_cw", ("dodge_cw", "dodge_ccw"), threshold=0.70, min_weight=4.0, max_bonus=MAX_BONUS),
        Adaptation("lead_ccw", "dodge_ccw", ("dodge_cw", "dodge_ccw"), threshold=0.70, min_weight=4.0, max_bonus=MAX_BONUS),
        Adaptation("keep_distance", "atk_melee", ("atk_melee", "atk_ranged"), threshold=0.80, min_weight=6.0,
                   max_bonus=MAX_BONUS),
        Adaptation("pressure", "atk_ranged", ("atk_melee", "atk_ranged"), threshold=0.70, min_weight=6.0,
                   max_bonus=MAX_BONUS),
        Adaptation("bait_parry", "parry_try", ("parry_try", "dodge_any"), threshold=0.55, min_weight=4.0,
                   max_bonus=MAX_BONUS),
        Adaptation("punish_charge", "atk_heavy", ("atk_heavy", "atk_light"), threshold=0.60, min_weight=5.0,
                   max_bonus=MAX_BONUS),
    ]
    return AdaptiveController(model, ad, strength=strength, cooldown=8.0)


class AdaptView:
    """Gameplay-facing readout of the controller (what brains actually consult)."""

    def __init__(self, ctl: AdaptiveController) -> None:
        self.ctl = ctl

    @property
    def model(self) -> PlayerModel:
        return self.ctl.model

    def _k(self, name: str) -> float:
        return self.ctl.level(name) / MAX_BONUS          # 0 .. strength-limited (<= 1.5)

    def lead_angle(self, side_sign: float) -> float:
        """Rotation (radians) to add to an aimed attack.  ``side_sign`` +1 = clockwise on screen from the
        attacker's view of the player.  Positive result rotates clockwise."""
        return (self._k("lead_cw") - self._k("lead_ccw")) * MAX_LEAD * side_sign

    def spacing(self) -> float:
        return self._k("keep_distance") * MAX_SPACING

    def extra_tokens(self) -> int:
        return 1 if self._k("pressure") >= 0.6 else 0

    def rush(self) -> float:
        return 1.0 + 0.12 * self._k("pressure")

    def feint(self, rnd) -> int:
        k = self._k("bait_parry")
        if k <= 0.05:
            return 0
        return int(round(rnd.random() * k * MAX_FEINT))

    def quicken(self) -> float:
        return 1.0 - min(MAX_QUICKEN * 1.5, self._k("punish_charge") * MAX_QUICKEN)

    def describe(self) -> list[str]:
        out = []
        for a in self.ctl.adaptations:
            if a.level > 0.001 or a.active:
                out.append(f"{a.name}: {'ON ' if a.active else 'off'} lvl {a.level:.2f}/{a.max_bonus:.2f}")
        return out
