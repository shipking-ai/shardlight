"""Shared constants for the Gloaming Ward: grid kinds, speeds, noise tables, palette."""
from __future__ import annotations

TILE = 12                      # pixels per tile at the 480x270 internal resolution
SCREEN_W, SCREEN_H = 480, 270

# --- grid cell kinds
VOID, FLOOR, WALL, DOOR = 0, 1, 2, 3

# --- floor surfaces (footstep colour)
S_WOOD, S_TILE, S_STONE, S_CARPET, S_GRAVEL, S_GLASS, S_WATER = range(7)
SURFACE_NAMES = ("wood", "tile", "stone", "carpet", "gravel", "glass", "water")
SURFACE_BY_NAME = {n: i for i, n in enumerate(SURFACE_NAMES)}
# multiplier on footstep loudness per surface
SURFACE_LOUDNESS = (1.0, 1.15, 1.05, 0.55, 1.6, 2.1, 1.3)

# --- movement stances
SNEAK, WALK, RUN = "sneak", "walk", "run"
SPEED = {SNEAK: 27.0, WALK: 50.0, RUN: 86.0}              # pixels per second
STRIDE = {SNEAK: 11.0, WALK: 15.0, RUN: 18.0}              # pixels between footfalls
STEP_LOUDNESS = {SNEAK: 1.5, WALK: 4.5, RUN: 9.0}          # tiles (audible radius), before surface multiplier

# --- noise loudness (tiles of audible radius)
NOISE = {
    "door_open": 6.0, "door_open_sneak": 2.5, "door_close": 5.5, "door_close_sneak": 2.0,
    "door_slam": 11.0, "door_bang": 9.0, "door_break": 15.0, "unlock": 1.6,
    "flashlight": 2.8, "match": 2.4, "lamp_refill": 3.0, "bandage": 2.4, "pickup": 2.0, "rustle": 3.2,
    "drawer": 4.0, "locker": 5.0, "breath": 1.2, "gasp": 6.5, "pant": 4.0,
    "fuse": 4.5, "generator": 22.0, "clock": 12.0, "crank": 18.0, "ward_hum": 7.5, "hit": 7.0,
    "thrown_default": 5.0, "scream": 12.0,
}

# --- player
PLAYER_RADIUS = 3.4
REACH = 1.55 * TILE
STAMINA_MAX = 5.0              # seconds of running
HEALTH_MAX = 3

# --- palette (ART_BIBLE: near-black, sick teal, bone, one warm lamp colour)
NEAR_BLACK = (7, 9, 14)
TEAL_DARK = (14, 26, 30)
TEAL = (47, 90, 90)
TEAL_LIGHT = (96, 150, 140)
BONE = (201, 195, 176)
BONE_DIM = (130, 126, 114)
LAMP = (255, 176, 96)
LAMP_HOT = (255, 214, 150)
COLD = (200, 232, 232)
BLOOD = (150, 30, 34)
