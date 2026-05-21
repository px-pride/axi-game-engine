import time
import uuid
from abc import ABC, abstractmethod

from axi.effects import (
    LaunchTournamentMatch,
    CallMatchForStream,
    ArchiveTournamentMatch,
)
from axi.match_node import MatchNode
from axi.util import (
    MATCH_STATUS_ASLEEP,
    MATCH_STATUS_CALLED,
    MATCH_STATUS_ACTIVE,
    MATCH_STATUS_COMPLETED,
)


class MatchGraph(ABC):
    """Abstract base for tournament bracket formats.

    Subclasses implement generate_bracket() to build their format-specific
    DAG of MatchNodes. Lifecycle transitions (call/complete/report/undo)
    live here so MatchNode stays pure data.
    """

    def __init__(self, tournament, players, stream=False):
        self.tournament = tournament
        self.tournament_id = tournament.tournament_id
        self.graph_id = uuid.uuid4().hex
        self.players = list(players)
        self.stream = stream

        self.nodes_by_id = {}
        self.seed_by_player = {}
        self.matches_by_round = {}
        self.matches_by_pair = {}
        self.matches_by_player = {}
        self.current_match_by_player = {}
        self.placements_dict = {}
        self.active_matches = []
        self.called_matches = []
        self.non_matches = {}
        self.stream_history = []
        self.stream_planned = []
        self.stream_candidates = []
        self.stream_match = None
        self.victory_node = None

    @abstractmethod
    def generate_bracket(self):
        """Return the initial set of MatchNodes ready to be called.

        Subclasses build the full bracket DAG here (using add_node /
        link_parent) and return the round-1 nodes.
        """

    def begin(self):
        """Build bracket and call initial matches. Returns effect list."""
        self.create_data_structures()
        initial = self.generate_bracket()
        effects = []
        stream_candidates = []
        if self.stream:
            self.schedule_stream()
        for n in initial:
            target = stream_candidates if n.streamed else effects
            target.extend(self.call_match(n))
        if not self.stream_match and stream_candidates:
            effects += self.call_match_for_stream(stream_candidates)
        else:
            effects += stream_candidates
        return effects

    def create_data_structures(self):
        self.seed_by_player = {p: i for i, p in enumerate(self.players)}
        self.matches_by_round = {}
        self.matches_by_pair = {p: {q: [] for q in self.players} for p in self.players}
        self.matches_by_player = {p: [] for p in self.players}
        self.current_match_by_player = {p: None for p in self.players}
        self.placements_dict = {p: -1 for p in self.players}
        self.active_matches = []
        self.called_matches = []
        self.non_matches = {}
        self.stream_history = []
        self.stream_planned = []
        self.stream_candidates = []
        self.stream_match = None
        self.victory_node = self.add_node(label="VICTORY")

    def add_node(self, **kwargs):
        kwargs.setdefault("tournament_id", self.tournament_id)
        kwargs.setdefault("graph_id", self.graph_id)
        node = MatchNode(**kwargs)
        if "first_ban" not in kwargs:
            node.first_ban = self.tournament.rng.randrange(2)
        self.nodes_by_id[node.node_id] = node
        return node

    def link_parent(self, child, parent, flag):
        """Link `parent` -> `child` with W/L flag.

        flag == "W" means child receives the parent's winner.
        flag == "L" means child receives the parent's loser.
        """
        if flag not in ("W", "L"):
            raise ValueError(f"flag must be 'W' or 'L', got {flag!r}")
        child.parents[parent.node_id] = flag
        parent.children[child.node_id] = flag

    def ancestors(self, node, include_completed=False):
        """Return recursive set of ancestor MatchNodes."""
        result = set()
        for parent_id in node.parents:
            parent = self.nodes_by_id.get(parent_id)
            if parent is None:
                continue
            if parent.completed() and not include_completed:
                continue
            result.add(parent)
            result |= self.ancestors(parent, include_completed)
        return result

    def call_match(self, node):
        """Transition node ASLEEP -> CALLED. Returns effects.

        Handles bye / drop / dq auto-resolution by short-circuiting to
        complete_match without emitting LaunchTournamentMatch.
        """
        if not node.asleep():
            return []
        if node.is_bye():
            return self.auto_resolve_non_match(node, reason="bye")
        if self.tournament.has_drop_or_dq(node.players):
            return self.auto_resolve_non_match(node, reason="drop_or_dq")

        node.status = MATCH_STATUS_CALLED
        node.checkin_deadline = time.time() + node.checkin_timer
        self.called_matches.append(node)
        for p in node.players:
            self.current_match_by_player[p] = node
            self.matches_by_player.setdefault(p, []).append(node)
        for i, p in enumerate(node.players):
            for q in node.players[i + 1:]:
                self.matches_by_pair.setdefault(p, {}).setdefault(q, []).append(node)
                self.matches_by_pair.setdefault(q, {}).setdefault(p, []).append(node)
        return [LaunchTournamentMatch(
            node_id=node.node_id,
            tournament_id=self.tournament_id,
            graph_id=self.graph_id,
            players=[getattr(p.uid, "id", None) for p in node.players],
            game=node.game,
            mode=node.mode,
            best_of=node.best_of,
            label=node.label,
            stream=node.streamed,
        )]

    def receive_checkin(self, node, user):
        """Add user to node.checkins. Transition to ACTIVE if all checked in."""
        if not node.awake() or user not in node.players:
            return []
        node.checkins.add(user)
        if len(node.checkins) >= len(node.players) and node.status == MATCH_STATUS_CALLED:
            node.status = MATCH_STATUS_ACTIVE
            if node in self.called_matches:
                self.called_matches.remove(node)
            self.active_matches.append(node)
        return []

    def report_score(self, node, reporter, score_tuple):
        """Record a score report from a player or admin.

        score_tuple is (a, b) with non-negative ints summing to best_of's
        first_to or less. Validates legality. Confirms when both players
        agree (or reporter is admin) and triggers complete_match.

        Returns (accepted: bool, effects: list).
        """
        if not node.awake():
            return False, []
        if not self._score_legal(node, score_tuple):
            return False, []
        node.reports[reporter] = tuple(score_tuple)

        confirmed = False
        if getattr(reporter, "is_admin", lambda: False)() if hasattr(reporter, "is_admin") else False:
            confirmed = True
        elif len(node.reports) >= len(node.players):
            unique = set(node.reports.values())
            if len(unique) == 1:
                confirmed = True

        if confirmed:
            agreed = next(iter(set(node.reports.values())))
            node.score = list(agreed)
            return True, self.complete_match(node)
        return True, []

    def _score_legal(self, node, score):
        a, b = score
        if a < 0 or b < 0:
            return False
        ft = node.first_to()
        if ft <= 0:
            return a + b > 0
        if max(a, b) > ft:
            return False
        if max(a, b) == ft and min(a, b) >= ft:
            return False
        return a + b > 0

    def complete_match(self, node):
        """Transition node -> COMPLETED. Propagate winner/loser to children
        and recursively call any children that are now ready."""
        if node.completed():
            return []
        node.status = MATCH_STATUS_COMPLETED
        if node in self.active_matches:
            self.active_matches.remove(node)
        if node in self.called_matches:
            self.called_matches.remove(node)
        for p in node.players:
            if self.current_match_by_player.get(p) is node:
                self.current_match_by_player[p] = None

        effects = []
        winner = node.winner()
        loser = node.loser()

        for child_id, flag in list(node.children.items()):
            child = self.nodes_by_id.get(child_id)
            if child is None:
                continue
            incoming = winner if flag == "W" else loser
            if incoming is not None and incoming not in child.players:
                child.players.append(incoming)
            if child is self.victory_node:
                # Victory sentinel: mark completed once a winner reaches it.
                if winner is not None:
                    child.status = MATCH_STATUS_COMPLETED
                    self.placements_dict[winner] = 1
            elif self._child_ready(child):
                effects += self.call_match(child)

        if node.loser_gets is not None and loser is not None:
            self.placements_dict[loser] = node.loser_gets

        effects.append(ArchiveTournamentMatch(node_id=node.node_id))
        return effects

    def _child_ready(self, child):
        """A child is ready to call once all its parent nodes have completed
        and its players list is fully resolved (or it's a victory node with
        all incoming streams settled)."""
        for parent_id in child.parents:
            parent = self.nodes_by_id.get(parent_id)
            if parent is None or not parent.completed():
                return False
        if len(child.parents) > 0 and len(child.players) < min(2, len(child.parents)):
            return False
        return True

    def auto_resolve_non_match(self, node, reason):
        """Handle a node that should not actually play (bye/drop/dq)."""
        node.status = MATCH_STATUS_COMPLETED
        present = [
            p for p in node.players
            if not getattr(p, "is_bye", lambda: False)()
            and not self.tournament.is_dropped(p)
            and not self.tournament.is_dq(p)
        ]
        if len(present) == 1:
            winner_idx = node.players.index(present[0])
            node.score = [0, 0]
            node.score[winner_idx] = node.first_to() if node.first_to() > 0 else 1
        self.non_matches[node.node_id] = reason

        effects = []
        winner = node.winner()
        loser = node.loser()
        for child_id, flag in list(node.children.items()):
            child = self.nodes_by_id.get(child_id)
            if child is None:
                continue
            incoming = winner if flag == "W" else loser
            if incoming is not None and incoming not in child.players:
                child.players.append(incoming)
            if self._child_ready(child):
                effects += self.call_match(child)
        return effects

    def schedule_stream(self):
        for m in self.stream_candidates:
            self.stream_planned.append(m)
        self.stream_candidates.clear()

    def score_stream_match(self, node):
        """Default scoring: prefer matches deeper in the bracket (smaller
        loser_gets) and matches not yet streamed. Subclasses can override.
        """
        loser_gets = node.loser_gets if node.loser_gets is not None else 999
        already_streamed = 1 if node in self.stream_history else 0
        return (already_streamed, loser_gets)

    def call_match_for_stream(self, candidates):
        """Pick the best candidate as next streamed match. Returns effects."""
        if not candidates and not self.stream_planned:
            return []
        pool = list(candidates) + list(self.stream_planned)
        if not pool:
            return []
        pool.sort(key=lambda effect_or_node: 0)
        best_node = None
        for c in pool:
            if isinstance(c, LaunchTournamentMatch):
                node = self.nodes_by_id.get(c.node_id)
                if node:
                    if best_node is None or self.score_stream_match(node) < self.score_stream_match(best_node):
                        best_node = node
            elif isinstance(c, MatchNode):
                if best_node is None or self.score_stream_match(c) < self.score_stream_match(best_node):
                    best_node = c
        if best_node is None:
            return []
        self.stream_match = best_node
        self.stream_history.append(best_node)
        return [CallMatchForStream(node_id=best_node.node_id)]

    def undo_match(self, node):
        """Revert a completed match. Cascades through children that depend on it."""
        if not node.completed():
            return []
        effects = []
        for child_id in list(node.children):
            child = self.nodes_by_id.get(child_id)
            if child is None:
                continue
            if child.completed():
                effects += self.undo_match(child)
            winner = node.winner()
            loser = node.loser()
            flag = node.children[child_id]
            incoming = winner if flag == "W" else loser
            if incoming is not None and incoming in child.players:
                child.players.remove(incoming)
            if not child.asleep():
                child.status = MATCH_STATUS_ASLEEP
                child.checkins.clear()
                child.reports.clear()
                child.score = [0, 0]
                if child in self.called_matches:
                    self.called_matches.remove(child)
                if child in self.active_matches:
                    self.active_matches.remove(child)

        node.status = MATCH_STATUS_ASLEEP
        node.score = [0, 0]
        node.checkins.clear()
        node.reports.clear()
        for p in node.players:
            if self.placements_dict.get(p, -1) == node.loser_gets:
                self.placements_dict[p] = -1
        return effects

    def undo_drop_user(self, user):
        return []

    def undo_dq_user(self, user):
        return []

    def get_placements(self):
        return sorted(
            ((rank, p) for p, rank in self.placements_dict.items() if rank > 0),
            key=lambda t: t[0],
        )

    def is_user_in_match(self, user):
        m = self.current_match_by_player.get(user)
        return m is not None and not m.completed()

    def completed(self):
        return self.victory_node is not None and self.victory_node.completed()
