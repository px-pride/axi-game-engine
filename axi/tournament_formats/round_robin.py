"""RoundRobin tournament format with pools.

Flattens source's nested-tournament structure: one MatchGraph per
RoundRobin, with all pool matches tagged via MatchNode.pool_id.
Tiebreaker matches are spawned dynamically on `complete_match` when
scoring detects unresolved pods.

Preset registration at module bottom:
  - pool      : RoundRobin alone (no DE follow-up)
  - standard  : RoundRobin + DoubleElimination(stream=6, bo5=-1)
  - top4      : RoundRobin + DoubleElimination(stream=4)
  - top6      : RoundRobin + DoubleElimination(stream=6)
  - grands    : RoundRobin + DoubleElimination(stream=2)
  - daily     : RoundRobin + DoubleElimination(stream=False)
  - phase2    : DoubleElimination only (no RR phase)
"""

import math
from collections import defaultdict

from axi.match_graph import MatchGraph
from axi.tournament_formats.single_elimination import _ByeUser
from axi.tournament_presets import register_preset


class RoundRobin(MatchGraph):
    """Round-robin tournament with pools, Berger polygon scheduling,
    snake or modulo seeding, and a tiebreaker cascade
    (set_wins → H2H → GPW → seed → 3-way ring BO1 → N-way RPS).

    Constructor params:
        tournament    : owning Tournament
        players       : list of AxiUser-like players
        stream        : bool|int (currently mark-only; advanced stream
                        selection deferred to Phase 7)
        num_pools     : positive int; players distributed across pools
        snake_seeding : bool; if True, snake distribution; else modulo
    """

    def __init__(self, tournament, players, stream=False, num_pools=1,
                 snake_seeding=True):
        super().__init__(tournament, players, stream=stream)
        self.num_pools = max(1, num_pools)
        self.snake_seeding = snake_seeding

        # Pad to even-sized pools. Each pool must have an even count for
        # Berger scheduling.
        per_pool_size = math.ceil(len(players) / (2 * self.num_pools)) * 2
        self.num_players = per_pool_size * self.num_pools
        for i in range(self.num_players - len(self.players)):
            self.players.append(_ByeUser(len(self.players) + i))

        self.players_by_pool = []
        self.pool_id_by_player = {}
        self._pool_matches = defaultdict(list)  # pool_id -> [MatchNode]
        self._all_pool_matches_complete_cached = False
        self._tiebreakers_spawned = False
        self._tiebreaker_matches = []
        self._final_placements_set = False

        # Stream threshold (Phase 4 keeps it simple: 0 = off, else mark first
        # match per round of each pool as streamed).
        if stream is True:
            self.stream_threshold = 1
        elif isinstance(stream, int) and not isinstance(stream, bool):
            self.stream_threshold = max(0, stream)
        else:
            self.stream_threshold = 0

    def __repr__(self):
        return "ROUND ROBIN POOLS"

    def add_node(self, **kwargs):
        pool_id = kwargs.pop("pool_id", None)
        node = super().add_node(**kwargs)
        node.pool_id = pool_id
        return node

    def generate_bracket(self):
        self._distribute_players_to_pools()
        matches_to_call = []
        for pool_id in range(self.num_pools):
            matches_to_call += self._build_pool_bracket(pool_id)
        # Hook into victory_node only after we know placements; victory
        # gets set when all pool matches + tiebreakers complete.
        return matches_to_call

    # -- internal helpers --

    def _distribute_players_to_pools(self):
        """Snake or modulo distribution into pools."""
        self.players_by_pool = [[] for _ in range(self.num_pools)]
        for i in range(len(self.players)):
            if self.snake_seeding:
                # Snake: pools fill 0,1,2,N-1,N-2,...,1,0,1,2,...
                pool_id = i % (2 * self.num_pools)
                if pool_id >= self.num_pools:
                    pool_id = 2 * self.num_pools - 1 - pool_id
            else:
                pool_id = i % self.num_pools
            self.players_by_pool[pool_id].append(self.players[i])
            self.pool_id_by_player[self.players[i]] = pool_id

    def _build_pool_bracket(self, pool_id):
        """Build one pool's Berger-rotation schedule. Returns matches to call."""
        pool_players = self.players_by_pool[pool_id]
        n = len(pool_players)
        if n % 2 == 1:
            n += 1
        # Polygon for rotation: indices 1..n-1.
        polygon = list(range(1, n))
        prev_round_match_by_player = {p: None for p in pool_players}
        first_round_matches = []
        rounds_total = n - 1

        for r in range(rounds_total):
            round_matches = []
            # Match 0: player[0] vs player[polygon[-1]]
            a_idx, b_idx = 0, polygon[-1]
            if a_idx < len(pool_players) and b_idx < len(pool_players):
                m = self._make_pool_match(pool_id, pool_players, a_idx, b_idx,
                                          round_num=r + 1)
                self._link_round_parent(m, prev_round_match_by_player,
                                        pool_players, a_idx, b_idx)
                round_matches.append(m)

            # Match n: player[polygon[k]] vs player[polygon[-2-k]]
            for k in range(n // 2 - 1):
                a_idx = polygon[k]
                b_idx = polygon[-2 - k]
                if a_idx >= len(pool_players) or b_idx >= len(pool_players):
                    continue
                m = self._make_pool_match(pool_id, pool_players, a_idx, b_idx,
                                          round_num=r + 1)
                self._link_round_parent(m, prev_round_match_by_player,
                                        pool_players, a_idx, b_idx)
                round_matches.append(m)

            if r == 0:
                first_round_matches = round_matches[:]
                self.matches_by_round[round_matches[0].label] = round_matches \
                    if round_matches else []

            # Track each player's most-recent match for parent linking next round.
            for m in round_matches:
                for p in m.players:
                    prev_round_match_by_player[p] = m

            # Rotate polygon
            polygon = [polygon[-1]] + polygon[:-1]

        return first_round_matches

    def _make_pool_match(self, pool_id, pool_players, a_idx, b_idx, round_num):
        p_a = pool_players[a_idx]
        p_b = pool_players[b_idx]
        node = self.add_node(
            players=[p_a, p_b],
            best_of=3,
            label=f"POOLS ROUND {round_num}",
            game=self._game_name(),
            pool_id=pool_id,
        )
        self._pool_matches[pool_id].append(node)
        # Phase 4 simple stream marking: first match of each round if enabled.
        if self.stream_threshold > 0:
            existing_in_round = self.matches_by_round.get(node.label, [])
            if not existing_in_round:
                node.streamed = True
                self.stream_candidates.append(node)
        return node

    def _link_round_parent(self, node, prev_by_player, pool_players, a_idx, b_idx):
        """Subsequent-round matches depend on each player's previous match
        completing. The child already has its fixed players from the Berger
        schedule, so use "S" (sequence-only) flag to gate without propagating
        winners/losers into the child's players list.
        """
        for idx in (a_idx, b_idx):
            p = pool_players[idx]
            prev = prev_by_player.get(p)
            if prev is not None:
                self.link_parent(node, prev, "S")

    def _game_name(self):
        return getattr(self.tournament, "game", "rps")

    # -- tiebreaker resolution --

    def complete_match(self, node):
        effects = super().complete_match(node)
        # When all pool matches done (and we haven't already spawned
        # tiebreakers), inspect and spawn.
        if (not self._tiebreakers_spawned
                and self._all_pool_matches_complete()):
            effects += self._spawn_tiebreakers()
            self._tiebreakers_spawned = True
        # When all tiebreaker matches done and we haven't finalized
        # placements yet, finalize.
        if (self._tiebreakers_spawned
                and not self._final_placements_set
                and self._all_tiebreaker_matches_complete()):
            self._finalize_placements()
            self._final_placements_set = True
            # Mark victory_node completed.
            if self.victory_node is not None and not self.victory_node.completed():
                from axi.util import MATCH_STATUS_COMPLETED
                # Pick the overall champion (highest-ranked across pools).
                champ = self._overall_champion()
                if champ is not None:
                    self.victory_node.players = [champ]
                    self.victory_node.status = MATCH_STATUS_COMPLETED
                    self.placements_dict[champ] = 1
        return effects

    def _all_pool_matches_complete(self):
        for pool_id, matches in self._pool_matches.items():
            for m in matches:
                if not m.completed():
                    return False
        return True

    def _all_tiebreaker_matches_complete(self):
        for m in self._tiebreaker_matches:
            if not m.completed():
                return False
        return True

    def _spawn_tiebreakers(self):
        """Inspect each pool's scores; spawn 3-way ring or N-way RPS
        tiebreaker matches for unresolved pods. Returns effects."""
        effects = []
        for pool_id in range(self.num_pools):
            scores = self._calculate_pool_scores(pool_id)
            # scores: list of (sort_key_tuple, player); 'TIE' marker present
            # indicates unresolved pod.
            unresolved = defaultdict(list)
            for sort_key, player in scores:
                if isinstance(sort_key, tuple) and sort_key and sort_key[-1] == "TIE":
                    bucket = sort_key[:-2] if len(sort_key) >= 2 else sort_key
                    unresolved[bucket].append(player)
            for bucket, pod in unresolved.items():
                if len(pod) == 3:
                    effects += self._spawn_three_way_ring(pool_id, pod)
                elif len(pod) >= 2:
                    effects += self._spawn_nway_rps(pool_id, pod)
        return effects

    def _spawn_three_way_ring(self, pool_id, pod):
        """A→B, B→C, C→A chain of BO1 matches."""
        effects = []
        a, b, c = pod
        m1 = self.add_node(
            players=[a, b],
            best_of=1,
            label="POOLS TIEBREAKER",
            game=self._game_name(),
            pool_id=pool_id,
        )
        m2 = self.add_node(
            players=[b, c],
            best_of=1,
            label="POOLS TIEBREAKER",
            game=self._game_name(),
            pool_id=pool_id,
        )
        m3 = self.add_node(
            players=[c, a],
            best_of=1,
            label="POOLS TIEBREAKER",
            game=self._game_name(),
            pool_id=pool_id,
        )
        # Chain: m2 depends on m1, m3 depends on m2 (sequence ordering).
        self.link_parent(m2, m1, "S")
        self.link_parent(m3, m2, "S")
        self._tiebreaker_matches += [m1, m2, m3]
        # Only m1 is callable now.
        effects += self.call_match(m1)
        return effects

    def _spawn_nway_rps(self, pool_id, pod):
        """N-way RPS match. If game registry doesn't support N>2 RPS,
        we still create the match but seed-rank fallback resolves the order."""
        node = self.add_node(
            players=list(pod),
            best_of=1,
            label="RPS TIEBREAKER",
            game="rps",
            pool_id=pool_id,
        )
        self._tiebreaker_matches.append(node)
        return self.call_match(node)

    def _calculate_pool_scores(self, pool_id):
        """Compute (sort_key, player) tuples for a pool. Returns sorted DESC."""
        pool_players = self.players_by_pool[pool_id]
        data = {}
        for p in pool_players:
            code = self._player_code(p)
            set_wins = self._set_wins(p, pool_id)
            gpw = self._gpw(p, pool_id)
            data[p] = (code, set_wins, gpw)

        # Group into pods by (code, set_wins)
        pods = defaultdict(list)
        for p in pool_players:
            code, set_wins, gpw = data[p]
            pods[(code, set_wins)].append(p)

        scores = []
        for (code, set_wins), pod in pods.items():
            if len(pod) == 1:
                p = pod[0]
                scores.append(((code, set_wins, data[p][2], -self.seed_by_player.get(p, 0)), p))
                continue
            # Cascade: H2H → GPW → seed → TIE marker
            h2h = self._pod_h2h(pod, pool_id)
            h2h_pods = defaultdict(list)
            for p in pod:
                h2h_pods[h2h[p]].append(p)
            if len(h2h_pods) > 1:
                # H2H resolves some/all
                for h_score, sub_pod in h2h_pods.items():
                    for q in sub_pod:
                        scores.append(((code, set_wins, h_score, data[q][2],
                                       -self.seed_by_player.get(q, 0)), q))
                continue
            # H2H tied; try GPW within pod
            gpw_pods = defaultdict(list)
            for p in pod:
                gpw_pods[data[p][2]].append(p)
            if len(gpw_pods) > 1:
                for gpw_score, sub_pod in gpw_pods.items():
                    for q in sub_pod:
                        scores.append(((code, set_wins, 0, gpw_score,
                                       -self.seed_by_player.get(q, 0)), q))
                continue
            # GPW tied; mark as TIE for tiebreaker spawning. The bucket key
            # is (code, set_wins) so all pod members group together.
            for p in pod:
                scores.append(((code, set_wins, 0, data[p][2],
                               -self.seed_by_player.get(p, 0), "TIE"), p))

        scores.sort(reverse=True, key=lambda kv: kv[0])
        return scores

    def _player_code(self, p):
        if self.tournament.is_dq(p):
            return -3
        if isinstance(p, _ByeUser):
            return -2
        if self.tournament.is_dropped(p):
            return -1
        return 0

    def _set_wins(self, p, pool_id):
        wins = 0
        for m in self._pool_matches[pool_id]:
            if not m.completed():
                continue
            if isinstance(m, type(m)) and p in m.players and m.winner() is p:
                wins += 1
        return wins

    def _gpw(self, p, pool_id):
        won, played = 0, 0
        for m in self._pool_matches[pool_id]:
            if not m.completed() or p not in m.players:
                continue
            # Skip byes
            if any(isinstance(x, _ByeUser) for x in m.players):
                continue
            idx = m.players.index(p)
            won += m.score[idx]
            played += sum(m.score)
        return (100 * won // max(1, played))

    def _pod_h2h(self, pod, pool_id):
        h2h = {p: 0 for p in pod}
        for m in self._pool_matches[pool_id]:
            if not m.completed():
                continue
            if m.players and m.players[0] in pod and m.players[1] in pod:
                w = m.winner()
                if w in h2h:
                    h2h[w] += 1
        return h2h

    def _finalize_placements(self):
        """After tiebreakers complete, recompute pool scores incorporating
        tiebreaker wins, and assign final placements."""
        for pool_id in range(self.num_pools):
            scores = self._calculate_pool_scores_with_tiebreakers(pool_id)
            # Assign placements: rank within pool * num_pools (so pool 0
            # rank 1 = overall 1, pool 1 rank 1 = overall 2, etc.).
            for rank, (sort_key, player) in enumerate(scores, start=1):
                overall_rank = (rank - 1) * self.num_pools + pool_id + 1
                if not isinstance(player, _ByeUser):
                    self.placements_dict[player] = overall_rank

    def _calculate_pool_scores_with_tiebreakers(self, pool_id):
        """Same as _calculate_pool_scores but using tiebreaker results to
        resolve TIE buckets."""
        # Tally tiebreaker wins for each player in this pool.
        tb_wins = defaultdict(int)
        for m in self._tiebreaker_matches:
            if m.pool_id != pool_id or not m.completed():
                continue
            w = m.winner()
            if w is not None:
                tb_wins[w] += 1

        scores = self._calculate_pool_scores(pool_id)
        # Replace TIE entries with tiebreaker-augmented sort keys.
        new_scores = []
        for sort_key, player in scores:
            if isinstance(sort_key, tuple) and sort_key and sort_key[-1] == "TIE":
                key_without_tie = tuple(list(sort_key[:-1]) + [tb_wins[player]])
                new_scores.append((key_without_tie, player))
            else:
                new_scores.append((sort_key, player))
        new_scores.sort(reverse=True, key=lambda kv: kv[0])
        return new_scores

    def _overall_champion(self):
        """Return the player with placements_dict[player] == 1, or None."""
        for p, rank in self.placements_dict.items():
            if rank == 1:
                return p
        return None


# ---------------------------------------------------------------------------
# Composite preset factories
# ---------------------------------------------------------------------------


def _calc_num_pools(players):
    """Source's pool-sizing heuristic: log2-based, max 2^N pools from
    4+ players each."""
    n = max(1, len(players) // 4)
    return 2 ** int(math.log2(n)) if n > 0 else 1


def _rr_factory(stream=True, snake_seeding=True):
    def factory(tournament, players):
        return RoundRobin(
            tournament, players,
            stream=stream,
            num_pools=_calc_num_pools(players),
            snake_seeding=snake_seeding,
        )
    return factory


def _composite_de_factory(stream_value, bo5=-1):
    """Factory wrapping DoubleElimination for RR → DE pipelines."""
    def factory(tournament, players):
        # Import here to avoid circular import at module load
        from axi.tournament_formats.double_elimination import DoubleElimination
        # Top 3 per pool advance; reduce_double_jeopardy adjusts seeding.
        num_pools = _calc_num_pools(players)
        cutoff = num_pools * 3
        adjusted = tournament.reduce_double_jeopardy(list(players[:cutoff]))
        return DoubleElimination(
            tournament, adjusted,
            stream=stream_value, bo5=bo5,
            winner_loser_split=num_pools,
        )
    return factory


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------


@register_preset("pool")
def _preset_pool(_t):
    return [_rr_factory(stream=False)], "Round robin pools."


@register_preset("standard")
def _preset_standard(_t):
    return (
        [_rr_factory(stream=True), _composite_de_factory(stream_value=6)],
        "Round robin pools. Top 3 per pool advance to DE.",
    )


@register_preset("top4")
def _preset_top4(_t):
    return (
        [_rr_factory(stream=True), _composite_de_factory(stream_value=4)],
        "Round robin pools. Top 4 stream.",
    )


@register_preset("top6")
def _preset_top6(_t):
    return (
        [_rr_factory(stream=True), _composite_de_factory(stream_value=6)],
        "Round robin pools. Top 6 stream.",
    )


@register_preset("grands")
def _preset_grands(_t):
    return (
        [_rr_factory(stream=True), _composite_de_factory(stream_value=2)],
        "Round robin pools. Top 2 stream.",
    )


@register_preset("daily")
def _preset_daily(_t):
    return (
        [_rr_factory(stream=False), _composite_de_factory(stream_value=False)],
        "Round robin pools. No streaming.",
    )


@register_preset("phase2")
def _preset_phase2(_t):
    """DoubleElimination only — skips RR; assumes the players list is
    already pre-seeded as if RR had finished."""
    def factory(tournament, players):
        from axi.tournament_formats.double_elimination import DoubleElimination
        num_pools = _calc_num_pools(players)
        return DoubleElimination(
            tournament, players[: num_pools * 3],
            stream=True, bo5=-1,
            winner_loser_split=num_pools,
        )
    return [factory], "Double elimination only (post-pool)."
