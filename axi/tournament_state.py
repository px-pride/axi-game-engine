class TournamentState:
    """Module-level service object for tournament-related global state.

    Mirrors the MatchState / LadderState pattern in handlers.
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


state = TournamentState()
