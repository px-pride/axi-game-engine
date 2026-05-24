"""Series + Multibracket handler.

Phase 8: persistence + scope→series mapping for the Series /
Multibracket data model. Pure layer — no Discord imports.

Operations mirror source's axi_backend.create_series /
create_multibracket / set_series / get_series_ctr.
"""

from collections import defaultdict

import axi.handlers.database_handler as db
from axi.series import Series, Multibracket


class SeriesState:
    def __init__(self):
        # (guild_id, scope) → Series instance
        self.scope_to_series = defaultdict(lambda: None)
        # series rowid → Series
        self.series_by_id = {}
        # multibracket rowid → Multibracket
        self.multibrackets_by_id = {}

    def reset(self):
        """Test-only: clears in-memory registry (does not touch DB)."""
        self.scope_to_series.clear()
        self.series_by_id.clear()
        self.multibrackets_by_id.clear()


state = SeriesState()


def create_series(guild_id, name, season, game, pinned_channel):
    """Persist a new Series, register in state, return the instance."""
    s = Series(
        guild_id=guild_id,
        name=name,
        season=season,
        game=game,                # __post_init__ joins lists
        pinned_channel=pinned_channel,
    )
    s.rowid = db.add_entry("series", s.get_db_entry())
    state.series_by_id[s.rowid] = s
    return s


def create_multibracket(name):
    """Persist a new Multibracket, register in state, return the instance."""
    m = Multibracket(name=name)
    m.rowid = db.add_entry("multibrackets", m.get_db_entry())
    state.multibrackets_by_id[m.rowid] = m
    return m


def set_series_for_scope(guild_id, scope, series):
    """Bind a Series to a (guild, scope) pair. Subsequent tournaments
    created in this scope will inherit this series link."""
    state.scope_to_series[(guild_id, scope)] = series


def get_series_for_scope(guild_id, scope):
    return state.scope_to_series.get((guild_id, scope))


def get_series_ctr(series_id):
    """Next episode index for this series.

    Defined as count(tourneys.series_id == sid) + 1 — matches source.
    """
    rows = db.load_entries_where("tourneys", "series_id", series_id)
    return len(rows) + 1


def register_tournament(tournament, multibracket_id=None):
    """Insert a tourneys row linking the Tournament to its series +
    (optional) multibracket. Mutates the Tournament with series_ctr +
    multibracket_id. No-op if tournament has no series_id."""
    series_id = getattr(tournament, "series_id", None)
    if series_id is None:
        return None
    series_ctr = get_series_ctr(series_id)
    tourney_rowid = db.add_entry(
        "tourneys", (multibracket_id, series_id, series_ctr))
    tournament.series_ctr = series_ctr
    tournament.multibracket_id = multibracket_id
    return tourney_rowid


def load_series(rowid):
    """Reconstruct a Series instance from its DB row."""
    row = db.load_entry("series", rowid)
    if not row:
        return None
    # Columns: guild_id, name, season, game, pinned_channel, timestamp
    s = Series(
        guild_id=row[0],
        name=row[1],
        season=row[2],
        game=row[3],
        pinned_channel=row[4],
        rowid=rowid,
    )
    state.series_by_id[rowid] = s
    return s


def load_multibracket(rowid):
    """Reconstruct a Multibracket from its DB row."""
    row = db.load_entry("multibrackets", rowid)
    if not row:
        return None
    # Columns: name, timestamp
    m = Multibracket(name=row[0], rowid=rowid)
    state.multibrackets_by_id[rowid] = m
    return m
