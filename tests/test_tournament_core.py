"""Phase 1 tests — Tournament core abstraction.

Covers MatchNode (pure data + predicates), MatchGraph (DAG, transitions,
stream selection, undo), Tournament (roster, presets, phase lifecycle,
drop/dq, callback path), TournamentState (round-trip + reset).

Also includes integration test simulating the
LaunchTournamentMatch → match_handler.launch_match → completion_callback →
report_match_complete loop.
"""

import pytest
from unittest.mock import MagicMock

import axi.handlers.match_handler as match_handler
from axi.effects import (
    ArchiveTournamentMatch,
    CallMatchForStream,
    LaunchTournamentMatch,
)
from axi.match_graph import MatchGraph
from axi.match_node import MatchNode
from axi.tournament import Tournament
from axi.tournament_presets import PRESETS, apply_preset, register_preset
from axi.tournament_state import state as tournament_state
from axi.util import (
    MATCH_STATUS_ACTIVE,
    MATCH_STATUS_ASLEEP,
    MATCH_STATUS_CALLED,
    MATCH_STATUS_COMPLETED,
)


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


@pytest.fixture
def tournament(players):
    t = Tournament(title="Test Tournament", scope="test", seed=42)
    t.add_players(players)
    return t


class StubGraph(MatchGraph):
    """Minimal MatchGraph subclass for testing. Builds a 2-round single
    elimination from 4 players (or fewer)."""

    def generate_bracket(self):
        # Two round-1 matches: (p0, p1) and (p2, p3). Winners meet in finals.
        # If only 2 players, just create a finals match.
        match_list = []
        if len(self.players) == 4:
            m1 = self.add_node(
                players=[self.players[0], self.players[1]],
                label="SEMIS",
                game="rps",
                best_of=3,
                loser_gets=3,
            )
            m2 = self.add_node(
                players=[self.players[2], self.players[3]],
                label="SEMIS",
                game="rps",
                best_of=3,
                loser_gets=3,
            )
            finals = self.add_node(
                players=[],
                label="FINALS",
                game="rps",
                best_of=3,
                loser_gets=2,
            )
            self.link_parent(finals, m1, "W")
            self.link_parent(finals, m2, "W")
            self.link_parent(self.victory_node, finals, "W")
            match_list = [m1, m2]
        elif len(self.players) == 2:
            finals = self.add_node(
                players=list(self.players),
                label="FINALS",
                game="rps",
                best_of=3,
                loser_gets=2,
            )
            self.link_parent(self.victory_node, finals, "W")
            match_list = [finals]
        return match_list


# ---------------------------------------------------------------------------
# MatchNode predicates
# ---------------------------------------------------------------------------


class TestMatchNodePredicates:
    def _make(self, **kw):
        kw.setdefault("tournament_id", "tid")
        kw.setdefault("graph_id", "gid")
        return MatchNode(**kw)

    def test_asleep_initial(self):
        n = self._make()
        assert n.asleep()
        assert not n.awake()
        assert not n.completed()

    def test_awake_called(self):
        n = self._make()
        n.status = MATCH_STATUS_CALLED
        assert n.awake()
        assert not n.asleep()
        assert not n.completed()

    def test_awake_active(self):
        n = self._make()
        n.status = MATCH_STATUS_ACTIVE
        assert n.awake()

    def test_completed_status(self):
        n = self._make()
        n.status = MATCH_STATUS_COMPLETED
        assert n.completed()
        assert not n.asleep()
        assert not n.awake()

    def test_first_to_bo3(self):
        assert self._make(best_of=3).first_to() == 2

    def test_first_to_bo5(self):
        assert self._make(best_of=5).first_to() == 3

    def test_first_to_bo7(self):
        assert self._make(best_of=7).first_to() == 4

    def test_winner_loser_after_completion(self, p1, p2):
        n = self._make(players=[p1, p2], best_of=3)
        n.score = [2, 0]
        n.status = MATCH_STATUS_COMPLETED
        assert n.winner() is p1
        assert n.loser() is p2

    def test_winner_returns_none_when_incomplete(self, p1, p2):
        n = self._make(players=[p1, p2], best_of=3)
        assert n.winner() is None

    def test_is_sweep_true(self, p1, p2):
        n = self._make(players=[p1, p2], best_of=3)
        n.score = [2, 0]
        n.status = MATCH_STATUS_COMPLETED
        assert n.is_sweep()

    def test_is_sweep_false_when_close(self, p1, p2):
        n = self._make(players=[p1, p2], best_of=3)
        n.score = [2, 1]
        n.status = MATCH_STATUS_COMPLETED
        assert not n.is_sweep()

    def test_is_bye_detects_bye_players(self):
        bye = MagicMock()
        bye.is_bye.return_value = True
        normal = MagicMock()
        normal.is_bye.return_value = False
        n = self._make(players=[normal, bye])
        assert n.is_bye()

    def test_is_bye_false_without_bye(self, p1, p2):
        n = self._make(players=[p1, p2])
        assert not n.is_bye()

    def test_has_player(self, p1, p2):
        n = self._make(players=[p1, p2])
        assert n.has_player(p1)
        assert n.has_player(p2)

    def test_opponent(self, p1, p2):
        n = self._make(players=[p1, p2])
        assert n.opponent(p1) is p2
        assert n.opponent(p2) is p1

    def test_node_id_is_uuid_hex_string(self):
        n = self._make()
        assert isinstance(n.node_id, str)
        assert len(n.node_id) == 32  # uuid4 hex

    def test_node_ids_are_unique(self):
        a = self._make()
        b = self._make()
        assert a.node_id != b.node_id

    def test_get_score(self):
        n = self._make()
        n.score = [2, 1]
        assert n.get_score() == "2-1"


