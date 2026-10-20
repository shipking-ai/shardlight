"""Static description of the Orrery shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="orrery",
    title="Orrery",
    genre="Space Exploration",
    tagline="A galaxy that keeps its own books",
    blurb="Fly a salvage ship through a seeded galaxy of eighty-odd systems. Five civilisations trade, expand and "
          "go to war whether or not you watch. Triangulate stray signals, solve their locks, and wind the five "
          "gears of the Last Lamp.",
    color=(111, 224, 255),
    dark=(14, 12, 36),
    max_players=1,
    controls=(("UP/LEFT/RIGHT", "Thrust and turn"), ("A", "Pulse cannon"), ("B", "Hold: lock a missile"), ("X", "Hold: beam"),
              ("Y", "Boost"), ("L", "Decoy"), ("R", "Hold: dock / scan / gear (or ship ability)"), ("SELECT", "Star chart")),
    options=({"key": "seed", "label": "Galaxy seed", "choices": ["random", 1, 7, 42, 1337, 20241019], "default": "random"},),
)
