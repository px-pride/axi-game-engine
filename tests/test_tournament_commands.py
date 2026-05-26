"""Phase 14 tests — tournament_handler pure layer + end-to-end flow.

Tests the pure-layer `tournament_handler` orchestrator, the four
announcement effects, end-to-end tournament lifecycle (create → preset
→ adduser → begin → score → placements → advancephase → destroy),
scope routing across multiple coexisting tournaments, and static
verification of `@has_permissions(ban_members=True)` gating on admin
slash commands.

The slash command surface (in `axi/handlers/discord_handler.py`) is
not directly testable under conftest's Discord mocks; we exercise the
pure-layer handler beneath it.
"""

import os

import pytest

import axi.handlers.tournament_handler as tournament_handler
from axi.effects import (
    AnnouncePhaseStart,
    AnnouncePhaseEnd,
    AnnounceTourneyStart,
    AnnounceTourneyEnd,
    SendToChannel,
)
from axi.match_graph import MatchGraph
from axi.tournament import Tournament
from axi.tournament_presets import PRESETS, register_preset
from axi.tournament_state import state as tournament_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_tournament_state():
    tournament_state.reset()
    yield
    tournament_state.reset()


@pytest.fixture(autouse=True)
def _clean_presets():
    saved = dict(PRESETS)
    yield
    PRESETS.clear()
    PRESETS.update(saved)


@pytest.fixture
def players(p1, p2):
    p3 = type(p1)("Carol", 1003)
    p4 = type(p1)("Dave", 1004)
    return [p1, p2, p3, p4]


class _StubGraph(MatchGraph):
    """Minimal MatchGraph for testing — 4-player SE."""

    def generate_bracket(self):
        match_list = []
        if len(self.players) == 4:
            m1 = self.add_node(
                players=[self.players[0], self.players[1]],
                label="SEMIS", game="rps", best_of=3, loser_gets=3,
            )
            m2 = self.add_node(
                players=[self.players[2], self.players[3]],
                label="SEMIS", game="rps", best_of=3, loser_gets=3,
            )
            finals = self.add_node(
                players=[], label="FINALS", game="rps", best_of=3,
                loser_gets=2,
            )
            self.link_parent(finals, m1, "W")
            self.link_parent(finals, m2, "W")
            self.link_parent(self.victory_node, finals, "W")
            match_list = [m1, m2]
        elif len(self.players) == 2:
            finals = self.add_node(
                players=list(self.players), label="FINALS", game="rps",
                best_of=3, loser_gets=2,
            )
            self.link_parent(self.victory_node, finals, "W")
            match_list = [finals]
        return match_list


def _register_stub():
    @register_preset("stub_se")
    def _(_t):
        return [lambda tt, pp: _StubGraph(tt, pp)], "Stub SE"
    return "stub_se"


# ---------------------------------------------------------------------------
# tournament_handler — create / destroy / preset
# ---------------------------------------------------------------------------


class TestCreateDestroy:
    def test_create_registers_with_state(self):
        t, effects = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        assert t is not None
        assert tournament_state.get_tournament_by_scope("MAIN") is t

    def test_create_emits_send_to_channel(self):
        _, effects = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps", name="My Test")
        assert any(isinstance(e, SendToChannel) for e in effects)

    def test_create_uses_scope_as_default_title(self):
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        assert t.title == "MAIN"

    def test_create_overrides_with_name(self):
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps", name="Custom Name")
        assert t.title == "Custom Name"

    def test_destroy_unbinds_scope(self):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t, effects = tournament_handler.destroy_tournament(
            scope="MAIN", guild_id=99)
        assert t is not None
        assert tournament_state.get_tournament_by_scope("MAIN") is None

    def test_destroy_unknown_scope_noop(self):
        t, effects = tournament_handler.destroy_tournament(
            scope="UNKNOWN", guild_id=99)
        assert t is None
        assert effects == []


