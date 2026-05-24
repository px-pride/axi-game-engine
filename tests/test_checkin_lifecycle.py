"""Phase 9 tests — Event check-in lifecycle (pure-layer handler + effects).

Tests cover the checkin_handler functions and the 5 new effect
dataclasses. Slash commands and the Discord adapter are NOT directly
tested (they require a Discord environment); the handler-level tests
verify the effect shapes that the adapter consumes.
"""

import pytest

from axi.effects import (
    AddReactorsToTournament,
    CollectReactors,
    CreateCheckinPost,
    EditScheduledEventDescription,
    MentionReactors,
    SendToChannel,
)
from axi.handlers import checkin_handler
from axi.ladder import Ladder
from axi.tournament import Tournament


# ---------------------------------------------------------------------------
# Effect dataclass shapes
# ---------------------------------------------------------------------------


class TestEffectShapes:
    def test_create_checkin_post(self):
        e = CreateCheckinPost(
            guild_id=1, channel_name="ch",
            header_image_path="path.png", message="msg",
            reaction_emoji="\N{THUMBS UP SIGN}", scope="scope")
        assert e.guild_id == 1
        assert e.reaction_emoji == "\N{THUMBS UP SIGN}"

    def test_collect_reactors(self):
        e = CollectReactors(guild_id=1, channel_name="ch", message_id=99)
        assert e.message_id == 99

    def test_add_reactors_to_tournament(self):
        e = AddReactorsToTournament(scope="ch", user_ids=[10, 20])
        assert e.user_ids == [10, 20]

    def test_mention_reactors(self):
        e = MentionReactors(guild_id=1, channel_name="ch",
                            user_ids=[10, 20])
        assert e.user_ids == [10, 20]
        assert e.message_prefix == ""
        assert e.message_suffix == ""

    def test_edit_scheduled_event_description(self):
        e = EditScheduledEventDescription(event_id=123, description="X")
        assert e.event_id == 123
        assert e.description == "X"


# ---------------------------------------------------------------------------
# checkins_post_id on Tournament + Ladder
# ---------------------------------------------------------------------------


class TestCheckinsPostIdField:
    def test_tournament_default_none(self):
        t = Tournament(title="T", scope="s", seed=42)
        assert t.checkins_post_id is None

    def test_tournament_settable(self):
        t = Tournament(title="T", scope="s", seed=42)
        t.checkins_post_id = 12345
        assert t.checkins_post_id == 12345

    def test_ladder_default_none(self):
        config = {
            "name": "n", "game": "rps", "format": "openskill",
            "queue-channel": "q", "status-channel": "s",
            "results-channel": "r", "leaderboard-channel": "l",
            "duration": "1h",
        }
        class FakeGuild:
            id = 1
        ladder = Ladder(FakeGuild(), config, scheduled_event=None,
                        duration_seconds=3600)
        assert ladder.checkins_post_id is None

    def test_ladder_settable(self):
        config = {
            "name": "n", "game": "rps", "format": "openskill",
            "queue-channel": "q", "status-channel": "s",
            "results-channel": "r", "leaderboard-channel": "l",
            "duration": "1h",
        }
        class FakeGuild:
            id = 1
        ladder = Ladder(FakeGuild(), config, scheduled_event=None,
                        duration_seconds=3600)
        ladder.checkins_post_id = 99
        assert ladder.checkins_post_id == 99


# ---------------------------------------------------------------------------
# create_checkins
# ---------------------------------------------------------------------------


class TestCreateCheckins:
    def test_emits_create_checkin_post(self):
        effects = checkin_handler.create_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            start_time=1700000000, signup_user_ids=[10, 20])
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, CreateCheckinPost)
        assert e.scope == "ch"
        assert e.guild_id == 99
        assert e.channel_name == "ch"
        assert e.reaction_emoji == "\N{THUMBS UP SIGN}"

    def test_message_includes_signup_mentions(self):
        effects = checkin_handler.create_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            start_time=1700000000, signup_user_ids=[10, 20])
        msg = effects[0].message
        assert "<@10>" in msg
        assert "<@20>" in msg
        assert ", and anyone else!" in msg

    def test_message_without_signups(self):
        effects = checkin_handler.create_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            start_time=1700000000, signup_user_ids=[])
        msg = effects[0].message
        # No "and anyone else" line, but still has the check-in instructions.
        assert "*Check in:* Just react to this post" in msg
        assert "<@" not in msg

    def test_message_includes_start_time(self):
        effects = checkin_handler.create_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            start_time=1700000000, signup_user_ids=[])
        msg = effects[0].message
        assert "*Ladder opens:*" in msg
        assert "PT." in msg


