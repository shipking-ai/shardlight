"""Static description of the Umbra shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="umbra",
    title="Umbra",
    genre="Psychological Horror",
    tagline="Three nights in the Gloaming Ward",
    blurb="Top-down stealth in a dark building. You are never safe from sound, light or habit: the Hark listens, "
          "the Stillwatch only sees what is lit, and the Understudy learns where you hide. Reach each night's goal, "
          "return to the safe room, and read what the dead left behind.",
    color=(47, 90, 90),
    dark=(7, 9, 14),
    max_players=1,
    controls=(("MOVE", "Walk"), ("A", "Run (hold, loud)"), ("L", "Sneak (hold, quiet)"), ("B", "Interact: doors, search, hide, read"),
              ("X", "Use / throw selected item"), ("R", "Next item"), ("Y", "Flashlight / lamp / off"), ("SELECT", "Bag and journal"),
              ("PAUSE", "Pause")),
    options=({"key": "seed", "label": "Ward seed", "choices": ["random", 1, 7, 42, 1337, 20241019], "default": "random"},),
)
