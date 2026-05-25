from collections import defaultdict


DEFAULT_SCOPE = "DEFAULT_SCOPE"


class TournamentState:
    """Module-level service object for tournament-related global state.

    Mirrors the MatchState / LadderState pattern in handlers.

    Phase 12 added scope routing: a tournament command in a server with
    multiple active tournaments uses the caller's scope (a normalized
    channel name) to disambiguate which tournament it targets.
    """

    def __init__(self):
        # (guild_id, scope) -> tournament_id
        self.scope_to_tournament = {}
        # tournament_id -> Tournament instance
        self.tournaments = {}
        # node_id -> id(Match)  (from match_handler.state.matches_by_id)
        self.nodes_to_matches = {}
        # id(Match) -> node_id
        self.matches_to_nodes = {}
        # Phase 12: scope state for per-(caller, guild) tournament targeting.
        # guild_id -> default scope name
        self.default_scopes = defaultdict(lambda: DEFAULT_SCOPE)
        # (caller_id, guild_id) -> scope name (per-user override)
        self.scopes = {}
        # guild_id -> [scope_name, ...]  (all known scopes for the guild)
        self.scopes_by_guild = defaultdict(list)

    def get_tournament(self, tournament_id):
        return self.tournaments.get(tournament_id)

    def register_tournament(self, tournament):
        self.tournaments[tournament.tournament_id] = tournament
        if tournament.scope is not None:
            self.scope_to_tournament[tournament.scope] = tournament.tournament_id

    def get_tournament_by_scope(self, scope):
        tid = self.scope_to_tournament.get(scope)
        return self.tournaments.get(tid) if tid else None

    def map_node_to_match(self, node_id, match_id):
        self.nodes_to_matches[node_id] = match_id
        self.matches_to_nodes[match_id] = node_id

    def unmap_node(self, node_id):
        match_id = self.nodes_to_matches.pop(node_id, None)
        if match_id is not None:
            self.matches_to_nodes.pop(match_id, None)

    def get_node_for_match(self, match_id):
        return self.matches_to_nodes.get(match_id)

    def get_match_for_node(self, node_id):
        return self.nodes_to_matches.get(node_id)

    def reset(self):
        """Test-only helper — clears all state."""
        self.scope_to_tournament.clear()
        self.tournaments.clear()
        self.nodes_to_matches.clear()
        self.matches_to_nodes.clear()
        self.default_scopes.clear()
        self.scopes.clear()
        self.scopes_by_guild.clear()

    # ------------------------------------------------------------------
    # Phase 12: scope system
    # ------------------------------------------------------------------

    @staticmethod
    def channel_to_scope(channel):
        """Normalize a Discord channel (or Thread) to a scope string.

        Uppercase the channel name; strip trailing '-BRACKET'. Threads
        map to their parent channel.
        """
        if channel is None:
            return DEFAULT_SCOPE
        # Threads: use parent channel name (matches source semantics).
        parent = getattr(channel, "parent", None)
        name = str(parent) if parent is not None else str(channel)
        name = name.upper()
        if name.endswith("-BRACKET"):
            name = name[: -len("-BRACKET")]
        return name

    def get_scope(self, caller, guild, channel):
        """Resolve the active scope for a (caller, guild, channel) triple.

        Priority order:
          1. Per-caller override (self.scopes[(caller_id, guild_id)]).
          2. Channel-derived scope (channel_to_scope).
          3. Guild default (self.default_scopes[guild_id]) — used if
             channel is None.

        Always registers the resolved scope in scopes_by_guild[guild_id].
        """
        caller_id = self._extract_id(caller)
        guild_id = self._extract_id(guild)
        key = (caller_id, guild_id)
        if key in self.scopes:
            scope = self.scopes[key]
        else:
            scope = self.channel_to_scope(channel)
            if scope == DEFAULT_SCOPE:
                scope = self.default_scopes[guild_id]
        if scope not in self.scopes_by_guild[guild_id]:
            self.scopes_by_guild[guild_id].append(scope)
        return scope

    def set_scope(self, caller, guild, channel, scope, admin=False):
        """Bind a per-(caller, guild) scope.

        `admin=True` (typically from a slash command decorated with
        @has_permissions(ban_members=True)) also sets the guild-wide
        default. `channel` is accepted for source-compat (used by the
        admin's auto-detect branch in source); the target keeps it as
        an unused arg for now.
        """
        caller_id = self._extract_id(caller)
        guild_id = self._extract_id(guild)
        scope = scope.upper() if isinstance(scope, str) else scope
        self.scopes[(caller_id, guild_id)] = scope
        if scope not in self.scopes_by_guild[guild_id]:
            self.scopes_by_guild[guild_id].append(scope)
        if admin:
            self.set_default_scope(guild, scope)

    def set_default_scope(self, guild, scope):
        """Set the guild-wide default scope."""
        guild_id = self._extract_id(guild)
        scope = scope.upper() if isinstance(scope, str) else scope
        self.default_scopes[guild_id] = scope
        if scope not in self.scopes_by_guild[guild_id]:
            self.scopes_by_guild[guild_id].append(scope)

    def get_all_scopes(self, caller, guild, channel=None):
        """Return all known scopes for the guild."""
        guild_id = self._extract_id(guild)
        return list(self.scopes_by_guild[guild_id])

    @staticmethod
    def _extract_id(obj):
        """Extract an id from a Discord-like object (.id) or pass through int."""
        if obj is None:
            return None
        if isinstance(obj, (int, str)):
            return obj
        return getattr(obj, "id", obj)


state = TournamentState()