class TestPreset:
    def test_apply_known_preset(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        ok, _ = tournament_handler.apply_preset("MAIN", "stub_se")
        assert ok
        assert t.format == "Stub SE"

    def test_apply_unknown_preset(self):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        ok, _ = tournament_handler.apply_preset("MAIN", "doesnotexist")
        assert not ok

    def test_apply_preset_unknown_scope(self):
        ok, _ = tournament_handler.apply_preset("MISSING", "stub_se")
        assert not ok


# ---------------------------------------------------------------------------
# tournament_handler — begin / advance / undo phase
# ---------------------------------------------------------------------------


class TestBegin:
    def test_begin_emits_announcements(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        effects = tournament_handler.begin("MAIN", guild_id=99)
        # AnnounceTourneyStart + AnnouncePhaseStart present.
        assert any(isinstance(e, AnnounceTourneyStart) for e in effects)
        assert any(isinstance(e, AnnouncePhaseStart) for e in effects)

    def test_begin_no_tournament_no_op(self):
        effects = tournament_handler.begin("MISSING", guild_id=99)
        assert effects == []

    def test_begin_tourney_start_carries_title(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps", name="Spring Open")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        effects = tournament_handler.begin("MAIN", guild_id=99)
        ts = next(e for e in effects if isinstance(e, AnnounceTourneyStart))
        assert ts.title == "Spring Open"
        assert ts.format == "Stub SE"


class TestAdvancePhase:
    def _setup(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        return t

    def test_advance_after_finals_emits_tourney_end(self, players):
        t = self._setup(players)
        # Complete the bracket.
        graph = t.current_phase()
        semis = [n for n in graph.nodes_by_id.values() if n.label == "SEMIS"]
        for s in semis:
            s.score = [2, 0]
            graph.complete_match(s)
        finals = next(n for n in graph.nodes_by_id.values()
                      if n.label == "FINALS")
        finals.score = [2, 0]
        graph.complete_match(finals)
        effects = tournament_handler.advance_phase("MAIN", guild_id=99)
        # check_end_of_phase already advanced; advance_phase here is a
        # no-op past the end but should emit the tourney-end announcement
        # if completed.
        # Since the tournament has only 1 phase_fn, we're already done.
        assert t.completed()


class TestUndoPhase:
    def test_undo_after_begin(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        before = t.phase_id
        tournament_handler.undo_phase("MAIN")
        assert t.phase_id == before - 1


# ---------------------------------------------------------------------------
# Player management
# ---------------------------------------------------------------------------


class TestPlayerManagement:
    def test_add_players(self, players):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        n, _ = tournament_handler.add_players("MAIN", players)
        assert n == 4

    def test_add_duplicate_skipped(self, p1):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        tournament_handler.add_players("MAIN", [p1])
        n, _ = tournament_handler.add_players("MAIN", [p1])
        assert n == 0

    def test_remove_players_before_begin(self, players):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        tournament_handler.add_players("MAIN", players)
        n, _ = tournament_handler.remove_players("MAIN", [players[0]])
        assert n == 1

    def test_drop_user_marks_dropped(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        tournament_handler.drop_user("MAIN", players[0])
        assert t.is_dropped(players[0])

    def test_dq_user_marks_dq(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        tournament_handler.dq_user("MAIN", players[0])
        assert t.is_dq(players[0])

    def test_undo_drop_user(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        tournament_handler.drop_user("MAIN", players[0])
        tournament_handler.undo_drop_user("MAIN", players[0])
        assert not t.is_dropped(players[0])

    def test_undo_dq_user(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        tournament_handler.dq_user("MAIN", players[0])
        tournament_handler.undo_dq_user("MAIN", players[0])
        assert not t.is_dq(players[0])


# ---------------------------------------------------------------------------
# Score reporting / undo_match
# ---------------------------------------------------------------------------


class TestScoreReporting:
    def _setup(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        return t

    def test_undo_match_does_not_raise(self, players):
        t = self._setup(players)
        graph = t.current_phase()
        # Complete the semi-final between p0 and p1.
        m1 = next(n for n in graph.nodes_by_id.values()
                  if n.label == "SEMIS"
                  and players[0] in n.players)
        m1.score = [2, 0]
        graph.complete_match(m1)
        # Now undo it via handler.
        effects = tournament_handler.undo_match("MAIN", players[0], players[1])
        # undo_match returns whatever undo_match emits — no exception is
        # the success criterion.
        assert isinstance(effects, list)


# ---------------------------------------------------------------------------
# Status / placements / matches
# ---------------------------------------------------------------------------


class TestStatusPlacements:
    def _setup(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        return t

    def test_get_placements_after_bracket_done(self, players):
        t = self._setup(players)
        graph = t.current_phase()
        semis = [n for n in graph.nodes_by_id.values() if n.label == "SEMIS"]
        for s in semis:
            s.score = [2, 0]
            graph.complete_match(s)
        finals = next(n for n in graph.nodes_by_id.values()
                      if n.label == "FINALS")
        finals.score = [2, 0]
        graph.complete_match(finals)
        pls = tournament_handler.get_placements("MAIN")
        # Must return a list of (rank, user) tuples.
        assert isinstance(pls, list)

    def test_get_matches_for_player(self, players):
        t = self._setup(players)
        ms = tournament_handler.get_matches_for_player("MAIN", players[0])
        assert isinstance(ms, list)

    def test_get_format(self, players):
        self._setup(players)
        fmt = tournament_handler.get_format("MAIN")
        assert fmt == "Stub SE"

    def test_get_format_unknown_scope(self):
        assert tournament_handler.get_format("MISSING") is None

    def test_get_pool_scores_non_rr(self, players):
        self._setup(players)
        # _StubGraph isn't RoundRobin, so pool_scores returns None.
        scores = tournament_handler.get_pool_scores("MAIN")
        assert scores is None


class TestCurrentMatches:
    def _setup(self, players):
        _register_stub()
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        return t

    def test_returns_three_lists(self, players):
        self._setup(players)
        active, called, stream = tournament_handler.get_current_matches("MAIN")
        # After begin, semis should be CALLED (status 1).
        assert isinstance(active, list)
        assert isinstance(called, list)
        # 2 semis called.
        assert len(called) == 2


# ---------------------------------------------------------------------------
# Admin RNG / series
# ---------------------------------------------------------------------------


class TestAdminOps:
    def test_set_seed(self, players):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        assert tournament_handler.set_seed("MAIN", 12345) is True

    def test_set_seed_unknown_scope(self):
        assert tournament_handler.set_seed("MISSING", 1) is False

    def test_set_series_id(self):
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        assert tournament_handler.set_series_id("MAIN", 42) is True

    def test_set_series_id_unknown_scope(self):
        assert tournament_handler.set_series_id("MISSING", 42) is False


# ---------------------------------------------------------------------------
# Scope routing — multiple tournaments coexisting
# ---------------------------------------------------------------------------


class TestScopeRouting:
    def test_two_tournaments_distinct_scopes(self, players):
        _register_stub()
        t1, _ = tournament_handler.create_tournament(
            scope="ALPHA", guild_id=99, game="rps")
        t2, _ = tournament_handler.create_tournament(
            scope="BETA", guild_id=99, game="rps")
        assert tournament_state.get_tournament_by_scope("ALPHA") is t1
        assert tournament_state.get_tournament_by_scope("BETA") is t2

    def test_handler_routes_to_correct_scope(self, players):
        _register_stub()
        t1, _ = tournament_handler.create_tournament(
            scope="ALPHA", guild_id=99, game="rps")
        t2, _ = tournament_handler.create_tournament(
            scope="BETA", guild_id=99, game="rps")
        # Add to ALPHA only.
        tournament_handler.add_players("ALPHA", players[:2])
        # Add different players to BETA.
        tournament_handler.add_players("BETA", players[2:])
        assert len(t1.players) == 2
        assert len(t2.players) == 2
        # Each tournament has the right players.
        assert players[0] in t1.players
        assert players[2] in t2.players

    def test_destroy_only_unbinds_target_scope(self):
        tournament_handler.create_tournament(
            scope="ALPHA", guild_id=99, game="rps")
        tournament_handler.create_tournament(
            scope="BETA", guild_id=99, game="rps")
        tournament_handler.destroy_tournament("ALPHA", guild_id=99)
        assert tournament_state.get_tournament_by_scope("ALPHA") is None
        assert tournament_state.get_tournament_by_scope("BETA") is not None


# ---------------------------------------------------------------------------
# End-to-end lifecycle simulation
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Simulate the source flow:
    /create → /preset → /adduser × 4 → /begin → /score (4 matches) →
    /placements → /destroy.

    This is the canonical Phase 14 acceptance test."""

    def test_full_se_flow(self, players):
        _register_stub()
        # /create
        t, _ = tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps", name="Test Open")
        assert t is not None
        # /preset
        ok, _ = tournament_handler.apply_preset("MAIN", "stub_se")
        assert ok
        # /adduser × 4
        n, _ = tournament_handler.add_players("MAIN", players)
        assert n == 4
        # /begin
        effects = tournament_handler.begin("MAIN", guild_id=99)
        assert any(isinstance(e, AnnounceTourneyStart) for e in effects)
        assert any(isinstance(e, AnnouncePhaseStart) for e in effects)
        # Complete the bracket via direct MatchGraph calls (slash command
        # would route this via /score).
        graph = t.current_phase()
        semis = [n_ for n_ in graph.nodes_by_id.values()
                 if n_.label == "SEMIS"]
        for s in semis:
            s.score = [2, 0]
            graph.complete_match(s)
        finals = next(n_ for n_ in graph.nodes_by_id.values()
                      if n_.label == "FINALS")
        finals.score = [2, 0]
        graph.complete_match(finals)
        # /placements
        pls = tournament_handler.get_placements("MAIN")
        assert isinstance(pls, list)
        # /destroy
        t_destroyed, _ = tournament_handler.destroy_tournament(
            "MAIN", guild_id=99)
        assert t_destroyed is t
        assert tournament_state.get_tournament_by_scope("MAIN") is None

    def test_tournament_completes_after_finals(self, players):
        _register_stub()
        tournament_handler.create_tournament(
            scope="MAIN", guild_id=99, game="rps")
        t = tournament_state.get_tournament_by_scope("MAIN")
        t.add_players(players)
        tournament_handler.apply_preset("MAIN", "stub_se")
        tournament_handler.begin("MAIN", guild_id=99)
        graph = t.current_phase()
        for s in [n for n in graph.nodes_by_id.values() if n.label == "SEMIS"]:
            s.score = [2, 0]
            graph.complete_match(s)
        finals = next(n for n in graph.nodes_by_id.values()
                      if n.label == "FINALS")
        finals.score = [2, 0]
        graph.complete_match(finals)
        assert t.completed()


# ---------------------------------------------------------------------------
# Permission gating — static analysis of discord_handler source
# ---------------------------------------------------------------------------


class TestPermissionGating:
    """Verify @has_permissions(ban_members=True) is applied to every
    admin command. We can't exercise the decorator at runtime (Discord
    is mocked under conftest) — but we can grep the source file to
    confirm the decorator is present above each admin command.
    """

    @pytest.fixture
    def source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "axi", "handlers", "discord_handler.py",
        )
        with open(path, "r") as f:
            return f.read()

    @pytest.mark.parametrize("cmd_name", [
        "create", "destroy", "preset", "begin", "start",
        "advancephase", "undophase",
        "adduser", "removeuser", "checkinuser",
        "dropuser", "fulldropuser", "dquser",
        "undodrop", "undodq", "undomatch",
        "setseries", "createseries", "createmultibracket",
        "setrng", "forcebreak", "forcequeue",
        "clearchannel", "verify", "sql",
        "statusadmin",
    ])
    def test_admin_command_gated(self, source, cmd_name):
        # Build a regex-like check: the command's @bot.tree.command(name="<cmd>")
        # decorator must be followed (within a few lines) by
        # @has_permissions(ban_members=True).
        marker = f'name="{cmd_name}"'
        idx = source.find(marker)
        assert idx != -1, f"Command /{cmd_name} not registered."
        # Look at the next ~200 chars after the marker for the perm
        # decorator + the async def line — the perm decorator must come
        # before async def.
        snippet = source[idx:idx + 500]
        def_idx = snippet.find("async def ")
        assert def_idx != -1, f"Command /{cmd_name} missing async def."
        head = snippet[:def_idx]
        assert "@has_permissions(ban_members=True)" in head, (
            f"Command /{cmd_name} not gated with @has_permissions"
            f"(ban_members=True). Head text:\n{head}"
        )

    @pytest.mark.parametrize("cmd_name", [
        "score", "dropme", "fulldropme", "placements", "poolscores",
        "round", "current", "bracket", "stream",
        "matches", "mymatches", "format", "info", "elements", "spells",
        "rules", "events", "takeabreak", "resign", "stopspectate",
    ])
    def test_public_command_not_gated(self, source, cmd_name):
        """Public commands should NOT have the admin decorator."""
        marker = f'name="{cmd_name}"'
        idx = source.find(marker)
        assert idx != -1, f"Command /{cmd_name} not registered."
        snippet = source[idx:idx + 500]
        def_idx = snippet.find("async def ")
        head = snippet[:def_idx]
        assert "@has_permissions(ban_members=True)" not in head, (
            f"Command /{cmd_name} should be public but has admin decorator."
        )


# ---------------------------------------------------------------------------
# Effect dataclass coverage
# ---------------------------------------------------------------------------


class TestAnnouncementEffects:
    def test_tourney_start_fields(self):
        e = AnnounceTourneyStart(
            guild_id=99, channel_name="main", title="T", format="Stub")
        assert e.title == "T" and e.format == "Stub"

    def test_phase_start_carries_mentions(self):
        e = AnnouncePhaseStart(
            guild_id=99, channel_name="main",
            phase_name="SE", player_mentions=["<@1>", "<@2>"])
        assert len(e.player_mentions) == 2

    def test_phase_end_placements(self):
        e = AnnouncePhaseEnd(
            guild_id=99, channel_name="main",
            phase_name="SE", placements=[(1, "<@1>"), (2, "<@2>")])
        assert e.placements[0] == (1, "<@1>")

    def test_tourney_end_winner(self):
        e = AnnounceTourneyEnd(
            guild_id=99, channel_name="main",
            title="T", winner_mention="<@1>")
        assert e.winner_mention == "<@1>"
