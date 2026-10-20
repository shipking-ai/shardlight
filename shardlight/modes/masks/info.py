"""Static description of the Masks shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="masks",
    title="Masks",
    genre="2D Fighting Game",
    tagline="The Gauntlet of Masks",
    blurb="Every fighter wears the face of a feeling. Learn frame data, read habits, parry on the beat and climb the "
          "Gauntlet - or settle it with a friend on the same keyboard or two controllers.",
    color=(214, 58, 44),
    dark=(38, 34, 52),
    max_players=2,
    controls=(("A", "Light attack"), ("B", "Medium attack"), ("X", "Heavy attack"), ("Y", "Parry (tight timing)"),
              ("R", "Forward dash"), ("L", "Back dash"), ("SELECT", "Training options"), ("PAUSE", "Pause / move list")),
    options=({"key": "cpu", "label": "CPU level", "choices": [1, 2, 3, 4], "default": 2},),
)
