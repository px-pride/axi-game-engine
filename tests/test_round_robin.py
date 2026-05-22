"""Phase 4 tests — RoundRobin tournament format with pools.

Covers pool distribution (snake/modulo), Berger polygon all-vs-all
scheduling, padding to even pool sizes, tiebreaker cascade (2-way H2H,
3-way ring spawn, N-way RPS spawn), pool_id tagging, reduce_double_jeopardy
snake swap, and composite preset registration (pool, standard, top4,
top6, grands, daily, phase2).
"""

import pytest

from axi.tournament import Tournament
from axi.tournament_formats.double_elimination import DoubleElimination
from axi.tournament_formats.round_robin import (
    RoundRobin,
    _calc_num_pools,
)
from axi.tournament_formats.single_elimination import _ByeUser
from axi.tournament_presets import PRESETS, apply_preset
from axi.tournament_state import state as tournament_state


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


def _pool_match_nodes(rr):
    return [n for n in rr.nodes_by_id.values()
            if n.label != "VICTORY" and getattr(n, "pool_id", None) is not None
            and "TIEBREAKER" not in n.label]


def _tiebreaker_nodes(rr):
    return [n for n in rr.nodes_by_id.values() if "TIEBREAKER" in n.label]


def _complete_with_winner(graph, node, winner):
    """Set node.score so `winner` (must be in node.players) wins."""
    idx = node.players.index(winner)
    ft = node.first_to() if node.first_to() > 0 else 1
    score = [0, 0]
    score[idx] = ft
    node.score = score
    return graph.complete_match(node)


# ---------------------------------------------------------------------------
# Padding
# ---------------------------------------------------------------------------


class TestPadding:
    def test_4_players_1_pool_no_pad(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1)
        assert rr.num_players == 4
        byes = [p for p in rr.players if isinstance(p, _ByeUser)]
        assert len(byes) == 0

    def test_5_players_1_pool_pads_to_6(self, t, p1):
        rr = RoundRobin(t, make_players(5, p1), num_pools=1)
        assert rr.num_players == 6
        byes = [p for p in rr.players if isinstance(p, _ByeUser)]
        assert len(byes) == 1

    def test_3_players_1_pool_pads_to_4(self, t, p1):
        rr = RoundRobin(t, make_players(3, p1), num_pools=1)
        assert rr.num_players == 4
        byes = [p for p in rr.players if isinstance(p, _ByeUser)]
        assert len(byes) == 1

    def test_8_players_2_pools_no_pad(self, t, p1):
        rr = RoundRobin(t, make_players(8, p1), num_pools=2)
        assert rr.num_players == 8

    def test_7_players_2_pools_pads_to_8(self, t, p1):
        rr = RoundRobin(t, make_players(7, p1), num_pools=2)
        # ceil(7 / (2*2)) * 2 = ceil(1.75)*2 = 2*2 = 4 per pool, total 8
        assert rr.num_players == 8


# ---------------------------------------------------------------------------
# Pool distribution
# ---------------------------------------------------------------------------


