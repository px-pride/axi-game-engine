# Phase 10: Checkpointing + undo system

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 10.

Phase 10 makes tournament state durable: every mutating operation
(call/complete/drop/dq/phase advance) auto-saves a checkpoint to DB,
and restart recovery rebuilds in-memory state from the latest
checkpoint. Also strengthens the existing undo stubs into a working
recursive cascade (undo_match, undo_drop_user, undo_dq_user,
undo_phase).

## Scope

- 2 new DB tables in `axi/handlers/database_handler.py`:
  - `tourney_checkpoints (tourney_id, checkpoint_ctr, status,
    player_state_str TEXT, match_checkpoints_str TEXT, timestamp)`
    — schema mirrors source `database_manager.py:101–110`.
  - `match_checkpoints (match_id, tourney_checkpoint_id,
    checkpoint_ctr, status, user_id_a, user_id_b, score_a, score_b,
    parent_k_a, parent_v_a, parent_k_b, parent_v_b, timestamp)` —
    mirrors source `:124–139`.
- New `axi/handlers/checkpoint_handler.py` for persistence ops:
  `save_checkpoint(tournament)`, `load_latest_checkpoint(tournament_id)`,
  `restore_tournament(tournament_id)`.
- `Tournament.save_checkpoint()` (currently a stub) becomes real:
  serializes player state + per-match snapshots, inserts rows, returns
  the new checkpoint_id.
- `MatchGraph.undo_match` strengthened to actually cascade through
  children (currently the impl exists but Phase 10 verifies it
  against source semantics: recursive child undo, removal from
  matches_by_pair, re-call base match).
- `MatchGraph.undo_drop_user`/`undo_dq_user`: source iterates
  dropped/dq match list and calls `undo_match` on each. Target
  currently has stubs returning `[]` — Phase 10 implements.
- `Tournament.undo_phase`: source rolls back the last phase
  advance. Target has stub — Phase 10 implements.
- Auto-checkpoint hooks: `MatchGraph.complete_match` and
  `Tournament.advance_phase` save a checkpoint after they finish.
- Tests cover serialization roundtrip + undo cascade + restart
  recovery from a saved checkpoint.

## Files

| File | Change |
|---|---|
| `axi/handlers/database_handler.py` | Add 2 `CREATE TABLE` statements. |
| `axi/handlers/checkpoint_handler.py` (NEW) | save_checkpoint, load_latest_checkpoint, restore_tournament + serialization helpers. |
| `axi/tournament.py` | Implement `save_checkpoint()`, `restore_from_checkpoint()`, `undo_phase()`. Call save_checkpoint from `advance_phase` and after mutations. |
| `axi/match_graph.py` | Verify/strengthen `undo_match`, implement `undo_drop_user` / `undo_dq_user`. Call save_checkpoint from `complete_match` (delegated to Tournament). |
| `axi/match_node.py` | Add `undo()` method (clears score, checkins, reports, status → ASLEEP). |
| `tests/test_checkpoint_undo.py` (NEW) | Serialization roundtrip, undo cascade, restart recovery, dropped-user undo. |

## Serialization format

Source uses TEXT columns with self-rolled string serialization.
Target uses **JSON via `json.dumps()`** for cleaner roundtrip.

### `player_state_str` schema

```json
{
  "players": [user_id, ...],
  "drop_dict": {user_id: [phase_id, ...]},
  "dq_dict": {user_id: [phase_id, ...]},
  "placements_dict": {user_id: rank},
  "status_by_player": {user_id: status_int},
  "ratings_by_player": {user_id: [threshold, rating_mu, rating_sigma]},
  "checkins_post_id": int_or_null
}
```

### `match_checkpoints_str` schema

JSON array of per-node snapshots; mirrors the `match_checkpoints`
row schema but consolidated into one TEXT column for fast restart:

```json
[
  {
    "node_id": str,
    "status": int,
    "user_id_a": int,
    "user_id_b": int,
    "score_a": int,
    "score_b": int,
    "label": str,
    "best_of": int,
    "parents": [[parent_node_id, flag], ...],
    "children": [[child_node_id, flag], ...]
  },
  ...
]
```

Why both `match_checkpoints` table AND `match_checkpoints_str`? Source
duplicates because the table lets you query individual match history
while the str blob lets you reconstruct in one read. We follow.

## Algorithm port

### `save_checkpoint(tournament) → checkpoint_id`

