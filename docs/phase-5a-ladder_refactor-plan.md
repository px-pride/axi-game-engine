# Phase 5a: Refactor Ladder to a MatchGraph subclass

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 5a.

Phase 5a is a **prerequisite refactor** that makes `axi/ladder.py` `Ladder`
a clean subclass of `MatchGraph` so Phase 5b's `LadderElimination` can
inherit from it cleanly. The refactor surfaces no new feature for users
— it's pure structural cleanup.

This phase exists because the original Phase 5 attempt
(commit `a688ba0`, reverted in `17023ec`) shipped a parallel
`LadderElimination(MatchGraph)` that duplicated ~400 lines of
`Ladder`'s matchmaking / streaming / ratings logic. The user pushed
back: friendlies (`Ladder`) and elimination ladders should share one
implementation under `MatchGraph`.

## Scope

- Refactor `axi/ladder.py` `Ladder` to inherit from `MatchGraph`.
- Fix the circular import between `axi/ladder.py` and
  `axi/handlers/ladder_handler.py`.
- Switch `Ladder`'s match bookkeeping from real `Match` objects (from
  `axi/handlers/match_handler.py`) to pure-data `MatchNode` objects.
- Inject `time_fn` for deterministic tests.
- Update `axi/handlers/ladder_handler.py` to consume the new Ladder
  API (without changing Discord-facing behavior).
- Add new `tests/test_ladder.py` covering Ladder under the conftest
  mock environment.
- No user-visible behavior changes. All existing Discord commands
  (`/queue`, `/dequeue`, `/autoqueue`, etc.) keep working.

## The five structural changes

### 1. Break the circular import

**Current:**
```python
# axi/ladder.py top
import axi.handlers.ladder_handler as ladder_handler  # for DB writes
```
```python
# axi/handlers/ladder_handler.py top
from axi.ladder import Ladder  # for type + construction
```

Triggers `ImportError: cannot import name 'Ladder' from partially
initialized module 'axi.ladder'` when either is imported first under
tests.