class TestPoolDistribution:
    def test_snake_seeding_2_pools_8_players(self, t, p1):
        rr = RoundRobin(t, make_players(8, p1), num_pools=2,
                        snake_seeding=True)
        rr.begin()
        # Snake with num_pools=2:
        # i=0 → pool 0 (seed 1)
        # i=1 → pool 1 (seed 2)
        # i=2 → pool 1 (seed 3) [2*2-1-2=1]
        # i=3 → pool 0 (seed 4) [2*2-1-3=0]
        # i=4 → pool 0 (seed 5)
        # i=5 → pool 1 (seed 6)
        # i=6 → pool 1 (seed 7)
        # i=7 → pool 0 (seed 8)
        assert rr.players_by_pool[0] == [
            rr.players[0], rr.players[3], rr.players[4], rr.players[7]
        ]
        assert rr.players_by_pool[1] == [
            rr.players[1], rr.players[2], rr.players[5], rr.players[6]
        ]

    def test_modulo_seeding_2_pools_8_players(self, t, p1):
        rr = RoundRobin(t, make_players(8, p1), num_pools=2,
                        snake_seeding=False)
        rr.begin()
        # Modulo: i % num_pools
        assert rr.players_by_pool[0] == [
            rr.players[0], rr.players[2], rr.players[4], rr.players[6]
        ]
        assert rr.players_by_pool[1] == [
            rr.players[1], rr.players[3], rr.players[5], rr.players[7]
        ]

    def test_snake_seeding_4_pools_16_players(self, t, p1):
        rr = RoundRobin(t, make_players(16, p1), num_pools=4,
                        snake_seeding=True)
        rr.begin()
        # Snake with 4 pools:
        # Round 0 (i=0..3): pools 0,1,2,3 (seeds 1,2,3,4)
        # Round 1 (i=4..7): pools 3,2,1,0 (seeds 5,6,7,8)
        # Round 2 (i=8..11): pools 0,1,2,3 (seeds 9,10,11,12)
        # Round 3 (i=12..15): pools 3,2,1,0 (seeds 13,14,15,16)
        assert rr.pool_id_by_player[rr.players[0]] == 0  # seed 1
        assert rr.pool_id_by_player[rr.players[1]] == 1  # seed 2
        assert rr.pool_id_by_player[rr.players[2]] == 2  # seed 3
        assert rr.pool_id_by_player[rr.players[3]] == 3  # seed 4
        assert rr.pool_id_by_player[rr.players[4]] == 3  # seed 5 (wrap)
        assert rr.pool_id_by_player[rr.players[5]] == 2  # seed 6
        assert rr.pool_id_by_player[rr.players[6]] == 1  # seed 7
        assert rr.pool_id_by_player[rr.players[7]] == 0  # seed 8
        assert rr.pool_id_by_player[rr.players[8]] == 0  # seed 9 (wrap)


# ---------------------------------------------------------------------------
# Berger schedule: all-vs-all in pool
# ---------------------------------------------------------------------------


class TestBergerSchedule:
    def _collect_pool_pairs(self, rr, pool_id):
        """Return set of frozensets — one per match — for matches in pool_id."""
        pairs = set()
        for n in _pool_match_nodes(rr):
            if n.pool_id != pool_id:
                continue
            pairs.add(frozenset(n.players))
        return pairs

    def test_4_player_pool_6_matches(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1)
        rr.begin()
        pool_matches = [n for n in _pool_match_nodes(rr) if n.pool_id == 0]
        # C(4, 2) = 6
        assert len(pool_matches) == 6

    def test_4_player_pool_all_pairs(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1)
        rr.begin()
        pairs = self._collect_pool_pairs(rr, 0)
        # All 6 distinct pairs of 4 players
        expected = set()
        for i in range(4):
            for j in range(i + 1, 4):
                expected.add(frozenset([rr.players[i], rr.players[j]]))
        assert pairs == expected

    def test_6_player_pool_15_matches(self, t, p1):
        rr = RoundRobin(t, make_players(6, p1), num_pools=1)
        rr.begin()
        pool_matches = [n for n in _pool_match_nodes(rr) if n.pool_id == 0]
        # C(6, 2) = 15
        assert len(pool_matches) == 15

    def test_6_player_pool_all_pairs(self, t, p1):
        rr = RoundRobin(t, make_players(6, p1), num_pools=1)
        rr.begin()
        pairs = self._collect_pool_pairs(rr, 0)
        expected = set()
        for i in range(6):
            for j in range(i + 1, 6):
                expected.add(frozenset([rr.players[i], rr.players[j]]))
        assert pairs == expected

    def test_8_player_pool_28_matches(self, t, p1):
        rr = RoundRobin(t, make_players(8, p1), num_pools=1)
        rr.begin()
        pool_matches = [n for n in _pool_match_nodes(rr) if n.pool_id == 0]
        # C(8, 2) = 28
        assert len(pool_matches) == 28

    def test_5_player_pool_with_bye(self, t, p1):
        rr = RoundRobin(t, make_players(5, p1), num_pools=1)
        rr.begin()
        # 5 players padded to 6 (one bye). C(5, 2) real + bye matches.
        # Real player pair count = C(5, 2) = 10
        pairs = self._collect_pool_pairs(rr, 0)
        real_pairs = {p for p in pairs
                      if not any(isinstance(x, _ByeUser) for x in p)}
        assert len(real_pairs) == 10


