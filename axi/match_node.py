import uuid
from dataclasses import dataclass, field

from axi.util import (
    MATCH_STATUS_ASLEEP,
    MATCH_STATUS_CALLED,
    MATCH_STATUS_ACTIVE,
    MATCH_STATUS_COMPLETED,
)


@dataclass(eq=False)
class MatchNode:
    """A bracket slot. Pure data — transitions live on MatchGraph.

    Holds NO reference to an underlying Match object from match_handler;
    the mapping lives in TournamentState.nodes_to_matches keyed by node_id.

    Graph edges use node_id strings (not object references) so the structure
    is serializable and immune to garbage-collection identity reuse.
    """

    tournament_id: str
    graph_id: str
    players: list = field(default_factory=list)
    label: str = ""
    game: str = "rps"
    mode: str = "versus"
    best_of: int = 3
    loser_gets: int = None
    checkin_timer: int = 360

    score: list = field(default_factory=lambda: [0, 0])
    checkins: set = field(default_factory=set)
    reports: dict = field(default_factory=dict)
    status: int = MATCH_STATUS_ASLEEP
    streamed: bool = False
    round_number: int = 0
    first_ban: int = 0
    checkin_deadline: float = None

    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parents: dict = field(default_factory=dict)
    children: dict = field(default_factory=dict)

    def asleep(self):
        return self.status == MATCH_STATUS_ASLEEP

    def awake(self):
        return self.status in (MATCH_STATUS_CALLED, MATCH_STATUS_ACTIVE)

    def completed(self):
        return self.status == MATCH_STATUS_COMPLETED

    def first_to(self):
        return (self.best_of + 1) // 2

    def winner(self):
        if not self.completed() or len(self.players) < 2:
            return None
        return self.players[0] if self.score[0] > self.score[1] else self.players[1]

    def loser(self):
        if not self.completed() or len(self.players) < 2:
            return None
        return self.players[1] if self.score[0] > self.score[1] else self.players[0]

    def is_sweep(self):
        return self.completed() and min(self.score) == 0

    def is_bye(self):
        return any(getattr(p, "is_bye", lambda: False)() for p in self.players)

    def has_player(self, user):
        return user in self.players

    def opponent(self, user):
        if len(self.players) != 2 or user not in self.players:
            return None
        return self.players[1] if user == self.players[0] else self.players[0]

    def rank(self):
        """Placement tier for the loser. Subclasses/format code may override
        via loser_gets propagation through children."""
        return self.loser_gets

    def get_score(self):
        return f"{self.score[0]}-{self.score[1]}"
