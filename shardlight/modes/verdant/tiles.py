"""Tile and object tables for Hollowmere.  Pure data (no pygame): ids, walkability, costs, gather rules.

Ground ids live in a uint8 array, objects in a second uint8 array; both are indexed ``[y, x]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TILE = 16

# ------------------------------------------------------------------------------------ ground
GROUND_NAMES = [
    "deep", "shallow", "sand", "mud", "grass", "forest", "moor", "rock", "dirt", "road", "bridge", "plank",
    "flag", "farm", "cliff", "ruin", "cobble", "woodfloor", "cave", "cavewall", "crypt", "cryptwall", "void",
    "bog", "blight", "carpet",
]
G = {n: i for i, n in enumerate(GROUND_NAMES)}
(DEEP, SHALLOW, SAND, MUD, GRASS, FOREST, MOOR, ROCK, DIRT, ROAD, BRIDGE, PLANK, FLAG, FARM, CLIFF, RUIN,
 COBBLE, WOODFLOOR, CAVE, CAVEWALL, CRYPT, CRYPTWALL, VOID, BOG, BLIGHT, CARPET) = range(len(GROUND_NAMES))

# movement multiplier on each ground type (0 = impassable)
GROUND_SPEED = {DEEP: 0.0, SHALLOW: 0.62, SAND: 0.92, MUD: 0.8, GRASS: 1.0, FOREST: 0.96, MOOR: 0.94, ROCK: 0.92,
                DIRT: 1.05, ROAD: 1.12, BRIDGE: 1.08, PLANK: 1.08, FLAG: 1.08, FARM: 0.9, CLIFF: 0.0, RUIN: 1.0,
                COBBLE: 1.1, WOODFLOOR: 1.05, CAVE: 1.0, CAVEWALL: 0.0, CRYPT: 1.0, CRYPTWALL: 0.0, VOID: 0.0,
                BOG: 0.55, BLIGHT: 0.9, CARPET: 1.05}
# A* cost for NPC pathing (lower = preferred)
GROUND_COST = {SHALLOW: 3.2, SAND: 1.0, MUD: 1.5, GRASS: 1.0, FOREST: 1.1, MOOR: 1.2, ROCK: 1.3, DIRT: 0.8, ROAD: 0.6,
               BRIDGE: 0.7, PLANK: 0.7, FLAG: 0.6, FARM: 1.2, RUIN: 1.0, COBBLE: 0.6, WOODFLOOR: 0.6, CAVE: 1.0,
               CRYPT: 1.0, BOG: 5.0, BLIGHT: 1.2, CARPET: 0.6}
# spill priority for autotiled edges: tiles with a higher value spill over lower neighbours
GROUND_PRIO = {DEEP: 0, SHALLOW: 1, BOG: 2, MUD: 3, SAND: 4, GRASS: 6, FOREST: 7, MOOR: 7, ROCK: 8, BLIGHT: 6,
               FARM: 5, DIRT: 9, ROAD: 10, COBBLE: 11, FLAG: 11, RUIN: 11, PLANK: 12, BRIDGE: 13, WOODFLOOR: 12,
               CAVE: 5, CRYPT: 5, CARPET: 13, CLIFF: 14, CAVEWALL: 14, CRYPTWALL: 14, VOID: 15}
WATER_TILES = (DEEP, SHALLOW, BOG)

# ------------------------------------------------------------------------------------ objects


@dataclass(frozen=True)
class ObjDef:
    name: str
    blocks: bool = False
    height: int = 1            # sprite height in tiles (draw order only)
    light: tuple | None = None  # (radius, (r, g, b), night_only)
    gather: dict | None = None  # {"item","skill","time","regrow","xp"}
    interact: str = ""          # label shown by the contextual prompt
    decor: bool = False         # walkable ground clutter (tufts, flowers, reeds)


OBJ_LIST: list[ObjDef] = [
    ObjDef("none"),
    ObjDef("oak", True, 2), ObjDef("pine", True, 2), ObjDef("dead", True, 2), ObjDef("willow", True, 2),
    ObjDef("bush", True), ObjDef("berry", True, 1, gather={"item": "hedge_berries", "skill": "forage", "time": 0.7, "regrow": 3, "xp": 3},
                                 interact="Pick berries"),
    ObjDef("boulder", True), ObjDef("stones", decor=True), ObjDef("reeds", decor=True), ObjDef("cattail", decor=True),
    ObjDef("flowers", decor=True), ObjDef("tuft", decor=True), ObjDef("mushroom", False, 1,
                                                                    gather={"item": "bellcap", "skill": "forage", "time": 0.7, "regrow": 4, "xp": 3},
                                                                    interact="Pick mushrooms"),
    ObjDef("standing", True, 2), ObjDef("pillar", True, 2), ObjDef("ruinwall", True), ObjDef("fence", True),
    ObjDef("lamp", True, 2, interact="Light lamp"), ObjDef("well", True, 1, interact="Draw water"),
    ObjDef("stall", True), ObjDef("barrel", True), ObjDef("crate", True),
    ObjDef("notice", True, 1, interact="Read notice board"),
    ObjDef("haystack", True), ObjDef("campfire", True, 1, light=(46, (255, 170, 90), False), interact="Cook at fire"),
    ObjDef("tent", True, 2),
    ObjDef("ore", True, 1, gather={"item": "iron_ore", "skill": "delve", "time": 1.3, "regrow": 6, "xp": 5},
           interact="Mine ore"),
    ObjDef("reedmint", False, 1, gather={"item": "reedmint", "skill": "forage", "time": 0.7, "regrow": 3, "xp": 3},
           interact="Pick reedmint"),
    ObjDef("heather", False, 1, gather={"item": "heather_sprig", "skill": "forage", "time": 0.7, "regrow": 3, "xp": 3},
           interact="Cut heather"),
    ObjDef("flax", False, 1, gather={"item": "flax", "skill": "forage", "time": 0.6, "regrow": 3, "xp": 2},
           interact="Gather flax"),
    ObjDef("chest", True, 1, interact="Open chest"), ObjDef("grave", True), ObjDef("statue", True, 2),
    ObjDef("brazier", True, 1, light=(54, (255, 190, 110), False)), ObjDef("bed", True, 1, interact="Rest"),
    ObjDef("table", True), ObjDef("hearth", True, 1, light=(64, (255, 160, 80), False), interact="Cook at hearth"),
    ObjDef("shelf", True, 2), ObjDef("bench", True, 1, interact="Use lamp bench"),
    ObjDef("forge", True, 1, light=(40, (255, 140, 60), False), interact="Use forge"),
    ObjDef("hiddendoor", True, 2, interact="Open hidden door"), ObjDef("signpost", True, 1, interact="Read sign"),
    ObjDef("boat", True), ObjDef("net", True), ObjDef("pierpost", True),
    ObjDef("stairdown", False, 1, interact="Descend"), ObjDef("stairup", False, 1, interact="Climb"),
    ObjDef("ringtree", True, 2), ObjDef("banner", True, 2), ObjDef("barricade", True),
    ObjDef("bunting", False, 1), ObjDef("stump", True), ObjDef("log", True), ObjDef("brokenplank", False),
    ObjDef("glowmoss", False, 1, light=(26, (130, 230, 170), False), decor=True),
    ObjDef("cairn", True, 1, interact="Search cairn"), ObjDef("dig", False, 1, interact="Dig"),
    ObjDef("rug", False), ObjDef("candle", False, 1, light=(28, (255, 210, 130), False), decor=True),
    ObjDef("greatlamp", True, 2, interact="Light the Great Lamp"),
    ObjDef("greatlamp_lit", True, 2, light=(150, (255, 210, 130), False)),
    ObjDef("tablet", True, 1, interact="Read the tablet"), ObjDef("anvil", True, 1), ObjDef("counter", True, 1),
    ObjDef("lamp_lit", True, 2, light=(70, (255, 200, 120), True), interact="Lamp is lit"),
]
O = {d.name: i for i, d in enumerate(OBJ_LIST)}
OBJ_COUNT = len(OBJ_LIST)

# arrays for fast numpy lookups
import numpy as np  # noqa: E402

OBJ_BLOCKS = np.array([d.blocks for d in OBJ_LIST], dtype=bool)
GROUND_WALK = np.array([GROUND_SPEED.get(i, 1.0) > 0 for i in range(len(GROUND_NAMES))], dtype=bool)
GROUND_SPEED_ARR = np.array([GROUND_SPEED.get(i, 1.0) for i in range(len(GROUND_NAMES))], dtype=np.float32)
GROUND_COST_ARR = np.array([GROUND_COST.get(i, 1e9) for i in range(len(GROUND_NAMES))], dtype=np.float32)

# region ids for the coarse biome map
REGION_NAMES = ["sea", "coast", "meadow", "forest", "marsh", "highmoor", "river", "ruins", "town"]
R = {n: i for i, n in enumerate(REGION_NAMES)}
REGION_LABEL = {"sea": "the Salt Sea", "coast": "the Shingle Coast", "meadow": "Hollowmere Meadows",
                "forest": "the Greywood", "marsh": "the Sallow Marsh", "highmoor": "the High Moor",
                "river": "the Kestrel River", "ruins": "Old Ruins", "town": "a settlement"}


def obj_id(name: str) -> int:
    return O[name]


def hash2(x: int, y: int, salt: int = 0) -> int:
    """Cheap deterministic 2D integer hash (used for tile variation, never for gameplay randomness)."""
    h = (x * 374761393 + y * 668265263 + salt * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return h ^ (h >> 16)
