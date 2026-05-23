"""Phase 5a tests — refactored axi/ladder.py Ladder as a MatchGraph subclass.

The existing codebase had ZERO direct Ladder tests. Phase 5a adds them.
Covers the five structural changes from docs/phase-5a-ladder_refactor-plan.md:
  - Circular import fixed (Ladder importable under conftest mocks).
  - Match→MatchNode bookkeeping.
  - time_fn injection (FakeClock for deterministic end_time + downtime).
  - MatchGraph inheritance + synthetic Tournament.
  - advance(match) / abort(match) Match→MatchNode adapter routing.

All tests use `duration_seconds=` kwarg to bypass pytimeparse (mocked
in conftest) and `time_fn=` for deterministic time.
"""

import pytest

from axi.effects import LaunchTournamentMatch
from axi.ladder import Ladder
from axi.match_graph import MatchGraph
from axi.match_node import MatchNode
from axi.tournament_state import state as tournament_state
from axi.util import (
    USER_STATUS_BREAK,
    USER_STATUS_CALLED,
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


class FakeGuild:
    id = 99
    name = "g"


def make_config():
    return {
        "name": "ladder1", "game": "rps", "format": "openskill",
        "queue-channel": "q1", "status-channel": "s1",
        "results-channel": "r1", "leaderboard-channel": "l1",
        "duration": "1h",
    }


def make_players(n, p1):
    return [type(p1)(f"p{i}", 1000 + i) for i in range(n)]


def _new_ladder(clock=None, duration=3600):
    if clock is None:
        clock = FakeClock()
    return Ladder(
        FakeGuild(), make_config(), scheduled_event=None,
        streamed=False, time_fn=clock.now, duration_seconds=duration,
    ), clock


@pytest.fixture(autouse=True)
def _clean_tournament_state():
    tournament_state.reset()
    yield
    tournament_state.reset()


# ---------------------------------------------------------------------------
# Regression: import cleanly under conftest mocks
# ---------------------------------------------------------------------------


class TestImportRegression:
    def test_direct_import_succeeds(self):
        # Phase 5a fix: no circular import between axi/ladder.py and
        # axi/handlers/ladder_handler.py under conftest's mock environment.
        from axi.ladder import Ladder
        assert Ladder is not None

    def test_ladder_is_match_graph_subclass(self):
        assert issubclass(Ladder, MatchGraph)


# ---------------------------------------------------------------------------
# Construction + begin()
# ---------------------------------------------------------------------------


class TestConstructAndBegin:
    def test_construct_with_time_fn(self):
        ladder, clock = _new_ladder()
        assert ladder._now() == 1000.0
        clock.advance(50)
        assert ladder._now() == 1050.0

    def test_construct_assigns_config_fields(self):
        ladder, _ = _new_ladder()
        assert ladder.name == "ladder1"
        assert ladder.game == "rps"
        assert ladder.fmt == "openskill"
        assert ladder.queue_channel == "q1"

    def test_begin_initializes_match_graph_structures(self):
        ladder, _ = _new_ladder()
        ladder.begin()
        assert hasattr(ladder, "matches_by_pair")
        assert hasattr(ladder, "matches_by_player")
        assert hasattr(ladder, "current_match_by_player")
        assert hasattr(ladder, "status_by_player")
        assert hasattr(ladder, "ratings_by_player")
        assert hasattr(ladder, "stream_history")
        assert hasattr(ladder, "called_matches")
        assert hasattr(ladder, "active_matches")
        assert hasattr(ladder, "past_matches")
        assert hasattr(ladder, "end_time")
        # MatchGraph base creates victory_node — never completes for Ladder.
        assert ladder.victory_node is not None
        assert not ladder.victory_node.completed()

    def test_generate_bracket_returns_empty(self):
        ladder, _ = _new_ladder()
        ladder.begin()
        assert ladder.generate_bracket() == []

    def test_end_time_uses_time_fn(self):
        clock = FakeClock(t=5000.0)
        ladder, _ = _new_ladder(clock=clock, duration=600)
        ladder.begin()
        assert ladder.end_time == 5600.0


# ---------------------------------------------------------------------------
# add_new_player + queue/dequeue
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    def test_add_new_player_pre_close(self, p1):
        ladder, _ = _new_ladder()
        ladder.begin()
        ok = ladder.add_new_player(p1)
        assert ok is True
        assert p1 in ladder.players
        assert ladder.status_by_player[p1] == USER_STATUS_BREAK

    def test_add_new_player_post_close_rejected(self, p1):
        clock = FakeClock()
        ladder, _ = _new_ladder(clock=clock, duration=10)
        ladder.begin()
        clock.advance(20)  # past end_time
        ok = ladder.add_new_player(p1)
        assert ok is False
        assert p1 not in ladder.players

    def test_queue_sets_queued(self, p1):
        ladder, _ = _new_ladder()
        ladder.begin()
        ladder.add_new_player(p1)
        ladder.queue(p1)
        assert ladder.status_by_player[p1] == USER_STATUS_QUEUED

    def test_dequeue_sets_break(self, p1):
        ladder, _ = _new_ladder()
        ladder.begin()
        ladder.add_new_player(p1)
        ladder.queue(p1)
        ladder.dequeue(p1)
        assert ladder.status_by_player[p1] == USER_STATUS_BREAK

    def test_queue_idempotent(self, p1):
        ladder, _ = _new_ladder()
        ladder.begin()
        ladder.add_new_player(p1)
        ladder.queue(p1)
        ladder.queue(p1)
        assert ladder.status_by_player[p1] == USER_STATUS_QUEUED


# ---------------------------------------------------------------------------
# matchmaking emits effects + MatchNode bookkeeping
# ---------------------------------------------------------------------------


class TestMatchmakingEmitsEffects:
    def _setup_two_players(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        ladder.add_new_player(p1)
        ladder.add_new_player(p2)
        ladder.queue(p1)
        ladder.queue(p2)
        return ladder

    def test_matchmaking_returns_nodes_and_effects(self, p1, p2):
        ladder = self._setup_two_players(p1, p2)
        nodes, effects = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        assert len(nodes) == 1
        # All match objects in `nodes` must be MatchNode, not raw Match.
        for n in nodes:
            assert isinstance(n, MatchNode)

    def test_matchmaking_emits_launch_tournament_match(self, p1, p2):
        ladder = self._setup_two_players(p1, p2)
        nodes, effects = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        launches = [e for e in effects if isinstance(e, LaunchTournamentMatch)]
        assert len(launches) == 1
        assert launches[0].graph_id == ladder.graph_id
        assert launches[0].players == [p1.uid.id, p2.uid.id]

    def test_matchmaking_creates_match_nodes_via_add_node(self, p1, p2):
        ladder = self._setup_two_players(p1, p2)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        # Each generated node must be tracked in nodes_by_id (from add_node).
        for n in nodes:
            assert n.node_id in ladder.nodes_by_id

    def test_matchmaking_node_carries_label_and_timer(self, p1, p2):
        ladder = self._setup_two_players(p1, p2)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        n = nodes[0]
        assert n.label == "LADDER MATCH"
        assert n.checkin_timer == 120

    def test_matchmaking_challenge_label(self, p1, p2):
        ladder = self._setup_two_players(p1, p2)
        nodes, _ = ladder.matchmaking([], [(p1, p2)], set_stream_match=False)
        assert nodes[0].label == "CHALLENGE MATCH"

    def test_no_matches_for_solo_player(self, p1):
        ladder, _ = _new_ladder()
        ladder.begin()
        ladder.add_new_player(p1)
        ladder.queue(p1)
        nodes, _ = ladder.matchmaking([], [], set_stream_match=False)
        assert nodes == []


# ---------------------------------------------------------------------------
# call_match transitions + downtime
# ---------------------------------------------------------------------------


class TestCallMatch:
    def test_call_match_sets_called_status(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        assert ladder.status_by_player[p1] == USER_STATUS_CALLED
        assert ladder.status_by_player[p2] == USER_STATUS_CALLED

    def test_call_match_registers_node_in_bookkeeping(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        n = nodes[0]
        assert n in ladder.called_matches
        assert n in ladder.matches_by_pair[p1][p2]
        assert n in ladder.matches_by_pair[p2][p1]
        assert n in ladder.matches_by_player[p1]
        assert n in ladder.matches_by_player[p2]
        assert ladder.current_match_by_player[p1] is n
        assert ladder.current_match_by_player[p2] is n


# ---------------------------------------------------------------------------
# complete_match lifecycle
# ---------------------------------------------------------------------------


class TestCompleteMatchLifecycle:
    def _setup_and_call(self, p1, p2):
        ladder, clock = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        return ladder, clock, nodes[0]

    def _set_winner(self, node, winner):
        from axi.util import MATCH_STATUS_COMPLETED
        idx = node.players.index(winner)
        score = [0, 0]
        score[idx] = node.first_to()
        node.score = score
        node.status = MATCH_STATUS_COMPLETED

    def test_autoqueue_off_routes_to_break(self, p1, p2):
        ladder, _, node = self._setup_and_call(p1, p2)
        # autoqueue is False by default
        self._set_winner(node, p1)
        ladder.complete_match(node)
        assert ladder.status_by_player[p1] == USER_STATUS_BREAK
        assert ladder.status_by_player[p2] == USER_STATUS_BREAK

    def test_autoqueue_on_routes_to_queue(self, p1, p2):
        ladder, _, node = self._setup_and_call(p1, p2)
        ladder.autoqueue_by_player[p1] = True
        ladder.autoqueue_by_player[p2] = True
        self._set_winner(node, p1)
        ladder.complete_match(node)
        assert ladder.status_by_player[p1] == USER_STATUS_QUEUED
        assert ladder.status_by_player[p2] == USER_STATUS_QUEUED

    def test_appends_to_past_matches(self, p1, p2):
        ladder, _, node = self._setup_and_call(p1, p2)
        self._set_winner(node, p1)
        ladder.complete_match(node)
        assert node in ladder.past_matches

    def test_clears_current_match_by_player(self, p1, p2):
        ladder, _, node = self._setup_and_call(p1, p2)
        self._set_winner(node, p1)
        ladder.complete_match(node)
        assert ladder.current_match_by_player[p1] is None
        assert ladder.current_match_by_player[p2] is None

    def test_removes_from_called_matches(self, p1, p2):
        ladder, _, node = self._setup_and_call(p1, p2)
        self._set_winner(node, p1)
        ladder.complete_match(node)
        assert node not in ladder.called_matches

    def test_not_completed_node_no_op(self, p1, p2):
        ladder, _, node = self._setup_and_call(p1, p2)
        # Don't complete the node.
        ladder.complete_match(node)
        assert node not in ladder.past_matches


# ---------------------------------------------------------------------------
# advance(match) Match→MatchNode adapter
# ---------------------------------------------------------------------------


class TestAdvanceAdapter:
    def test_advance_translates_match_to_node(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        node = nodes[0]

        # Simulate the adapter mapping. A fake Match-like object whose id()
        # is registered in tournament_state alongside this node.
        class FakeMatch:
            def __init__(self, players, score):
                self.players = list(players)
                self.score = list(score)
            def check_match_over(self):
                return True
            def winner(self):
                return self.players[0] if self.score[0] > self.score[1] else self.players[1]
            def first_to(self):
                return 2

        fm = FakeMatch([p1, p2], [2, 0])
        tournament_state.map_node_to_match(node.node_id, id(fm))

        ladder.advance(fm)
        # Node should be completed and routed through complete_match.
        assert node.completed()
        assert node in ladder.past_matches

    def test_advance_match_not_over_noop(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        node = nodes[0]

        class FakeMatch:
            def check_match_over(self):
                return False  # not over

        fm = FakeMatch()
        tournament_state.map_node_to_match(node.node_id, id(fm))
        ladder.advance(fm)
        assert node not in ladder.past_matches

    def test_abort_routes_to_cancel(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        node = nodes[0]

        class FakeMatch:
            pass

        fm = FakeMatch()
        tournament_state.map_node_to_match(node.node_id, id(fm))
        ladder.abort(fm)
        # Cancel removes from called_matches + clears current_match_by_player.
        assert node not in ladder.called_matches
        assert ladder.current_match_by_player[p1] is None
        assert ladder.current_match_by_player[p2] is None


# ---------------------------------------------------------------------------
# select_stream_match
# ---------------------------------------------------------------------------


class TestSelectStreamMatch:
    def test_picks_lowest_score(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        # Add 4 players so we can build 2 candidate matches.
        p3 = type(p1)("p3", 1003)
        p4 = type(p1)("p4", 1004)
        for p in (p1, p2, p3, p4):
            ladder.add_new_player(p)
            ladder.queue(p)
        # Set ratings: p1 == p2 (small diff) → preferred; p3 vs p4 has bigger gap.
        ladder.ratings_by_player[p1] = (100, ladder.initial_rating[1])
        ladder.ratings_by_player[p2] = (102, ladder.initial_rating[1])
        ladder.ratings_by_player[p3] = (100, ladder.initial_rating[1])
        ladder.ratings_by_player[p4] = (500, ladder.initial_rating[1])
        # Manually create two MatchNode candidates (bypass matchmaking).
        n1 = ladder.add_node(players=[p1, p2], game="rps", best_of=3, label="LADDER MATCH")
        n2 = ladder.add_node(players=[p3, p4], game="rps", best_of=3, label="LADDER MATCH")
        chosen = ladder.select_stream_match([n1, n2])
        assert chosen is n1

    def test_skips_recently_streamed_repeat(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        p3 = type(p1)("p3", 1003)
        p4 = type(p1)("p4", 1004)
        for p in (p1, p2, p3, p4):
            ladder.add_new_player(p)
            ladder.queue(p)
        # Same ratings — so the skip criterion is the deciding factor.
        for p in (p1, p2, p3, p4):
            ladder.ratings_by_player[p] = (100, ladder.initial_rating[1])
        # Build n1 with p1+p2 and put p1 in the last TWO stream_history.
        n_prev = ladder.add_node(players=[p1, p2], game="rps", best_of=3, label="LADDER MATCH")
        ladder.stream_history.append(n_prev)
        ladder.stream_history.append(n_prev)
        # n_a has p1 (recently streamed); n_b has p3+p4 (fresh).
        n_a = ladder.add_node(players=[p1, p2], game="rps", best_of=3, label="LADDER MATCH")
        n_b = ladder.add_node(players=[p3, p4], game="rps", best_of=3, label="LADDER MATCH")
        chosen = ladder.select_stream_match([n_a, n_b])
        assert chosen is n_b


# ---------------------------------------------------------------------------
# challenge(p0, p1)
# ---------------------------------------------------------------------------


class TestChallenge:
    def test_first_challenge_pending(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
        accepted, rejected = ladder.challenge(p1, p2)
        assert accepted is False
        assert rejected is False
        assert p2 in ladder.challenge_requests[p1]

    def test_reciprocal_challenge_accepted(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
        ladder.challenge(p1, p2)
        accepted, rejected = ladder.challenge(p2, p1)
        assert accepted is True
        assert rejected is False
        assert (p2, p1) in ladder.challenges_on_deck

    def test_rejected_after_3_or_more_pairs(self, p1, p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
        # Inject 3 dummy past matches between p1 and p2.
        for _ in range(3):
            n = ladder.add_node(players=[p1, p2], game="rps", best_of=3, label="LADDER MATCH")
            ladder.matches_by_pair[p1][p2].append(n)
            ladder.matches_by_pair[p2][p1].append(n)
        accepted, rejected = ladder.challenge(p1, p2)
        assert accepted is False
        assert rejected is True


# ---------------------------------------------------------------------------
# completed() time-based
# ---------------------------------------------------------------------------


class TestCompletedByTime:
    def test_pre_end_time_false(self):
        clock = FakeClock(t=1000.0)
        ladder, _ = _new_ladder(clock=clock, duration=600)
        ladder.begin()
        assert ladder.completed() is False

    def test_at_end_time_true(self):
        clock = FakeClock(t=1000.0)
        ladder, _ = _new_ladder(clock=clock, duration=600)
        ladder.begin()
        clock.advance(600)
        assert ladder.completed() is True

    def test_past_end_time_true(self):
        clock = FakeClock(t=1000.0)
        ladder, _ = _new_ladder(clock=clock, duration=600)
        ladder.begin()
        clock.advance(700)
        assert ladder.completed() is True

    def test_victory_node_stays_uncompleted(self):
        clock = FakeClock(t=1000.0)
        ladder, _ = _new_ladder(clock=clock, duration=600)
        ladder.begin()
        clock.advance(700)
        # completed() is True (time-based), but victory_node never completes.
        assert ladder.completed() is True
        assert not ladder.victory_node.completed()


# ---------------------------------------------------------------------------
# Autoqueue post-match routing
# ---------------------------------------------------------------------------


class TestAutoqueueRouting:
    def _setup_and_complete(self, p1, p2, autoqueue_p1, autoqueue_p2):
        ladder, _ = _new_ladder()
        ladder.begin()
        for p in (p1, p2):
            ladder.add_new_player(p)
            ladder.queue(p)
        ladder.autoqueue_by_player[p1] = autoqueue_p1
        ladder.autoqueue_by_player[p2] = autoqueue_p2
        nodes, _ = ladder.matchmaking([(p1, p2)], [], set_stream_match=False)
        node = nodes[0]
        from axi.util import MATCH_STATUS_COMPLETED
        node.score = [node.first_to(), 0]
        node.status = MATCH_STATUS_COMPLETED
        ladder.complete_match(node)
        return ladder

    def test_both_autoqueue(self, p1, p2):
        ladder = self._setup_and_complete(p1, p2, True, True)
        assert ladder.status_by_player[p1] == USER_STATUS_QUEUED
        assert ladder.status_by_player[p2] == USER_STATUS_QUEUED

    def test_neither_autoqueue(self, p1, p2):
        ladder = self._setup_and_complete(p1, p2, False, False)
        assert ladder.status_by_player[p1] == USER_STATUS_BREAK
        assert ladder.status_by_player[p2] == USER_STATUS_BREAK

    def test_mixed_autoqueue(self, p1, p2):
        ladder = self._setup_and_complete(p1, p2, True, False)
        assert ladder.status_by_player[p1] == USER_STATUS_QUEUED
        assert ladder.status_by_player[p2] == USER_STATUS_BREAK


# ---------------------------------------------------------------------------
# Synthetic Tournament invariants
# ---------------------------------------------------------------------------


class TestSyntheticTournament:
    def test_tournament_attached(self):
        ladder, _ = _new_ladder()
        assert ladder.tournament is not None
        assert ladder.tournament.title == "ladder1"
        assert ladder.tournament.scope == "q1"
        assert ladder.tournament_id is not None
        assert ladder.graph_id is not None

    def test_tournament_not_registered_in_state(self):
        ladder, _ = _new_ladder()
        # Ladder doesn't register itself in tournament_state's
        # scope_to_tournament map (it's its own session type).
        assert ladder.tournament_id not in tournament_state.tournaments
