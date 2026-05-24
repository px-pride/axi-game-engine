# Phase 7: Drowning matchmaking weights + cross-ladder tuning

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 7.

Phase 7 wires drowning awareness into `ladder_handler.score_hypothesis`
so that elimination matches happen on time when the lava is rising
(Phase 5b). It also fixes a latent `NameError` bug at
`ladder_handler.py:279` and `:647` (bare `ladders.values()` instead of
`state.ladders.values()`), and revisits the cross-ladder stream-ratio
heuristic to bias toward the primary ladder.

## Scope

- Add **`w_num_drowning`** weight to `ladder_handler.score_hypothesis`:
  +50 per drowning player per viable pair. Drives the matchmaker to
  prefer hypotheses that have drowning players in matches, ensuring
  Phase 5b's elimination clock isn't starved.
- Add **`w_stream_drowning`** weight to `score_hypothesis`: +50 if the
  chosen stream match has drowning players. Drives stream selection
  to favor elimination-relevant matches.
- Replace `desired_stream_ladder_ratio` (currently uniform `1/N`) with
  source's primary-biased `[0.5, 0.5/(N-1), ...]` pattern.
- Wire `ladder_handler.matchmaking` to compute per-ladder drowning
  partitions (via the new `Ladder.afloat_and_drowning` default + the
  existing `LadderElimination.afloat_and_drowning` override) so
  `score_hypothesis` has the drowning set per ladder.
- Fix the bare-`ladders.values()` NameError at
  `ladder_handler.py:279` and `:647` → `state.ladders.values()`.

## Files to modify

| File | Change |
|---|---|
| `axi/handlers/ladder_handler.py` | Add `w_num_drowning` + `w_stream_drowning` to `score_hypothesis`; replace uniform `desired_stream_ladder_ratio` with primary-biased pattern; fix bare-`ladders.values()` typos; thread drowning sets through `matchmaking()`. |
| `axi/ladder.py` | Add default `afloat_and_drowning(users, breakers)` that returns `(users + breakers, [])` — friendlies have no drowning. `LadderElimination` already overrides. |
| `tests/test_ladder.py` | Add 1 test: `Ladder.afloat_and_drowning` returns all-afloat, no-drowning. |
| `tests/test_ladder_elimination.py` (existing) | No change — afloat/drowning tests already exist. |
| New: `tests/test_ladder_handler_scoring.py` | NEW tests for the scoring math + the desired-stream-ratio change + the bare-`ladders` regression. |

## Source ↔ target diff

### `score_hypothesis` — what source has, what target lacks

Source (`/tmp/claude-1001/tourney-inspect/ladder_manager.py:204–293`):
```python
w_num_drowning = 50          # +50 per drowning player per pair
w_stream_drowning = 50       # +50 if stream match has drowning players
desired_stream_ladder_ratio = [0.5]
for i in range(1, len(self.ladders)):
    desired_stream_ladder_ratio.append(0.5 / (len(self.ladders) - 1))
```

Target (`axi/handlers/ladder_handler.score_hypothesis`):
- Missing `w_num_drowning` and `w_stream_drowning`.
- `desired_stream_ladder_ratio = {l: 1.0 / len(state.ladders) for l in ladders.values()}` — broken (bare `ladders`) AND uniform.

### Algorithm port

```python
# Inside score_hypothesis, after the existing per-pair scoring loop:

w_num_drowning = 50

for l in pairings:
    drowning_for_l = drowning.get(l, set())
    for pair_list in (pairings[l][0], pairings[l][1]):
        for (p0, p1) in pair_list:
            for p in (p0, p1):
                if p in drowning_for_l:
                    score += w_num_drowning
```

And for the stream block:
```python
w_stream_drowning = 50

for l_ in stream_match_hypothesis:
    stream_pair = stream_match_hypothesis[l_]
    if not stream_pair:
        continue
    # ... existing w_stream_match_called/repeat ...
    drowning_for_l = drowning.get(l_, set())
    for p in stream_pair:
        if p in drowning_for_l:
            score += w_stream_drowning
```

And for the diversity block:
```python
ladders_list = list(state.ladders.values())
desired_stream_ladder_ratio = {}
if ladders_list:
    desired_stream_ladder_ratio[ladders_list[0]] = 0.5
    for ll in ladders_list[1:]:
        desired_stream_ladder_ratio[ll] = 0.5 / max(1, len(ladders_list) - 1)
```

(Replaces the broken `{l: 1.0 / len(state.ladders) for l in ladders.values()}`.)

### Wiring drowning through `ladder_handler.matchmaking()`

Currently `matchmaking()` iterates ladders, computes `unoccupied[p]`,
generates pairings via `generate_pairing_hypothesis(l, setting[l])`,
and scores via `score_hypothesis(pairings, set_stream_match)`. It
does NOT compute drowning sets per ladder.

**Refactor:**
1. After computing `setting[l]` for each ladder, also call
   `l.afloat_and_drowning(setting[l], [])` to derive `(afloat[l],
   drowning[l])`.
2. Pass `drowning` dict (keyed by ladder) into `score_hypothesis`.
3. Optional follow-up: also pass `afloat` into
   `generate_pairing_hypothesis` so it has full context — but for
   Phase 7 keep this minimal: drowning only flows into scoring, not
   into pairing generation. (Pairing generation already happens
   inside `LadderElimination.generate_pairings` for the elim case.)

