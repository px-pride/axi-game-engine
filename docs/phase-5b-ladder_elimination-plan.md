# Phase 5b: LadderElimination — Detailed Design

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 5b.

This phase introduces `LadderElimination(Ladder)` — a tournament format
that extends the refactored `Ladder` (Phase 5a) with the rising-lava
elimination mechanic. Survives as the `px` preset.

**Prerequisite:** Phase 5a must ship first. Phase 5b assumes
`Ladder` is a clean `MatchGraph` subclass with `time_fn` injection
and `MatchNode`-based bookkeeping.

## Scope

- `axi/tournament_formats/ladder_elimination.py` containing
  `LadderElimination(Ladder)` with:
  - Lava timer with configurable `lava_delay`, `lava_rate`.
  - Placement tiers (Fibonacci: 1, 2, 3, 5, 8, 13, 21, ...).
  - `USER_STATUS_ELIMINATED` status (added to `axi/util.py`).
  - `afloat`/`drowning` partition based on lava threshold.
  - Match-label state machine: `LADDER MATCH`, `DANGER MATCH`,
    `DOUBLE DANGER`, `LOSERS FINALS`, `GRAND FINALS`.
  - Escalating best_of: bo3 default → bo5 ≤8 players → bo7 final 2
    (and RPS variant 13/21/29).
  - Checkin-timer escalation: 360s normal → 480s on break, 240s RPS
    (120s rps-normal).
  - Override `update_ratings()` with 10-epoch gradient (Ladder's base
    is per-match).
  - Override `complete_match` to eliminate losers on certain labels.
  - Override `completed()` to check `player_count <= 1 + lava >= 0`.
- New `UpdateLavaUI` effect in `axi/effects.py`.
- Preset registration: `px` → `LadderElimination` factory.

## Inheritance chain after Phase 5a + 5b

```
MatchGraph (pure abstract)
  └─ Ladder (pure friendlies session, time-bounded, MatchNode-based)
       └─ LadderElimination (adds lava elimination mechanic)
```

## What Phase 5b inherits from Phase 5a (no re-implementation)

| Concern | Inherited from Ladder |
|---|---|
| `matches_by_pair`, `matches_by_player`, `current_match_by_player` | ✓ |
| `status_by_player` (QUEUED/CALLED/BREAK) | ✓ |
| `stream_history`, `stream_planned`, `stream_match`, `stream_matches_by_player`, `select_stream_match` | ✓ |
| `downtime_by_player`, `downtime_clock_by_player`, downtime hooks | ✓ |
| `generate_pairings` 100-hypothesis stochastic matchmaking | ✓ (override to add afloat/drowning context) |
| `call_match`, `complete_match` core flow | ✓ (override only the eliminate-loser logic) |
| `update_ratings` (per-match openskill/glicko/danisen) | ✗ (override with 10-epoch gradient) |
| `time_fn` injection | ✓ |
| `MatchNode`-based bookkeeping | ✓ |

The override surface shrinks dramatically vs. the original Phase 5
(commit `a688ba0`, reverted): instead of duplicating ~400 lines of
matchmaking/streaming/ratings, Phase 5b adds only the
lava/elimination layer (~150 lines).

## Algorithm port

### Constructor

```python
def __init__(self, tournament, players, stream=False,
             lava_delay=150, lava_rate=1/6,
             matchmaking_num_hypotheses=100,
             rating_num_epochs=10,
             rating_learning_rate=2.0,
             sweep_bonus=1.0,
             bo3_penalty=0.8,
             matchup_regularization=1.0,
             checkin_normal=360,
             checkin_break=480,
             checkin_rps=240,
             time_fn=None):
    # Build the synthetic config / Tournament that Ladder expects.
    # (For tournament-mode use, the caller supplies a real Tournament
    # via the Phase 1 preset path.)
    super().__init__(tournament, players, stream=stream, time_fn=time_fn)
    self.lava_delay = lava_delay
    self.lava_rate = lava_rate
    self.matchmaking_num_hypotheses = matchmaking_num_hypotheses
    self.rating_num_epochs = rating_num_epochs
    self.rating_learning_rate = rating_learning_rate
    self.sweep_bonus = sweep_bonus
    self.bo3_penalty = bo3_penalty
    self.matchup_regularization = matchup_regularization
    self.checkin_normal = checkin_normal
    self.checkin_break = checkin_break
    self.checkin_rps = checkin_rps
```

### `create_data_structures()` extension

