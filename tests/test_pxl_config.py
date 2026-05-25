"""Phase 13 tests — PXL config parser.

Covers: 4 sample configs (single event, single-bracket series,
multi-bracket series, multi-bracket with FORMATS); $NAME/$EPISODE/$GAME
substitution; subsection override resolution; timedelta + datetime
parsing; comma-separated list parsing; nested-section flattening; and
end-to-end episode iteration with substitution applied.
"""

from datetime import datetime, timedelta

import pytest

from axi.pxl_config import (
    BracketSpec,
    EpisodeSpec,
    PxlConfig,
    PxlConfigError,
    parse_config,
    parse_datetime,
    parse_list,
    parse_timedelta,
    preprocess_ini,
    resolve_episode,
    substitute_vars,
)


# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------


SAMPLE_0 = """[EVENT]
NAME = Test Event
DESCRIPTION = This is a test for automating a single-bracket event.
CHANNEL = #test-bracket
DATE = 4/7/2023
TIME = 6:00 PM EST
DURATION = 30 minutes
IMAGE = C:/Downloads/main8.png

[ANNOUNCEMENTS]
CHANNEL = #announcements
INITIAL_DATE = 4/7/2023
INITIAL_TIME = 5:30 PM EST
FINAL_DATE = 4/7/2023
FINAL_TIME = 5:32 PM EST

[CHECKINS]
INITIAL_DATE = 4/7/2023
INITIAL_TIME = 5:30 PM EST
FINAL_DATE = 4/7/2023
FINAL_TIME = 5:32 PM EST
"""


SAMPLE_1 = """[SERIES]
NAME = Test Series
COUNT = 3
FREQUENCY = 30 minutes
FIRST_DATE = 4/7/2023
FIRST_TIME = 6:00 PM EST
DESCRIPTION = Welcome to Test Series #$EPISODE!
IMAGE = C:/Downloads/main8.png
GAME = nasb
EVENT_CHANNEL = #test-bracket
CHECKINS_INITIAL_OFFSET = 40 minutes
CHECKINS_FINAL_OFFSET = 5 minutes
ANNOUNCEMENT_CHANNEL = #announcements
ANNOUNCEMENT_INITIAL_OFFSET = 1 hour
ANNOUNCEMENT_FINAL_OFFSET = 50 minutes
"""


SAMPLE_2 = """[Testing Series]
GUILD_ID = 952094562317373510
COUNT = 1
FREQUENCY = 3 minutes
FIRST_DATE = 5/6/2023
FIRST_TIME = 12:25 PM
ANNOUNCEMENT_CHANNEL = announcements
ANNOUNCEMENT_INITIAL_IMAGE = D:/Pride_Axioms/AI/axi/discord_header_upcoming_rps.png
ANNOUNCEMENT_FINAL_IMAGE = D:/Pride_Axioms/AI/axi/discord_header_tonight_rps.png
ANNOUNCEMENT_INITIAL_OFFSET = 75 seconds
ANNOUNCEMENT_FINAL_OFFSET = 60 seconds
CHECKINS_INITIAL_OFFSET = 45 seconds
CHECKINS_FINAL_OFFSET = 15 seconds

    [[default]]
    TITLE = $NAME $EPISODE: $GAME
    DESCRIPTION = Welcome to $NAME #$EPISODE: $GAME!
    GAMES = rps
    ROLES = rps-tourney
    IMAGES = D:/Pride_Axioms/AI/axi/discord_event_cover_rps.png
    EVENT_CHANNELS = rps-bracket

    [[2]]
    GAMES = nasb, rivals
    ROLES = nick-tourney, rivals-tourney
    IMAGES = D:/Pride_Axioms/AI/axi/discord_event_cover_nick.png, D:/Pride_Axioms/AI/axi/discord_event_cover_rivals.png
    EVENT_CHANNELS = nick-bracket, rivals-bracket
"""


