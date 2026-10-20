"""Static description of the Verdant shard."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="verdant",
    title="Verdant",
    genre="Open-World RPG",
    tagline="Hollowmere keeps its debts",
    blurb="Walk a hand-built, seeded countryside of four towns, a river, a moor and a marsh. Townsfolk keep schedules, "
          "shopkeepers keep stock, and the dark keeps count of every lamp you did not light. Fight with blade or bow, "
          "gather and craft, repay the Lamplighter's debt, and kindle the Hollow.",
    color=(106, 163, 74),
    dark=(18, 30, 20),
    max_players=1,
    controls=(("MOVE", "Walk"), ("A", "Attack (arc)"), ("X", "Dodge roll"), ("Y", "Fire bow"), ("B", "Talk / use / enter / pick"),
              ("L / R", "Cycle quick item"), ("SELECT", "Pack, quests, map, skills"), ("PAUSE", "Pause")),
    options=({"key": "seed", "label": "World seed", "choices": ["random", 1, 7, 42, 1337, 20241019], "default": "random"},),
)
