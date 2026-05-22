# Phase 5: LadderElimination (the 'px' preset) — Detailed Design

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 5.

This phase introduces `LadderElimination` — a tournament format where
players queue continuously and "lava" rises over time, eliminating
the bottom-ranked players in tiers. Survives as the `px` preset.

## Scope

- `axi/tournament_formats/ladder_elimination.py` containing:
  - `LadderElimination(MatchGraph)` — top-level orchestrator.
  - Lava timer with configurable `lava_delay`, `lava_rate`.
  - Placement tiers (Fibonacci: 1, 2, 3, 5, 8, 13, 21, ...).
  - Player statuses: `QUEUED`, `CALLED`, `BREAK`, `ELIMINATED`.
  - `afloat`/`drowning` partition based on lava threshold.
  - Match-label state machine: `LADDER MATCH`, `DANGER MATCH`,
    `DOUBLE DANGER`, `LOSERS FINALS`, `GRAND FINALS`.
  - Escalating best_of: bo3 default → bo5 ≤8 players → bo7 final 2.
  - Checkin-timer escalation: 360s normal → 480s on break, 240s RPS.
  - Stochastic pairing generator (`generate_pairings`).
  - Rating model integration (OpenSkill default, Glicko alternative).
  - `update_ratings` with 10-epoch gradient updates.
- Preset registration: `px` (default LadderElimination, OpenSkill).
- New `axi/util.py` constants for user-status enum (already exist as
  `USER_STATUS_QUEUED`/`BREAK`/`CALLED`; add `USER_STATUS_ELIMINATED`).
- Effects: reuse `LaunchTournamentMatch`, `ArchiveTournamentMatch`;
  add `UpdateLavaUI(lava_level, placement_snapshot, players_in_danger)`
  for Discord status updates (executed by Phase 14 cmd handlers later).

## Major architectural decisions

### 1. MatchGraph subclass (not Ladder subclass)

Source has both `AbstractLadder` (continuous friendlies) and
`LadderElimination(MatchGraph)` (tournament-elimination ladder). Target
already has `axi/ladder.py` for the friendlies-style flow (Phase 6).

**Decision:** `LadderElimination` extends `MatchGraph`, lives in
`axi/tournament_formats/ladder_elimination.py`, integrates with
`Tournament` as a phase. NOT a `Ladder` subclass. Keeps tournament code
in `tournament_formats/`, ladder code in `axi/ladder.py`. No cross
coupling.

### 2. Time injection for testability

Source calls `time.time()` directly throughout. Tests can't deterministically
simulate the lava clock.

**Decision:** Accept `time_fn=None` constructor param; default to
`time.time` when None. Tests inject a `FakeClock().now` callable that
they can advance. `lava_start_time` is captured at `create_data_structures`
using `self._now()`.

### 3. Dynamic matchmaking (generate_bracket returns [])

MatchGraph's contract: `generate_bracket()` returns the initial set of
matches to call. LadderElimination doesn't have a static bracket — it
generates pairings dynamically as players become available.

**Decision:** `generate_bracket()` runs initial matchmaking from the
QUEUED player set and returns those matches. Subsequent rounds are
spawned via `complete_match` triggering `matchmaking()` again. All matches
are created with `add_node` so they're tracked in `nodes_by_id`.

Players join/leave via `queue(user)` / `take_a_break(user)` /
`eliminate_user(user)`, with the matchmaker re-invoked on each call.

### 4. No round-graph parent linkage

Source's matches have no parent linkage at all — each new match is
independent. We follow this. No `link_parent` calls. `_child_ready` /
`ancestors` aren't exercised since `parents` is empty.

### 5. Lava-level UI updates as effects

Source calls `discord_manager.update_lava_msg` directly. We emit
`UpdateLavaUI(lava_level, placement_snapshot, players_in_danger)`
effects from the points where the lava state changes (after
`complete_match`, after `add_new_player`, after `eliminate_user`). The
adapter renders the lava bar; tests assert the effect was emitted.