```python
def save_checkpoint(tournament):
    """Snapshot the tournament's current state to DB. Returns
    the new checkpoint_id (rowid of tourney_checkpoints row)."""
    graph = tournament.current_phase()
    player_state = _serialize_player_state(tournament, graph)
    match_snapshots = _serialize_match_snapshots(graph) if graph else []
    match_str = json.dumps(match_snapshots)
    checkpoint_id = db.add_entry("tourney_checkpoints", (
        tournament.tournament_id,
        tournament.checkpoint_ctr,
        int(tournament.completed()),
        json.dumps(player_state),
        match_str,
    ))
    tournament.checkpoint_ctr += 1
    tournament.checkpoint_id = checkpoint_id
    # Also write per-match rows for query-friendly history.
    if graph:
        for snap in match_snapshots:
            db.add_entry("match_checkpoints", (
                _hash_node_id(snap["node_id"]),
                checkpoint_id,
                tournament.checkpoint_ctr - 1,
                snap["status"],
                snap.get("user_id_a"),
                snap.get("user_id_b"),
                snap.get("score_a"),
                snap.get("score_b"),
                None, None, None, None,  # parent_k/v columns (legacy
                                         # from source; unused — we
                                         # carry parents inside the
                                         # JSON blob).
            ))
    return checkpoint_id
```

### `restore_tournament(tournament_id, axi_users_lookup)`

```python
def restore_tournament(tournament_id, user_lookup):
    """Reconstruct a Tournament from its latest checkpoint row.

    `user_lookup` is a callable user_id → AxiUser (provided by the
    caller — usually `lambda uid: user_handler.users_by_id.get(uid)`).
    Returns the reconstructed Tournament instance.
    """
    row = _load_latest(tournament_id)
    if row is None:
        return None
    player_state = json.loads(row["player_state_str"])
    match_snaps = json.loads(row["match_checkpoints_str"])
    tournament = Tournament(
        title="<restored>",
        scope=None,
        series_id=None,
    )
    tournament.tournament_id = tournament_id
    tournament.checkpoint_ctr = row["checkpoint_ctr"] + 1
    tournament.checkpoint_id = row["rowid"]
    # Restore players, drop/dq dicts, placements_dict, etc.
    tournament.players = [user_lookup(uid) for uid in player_state["players"]
                          if user_lookup(uid) is not None]
    tournament.drop_dict = defaultdict(list, {
        user_lookup(int(uid)): phases
        for uid, phases in player_state["drop_dict"].items()
        if user_lookup(int(uid)) is not None
    })
    # (Similar for dq_dict, placements_dict, status_by_player, etc.)
    # Phase reconstruction: phases are not directly restored — Phase 10
    # is for state recovery only. Re-applying the preset is the
    # caller's job. Phase 14 admin commands handle "restart sequence".
    return tournament
```

### `MatchGraph.undo_match(node)` (verify existing)

Source semantics (`match_graph.py:244–268`):
1. If `node.players` is empty: nothing to do.
2. Recurse: undo each child first.
3. Clear `current_match_by_player[p]` and `placements_dict[p]` for
   `p in node.players`.
4. Remove from `active_matches` / `called_matches`.
5. Call `node.undo()` — resets status to ASLEEP, clears
   score/checkins/reports.
6. If `len(node.players) < 2` after parent re-projection, remove
   from `matches_by_pair[a][b]` / `[b][a]`.
7. If `base and len(node.ancestors()) == 0`: re-call the match.

Target's current `MatchGraph.undo_match` (in axi/match_graph.py:335–370)
already does most of this. Phase 10 verifies against source and adds
the auto-checkpoint hook at the end.

### `MatchGraph.undo_drop_user(user)` / `undo_dq_user(user)`

Source iterates `tournament.drop_dict[user]` (or `dq_dict`), removes
each entry, and calls `undo_match` on each affected match. Target has
stubs returning `[]`. Phase 10 implements:

```python
def undo_drop_user(self, user):
    effects = []
    drop_phases = self.tournament.drop_dict.get(user, [])
    if not drop_phases:
        return effects
    # Find all matches affected by this drop and undo them.
    for node in list(self.nodes_by_id.values()):
        if user in node.players and not node.is_bye():
            if node.label and node.completed():
                effects += self.undo_match(node)
    self.tournament.drop_dict.pop(user, None)
    return effects
```

Source iterates the drop_dict's match list directly; target's
`drop_dict` only stores `phase_id`s, so we scan
`nodes_by_id.values()`. Phase 10 may add an explicit per-user
`affected_matches` field later if performance matters.

### `Tournament.undo_phase()`

Source rolls back the last phase advance:
- Pop the last phase from `phases`.
- Decrement `phase_id`.
- (Don't actually undo any matches — phase undo is at the structural
  level.)

Target's current `Tournament.undo_phase` already does this. Phase 10
just adds the checkpoint save.

### Auto-checkpoint hooks

After every state mutation:
- `complete_match` — graph calls `tournament.save_checkpoint()`.
- `advance_phase` — Tournament calls `save_checkpoint()` after
  appending the new phase.
- `drop_user` / `dq_user` — Tournament saves after appending.

Performance: each checkpoint is ~1 INSERT INTO + 1 per-match-snapshot
INSERT. For a 16-player single elimination ~30 matches → ~30 inserts
per checkpoint. Acceptable for tournament cadence (~1/min). If too
slow later, batch via executemany.

## Test plan

`tests/test_checkpoint_undo.py`:

