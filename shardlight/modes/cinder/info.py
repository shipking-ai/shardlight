"""Static description of the Cinder shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="cinder",
    title="Cinder",
    genre="Action Roguelike",
    tagline="The spire that rebuilds itself",
    blurb="Climb five floors of a tower that rearranges itself. Four weapon families evolve through how you fight; "
          "boons trade power for risk; enemies telegraph everything and slowly learn your habits.",
    color=(255, 122, 60),
    dark=(23, 20, 28),
    max_players=1,
    controls=(("A", "Light attack / chain"), ("X", "Heavy: hold to charge"), ("B", "Dodge roll"), ("Y", "Parry (time it)"),
              ("R", "Interact"), ("L", "Ember Flare"), ("SELECT", "Boon list"), ("PAUSE", "Pause")),
    options=({"key": "seed", "label": "Seed", "choices": ["random", 1, 7, 42, 1337, 20241019], "default": "random"},),
)
