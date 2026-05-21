"""Phase 2 tests — SingleElimination bracket format.

Covers bracket structure for sizes 2/4/7/8/16, BO5 escalation, stream
marking, loser_gets placement tiers, bye auto-resolution, and preset
registration.
"""

import pytest

from axi.effects import LaunchTournamentMatch
from axi.tournament import Tournament
from axi.tournament_presets import PRESETS, apply_preset
from axi.tournament_state import state as tournament_state
from axi.tournament_formats.single_elimination import (
    SingleElimination,
    _ByeUser,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_tournament_state():
    tournament_state.reset()
    yield
    tournament_state.reset()


def make_players(n, p1):
    """Build n FakeUsers; reuses the FakeUser class from p1 fixture."""
    return [type(p1)(f"p{i}", 1000 + i) for i in range(n)]


@pytest.fixture
def t(p1):
    """Tournament with a fixed RNG seed for reproducibility."""
    return Tournament(title="T", scope="s", seed=42)


# ---------------------------------------------------------------------------
# _ByeUser sentinel
# ---------------------------------------------------------------------------


class TestByeUser:
    def test_is_bye_true(self):
        assert _ByeUser(0).is_bye()

    def test_uid_id_is_negative(self):
        assert _ByeUser(0).uid.id == -1
        assert _ByeUser(5).uid.id == -6

    def test_str_repr_includes_index(self):
        b = _ByeUser(3)
        assert "__BYE__3" in str(b)
        assert "__BYE__3" in repr(b)


# ---------------------------------------------------------------------------
# Padding to power of 2
# ---------------------------------------------------------------------------


class TestPadding:
    def test_size_2_min_pads_to_4(self, t, p1):
        players = make_players(2, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 4

    def test_size_4_no_pad(self, t, p1):
        players = make_players(4, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 4

    def test_size_5_pads_to_8(self, t, p1):
        players = make_players(5, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 8

    def test_size_7_pads_to_8(self, t, p1):
        players = make_players(7, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 8
        # Exactly 1 bye added
        byes = [p for p in se.players if isinstance(p, _ByeUser)]
        assert len(byes) == 1

    def test_size_8_no_pad(self, t, p1):
        players = make_players(8, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 8

    def test_size_9_pads_to_16(self, t, p1):
        players = make_players(9, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 16

    def test_size_16_no_pad(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players)
        assert se.num_players == 16


# ---------------------------------------------------------------------------
# Bracket structure (size 2, 4, 8, 16)
# ---------------------------------------------------------------------------


def _all_bracket_nodes(se):
    return [n for n in se.nodes_by_id.values() if n.label != "VICTORY"]


class TestBracketStructure:
    def test_size_2_one_final(self, t, p1):
        players = make_players(2, p1)
        se = SingleElimination(t, players)
        se.begin()
        nodes = _all_bracket_nodes(se)
        # 2-player → padded to 4 → 3 nodes (2 semis + 1 final)
        assert len(nodes) == 3
        labels = sorted({n.label for n in nodes})
        assert labels == ["WINNERS FINALS", "WINNERS SEMIS"]

    def test_size_4_two_semis_one_final(self, t, p1):
        players = make_players(4, p1)
        se = SingleElimination(t, players)
        se.begin()
        nodes = _all_bracket_nodes(se)
        assert len(nodes) == 3
        semis = [n for n in nodes if n.label == "WINNERS SEMIS"]
        finals = [n for n in nodes if n.label == "WINNERS FINALS"]
        assert len(semis) == 2
        assert len(finals) == 1

    def test_size_8_quarters_semis_finals(self, t, p1):
        players = make_players(8, p1)
        se = SingleElimination(t, players)
        se.begin()
        nodes = _all_bracket_nodes(se)
        assert len(nodes) == 7
        assert sum(1 for n in nodes if n.label == "WINNERS QUARTERS") == 4
        assert sum(1 for n in nodes if n.label == "WINNERS SEMIS") == 2
        assert sum(1 for n in nodes if n.label == "WINNERS FINALS") == 1

    def test_size_16_full_bracket(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players)
        se.begin()
        nodes = _all_bracket_nodes(se)
        assert len(nodes) == 15
        assert sum(1 for n in nodes if n.label == "WINNERS ROUND 1") == 8
        assert sum(1 for n in nodes if n.label == "WINNERS QUARTERS") == 4
        assert sum(1 for n in nodes if n.label == "WINNERS SEMIS") == 2
        assert sum(1 for n in nodes if n.label == "WINNERS FINALS") == 1

    def test_final_links_to_victory(self, t, p1):
        players = make_players(8, p1)
        se = SingleElimination(t, players)
        se.begin()
        # victory_node should have exactly one parent: the finals match
        assert len(se.victory_node.parents) == 1
        parent_id = next(iter(se.victory_node.parents))
        parent = se.nodes_by_id[parent_id]
        assert parent.label == "WINNERS FINALS"


# ---------------------------------------------------------------------------
# Seeding: 1-vs-N pairing in round 1
# ---------------------------------------------------------------------------


class TestSeeding:
    def test_round1_pairs_top_vs_bottom(self, t, p1):
        players = make_players(8, p1)
        se = SingleElimination(t, players)
        se.begin()
        quarters = [n for n in se.nodes_by_id.values() if n.label == "WINNERS QUARTERS"]
        pairings = [tuple(sorted(p.uid.id for p in n.players)) for n in quarters]
        # Players IDs are 1000..1007. Standard SE pairing: (0,7),(1,6),(2,5),(3,4)
        expected = {
            (1000, 1007),
            (1001, 1006),
            (1002, 1005),
            (1003, 1004),
        }
        assert set(pairings) == expected


# ---------------------------------------------------------------------------
# BO5 escalation
# ---------------------------------------------------------------------------


class TestBO5Escalation:
    def test_default_bo5_threshold_8(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, bo5=8)
        se.begin()
        nodes = _all_bracket_nodes(se)
        # Rounds with temp_players <= 8 are BO5: quarters (8), semis (4), finals (2)
        # = 4 + 2 + 1 = 7 BO5 matches.
        # Round 1 has temp_players = 16, so BO3.
        bo5_count = sum(1 for n in nodes if n.best_of == 5)
        bo3_count = sum(1 for n in nodes if n.best_of == 3)
        assert bo5_count == 7
        assert bo3_count == 8

    def test_bo5_minus_one_dynamic(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, bo5=-1)
        se.begin()
        nodes = _all_bracket_nodes(se)
        # -1 maps to default threshold 8 (same as bo5=8)
        bo5_count = sum(1 for n in nodes if n.best_of == 5)
        assert bo5_count == 7

    def test_bo5_threshold_4(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, bo5=4)
        se.begin()
        nodes = _all_bracket_nodes(se)
        # Only rounds with temp_players <= 4 escalate: semis (4) + finals (2) = 3
        bo5_count = sum(1 for n in nodes if n.best_of == 5)
        assert bo5_count == 3

    def test_bo5_zero_disables(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, bo5=0)
        se.begin()
        nodes = _all_bracket_nodes(se)
        bo5_count = sum(1 for n in nodes if n.best_of == 5)
        assert bo5_count == 0


# ---------------------------------------------------------------------------
# Stream marking
# ---------------------------------------------------------------------------


class TestStreamMarking:
    def test_stream_false_no_marking(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, stream=False)
        se.begin()
        assert all(not n.streamed for n in _all_bracket_nodes(se))

    def test_stream_true_default_thresh_6(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, stream=True)
        # call generate_bracket directly (not begin()) to avoid stream-routing
        # so we can inspect node.streamed and stream_candidates without the
        # call_match_for_stream stripping them.
        se.create_data_structures()
        se.generate_bracket()
        nodes = _all_bracket_nodes(se)
        # Rounds with temp_players <= 6 (i.e. <= 4 in SE since rounds halve)
        # would be SEMIS (4) and FINALS (2) — 3 matches always streamed.
        # Plus the last match of each round (8-player round-1 last match,
        # quarters last, etc.) gets streamed too.
        streamed = [n for n in nodes if n.streamed]
        # Expect: 3 (semis+finals fully streamed) + 1 last-of-round-1 + 1 last quarter
        # = 5 streamed. Verify >= 3.
        assert len(streamed) >= 3
        # All semis + final must be streamed (temp_players <= 6)
        semis_finals = [n for n in nodes if n.label in ("WINNERS SEMIS", "WINNERS FINALS")]
        assert all(n.streamed for n in semis_finals)

    def test_stream_int_explicit_thresh(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players, stream=2)
        se.create_data_structures()
        se.generate_bracket()
        nodes = _all_bracket_nodes(se)
        # Only finals (temp_players=2) fully streamed; plus last-of-round bonus
        streamed = [n for n in nodes if n.streamed]
        # Finals is streamed (temp_players==2 <= threshold 2) AND it's the last of its round
        finals = [n for n in nodes if n.label == "WINNERS FINALS"]
        assert finals[0].streamed
        # Semis (temp_players=4) is NOT below thresh, but the last semi IS the last of its round
        semis = [n for n in nodes if n.label == "WINNERS SEMIS"]
        last_semi_streamed = any(n.streamed for n in semis)
        assert last_semi_streamed


# ---------------------------------------------------------------------------
# loser_gets placement tiers
# ---------------------------------------------------------------------------


class TestLoserGets:
    def test_size_16_loser_gets_per_round(self, t, p1):
        players = make_players(16, p1)
        se = SingleElimination(t, players)
        se.begin()
        nodes = _all_bracket_nodes(se)
        # Round-1 losers get tier 16, quarter losers 8, semi losers 4, finals loser 2
        by_label = {}
        for n in nodes:
            by_label.setdefault(n.label, set()).add(n.loser_gets)
        assert by_label["WINNERS ROUND 1"] == {16}
        assert by_label["WINNERS QUARTERS"] == {8}
        assert by_label["WINNERS SEMIS"] == {4}
        assert by_label["WINNERS FINALS"] == {2}


# ---------------------------------------------------------------------------
# Bye auto-resolution
# ---------------------------------------------------------------------------


class TestByeAutoResolve:
    def test_size_7_bye_auto_completes(self, t, p1):
        players = make_players(7, p1)
        se = SingleElimination(t, players)
        effects = se.begin()
        # Exactly 1 bye → exactly 1 round-1 match auto-resolves.
        # That match should be COMPLETED, not in called_matches.
        bye_match = next(
            n for n in se.nodes_by_id.values()
            if n.label == "WINNERS QUARTERS" and any(isinstance(p, _ByeUser) for p in n.players)
        )
        assert bye_match.completed()
        # The real player (non-bye) should be the winner
        real = next(p for p in bye_match.players if not isinstance(p, _ByeUser))
        assert bye_match.winner() is real
        # The match should appear in non_matches with reason "bye"
        assert bye_match.node_id in se.non_matches
        assert se.non_matches[bye_match.node_id] == "bye"


# ---------------------------------------------------------------------------
# Initial matches list & LaunchTournamentMatch effects
# ---------------------------------------------------------------------------


class TestInitialMatchesAndEffects:
    def test_size_8_emits_four_launch_effects(self, t, p1):
        players = make_players(8, p1)
        se = SingleElimination(t, players, stream=False)
        effects = se.begin()
        launches = [e for e in effects if isinstance(e, LaunchTournamentMatch)]
        # Round 1 has 4 matches; with stream=False, all 4 are launched.
        assert len(launches) == 4
        for e in launches:
            assert e.tournament_id == t.tournament_id
            assert e.graph_id == se.graph_id


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------


class TestPresetRegistration:
    def test_fast_preset_registered(self):
        assert "fast" in PRESETS

    def test_se_preset_registered(self):
        assert "se" in PRESETS

    def test_fast_preset_applies(self, t, p1):
        t.add_players(make_players(4, p1))
        assert apply_preset(t, "fast")
        assert t.format == "Single elimination."
        assert len(t.phase_fns) == 1
        # Factory should produce a SingleElimination instance
        graph = t.phase_fns[0](t, t.players)
        assert isinstance(graph, SingleElimination)

    def test_se_preset_applies(self, t, p1):
        t.add_players(make_players(4, p1))
        assert apply_preset(t, "se")
        assert t.format == "Single elimination."


# ---------------------------------------------------------------------------
# End-to-end: complete a 4-player bracket
# ---------------------------------------------------------------------------


class TestEndToEnd4Player:
    def test_complete_4_player_bracket(self, t, p1):
        players = make_players(4, p1)
        t.add_players(players)
        se = SingleElimination(t, players)
        se.begin()
        semis = [n for n in se.nodes_by_id.values() if n.label == "WINNERS SEMIS"]
        # Complete both semis with players[0] and players[2] winning their matches.
        # players are seeded so semis pair (0,3) and (1,2).
        for n in semis:
            top = min(n.players, key=lambda p: p.uid.id)
            # Determine the index of the winner so score reflects [winner_score, loser_score]
            if n.players[0] is top:
                n.score = [2, 0]
            else:
                n.score = [0, 2]
            se.complete_match(n)
        finals = next(n for n in se.nodes_by_id.values() if n.label == "WINNERS FINALS")
        assert finals.status != 0  # not asleep anymore — it's been called
        # Complete finals
        finals.score = [2, 1]
        se.complete_match(finals)
        # victory_node should be completed
        assert se.victory_node.completed()
        assert se.completed()
