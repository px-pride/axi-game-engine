"""Tests for AbstractGame base class — opponent, first_to, check_match_over, loser, description."""

from conftest import FakeUser, THREAD_GAME_INFO
from axi.thread_game import ThreadGame
import axi.registry as registry


# We use ThreadGame as a concrete subclass since AbstractGame is abstract.
# ThreadGame.winner() is driven by reports, so we can control match-over state.


def _make_game(p1, p2, **kwargs):
    return ThreadGame(THREAD_GAME_INFO, [p1, p2], **kwargs)


class TestOpponent:

    def test_opponent_of_p1_is_p2(self, p1, p2):
        g = _make_game(p1, p2)
        assert g.opponent(p1) is p2

    def test_opponent_of_p2_is_p1(self, p1, p2):
        g = _make_game(p1, p2)
        assert g.opponent(p2) is p1

    def test_opponent_of_stranger_is_none(self, p1, p2):
        g = _make_game(p1, p2)
        stranger = FakeUser("Stranger", 9999)
        assert g.opponent(stranger) is None


class TestFirstTo:

    def test_bo1(self, p1, p2):
        g = _make_game(p1, p2, best_of=1)
        assert g.first_to() == 1

    def test_bo3(self, p1, p2):
        g = _make_game(p1, p2, best_of=3)
        assert g.first_to() == 2

    def test_bo5(self, p1, p2):
        g = _make_game(p1, p2, best_of=5)
        assert g.first_to() == 3

    def test_bo7(self, p1, p2):
        g = _make_game(p1, p2, best_of=7)
        assert g.first_to() == 4


class TestCheckMatchOver:

    def test_no_reports_not_over(self, p1, p2):
        g = _make_game(p1, p2)
        assert g.check_match_over() is False

    def test_one_report_not_over(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        assert g.check_match_over() is False

    def test_both_report_same_winner_over(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        assert g.check_match_over() is True

    def test_disagreeing_reports_not_over(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p2)
        assert g.check_match_over() is False

    def test_match_over_cached(self, p1, p2):
        """Once match_over is True, it stays True even if state changes."""
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        assert g.check_match_over() is True
        g.reports.clear()  # clear reports
        assert g.check_match_over() is True  # still cached


class TestLoser:

    def test_loser_is_opponent_of_winner(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        assert g.winner() is p1
        assert g.loser() is p2

    def test_loser_when_p2_wins(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p2)
        g.report_winner(p2, p2)
        assert g.loser() is p1


class TestDescription:

    def test_contains_label(self, p1, p2):
        g = _make_game(p1, p2, label="LADDER MATCH")
        desc = g.description()
        assert "LADDER MATCH" in desc

    def test_contains_bo(self, p1, p2):
        g = _make_game(p1, p2, best_of=3)
        desc = g.description()
        assert "Bo3" in desc

    def test_contains_ft_for_large_bo(self, p1, p2):
        g = _make_game(p1, p2, best_of=9)
        desc = g.description()
        assert "Ft5" in desc

    def test_contains_player_names(self, p1, p2):
        g = _make_game(p1, p2)
        desc = g.description()
        assert "Alice" in desc
        assert "Bob" in desc

    def test_winner_in_description_after_match_over(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        desc = g.description()
        assert "Alice" in desc
        assert "wins" in desc

    def test_pov_wins(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        desc = g.description(pov=p1)
        assert "wins" in desc

    def test_pov_loses(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        desc = g.description(pov=p2)
        assert "loses" in desc
