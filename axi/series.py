"""Series + Multibracket pure-data classes.

Phase 8: groups tournaments across episodes (Series) and across
parallel brackets in a single event (Multibracket). No Discord refs.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Series:
    """Recurring tournament lineage across episodes.

    Identified by (guild_id, name, season, game, pinned_channel).
    A Series spans multiple Tournament instances (one per episode);
    each episode's Tournament gets a series_ctr = index in the lineage.
    """
    guild_id: int
    name: str
    season: int
    game: str            # comma-joined string when multi-game
    pinned_channel: str
    rowid: Optional[int] = None

    def __post_init__(self):
        # Source's Series.__init__ accepts a list for game and joins it.
        if isinstance(self.game, list):
            self.game = ", ".join(self.game)

    def get_db_entry(self):
        """5-tuple matching source's series column order."""
        return (
            self.guild_id,
            self.name,
            self.season,
            self.game,
            self.pinned_channel,
        )


@dataclass
class Multibracket:
    """Named event with potentially multiple parallel brackets per
    episode (e.g. RPS + Smash + Rivals running simultaneously)."""
    name: str
    rowid: Optional[int] = None

    def get_db_entry(self):
        """1-tuple matching source's multibrackets column order."""
        return (self.name,)
