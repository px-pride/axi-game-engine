# Phase 4: RoundRobin (pools) — Detailed Design

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 4.

This phase introduces `RoundRobin` — pool-based round-robin tournaments
with Berger polygon scheduling, snake seeding, and a tiebreaker cascade
(set wins → H2H → GPW → seed → BO1 ring → N-way RPS).

## Scope

- `axi/tournament_formats/round_robin.py` containing:
  - `RoundRobin(MatchGraph)` — top-level orchestrator.
  - `_RoundRobinPool` — helper that builds one pool's Berger schedule.
  - Tiebreaker-cascade resolution (set wins → H2H → GPW → seed).
  - 3-way ring BO1 tiebreaker spawning (when GPW doesn't resolve).
  - N-way RPS tiebreaker spawning (when BO1 doesn't resolve).
- New `Tournament.reduce_double_jeopardy()` helper (for RR → DE
  seeding used by composite presets).
- Composite presets registering RoundRobin + DoubleElimination:
  `standard`, `top4`, `top6`, `grands`, `daily`, `phase2`, `pool`.

## Major architectural decision: flatten the nested-tournament

**Source uses nested tournaments.** `RoundRobin` creates one
`Tournament` per pool, each with `preset_pool` setting `phase_fns =
[RoundRobinPool, RoundRobinTiebreaker]`. Each pool runs as its own
mini-tournament; the outer RoundRobin orchestrates them.

**Phase 4 flattens this.** A single `RoundRobin(MatchGraph)` builds
all pool matches as parallel sub-DAGs in one MatchGraph. Tiebreaker
resolution (3-way ring, N-way RPS) happens **within the same MatchGraph**
as additional matches spawned dynamically when scoring detects
unresolved pods.

Rationale:
- Phase 1's `Tournament` holds `phases: list[MatchGraph]`. Nested
  Tournaments would require either parent/child Tournament linkage
  (large abstraction expansion) or duplicating state through a "pool
  tournament" wrapper (lots of glue code).
- All Phase 4 source `RoundRobin` methods that delegate to per-pool
  Tournaments (`get_matches_by_player`, `report_score`, etc.) are
  trivially expressible by tagging each MatchNode with `pool_id`.
- Tiebreakers in source live in separate phases. In our port they
  become dynamic additions to the same MatchGraph, triggered on
  `complete_match` when scoring detects ties. This is cleaner: one
  graph, one set of placements, no cross-phase plumbing.

## Algorithm port

### Constructor

```python
def __init__(self, tournament, players, stream=False, num_pools=1,
             snake_seeding=True):
    super().__init__(tournament, players, stream=stream)
    self.num_pools = num_pools
    self.snake_seeding = snake_seeding
    # Pad each pool to even size (Berger requires even player count).
    pool_capacity = math.ceil(len(players) / (2 * num_pools)) * 2 * num_pools
    self.num_players = pool_capacity
    for i in range(pool_capacity - len(self.players)):
        self.players.append(_ByeUser(i))
```

### `generate_bracket()`

1. **Distribute players into pools** (snake or modulo seeding):
   - Snake: `pool_id = i % (2*num_pools); if pool_id >= num_pools: pool_id = 2*num_pools - 1 - pool_id`
   - Modulo: `pool_id = i % num_pools`
   - Store `self.players_by_pool[pool_id]` and `self.pool_id_by_player[p]`.
2. **For each pool, build Berger schedule:**
   - `pool_size` = number of non-bye players in the pool, rounded up to even.
   - `polygon = [1, 2, ..., pool_size - 1]` (indices into pool players).
   - For each round `r` in `range(pool_size - 1)`:
     - Create match `(pool_players[0], pool_players[polygon[-1]])` — top seed fixed, plays end of polygon.
     - For `n` in `range(pool_size // 2 - 1)`:
       - Create match `(pool_players[polygon[n]], pool_players[polygon[-2-n]])`.
     - Rotate polygon: `polygon = [polygon[-1]] + polygon[:-1]`.
   - Round-1 matches: no parents (immediately callable).
   - Subsequent rounds: each match has 2 parents (the previous-round
     matches involving each of its players), linked with "W" flag
     (W means "the match completed", we don't actually use the winner).
3. **Mark stream candidates** (optional, via stochastic
   `schedule_stream`; default false for Phase 4 initial).
4. **Return** the round-1 matches from all pools.

Pool tagging: each MatchNode created carries a `pool_id` attribute
(added in `RoundRobin.add_node` override).

### Tiebreaker cascade (in `_calculate_pool_scores(pool_id)`)

For each player in pool:
- Compute `(code, set_wins, gpw)`:
  - `code = -3` if `tournament.is_dq(p)`
  - `code = -2` if `p.is_bye()` or `isinstance(p, _ByeUser)`
  - `code = -1` if `tournament.is_dropped(p)`
  - `code = 0` otherwise
  - `set_wins` = count of completed matches where `p == match.winner()`.
  - `gpw` = `100 * sum(games_won) / max(1, sum(games_played))` over completed non-bye matches.

Sort by `(code, set_wins, ...)` descending. For pods with multiple
players sharing `(code, set_wins)`:
- Apply H2H: count within-pod wins. Sort by H2H. If still tied:
- Apply GPW within pod. Sort by GPW. If still tied:
- Apply seed rank (lower seed = higher placement). If still tied:
- Mark the pod with sentinel value `"TIE"` — to be resolved by
  spawning 3-way ring or N-way RPS matches.

### 3-way ring (when `len(unresolved_pod) == 3`)

When a pod has exactly 3 tied players after the cascade, spawn
a chain of 3 BO1 matches: A→B, B→C, C→A. Each player wins exactly
one or two of these; the player with most wins breaks the tie.

In our flattened model:
- After all pool matches complete (i.e. `_check_pools_complete()`),
  inspect each pool's scores. For each unresolved 3-way pod, add
  3 new MatchNodes to the graph with `label="POOLS TIEBREAKER"`,
  `best_of=1`, chained `A→B→C→A`. First in chain has no parent (callable
  immediately); subsequent depend on previous tiebreaker match.
- On completion of all 3 tiebreaker matches, recompute scores;
  `set_wins_in_tiebreaker` becomes the new sort key.

### N-way RPS (final fallback)

If a pod has ≥ 2 tied players and the 3-way ring isn't applicable
(e.g. 4+ tied, or 3-way didn't resolve), spawn a single
`MatchNode(players=tied_pod, label="RPS TIEBREAKER", game="rps",
best_of=1)`. The match goes to the underlying RPS game's N-player
variant. Whoever wins is ranked highest in the pod.

Defer for now: N-way RPS requires `game="rps"` to support N>2 players.
Phase 1's RPS game implementation accepts 2 players. We'll register an
N-way variant later or fall back to deterministic tiebreak (lowest seed
wins).

**Phase 4 simplification:** If N-way RPS isn't available, the cascade
falls back to seed rank as the final tiebreaker (lowest seed wins).
This matches source's eventual behavior when `RpsTiebreaker` isn't
configured.

## `complete_match` override

```python
def complete_match(self, node):
    effects = super().complete_match(node)
    # When all pool matches complete, run tiebreaker cascade.
    if self._all_pool_matches_complete() and not self._tiebreakers_spawned:
        effects += self._spawn_tiebreakers()
        self._tiebreakers_spawned = True
    elif self._all_tiebreaker_matches_complete():
        self._finalize_placements()
    return effects
```

`_spawn_tiebreakers()` calls `_calculate_pool_scores` for each pool,
detects unresolved pods, and adds appropriate tiebreaker MatchNodes to
the graph. Each tiebreaker match has `loser_gets` set so placements
propagate cleanly.

## `Tournament.reduce_double_jeopardy(players)` helper

For RR → DE seeding: prevent rematches in DE round 1 by swapping pairs
in the bottom 1/3 of the seeding list. Source's pattern:

```python
def reduce_double_jeopardy(self, players):
    n = len(players)
    cutoff = (2 * n) // 3
    for i in range(cutoff, n - 1, 2):
        players[i], players[i + 1] = players[i + 1], players[i]
    return players
```

This is a Tournament method (not RoundRobin-specific), used in
preset_standard etc. Add to `axi/tournament.py` in Phase 4.

## Composite presets

Source's composite presets feed RoundRobin into DoubleElimination via
top-N cutoffs:

```python
@register_preset("standard")
def _preset_standard(t):
    def calc_num_pools(players):
        # Source: log-based pool sizing, max 2^N pools from 4+ players each
        n = max(1, len(players) // 4)
        return 2 ** int(math.log2(n)) if n else 1

    rr_factory  = lambda tt, pp: RoundRobin(tt, pp, stream=True,
                                              num_pools=calc_num_pools(pp))
    de_factory  = lambda tt, pp: DoubleElimination(
        tt,
        tt.reduce_double_jeopardy(pp[:calc_num_pools(pp) * 3]),
        stream=6, bo5=-1, winner_loser_split=calc_num_pools(pp),
    )
    return [rr_factory, de_factory], \
           "Round robin pools. Top 3 per pool advance to DE. Top 1 to winners side."
```

Similar wrappers for `top4`, `top6`, `grands`, `daily`, `phase2`. Each
varies only in DE `stream` arg (6/4/2/False) — same RR+DE pipeline.

**`pool` preset**: just RoundRobin alone (no DE follow-up). Used for
informal pool-only events.

## Files to add / modify

```
NEW  axi/tournament_formats/round_robin.py
MOD  axi/tournament.py             # add reduce_double_jeopardy method
```

No Phase 1-3 changes needed.

## Test plan

`tests/test_round_robin.py`:

### Pool distribution

- 4 players, 1 pool → all in pool 0.
- 8 players, 2 pools, snake → seeds 0,1,2,3 in pool 0; seeds 7,6,5,4 in pool 1.
- 8 players, 2 pools, modulo → seeds 0,2,4,6 in pool 0; seeds 1,3,5,7 in pool 1.

### Berger schedule (per pool)

- 4-player pool → 3 rounds × 2 matches/round = 6 matches.
- 6-player pool → 5 rounds × 3 matches/round = 15 matches.
- 8-player pool → 7 rounds × 4 matches/round = 28 matches.
- Verify each player plays every other exactly once per pool.

### Tiebreaker cascade

- 4-player pool, P0 wins all 3 → top placement (no tiebreaker needed).
- 4-player pool, all win 1 each → tiebreaker triggered. Pod tested.
- 4-player pool, 2 players tied at 2-1 → resolve via H2H if direct match
  decided it; via GPW otherwise; via seed final fallback.

### 3-way ring spawn

- Set up a 3-way tie deliberately; verify 3 BO1 matches created with
  labels "POOLS TIEBREAKER", chained A→B→C→A.

### N-way RPS spawn (fallback)

- Set up 4-way tie; verify RPS TIEBREAKER match created OR seed-rank
  fallback applied if RPS N-way isn't available.

### Snake seeding

- 8 players, 2 pools, `snake_seeding=True` vs `False` — verify
  distribution differs.

### `reduce_double_jeopardy`

- 12 players, cutoff at 8. Swap pairs (8,9) and (10,11). Verify.
- 9 players, cutoff at 6. Swap (6,7). Verify.

### Composite presets

- `standard`: verify phase_fns has 2 entries (RR + DE).
- `top4` / `top6` / `grands` / `daily`: verify all 4 register.
- `pool`: single-phase RR only.

## Resolved questions (no open items)

1. **Nested-tournament approach** → flatten into one MatchGraph,
   tag matches with `pool_id`, spawn tiebreakers dynamically. Avoids
   recursive Tournament linkage.

2. **3-way ring vs N-way RPS** → both supported. 3-way ring is the
   default for exactly-3 ties; RPS fallback for ≥4. If RPS isn't
   available, fall back to seed-rank ordering.

3. **Tournament.reduce_double_jeopardy** → add as a Tournament method
   (not RR-specific). Lives in `axi/tournament.py`. Used by
   composite presets in Phase 4 and possibly future phases.

4. **`pool_id` storage on MatchNode** → add as a new optional field
   (default None). Phase 4 sets it during pool construction. Other
   phases ignore it.

## What's deferred

- Matplotlib bracket table visualization → Phase 15.
- Stochastic `schedule_stream` (1000-hypothesis stream selection) →
  Phase 7 (matchmaking weights, where similar hypothesis-scoring lives).
  Phase 4 supports basic stream-marking only (each pool's last match
  per round if `stream=True`).
- True N-way RPS game → handled here as best-effort; full N-way RPS
  registration could live in Phase 16 (game features).
