"""Phase 3 tests — DoubleElimination bracket format.

Covers bracket structure (4/8/16 players), winners→losers L-flag linkage,
GRAND FINALS + DEADASS FINALS lifecycle, reset short-circuit when WF wins
GF, winner_loser_split DQ behavior, snake swap, placement tiers, labels,
BO5 escalation (DE bo5=-1 = all BO5), stream marking, presets.
"""

import pytest

from axi.tournament import Tournament
from axi.tournament_formats.double_elimination import DoubleElimination
from axi.tournament_formats.single_elimination import _ByeUser
from axi.tournament_presets import PRESETS, apply_preset
from axi.tournament_state import state as tournament_state
from axi.util import MATCH_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_tournament_state():
    tournament_state.reset()
    yield
    tournament_state.reset()


def make_players(n, p1):
    return [type(p1)(f"p{i}", 1000 + i) for i in range(n)]


@pytest.fixture
def t(p1):
    return Tournament(title="T", scope="s", seed=42)


def _bracket_nodes(de):
    return [n for n in de.nodes_by_id.values() if n.label != "VICTORY"]


def _by_label(de, label):
    return [n for n in de.nodes_by_id.values() if n.label == label]


# ---------------------------------------------------------------------------
# Bracket structure
# ---------------------------------------------------------------------------


class TestBracketStructure:
    def test_size_4_structure(self, t, p1):
        de = DoubleElimination(t, make_players(4, p1))
        de.begin()
        counts = {n.label: 0 for n in de.nodes_by_id.values()}
        for n in de.nodes_by_id.values():
            counts[n.label] += 1
        assert counts.get("WINNERS SEMIS") == 2
        assert counts.get("WINNERS FINALS") == 1
        assert counts.get("LOSERS SEMIS") == 1
        assert counts.get("LOSERS FINALS") == 1
        assert counts.get("GRAND FINALS") == 1
        assert counts.get("DEADASS FINALS") == 1
        # Total bracket = 7 (excluding VICTORY)
        assert len(_bracket_nodes(de)) == 7

    def test_size_8_structure(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1))
        de.begin()
        nodes = _bracket_nodes(de)
        assert len(nodes) == 15
        # 8-player has GF + Reset + LF
        assert _by_label(de, "GRAND FINALS")
        assert _by_label(de, "DEADASS FINALS")
        assert _by_label(de, "LOSERS FINALS")
        assert len(_by_label(de, "WINNERS QUARTERS")) == 4
        assert len(_by_label(de, "WINNERS SEMIS")) == 2
        assert len(_by_label(de, "WINNERS FINALS")) == 1

    def test_size_16_structure(self, t, p1):
        de = DoubleElimination(t, make_players(16, p1))
        de.begin()
        nodes = _bracket_nodes(de)
        assert len(nodes) == 31
        assert len(_by_label(de, "WINNERS ROUND 1")) == 8
        assert len(_by_label(de, "WINNERS QUARTERS")) == 4
        assert len(_by_label(de, "WINNERS SEMIS")) == 2
        assert len(_by_label(de, "WINNERS FINALS")) == 1
        assert _by_label(de, "GRAND FINALS")
        assert _by_label(de, "DEADASS FINALS")
        assert _by_label(de, "LOSERS FINALS")


# ---------------------------------------------------------------------------
# Winners → losers linkage
# ---------------------------------------------------------------------------


class TestWinnersLosersLinkage:
    def test_lb_round1_receives_l_from_wb(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1))
        de.begin()
        # Find a losers round-1 node (label "LOSERS ROUND 1") and verify
        # both its parents are linked with "L" flag, pointing to winners
        # bracket round-1 nodes.
        lb_r1 = _by_label(de, "LOSERS ROUND 1")
        assert lb_r1, "Expected LOSERS ROUND 1 matches"
        for lb_node in lb_r1:
            parent_flags = list(lb_node.parents.values())
            assert all(f == "L" for f in parent_flags), \
                f"LB R1 node should have all L parents, got {parent_flags}"
            # Each parent must be a WINNERS bracket round-1 node
            for pid in lb_node.parents:
                parent = de.nodes_by_id[pid]
                assert parent.label.startswith("WINNERS"), \
                    f"LB R1 parent should be in winners bracket, got {parent.label}"