# ---------------------------------------------------------------------------
# Pool ID tagging
# ---------------------------------------------------------------------------


class TestPoolIdTagging:
    def test_all_pool_matches_have_pool_id(self, t, p1):
        rr = RoundRobin(t, make_players(8, p1), num_pools=2)
        rr.begin()
        for n in _pool_match_nodes(rr):
            assert n.pool_id is not None
            assert n.pool_id in (0, 1)

    def test_victory_node_has_no_pool_id(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1)
        rr.begin()
        assert rr.victory_node.pool_id is None


# ---------------------------------------------------------------------------
# Tiebreaker cascade
# ---------------------------------------------------------------------------


def _play_pool_with_outcomes(rr, pool_id, outcomes):
    """Iteratively complete callable matches in this pool, picking winners
    from outcomes: {frozenset({p_a, p_b}): winner_player}. Missing pairs
    default to the first listed player winning.
    """
    safety = 100
    while safety > 0:
        safety -= 1
        candidate = None
        for n in _pool_match_nodes(rr):
            if n.pool_id != pool_id:
                continue
            if n.awake() and len(n.players) == 2:
                candidate = n
                break
        if candidate is None:
            return
        pair = frozenset(candidate.players)
        if pair in outcomes:
            winner = outcomes[pair]
        else:
            winner = candidate.players[0]
        _complete_with_winner(rr, candidate, winner)


class TestTiebreakerCascade2Way:
    def test_2_way_h2h_resolves_no_tiebreaker(self, t, p1):
        # 4 players, 1 pool. Make 2 players tie on set_wins, but H2H
        # between them is decisive → no tiebreaker spawned.
        players = make_players(4, p1)
        rr = RoundRobin(t, players, num_pools=1)
        rr.begin()
        p_a, p_b, p_c, p_d = players
        # Construct outcomes so a and b both go 2-1, but a beats b.
        # a beats b, a beats c, d beats a → a: 2W, 1L
        # b beats c, b beats d → b: 2W (lost to a) → 2W, 1L
        # c beats d → c: 1W
        # d: 1W (vs a)
        outcomes = {
            frozenset({p_a, p_b}): p_a,
            frozenset({p_a, p_c}): p_a,
            frozenset({p_a, p_d}): p_d,
            frozenset({p_b, p_c}): p_b,
            frozenset({p_b, p_d}): p_b,
            frozenset({p_c, p_d}): p_c,
        }
        _play_pool_with_outcomes(rr, 0, outcomes)
        # No tiebreakers should be spawned (H2H resolves a > b)
        tbs = _tiebreaker_nodes(rr)
        assert len(tbs) == 0


class TestTiebreakerCascade3Way:
    def test_3_way_ring_spawned(self, t, p1):
        # Construct 3-way tie via rock-paper-scissors cycle.
        # 4 players: a beats b, b beats c, c beats a; all beat d.
        # → a, b, c each go 2-1; d goes 0-3.
        # H2H within {a,b,c}: a beats b (1), b beats c (1), c beats a (1)
        #   → all 1-1 in H2H within pod → unresolved by H2H.
        # GPW likely tied (BO3 2-1 each) → falls through to spawning ring.
        players = make_players(4, p1)
        rr = RoundRobin(t, players, num_pools=1)
        rr.begin()
        p_a, p_b, p_c, p_d = players
        outcomes = {
            frozenset({p_a, p_b}): p_a,
            frozenset({p_b, p_c}): p_b,
            frozenset({p_c, p_a}): p_c,
            frozenset({p_a, p_d}): p_a,
            frozenset({p_b, p_d}): p_b,
            frozenset({p_c, p_d}): p_c,
        }
        _play_pool_with_outcomes(rr, 0, outcomes)
        # Should spawn 3 tiebreaker matches (ring: a→b, b→c, c→a)
        tbs = _tiebreaker_nodes(rr)
        # All labels say POOLS TIEBREAKER, and there are 3
        pool_tbs = [n for n in tbs if n.label == "POOLS TIEBREAKER"]
        assert len(pool_tbs) == 3, f"Expected 3 ring tiebreakers, got {len(pool_tbs)}"
        # All BO1
        for m in pool_tbs:
            assert m.best_of == 1
        # All tagged to pool 0
        for m in pool_tbs:
            assert m.pool_id == 0