1. **`TestSchemaTables`** — tourney_checkpoints and match_checkpoints
   tables exist after database_handler init.

2. **`TestSerializePlayerState`** — given a Tournament with players +
   drop_dict + status_by_player + placements_dict, the JSON roundtrip
   reconstructs identical content.

3. **`TestSerializeMatchSnapshots`** — given a MatchGraph with a few
   completed and incomplete nodes, the per-node snapshot includes
   status, score, parents/children, players' user_ids.

4. **`TestSaveCheckpoint`** — `save_checkpoint(tournament)` returns a
   rowid; the row exists at that id; `tournament.checkpoint_ctr`
   increments.

5. **`TestRestoreTournament`** — save a checkpoint, then call
   `restore_tournament(tournament_id, lookup_fn)` with a fresh state;
   the returned tournament has matching players / status / drop_dict.

6. **`TestUndoMatch`** — complete a match, call undo_match(node);
   verify node status reverts to ASLEEP, players are released, the
   match is removed from `past_matches`.

7. **`TestUndoMatchCascade`** — complete a parent match, complete its
   child via the propagation, undo the parent; verify the child is
   also undone.

8. **`TestUndoDropUser`** — drop a user mid-tournament, complete some
   matches affected, undo_drop_user; verify drop_dict no longer
   contains the user and the affected matches are undone.

9. **`TestUndoDqUser`** — same as above but for dq_dict.

10. **`TestUndoPhase`** — advance to phase 2 of a multi-phase preset,
    undo_phase; verify phase_id decrements and the last phase pops.

11. **`TestAutoCheckpointHooks`** — completing a match auto-saves a
    checkpoint; advancing a phase auto-saves; verify
    `tournament.checkpoint_ctr` increments at each event.

Full suite must still pass.

## Major decisions

### A. JSON in TEXT columns (vs separate normalized tables)

Source uses TEXT with self-rolled string format. Target uses JSON
for cleaner Python roundtrip. Both fit in a TEXT column.

### B. Player + match state in 2 places (column + blob)

Source duplicates: `match_checkpoints` table has per-match rows AND
the blob in `tourney_checkpoints.match_checkpoints_str`. We follow:
table for ad-hoc queries, blob for fast bulk restore.

### C. Phase reconstruction NOT auto-restored

Phase 10 restores player/match state, NOT the phase orchestration
(preset, phase_fns). Caller (Phase 14 admin `/restart` command) is
responsible for re-applying the preset and walking advance_phase up
to the saved phase_id.

### D. User lookup via callable

`restore_tournament(tournament_id, user_lookup)` — caller supplies
the int → AxiUser resolution. Keeps the handler pure (no
user_handler import dependency).

### E. Auto-checkpoint frequency

After every `complete_match`, `advance_phase`, `drop_user`,
`dq_user`. Tournament-level mutations only — match status
transitions (ASLEEP → CALLED → ACTIVE) don't checkpoint per
transition (would be too noisy).

### F. Per-node parent/child stored as JSON inside blob

The `parent_k_a/v_a/k_b/v_b` legacy columns in source's
match_checkpoints schema are vestigial — Phase 10 leaves them
nullable for schema compat and stores full parents/children inside
the JSON blob.

## What's deferred

- **Phase 11 (DB-backed scheduler):** persists scheduled callbacks
  across restarts; pairs naturally with Phase 10's state recovery
  via a `restart_recovery()` orchestrator.
- **Phase 14 admin commands** wraps `/undo`, `/undomatch`,
  `/undodrop`, `/undodq`, `/undophase`, and `/restart` around the
  handler API.
- **Conflict resolution on out-of-band DB writes** — Phase 10 assumes
  axi.db has a single writer. If multiple processes write
  concurrently, follow-up work needed.
- **Compression** — checkpoint blobs aren't compressed. For large
  brackets (~64 players) the blob can be ~50KB. Acceptable for
  sqlite; defer optimization.

## Resolved questions

1. **What if a user_id in player_state can't be resolved by the
   lookup callable?** Skip that player from the reconstructed list.
   The caller can detect missing players and prompt admin to
   re-add.

2. **Are checkpoints append-only?** Yes. Each save inserts a new row
   with `checkpoint_ctr += 1`. Old checkpoints persist; restore
   uses the row with the highest `checkpoint_ctr` for that
   `tourney_id`.

3. **How is the latest checkpoint queried?** `SELECT * FROM
   tourney_checkpoints WHERE tourney_id=? ORDER BY checkpoint_ctr
   DESC LIMIT 1`.

4. **`match_id` in `match_checkpoints` table — what is it?** A hash
   of `node_id` (str) → int. Source uses `id(match)` (Python object
   id); we hash `node_id` for stability across restarts.

5. **`status` field semantics?** 0=incomplete, 1=completed.
   `tournament.completed()` is the source.

6. **What if a node was added mid-tournament after a previous
   checkpoint?** The next save_checkpoint captures it. Restore
   reads all nodes from the latest blob — no merge needed.
