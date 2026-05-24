"""Checkpoint + restore handler (Phase 10).

Pure-layer persistence ops for tournament state. Serialization is
JSON-in-TEXT inside two DB tables (tourney_checkpoints + per-match
match_checkpoints).

Usage from Tournament.save_checkpoint():
    checkpoint_handler.save_checkpoint(self)

Usage from restart recovery:
    tournament = checkpoint_handler.restore_tournament(
        tournament_id, user_lookup)
"""

import hashlib
import json
from collections import defaultdict

import axi.handlers.database_handler as db
from axi.util import MATCH_STATUS_ASLEEP


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_player_state(tournament, graph):
    """Snapshot tournament + current phase player state."""
    state = {
        "players": [_user_id(p) for p in tournament.players],
        "drop_dict": {
            str(_user_id(u)): list(phases)
            for u, phases in tournament.drop_dict.items()
        },
        "dq_dict": {
            str(_user_id(u)): list(phases)
            for u, phases in tournament.dq_dict.items()
        },
        "checkins_post_id": getattr(tournament, "checkins_post_id", None),
        "started": getattr(tournament, "started", False),
        "phase_id": getattr(tournament, "phase_id", -1),
    }
    if graph is not None:
        state["placements_dict"] = {
            str(_user_id(p)): rank
            for p, rank in graph.placements_dict.items()
        }
        state["status_by_player"] = {
            str(_user_id(p)): s
            for p, s in getattr(graph, "status_by_player", {}).items()
        }
        state["ratings_by_player"] = {
            str(_user_id(p)): _serialize_rating(r)
            for p, r in getattr(graph, "ratings_by_player", {}).items()
        }
    return state


def _serialize_rating(rating_tuple):
    """Compress a (threshold, RatingObj) tuple into JSON-safe form."""
    if rating_tuple is None:
        return None
    threshold = rating_tuple[0] if isinstance(rating_tuple, (tuple, list)) else None
    rating_obj = rating_tuple[1] if isinstance(rating_tuple, (tuple, list)) and len(rating_tuple) > 1 else None
    mu = getattr(rating_obj, "mu", None)
    sigma = getattr(rating_obj, "sigma", None)
    if isinstance(mu, (int, float)) and isinstance(sigma, (int, float)):
        return [threshold, float(mu), float(sigma)]
    if isinstance(threshold, (int, float)):
        return [threshold, None, None]
    return None


def _serialize_match_snapshots(graph):
    """Per-node snapshots for the current graph."""
    snaps = []
    for node in graph.nodes_by_id.values():
        snap = {
            "node_id": node.node_id,
            "status": int(getattr(node, "status", MATCH_STATUS_ASLEEP)),
            "label": getattr(node, "label", ""),
            "best_of": getattr(node, "best_of", 3),
            "score": list(getattr(node, "score", [0, 0])),
            "players": [_user_id(p) for p in getattr(node, "players", [])],
            "parents": [
                [pid, flag] for pid, flag in getattr(node, "parents", {}).items()
            ],
            "children": [
                [cid, flag] for cid, flag in getattr(node, "children", {}).items()
            ],
            "pool_id": getattr(node, "pool_id", None),
            "loser_gets": getattr(node, "loser_gets", None),
        }
        snaps.append(snap)
    return snaps


def _user_id(user):
    """Resolve an AxiUser / FakeUser → int user_id. None-safe."""
    if user is None:
        return None
    uid_obj = getattr(user, "uid", None)
    if uid_obj is not None:
        return getattr(uid_obj, "id", None)
    return getattr(user, "id", None)


def _hash_node_id(node_id_str):
    """Stable int hash of a node_id string for match_checkpoints.match_id."""
    if node_id_str is None:
        return 0
    h = hashlib.md5(node_id_str.encode("utf-8")).hexdigest()
    # First 12 hex digits as int — fits comfortably in sqlite INT.
    return int(h[:12], 16)


# ---------------------------------------------------------------------------
# Save + load
# ---------------------------------------------------------------------------


