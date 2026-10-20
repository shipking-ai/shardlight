"""Static description of the Slipstream shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="slipstream",
    title="Slipstream",
    genre="Futuristic Racing",
    tagline="Salt, speed and one more corner",
    blurb="Drift to build boost, tuck behind rivals to draft, and gamble on risky shortcuts across the white. "
          "Race solo, chase your own ghost, win the Salt Cup - or split the screen with a friend.",
    color=(239, 75, 51),
    dark=(20, 21, 42),
    max_players=2,
    controls=(("UP", "Accelerate (or A)"), ("B", "Brake / reverse"), ("X", "Handbrake: drift"), ("Y", "Boost"),
              ("R", "Rewind (Chronograph)"), ("SELECT", "Reset to track"), ("PAUSE", "Pause")),
    options=({"key": "seed", "label": "Track seed", "choices": ["random", 12, 24, 28, 46, 7, 101, 2024], "default": "random"},),
)
