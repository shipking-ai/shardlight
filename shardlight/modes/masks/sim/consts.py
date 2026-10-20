"""Constants shared by the deterministic combat core.

Units: positions and velocities are integers in 1/16 pixel ("sub-pixels").  Character data authored in
pixels is converted at load time.  Nothing in the simulation uses floats, wall-clock time or global
random state.
"""
from __future__ import annotations

SUB = 16                      # sub-pixels per pixel
FPS = 60

# input bitmask (absolute screen directions; facing-relative conversion happens in the buffer)
UP, DOWN, LEFT, RIGHT = 1, 2, 4, 8
LP, MP, HP, PAR = 16, 32, 64, 128     # light / medium / heavy / parry
DASHF, DASHB = 256, 512                # convenience macro buttons (shoulders)
ATTACKS = LP | MP | HP
BUTTON_NAMES = {"L": LP, "M": MP, "H": HP, "P": PAR}
DIRS = UP | DOWN | LEFT | RIGHT

# logical engine button -> sim bit (used by the scene and the replay recorder)
LOGICAL_TO_BIT = {"UP": UP, "DOWN": DOWN, "LEFT": LEFT, "RIGHT": RIGHT, "A": LP, "B": MP, "X": HP,
                  "Y": PAR, "R": DASHF, "L": DASHB}

BUFFER_FRAMES = 6             # input buffer window for pressed buttons
SIMUL_FRAMES = 3              # simultaneous-press tolerance
MOTION_FRAMES = 16            # a motion must complete within this many frames
HISTORY = 48                  # frames of input kept per player
CHARGE_FRAMES = 38            # frames a charge direction must be held
CHARGE_GRACE = 4              # frames the charge may be broken without losing it

# physics
GRAVITY = 8
FRICTION = 2                  # ground knockback deceleration (sub-px / frame^2)
AIR_FRICTION = 1
STAGE_HALF = 260 * SUB        # walls are at +/- this x
PUSH_HALF = 11 * SUB          # default body push half-width
MAX_SEP = 190 * SUB           # fighters may not separate more than this (camera limit)
MIN_SEP_AIR = 6 * SUB

# round
ROUND_FRAMES = 99 * FPS
INTRO_FRAMES = 90
KO_FRAMES = 110
ROUND_END_FRAMES = 150
ROUNDS_TO_WIN = 2

# health / meter
MAX_HEALTH = 1000
MAX_METER = 1000
SUPER_COST = 500
PUSHBLOCK_COST = 100

# defence timings
PARRY_WINDOW = 6              # active frames of a parry
PARRY_RECOVERY = 22           # whiff recovery after the window
PARRY_PENALTY = 14            # extra recovery added for every consecutive parry attempt (spam penalty)
PARRY_SUCCESS_RECOVERY = 4    # the parrier recovers fast after a success
PARRY_ADV = 9                 # frames the attacker is held in recovery extension on a parry
PARRY_HITSTOP = 8
PARRY_MEMORY = 90             # frames over which consecutive parry attempts are counted
THROW_TECH_WINDOW = 8
THROW_GRAB_FRAMES = 22
THROW_INVULN_WAKE = 6
BLOCK_PUSH_PX = 5
PUSHBLOCK_FRAMES = 12
WAKEUP_INVULN = 6

# combo scaling (percent of base damage by hit index, 0-based)
PRORATION = (100, 100, 90, 80, 70, 60, 50, 40, 35, 30, 25, 20, 15, 10)
MIN_DAMAGE_PERCENT = 10
COMBO_DAMAGE_CAP = 650        # hard cap on damage per combo (of 1000 health)
COMBO_HIT_CAP = 40
JUGGLE_LIMIT = 4
HITSTUN_DECAY_START = 4       # combo hit index after which hitstun is reduced
HITSTUN_DECAY = 1

# states (strings keep state hashing and debugging readable)
S_IDLE, S_CROUCH, S_WALKF, S_WALKB = "idle", "crouch", "walkf", "walkb"
S_PREJUMP, S_AIR, S_LAND = "prejump", "air", "land"
S_ATTACK, S_DASHF, S_DASHB = "attack", "dashf", "dashb"
S_HIT, S_HITAIR, S_BLOCK = "hit", "hitair", "block"
S_DOWN, S_WAKE = "down", "wake"
S_PARRY, S_GRAB, S_THROWN, S_TECH = "parry", "grab", "thrown", "tech"
S_KO, S_WIN = "ko", "win"

ACTIONABLE = (S_IDLE, S_CROUCH, S_WALKF, S_WALKB)

HEIGHT_HIGH, HEIGHT_MID, HEIGHT_LOW = "high", "mid", "low"


def isqrt(n: int) -> int:
    """Integer square root (math.isqrt wrapper kept local so the core has a single numeric vocabulary)."""
    import math
    return math.isqrt(max(0, n))


def px_to_speed(px: int, friction: int = FRICTION) -> int:
    """Initial velocity (sub-px / frame) that slides ``px`` pixels under constant friction."""
    return isqrt(2 * friction * px * SUB)