class TestTiebreakerCascadeNWay:
    def test_4_way_rps_spawned(self, t, p1):
        # Construct a 4-way perfect tie: each player goes exactly 1.5 wins?
        # In a 4-player round-robin, each plays 3 matches. For 4-way tie
        # they each need same set_wins. Possible only if all go 1.5-1.5 —
        # impossible with integer scores. So minimal 4-way tie requires
        # more players. Use 6-player pool to construct it.
        #
        # Easier: 6 players, contrive so 4 are tied on (set_wins, gpw).
        # Use a 4-cycle: a→b, b→c, c→d, d→a; plus each beats e and f
        # equally and loses one to each other.
        players = make_players(6, p1)
        rr = RoundRobin(t, players, num_pools=1)
        rr.begin()
        a, b, c, d, e, f = players
        # Cycle among a/b/c/d such that each wins 1 of 3 in-pod matches.
        # a beats b, b beats c, c beats d, d beats a: that's only 4 matches.
        # Remaining a-c, b-d: a beats c, b beats d.
        # → a: beats b,c (2W), lost to d (1L) → 2W within pod
        # → b: beats c,d (2W), lost to a (1L) → 2W within pod
        # → c: beats d (1W), lost to a,b (2L) → 1W within pod
        # → d: beats a (1W), lost to b,c (2L) → 1W within pod
        # That gives 2-2 tie not 4-way. Let me redo for 4-way.
        #
        # Cycle: a→b, b→c, c→d, d→a (1 win each in cycle)
        # Cross: a→c (a wins, b loses), b→d (b wins, c loses) — adds wins
        # Use: a→b, b→c, c→d, d→a, c→a, d→b
        # → a: 2W (b, ?) lost to c,d
        #   a beats b: W. d beats a: L. c beats a: L. → 1W, 2L
        # → b: beats c, lost to a, lost to d. → 1W, 2L
        # → c: beats d, beats a, lost to b. → 2W, 1L
        # → d: beats a, beats b, lost to c. → 2W, 1L
        # That's a 2-2 split too. With even-number rounds, 4-way ties
        # at 1.5 are not achievable. Skip exact 4-way; test that N-way RPS
        # spawning works when 4+ players land in the same TIE bucket via
        # forcing draws somehow. Actually, the code spawns N-way RPS when
        # pod size >= 2 and != 3. So a 4-way is exercised if we manufacture
        # one. With 6-player pool, build:
        # a,b,c,d all 1-2 (each lost to e and f, plus internal cycles
        # making them all tied at 1W within their group).
        # e: beats everyone except f. → 5W, 0L if also beats f
        # Simplified: just construct a 4-way set_wins tie however possible.
        #
        # 6-player pool: each plays 5. If a,b,c,d all go 1-4: each gets 1W.
        # Distribute: e beats a,b,c,d (4W); f beats a,b,c,d (4W); e vs f: e wins.
        # → e: 5W, f: 4W, a,b,c,d each need 1W
        # Among a,b,c,d (6 matches), distribute 4 wins: each gets 1, two
        # of them get 1.5 — impossible. So a,b,c,d play 6 in-group matches,
        # distributing 6 wins. Each can get 1.5 — impossible. So minimum
        # uneven. Skip exact construction.
        #
        # Just test that the spawning HAPPENS by manufacturing pods directly
        # in _spawn_nway_rps via mock pod.
        from collections import defaultdict
        # Directly invoke _spawn_nway_rps with a pod of 4 to check it produces
        # one match with 4 players.
        pod = [a, b, c, d]
        effects = rr._spawn_nway_rps(pool_id=0, pod=pod)
        # Should have created one RPS TIEBREAKER node with all 4 players
        rps_nodes = [n for n in rr.nodes_by_id.values()
                     if n.label == "RPS TIEBREAKER"]
        assert len(rps_nodes) == 1
        assert len(rps_nodes[0].players) == 4
        assert rps_nodes[0].best_of == 1
        assert rps_nodes[0].pool_id == 0
        # Effect should have launched it
        assert len(effects) == 1