# ---------------------------------------------------------------------------
# Grand Finals + Deadass Finals lifecycle
# ---------------------------------------------------------------------------


def _complete_node(graph, node, winner_idx):
    """Set score so player at winner_idx wins, then complete."""
    score = [0, 0]
    score[winner_idx] = node.first_to() if node.first_to() > 0 else 1
    node.score = score
    return graph.complete_match(node)


def _play_through_to_finals(de, wb_winners="top", lb_winners="bottom"):
    """Helper: complete all WB and LB matches up to (but not including) GF.

    wb_winners: 'top' = player at index 0 wins each WB match.
    lb_winners: 'top' or 'bottom' — for symmetry, default bottom-index player wins LB.
    """
    # Iteratively complete matches that are CALLED (status==1) and have both players.
    # Stop when only GF/Reset remain awake.
    safety_iter = 200
    while safety_iter > 0:
        safety_iter -= 1
        # Find any awake match (status CALLED or ACTIVE) that has 2 players and is not GF/Reset.
        candidate = None
        for n in de.nodes_by_id.values():
            if n.label in ("GRAND FINALS", "DEADASS FINALS", "VICTORY"):
                continue
            if n.awake() and len(n.players) == 2:
                candidate = n
                break
        if candidate is None:
            return
        # Decide winner based on which side has the higher-seeded player.
        # For simplicity, the player whose uid.id is lower wins (top-seed).
        if wb_winners == "top":
            top = min(candidate.players, key=lambda p: p.uid.id)
            idx = candidate.players.index(top)
        else:
            top = max(candidate.players, key=lambda p: p.uid.id)
            idx = candidate.players.index(top)
        _complete_node(de, candidate, idx)


class TestGrandFinalsLifecycle:
    def test_wf_wins_gf_short_circuits_reset(self, t, p1):
        de = DoubleElimination(t, make_players(4, p1))
        de.begin()
        # Run through bracket; top-seed always wins, so WF winner is players[0]
        _play_through_to_finals(de, wb_winners="top", lb_winners="top")
        gf = _by_label(de, "GRAND FINALS")[0]
        reset = _by_label(de, "DEADASS FINALS")[0]
        # GF should now have 2 players
        assert len(gf.players) == 2
        # Player 0 (top seed, WF winner) should be in GF
        wf = de._wf
        assert wf.winner() in gf.players
        # Make WF winner win GF too
        wf_winner = wf.winner()
        idx = gf.players.index(wf_winner)
        _complete_node(de, gf, idx)
        # Reset should be completed via short-circuit
        assert reset.completed()
        # Victory node should be completed with WF winner
        assert de.victory_node.completed()
        assert wf_winner in de.victory_node.players

    def test_lf_wins_gf_launches_reset(self, t, p1):
        de = DoubleElimination(t, make_players(4, p1))
        de.begin()
        _play_through_to_finals(de)
        gf = _by_label(de, "GRAND FINALS")[0]
        reset = _by_label(de, "DEADASS FINALS")[0]
        wf = de._wf
        lf_winner_in_gf = next(p for p in gf.players if p is not wf.winner())
        # LF winner wins GF
        idx = gf.players.index(lf_winner_in_gf)
        _complete_node(de, gf, idx)
        # Reset should NOT be short-circuited — it should now be in a callable state
        # (its parents have completed, so it should be active or have players populated)
        assert not reset.completed()
        # Reset should have both WF winner AND GF winner in players
        assert wf.winner() in reset.players
        assert lf_winner_in_gf in reset.players


# ---------------------------------------------------------------------------
# winner_loser_split DQ behavior
# ---------------------------------------------------------------------------


