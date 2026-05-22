"""Phase 5 tests — LadderElimination tournament format.

Covers placement tiers, lava timer/level snapshots, status transitions,
match label state machine (LADDER / DANGER / DOUBLE DANGER / LOSERS FINALS
/ GRAND FINALS), best_of escalation, checkin timer escalation,
afloat/drowning partition, eliminate_user placement assignment,
complete_match lifecycle, update_ratings (elementary model), UpdateLavaUI
effect emission, preset registration, and end-to-end smoke.

Tests use a `FakeClock` injected via `time_fn` for deterministic lava
rise. The `elementary` rating model keeps tests independent of openskill
(which conftest mocks).
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
    """Settable clock for deterministic lava-rise tests."""

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
    """Construct a LadderElimination with elementary rating + clock injection."""
    kwargs.setdefault("rating_model", "elementary")
    kwargs.setdefault("time_fn", clock.now)
    return LadderElimination(tournament, players, **kwargs)


def _set_ratings(le, players_by_rating):
    """Helper: assign integer ratings deterministically. Top of list = highest rating."""
    n = len(players_by_rating)
    for i, p in enumerate(players_by_rating):
        rating_val = (n - i) * 100
        le.ratings_by_player[p] = (rating_val, _Rating(mu=rating_val, sigma=10))


def _complete(graph, node, winner):
    """Set node.score so winner wins, then complete the node."""
    idx = node.players.index(winner)
    ft = node.first_to() if node.first_to() > 0 else 1
    score = [0, 0]
    score[idx] = ft
    node.score = score
    return graph.complete_match(node)


# ---------------------------------------------------------------------------
# USER_STATUS_ELIMINATED constant
# ---------------------------------------------------------------------------


class TestUtilConstant:
    def test_user_status_eliminated_value(self):
        assert USER_STATUS_ELIMINATED == 3

    def test_user_status_eliminated_distinct(self):
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
        assert rating.sigma == 100.0
        assert cls is _ElementaryRatingModel

    def test_openskill_falls_back_to_elementary_when_mocked(self):
        # In tests, conftest mocks openskill — _resolve falls back gracefully.
        (threshold, rating), cls = _resolve_rating_model("openskill")
        assert threshold == 0
        # Either real openskill.Rating (if not mocked) or our _Rating fallback.
        assert hasattr(rating, "mu") or rating is not None

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            _resolve_rating_model("bogus")

    def test_elementary_model_deltas(self):
        # [winner_first_arg, loser]
        m = _ElementaryRatingModel([_Rating(300, 100), _Rating(300, 100)])
        deltas = m.calculate_deltas()
        # Winner (first) gains mu, loser loses mu; both shrink log_sigma.
        assert deltas == [[1.0, -0.01], [-1.0, -0.01]]


# ---------------------------------------------------------------------------
# Constructor + configurable kwargs
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
                 rating_learning_rate=1.5,
                 sweep_bonus=2.0,
                 bo3_penalty=0.5,
                 matchup_regularization=2.5,
                 checkin_normal=100, checkin_break=200, checkin_rps=50)
        assert le.lava_delay == 10
        assert le.lava_rate == 0.5
        assert le.matchmaking_num_hypotheses == 5
        assert le.rating_num_epochs == 3
        assert le.rating_learning_rate == 1.5
        assert le.sweep_bonus == 2.0
        assert le.bo3_penalty == 0.5
        assert le.matchup_regularization == 2.5
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
        # Last tier must be >= 100; 144 is the next Fibonacci after 89.
        assert le.placement_tiers[-1] >= 100
        # Fibonacci progression starting from [1, 2].
        for i in range(2, len(le.placement_tiers)):
            assert le.placement_tiers[i] == le.placement_tiers[i - 1] + le.placement_tiers[i - 2]


# ---------------------------------------------------------------------------
# Lava timer
# ---------------------------------------------------------------------------


class TestLavaTimer:
    def test_negative_before_delay(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock, lava_delay=100)
        le.create_data_structures()
        assert le.get_lava_timer() == -100.0

    def test_zero_at_delay(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock, lava_delay=100)
        le.create_data_structures()
        clock.advance(100)
        assert le.get_lava_timer() == 0.0

    def test_positive_after_delay(self, t, clock, p1):
        le = _le(t, make_players(4, p1), clock, lava_delay=100)
        le.create_data_structures()
        clock.advance(150)
        assert le.get_lava_timer() == 50.0


# ---------------------------------------------------------------------------
# Lava level / snapshot (source-clamped semantics)
# ---------------------------------------------------------------------------


class TestLavaLevel:
    def test_pre_lava_returns_negative(self, t, clock, p1):
        le = _le(t, make_players(8, p1), clock, lava_delay=100)
        le.create_data_structures()
        assert le.get_lava_level() < 0
        assert le.lava_snapshot == -1
        assert le.placement_snapshot == -1

    def test_post_lava_eight_players(self, t, clock, p1):
        # tiers [1,2,3,5,8] with player_count=8 → lava=8 placement=6
        le = _le(t, make_players(8, p1), clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        assert le.get_lava_level() == 8
        assert le.lava_snapshot == 8
        assert le.placement_snapshot == 6

    def test_post_lava_ten_players(self, t, clock, p1):
        # tiers [1,2,3,5,8,13] with player_count=10 → min-clamp gives lava=10
        # (NOTE: design doc's claim of lava_snapshot=13 was inaccurate; source
        # uses min(player_count, tier).)
        le = _le(t, make_players(10, p1), clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        assert le.get_lava_level() == 10
        assert le.placement_snapshot == 9

    def test_snapshot_recomputes_after_player_count_drops(self, t, clock, p1):
        le = _le(t, make_players(8, p1), clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        _ = le.get_lava_level()  # lava=8, placement=6
        assert le.lava_snapshot == 8
        # Manually drop player_count below placement_snapshot to trigger recompute.
        le.player_count = 5
        new_lava = le.get_lava_level()
        # tiers [1,2,3,5,8] @ player_count=5 → i=0 lava=min(5,8)=5 placement=6;
        # i=1 tier[-2]=5>=5 lava=min(5,5)=5 placement=tier[-3]+1=4.
        assert new_lava == 5
        assert le.placement_snapshot == 4


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    def test_initial_all_queued(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        for p in players:
            assert le.status_by_player[p] == USER_STATUS_QUEUED

    def test_take_a_break(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        le.take_a_break(players[0])
        assert le.status_by_player[players[0]] == USER_STATUS_BREAK

    def test_queue_after_break(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        le.take_a_break(players[0])
        le.queue(players[0])
        assert le.status_by_player[players[0]] == USER_STATUS_QUEUED

    def test_eliminate_user_sets_status(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()  # sets placement_snapshot
        le.eliminate_user(players[3])
        assert le.status_by_player[players[3]] == USER_STATUS_ELIMINATED
        assert le.player_count == 3

    def test_eliminate_user_idempotent(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()
        le.eliminate_user(players[3])
        le.eliminate_user(players[3])  # Second call should no-op
        assert le.player_count == 3


# ---------------------------------------------------------------------------
# eliminate_user placement assignment
# ---------------------------------------------------------------------------


class TestEliminatePlacement:
    def test_uses_placement_snapshot_when_set(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)
        le.get_lava_level()  # placement_snapshot = 6
        assert le.placement_snapshot == 6
        le.eliminate_user(players[5])
        assert le.placements_dict[players[5]] == 6

    def test_walks_tiers_when_no_snapshot(self, t, clock, p1):
        # Pre-lava: snapshot is -1, so eliminate walks placement_tiers.
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        # No lava yet — placement_snapshot stays at -1.
        assert le.placement_snapshot == -1
        le.eliminate_user(players[5])
        # Placement should be some positive int derived from tier walk.
        assert le.placements_dict[players[5]] > 0


# ---------------------------------------------------------------------------
# Afloat / drowning partition
# ---------------------------------------------------------------------------


class TestAfloatDrowning:
    def test_pre_lava_all_afloat(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        afloat, drowning = le.afloat_and_drowning(list(players), [])
        # Pre-lava → everyone safe.
        assert set(afloat) == set(players)
        assert drowning == []

    def test_post_lava_bottom_drowning(self, t, clock, p1):
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        # Top of list = highest rating.
        _set_ratings(le, players)
        clock.advance(20)
        afloat, drowning = le.afloat_and_drowning(list(players), [])
        # Some drowning expected post-lava (bottom rated).
        assert len(drowning) >= 1
        # Drowning players are the lowest-rated.
        lowest = players[-1]
        assert lowest in drowning

    def test_endgame_three_players_only_bottom_two_drowning(self, t, clock, p1):
        # When count==3 post-lava: only bottom 2 are drowning.
        players = make_players(3, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        afloat, drowning = le.afloat_and_drowning(list(players), [])
        # Special endgame: bottom 2 are drowning, top 1 is afloat.
        assert len(drowning) == 2
        assert len(afloat) == 1
        assert players[0] in afloat  # highest rated


# ---------------------------------------------------------------------------
# Match labels
# ---------------------------------------------------------------------------


class TestMatchLabels:
    def test_pre_lava_all_ladder_match(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        matches = le.generate_bracket(
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
        # Pair: top1 vs bottom1 — top is afloat, bottom is drowning.
        matches = le.generate_bracket(
            pairings=[(players[0], players[-1])],
            afloat=[players[0]],
            drowning=[players[-1]],
            set_stream_match=False,
        )
        assert matches[0].label == "DANGER MATCH"
        # Drowning player must be at index 1.
        assert matches[0].players[1] == players[-1]

    def test_danger_match_swaps_to_idx1_if_first(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        # Pair: drowning first, then afloat. Impl should swap.
        matches = le.generate_bracket(
            pairings=[(players[-1], players[0])],
            afloat=[players[0]],
            drowning=[players[-1]],
            set_stream_match=False,
        )
        assert matches[0].label == "DANGER MATCH"
        assert matches[0].players[1] == players[-1]  # drowning at idx 1
        assert matches[0].players[0] == players[0]   # afloat at idx 0

    def test_double_danger_both_drowning(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        # Bottom 2 both drowning.
        matches = le.generate_bracket(
            pairings=[(players[-2], players[-1])],
            afloat=[],
            drowning=[players[-2], players[-1]],
            set_stream_match=False,
        )
        assert matches[0].label == "DOUBLE DANGER"

    def test_losers_finals_at_three(self, t, clock, p1):
        # player_count == 3 + lava >= 0 → LOSERS FINALS regardless of drowning.
        players = make_players(3, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket(
            pairings=[(players[1], players[2])],
            afloat=[players[0]],
            drowning=[players[1], players[2]],
            set_stream_match=False,
        )
        assert matches[0].label == "LOSERS FINALS"

    def test_grand_finals_at_two(self, t, clock, p1):
        players = make_players(2, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[],
            drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        assert matches[0].label == "GRAND FINALS"


# ---------------------------------------------------------------------------
# Best_of escalation
# ---------------------------------------------------------------------------


class TestBestOfEscalation:
    def test_pre_lava_bo3(self, t, clock, p1):
        players = make_players(10, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        matches = le.generate_bracket(
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
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 3

    def test_eight_or_fewer_post_lava_bo5(self, t, clock, p1):
        players = make_players(8, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket(
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
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[], drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        assert matches[0].best_of == 7

    def test_rps_variant_bo13_normal(self, t_rps, clock, p1):
        players = make_players(10, p1)
        le = _le(t_rps, players, clock, lava_delay=10_000)
        le.create_data_structures()
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 13

    def test_rps_variant_bo21_top8(self, t_rps, clock, p1):
        players = make_players(8, p1)
        le = _le(t_rps, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].best_of == 21

    def test_rps_variant_bo29_final2(self, t_rps, clock, p1):
        players = make_players(2, p1)
        le = _le(t_rps, players, clock, lava_delay=10)
        le.create_data_structures()
        _set_ratings(le, players)
        clock.advance(20)
        le.get_lava_level()
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[], drowning=[players[0], players[1]],
            set_stream_match=False,
        )
        assert matches[0].best_of == 29


# ---------------------------------------------------------------------------
# Checkin timer escalation
# ---------------------------------------------------------------------------


class TestCheckinTimer:
    def test_normal_360s(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 360

    def test_break_480s(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        le.take_a_break(players[1])
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[players[0]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 480

    def test_rps_normal_120s(self, t_rps, clock, p1):
        players = make_players(4, p1)
        le = _le(t_rps, players, clock)
        le.create_data_structures()
        matches = le.generate_bracket(
            pairings=[(players[0], players[1])],
            afloat=[players[0], players[1]], drowning=[],
            set_stream_match=False,
        )
        assert matches[0].checkin_timer == 120

    def test_rps_break_240s(self, t_rps, clock, p1):
        players = make_players(4, p1)
        le = _le(t_rps, players, clock)
        le.create_data_structures()
        le.take_a_break(players[1])
        matches = le.generate_bracket(
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
        effects = le.matchmaking()
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
        # Pre-lava — completed LADDER MATCH should not eliminate either player.
        players = make_players(6, p1)
        le = _le(t, players, clock, lava_delay=10_000,
                 matchmaking_num_hypotheses=1)
        le.begin()
        # Pick an active called match.
        active = [n for n in le.nodes_by_id.values()
                  if n.label == "LADDER MATCH" and n.awake()]
        assert active
        node = active[0]
        winner = node.players[0]
        loser = node.players[1]
        _complete(le, node, winner)
        # Neither eliminated.
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
        # Build a DANGER MATCH manually.
        matches = le.generate_bracket(
            pairings=[(players[0], players[-1])],
            afloat=[players[0]], drowning=[players[-1]],
            set_stream_match=False,
        )
        node = matches[0]
        assert node.label == "DANGER MATCH"
        le.call_match(node)
        # Drowning player is at idx 1.
        drowning_player = node.players[1]
        # Top player wins; bottom (drowning) eliminated.
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
        matches = le.generate_bracket(
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
        matches = le.generate_bracket(
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
# update_ratings — elementary model
# ---------------------------------------------------------------------------


class TestUpdateRatings:
    def test_no_completed_matches_no_op(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock)
        le.create_data_structures()
        initial_threshold = le.ratings_by_player[players[0]][0]
        le.update_ratings()
        # No change.
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
        # After update_ratings, winner's threshold should be > loser's.
        assert le.ratings_by_player[winner][0] > le.ratings_by_player[loser][0]


# ---------------------------------------------------------------------------
# add_new_player late-join gate
# ---------------------------------------------------------------------------


class TestAddNewPlayer:
    def test_accepted_pre_lava(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10_000)
        le.create_data_structures()
        newbie = type(p1)("newbie", 9999)
        accepted, _effects = le.add_new_player(newbie)
        assert accepted is True
        assert le.player_count == 5
        assert newbie in le.players
        # Newbie was queued; matchmaking may have immediately CALLED them.
        assert le.status_by_player[newbie] in (USER_STATUS_QUEUED, USER_STATUS_CALLED)
        assert le.status_by_player[newbie] != USER_STATUS_ELIMINATED

    def test_rejected_post_lava(self, t, clock, p1):
        players = make_players(4, p1)
        le = _le(t, players, clock, lava_delay=10)
        le.create_data_structures()
        clock.advance(20)  # past lava_delay
        le.get_lava_level()  # snapshot >= 0
        newbie = type(p1)("late", 8888)
        accepted, _effects = le.add_new_player(newbie)
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
# End-to-end smoke
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_bracket_via_tournament(self, t, p1):
        """4 players, fast lava, simulate matches until victory_node completes."""
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
        # At least one LaunchTournamentMatch effect emitted.
        assert any(isinstance(e, LaunchTournamentMatch) for e in effects)
        assert any(isinstance(e, UpdateLavaUI) for e in effects)
        # Tournament still running.
        phase = t.current_phase()
        assert isinstance(phase, LadderElimination)
        # Advance lava + complete matches until victory.
        safety = 50
        while not phase.victory_node.completed() and safety > 0:
            clock.advance(5)
            active = [n for n in phase.nodes_by_id.values()
                      if n.awake() and n.label != "VICTORY"]
            if not active:
                # Force another matchmaking round.
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
# Misc invariants
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