**Fix:** lazy-import `Ladder` inside `ladder_handler.start_ladder()`
(the one place it's constructed). Type hints in `ladder_handler.py`
use `TYPE_CHECKING` to keep static typing.

`Ladder`'s use of `ladder_handler.update_ratings_db` /
`load_from_ratings_db` stays put — those are runtime calls inside
method bodies (already evaluated lazily). Module-top import of
`ladder_handler` from `ladder.py` is REMOVED in favor of in-method
imports.

This keeps the existing DB-persistence pattern. Replacing DB writes
with effects is deferred to Phase 11 (DB-backed persistence), which
handles all phases uniformly.

### 2. Switch `Match` → `MatchNode`

**Current:** `Ladder.generate_match_nodes` calls
`match_handler.launch_match()` which returns real `Match` objects.
Stored in `matches_by_pair`, `matches_by_player`. Methods like
`match.check_match_over()`, `match.winner()`, `match.streamed` are
called against the `Match` API.

**Refactor:**
- `Ladder` becomes a `MatchGraph` subclass; use `self.add_node(...)`
  to create `MatchNode`s.
- `generate_match_nodes` becomes `generate_bracket(pairings,
  challenge_pairings)` returning `MatchNode`s.
- `Ladder.matchmaking()` returns `LaunchTournamentMatch` effects
  (one per non-stream match) + the stream-call effect, following the
  same pattern as the other MatchGraph subclasses.
- `match.check_match_over()` → `node.completed()` (already on
  `MatchNode`).
- `match.winner()` already exists on both — no change.
- `match.streamed` already exists on `MatchNode` — no change.
- `match.description(pov=user)` (used by `ladder_handler.history`)
  → port to a `MatchNode` helper or move formatting into the handler.

**Impact:** `ladder_handler.call_matches()` (currently iterates
`called_matches` calling `match_handler.prepare_match_ux`) is
replaced by consuming `LaunchTournamentMatch` effects emitted from
`Ladder.matchmaking()`. The Discord adapter (or a thin handler
shim) maps each `LaunchTournamentMatch` to a real
`match_handler.launch_match(...)` call and records the resulting
`Match` in `tournament_state.nodes_to_matches[node_id]`.

### 3. Inject `time_fn`

**Current:** `Ladder` calls `from time import time` and uses raw
`time()` for `end_time`, `downtime_clock_by_player`,
`start_downtime_clock`, `stop_downtime_clock`, `query_downtime_clock`,
and `completed()`.

**Refactor:** add `time_fn=None` constructor param defaulting to
`time.time` (lazy resolution to allow tests to inject a `FakeClock`).
Every internal call to `time()` becomes `self._now()` which calls
`self._time_fn()`.

### 4. Inherit from MatchGraph

`Ladder(MatchGraph)`:
- `super().__init__(tournament, players, stream=streamed)` — but
  `Ladder` doesn't have a `tournament` object the way bracket formats
  do. **Decision:** introduce a thin `_LadderTournament` shim or
  refactor `MatchGraph` to accept None for tournament. The simpler
  path: construct a no-op `Tournament(title=ladder.name,
  scope=ladder.queue_channel, seed=...)` to pass to MatchGraph's base.
  Pure layer; minimal overhead.

- Implement `generate_bracket()` per MatchGraph contract — for Ladder
  it returns `[]` initially (matchmaking is dynamic and driven by
  `queue(user)` calls, not bracket construction).

- Override `call_match(node)` — set player statuses to CALLED, stop
  downtime clock, then delegate to `super().call_match(node)` which
  emits `LaunchTournamentMatch`.

- Override `complete_match(node)` — the existing `advance(match)`
  logic ported: update ratings, re-queue or dequeue players based on
  `autoqueue_by_player`, mark stream cleanup.

- `completed()` overrides MatchGraph's `victory_node`-based check:
  `return self._now() >= self.end_time`.

- `victory_node` is created by `MatchGraph.create_data_structures` but
  never completes for `Ladder`. That's fine — `Ladder.completed()`
  doesn't consult it.

### 5. Update `ladder_handler.py` to consume the new API

The Discord-facing API (`queue`, `dequeue`, `autoqueue`, `challenge`,
`status`, `history`, `set_streamer`, `nostream`) keeps the same
function signatures and return shapes. Internal changes only:

- `start_ladder(guild, config, scheduled_event)` — lazy-imports
  `Ladder`, constructs it (passing through `streamed`), wires DB
  persistence, and returns the effects list from `ladder.begin()`.
- `matchmaking()` (top-level orchestration across multiple ladders) —
  unchanged in shape; internally calls `Ladder.matchmaking()` which
  now emits effects instead of returning Match objects directly.
- `call_matches()` — replaced by effect-consumption flow. The
  `LaunchTournamentMatch` effects from `Ladder.matchmaking()`
  propagate up to the top-level effect handler, which calls
  `match_handler.launch_match()` and registers the result.

## Files to modify

| File | Change |
|---|---|
| `axi/ladder.py` | Major refactor (~443 lines): inherit MatchGraph, MatchNode bookkeeping, time_fn, MatchGraph-style call_match/complete_match overrides. |
| `axi/handlers/ladder_handler.py` | Lazy-import Ladder; update matchmaking + call_matches to use effects pattern; preserve external API. |
| `axi/handlers/match_handler.py` | Add adapter for `LaunchTournamentMatch` originating from Ladder phases (small — mirrors existing tournament adapter). |
| `tests/test_ladder.py` (NEW) | Coverage for Ladder under conftest mocks: construct, begin, queue/dequeue, matchmaking, complete_match lifecycle, autoqueue, challenge, stream selection, update_ratings, completed by end_time. |

## Test plan

`tests/test_ladder.py` reuses `conftest.py` (Discord/openskill mocks
already in place). Uses `FakeClock` for `time_fn`.

Test classes:
- **TestConstruct** — Ladder constructs with a fake guild + config
  + fake clock; `begin()` populates `matches_by_pair` etc.
- **TestQueueDequeue** — `queue(user)` sets QUEUED; `dequeue(user)`
  sets BREAK; idempotent.
- **TestAddNewPlayer** — joins pre-`completed`; rejected post-`completed`.
- **TestMatchmaking** — `matchmaking([pair])` emits one
  `LaunchTournamentMatch` per pair plus stream-effect when applicable.
  No real Match objects created.
- **TestCallMatch** — `call_match(node)` transitions statuses to
  CALLED, stops downtime clock, emits `LaunchTournamentMatch`.
- **TestCompleteMatchLifecycle** — completing a match re-queues
  players if autoqueue on, otherwise dequeues; updates ratings via
  `PlackettLuceExtended`/`Glicko`/`Danisen` (mocked); appends to
  `past_matches`.
- **TestStreamSelection** — `select_stream_match` picks lowest score;
  skips repeats; emits `CallMatchForStream`.
- **TestChallenge** — `challenge(p0, p1)` reciprocity, rejection on
  3+ played pairs, on-deck queueing.
- **TestCompletedByEndTime** — pre-`end_time` False; post `False
  → True` transition via `FakeClock.advance`.
- **TestAutoqueue** — autoqueue=True keeps player in QUEUED after
  match; False sends them to BREAK.
- **TestCircularImportFixed** — direct `from axi.ladder import
  Ladder` import succeeds without errors under conftest mocks (the
  regression we're fixing).

Full pytest suite must still pass (344 tests + the new test_ladder.py
suite).

## Major architectural decisions

### A. Lazy-import to break the cycle (vs. effect-based DB)

**Decision:** lazy-import. Phase 11 handles holistic persistence
redesign across all phases; pulling that into Phase 5a balloons scope.

**Implication:** `Ladder` still calls `ladder_handler.update_ratings_db`
from inside its methods (in-method imports). Acceptable interim
coupling; Phase 11 cleans up.

### B. Inherit from `MatchGraph` (vs. ABC with both)

**Decision:** single inheritance. `Ladder(MatchGraph)` directly.

**Implication:** `Ladder` gets `nodes_by_id`, `victory_node`,
`ancestors`, `_child_ready`, etc. for free. It doesn't use most of
them — `victory_node` never completes; `ancestors` / `_child_ready`
are no-ops because Ladder matches have no parents. Acceptable
overhead.

### C. Synthetic `Tournament` for the Ladder

`MatchGraph.__init__` requires `tournament` (uses
`tournament.tournament_id`, `tournament.rng`,
`tournament.has_drop_or_dq`, `tournament.is_dropped`, `tournament.is_dq`).

**Decision:** construct a minimal `Tournament(title=ladder.name,
scope=ladder.queue_channel, seed=<derived>)` inside `Ladder.__init__`
and store it as `self.tournament`. Doesn't register with
`tournament_state` (since Ladder is its own session type). Provides
the required RNG and identity surface.

**Alternative considered (and rejected):** make `tournament` optional
on `MatchGraph`. Touches more code; weakens the invariant that bracket
formats have a Tournament. Synthetic Tournament is simpler.

### D. Match-completion callback flow

In production, `match_handler.launch_match(completion_callback=...)`
fires the callback when the Match finishes. For tournaments, the
callback is `tournament.report_match_complete(node_id, winner_id,
score)`. For Ladder, we need an equivalent —
`ladder_handler.report_match_complete(ladder_id, node_id, winner_id,
score)` that calls `ladder.complete_match(node)`.

**Decision:** add `ladder_handler.report_match_complete` mirroring
the tournament one. Wire it as the completion_callback when the
adapter calls `launch_match` in response to a
`LaunchTournamentMatch` effect that came from a Ladder phase.

(The effect carries `tournament_id` and `graph_id`; the adapter
looks up by graph_id to find the owning Ladder.)

### E. `tournament_state.nodes_to_matches` reuse

The existing `TournamentState` tracks `node_id ↔ Match` mappings.
Ladder uses the same mapping store — no new state object needed. The
`graph_id` on each `LaunchTournamentMatch` is the Ladder's graph_id;
the adapter inverts to find the Ladder via a new
`tournament_state.ladders_by_graph_id` (or similar) registry.

## What's deferred

- **Effect-based DB writes** — Phase 11.
- **Replacement of `match.description(pov=user)` callsite** in
  `ladder_handler.history` — keep using whatever the Match-attached
  description method does; once port is done, `tournament_state.get_match_for_node(node.node_id)`
  yields the underlying Match.
- **Visualization (Graphviz / Discord image)** — Phase 15.
- **Stream-match overlap heuristics** — keep current heuristic; deeper
  weighting is Phase 7.

## Resolved questions

1. **Are the existing Discord commands changing?** No. The public
   surface of `ladder_handler.py` keeps its signatures and return
   types.

2. **Does Ladder still write directly to DB?** Yes, for now, via
   lazy-import inside methods. Phase 11 reworks persistence.

3. **Does `Ladder` need a Tournament instance to inherit from
   MatchGraph?** Yes — `MatchGraph.__init__` requires one. Phase 5a
   constructs a synthetic minimal Tournament inside `Ladder.__init__`.

4. **What replaces `match_handler.launch_match()` inside Ladder?**
   `add_node` + emit `LaunchTournamentMatch`. The Discord adapter
   consumes the effect and calls `launch_match` itself, registering
   the result in `tournament_state`.

5. **What about `Match.cancel_match` and `Match.abort` flows?**
   Map to `MatchGraph.undo_match` (existing pure operation) plus an
   `ArchiveTournamentMatch` effect from `complete_match`.