## Algorithm port

### Constructor

```python
def __init__(self, tournament, players, stream=False,
             lava_delay=150, lava_rate=1/6,
             rating_model="openskill",
             initial_rating=None,
             matchmaking_num_hypotheses=100,
             rating_num_epochs=10,
             rating_learning_rate=2.0,
             sweep_bonus=1.0,
             bo3_penalty=0.8,
             matchup_regularization=1.0,
             time_fn=None):
    super().__init__(tournament, players, stream=stream)
    self.lava_delay = lava_delay
    self.lava_rate = lava_rate
    self._rating_model_name = rating_model
    self._initial_rating_override = initial_rating
    self.matchmaking_num_hypotheses = matchmaking_num_hypotheses
    self.rating_num_epochs = rating_num_epochs
    self.rating_learning_rate = rating_learning_rate
    self.sweep_bonus = sweep_bonus
    self.bo3_penalty = bo3_penalty
    self.matchup_regularization = matchup_regularization
    self._time_fn = time_fn or time.time
```

All Fibonacci tiers, rating model selection, status init happen in
`create_data_structures` (so they reset on test cleanup).

### `create_data_structures()`

Overrides base. Calls `super().create_data_structures()` then:
- `self.past_matches = []`
- Pick rating model: `openskill` → `PlackettLuceExtended`; `glicko` →
  `GlickoTimeless`. Initial rating `(0, Rating(mu=300, sigma=100))`.
- `lava_start_time = self._now()`
- `ratings_by_player = {p: initial_rating for p in self.players}`
- `stream_matches_by_player`, `downtime_by_player`,
  `downtime_clock_by_player`, `status_by_player = QUEUED for all`
- `placement_tiers = [1, 2]`; call `update_placement_tiers()` to grow
  the list until last tier ≥ `player_count`.
- `lava_snapshot = -1`, `placement_snapshot = -1`,
  `players_in_danger = []`

### `update_placement_tiers()`

```python
def update_placement_tiers(self):
    while self.placement_tiers[-1] < self.player_count:
        self.placement_tiers.append(
            self.placement_tiers[-1] + self.placement_tiers[-2])
```

Fibonacci continuation until coverage ≥ player count.

### `get_lava_timer()` / `get_lava_level()`

```python
def get_lava_timer(self):
    return self._now() - (self.lava_start_time + self.lava_delay)

def get_lava_level(self):
    lava_timer = self.get_lava_timer()
    if lava_timer < 0:
        return lava_timer
    if 0 < self.placement_snapshot <= self.player_count:
        return self.lava_snapshot
    # Walk placement_tiers from largest down, find the tier that brackets
    # current player_count. Set lava_snapshot, placement_snapshot.
    ...
```

`lava_snapshot` is the placement tier number representing the "current
elimination bracket" (e.g. 8 means "bottom-8 are at risk"). `placement_snapshot`
is the placement number for currently at-risk players (e.g. 5 means
"the player about to be eliminated will be placement 5").

### `get_at_risk()`

Returns players within the danger zone based on rating threshold. Top
of the at-risk list = lowest-rated non-eliminated players.

### `afloat_and_drowning(users, breakers)`

Partitions queued+break players into:
- `afloat`: players above the lava (safe this round).
- `drowning`: players at-risk; their next match becomes a `DANGER MATCH`
  or `DOUBLE DANGER`.

Special cases:
- If lava ≥ 0 and total players ≤ 3, only the bottom 2 are drowning;
  the rest are forced into the match.
- Single at-risk left: bottom-breaker is pulled in if no other available.

### `generate_pairings(afloat, drowning)`

Stochastic 100-hypothesis matchmaking:
- Shuffle available players.
- Pair sequentially. For each pair: compute viability (no rematch unless
  late stage) + score (rating diff, repetition penalty, bonus for fresh
  pair).
- Track best hypothesis.

For final 2 (player_count == 2 with lava ≥ 0), force `(drowning[0],
drowning[1])`.