# ---------------------------------------------------------------------------
# final_reminder
# ---------------------------------------------------------------------------


class TestFinalReminder:
    def test_emits_mention_reactors_with_missing_set(self):
        effects = checkin_handler.final_reminder(
            scope="ch", guild_id=99, pinned_channel="ch",
            event_name="PXL",
            signup_user_ids=[1, 2, 3],
            checkin_user_ids=[1])
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, MentionReactors)
        assert set(e.user_ids) == {2, 3}

    def test_empty_diff_still_emits_reminder(self):
        effects = checkin_handler.final_reminder(
            scope="ch", guild_id=99, pinned_channel="ch",
            event_name="PXL",
            signup_user_ids=[1, 2],
            checkin_user_ids=[1, 2])
        e = effects[0]
        assert isinstance(e, MentionReactors)
        assert e.user_ids == []
        # The suffix message still mentions "minutes until the ladder opens".
        assert "minutes until the ladder opens" in e.message_suffix

    def test_attention_prefix(self):
        effects = checkin_handler.final_reminder(
            scope="ch", guild_id=99, pinned_channel="ch",
            event_name="PXL",
            signup_user_ids=[1, 2],
            checkin_user_ids=[])
        e = effects[0]
        assert "**ATTENTION:**" in e.message_prefix

    def test_event_name_in_suffix(self):
        effects = checkin_handler.final_reminder(
            scope="ch", guild_id=99, pinned_channel="ch",
            event_name="MyCoolEvent",
            signup_user_ids=[1],
            checkin_user_ids=[])
        assert "MyCoolEvent" in effects[0].message_suffix

    def test_custom_minutes(self):
        effects = checkin_handler.final_reminder(
            scope="ch", guild_id=99, pinned_channel="ch",
            event_name="X",
            signup_user_ids=[1],
            checkin_user_ids=[],
            minutes_until_open=10)
        assert "10 minutes" in effects[0].message_suffix


# ---------------------------------------------------------------------------
# list_checkins
# ---------------------------------------------------------------------------


class TestListCheckins:
    def test_emits_send_to_channel(self):
        effects = checkin_handler.list_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            checkin_user_ids=[10, 20])
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, SendToChannel)
        assert e.guild_id == 99
        assert e.channel_name == "ch"

    def test_lists_all_checkin_users(self):
        effects = checkin_handler.list_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            checkin_user_ids=[10, 20])
        msg = effects[0].messages[0][0]
        assert "<@10>" in msg
        assert "<@20>" in msg

    def test_empty_list(self):
        effects = checkin_handler.list_checkins(
            scope="ch", guild_id=99, pinned_channel="ch",
            checkin_user_ids=[])
        msg = effects[0].messages[0][0]
        assert "CHECKED IN:" in msg
        # No specific user mentions when list is empty.
        assert "<@" not in msg


# ---------------------------------------------------------------------------
# add_from_reacts
# ---------------------------------------------------------------------------


class TestAddFromReacts:
    def test_emits_add_reactors_to_tournament(self):
        effects = checkin_handler.add_from_reacts(
            scope="ch", reaction_user_ids=[1, 2, 3])
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, AddReactorsToTournament)
        assert e.scope == "ch"
        assert e.user_ids == [1, 2, 3]

    def test_empty_reactor_list(self):
        effects = checkin_handler.add_from_reacts(
            scope="ch", reaction_user_ids=[])
        assert isinstance(effects[0], AddReactorsToTournament)
        assert effects[0].user_ids == []


# ---------------------------------------------------------------------------
# mention_from_reacts
# ---------------------------------------------------------------------------


class TestMentionFromReacts:
    def test_emits_mention_reactors(self):
        effects = checkin_handler.mention_from_reacts(
            scope="ch", guild_id=99, channel_name="ch",
            reaction_user_ids=[1, 2])
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, MentionReactors)
        assert e.user_ids == [1, 2]


# ---------------------------------------------------------------------------
# begin_all_events
# ---------------------------------------------------------------------------


