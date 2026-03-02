"""Tests for match_handler pure functions — the core of the effects system.

Every test calls sync pure functions and asserts on returned effect lists.
No Discord connection, no mocks of business logic, no async."""

import axi.registry as registry
import axi.handlers.match_handler as mh
from axi.effects import (
    SendUserMessages, SendToThread, SendToChannel,
    PresentDecision, CreateMatchThread, ArchiveThread,
    UpdateLadderUI,
)
from axi.thread_game import ThreadGame
from conftest import FakeUser, FakeLadder, THREAD_GAME_INFO

# RPS emoji constants (same as in rock_paper_scissors.py)
ROCK = "\N{ROCK}"
SCROLL = "\N{SCROLL}"
SCISSORS = "\N{BLACK SCISSORS}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _launch_rps(p1, p2):
    """Launch an RPS match and return (match, prepare_effects)."""
    match = mh.launch_match("rps", [p1, p2])
    effects = mh.prepare_match_ux(match, "rps")
    return match, effects


def _effects_of_type(effects, cls):
    """Filter effects by type."""
    return [e for e in effects if isinstance(e, cls)]


# ---------------------------------------------------------------------------
# launch_match
# ---------------------------------------------------------------------------

class TestLaunchMatch:

    def test_dm_game_creates_match(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        assert match is not None
        assert p1 in match.players
        assert p2 in match.players

    def test_dm_game_registers_players(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        assert mh.state.users_to_dm_matches[p1] is match
        assert mh.state.users_to_dm_matches[p2] is match

    def test_dm_game_in_matches_by_id(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        assert mh.state.matches_by_id[id(match)] is match

    def test_dm_game_initializes_state(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        assert hasattr(match, 'scores')
        assert hasattr(match, 'decisions')
        assert match.decisions[p1] is None
        assert match.decisions[p2] is None

    def test_invalid_game_returns_none(self, p1, p2):
        match = mh.launch_match("nonexistent", [p1, p2])
        assert match is None

    def test_invalid_mode_returns_none(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2], mode="invalid_mode")
        assert match is None

    def test_thread_game_creates_match(self, p1, p2):
        match = mh.launch_match("test_thread_game", [p1, p2])
        assert match is not None
        assert isinstance(match, ThreadGame)

    def test_thread_game_registers_players(self, p1, p2):
        match = mh.launch_match("test_thread_game", [p1, p2])
        assert mh.state.users_to_thread_matches[p1] is match
        assert mh.state.users_to_thread_matches[p2] is match


# ---------------------------------------------------------------------------
# prepare_match_ux
# ---------------------------------------------------------------------------

class TestPrepareMatchUx:

    def test_dm_game_presents_decisions(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        effects = mh.prepare_match_ux(match, "rps")
        presents = _effects_of_type(effects, PresentDecision)
        assert len(presents) == 2

    def test_dm_game_present_has_correct_user_ids(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        effects = mh.prepare_match_ux(match, "rps")
        presents = _effects_of_type(effects, PresentDecision)
        user_ids = {e.user_id for e in presents}
        assert user_ids == {p1.uid.id, p2.uid.id}

    def test_dm_game_present_has_match_id(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        effects = mh.prepare_match_ux(match, "rps")
        presents = _effects_of_type(effects, PresentDecision)
        for e in presents:
            assert e.match_id == id(match)

    def test_dm_game_present_has_options(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        effects = mh.prepare_match_ux(match, "rps")
        presents = _effects_of_type(effects, PresentDecision)
        for e in presents:
            assert set(e.options) == {ROCK, SCROLL, SCISSORS}

    def test_dm_game_present_has_init_messages(self, p1, p2):
        match = mh.launch_match("rps", [p1, p2])
        effects = mh.prepare_match_ux(match, "rps")
        presents = _effects_of_type(effects, PresentDecision)
        for e in presents:
            assert len(e.messages) > 0
            text = e.messages[0][0]
            assert "RPS" in text
            assert "Round 1" in text

    def test_thread_game_creates_thread(self, p1, p2):
        match = mh.launch_match("test_thread_game", [p1, p2])
        effects = mh.prepare_match_ux(
            match, "test_thread_game",
            channel_name="queue-ch", guild_id=99)
        threads = _effects_of_type(effects, CreateMatchThread)
        assert len(threads) == 1

    def test_thread_game_thread_has_correct_fields(self, p1, p2):
        match = mh.launch_match("test_thread_game", [p1, p2])
        effects = mh.prepare_match_ux(
            match, "test_thread_game",
            channel_name="queue-ch", guild_id=99,
            stream_notice="Stream!", launch_message="Go!")
        t = _effects_of_type(effects, CreateMatchThread)[0]
        assert t.guild_id == 99
        assert t.channel_name == "queue-ch"
        assert t.stream_notice == "Stream!"
        assert t.launch_message == "Go!"
        assert "Alice" in t.thread_name and "Bob" in t.thread_name

    def test_no_effects_after_prepare(self, p1, p2):
        """Message queues should be drained after prepare_match_ux."""
        match = mh.launch_match("rps", [p1, p2])
        mh.prepare_match_ux(match, "rps")
        assert match.flush_message_queue(p1) == []
        assert match.flush_message_queue(p2) == []


# ---------------------------------------------------------------------------
# process_decision
# ---------------------------------------------------------------------------

class TestProcessDecision:

    def test_single_player_decision_returns_feedback(self, p1, p2):
        match, _ = _launch_rps(p1, p2)
        effects = mh.process_decision(p1, ROCK)
        sends = _effects_of_type(effects, SendUserMessages)
        assert len(sends) == 1
        assert sends[0].user_id == p1.uid.id
        assert "[Secret]" in sends[0].messages[0][0]

    def test_single_player_decision_no_round(self, p1, p2):
        """Only one player decided — no round processing yet."""
        match, _ = _launch_rps(p1, p2)
        effects = mh.process_decision(p1, ROCK)
        presents = _effects_of_type(effects, PresentDecision)
        assert len(presents) == 0

    def test_both_players_triggers_round(self, p1, p2):
        """When both decide, a new round of PresentDecisions should appear."""
        match, _ = _launch_rps(p1, p2)
        mh.process_decision(p1, ROCK)
        effects = mh.process_decision(p2, SCISSORS)
        presents = _effects_of_type(effects, PresentDecision)
        # Round resolves → new decisions presented to both players
        assert len(presents) == 2

    def test_invalid_emoji_rejected(self, p1, p2):
        """Invalid emoji is rejected; feedback contains error message."""
        match, _ = _launch_rps(p1, p2)
        effects = mh.process_decision(p1, "invalid_emoji")
        sends = _effects_of_type(effects, SendUserMessages)
        assert len(sends) == 1
        assert "Illegal" in sends[0].messages[0][0]

    def test_invalid_emoji_does_not_count(self, p1, p2):
        """After invalid emoji, player can still make a valid choice."""
        match, _ = _launch_rps(p1, p2)
        mh.process_decision(p1, "invalid")  # rejected
        effects = mh.process_decision(p1, ROCK)  # valid
        sends = _effects_of_type(effects, SendUserMessages)
        assert any("[Secret]" in s.messages[0][0] for s in sends)

    def test_duplicate_decision_rejected(self, p1, p2):
        """Player can't decide twice in the same round."""
        match, _ = _launch_rps(p1, p2)
        mh.process_decision(p1, ROCK)  # accepted
        effects = mh.process_decision(p1, SCISSORS)  # rejected (already committed)
        sends = _effects_of_type(effects, SendUserMessages)
        assert len(sends) == 1
        assert "already committed" in sends[0].messages[0][0]

    def test_unknown_user_returns_empty(self):
        """Process decision for a user not in any match → empty effects."""
        stranger = FakeUser("Stranger", 9999)
        effects = mh.process_decision(stranger, ROCK)
        assert effects == []


# ---------------------------------------------------------------------------
# abort
# ---------------------------------------------------------------------------

class TestAbort:

    def test_abort_cleans_up_player(self, p1, p2):
        match, _ = _launch_rps(p1, p2)
        mh.process_decision(p1, "abort")
        assert p1 not in mh.state.users_to_dm_matches

    def test_abort_one_player_winner_is_other(self, p1, p2):
        """One player aborts → the other player wins."""
        match, _ = _launch_rps(p1, p2)
        mh.process_decision(p1, "abort")
        mh.process_decision(p2, ROCK)  # p2 makes any decision
        # After both decisions are in and match is over, close_match runs
        assert match.winner() == p2

    def test_both_abort_closes_match(self, p1, p2):
        match, _ = _launch_rps(p1, p2)
        mh.process_decision(p1, "abort")
        effects = mh.process_decision(p2, "abort")
        # Match is over → close_match effects
        sends = _effects_of_type(effects, SendUserMessages)
        assert len(sends) > 0
        assert p1 not in mh.state.users_to_dm_matches
        assert p2 not in mh.state.users_to_dm_matches


# ---------------------------------------------------------------------------
# close_match / cancel_match (DM game)
# ---------------------------------------------------------------------------

class TestCloseAndCancelDm:

    def _play_to_completion(self, p1, p2):
        """Play 3 rounds of ROCK vs SCISSORS (p1 wins each)."""
        match, _ = _launch_rps(p1, p2)
        for _ in range(3):
            mh.process_decision(p1, ROCK)
            effects = mh.process_decision(p2, SCISSORS)
        return match, effects

    def test_close_match_cleans_up_registrations(self, p1, p2):
        self._play_to_completion(p1, p2)
        assert p1 not in mh.state.users_to_dm_matches
        assert p2 not in mh.state.users_to_dm_matches

    def test_close_match_sends_game_over_messages(self, p1, p2):
        match, effects = self._play_to_completion(p1, p2)
        sends = _effects_of_type(effects, SendUserMessages)
        texts = " ".join(m[0] for s in sends for m in s.messages)
        assert "winner" in texts.lower()

    def test_close_match_no_ladder_no_update_ui(self, p1, p2):
        match, effects = self._play_to_completion(p1, p2)
        updates = _effects_of_type(effects, UpdateLadderUI)
        assert len(updates) == 0

    def test_cancel_match_cleans_up(self, p1, p2):
        match, _ = _launch_rps(p1, p2)
        effects = mh.cancel_match(match)
        assert p1 not in mh.state.users_to_dm_matches
        assert p2 not in mh.state.users_to_dm_matches

    def test_cancel_dm_no_archive_thread(self, p1, p2):
        """DM games don't have threads to archive."""
        match, _ = _launch_rps(p1, p2)
        effects = mh.cancel_match(match)
        archives = _effects_of_type(effects, ArchiveThread)
        assert len(archives) == 0


# ---------------------------------------------------------------------------
# close_match / cancel_match (thread game)
# ---------------------------------------------------------------------------

class TestCloseAndCancelThread:

    def _make_thread_match(self, p1, p2, ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=ladder)
        return match

    def test_close_thread_archives(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        match.report_winner(p1, p1)
        match.report_winner(p2, p1)
        assert match.check_match_over()
        effects = mh.close_match(match)
        archives = _effects_of_type(effects, ArchiveThread)
        assert len(archives) == 1
        assert archives[0].match_id == id(match)

    def test_close_thread_posts_result(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        match.report_winner(p1, p1)
        match.report_winner(p2, p1)
        effects = mh.close_match(match)
        channel_sends = _effects_of_type(effects, SendToChannel)
        assert len(channel_sends) == 1
        assert channel_sends[0].guild_id == 99
        assert channel_sends[0].channel_name == "results"
        assert "Alice" in channel_sends[0].messages[0][0]

    def test_close_thread_with_ladder_updates_ui(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        match.report_winner(p1, p1)
        match.report_winner(p2, p1)
        effects = mh.close_match(match)
        updates = _effects_of_type(effects, UpdateLadderUI)
        assert len(updates) == 1

    def test_close_thread_cleans_up_registrations(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        match.report_winner(p1, p1)
        match.report_winner(p2, p1)
        mh.close_match(match)
        assert p1 not in mh.state.users_to_thread_matches
        assert p2 not in mh.state.users_to_thread_matches

    def test_cancel_thread_archives(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        effects = mh.cancel_match(match)
        archives = _effects_of_type(effects, ArchiveThread)
        assert len(archives) == 1

    def test_cancel_thread_with_ladder_updates_ui(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        effects = mh.cancel_match(match)
        updates = _effects_of_type(effects, UpdateLadderUI)
        assert len(updates) == 1

    def test_cancel_thread_cleans_up(self, p1, p2, fake_ladder):
        match = self._make_thread_match(p1, p2, fake_ladder)
        mh.cancel_match(match)
        assert p1 not in mh.state.users_to_thread_matches
        assert p2 not in mh.state.users_to_thread_matches


# ---------------------------------------------------------------------------
# resolve_checkins
# ---------------------------------------------------------------------------

class TestResolveCheckins:

    def test_all_checked_in_empty_effects(self, p1, p2, fake_ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=fake_ladder)
        match.checkin_user(p1)
        match.checkin_user(p2)
        effects = mh.resolve_checkins(match)
        assert effects == []

    def test_missing_checkin_sends_timeout(self, p1, p2, fake_ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=fake_ladder)
        match.checkin_user(p1)
        # p2 has NOT checked in
        effects = mh.resolve_checkins(match)
        thread_sends = _effects_of_type(effects, SendToThread)
        assert len(thread_sends) == 1
        assert "expired" in thread_sends[0].messages[0][0].lower()

    def test_missing_checkin_cancels_match(self, p1, p2, fake_ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=fake_ladder)
        match.checkin_user(p1)
        effects = mh.resolve_checkins(match)
        archives = _effects_of_type(effects, ArchiveThread)
        assert len(archives) == 1

    def test_dm_game_checkin_no_op(self, p1, p2):
        """resolve_checkins is a no-op for DM games (checkins are automatic)."""
        match, _ = _launch_rps(p1, p2)
        effects = mh.resolve_checkins(match)
        assert effects == []


# ---------------------------------------------------------------------------
# process_command
# ---------------------------------------------------------------------------

class TestProcessCommand:

    def test_unrecognized_command_empty_effects(self, p1, p2):
        """RPS doesn't recognize any commands → empty effects."""
        match, _ = _launch_rps(p1, p2)
        effects = mh.process_command(p1, "some_command")
        assert effects == []

    def test_unknown_user_empty_effects(self):
        stranger = FakeUser("Stranger", 9999)
        effects = mh.process_command(stranger, "test")
        assert effects == []


# ---------------------------------------------------------------------------
# Full game flow
# ---------------------------------------------------------------------------

class TestFullRpsGame:

    def test_three_round_game(self, p1, p2):
        """Play a full RPS game: 3 rounds of ROCK vs SCISSORS.
        P1 wins every round → p1 wins the match."""
        # --- Launch ---
        match = mh.launch_match("rps", [p1, p2])
        assert match is not None
        ux_effects = mh.prepare_match_ux(match, "rps")
        presents = _effects_of_type(ux_effects, PresentDecision)
        assert len(presents) == 2

        # --- Round 1 ---
        e1 = mh.process_decision(p1, ROCK)
        assert _effects_of_type(e1, PresentDecision) == []  # waiting for p2

        e2 = mh.process_decision(p2, SCISSORS)
        r1_presents = _effects_of_type(e2, PresentDecision)
        assert len(r1_presents) == 2  # new round presented
        assert match.scores[p1] == 1
        assert match.scores[p2] == 0

        # --- Round 2 ---
        mh.process_decision(p1, ROCK)
        e3 = mh.process_decision(p2, SCISSORS)
        r2_presents = _effects_of_type(e3, PresentDecision)
        assert len(r2_presents) == 2
        assert match.scores[p1] == 2

        # --- Round 3 (winning round) ---
        mh.process_decision(p1, ROCK)
        e4 = mh.process_decision(p2, SCISSORS)
        assert match.scores[p1] == 3
        assert match.winner() == p1

        # Should NOT have PresentDecision (game is over)
        r3_presents = _effects_of_type(e4, PresentDecision)
        assert len(r3_presents) == 0

        # Should have game-over SendUserMessages
        sends = _effects_of_type(e4, SendUserMessages)
        all_text = " ".join(m[0] for s in sends for m in s.messages)
        assert "winner" in all_text.lower()

        # Players should be cleaned up
        assert p1 not in mh.state.users_to_dm_matches
        assert p2 not in mh.state.users_to_dm_matches

    def test_tie_round_continues(self, p1, p2):
        """When both players pick the same option, the round ties
        and new decisions are presented."""
        match, _ = _launch_rps(p1, p2)

        mh.process_decision(p1, ROCK)
        effects = mh.process_decision(p2, ROCK)

        # Tie → no score change, new round
        assert match.scores[p1] == 0
        assert match.scores[p2] == 0
        presents = _effects_of_type(effects, PresentDecision)
        assert len(presents) == 2

    def test_p2_wins(self, p1, p2):
        """P2 wins by choosing SCROLL (paper) vs P1's ROCK."""
        match, _ = _launch_rps(p1, p2)
        for _ in range(3):
            mh.process_decision(p1, ROCK)
            mh.process_decision(p2, SCROLL)
        assert match.winner() == p2
        assert p1 not in mh.state.users_to_dm_matches


# ---------------------------------------------------------------------------
# Effect type correctness
# ---------------------------------------------------------------------------

class TestEffectTypes:

    def test_present_decision_is_dataclass(self, p1, p2):
        match, effects = _launch_rps(p1, p2)
        presents = _effects_of_type(effects, PresentDecision)
        e = presents[0]
        assert hasattr(e, 'user_id')
        assert hasattr(e, 'match_id')
        assert hasattr(e, 'messages')
        assert hasattr(e, 'options')

    def test_create_match_thread_fields(self, p1, p2):
        match = mh.launch_match("test_thread_game", [p1, p2])
        effects = mh.prepare_match_ux(
            match, "test_thread_game",
            channel_name="ch", guild_id=42,
            stream_notice="STREAM", launch_message="GO")
        t = _effects_of_type(effects, CreateMatchThread)[0]
        assert t.match_id == id(match)
        assert t.guild_id == 42
        assert t.channel_name == "ch"
        assert t.stream_notice == "STREAM"
        assert t.launch_message == "GO"
        assert isinstance(t.init_messages, list)
        assert len(t.init_messages) > 0

    def test_archive_thread_has_match_id(self, p1, p2, fake_ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=fake_ladder)
        effects = mh.cancel_match(match)
        a = _effects_of_type(effects, ArchiveThread)[0]
        assert a.match_id == id(match)

    def test_send_to_channel_fields(self, p1, p2, fake_ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=fake_ladder)
        match.report_winner(p1, p1)
        match.report_winner(p2, p1)
        effects = mh.close_match(match)
        sc = _effects_of_type(effects, SendToChannel)[0]
        assert sc.guild_id == fake_ladder.guild.id
        assert sc.channel_name == "results"
        assert isinstance(sc.messages, list)

    def test_update_ladder_ui_id(self, p1, p2, fake_ladder):
        match = mh.launch_match("test_thread_game", [p1, p2], ladder=fake_ladder)
        match.report_winner(p1, p1)
        match.report_winner(p2, p1)
        effects = mh.close_match(match)
        u = _effects_of_type(effects, UpdateLadderUI)[0]
        assert u.ladder_id == id(fake_ladder)


# ---------------------------------------------------------------------------
# Registry extraction — structural tests
# ---------------------------------------------------------------------------

class TestRegistryExtraction:

    def test_match_handler_uses_registry_not_axi(self):
        """match_handler should import from axi.registry, not axi.axi."""
        assert hasattr(mh, 'registry')
        assert not hasattr(mh, 'axi')

    def test_registry_and_match_handler_share_same_dicts(self):
        """match_handler.registry.dm_games IS registry.dm_games (same object)."""
        assert mh.registry.dm_games is registry.dm_games
        assert mh.registry.thread_games is registry.thread_games

    def test_registry_has_registered_games(self):
        """The conftest fixture populates registry, and match_handler sees them."""
        assert "rps" in registry.dm_games
        assert "test_thread_game" in registry.thread_games

    def test_launch_match_reads_from_registry(self, p1, p2):
        """launch_match finds games via registry, not a separate dict."""
        match = mh.launch_match("rps", [p1, p2])
        assert match is not None
        assert type(match) is registry.dm_games["rps"]


# ---------------------------------------------------------------------------
# AxiUser decoupling — pure AxiUser tests
# ---------------------------------------------------------------------------

class TestAxiUserDecoupling:

    def test_axi_user_has_no_discord_imports(self):
        """axi_user module should have zero imports."""
        import axi.axi_user as axi_user_mod
        import inspect
        source = inspect.getsource(axi_user_mod)
        assert "discord" not in source.lower()

    def test_pure_axi_user_uid_id(self):
        from axi.axi_user import AxiUser
        u = AxiUser(42, "TestUser", "<@42>")
        assert u.uid.id == 42

    def test_pure_axi_user_parse(self):
        from axi.axi_user import AxiUser
        u = AxiUser(42, "TestUser", "<@42>")
        assert u.parse() == "TestUser"
        assert u.parse(mention=True) == "<@42>"

    def test_pure_axi_user_str_repr(self):
        from axi.axi_user import AxiUser
        u = AxiUser(42, "TestUser")
        assert str(u) == "TestUser"
        assert repr(u) == "TestUser"

    def test_fake_user_matches_axi_user_interface(self, p1):
        """FakeUser has the same interface as pure AxiUser."""
        assert hasattr(p1, 'uid')
        assert hasattr(p1.uid, 'id')
        assert hasattr(p1, 'parse')
        assert callable(p1.parse)