### `generate_bracket(pairings, afloat, drowning, set_stream_match)`

Creates `MatchNode`s for the given pairings. Determines:
- `best_of`: 3 default; 5 if `player_count <= 8` and lava ≥ 0;
  7 if `player_count == 2` and lava ≥ 0.
  (For `rps` game: 13/21/29 instead of 3/5/7.)
- `checkin_timer`: 360s normal, 480s if either player is on break.
  RPS: 120s normal, 240s on break.
- `label`:
  - `GRAND FINALS` if player_count == 2 and lava ≥ 0
  - `LOSERS FINALS` if player_count == 3 and lava ≥ 0
  - `DOUBLE DANGER` if both in drowning
  - `DANGER MATCH` if exactly one in drowning (drowning player is `pair[1]`)
  - `LADDER MATCH` otherwise (or always if lava < 0)
- For drowning players: add to `players_in_danger` (capped at
  `player_count - placement_snapshot + 1`); if cap hit, demote back to
  afloat.

### `matchmaking()` entrypoint

```python
def matchmaking(self):
    queued, break_, eliminated, called = self.get_players_by_status()
    afloat, drowning = self.afloat_and_drowning(queued, break_)
    pairings = self.generate_pairings(afloat, drowning)
    matches = self.generate_bracket(pairings, afloat, drowning,
                                     set_stream_match=True)
    effects = []
    stream_candidates = []
    for m in matches:
        if m.streamed:
            stream_candidates.append(m)
        else:
            effects += self.call_match(m)
    if not self.stream_match:
        effects += self.call_match_for_stream(stream_candidates)
    effects.append(self._make_lava_ui_effect())
    return effects
```

### `call_match(match)` override

Set every player's status to `CALLED`, stop their downtime clock, then
delegate to `super().call_match()`.

### `complete_match(node)` override

```python
def complete_match(self, node):
    effects = super().complete_match(node)
    self.past_matches.append(node)
    for p in node.players:
        if self.status_by_player[p] == USER_STATUS_CALLED:
            self.queue(p)
    self.update_ratings()
    # Eliminate loser of elimination labels.
    if node.label in ("GRAND FINALS", "LOSERS FINALS", "DOUBLE DANGER") \
            or (node.label == "DANGER MATCH"
                and node.loser() == node.players[1]):
        self.eliminate_user(node.loser())
    if node.label == "GRAND FINALS":
        self.placements_dict[node.winner()] = 1
        if self.victory_node is not None and not self.victory_node.completed():
            from axi.util import MATCH_STATUS_COMPLETED
            self.victory_node.players = [node.winner()]
            self.victory_node.status = MATCH_STATUS_COMPLETED
    # Drop players_in_danger entries for any played danger match.
    if node.label != "LADDER MATCH":
        for p in node.players:
            if p in self.players_in_danger:
                self.players_in_danger.remove(p)
    # Re-run matchmaking.
    effects += self.matchmaking()
    return effects
```

### `eliminate_user(user)`

Source's algorithm:
- Set `placements_dict[user] = placement_snapshot`.
- If no snapshot exists, walk `placement_tiers` from top down:
  the largest tier ≤ `player_count` determines the placement.
- Mark status ELIMINATED; stop downtime clock; decrement `player_count`.

### `add_new_player(user)`

Mid-tournament joins are allowed until lava reaches the initial-rating
floor (`get_lava_level() >= initial_rating[0]`). Else reject.

If accepted: append to `players`, seed at end, initialize all per-player
dicts, queue, run matchmaking.

### `take_a_break(user)`, `queue(user)`, `drop_user(user)`, `dq_user(user)`

Standard status transitions. `drop_user` / `dq_user` eliminate the user
(score auto-reported as `0-first_to` against opponent if mid-match).

### `update_ratings()`

10-epoch gradient descent over all past matches. For each pair:
- Compute weighted wins: `wins = match_wins * bo3_factor * sweep_factor`
- Normalize by total matches with regularization.
- Run rating model deltas; apply with `learning_rate / num_epochs`.