SAMPLE_3 = """[Testing Series]
GUILD_ID = 952094562317373510
COUNT = 2
FREQUENCY = 3 minutes
FIRST_DATE = 5/6/2023
FIRST_TIME = 12:25 PM
ANNOUNCEMENT_CHANNEL = announcements
ANNOUNCEMENT_INITIAL_IMAGE = D:/Pride_Axioms/AI/axi/discord_header_upcoming_rps.png
ANNOUNCEMENT_FINAL_IMAGE = D:/Pride_Axioms/AI/axi/discord_header_tonight_rps.png
ANNOUNCEMENT_INITIAL_OFFSET = 75 seconds
ANNOUNCEMENT_FINAL_OFFSET = 60 seconds
CHECKINS_INITIAL_OFFSET = 45 seconds
CHECKINS_FINAL_OFFSET = 15 seconds

    [[default]]
    TITLE = $NAME $EPISODE: $GAME
    DESCRIPTION = Welcome to $NAME #$EPISODE: $GAME!
    GAMES = rps
    ROLES = rps-tourney
    IMAGES = D:/Pride_Axioms/AI/axi/discord_event_cover_rps.png
    EVENT_CHANNELS = rps-bracket
    FORMATS = ladder-elim

    [[2]]
    GAMES = nasb, rivals
    ROLES = nick-tourney, rivals-tourney
    IMAGES = D:/Pride_Axioms/AI/axi/discord_event_cover_nick.png, D:/Pride_Axioms/AI/axi/discord_event_cover_rivals.png
    EVENT_CHANNELS = nick-bracket, rivals-bracket
    FORMATS = ladder-elim
"""


# ---------------------------------------------------------------------------
# parse_timedelta
# ---------------------------------------------------------------------------


class TestParseTimedelta:
    def test_minutes(self):
        assert parse_timedelta("30 minutes") == timedelta(minutes=30)

    def test_seconds(self):
        assert parse_timedelta("75 seconds") == timedelta(seconds=75)

    def test_hour(self):
        assert parse_timedelta("1 hour") == timedelta(hours=1)

    def test_days(self):
        assert parse_timedelta("2 days") == timedelta(days=2)

    def test_week(self):
        assert parse_timedelta("1 week") == timedelta(weeks=1)

    def test_compact(self):
        assert parse_timedelta("30m") == timedelta(minutes=30)

    def test_none(self):
        assert parse_timedelta(None) is None

    def test_empty(self):
        assert parse_timedelta("") is None

    def test_passthrough_timedelta(self):
        td = timedelta(seconds=42)
        assert parse_timedelta(td) is td

    def test_unparseable_raises(self):
        with pytest.raises(PxlConfigError):
            parse_timedelta("blue")


# ---------------------------------------------------------------------------
# parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:
    def test_basic(self):
        d = parse_datetime("4/7/2023", "6:00 PM")
        assert d == datetime(2023, 4, 7, 18, 0)

    def test_strips_tz(self):
        d = parse_datetime("4/7/2023", "6:00 PM EST")
        assert d == datetime(2023, 4, 7, 18, 0)

    def test_short_year(self):
        d = parse_datetime("4/7/23", "6:00 PM")
        assert d == datetime(2023, 4, 7, 18, 0)

    def test_24h(self):
        d = parse_datetime("5/6/2023", "12:25")
        assert d == datetime(2023, 5, 6, 12, 25)

    def test_none(self):
        assert parse_datetime(None, "6:00 PM") is None
        assert parse_datetime("4/7/2023", None) is None

    def test_unparseable_raises(self):
        with pytest.raises(PxlConfigError):
            parse_datetime("nope", "also nope")


# ---------------------------------------------------------------------------
# parse_list
# ---------------------------------------------------------------------------