# ---------------------------------------------------------------------------
# reduce_double_jeopardy (lives on Tournament; tested via RR consumption)
# ---------------------------------------------------------------------------


class TestReduceDoubleJeopardy:
    def test_12_player_swap(self, t):
        players = list(range(12))
        result = t.reduce_double_jeopardy(players)
        # n=12, cutoff = (2*12)//3 = 8
        # Swap pairs from index 8 to n-1 (=11), step 2
        # → swap (8,9), (10,11)
        # Original: [0,1,2,3,4,5,6,7,8,9,10,11]
        # After:    [0,1,2,3,4,5,6,7,9,8,11,10]
        assert result == [0, 1, 2, 3, 4, 5, 6, 7, 9, 8, 11, 10]

    def test_9_player_partial_swap(self, t):
        players = list(range(9))
        result = t.reduce_double_jeopardy(players)
        # n=9, cutoff = (2*9)//3 = 6
        # Swap pairs from 6 to n-1 (=8), step 2
        # → swap (6,7); (8,9) out of range
        # Original: [0,1,2,3,4,5,6,7,8]
        # After:    [0,1,2,3,4,5,7,6,8]
        assert result == [0, 1, 2, 3, 4, 5, 7, 6, 8]

    def test_3_player_no_swap_possible(self, t):
        players = list(range(3))
        result = t.reduce_double_jeopardy(players)
        # n=3, cutoff = 2, range(2, 2, 2) is empty
        assert result == [0, 1, 2]

    def test_returns_same_list(self, t):
        players = list(range(6))
        result = t.reduce_double_jeopardy(players)
        assert result is players


# ---------------------------------------------------------------------------
# Composite preset registration
# ---------------------------------------------------------------------------


class TestPresetRegistration:
    def test_all_presets_registered(self):
        for name in ("pool", "standard", "top4", "top6", "grands",
                     "daily", "phase2"):
            assert name in PRESETS, f"Preset {name!r} not registered"

    def test_pool_preset_rr_only(self, t, p1):
        t.add_players(make_players(8, p1))
        assert apply_preset(t, "pool")
        assert "Round robin" in t.format
        assert len(t.phase_fns) == 1
        graph = t.phase_fns[0](t, t.players)
        assert isinstance(graph, RoundRobin)

    def test_standard_preset_rr_then_de(self, t, p1):
        t.add_players(make_players(12, p1))
        assert apply_preset(t, "standard")
        assert len(t.phase_fns) == 2
        rr_graph = t.phase_fns[0](t, t.players)
        assert isinstance(rr_graph, RoundRobin)
        de_graph = t.phase_fns[1](t, t.players)
        assert isinstance(de_graph, DoubleElimination)

    def test_top4_preset_two_phases(self, t, p1):
        t.add_players(make_players(8, p1))
        assert apply_preset(t, "top4")
        assert len(t.phase_fns) == 2

    def test_top6_preset_two_phases(self, t, p1):
        t.add_players(make_players(8, p1))
        assert apply_preset(t, "top6")
        assert len(t.phase_fns) == 2

    def test_grands_preset_two_phases(self, t, p1):
        t.add_players(make_players(8, p1))
        assert apply_preset(t, "grands")
        assert len(t.phase_fns) == 2

    def test_daily_preset_two_phases(self, t, p1):
        t.add_players(make_players(8, p1))
        assert apply_preset(t, "daily")
        assert len(t.phase_fns) == 2

    def test_phase2_preset_de_only(self, t, p1):
        t.add_players(make_players(8, p1))
        assert apply_preset(t, "phase2")
        assert len(t.phase_fns) == 1
        graph = t.phase_fns[0](t, t.players)
        assert isinstance(graph, DoubleElimination)


# ---------------------------------------------------------------------------
# _calc_num_pools heuristic
# ---------------------------------------------------------------------------


