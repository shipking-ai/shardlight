"""Shared constants for the Terrace shard."""
from __future__ import annotations

TILE = 8                    # pixels per tile
CHUNK = 32                  # tiles per chunk edge
WORLD_W = 512
WORLD_H = 256
VIEW_W, VIEW_H = 480, 270

DAY_LEN = 480.0             # seconds of game time per day
START_CLOCK = 0.06          # clock fraction at a new game (just after dawn)
GEN_VERSION = 1             # bump when worldgen output changes (invalidates diffs deliberately)

# liquid layer encoding: low nibble = amount (0..8), bit 4 = lava
LIQ_MAX = 8
LIQ_LAVA = 16
LIQ_AMOUNT_MASK = 15

# block ids of the base game (asserted against data/terrace.block by the tests)
AIR, DIRT, GRASS, STONE, SLATE, SAND, SANDSTONE, SALT, SNOW, ICE = range(10)
LOG, LEAVES, PLANKS = 10, 11, 12
COAL_ORE, COPPER_ORE, IRON_ORE, GOLD_ORE, LUMINA_ORE, CINDER_ORE = 13, 14, 15, 16, 17, 18
BEDROCK, OBSIDIAN, BRICK, GLASS, TORCH = 19, 20, 21, 22, 23
WORKBENCH, FURNACE, FORGE, LOOM, CHEST = 24, 25, 26, 27, 28
DOOR_CLOSED, DOOR_OPEN, FARMLAND = 29, 30, 31
WHEAT0, TUBER0 = 32, 36
TALLGRASS, FLOWER, GLOWCAP, CACTUS, SAPLING = 40, 41, 42, 43, 44
PRISM, IRON_BLOCK, GOLD_BLOCK, COPPER_BLOCK, LUMINA_BLOCK = 45, 46, 47, 48, 49
PINE_LEAVES, FENCE, SHRINE, VAULT_SEAL, PLINTH, BED, RUIN_BRICK, LADDER = 50, 51, 52, 53, 54, 55, 56, 57
FARMLAND_WET, MOSS = 58, 59

BIOMES = ("meadow", "forest", "salt", "frozen")