# ---------------------------------------------------------------------------
# MatchGraph: add_node, link_parent, ancestors
# ---------------------------------------------------------------------------


class TestMatchGraphStructure:
    def test_create_data_structures_initializes_all(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        assert g.seed_by_player == {p: i for i, p in enumerate(players)}
        assert g.placements_dict == {p: -1 for p in players}
        assert g.victory_node is not None
        assert g.victory_node.label == "VICTORY"
        assert g.victory_node.node_id in g.nodes_by_id

    def test_add_node_registers_in_nodes_by_id(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        n = g.add_node(label="TEST", best_of=3)
        assert n.node_id in g.nodes_by_id
        assert g.nodes_by_id[n.node_id] is n
        assert n.tournament_id == tournament.tournament_id
        assert n.graph_id == g.graph_id

    def test_link_parent_sets_both_sides(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        parent = g.add_node(label="P")
        child = g.add_node(label="C")
        g.link_parent(child, parent, "W")
        assert child.parents == {parent.node_id: "W"}
        assert parent.children == {child.node_id: "W"}

    def test_link_parent_rejects_bad_flag(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        a = g.add_node()
        b = g.add_node()
        with pytest.raises(ValueError):
            g.link_parent(b, a, "X")

    def test_ancestors_recursive(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        grand = g.add_node(label="GRAND")
        parent = g.add_node(label="P")
        child = g.add_node(label="C")
        g.link_parent(parent, grand, "W")
        g.link_parent(child, parent, "W")
        ancestors = g.ancestors(child)
        assert parent in ancestors
        assert grand in ancestors

    def test_ancestors_skips_completed_by_default(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        completed_parent = g.add_node(label="DONE")
        completed_parent.status = MATCH_STATUS_COMPLETED
        child = g.add_node(label="C")
        g.link_parent(child, completed_parent, "W")
        assert completed_parent not in g.ancestors(child)
        assert completed_parent in g.ancestors(child, include_completed=True)


# ---------------------------------------------------------------------------
# MatchGraph: call_match
# ---------------------------------------------------------------------------


class TestCallMatch:
    def test_call_real_match_emits_launch(self, tournament, players):
        g = StubGraph(tournament, players)
        effects = g.begin()
        launch_effects = [e for e in effects if isinstance(e, LaunchTournamentMatch)]
        assert len(launch_effects) == 2
        first = launch_effects[0]
        assert first.tournament_id == tournament.tournament_id
        assert first.graph_id == g.graph_id
        assert first.game == "rps"

    def test_call_match_transitions_to_called(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        called = [n for n in g.nodes_by_id.values() if n.label == "SEMIS"]
        for n in called:
            assert n.status == MATCH_STATUS_CALLED
            assert n in g.called_matches
            assert n.checkin_deadline is not None

    def test_call_match_with_bye_auto_resolves(self, tournament):
        bye_user = MagicMock()
        bye_user.is_bye.return_value = True
        bye_user.uid = MagicMock()
        bye_user.uid.id = 9999
        real = tournament.players[0]
        g = StubGraph(tournament, [real, bye_user])
        g.create_data_structures()
        m = g.add_node(players=[real, bye_user], label="BYE", best_of=3, loser_gets=4)
        effects = g.call_match(m)
        # Bye doesn't emit a launch effect
        assert not any(isinstance(e, LaunchTournamentMatch) for e in effects)
        assert m.completed()
        assert m.node_id in g.non_matches
        assert g.non_matches[m.node_id] == "bye"

    def test_call_match_with_drop_auto_resolves(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        tournament.drop_user(players[1])
        m = g.add_node(players=[players[0], players[1]], label="X", best_of=3)
        effects = g.call_match(m)
        assert not any(isinstance(e, LaunchTournamentMatch) for e in effects)
        assert m.completed()


# ---------------------------------------------------------------------------
# MatchGraph: receive_checkin
# ---------------------------------------------------------------------------


class TestReceiveCheckin:
    def test_first_checkin_keeps_called(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        g.receive_checkin(m, m.players[0])
        assert m.status == MATCH_STATUS_CALLED

    def test_both_checkins_transition_to_active(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        g.receive_checkin(m, m.players[0])
        g.receive_checkin(m, m.players[1])
        assert m.status == MATCH_STATUS_ACTIVE
        assert m in g.active_matches
        assert m not in g.called_matches


# ---------------------------------------------------------------------------
# MatchGraph: report_score
# ---------------------------------------------------------------------------


class TestReportScore:
    def test_valid_bo3_score(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        accepted, _ = g.report_score(m, m.players[0], (2, 0))
        assert accepted

    def test_invalid_negative_score(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        accepted, _ = g.report_score(m, m.players[0], (-1, 0))
        assert not accepted

    def test_invalid_zero_zero(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        accepted, _ = g.report_score(m, m.players[0], (0, 0))
        assert not accepted

    def test_bo5_limit_max_3(self, tournament, players):
        g = StubGraph(tournament, players)
        g.create_data_structures()
        m = g.add_node(players=players[:2], label="X", best_of=5)
        m.status = MATCH_STATUS_CALLED
        accepted_high, _ = g.report_score(m, players[0], (4, 0))
        accepted_legal, _ = g.report_score(m, players[0], (3, 1))
        assert not accepted_high
        assert accepted_legal

    def test_dual_report_confirms(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        g.report_score(m, m.players[0], (2, 1))
        _, effects = g.report_score(m, m.players[1], (2, 1))
        assert m.completed()
        assert m.score == [2, 1]
        # complete_match emits ArchiveTournamentMatch
        assert any(isinstance(e, ArchiveTournamentMatch) for e in effects)

    def test_dual_report_disagreement_stays_open(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        g.report_score(m, m.players[0], (2, 1))
        g.report_score(m, m.players[1], (1, 2))
        assert not m.completed()


# ---------------------------------------------------------------------------
# MatchGraph: complete_match propagation
# ---------------------------------------------------------------------------


class TestCompleteMatch:
    def test_winner_propagates_to_child(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m1 = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS" and n.players[0] is players[0])
        finals = next(n for n in g.nodes_by_id.values() if n.label == "FINALS")
        m1.score = [2, 0]
        g.complete_match(m1)
        assert players[0] in finals.players

    def test_finals_calls_after_both_semis_complete(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m1, m2 = sorted(
            (n for n in g.nodes_by_id.values() if n.label == "SEMIS"),
            key=lambda n: n.players[0].uid.id,
        )
        m1.score = [2, 0]
        g.complete_match(m1)
        finals = next(n for n in g.nodes_by_id.values() if n.label == "FINALS")
        assert finals.asleep()
        m2.score = [2, 0]
        effects = g.complete_match(m2)
        # finals should now be called
        assert finals.status == MATCH_STATUS_CALLED
        assert any(isinstance(e, LaunchTournamentMatch) for e in effects)

    def test_placement_assigned_on_complete(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        m.score = [2, 0]
        g.complete_match(m)
        assert g.placements_dict[m.loser()] == 3


# ---------------------------------------------------------------------------
# MatchGraph: undo_match cascade
# ---------------------------------------------------------------------------


class TestUndoMatch:
    def test_undo_resets_status(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        m = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        m.score = [2, 0]
        g.complete_match(m)
        g.undo_match(m)
        assert m.asleep()
        assert m.score == [0, 0]
        assert len(m.checkins) == 0

    def test_undo_cascades_to_children(self, tournament, players):
        g = StubGraph(tournament, players)
        g.begin()
        # Complete both semis so finals gets called
        for n in list(g.nodes_by_id.values()):
            if n.label == "SEMIS":
                n.score = [2, 0]
                g.complete_match(n)
        finals = next(n for n in g.nodes_by_id.values() if n.label == "FINALS")
        # Complete finals
        finals.score = [2, 0]
        g.complete_match(finals)
        # Undo a semi — finals should also be reset
        first_semi = next(n for n in g.nodes_by_id.values() if n.label == "SEMIS")
        g.undo_match(first_semi)
        assert first_semi.asleep()
        assert finals.asleep()


# ---------------------------------------------------------------------------
# Stream selection
# ---------------------------------------------------------------------------


class TestStreamSelection:
    def test_call_match_for_stream_picks_one(self, tournament, players):
        g = StubGraph(tournament, players, stream=True)
        # Mark both semis streamed before begin
        # Easier: build manually and run call_match_for_stream
        g.create_data_structures()
        m1 = g.add_node(players=players[:2], label="A", best_of=3, loser_gets=3)
        m2 = g.add_node(players=players[2:], label="B", best_of=3, loser_gets=4)
        effects = g.call_match_for_stream([m1, m2])
        assert any(isinstance(e, CallMatchForStream) for e in effects)
        assert g.stream_match is not None


# ---------------------------------------------------------------------------
# Tournament: roster + colors + drops/dq + presets
# ---------------------------------------------------------------------------


class TestTournamentRoster:
    def test_add_players_unique(self, p1, p2):
        t = Tournament(title="T", scope="s")
        t.add_players([p1, p2, p1])
        assert t.players == [p1, p2]

    def test_remove_players_only_before_start(self, p1, p2):
        t = Tournament(title="T", scope="s")
        t.add_players([p1, p2])
        t.remove_players([p1])
        assert t.players == [p2]

    def test_remove_after_start_no_op(self, p1, p2):
        t = Tournament(title="T", scope="s")
        t.add_players([p1, p2])
        t.started = True
        t.remove_players([p1])
        assert p1 in t.players


class TestTournamentColors:
    def test_assign_player_colors_distributes(self, players):
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        t.assign_player_colors()
        assert len(t.player_colors) == 4
        # All colors are distinct
        colors = list(t.player_colors.values())
        assert len(set(colors)) == 4
        # All are RGB tuples of ints in [0, 255]
        for c in colors:
            assert len(c) == 3
            assert all(0 <= ch <= 255 for ch in c)


class TestTournamentDrops:
    def test_drop_and_check(self, players):
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        t.drop_user(players[0])
        assert t.is_dropped(players[0])
        assert not t.is_dq(players[0])

    def test_dq_and_check(self, players):
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        t.dq_user(players[0])
        assert t.is_dq(players[0])
        assert not t.is_dropped(players[0])

    def test_undo_drop(self, players):
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        t.drop_user(players[0])
        t.undo_drop_user(players[0])
        assert not t.is_dropped(players[0])

    def test_undo_dq(self, players):
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        t.dq_user(players[0])
        t.undo_dq_user(players[0])
        assert not t.is_dq(players[0])

    def test_has_drop_or_dq(self, players):
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        t.drop_user(players[0])
        assert t.has_drop_or_dq([players[0], players[1]])
        assert not t.has_drop_or_dq([players[1], players[2]])


class TestTournamentPresets:
    def test_apply_unknown_preset_fails(self, p1):
        t = Tournament(title="T", scope="s")
        t.add_players([p1])
        assert t.preset("doesnotexist") is False

    def test_apply_known_preset_sets_phase_fns(self, players):
        @register_preset("test_stub")
        def stub(_t):
            return [lambda tt, pp: StubGraph(tt, pp)], "Test format"
        t = Tournament(title="T", scope="s")
        t.add_players(players)
        assert t.preset("test_stub")
        assert t.format == "Test format"
        assert len(t.phase_fns) == 1

    def test_apply_preset_after_start_fails(self, p1):
        @register_preset("after_start")
        def _p(_t):
            return [], "X"
        t = Tournament(title="T", scope="s")
        t.add_players([p1])
        t.started = True
        assert t.preset("after_start") is False


# ---------------------------------------------------------------------------
# Tournament: lifecycle (begin / advance_phase / completed)
# ---------------------------------------------------------------------------


class TestTournamentLifecycle:
    def _setup(self, tournament):
        @register_preset("stub")
        def stub(_t):
            return [lambda tt, pp: StubGraph(tt, pp)], "Stub"
        tournament.preset("stub")
        return tournament

    def test_begin_initializes_first_phase(self, tournament):
        self._setup(tournament)
        effects = tournament.begin()
        assert tournament.started
        assert tournament.phase_id == 0
        assert len(tournament.phases) == 1
        # 2 LaunchTournamentMatch effects expected for 4-player semis
        assert sum(isinstance(e, LaunchTournamentMatch) for e in effects) == 2

    def test_begin_assigns_colors(self, tournament):
        self._setup(tournament)
        tournament.begin()
        assert len(tournament.player_colors) == 4

    def test_completed_after_full_run(self, tournament):
        self._setup(tournament)
        tournament.begin()
        graph = tournament.current_phase()
        # Complete both semis
        semis = [n for n in graph.nodes_by_id.values() if n.label == "SEMIS"]
        for s in semis:
            s.score = [2, 0]
            graph.complete_match(s)
        # Complete finals
        finals = next(n for n in graph.nodes_by_id.values() if n.label == "FINALS")
        finals.score = [2, 0]
        graph.complete_match(finals)
        assert graph.victory_node.completed()
        assert tournament.completed()

    def test_winner_returns_finals_winner(self, tournament, players):
        self._setup(tournament)
        tournament.begin()
        graph = tournament.current_phase()
        for s in [n for n in graph.nodes_by_id.values() if n.label == "SEMIS"]:
            s.score = [2, 0]
            graph.complete_match(s)
        finals = next(n for n in graph.nodes_by_id.values() if n.label == "FINALS")
        finals.score = [2, 0]
        graph.complete_match(finals)
        assert tournament.winner() is not None


# ---------------------------------------------------------------------------
# Tournament: report_match_complete callback path
# ---------------------------------------------------------------------------


class TestReportMatchComplete:
    def _setup(self, tournament):
        @register_preset("stub_cb")
        def stub(_t):
            return [lambda tt, pp: StubGraph(tt, pp)], "Stub"
        tournament.preset("stub_cb")
        tournament.begin()
        return tournament

    def test_report_match_complete_updates_node(self, tournament):
        self._setup(tournament)
        graph = tournament.current_phase()
        m = next(n for n in graph.nodes_by_id.values() if n.label == "SEMIS")
        tournament.report_match_complete(m.node_id, m.players[0].uid.id, [2, 0])
        assert m.completed()
        assert m.score == [2, 0]

    def test_report_match_complete_unknown_node(self, tournament):
        self._setup(tournament)
        effects = tournament.report_match_complete("not_a_real_id", 999, [1, 0])
        assert effects == []


# ---------------------------------------------------------------------------
# Tournament: undo
# ---------------------------------------------------------------------------


class TestTournamentUndo:
    def _setup(self, tournament):
        @register_preset("stub_undo")
        def stub(_t):
            return [lambda tt, pp: StubGraph(tt, pp)], "Stub"
        tournament.preset("stub_undo")
        tournament.begin()
        return tournament

    def test_undo_match_via_tournament(self, tournament):
        self._setup(tournament)
        graph = tournament.current_phase()
        m = next(n for n in graph.nodes_by_id.values() if n.label == "SEMIS")
        m.score = [2, 0]
        graph.complete_match(m)
        tournament.undo_match(m.players[0], m.players[1])
        assert m.asleep()

    def test_undo_phase_decrements_id(self, tournament):
        self._setup(tournament)
        assert tournament.phase_id == 0
        tournament.undo_phase()
        assert tournament.phase_id == -1
        assert tournament.phases == []


# ---------------------------------------------------------------------------
# TournamentState
# ---------------------------------------------------------------------------


class TestTournamentState:
    def test_register_and_lookup(self):
        t = Tournament(title="T", scope="s1")
        tournament_state.register_tournament(t)
        assert tournament_state.get_tournament(t.tournament_id) is t
        assert tournament_state.get_tournament_by_scope("s1") is t

    def test_node_to_match_round_trip(self):
        tournament_state.map_node_to_match("node-abc", 1234)
        assert tournament_state.get_match_for_node("node-abc") == 1234
        assert tournament_state.get_node_for_match(1234) == "node-abc"

    def test_unmap_node_clears_both(self):
        tournament_state.map_node_to_match("node-x", 5678)
        tournament_state.unmap_node("node-x")
        assert tournament_state.get_match_for_node("node-x") is None
        assert tournament_state.get_node_for_match(5678) is None

    def test_reset_clears_all(self):
        t = Tournament(title="T", scope="s_reset")
        tournament_state.register_tournament(t)
        tournament_state.map_node_to_match("n", 99)
        tournament_state.reset()
        assert tournament_state.get_tournament(t.tournament_id) is None
        assert tournament_state.get_match_for_node("n") is None
        assert tournament_state.get_node_for_match(99) is None


# ---------------------------------------------------------------------------
# Presets registry
# ---------------------------------------------------------------------------


class TestPresetRegistry:
    def test_apply_preset_returns_false_for_unknown(self):
        t = Tournament(title="T", scope="x")
        assert apply_preset(t, "no_such_preset") is False

    def test_apply_preset_for_known(self):
        @register_preset("regtest")
        def _f(_t):
            return [], "fmt"
        t = Tournament(title="T", scope="x")
        assert apply_preset(t, "regtest") is True
        assert t.format == "fmt"


# ---------------------------------------------------------------------------
# Integration test:
# LaunchTournamentMatch → match_handler.launch_match → completion_callback →
# Tournament.report_match_complete → node completes → finals launched.
# ---------------------------------------------------------------------------


class TestTournamentMatchHandlerIntegration:
    def test_full_callback_loop(self, tournament):
        @register_preset("integration_stub")
        def stub(_t):
            return [lambda tt, pp: StubGraph(tt, pp)], "Integration"
        tournament.preset("integration_stub")
        effects = tournament.begin()

        # Find a LaunchTournamentMatch effect to act on
        launch_effects = [e for e in effects if isinstance(e, LaunchTournamentMatch)]
        assert len(launch_effects) == 2
        first_launch = launch_effects[0]

        graph = tournament.current_phase()
        node = graph.nodes_by_id[first_launch.node_id]

        # Simulate the adapter wiring: register a completion callback that
        # routes the match result back into the tournament.
        def on_complete(match, winner, score):
            ordered = [match.scores.get(p, 0) for p in match.players]
            return tournament.report_match_complete(
                node_id=first_launch.node_id,
                winner_user_id=winner.uid.id if winner else None,
                score=ordered,
            )

        # Launch the underlying match via match_handler with the callback.
        actual_match = match_handler.launch_match(
            "rps",
            node.players,
            mode="versus",
            best_of=first_launch.best_of,
            label=first_launch.label,
            completion_callback=on_complete,
        )
        assert actual_match is not None
        assert id(actual_match) in match_handler.state.completion_callbacks

        # Wire the node ↔ match mapping the adapter would maintain.
        tournament_state.map_node_to_match(first_launch.node_id, id(actual_match))
        assert tournament_state.get_match_for_node(first_launch.node_id) == id(actual_match)

        # Simulate match completion: set the score on the match, then
        # invoke close_match (which fires the registered callback).
        actual_match.scores[node.players[0]] = 2
        actual_match.scores[node.players[1]] = 0
        # close_match needs at least the agents() interface; for RPS the
        # scores attribute already drives winner().
        close_effects = match_handler.close_match(actual_match)

        # After the callback fires, the node should be completed and the
        # second semi remains awake awaiting its own play-through.
        assert node.completed()
        assert node.score == [2, 0]

        # Callback was popped from match_handler state.
        assert id(actual_match) not in match_handler.state.completion_callbacks

    def test_callback_returns_effects(self, tournament):
        @register_preset("integration_effects")
        def stub(_t):
            return [lambda tt, pp: StubGraph(tt, pp)], "Integration"
        tournament.preset("integration_effects")
        effects = tournament.begin()
        launches = [e for e in effects if isinstance(e, LaunchTournamentMatch)]
        first = launches[0]
        graph = tournament.current_phase()
        node = graph.nodes_by_id[first.node_id]

        def on_complete(match, winner, score):
            ordered = [match.scores.get(p, 0) for p in match.players]
            return tournament.report_match_complete(
                node_id=first.node_id,
                winner_user_id=winner.uid.id if winner else None,
                score=ordered,
            )

        m = match_handler.launch_match(
            "rps", node.players, mode="versus",
            best_of=first.best_of, label=first.label,
            completion_callback=on_complete,
        )
        m.scores[node.players[0]] = 2
        m.scores[node.players[1]] = 0
        close_effects = match_handler.close_match(m)
        # The ArchiveTournamentMatch effect comes from complete_match via the callback
        assert any(isinstance(e, ArchiveTournamentMatch) for e in close_effects)
