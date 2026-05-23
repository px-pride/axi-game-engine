"""Phase 5b tests — LadderElimination(Ladder) lava-elimination tournament format.

Uses FakeClock via time_fn for deterministic lava-rise tests.
Reuses conftest.py mocks (Discord/openskill/numpy/pytimeparse).
Inherits Phase 5a Ladder; tests focus on the lava overrides + invariants.
"""

import pytest

from axi.effects import LaunchTournamentMatch, UpdateLavaUI
from axi.tournament import Tournament
from axi.tournament_formats.ladder_elimination import (
    LadderElimination,
    _ElementaryRatingModel,
    _Rating,
    _resolve_rating_model,
)
from axi.tournament_presets import PRESETS, apply_preset
from axi.tournament_state import state as tournament_state
from axi.util import (
    USER_STATUS_BREAK,
    USER_STATUS_CALLED,
    USER_STATUS_ELIMINATED,
    USER_STATUS_QUEUED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = float(t)

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture(autouse=True)
def _clean_state():
    tournament_state.reset()
    yield
    tournament_state.reset()


@pytest.fixture
def t():
    """Default tournament with non-rps game so bo3/5/7 + 360/480 timers apply."""
    tt = Tournament(title="LE", scope="s", seed=42)
    tt.game = "thread_game"
    return tt


@pytest.fixture
def t_rps():
    """Tournament with game='rps' for testing the RPS-specific bo13/21/29 +
    120/240 escalation path."""
    tt = Tournament(title="LE-RPS", scope="s", seed=42)
    tt.game = "rps"
    return tt


@pytest.fixture
def clock():
    return FakeClock()


def make_players(n, p1, start_id=1000):
    return [type(p1)(f"p{i}", start_id + i) for i in range(n)]


def _le(tournament, players, clock, **kwargs):
    kwargs.setdefault("rating_model", "elementary")
    kwargs.setdefault("time_fn", clock.now)
    return LadderElimination(tournament, players, **kwargs)


def _set_ratings(le, players_by_rating):
    """Top of list = highest rating."""
    n = len(players_by_rating)
    for i, p in enumerate(players_by_rating):
        rating_val = (n - i) * 100
        le.ratings_by_player[p] = (rating_val, _Rating(mu=rating_val, sigma=10))


def _complete(graph, node, winner):
    from axi.util import MATCH_STATUS_COMPLETED
    idx = node.players.index(winner)
    ft = node.first_to() if node.first_to() > 0 else 1
    score = [0, 0]
    score[idx] = ft
    node.score = score
    node.status = MATCH_STATUS_COMPLETED
    return graph.complete_match(node)


# ---------------------------------------------------------------------------
# USER_STATUS_ELIMINATED constant
# ---------------------------------------------------------------------------


class TestUtilConstant:
    def test_user_status_eliminated_value(self):
        assert USER_STATUS_ELIMINATED == 3

    def test_distinct_from_others(self):
        assert (USER_STATUS_QUEUED, USER_STATUS_CALLED,
                USER_STATUS_BREAK, USER_STATUS_ELIMINATED) == (0, 1, 2, 3)


# ---------------------------------------------------------------------------
# Rating model resolution
# ---------------------------------------------------------------------------


class TestRatingModelResolution:
    def test_elementary(self):
        (threshold, rating), cls = _resolve_rating_model("elementary")
        assert threshold == 0
        assert isinstance(rating, _Rating)
        assert rating.mu == 300.0
        assert cls is _ElementaryRatingModel

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            _resolve_rating_model("bogus")

    def test_elementary_model_deltas(self):
        m = _ElementaryRatingModel([_Rating(300, 100), _Rating(300, 100)])
        assert m.calculate_deltas() == [[1.0, -0.01], [-1.0, -0.01]]


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_defaults(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock)
        assert le.lava_delay == 150
        assert abs(le.lava_rate - (1 / 6)) < 1e-9
        assert le.matchmaking_num_hypotheses == 100
        assert le.rating_num_epochs == 10
        assert le.rating_learning_rate == 2.0
        assert le.sweep_bonus == 1.0
        assert le.bo3_penalty == 0.8
        assert le.matchup_regularization == 1.0
        assert le.checkin_normal == 360
        assert le.checkin_break == 480
        assert le.checkin_rps == 240

    def test_custom_kwargs_propagate(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock,
                 lava_delay=10, lava_rate=0.5,
                 matchmaking_num_hypotheses=5,
                 rating_num_epochs=3,
                 sweep_bonus=2.0,
                 checkin_normal=100, checkin_break=200, checkin_rps=50)
        assert le.lava_delay == 10
        assert le.lava_rate == 0.5
        assert le.matchmaking_num_hypotheses == 5
        assert le.rating_num_epochs == 3
        assert le.sweep_bonus == 2.0
        assert le.checkin_normal == 100
        assert le.checkin_break == 200
        assert le.checkin_rps == 50

    def test_repr(self, t, clock, p1):
        le = _le(t, make_players(2, p1), clock)
        assert repr(le) == "LADDER ELIMINATION"


# ---------------------------------------------------------------------------
# Placement tiers (Fibonacci)
# ---------------------------------------------------------------------------


class TestPlacementTiers:
    def test_two_players(self, t, clock, p1):
        le = _le(t, make_players(2, p1), clock)
        le.create_data_structures()
        assert le.placement_tiers == [1, 2]

    def test_eight_players(self, t, clock, p1):
        le = _le(t, make_players(8, p1), clock)
        le.create_data_structures()
        assert le.placement_tiers == [1, 2, 3, 5, 8]

    def test_fifteen_players(self, t, clock, p1):
        le = _le(t, make_players(15, p1), clock)
        le.create_data_structures()
        assert le.placement_tiers == [1, 2, 3, 5, 8, 13, 21]

    def test_one_hundred_players(self, t, clock, p1):
        le = _le(t, make_players(100, p1), clock)
        le.create_data_structures()
        assert le.placement_tiers[-1] >= 100
        for i in range(2, len(le.placement_tiers)):
            assert le.placement_tiers[i] == le.placement_tiers[i - 1] + le.placement_tiers[i - 2]


# ---------------------------------------------------------------------------
# Lava timer + level
# ---------------------------------------------------------------------------


class TestLavaTimer:
    def test_negative_before_delay(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock, lava_delay=100)
        le.create_data_structures()
        assert le.get_lava_timer() == -100.0

    def test_positive_after_delay(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock, lava_delay=100)
        le.create_data_structures()
        clock.advance(150)
        assert le.get_lava_timer() == 50.0


class TestLavaLevel:
    def test_pre_lava_returns_negative(self, t, clock, p1):
        le = _le(t, make_players(8, p1), clock, lava_delay=100)
        le.create_data_structures()
        assert le.get_lava_level() < 0
        assert le.lava_snapshot == -1
        assert le.placement_snapshot == -1

    def test_post_lava_eight_players(self, t, clock, p1):
        # tiers [1,2,3,5,8] + player_count=8 → source min-clamp: lava=8 placement=6
        le = _le(t, make_players(8, p1), clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        assert le.get_lava_level() == 8
        assert le.lava_snapshot == 8
        assert le.placement_snapshot == 6

    def test_post_lava_ten_players(self, t, clock, p1):
        # tiers [1,2,3,5,8,13] + player_count=10 → min-clamp: lava=10
        le = _le(t, make_players(10, p1), clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        assert le.get_lava_level() == 10
        assert le.placement_snapshot == 9

    def test_snapshot_recomputes_after_player_count_drops(self, t, clock, p1):
        le = _le(t, make_players(8, p1), clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        _ = le.get_lava_level()
        assert le.lava_snapshot == 8
        le.player_count = 5
        new_lava = le.get_lava_level()
        # tiers[1,2,3,5,8] + 5 players → lava=5, placement=4
        assert new_lava == 5
        assert le.placement_snapshot == 4


# ---------------------------------------------------------------------------
# Eliminate user
# ---------------------------------------------------------------------------


class TestEliminatePlacement:
    def test_uses_snapshot_when_set(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()  # placement_snapshot = 6
        assert le.placement_snapshot == 6
        le.eliminate_user(players[5])
        assert le.placements_dict[players[5]] == 6
        assert le.status_by_player[players[5]] == USER_STATUS_ELIMINATED

    def test_walks_tiers_when_no_snapshot(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        assert le.placement_snapshot == -1
        le.eliminate_user(players[5])
        assert le.placements_dict[players[5]] > 0

    def test_idempotent(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()
        le.eliminate_user(players[3])
        le.eliminate_user(players[3])
        assert le.player_count == 3

    def test_decrements_player_count(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()
        le.eliminate_user(players[3])
        assert le.player_count == 3


# ---------------------------------------------------------------------------
# Afloat / drowning partition
# ---------------------------------------------------------------------------


class TestAfloatDrowning:
    def test_pre_lava_all_afloat(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        afloat, drowning = le.afloat_and_drowning(list(players), [])
        assert set(afloat) == set(players)
        assert drowning == []

    def test_post_lava_bottom_drowning(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        afloat, drowning = le.afloat_and_drowning(list(players), [])
        assert len(drowning) >= 1
        assert players[-1] in drowning

    def test_endgame_count3_only_bottom_two_drowning(self, t, clock, p1):
        players = make_players(3, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        afloat, drowning = le.afloat_and_drowning(list(players), [])
        assert len(drowning) == 2
        assert len(afloat) == 1
        assert players[0] in afloat


# ---------------------------------------------------------------------------
# Match labels
# ---------------------------------------------------------------------------


class TestMatchLabels:
    def test_pre_lava_all_ladder_match(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]],
            drowning=[],
            set_stream_match=False,
        )
        assert matches[0].label == "LADDER MATCH"

    def test_danger_match_one_drowning(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[-1])],
            afloat=[players[0]],
            drowning=[players[-1]],
            set_stream_match=False,
        )
        assert matches[0].label == "DANGER MATCH"
        assert matches[0].players[1] == players[-1]

    def test_danger_swaps_to_idx1_if_first(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[-1], players[0])],
            afloat=[players[0]],
            drowning=[players[-1]],
            set_stream_match=False,
        )
        assert matches[0].label == "DANGER MATCH"
        assert matches[0].players[1] == players[-1]
        assert matches[0].players[0] == players[0]

    def test_double_danger_both_drowning(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[-2], players[-1])],
            afloat=[],
            drowning=[players[-2], players[-1]],
            set_stream_match=False,
        )
        assert matches[0].label == "DOUBLE DANGER"

    def test_losers_finals_count3(self, t, clock, p1):
        players = make_players(3, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[1], players[2])],
            afloat=[players[0]],
            drowning=[players[1], players[2]],
            set_stream_match=False,
        )
        assert matches[0].label == "LOSERS FINALS"

    def test_grand_finals_count2(self, t, clock, p1):
        players = make_players(2, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[],
            drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        assert matches[0].label == "GRAND FINALS"


# ---------------------------------------------------------------------------
# best_of escalation
# ---------------------------------------------------------------------------


class TestBestOfEscalation:
    def test_pre_lava_bo3(self, t, clock, p1):
        players = make_players(10, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 3

    def test_over_eight_post_lava_bo3(self, t, clock, p1):
        players = make_players(10, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 3

    def test_eight_post_lava_bo5(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 5

    def test_final_two_post_lava_bo7(self, t, clock, p1):
        players = make_players(2, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[], drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        assert matches[0].best_of == 7

    def test_rps_bo13_normal(self, t_rps, clock, p1):
        players = make_players(10, p1)
        le = _le(t_rps, players, clock, lava_delay=10_000)
        le.create_data_structures()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 13

    def test_rps_bo21_top8(self, t_rps, clock, p1):
        players = make_players(8, p1)
        le = _le(t_rps, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 21

    def test_rps_bo29_final2(self, t_rps, clock, p1):
        players = make_players(2, p1)
        le = _le(t_rps, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[], drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        assert matches[0].best_of == 29


# ---------------------------------------------------------------------------
# Checkin timer
# ---------------------------------------------------------------------------


class TestCheckinTimer:
    def test_normal_360s(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 360

    def test_break_480s(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        le.take_a_break(players[1]) if hasattr(le, "take_a_break") else None
        le.status_by_player[players[1]] = USER_STATUS_BREAK
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 480

    def test_rps_normal_120s(self, t_rps, clock, p1):
        players = make_players(4, p1)
        le = _le(t_rps, players, clock)
        le.create_data_structures()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 120

    def test_rps_break_240s(self, t_rps, clock, p1):
        players = make_players(4, p1)
        le = _le(t_rps, players, clock)
        le.create_data_structures()
        le.status_by_player[players[1]] = USER_STATUS_BREAK
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[players[0]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 240


# ---------------------------------------------------------------------------
# UpdateLavaUI effect emission
# ---------------------------------------------------------------------------


class TestUpdateLavaUIEffect:
    def test_emitted_from_matchmaking(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        nodes, effects = le.matchmaking()
        lava_effects = [e for e in effects if isinstance(e, UpdateLavaUI)]
        assert len(lava_effects) == 1
        assert lava_effects[0].tournament_id == le.tournament_id
        assert lava_effects[0].graph_id == le.graph_id

    def test_emitted_from_begin(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        effects = le.begin()
        assert any(isinstance(e, UpdateLavaUI) for e in effects)


# ---------------------------------------------------------------------------
# complete_match lifecycle
# ---------------------------------------------------------------------------


class TestCompleteMatchLifecycle:
    def test_ladder_match_no_elimination(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10_000,
                 matchmaking_num_hypotheses=1)
        le.begin()
        active = [n for n in le.nodes_by_id.values()
                  if n.label == "LADDER MATCH" and n.awake()]
        assert active
        node = active[0]
        winner = node.players[0]
        loser = node.players[1]
        _complete(le, node, winner)
        assert le.status_by_player[winner] != USER_STATUS_ELIMINATED
        assert le.status_by_player[loser] != USER_STATUS_ELIMINATED
        assert le.player_count == 6

    def test_danger_match_loser_eliminated(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[-1])],
            afloat=[players[0]], drowning=[players[-1]],
            set_stream_match=False,
        )
        node = matches[0]
        assert node.label == "DANGER MATCH"
        le.call_match(node)
        drowning_player = node.players[1]
        winner = node.players[0]
        _complete(le, node, winner)
        assert le.status_by_player[drowning_player] == USER_STATUS_ELIMINATED
        assert le.player_count == 7

    def test_double_danger_loser_eliminated(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[-2], players[-1])],
            afloat=[], drowning=[players[-2], players[-1]],
            set_stream_match=False,
        )
        node = matches[0]
        assert node.label == "DOUBLE DANGER"
        le.call_match(node)
        winner = node.players[0]
        loser = node.players[1]
        _complete(le, node, winner)
        assert le.status_by_player[loser] == USER_STATUS_ELIMINATED
        assert le.status_by_player[winner] != USER_STATUS_ELIMINATED

    def test_grand_finals_completes_victory_node(self, t, clock, p1):
        players = make_players(2, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket_for(
            pairings=[(players[0], players[1])],
            afloat=[], drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        node = matches[0]
        assert node.label == "GRAND FINALS"
        le.call_match(node)
        winner = node.players[0]
        _complete(le, node, winner)
        assert le.victory_node.completed()
        assert le.placements_dict[winner] == 1


# ---------------------------------------------------------------------------
# update_ratings (10-epoch override)
# ---------------------------------------------------------------------------


class TestUpdateRatings:
    def test_no_completed_matches_no_op(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        initial_threshold = le.ratings_by_player[players[0]][0]
        le.update_ratings()
        assert le.ratings_by_player[players[0]][0] == initial_threshold

    def test_winner_threshold_above_loser(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10_000,
                 matchmaking_num_hypotheses=1)
        le.begin()
        active = [n for n in le.nodes_by_id.values()
                  if n.label == "LADDER MATCH" and n.awake()]
        assert active
        node = active[0]
        winner = node.players[0]
        loser = node.players[1]
        _complete(le, node, winner)
        assert le.ratings_by_player[winner][0] > le.ratings_by_player[loser][0]


# ---------------------------------------------------------------------------
# add_new_player gate
# ---------------------------------------------------------------------------


class TestAddNewPlayer:
    def test_accepted_pre_lava(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        newbie = type(p1)("newbie", 9999)
        accepted = le.add_new_player(newbie)
        assert accepted is True
        assert newbie in le.players

    def test_rejected_post_lava(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()
        newbie = type(p1)("late", 8888)
        accepted = le.add_new_player(newbie)
        assert accepted is False
        assert newbie not in le.players


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------


class TestPresetRegistration:
    def test_px_in_presets(self):
        assert "px" in PRESETS

    def test_apply_preset_sets_phase_fns(self, t):
        ok = apply_preset(t, "px")
        assert ok is True
        assert len(t.phase_fns) == 1
        assert "px" in t.format.lower() or "ladder" in t.format.lower()


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_bracket_to_victory(self, t, p1):
        clock = FakeClock()
        players = make_players(4, p1)
        t.add_players(players)

        def factory(tt, ps):
            return LadderElimination(
                tt, ps, stream=False,
                rating_model="elementary",
                time_fn=clock.now,
                lava_delay=1,
                matchmaking_num_hypotheses=1,
            )
        t.phase_fns = [factory]
        t.format = "Ladder elimination."
        effects = t.begin()
        assert any(isinstance(e, LaunchTournamentMatch) for e in effects)
        assert any(isinstance(e, UpdateLavaUI) for e in effects)
        phase = t.current_phase()
        assert isinstance(phase, LadderElimination)
        # Run-to-victory loop.
        safety = 50
        while not phase.victory_node.completed() and safety > 0:
            clock.advance(5)
            active = [n for n in phase.nodes_by_id.values()
                      if n.awake() and n.label != "VICTORY"]
            if not active:
                phase.matchmaking()
                safety -= 1
                continue
            for node in list(active):
                if node.completed() or not node.awake():
                    continue
                _complete(phase, node, node.players[0])
            safety -= 1
        assert phase.victory_node.completed()
        winner = phase.victory_node.players[0]
        assert phase.placements_dict[winner] == 1


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    def test_completed_false_initially(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock)
        le.create_data_structures()
        assert le.completed() is False

    def test_completed_requires_one_player_and_lava(self, t, clock, p1):
        players = make_players(2, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()
        le.eliminate_user(players[1])
        assert le.completed() is True