class TestParseList:
    def test_single(self):
        assert parse_list("rps") == ["rps"]

    def test_multiple(self):
        assert parse_list("nasb, rivals") == ["nasb", "rivals"]

    def test_strips_whitespace(self):
        assert parse_list("a,  b ,c") == ["a", "b", "c"]

    def test_empty(self):
        assert parse_list("") == []
        assert parse_list(None) == []

    def test_passthrough_list(self):
        assert parse_list(["a", "b"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# substitute_vars
# ---------------------------------------------------------------------------


class TestSubstituteVars:
    def test_all_three(self):
        result = substitute_vars(
            "$NAME #$EPISODE: $GAME", "PXL", 3, "rps")
        assert result == "PXL #3: RPS"

    def test_uppercases_game(self):
        assert substitute_vars("$GAME", "x", 1, "nasb") == "NASB"

    def test_no_op_on_empty(self):
        assert substitute_vars("", "x", 1, "y") == ""
        assert substitute_vars(None, "x", 1, "y") is None

    def test_passthrough_no_tokens(self):
        assert substitute_vars("Hello, World", "x", 1, "y") == "Hello, World"


# ---------------------------------------------------------------------------
# resolve_episode
# ---------------------------------------------------------------------------


class TestResolveEpisode:
    def test_override_wins(self):
        d = {"A": "1", "B": "2"}
        o = {"A": "X"}
        merged = resolve_episode(d, o)
        assert merged == {"A": "X", "B": "2"}

    def test_override_only_keys(self):
        d = {"A": "1"}
        o = {"B": "2"}
        merged = resolve_episode(d, o)
        assert merged == {"A": "1", "B": "2"}

    def test_default_only(self):
        d = {"A": "1"}
        assert resolve_episode(d, None) == {"A": "1"}
        assert resolve_episode(d, {}) == {"A": "1"}


# ---------------------------------------------------------------------------
# preprocess_ini — [[X]] → [Section.X]
# ---------------------------------------------------------------------------


class TestPreprocessIni:
    def test_double_bracket_under_section(self):
        text = "[Series]\n    [[default]]\n    K = v\n"
        out = preprocess_ini(text)
        assert "[Series]" in out
        assert "[Series.default]" in out

    def test_no_subsections(self):
        text = "[EVENT]\nNAME = X\n"
        out = preprocess_ini(text)
        assert "[EVENT]" in out
        assert "NAME = X" in out


# ---------------------------------------------------------------------------
# parse_config — sample 0 (EVENT)
# ---------------------------------------------------------------------------


class TestParseSample0:
    def test_kind_event(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.kind == "EVENT"

    def test_name(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.name == "Test Event"

    def test_channel(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.channel == "test-bracket"

    def test_event_datetime(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.event_datetime == datetime(2023, 4, 7, 18, 0)

    def test_duration(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.duration == timedelta(minutes=30)

    def test_image(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.image == "C:/Downloads/main8.png"

    def test_announcement_channel_from_sibling(self):
        cfg = parse_config(SAMPLE_0)
        assert cfg.announcement_channel == "announcements"

    def test_announcement_offset(self):
        cfg = parse_config(SAMPLE_0)
        # event = 18:00, initial = 17:30 → 30-minute offset.
        assert cfg.announcement_initial_offset == timedelta(minutes=30)

    def test_iter_yields_one_episode(self):
        cfg = parse_config(SAMPLE_0)
        eps = list(cfg.iter_episodes())
        assert len(eps) == 1
        assert eps[0].episode_index == 1
        assert eps[0].start_time == datetime(2023, 4, 7, 18, 0)
        assert len(eps[0].brackets) == 1


# ---------------------------------------------------------------------------
# parse_config — sample 1 (SERIES)
# ---------------------------------------------------------------------------


class TestParseSample1:
    def test_kind_series(self):
        cfg = parse_config(SAMPLE_1)
        assert cfg.kind == "SERIES"

    def test_count(self):
        cfg = parse_config(SAMPLE_1)
        assert cfg.count == 3

    def test_frequency(self):
        cfg = parse_config(SAMPLE_1)
        assert cfg.frequency == timedelta(minutes=30)

    def test_first_datetime(self):
        cfg = parse_config(SAMPLE_1)
        assert cfg.first_datetime == datetime(2023, 4, 7, 18, 0)

    def test_announcement_offset(self):
        cfg = parse_config(SAMPLE_1)
        assert cfg.announcement_initial_offset == timedelta(hours=1)
        assert cfg.announcement_final_offset == timedelta(minutes=50)

    def test_checkins_offset(self):
        cfg = parse_config(SAMPLE_1)
        assert cfg.checkins_initial_offset == timedelta(minutes=40)
        assert cfg.checkins_final_offset == timedelta(minutes=5)

    def test_iter_three_episodes(self):
        cfg = parse_config(SAMPLE_1)
        eps = list(cfg.iter_episodes())
        assert len(eps) == 3
        # Spaced by 30 minutes.
        assert eps[0].start_time == datetime(2023, 4, 7, 18, 0)
        assert eps[1].start_time == datetime(2023, 4, 7, 18, 30)
        assert eps[2].start_time == datetime(2023, 4, 7, 19, 0)

    def test_iter_substitutes_episode(self):
        cfg = parse_config(SAMPLE_1)
        eps = list(cfg.iter_episodes())
        # DESCRIPTION = "Welcome to Test Series #$EPISODE!"
        assert "Welcome to Test Series #2!" in eps[1].brackets[0].description

    def test_iter_single_bracket_per_episode(self):
        cfg = parse_config(SAMPLE_1)
        for ep in cfg.iter_episodes():
            assert len(ep.brackets) == 1
            assert ep.brackets[0].game == "nasb"


# ---------------------------------------------------------------------------
# parse_config — sample 2 (MULTI)
# ---------------------------------------------------------------------------


class TestParseSample2:
    def test_kind_multi(self):
        cfg = parse_config(SAMPLE_2)
        assert cfg.kind == "MULTI"

    def test_name(self):
        cfg = parse_config(SAMPLE_2)
        assert cfg.name == "Testing Series"

    def test_guild_id(self):
        cfg = parse_config(SAMPLE_2)
        assert cfg.guild_id == 952094562317373510

    def test_default_subsection_loaded(self):
        cfg = parse_config(SAMPLE_2)
        assert cfg.default["GAMES"] == "rps"
        assert cfg.default["ROLES"] == "rps-tourney"

    def test_override_2_loaded(self):
        cfg = parse_config(SAMPLE_2)
        assert 2 in cfg.overrides
        assert cfg.overrides[2]["GAMES"] == "nasb, rivals"

    def test_iter_episode_1_uses_default(self):
        cfg = parse_config(SAMPLE_2)
        eps = list(cfg.iter_episodes())
        assert len(eps) == 1   # COUNT = 1
        ep1 = eps[0]
        assert len(ep1.brackets) == 1
        # Default GAMES = rps → one bracket.
        assert ep1.brackets[0].game == "rps"

    def test_iter_substitutes_title(self):
        cfg = parse_config(SAMPLE_2)
        ep1 = list(cfg.iter_episodes())[0]
        # TITLE = "$NAME $EPISODE: $GAME"
        assert ep1.brackets[0].title == "Testing Series 1: RPS"

    def test_offsets_parsed(self):
        cfg = parse_config(SAMPLE_2)
        assert cfg.announcement_initial_offset == timedelta(seconds=75)
        assert cfg.checkins_initial_offset == timedelta(seconds=45)


# ---------------------------------------------------------------------------
# parse_config — sample 3 (MULTI with FORMATS)
# ---------------------------------------------------------------------------


class TestParseSample3:
    def test_parses_without_crash(self):
        cfg = parse_config(SAMPLE_3)
        assert cfg.kind == "MULTI"

    def test_default_format(self):
        cfg = parse_config(SAMPLE_3)
        assert cfg.default["FORMATS"] == "ladder-elim"

    def test_iter_episode_1_format(self):
        cfg = parse_config(SAMPLE_3)
        ep1 = list(cfg.iter_episodes())[0]
        assert ep1.brackets[0].format == "ladder-elim"

    def test_iter_episode_2_uses_override(self):
        cfg = parse_config(SAMPLE_3)
        eps = list(cfg.iter_episodes())
        ep2 = eps[1]
        # Override [[2]] has GAMES = nasb, rivals → 2 brackets.
        assert len(ep2.brackets) == 2
        games = {b.game for b in ep2.brackets}
        assert games == {"nasb", "rivals"}

    def test_iter_episode_2_title_substituted_per_game(self):
        cfg = parse_config(SAMPLE_3)
        ep2 = list(cfg.iter_episodes())[1]
        titles = {b.title for b in ep2.brackets}
        assert "Testing Series 2: NASB" in titles
        assert "Testing Series 2: RIVALS" in titles

    def test_iter_episode_2_event_channels_paired(self):
        cfg = parse_config(SAMPLE_3)
        ep2 = list(cfg.iter_episodes())[1]
        # Brackets are emitted in the order GAMES are listed.
        # `nasb, rivals` → ["nick-bracket", "rivals-bracket"].
        for b in ep2.brackets:
            if b.game == "nasb":
                assert b.event_channel == "nick-bracket"
            elif b.game == "rivals":
                assert b.event_channel == "rivals-bracket"


# ---------------------------------------------------------------------------
# Episode iteration general invariants
# ---------------------------------------------------------------------------


class TestEpisodeIteration:
    def test_episode_indices_are_1based(self):
        cfg = parse_config(SAMPLE_1)
        eps = list(cfg.iter_episodes())
        assert [e.episode_index for e in eps] == [1, 2, 3]

    def test_episodes_spaced_by_frequency(self):
        cfg = parse_config(SAMPLE_1)
        eps = list(cfg.iter_episodes())
        deltas = [(eps[i+1].start_time - eps[i].start_time)
                  for i in range(len(eps)-1)]
        assert all(d == timedelta(minutes=30) for d in deltas)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestParserErrors:
    def test_empty_input_raises(self):
        with pytest.raises(PxlConfigError):
            parse_config("")

    def test_unparseable_offset_raises(self):
        text = """[SERIES]
NAME = X
COUNT = 1
FIRST_DATE = 1/1/2023
FIRST_TIME = 12:00 PM
ANNOUNCEMENT_INITIAL_OFFSET = nonsense
"""
        with pytest.raises(PxlConfigError):
            parse_config(text)


# ---------------------------------------------------------------------------
# Absolute fire-time computation (offset applied to start_time)
# ---------------------------------------------------------------------------


class TestAbsoluteFireTimes:
    """The slash command computes fire times as start_time - offset.
    These tests verify the math is well-defined when both pieces come
    from the parser."""

    def test_initial_announcement_fire_time(self):
        cfg = parse_config(SAMPLE_1)
        ep1 = list(cfg.iter_episodes())[0]
        # First episode: 4/7/2023 6:00 PM minus 1 hour = 5:00 PM.
        fire_at = ep1.start_time - cfg.announcement_initial_offset
        assert fire_at == datetime(2023, 4, 7, 17, 0)

    def test_final_announcement_fire_time(self):
        cfg = parse_config(SAMPLE_1)
        ep1 = list(cfg.iter_episodes())[0]
        # 18:00 - 50min = 17:10.
        fire_at = ep1.start_time - cfg.announcement_final_offset
        assert fire_at == datetime(2023, 4, 7, 17, 10)

    def test_checkins_initial_fire_time(self):
        cfg = parse_config(SAMPLE_1)
        ep1 = list(cfg.iter_episodes())[0]
        # 18:00 - 40min = 17:20.
        fire_at = ep1.start_time - cfg.checkins_initial_offset
        assert fire_at == datetime(2023, 4, 7, 17, 20)

    def test_checkins_final_fire_time(self):
        cfg = parse_config(SAMPLE_1)
        ep1 = list(cfg.iter_episodes())[0]
        # 18:00 - 5min = 17:55.
        fire_at = ep1.start_time - cfg.checkins_final_offset
        assert fire_at == datetime(2023, 4, 7, 17, 55)

    def test_seconds_precision(self):
        """SAMPLE_2 uses sub-minute offsets."""
        cfg = parse_config(SAMPLE_2)
        ep1 = list(cfg.iter_episodes())[0]
        # 12:25 - 75s = 12:23:45.
        fire_at = ep1.start_time - cfg.announcement_initial_offset
        assert fire_at == datetime(2023, 5, 6, 12, 23, 45)


# ---------------------------------------------------------------------------
# pxl_handler callbacks — pure effect emission
# ---------------------------------------------------------------------------


class TestPxlHandlerCallbacks:
    """The 6 PXL lifecycle callbacks should return lists of effects
    without touching Discord directly."""

    def test_initial_announcement_emits_send_to_channel(self):
        from axi.handlers import pxl_handler
        from axi.effects import SendToChannel
        effects = pxl_handler.pxl_initial_announcement(
            guild_id=99, channel="#announcements",
            message="Upcoming event!", image_path="/tmp/up.png")
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, SendToChannel)
        assert e.guild_id == 99
        # Hash stripped.
        assert e.channel_name == "announcements"

    def test_final_announcement_strips_hash(self):
        from axi.handlers import pxl_handler
        from axi.effects import SendToChannel
        effects = pxl_handler.pxl_final_announcement(
            guild_id=99, channel="announcements", message="Tonight!")
        assert isinstance(effects[0], SendToChannel)
        assert effects[0].channel_name == "announcements"

    def test_create_checkins_delegates_to_checkin_handler(self):
        from axi.handlers import pxl_handler
        from axi.effects import CreateCheckinPost
        effects = pxl_handler.pxl_create_checkins(
            guild_id=99, scope="RPS-BRACKET",
            pinned_channel="rps-bracket",
            start_timestamp=1234567890.0,
            signup_user_ids=[1001, 1002])
        # checkin_handler.create_checkins returns [CreateCheckinPost].
        assert len(effects) == 1
        assert isinstance(effects[0], CreateCheckinPost)
        assert effects[0].scope == "RPS-BRACKET"

    def test_final_reminder_delegates_to_checkin_handler(self):
        from axi.handlers import pxl_handler
        from axi.effects import MentionReactors
        effects = pxl_handler.pxl_final_checkins_reminder(
            guild_id=99, scope="RPS", pinned_channel="rps-bracket",
            event_name="Test Series 1: RPS",
            signup_user_ids=[1001, 1002],
            checkin_user_ids=[1001],   # 1002 missed check-in
            minutes_until_open=5)
        assert len(effects) == 1
        assert isinstance(effects[0], MentionReactors)
        # 1002 is the missing user.
        assert 1002 in effects[0].user_ids

    def test_begin_event_delegates_to_checkin_handler(self):
        from axi.handlers import pxl_handler
        from axi.effects import (
            AddReactorsToTournament,
            EditScheduledEventDescription,
            SendToChannel,
        )
        events_info = [{
            "scope": "RPS",
            "event_id": 12345,
            "tournament_title": "Test Series 1: RPS",
            "guild_id": 99,
            "channel_name": "rps-bracket",
            "reactor_user_ids": [1001, 1002],
        }]
        effects = pxl_handler.pxl_begin_event(events_info)
        types = {type(e).__name__ for e in effects}
        assert "AddReactorsToTournament" in types
        assert "EditScheduledEventDescription" in types
        assert "SendToChannel" in types

    def test_create_event_emits_send_to_channel(self):
        from axi.handlers import pxl_handler
        from axi.effects import SendToChannel
        effects = pxl_handler.pxl_create_event(
            guild_id=99, title="Test Series 1: RPS",
            description="Welcome to Test Series #1!",
            image_path="/tmp/rps.png",
            start_timestamp=1234567890.0,
            event_channel="rps-bracket")
        assert len(effects) == 1
        assert isinstance(effects[0], SendToChannel)
        assert "Test Series 1: RPS" in effects[0].messages[0][0]

    def test_all_six_callbacks_registered(self):
        from axi.handlers import pxl_handler  # noqa
        from axi.handlers import schedule_handler
        names = schedule_handler._list_registered_callbacks()
        expected = {
            "pxl_initial_announcement",
            "pxl_final_announcement",
            "pxl_create_event",
            "pxl_create_checkins",
            "pxl_final_checkins_reminder",
            "pxl_begin_event",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# Real sample files on disk (if present in tourney-inspect)
# ---------------------------------------------------------------------------


import os


SAMPLE_DIR = "/tmp/claude-1001/tourney-inspect"


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(SAMPLE_DIR, "pxl_sample_config_0.ini")),
    reason="Source sample configs not available in this environment.")
class TestRealSampleFiles:
    def test_sample_0(self):
        cfg = parse_config(os.path.join(SAMPLE_DIR, "pxl_sample_config_0.ini"))
        assert cfg.kind == "EVENT"

    def test_sample_1(self):
        cfg = parse_config(os.path.join(SAMPLE_DIR, "pxl_sample_config_1.ini"))
        assert cfg.kind == "SERIES"

    def test_sample_2(self):
        cfg = parse_config(os.path.join(SAMPLE_DIR, "pxl_sample_config_2.ini"))
        assert cfg.kind == "MULTI"

    def test_sample_3(self):
        cfg = parse_config(os.path.join(SAMPLE_DIR, "pxl_sample_config_3.ini"))
        assert cfg.kind == "MULTI"
