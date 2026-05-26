"""Tournament command handler (Phase 14).

Pure layer — given a scope (channel name), look up the active
Tournament via TournamentState and call its API. Each operation
returns a list of effects + a structured result the slash command
formats into a user-facing response.

Mirrors the `ladder_handler` / `checkin_handler` shape.
"""

from axi.tournament import Tournament
from axi.tournament_state import state as tournament_state
from axi.effects import (
    AnnouncePhaseStart,
    AnnouncePhaseEnd,
    AnnounceTourneyStart,
    AnnounceTourneyEnd,
    SendToChannel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tournament(scope):
    """Look up the Tournament bound to a scope. Returns None if no
    tournament for that scope."""
    return tournament_state.get_tournament_by_scope(scope)


def _mention(user):
    """Return a mention string for a user. Falls back to str(user)."""
    if user is None:
        return ""
    uid = getattr(user, "uid", None)
    if uid is not None:
        return f"<@{uid.id if hasattr(uid, 'id') else uid}>"
    if hasattr(user, "id"):
        return f"<@{user.id}>"
    return str(user)


def _user_id(user):
    """Extract an int id from a user-like object."""
    if user is None:
        return None
    if isinstance(user, int):
        return user
    uid = getattr(user, "uid", None)
    if uid is not None and hasattr(uid, "id"):
        return uid.id
    return getattr(user, "id", None)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def create_tournament(scope, guild_id, game, name=None, season=None,
                      pinned_channel=None, seed=None):
    """Construct a Tournament + register it with TournamentState.

    Returns (tournament, effects). Caller decides how to present.
    """
    title = name or scope
    tournament = Tournament(
        title=title,
        scope=scope,
        seed=seed,
    )
    tournament.game = game
    tournament.season = season
    tournament.pinned_channel = pinned_channel or scope
    tournament_state.register_tournament(tournament)
    effects = [SendToChannel(
        guild_id=guild_id,
        channel_name=pinned_channel or scope.lower(),
        messages=[(f"Created tournament `{title}` (game: {game}).", None)],
    )]
    return tournament, effects


def destroy_tournament(scope, guild_id, channel_name=None):
    """Remove a tournament binding from TournamentState. Doesn't
    delete the Tournament instance (state.tournaments still holds it)
    — just unbinds it from the scope so future scope lookups miss."""
    t = _get_tournament(scope)
    if t is None:
        return None, []
    # Remove only the scope binding (the tournament itself stays in
    # state.tournaments by tournament_id for reference).
    tournament_state.scope_to_tournament.pop(scope, None)
    effects = [SendToChannel(
        guild_id=guild_id,
        channel_name=channel_name or scope.lower(),
        messages=[(f"Tournament `{t.title}` destroyed.", None)],
    )]
    return t, effects


def apply_preset(scope, preset_name):
    """Apply a registered preset to the scope's tournament."""
    t = _get_tournament(scope)
    if t is None:
        return False, []
    ok = t.preset(preset_name)
    return ok, []


def begin(scope, guild_id, channel_name=None):
    """Start the scope's tournament. Returns (effects)."""
    t = _get_tournament(scope)
    if t is None:
        return []
    effects = t.begin()
    if t.started:
        effects = [AnnounceTourneyStart(
            guild_id=guild_id,
            channel_name=channel_name or scope.lower(),
            title=t.title,
            format=t.format or "",
        )] + list(effects)
        # First phase-start announcement.
        phase = t.current_phase()
        if phase is not None:
            mentions = [_mention(p) for p in t.players if not t.is_dropped(p)
                        and not t.is_dq(p)]
            effects.append(AnnouncePhaseStart(
                guild_id=guild_id,
                channel_name=channel_name or scope.lower(),
                phase_name=type(phase).__name__,
                player_mentions=mentions,
            ))
    return effects


def advance_phase(scope, guild_id, channel_name=None):
    """Advance the tournament to its next phase."""
    t = _get_tournament(scope)
    if t is None:
        return []
    effects = list(t.advance_phase())
    phase = t.current_phase()
    if phase is not None:
        mentions = [_mention(p) for p in t.players if not t.is_dropped(p)
                    and not t.is_dq(p)]
        effects.append(AnnouncePhaseStart(
            guild_id=guild_id,
            channel_name=channel_name or scope.lower(),
            phase_name=type(phase).__name__,
            player_mentions=mentions,
        ))
    if t.completed():
        winner = t.winner()
        effects.append(AnnounceTourneyEnd(
            guild_id=guild_id,
            channel_name=channel_name or scope.lower(),
            title=t.title,
            winner_mention=_mention(winner) if winner else "(no winner)",
        ))
    return effects


def undo_phase(scope):
    """Reverse the most recent phase advance."""
    t = _get_tournament(scope)
    if t is None:
        return []
    return list(t.undo_phase())


# ---------------------------------------------------------------------------
# Player management
# ---------------------------------------------------------------------------


def add_players(scope, users):
    """Add a list of user-like objects to the tournament's roster."""
    t = _get_tournament(scope)
    if t is None:
        return 0, []
    before = len(t.players)
    t.add_players(users)
    return len(t.players) - before, []


def remove_players(scope, users):
    """Remove users from the tournament (only valid before begin())."""
    t = _get_tournament(scope)
    if t is None:
        return 0, []
    before = len(t.players)
    t.remove_players(users)
    return before - len(t.players), []


def drop_user(scope, user):
    t = _get_tournament(scope)
    if t is None:
        return []
    return list(t.drop_user(user))


def dq_user(scope, user):
    t = _get_tournament(scope)
    if t is None:
        return []
    return list(t.dq_user(user))


def undo_drop_user(scope, user):
    t = _get_tournament(scope)
    if t is None:
        return []
    return list(t.undo_drop_user(user))


def undo_dq_user(scope, user):
    t = _get_tournament(scope)
    if t is None:
        return []
    return list(t.undo_dq_user(user))


# ---------------------------------------------------------------------------
# Score / match reporting
# ---------------------------------------------------------------------------


def report_score(scope, reporter, p0, p1, score):
    """Pass through to Tournament.report_score. Returns (accepted, effects)."""
    t = _get_tournament(scope)
    if t is None:
        return False, []
    accepted, effects = t.report_score(reporter, p0, p1, score)
    return accepted, list(effects)


def undo_match(scope, p0, p1):
    t = _get_tournament(scope)
    if t is None:
        return []
    return list(t.undo_match(p0, p1))


# ---------------------------------------------------------------------------
# Status / placements / matches
# ---------------------------------------------------------------------------


def get_placements(scope):
    """Return the placement list of the current phase: [(rank, user), ...]
    Empty list if no current phase."""
    t = _get_tournament(scope)
    if t is None:
        return []
    phase = t.current_phase()
    if phase is None or not hasattr(phase, "get_placements"):
        return []
    return list(phase.get_placements())


def get_matches_for_player(scope, user):
    t = _get_tournament(scope)
    if t is None:
        return []
    phase = t.current_phase()
    if phase is None:
        return []
    matches = []
    for nodes in phase.matches_by_pair.get(user, {}).values():
        matches.extend(nodes)
    return matches


def get_matches_for_round(scope, round_n):
    """Return all matches at round R in the current phase."""
    t = _get_tournament(scope)
    if t is None:
        return []
    phase = t.current_phase()
    if phase is None:
        return []
    return [n for n in phase.nodes_by_id.values()
            if getattr(n, "round", None) == round_n]


def get_current_matches(scope):
    """Active + called + stream matches in current phase."""
    t = _get_tournament(scope)
    if t is None:
        return [], [], None
    phase = t.current_phase()
    if phase is None:
        return [], [], None
    active = [n for n in phase.nodes_by_id.values()
              if getattr(n, "status", 0) == 2]   # MATCH_STATUS_ACTIVE
    called = [n for n in phase.nodes_by_id.values()
              if getattr(n, "status", 0) == 1]   # MATCH_STATUS_CALLED
    stream = None
    for n in active + called:
        if getattr(n, "streamed", False):
            stream = n
            break
    return active, called, stream


def get_format(scope):
    t = _get_tournament(scope)
    if t is None:
        return None
    return t.format or ""


def get_pool_scores(scope):
    """Return per-pool score lists if the current phase is RoundRobin."""
    t = _get_tournament(scope)
    if t is None:
        return None
    phase = t.current_phase()
    if phase is None or not hasattr(phase, "get_single_pool_scores"):
        return None
    return [phase.get_single_pool_scores(i)
            for i in range(getattr(phase, "num_pools", 0))]


# ---------------------------------------------------------------------------
# Misc admin
# ---------------------------------------------------------------------------


def set_seed(scope, seed):
    """Reseed the active tournament's RNG. Used for deterministic tests
    and tiebreak coin flips."""
    import random
    t = _get_tournament(scope)
    if t is None:
        return False
    t.rng = random.Random(seed)
    return True


def set_series_id(scope, series_id):
    """Bind a series_id to the active tournament (admin override)."""
    t = _get_tournament(scope)
    if t is None:
        return False
    t.series_id = series_id
    return True