class TestBeginAllEvents:
    def test_emits_per_event_effects(self):
        events_info = [
            {
                "scope": "ch1",
                "event_id": 100,
                "tournament_title": "Ev1",
                "guild_id": 99,
                "channel_name": "ch1",
                "reactor_user_ids": [1, 2],
            },
        ]
        effects = checkin_handler.begin_all_events(events_info)
        # 3 effects per event: AddReactorsToTournament, EditScheduledEventDescription, SendToChannel.
        assert len(effects) == 3
        types = [type(e).__name__ for e in effects]
        assert "AddReactorsToTournament" in types
        assert "EditScheduledEventDescription" in types
        assert "SendToChannel" in types

    def test_multibracket_iterates_all(self):
        events_info = [
            {
                "scope": f"ch{i}",
                "event_id": 100 + i,
                "tournament_title": f"Ev{i}",
                "guild_id": 99,
                "channel_name": f"ch{i}",
                "reactor_user_ids": [],
            }
            for i in range(3)
        ]
        effects = checkin_handler.begin_all_events(events_info)
        # 3 events × 3 effects each = 9.
        assert len(effects) == 9

    def test_description_includes_queue_command(self):
        events_info = [{
            "scope": "ch",
            "event_id": 100,
            "tournament_title": "MyTourney",
            "guild_id": 99,
            "channel_name": "ch",
            "reactor_user_ids": [],
        }]
        effects = checkin_handler.begin_all_events(events_info)
        edit_effects = [e for e in effects
                        if isinstance(e, EditScheduledEventDescription)]
        assert edit_effects
        assert "THE LADDER HAS BEGUN!" in edit_effects[0].description
        assert "/queue MyTourney" in edit_effects[0].description


# ---------------------------------------------------------------------------
# edit_events_for_close
# ---------------------------------------------------------------------------


class TestEditEventsForClose:
    def test_emits_edit_per_event(self):
        events_info = [{"event_id": 100}, {"event_id": 200}]
        effects = checkin_handler.edit_events_for_close(events_info)
        assert len(effects) == 2
        for e in effects:
            assert isinstance(e, EditScheduledEventDescription)
            assert "CLOSED" in e.description


# ---------------------------------------------------------------------------
# clear_announcement
# ---------------------------------------------------------------------------


class TestClearAnnouncement:
    def test_emits_send_to_channel(self):
        effects = checkin_handler.clear_announcement(
            guild_id=99, announcement_channel="announcements")
        assert len(effects) == 1
        e = effects[0]
        assert isinstance(e, SendToChannel)
        assert e.channel_name == "announcements"
        msg = e.messages[0][0]
        assert "thanks" in msg.lower() or "over" in msg.lower()


# ---------------------------------------------------------------------------
# End-to-end simulated lifecycle (effect-emission only; no Discord)
# ---------------------------------------------------------------------------


class TestSimulatedLifecycle:
    def test_full_cycle_emits_expected_effects(self):
        """Simulates: create_checkins → final_reminder → add_from_reacts
        → begin_all_events → edit_events_for_close → clear_announcement.
        Verifies the right effect types flow through."""
        scope = "ch"
        guild_id = 99
        pinned = "ch"

        # 1. /createcheckins
        e1 = checkin_handler.create_checkins(
            scope=scope, guild_id=guild_id, pinned_channel=pinned,
            start_time=1700000000, signup_user_ids=[1, 2, 3])
        assert isinstance(e1[0], CreateCheckinPost)

        # 2. /checkinsreminder (signups [1,2,3], checkins [1] → missing [2,3])
        e2 = checkin_handler.final_reminder(
            scope=scope, guild_id=guild_id, pinned_channel=pinned,
            event_name="PXL", signup_user_ids=[1, 2, 3],
            checkin_user_ids=[1])
        assert isinstance(e2[0], MentionReactors)
        assert set(e2[0].user_ids) == {2, 3}

        # 3. /addfromreacts (reactors [1, 2, 3, 4])
        e3 = checkin_handler.add_from_reacts(
            scope=scope, reaction_user_ids=[1, 2, 3, 4])
        assert isinstance(e3[0], AddReactorsToTournament)
        assert e3[0].user_ids == [1, 2, 3, 4]

        # 4. /beginallevents
        e4 = checkin_handler.begin_all_events([{
            "scope": scope, "event_id": 50, "tournament_title": "PXL",
            "guild_id": guild_id, "channel_name": pinned,
            "reactor_user_ids": [1, 2, 3, 4],
        }])
        types4 = [type(e).__name__ for e in e4]
        assert "AddReactorsToTournament" in types4
        assert "EditScheduledEventDescription" in types4

        # 5. close
        e5 = checkin_handler.edit_events_for_close([{"event_id": 50}])
        assert isinstance(e5[0], EditScheduledEventDescription)
        assert "CLOSED" in e5[0].description

        # 6. clear_announcement
        e6 = checkin_handler.clear_announcement(
            guild_id=guild_id, announcement_channel="announcements")
        assert isinstance(e6[0], SendToChannel)
