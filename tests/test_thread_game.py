"""Tests for ThreadGame — report_winner, check_match_aborted, checkin, winner, description."""

from conftest import FakeUser, THREAD_GAME_INFO
from axi.thread_game import ThreadGame


def _make_game(p1, p2, **kwargs):
    return ThreadGame(THREAD_GAME_INFO, [p1, p2], **kwargs)


class TestReportWinner:

    def test_single_report_recorded(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        assert g.reports[p1] is p1

    def test_admin_override(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1, admin_override=True)
        assert g.reports["admin"] is p1

    def test_admin_override_takes_precedence(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p2)
        g.report_winner(p2, p2)
        g.report_winner(p1, p1, admin_override=True)
        assert g.winner() is p1


class TestWinner:

    def test_no_reports_returns_none(self, p1, p2):
        g = _make_game(p1, p2)
        assert g.winner() is None

    def test_one_report_returns_none(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        assert g.winner() is None

    def test_agreeing_reports_returns_winner(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p1)
        assert g.winner() is p1

    def test_disagreeing_reports_returns_none(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1)
        g.report_winner(p2, p2)
        assert g.winner() is None

    def test_admin_override_winner(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_winner(p1, p1, admin_override=True)
        assert g.winner() is p1


class TestCheckMatchAborted:

    def test_no_aborts_not_aborted(self, p1, p2):
        g = _make_game(p1, p2)
        assert g.check_match_aborted() is False

    def test_one_abort_not_aborted(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_abort(p1)
        assert g.check_match_aborted() is False

    def test_both_abort_is_aborted(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_abort(p1)
        g.report_abort(p2)
        assert g.check_match_aborted() is True

    def test_admin_abort_is_aborted(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_abort("admin")
        assert g.check_match_aborted() is True

    def test_abort_makes_match_over(self, p1, p2):
        g = _make_game(p1, p2)
        g.report_abort(p1)
        g.report_abort(p2)
        assert g.check_match_over() is True


class TestCheckinUser:

    def test_checkin_first_time_returns_true(self, p1, p2):
        g = _make_game(p1, p2)
        assert g.checkin_user(p1) is True

    def test_checkin_second_time_returns_false(self, p1, p2):
        g = _make_game(p1, p2)
        g.checkin_user(p1)
        assert g.checkin_user(p1) is False

    def test_checkin_adds_to_set(self, p1, p2):
        g = _make_game(p1, p2)
        g.checkin_user(p1)
        assert p1 in g.checkins


class TestMatchInitMsg:

    def test_includes_game_init_text(self, p1, p2):
        g = _make_game(p1, p2)
        msgs = g.match_init_msg()
        texts = [m[0] for m in msgs]
        assert any("Welcome" in t for t in texts)

    def test_includes_description(self, p1, p2):
        g = _make_game(p1, p2)
        msgs = g.match_init_msg()
        texts = [m[0] for m in msgs]
        assert any("Alice" in t and "Bob" in t for t in texts)

    def test_includes_first_ban(self, p1, p2):
        g = _make_game(p1, p2)
        msgs = g.match_init_msg()
        texts = [m[0] for m in msgs]
        assert any("bans first" in t for t in texts)


class TestMatchOverMsg:

    def test_match_over_msg(self, p1, p2):
        g = _make_game(p1, p2)
        msgs = g.match_over_msg()
        assert len(msgs) == 1
        assert "confirmed" in msgs[0][0].lower()


class TestThreadDescription:

    def test_streamed_prefix(self, p1, p2):
        g = _make_game(p1, p2)
        g.streamed = True
        desc = g.description()
        assert desc.startswith(":tv:")

    def test_first_ban_in_description(self, p1, p2):
        g = _make_game(p1, p2)
        desc = g.description(first_ban=True)
        assert "bans first" in desc