class TestCalcNumPools:
    def test_4_players_1_pool(self):
        assert _calc_num_pools([None] * 4) == 1

    def test_7_players_1_pool(self):
        # 7 // 4 = 1, 2^log2(1) = 1
        assert _calc_num_pools([None] * 7) == 1

    def test_8_players_2_pools(self):
        # 8 // 4 = 2, 2^log2(2) = 2
        assert _calc_num_pools([None] * 8) == 2

    def test_16_players_4_pools(self):
        # 16 // 4 = 4, 2^log2(4) = 4
        assert _calc_num_pools([None] * 16) == 4

    def test_20_players_4_pools(self):
        # 20 // 4 = 5, 2^log2(5) = 4
        assert _calc_num_pools([None] * 20) == 4


# ---------------------------------------------------------------------------
# Stream marking
# ---------------------------------------------------------------------------


class TestStreamMarking:
    def test_stream_false_no_marking(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1, stream=False)
        rr.begin()
        for n in _pool_match_nodes(rr):
            assert not n.streamed

    def test_stream_true_marks_first_match_per_round(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1, stream=True)
        rr.begin()
        # At least one match per round should be marked streamed
        streamed = [n for n in _pool_match_nodes(rr) if n.streamed]
        assert len(streamed) >= 1


# ---------------------------------------------------------------------------
# Begin/complete lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_begin_returns_initial_round_matches(self, t, p1):
        rr = RoundRobin(t, make_players(4, p1), num_pools=1)
        effects = rr.begin()
        # Round 1 for 4-player single-pool = 2 matches
        # Each match → 1 LaunchTournamentMatch effect
        from axi.effects import LaunchTournamentMatch
        launches = [e for e in effects if isinstance(e, LaunchTournamentMatch)]
        assert len(launches) == 2

    def test_complete_all_no_ties_finalizes(self, t, p1):
        # 4 players, all matches won by the top seed in each pairing.
        players = make_players(4, p1)
        rr = RoundRobin(t, players, num_pools=1)
        rr.begin()
        a, b, c, d = players
        # a beats everyone, b beats c and d, c beats d
        outcomes = {
            frozenset({a, b}): a,
            frozenset({a, c}): a,
            frozenset({a, d}): a,
            frozenset({b, c}): b,
            frozenset({b, d}): b,
            frozenset({c, d}): c,
        }
        _play_pool_with_outcomes(rr, 0, outcomes)
        # No tiebreakers
        assert len(_tiebreaker_nodes(rr)) == 0
        # Victory should be completed with `a` as champion
        assert rr.victory_node.completed()
        assert rr.placements_dict[a] == 1
        assert rr.completed()

    def test_complete_tied_spawns_tiebreaker_and_finalizes(self, t, p1):
        # 3-way ring (a→b, b→c, c→a, all beat d) → 3 tiebreaker matches.
        players = make_players(4, p1)
        rr = RoundRobin(t, players, num_pools=1)
        rr.begin()
        a, b, c, d = players
        outcomes = {
            frozenset({a, b}): a,
            frozenset({b, c}): b,
            frozenset({c, a}): c,
            frozenset({a, d}): a,
            frozenset({b, d}): b,
            frozenset({c, d}): c,
        }
        _play_pool_with_outcomes(rr, 0, outcomes)
        tbs = _tiebreaker_nodes(rr)
        assert len(tbs) == 3
        # Complete tiebreakers — a wins ring outright by sweeping
        for m in tbs:
            if not m.awake() or len(m.players) != 2:
                continue
            # Always make the first listed player win
            _complete_with_winner(rr, m, m.players[0])
        # Now finalize. Complete any newly-callable tiebreaker matches.
        # The ring uses sequential dependencies, so we loop again.
        safety = 20
        while safety > 0:
            safety -= 1
            any_open = False
            for m in tbs:
                if m.awake() and len(m.players) == 2:
                    any_open = True
                    _complete_with_winner(rr, m, m.players[0])
            if not any_open:
                break
        # Victory should be set
        assert rr.victory_node.completed()
        assert rr.completed()