class TestWinnerLoserSplit:
    def test_no_split_no_dq(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1), winner_loser_split=None)
        de.begin()
        # No matches in non_matches with dq reason
        dq_reasons = [r for r in de.non_matches.values() if r == "dq"]
        assert len(dq_reasons) == 0

    def test_split_4_dqs_bottom_seeds_8player(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1), winner_loser_split=4)
        de.begin()
        # Seeds 4-7 should be DQ'd
        dq_reasons = [r for r in de.non_matches.values() if r == "dq"]
        assert len(dq_reasons) == 4

    def test_even_split_triggers_snake_swap(self, t, p1):
        players = make_players(8, p1)
        # Save original player order
        original_ids = [p.uid.id for p in players]
        de = DoubleElimination(t, players, winner_loser_split=4)
        # After construction, players[4..7] should be snake-swapped.
        new_ids = [p.uid.id for p in de.players if not isinstance(p, _ByeUser)]
        # Top 4 unchanged
        assert new_ids[:4] == original_ids[:4]
        # Bottom 4: pairs (4,5) → (5,4); (6,7) → (7,6)
        assert new_ids[4] == original_ids[5]
        assert new_ids[5] == original_ids[4]
        assert new_ids[6] == original_ids[7]
        assert new_ids[7] == original_ids[6]


# ---------------------------------------------------------------------------
# Placement tiers
# ---------------------------------------------------------------------------


class TestPlacementTiers:
    def test_loser_gets_per_round_8player(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1))
        de.begin()
        # WB loser_gets:
        # - WINNERS QUARTERS (temp_players=8) → 8
        # - WINNERS SEMIS (4) → 4
        # - WINNERS FINALS (2) → 2
        wq = _by_label(de, "WINNERS QUARTERS")
        assert all(n.loser_gets == 8 for n in wq)
        ws = _by_label(de, "WINNERS SEMIS")
        assert all(n.loser_gets == 4 for n in ws)
        wf = _by_label(de, "WINNERS FINALS")
        assert wf[0].loser_gets == 2

    def test_grand_finals_loser_gets_2(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1))
        de.begin()
        gf = _by_label(de, "GRAND FINALS")[0]
        reset = _by_label(de, "DEADASS FINALS")[0]
        assert gf.loser_gets == 2
        assert reset.loser_gets == 2


# ---------------------------------------------------------------------------
# BO5 escalation: bo5=-1 means all BO5
# ---------------------------------------------------------------------------


class TestBO5:
    def test_bo5_minus_one_all_bo5_4player(self, t, p1):
        de = DoubleElimination(t, make_players(4, p1), bo5=-1)
        de.begin()
        bracket_nodes = _bracket_nodes(de)
        assert all(n.best_of == 5 for n in bracket_nodes)

    def test_bo5_minus_one_all_bo5_8player(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1), bo5=-1)
        de.begin()
        assert all(n.best_of == 5 for n in _bracket_nodes(de))

    def test_bo5_explicit_zero_no_bo5(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1), bo5=0)
        de.begin()
        # bo5=0 → bo5_threshold=0 → no BO5 escalation in WB or LB.
        # But GF and reset are hardcoded BO5 (per source).
        for n in _bracket_nodes(de):
            if n.label in ("GRAND FINALS", "DEADASS FINALS"):
                assert n.best_of == 5
            else:
                assert n.best_of == 3, f"{n.label}: expected BO3, got BO{n.best_of}"


# ---------------------------------------------------------------------------
# Stream marking
# ---------------------------------------------------------------------------


class TestStreamMarking:
    def test_stream_false_no_marking(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1), stream=False)
        de.begin()
        assert all(not n.streamed for n in _bracket_nodes(de))

    def test_stream_true_gf_reset_streamed(self, t, p1):
        de = DoubleElimination(t, make_players(8, p1), stream=6)
        de.create_data_structures()
        de.generate_bracket()
        gf = _by_label(de, "GRAND FINALS")[0]
        reset = _by_label(de, "DEADASS FINALS")[0]
        assert gf.streamed
        assert reset.streamed


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------


class TestPresetRegistration:
    def test_classic_de_side_registered(self):
        assert "classic" in PRESETS
        assert "de" in PRESETS
        assert "side" in PRESETS

    def test_apply_classic_preset(self, t, p1):
        t.add_players(make_players(4, p1))
        assert apply_preset(t, "classic")
        assert t.format == "Double elimination."
        # The factory should produce a DoubleElimination instance
        graph = t.phase_fns[0](t, t.players)
        assert isinstance(graph, DoubleElimination)

    def test_apply_side_preset(self, t, p1):
        t.add_players(make_players(4, p1))
        assert apply_preset(t, "side")
        assert t.format == "Double elimination."
