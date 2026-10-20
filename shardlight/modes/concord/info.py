"""Static description of the Concord shard."""
from ...core.scene import ModeInfo

SEED_CHOICES = ["random", 1, 7, 12, 42, 77, 101, 314, 2024, 31337]
SIZE_CHOICES = ["small", "medium", "large"]
# TODO(#13): balance the four houses for a human and exercise the large map more.
HOUSE_CHOICES = ["ostrel", "karrow", "saline", "wick"]

INFO = ModeInfo(
    id="concord",
    title="Concord",
    genre="Strategy / Empire Simulation",
    tagline="Ledger of Crowns",
    blurb="Four houses share one map and no calendar. March armies along roads you can feed, sign treaties you "
          "may regret, and settle borders on the battlefield or on paper.",
    color=(168, 50, 58),
    dark=(43, 36, 56),
    max_players=1,
    controls=(("A", "Select / order"), ("B", "Back"), ("X", "Province actions"), ("Y", "Ledger menu"),
              ("L", "Previous army"), ("R", "Next army"), ("SELECT", "Cycle map overlay"), ("PAUSE", "Pause")),
    options=(
        {"key": "house", "label": "Play as", "choices": HOUSE_CHOICES, "default": "ostrel"},
        {"key": "size", "label": "Map size", "choices": SIZE_CHOICES, "default": "medium"},
        {"key": "seed", "label": "Seed", "choices": SEED_CHOICES, "default": "random"},
    ),
)