def save_checkpoint(tournament):
    """Snapshot the tournament's current state to DB.

    Returns the new tourney_checkpoints rowid (checkpoint_id).
    Appends one row to tourney_checkpoints plus N rows to
    match_checkpoints (one per active MatchNode in the current phase).
    """
    graph = None
    if hasattr(tournament, "current_phase"):
        graph = tournament.current_phase()

    player_state = _serialize_player_state(tournament, graph)
    match_snapshots = _serialize_match_snapshots(graph) if graph else []
    match_str = json.dumps(match_snapshots)

    completed_flag = 0
    try:
        completed_flag = int(bool(tournament.completed()))
    except Exception:
        completed_flag = 0

    checkpoint_ctr = getattr(tournament, "checkpoint_ctr", 0)

    checkpoint_id = db.add_entry("tourney_checkpoints", (
        tournament.tournament_id,
        checkpoint_ctr,
        completed_flag,
        json.dumps(player_state),
        match_str,
    ))
    tournament.checkpoint_ctr = checkpoint_ctr + 1
    tournament.checkpoint_id = checkpoint_id

    # Per-match rows for query-friendly history.
    for snap in match_snapshots:
        players = snap.get("players", [])
        score = snap.get("score", [0, 0])
        db.add_entry("match_checkpoints", (
            _hash_node_id(snap["node_id"]),
            checkpoint_id,
            checkpoint_ctr,
            snap["status"],
            players[0] if len(players) > 0 else None,
            players[1] if len(players) > 1 else None,
            score[0] if len(score) > 0 else 0,
            score[1] if len(score) > 1 else 0,
            None, None, None, None,  # legacy parent_k/v columns
        ))
    return checkpoint_id


def load_latest_checkpoint(tournament_id):
    """Return the latest tourney_checkpoints row for this tournament_id
    as a dict, or None if none exists.

    Row keys (mirror sqlite column order; rowid prepended):
      rowid, tourney_id, checkpoint_ctr, status, player_state_str,
      match_checkpoints_str, timestamp.
    """
    sql = (
        "SELECT rowid, tourney_id, checkpoint_ctr, status, "
        "player_state_str, match_checkpoints_str, timestamp "
        "FROM tourney_checkpoints WHERE tourney_id=? "
        "ORDER BY checkpoint_ctr DESC LIMIT 1"
    )
    db.cursor.execute(sql, (tournament_id,))
    row = db.cursor.fetchone()
    if not row:
        return None
    return {
        "rowid": row[0],
        "tourney_id": row[1],
        "checkpoint_ctr": row[2],
        "status": row[3],
        "player_state_str": row[4],
        "match_checkpoints_str": row[5],
        "timestamp": row[6],
    }


def load_match_checkpoints(checkpoint_id):
    """Return all per-match rows for a given tourney_checkpoint_id."""
    return db.load_entries_where(
        "match_checkpoints", "tourney_checkpoint_id", checkpoint_id)


def restore_tournament(tournament_id, user_lookup):
    """Reconstruct a Tournament from its latest checkpoint row.

    `user_lookup(user_id) → AxiUser | None` is a callable supplied
    by the caller (typically wrapping user_handler.users_by_id.get).

    Returns the reconstructed Tournament instance, or None if no
    checkpoint exists for this tournament_id.

    Note: phase orchestration (preset, phase_fns) is NOT restored —
    Phase 14 admin `/restart` re-applies the preset and walks
    advance_phase to the saved phase_id.
    """
    from axi.tournament import Tournament

    row = load_latest_checkpoint(tournament_id)
    if row is None:
        return None
    player_state = json.loads(row["player_state_str"])

    tournament = Tournament(
        title="<restored>",
        scope=None,
        seed=None,
    )
    # Override the auto-generated tournament_id with the saved one.
    tournament.tournament_id = tournament_id
    tournament.checkpoint_ctr = row["checkpoint_ctr"] + 1
    tournament.checkpoint_id = row["rowid"]
    tournament.checkins_post_id = player_state.get("checkins_post_id")
    tournament.started = bool(player_state.get("started", False))
    tournament.phase_id = player_state.get("phase_id", -1)

    # Players (drop missing ones).
    tournament.players = []
    for uid in player_state.get("players", []):
        u = user_lookup(uid) if uid is not None else None
        if u is not None:
            tournament.players.append(u)

    # drop_dict / dq_dict.
    tournament.drop_dict = defaultdict(list)
    for uid_str, phases in player_state.get("drop_dict", {}).items():
        u = user_lookup(int(uid_str))
        if u is not None:
            tournament.drop_dict[u] = list(phases)
    tournament.dq_dict = defaultdict(list)
    for uid_str, phases in player_state.get("dq_dict", {}).items():
        u = user_lookup(int(uid_str))
        if u is not None:
            tournament.dq_dict[u] = list(phases)

    return tournament
