"""Phase 8 tests — Series + Multibracket data model + series_handler ops.

Covers Series/Multibracket dataclass construction, DB-row roundtrip,
series_handler scope→series mapping, register_tournament linkage,
series_ctr counter across episodes.

NOTE: tests use the real sqlite axi.db (no DB mock in conftest). To
avoid cross-test data collisions we use uuid-based unique names for
Series/Multibracket rows.
"""

import uuid

import pytest

import axi.handlers.database_handler as db
import axi.handlers.series_handler as sh
from axi.series import Series, Multibracket
from axi.tournament import Tournament


def _unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _clean_series_state():
    sh.state.reset()
    yield
    sh.state.reset()


# ---------------------------------------------------------------------------
# Pure dataclass tests (no DB)
# ---------------------------------------------------------------------------


class TestSeriesDataclass:
    def test_construct_with_all_fields(self):
        s = Series(guild_id=42, name="PXL", season=7,
                   game="rps", pinned_channel="general")
        assert s.guild_id == 42
        assert s.name == "PXL"
        assert s.season == 7
        assert s.game == "rps"
        assert s.pinned_channel == "general"
        assert s.rowid is None

    def test_list_game_joined_in_post_init(self):
        s = Series(guild_id=1, name="Multi", season=1,
                   game=["rps", "smash"], pinned_channel="c")
        assert s.game == "rps, smash"

    def test_get_db_entry_5tuple(self):
        s = Series(guild_id=10, name="N", season=2,
                   game="rps", pinned_channel="ch1")
        assert s.get_db_entry() == (10, "N", 2, "rps", "ch1")

    def test_list_game_in_db_entry(self):
        s = Series(guild_id=1, name="M", season=1,
                   game=["rps", "smash", "rivals"], pinned_channel="c")
        assert s.get_db_entry() == (1, "M", 1, "rps, smash, rivals", "c")


class TestMultibracketDataclass:
    def test_construct_with_name(self):
        m = Multibracket(name="Quarterfinals weekend")
        assert m.name == "Quarterfinals weekend"
        assert m.rowid is None

    def test_get_db_entry_1tuple(self):
        m = Multibracket(name="Event 1")
        assert m.get_db_entry() == ("Event 1",)


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


