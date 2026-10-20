"""Static description of the Grand Tour (final world of the restored Lens)."""
from ...core.scene import ModeInfo

INFO = ModeInfo(
    id="prism",
    title="The Grand Tour",
    genre="Final World",
    tagline="Eight shards, one lamp, one last flight",
    blurb="When every facet is repaired, the Lens opens. Walk all eight shards once more, then fly into the light.",
    color=(230, 200, 120),
    dark=(24, 20, 14),
    max_players=1,
    controls=(("A", "Confirm / interact"), ("B", "Back"), ("PAUSE", "Pause")),
)
