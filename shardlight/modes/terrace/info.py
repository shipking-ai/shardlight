"""Static description of the Terrace shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="terrace",
    title="Terrace",
    genre="Sandbox Survival",
    tagline="Dig, build, and keep the vigil",
    blurb="A side-on world of meadow, forest, salt flats and ice, with caves down to lava. Craft your way up the tool "
          "tiers, tame the grazers, outlast the night, and raise the Keystone on its plinth.",
    color=(111, 168, 74),
    dark=(90, 61, 43),
    max_players=1,
    controls=(("MOVE", "Walk, swim, climb ladders and trunks"), ("A", "Jump"), ("X", "Mine / attack (hold)"), ("Y", "Place / use held item"),
              ("B", "Interact: doors, beds, chests, shrines"), ("L", "Previous hotbar slot"), ("R", "Next hotbar slot"),
              ("SELECT", "Pack and crafting"), ("UP/DOWN", "Aim up / down"), ("PAUSE", "Pause")),
    options=({"key": "seed", "label": "World seed", "choices": ["random", 1, 7, 42, 1337, 20241019], "default": "random"},),
)