class TestSeriesPersistence:
    def test_create_series_persists_and_returns_rowid(self):
        name = _unique("series")
        s = sh.create_series(
            guild_id=99, name=name, season=1,
            game="rps", pinned_channel="ch")
        assert s.rowid is not None
        # Verify a row exists at that rowid.
        row = db.load_entry("series", s.rowid)
        assert row is not None
        # Columns: guild_id, name, season, game, pinned_channel, timestamp.
        assert row[0] == 99
        assert row[1] == name
        assert row[2] == 1
        assert row[3] == "rps"
        assert row[4] == "ch"

    def test_create_series_registers_in_state(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        assert sh.state.series_by_id[s.rowid] is s

    def test_list_game_persists_as_joined_string(self):
        name = _unique("multi-game")
        s = sh.create_series(
            guild_id=1, name=name, season=1,
            game=["rps", "smash"], pinned_channel="c")
        row = db.load_entry("series", s.rowid)
        assert row[3] == "rps, smash"


class TestMultibracketPersistence:
    def test_create_multibracket_persists_and_returns_rowid(self):
        name = _unique("mb")
        m = sh.create_multibracket(name=name)
        assert m.rowid is not None
        row = db.load_entry("multibrackets", m.rowid)
        assert row is not None
        assert row[0] == name

    def test_create_multibracket_registers_in_state(self):
        m = sh.create_multibracket(name=_unique("mb"))
        assert sh.state.multibrackets_by_id[m.rowid] is m


# ---------------------------------------------------------------------------
# Scope→series mapping
# ---------------------------------------------------------------------------


class TestScopeToSeriesMapping:
    def test_set_and_get(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        sh.set_series_for_scope(guild_id=1, scope="channel-a", series=s)
        assert sh.get_series_for_scope(1, "channel-a") is s

    def test_missing_scope_returns_none(self):
        assert sh.get_series_for_scope(99, "nowhere") is None

    def test_overwrite(self):
        s1 = sh.create_series(1, _unique("s1"), 1, "rps", "ch")
        s2 = sh.create_series(1, _unique("s2"), 1, "rps", "ch")
        sh.set_series_for_scope(1, "channel-a", s1)
        sh.set_series_for_scope(1, "channel-a", s2)
        assert sh.get_series_for_scope(1, "channel-a") is s2

    def test_per_guild_isolation(self):
        s1 = sh.create_series(10, _unique("s"), 1, "rps", "ch")
        s2 = sh.create_series(20, _unique("s"), 1, "rps", "ch")
        sh.set_series_for_scope(10, "c", s1)
        sh.set_series_for_scope(20, "c", s2)
        assert sh.get_series_for_scope(10, "c") is s1
        assert sh.get_series_for_scope(20, "c") is s2


# ---------------------------------------------------------------------------
# Tournament + Series integration
# ---------------------------------------------------------------------------


class TestTournamentWithSeries:
    def test_no_series_defaults_to_none(self):
        t = Tournament(title="T", scope="s", seed=42)
        assert t.series_id is None
        assert t.multibracket_id is None
        assert t.series_ctr is None
        assert t.series is None

    def test_series_instance_derives_series_id(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        t = Tournament(title="T", scope="s", series=s, seed=42)
        assert t.series_id == s.rowid
        assert t.series is s

    def test_series_id_int_kwarg(self):
        t = Tournament(title="T", scope="s", series_id=12345, seed=42)
        assert t.series_id == 12345
        assert t.series is None

    def test_multibracket_id_kwarg(self):
        t = Tournament(title="T", scope="s",
                       multibracket_id=99, seed=42)
        assert t.multibracket_id == 99


# ---------------------------------------------------------------------------
# register_tournament + series_ctr
# ---------------------------------------------------------------------------


class TestRegisterTournament:
    def test_no_op_when_no_series_id(self):
        t = Tournament(title="T", scope="s", seed=42)
        result = sh.register_tournament(t)
        assert result is None
        assert t.series_ctr is None
        assert t.multibracket_id is None

    def test_inserts_tourneys_row(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        t = Tournament(title="T", scope="s", series=s, seed=42)
        rowid = sh.register_tournament(t, multibracket_id=None)
        assert rowid is not None
        row = db.load_entry("tourneys", rowid)
        assert row is not None
        # Columns: multibracket_id, series_id, series_ctr, timestamp
        assert row[0] is None
        assert row[1] == s.rowid
        assert row[2] == 1

    def test_inserts_with_multibracket(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        m = sh.create_multibracket(name=_unique("mb"))
        t = Tournament(title="T", scope="s", series=s, seed=42)
        rowid = sh.register_tournament(t, multibracket_id=m.rowid)
        row = db.load_entry("tourneys", rowid)
        assert row[0] == m.rowid
        assert row[1] == s.rowid

    def test_sets_tournament_series_ctr(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        t = Tournament(title="T", scope="s", series=s, seed=42)
        sh.register_tournament(t)
        assert t.series_ctr == 1

    def test_sets_tournament_multibracket_id(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        m = sh.create_multibracket(name=_unique("mb"))
        t = Tournament(title="T", scope="s", series=s, seed=42)
        sh.register_tournament(t, multibracket_id=m.rowid)
        assert t.multibracket_id == m.rowid


class TestSeriesCtrIncrementing:
    def test_first_episode_is_1(self):
        s = sh.create_series(1, _unique("series"), 1, "rps", "ch")
        assert sh.get_series_ctr(s.rowid) == 1

    def test_increments_across_episodes(self):
        s = sh.create_series(1, _unique("series"), 1, "rps", "ch")
        # Register 3 tournaments sequentially.
        ctrs = []
        for _ in range(3):
            t = Tournament(title=f"T", scope="s", series=s, seed=42)
            sh.register_tournament(t)
            ctrs.append(t.series_ctr)
        assert ctrs == [1, 2, 3]

    def test_independent_per_series(self):
        s1 = sh.create_series(1, _unique("s1"), 1, "rps", "ch")
        s2 = sh.create_series(1, _unique("s2"), 1, "rps", "ch")
        t1 = Tournament(title="T1", scope="s", series=s1, seed=42)
        sh.register_tournament(t1)
        t2 = Tournament(title="T2", scope="s", series=s2, seed=42)
        sh.register_tournament(t2)
        assert t1.series_ctr == 1
        assert t2.series_ctr == 1  # different series, independent counter
        t1b = Tournament(title="T1b", scope="s", series=s1, seed=42)
        sh.register_tournament(t1b)
        assert t1b.series_ctr == 2


# ---------------------------------------------------------------------------
# load_series + load_multibracket
# ---------------------------------------------------------------------------


class TestLoadFromDB:
    def test_load_series_roundtrip(self):
        name = _unique("load-s")
        original = sh.create_series(
            guild_id=42, name=name, season=3,
            game="rps", pinned_channel="ch1")
        sh.state.reset()  # clear in-memory cache
        loaded = sh.load_series(original.rowid)
        assert loaded is not None
        assert loaded.rowid == original.rowid
        assert loaded.guild_id == 42
        assert loaded.name == name
        assert loaded.season == 3
        assert loaded.game == "rps"
        assert loaded.pinned_channel == "ch1"

    def test_load_multibracket_roundtrip(self):
        name = _unique("load-mb")
        original = sh.create_multibracket(name=name)
        sh.state.reset()
        loaded = sh.load_multibracket(original.rowid)
        assert loaded is not None
        assert loaded.rowid == original.rowid
        assert loaded.name == name

    def test_load_series_missing_returns_none(self):
        result = sh.load_series(999999999)
        assert result is None

    def test_load_multibracket_missing_returns_none(self):
        result = sh.load_multibracket(999999999)
        assert result is None


# ---------------------------------------------------------------------------
# SeriesState.reset
# ---------------------------------------------------------------------------


class TestSeriesStateReset:
    def test_reset_clears_all_in_memory(self):
        s = sh.create_series(1, _unique("s"), 1, "rps", "ch")
        m = sh.create_multibracket(name=_unique("mb"))
        sh.set_series_for_scope(1, "c", s)
        assert sh.state.series_by_id
        assert sh.state.multibrackets_by_id
        assert sh.state.scope_to_series
        sh.state.reset()
        assert not sh.state.series_by_id
        assert not sh.state.multibrackets_by_id
        assert not sh.state.scope_to_series