After all epochs, commit ratings for non-eliminated players.

`PlackettLuceExtended` and `GlickoTimeless` already exist in
`axi/ratings/`. We use their `__init__([rating_a, rating_b])` +
`calculate_deltas()` interface.

### `select_stream_match(matches)`

- Skip matches whose players were streamed in the last 2 events
  (except GF/LF).
- Score by rating differential + frequency-of-stream penalty (250 per
  prior stream) + `LADDER MATCH` penalty (+100, prefer DANGER over LADDER).
- Pick lowest score.

### `score_stream_match(match)` override

Used by base `call_match_for_stream` to pick from a pool:
- Lower score = better candidate.
- `below_lava` flag (1 if any player below lava threshold, 0 otherwise).
- Rating differential.
- Index in `stream_planned`.
- Returns tuple for lex-sort.

### `completed()`

```python
def completed(self):
    result = self.player_count <= 1 and self.get_lava_level() >= 0
    if result and self.player_count == 1:
        winner = self.get_non_elim_sorted()[0]
        self.placements_dict[winner] = 1
    return result
```

### Preset registration

```python
@register_preset("px")
def _preset_px(t):
    def factory(tournament, players):
        return LadderElimination(tournament, players, stream=False)
    return [factory], "Ladder elimination (px-style)."
```

`pxl` adds OpenSkill+streaming defaults (per audit notes; finalized in
Phase 13 PXL config).

## Files to add / modify

```
NEW  axi/tournament_formats/ladder_elimination.py
NEW  axi/effects.py — UpdateLavaUI effect
MOD  axi/util.py    — add USER_STATUS_ELIMINATED constant
```

No Phase 1-4 changes needed. `axi/ladder.py` (friendlies) untouched.

## Test plan

`tests/test_ladder_elimination.py`:

### Setup helpers
- `FakeClock` — settable `.now`, advanced via `.advance(seconds)`.
- `make_players(n, p1)` — reuse from existing test patterns.
- Construct with `time_fn=clock.now`; advance clock to simulate lava rise.

### Constructor and config
- Default lava_delay=150, lava_rate=1/6, rating_model="openskill".
- Custom params propagated.

### Placement tiers (Fibonacci)
- `player_count=1` → tiers [1, 2].
- `player_count=8` → tiers [1, 2, 3, 5, 8].
- `player_count=15` → tiers [1, 2, 3, 5, 8, 13, 21] (last >= 15).
- `player_count=100` → extends to 144.

### Lava timer
- `get_lava_timer()` returns negative before `lava_start_time + lava_delay`.
- Returns positive after.

### Lava level / snapshot
- Pre-lava (timer < 0): `get_lava_level() < 0`, no snapshot.
- Post-lava with 10 players, tiers [1,2,3,5,8,13]: lava_snapshot=13,
  placement_snapshot=9 initially (bottom 9-13 are at risk).
- After eliminating to 5 players: lava_snapshot=5, placement_snapshot=4.

### Status transitions
- `queue(user)` → QUEUED.
- `take_a_break(user)` → BREAK.
- `call_match(match)` → all match players CALLED.
- `eliminate_user(user)` → ELIMINATED, decrements player_count.

### Match labels (post-lava)
- 8 players, lava ≥ 0, 2 players drowning: produces DANGER MATCH.
- 8 players, lava ≥ 0, both drowning: produces DOUBLE DANGER.
- 3 players, lava ≥ 0: LOSERS FINALS.
- 2 players, lava ≥ 0: GRAND FINALS.
- Any setup, lava < 0: LADDER MATCH only.

### Match labels (pre-lava)
- All matches LADDER MATCH regardless of player count.

### Best_of escalation
- `player_count > 8` or lava < 0: bo3.
- `player_count <= 8`, lava ≥ 0: bo5.
- `player_count == 2`, lava ≥ 0: bo7.
- RPS game variant: 13/21/29 instead.

### Checkin timer
- All-queued: 360s (120 for RPS).
- Either on break: 480s (240 for RPS).

