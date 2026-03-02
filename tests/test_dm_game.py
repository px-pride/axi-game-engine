"""Tests for AbstractDmGame logic — validate_decision, check_all_decisions_in,
message queue, spectators, and RPS-specific behavior."""

import axi.handlers.match_handler as mh
import axi.registry as registry
from conftest import FakeUser

ROCK = "\N{ROCK}"
SCROLL = "\N{SCROLL}"
SCISSORS = "\N{BLACK SCISSORS}"


def _launch(p1, p2):
    match = mh.launch_match("rps", [p1, p2])
    mh.prepare_match_ux(match, "rps")
    return match


class TestValidateDecision:

    def test_valid_option_accepted(self, p1, p2):
        m = _launch(p1, p2)
        assert m.validate_decision(p1, ROCK) is True

    def test_invalid_option_rejected(self, p1, p2):
        m = _launch(p1, p2)
        assert m.validate_decision(p1, "bad") is False

    def test_abort_always_accepted(self, p1, p2):
        m = _launch(p1, p2)
        assert m.validate_decision(p1, "abort") is True
        assert p1 in m.resigned

    def test_duplicate_decision_rejected(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        assert m.validate_decision(p1, SCISSORS) is False

    def test_rejected_decision_leaves_slot_open(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, "bad")  # rejected
        assert m.decisions[p1] is None  # slot still None


class TestCheckAllDecisionsIn:

    def test_no_decisions_returns_false(self, p1, p2):
        m = _launch(p1, p2)
        assert m.check_all_decisions_in() is False

    def test_one_decision_returns_false(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        assert m.check_all_decisions_in() is False

    def test_both_decisions_returns_true(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        m.validate_decision(p2, SCISSORS)
        assert m.check_all_decisions_in() is True

    def test_abort_counts_as_decision(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, "abort")
        m.validate_decision(p2, ROCK)
        assert m.check_all_decisions_in() is True


class TestMessageQueue:

    def test_init_populates_queue(self, p1, p2):
        m = mh.launch_match("rps", [p1, p2])
        # Before prepare_match_ux drains them, queues should have init messages
        assert len(m.message_queue[p1]) > 0
        assert len(m.message_queue[p2]) > 0

    def test_flush_clears_queue(self, p1, p2):
        m = mh.launch_match("rps", [p1, p2])
        msgs = m.flush_message_queue(p1)
        assert len(msgs) > 0
        assert m.flush_message_queue(p1) == []

    def test_flush_returns_tuples(self, p1, p2):
        m = mh.launch_match("rps", [p1, p2])
        msgs = m.flush_message_queue(p1)
        for msg in msgs:
            assert isinstance(msg, tuple)
            assert len(msg) == 2


class TestRefreshDecisions:

    def test_refresh_clears_all_decisions(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        m.refresh_decisions()
        assert m.decisions[p1] is None
        assert m.decisions[p2] is None


class TestAgents:

    def test_agents_are_players_initially(self, p1, p2):
        m = _launch(p1, p2)
        agents = m.agents()
        assert p1 in agents
        assert p2 in agents
        assert len(agents) == 2

    def test_spectator_added_to_agents(self, p1, p2):
        m = _launch(p1, p2)
        spectator = FakeUser("Spectator", 3000)
        m.add_spectator(spectator)
        agents = m.agents()
        assert spectator in agents
        assert len(agents) == 3


class TestRpsSpecific:

    def test_validate_mode_versus(self, p1, p2):
        m = mh.launch_match("rps", [p1, p2], mode="versus")
        assert m is not None

    def test_validate_mode_cpu(self, p1, p2):
        m = mh.launch_match("rps", [p1], mode="cpu")
        assert m is not None

    def test_validate_mode_invalid(self, p1, p2):
        m = mh.launch_match("rps", [p1, p2], mode="team")
        assert m is None

    def test_options_are_rps_emojis(self, p1, p2):
        m = _launch(p1, p2)
        opts = m.get_options(p1)
        assert set(opts) == {ROCK, SCROLL, SCISSORS}

    def test_scores_start_at_zero(self, p1, p2):
        m = _launch(p1, p2)
        assert m.scores[p1] == 0
        assert m.scores[p2] == 0

    def test_rock_beats_scissors(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        m.validate_decision(p2, SCISSORS)
        m.match_step()
        assert m.scores[p1] == 1
        assert m.scores[p2] == 0

    def test_paper_beats_rock(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        m.validate_decision(p2, SCROLL)
        m.match_step()
        assert m.scores[p2] == 1
        assert m.scores[p1] == 0

    def test_scissors_beats_paper(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, SCROLL)
        m.validate_decision(p2, SCISSORS)
        m.match_step()
        assert m.scores[p2] == 1
        assert m.scores[p1] == 0

    def test_tie_no_score_change(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, ROCK)
        m.validate_decision(p2, ROCK)
        m.match_step()
        assert m.scores[p1] == 0
        assert m.scores[p2] == 0

    def test_winner_after_three_wins(self, p1, p2):
        m = _launch(p1, p2)
        for _ in range(3):
            m.validate_decision(p1, ROCK)
            m.validate_decision(p2, SCISSORS)
            m.match_step()
            m.refresh_decisions()
        assert m.winner() is p1

    def test_no_winner_after_two_wins(self, p1, p2):
        m = _launch(p1, p2)
        for _ in range(2):
            m.validate_decision(p1, ROCK)
            m.validate_decision(p2, SCISSORS)
            m.match_step()
            m.refresh_decisions()
        assert m.winner() is None

    def test_resign_makes_opponent_winner(self, p1, p2):
        m = _launch(p1, p2)
        m.validate_decision(p1, "abort")
        m.validate_decision(p2, ROCK)
        assert m.winner() is p2