Calls `super().create_data_structures()` (which initializes Ladder's
bookkeeping), then adds:
- `placement_tiers = [1, 2]`; grow via `update_placement_tiers()` until
  last tier ≥ `player_count`.
- `lava_snapshot = -1`, `placement_snapshot = -1`,
  `players_in_danger = []`.
- `lava_start_time = self._now()` (overrides Ladder's `end_time`-only
  semantics).

### `get_lava_timer()` / `get_lava_level()`

Same as source / original Phase 5:
- `get_lava_timer() = self._now() - (lava_start_time + lava_delay)`.
- `get_lava_level()` returns lava_timer when negative; otherwise
  the placement-tier snapshot clamped to `min(player_count, tier)`
  (source semantics).

### `update_placement_tiers()`

Fibonacci continuation:
```python
while self.placement_tiers[-1] < self.player_count:
    self.placement_tiers.append(
        self.placement_tiers[-1] + self.placement_tiers[-2])
```

### Override `generate_pairings(afloat, drowning)`

Ladder's base takes just `available`. LadderElim's variant splits
into afloat + drowning. Calls `super().generate_pairings(available)`
internally if useful, or re-implements with the drowning-aware
scoring (the latter is what source does).

### Override `generate_bracket(pairings, afloat, drowning,
set_stream_match)`

Builds MatchNodes per Phase 5a's pattern, but with labels:
- Pre-lava: all LADDER MATCH.
- Post-lava with `player_count == 2`: GRAND FINALS.
- Post-lava with `player_count == 3`: LOSERS FINALS.
- Post-lava with both drowning: DOUBLE DANGER.
- Post-lava with one drowning: DANGER MATCH (drowning forced to idx 1).
- Otherwise: LADDER MATCH.

best_of and checkin_timer per the source escalation tables.

### Override `complete_match(node)`

Calls `super().complete_match(node)` (Ladder base — re-queues
players, updates ratings, etc.), then:
- If `node.label != "LADDER MATCH"`: drop players from
  `players_in_danger`.
- If `node.label` in `("GRAND FINALS", "LOSERS FINALS",
  "DOUBLE DANGER")`: `eliminate_user(node.loser())`.
- If `node.label == "DANGER MATCH"` and the loser is the drowning
  player (idx 1): `eliminate_user`.
- If `node.label == "GRAND FINALS"`: set winner's placement to 1 and
  complete `victory_node`.
- Re-run `matchmaking()` (Ladder's base does NOT auto-rerun
  matchmaking; LadderElim does because lava progresses).
- Emit `UpdateLavaUI` effect at end.

### Override `update_ratings()`

10-epoch gradient descent over all `past_matches`. Per pair:
- `bo3_factor = 1.0 if best_of == 3 else 1/bo3_penalty`
- `sweep_factor = sweep_bonus if is_sweep else 1.0`
- accumulate weighted wins, normalize by `(1 + reg) / (total + reg)`
- compute deltas via the rating model
- apply deltas with `learning_rate / num_epochs` step size

For test environments where openskill is mocked, the rating model's
`calculate_deltas` returns MagicMocks. Wrap the gradient math in a
try/except that no-ops if the rating model fails — preserves
behavior for tests that don't assert on specific rating values.

### `eliminate_user(user)`

- If `placement_snapshot > 0`: `placements_dict[user] = placement_snapshot`.
- Else: walk `placement_tiers` from top down to find the right tier.
- Set `status_by_player[user] = USER_STATUS_ELIMINATED`.
- Stop downtime clock; decrement `player_count`.

### `add_new_player(user)` override

Pre-lava (lava_level < initial_rating[0] = 0): accept (delegate to
Ladder's `add_new_player`).
Post-lava: reject.

### `completed()` override

`player_count <= 1 and get_lava_level() >= 0`. If `player_count == 1`,
assign winner placement.

### `select_stream_match(matches)` override

Same as source: skip recently-streamed (except GF/LF), prefer
matches with small rating differential, penalize repeat streamers
and LADDER MATCH label.

### `_make_lava_ui_effect()`

```python
UpdateLavaUI(
    tournament_id=self.tournament_id,
    graph_id=self.graph_id,
    lava_level=self.get_lava_level(),
    placement_snapshot=self.placement_snapshot,
    players_in_danger=[
        getattr(p.uid, "id", None) for p in self.players_in_danger
    ],
)
```

## Files to add / modify

| File | Change |
|---|---|
| `axi/util.py` | Add `USER_STATUS_ELIMINATED = 3`. |
| `axi/effects.py` | Add `UpdateLavaUI` dataclass. |
| `axi/tournament_formats/ladder_elimination.py` (NEW) | `LadderElimination(Ladder)` with lava overrides. |
| `tests/test_ladder_elimination.py` (NEW) | 60+ tests covering lava/elimination, label state machine, best_of/checkin escalation, end-to-end smoke. |

## Test plan

Reuse `tests/conftest.py` (Discord/openskill mocks). FakeClock
injected via `time_fn`. Tests fully isolated — no real Discord, no
real openskill math (use the `_ElementaryRatingModel`-equivalent
pattern from the reverted Phase 5 tests).

Test classes (mirrors the reverted-Phase-5 test plan but inherits
Ladder behavior so many integration tests are smaller):

1. `TestUtilConstant` — USER_STATUS_ELIMINATED == 3, distinct.
2. `TestConstructor` — defaults + custom kwargs propagate.
3. `TestPlacementTiers` — Fibonacci for n∈{2, 8, 15, 100}.
4. `TestLavaTimer` — pre/at/post delay via FakeClock.
5. `TestLavaLevel` — pre-lava negative, post-lava source-clamped.
6. `TestStatusTransitions` — eliminate_user sets ELIMINATED,
   decrements count, idempotent.
7. `TestEliminatePlacement` — snapshot vs tier-walk paths.
8. `TestAfloatDrowning` — pre-lava all afloat, post-lava partition,
   count<=3 endgame special.
9. `TestMatchLabels` — all 5 labels, DANGER swap-to-idx-1.
10. `TestBestOfEscalation` — bo3/5/7 + RPS variant 13/21/29.
11. `TestCheckinTimer` — 360/480 + RPS 120/240.
12. `TestUpdateLavaUIEffect` — emitted on matchmaking + begin.
13. `TestCompleteMatchLifecycle` — LADDER no-elim, DANGER eliminates
    idx-1 loser, DOUBLE DANGER eliminates loser, GRAND FINALS
    completes victory_node + sets winner placement.
14. `TestUpdateRatingsOverride` — 10-epoch gradient (vs Ladder's
    per-match); winner threshold > loser after match.
15. `TestAddNewPlayer` — accepted pre-lava, rejected post-lava.
16. `TestPresetRegistration` — `'px' in PRESETS`.
17. `TestEndToEnd` — 4 players, fast lava, run to victory_node.

## Major decisions

### A. Inherit from Ladder, not from MatchGraph

Already settled by the architectural rethink. Phase 5b just executes
on it.

### B. Override `update_ratings`, don't re-implement

Ladder's `update_ratings` is per-match (mid-flow). LadderElim's is
batch (10-epoch gradient over all `past_matches`). Override; don't
call super.

### C. Override `complete_match`, call super

The base does the "transition to COMPLETED, re-queue players, append
to past_matches" plumbing. LadderElim adds lava-specific
post-processing.

### D. Synthetic Tournament via Ladder's existing pattern

Phase 5a already establishes how Ladder constructs/uses a synthetic
Tournament. Phase 5b inherits the pattern unchanged.

### E. lava_snapshot semantics: source-clamped

`lava_snapshot = min(player_count, tier)`. The original Phase 5
design doc claimed `lava_snapshot=13 for 10 players, tiers
[1,2,3,5,8,13]` — that was incorrect vs source's `min()` clamp.
Phase 5b follows source semantics (10-player case gives
`lava_snapshot=10, placement_snapshot=9`).

## What's deferred

- **Phase 7:** drowning matchmaking weights — Phase 5b uses the
  simpler rating-only generator.
- **Phase 9:** check-in timer expiry → forfeit handling.
- **Phase 11:** persisting LadderElimination state to DB.
- **Phase 13:** PXL config `pxl` preset.
- **Phase 14:** Discord commands (`/ladder`, `/takeabreak`, etc.).
- **Phase 15:** Graphviz lava-bar visualization.

## Resolved questions

1. **Time injection** — inherited from Phase 5a Ladder.
2. **Rating model interface** — inherited from Phase 5a Ladder.
3. **Static vs dynamic bracket** — dynamic, same as original Phase 5.
4. **Drowning cap** — `player_count - placement_snapshot + 1` (source).
5. **Configurable params** — all 7 tuning params from source plus
   3 checkin timers, all kwargs.
6. **`update_ratings` mocked-openskill compatibility** — wrap in
   try/except; tests use real math via injected
   `_ElementaryRatingModel` if needed (same approach as reverted
   Phase 5).