### afloat / drowning partition
- Pre-lava (timer < 0): all queued in afloat, none drowning.
- Post-lava, 10 players, bottom 3 by rating: drowning = bottom 3.
- Post-lava with breakers: breaker can still be drowning if at-risk.
- `player_count == 3` end-game: only bottom 2 are drowning.

### generate_pairings
- Pairs available players up.
- Rejects rematches unless `player_count - 1` matches per player (late stage).
- Odd count: last unpaired player penalized.

### generate_bracket integration
- Returns matches with correct labels, BO, timer.
- Drowning players added to `players_in_danger` (capped).
- Stream match selected if `stream=True`.

### complete_match lifecycle
- LADDER MATCH: loser stays in tournament; both go back to queue.
- DANGER MATCH: drowning loser eliminated (the one at index 1).
- DOUBLE DANGER: loser eliminated.
- LOSERS FINALS: loser eliminated.
- GRAND FINALS: loser eliminated, winner placed 1st, victory_node completed.
- After completion: matchmaking re-runs.

### update_ratings
- No completed matches: no-op.
- Single completed match: ratings shift in expected direction.
- Sweep adds bonus; BO5 unaffected by penalty.

### Eliminations
- Eliminating bottom player sets placements_dict to placement_snapshot.
- Eliminating without snapshot: walks placement_tiers correctly.

### add_new_player
- Pre-lava: accepted, added to QUEUED.
- Post-lava-floor: rejected (`get_lava_level() >= initial_rating[0]`).

### Preset registration
- `px` is in PRESETS.
- `apply_preset(t, "px")` sets phase_fns and format string.

### End-to-end smoke
- 4 players, fast lava: simulate full bracket to one winner.
- victory_node completes, all placements assigned.

## Resolved questions (no open items)

1. **Time injection** → `time_fn` constructor param defaulting to
   `time.time`. Tests inject a fake clock for deterministic lava rise.

2. **Friendlies vs elimination** → keep separate. `axi/ladder.py`
   handles persistent friendlies (Phase 6). LadderElimination is its
   own MatchGraph in `axi/tournament_formats/`.

3. **Static vs dynamic bracket** → dynamic. `generate_bracket` runs
   initial matchmaking; subsequent matches via `complete_match` →
   `matchmaking()` re-trigger. No `link_parent` calls.

4. **Rating model interface** → use existing
   `PlackettLuceExtended` / `GlickoTimeless` from `axi/ratings/`.
   Default to OpenSkill (PlackettLuce).

5. **Drowning cap** → matches source: `player_count - placement_snapshot + 1`.
   Caps how many "danger" players can be in active matches; excess
   demoted to afloat for this round.

6. **Configurable params** → all 7 numeric tuning params from source
   exposed as constructor kwargs (lava_delay, lava_rate,
   matchmaking_num_hypotheses, rating_num_epochs, rating_learning_rate,
   sweep_bonus, bo3_penalty, matchup_regularization).

7. **Stream match overlap** → reused source's "skip if streamed in last 2
   events" guard, except GF/LF always eligible.

8. **N-way ranking** → not applicable here; all matches are 2-player.

## What's deferred

- **Phase 7 (drowning weights):** richer matchmaking that explicitly
  weighs drowning probability vs. ratings — Phase 5 uses the simpler
  rating-only generator from source.
- **Phase 9 (check-in lifecycle):** the 360/480/240 timer values are
  set, but the timer-expiry → forfeit handling lives in Phase 9.
- **Phase 13 (PXL config):** the `pxl` preset (OpenSkill + streaming +
  PXL-specific defaults) is registered then.
- **Phase 14 (Discord cmds):** `/ladder`, `/takeabreak`, `/queue`,
  `/eliminate` commands wire to LadderElimination methods.
- **Phase 11 (checkpointing):** persisting LadderElimination state to
  the DB. Phase 5 keeps everything in-memory.
- **Phase 15 (visualization):** lava-bar Graphviz / Discord image.