### `Ladder.afloat_and_drowning` default

Add a no-op default on Ladder so `ladder_handler.matchmaking` can
call it uniformly:

```python
def afloat_and_drowning(self, users, breakers):
    """Default: no drowning concept (friendlies). Subclasses override."""
    return list(users) + list(breakers), []
```

LadderElimination already overrides this and returns the lava-derived
partition. Both signatures are compatible.

### `state.ladders.values()` fix

Two callsites:
- `axi/handlers/ladder_handler.py:279` — inside score_hypothesis,
  inside the per-stream diversity block:
  ```python
  desired_stream_ladder_ratio = {l: 1.0 / len(state.ladders) for l in ladders.values()}
  # NameError: ladders is not defined
  ```
- `axi/handlers/ladder_handler.py:647` — inside `push_ladder_updates`:
  ```python
  return [UpdateLadderUI(ladder_id=id(l)) for l in ladders.values()]
  # NameError
  ```

Fix both: change `ladders.values()` → `state.ladders.values()`.

## Test plan

`tests/test_ladder_handler_scoring.py` (NEW):

1. **`TestNameErrorRegression`** — call `push_ladder_updates()` with an
   empty `state.ladders` dict → returns `[]` without NameError. With
   one ladder → returns `[UpdateLadderUI(...)]` correctly. (Pre-fix
   this would have raised NameError.)

2. **`TestDrowningWeights`** — construct a minimal `pairings` dict and
   `drowning` dict; call `score_hypothesis` and verify:
   - Pair with both players drowning adds `2 * w_num_drowning = 100`.
   - Pair with one drowning adds `50`.
   - Pair with no drowning adds 0.
   - Stream match with drowning adds `w_stream_drowning = 50`.

3. **`TestDesiredStreamLadderRatio`** — when 1 ladder: ratio = {l: 0.5}
   (degenerate but documented). When N ladders: first gets 0.5,
   remaining N-1 each get `0.5/(N-1)`.

4. **`TestAfloatDrowningDefault`** (in `test_ladder.py`):
   - `Ladder.afloat_and_drowning([p1, p2], [])` → `([p1, p2], [])`.
   - `Ladder.afloat_and_drowning([p1], [p2])` → `([p1, p2], [])`.

5. **`TestLadderElimDrowningOverride`** (already covered in
   `test_ladder_elimination.py::TestAfloatDrowning` — no new test).

Full suite: `uv run pytest` must still pass 444+ tests.

## Major decisions

### A. Pure-handler change vs. Ladder API change

The drowning weights live in the **handler** (`ladder_handler.py`),
which is consistent with the "scoring of cross-ladder matchmaking
hypotheses is a handler concern" intent. The Ladder/LadderElimination
classes only expose the drowning set via `afloat_and_drowning`; the
handler decides how to weight it.

### B. Default `afloat_and_drowning` on Ladder

The handler calls `l.afloat_and_drowning(users, [])` uniformly across
all ladders. Friendlies (Ladder base) returns no drowning;
LadderElimination returns its lava-derived partition. This keeps the
handler subclass-agnostic.

### C. desired_stream_ladder_ratio bias

Source's `[0.5, 0.5/(N-1), ...]` pattern is asymmetric — the first
ladder is preferred. For PXL setups this is the "main bracket" and
the rest are secondary. We follow source's pattern. **Decision:** use
iteration order of `state.ladders` to determine primacy. Phase 13's
PXL config can pin a specific ladder as primary by registering it
first.

### D. Pairing generation NOT touched

`generate_pairing_hypothesis` already excludes most stale pairs; it
doesn't need drowning awareness because:
- LadderElim's own `generate_pairings` (called from
  `LadderElimination.matchmaking`) is drowning-aware.
- The handler-level pairing path is for cross-ladder coordination —
  scoring is the right layer to inject drowning preference.

### E. NameError fix scoped to Phase 7

These bugs are tracked in the deck notes' "INCIDENTAL BUGS" list.
Phase 7 fixes them since we're touching that file anyway. The other
two listed bugs (`/lag stale x!drop text` and `/lag thresholds
mismatch source`) remain deferred.

## Open questions resolved

1. **What if `state.ladders` is empty inside `score_hypothesis`?**
   Skip the diversity block; `desired_stream_ladder_ratio` defaults
   to empty dict and is iterated safely.

2. **`drowning` arg signature in `score_hypothesis`?**
   `Dict[Ladder, Set[Player]]`. Keyed by ladder, values are drowning
   players in that ladder. Empty set if not provided.

3. **Backward compat for `score_hypothesis` callers?**
   The existing call site (`ladder_handler.matchmaking`) is the only
   caller. Both get updated together.

4. **Does LadderElimination still call its own scoring?**
   Yes, `LadderElimination.generate_pairings` has internal scoring
   for hypothesis selection (rating-diff penalty, rematch penalty,
   drowning bonus). Phase 7's scoring is at a different layer
   (cross-ladder matchmaking selection), not the per-hypothesis
   pairing selection. They're independent.

## What's deferred

- **Pairing-generation drowning awareness** (handler level) — Phase 7
  keeps pairing generation drowning-unaware. If lava-rise testing
  later shows drowning players aren't getting paired enough, revisit.
- **Custom `primary` flag on Ladder** for explicit primacy — Phase 13
  PXL config decides this.
- **The other two incidental bugs** (`/lag` text + thresholds) —
  separate work.
