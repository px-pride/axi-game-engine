import colorsys
import random
import uuid
from collections import defaultdict

from axi.tournament_presets import apply_preset
from axi.tournament_state import state as tournament_state


class Tournament:
    """Top-level tournament orchestrator.

    Holds a sequence of phases (each a MatchGraph), drop/dq state, RNG,
    player colors, and preset wiring. All Discord I/O lives in effects.
    """

    def __init__(self, title, scope, series=None, seed=None,
                 series_id=None, multibracket_id=None):
        self.tournament_id = uuid.uuid4().hex
        self.title = title
        self.scope = scope
        # Series can be a Series instance (preferred) or an int rowid.
        # Both paths converge to self.series_id; the instance ref is
        # kept for the series_handler.
        if hasattr(series, "rowid"):
            self.series = series
            self.series_id = series.rowid
        else:
            self.series = None
            self.series_id = series_id
        # Multibracket linkage; set by series_handler.register_tournament.
        self.multibracket_id = multibracket_id
        self.series_ctr = None
        # Phase 9: id of the check-in announcement message (set by
        # discord adapter when /createcheckins posts).
        self.checkins_post_id = None
        # Phase 10: checkpoint counter + last saved checkpoint id.
        self.checkpoint_ctr = 0
        self.checkpoint_id = None
        self.rng = random.Random(seed) if seed is not None else random.Random()

        self.players = []
        self.placements = []
        self.phase_fns = []
        self.phases = []
        self.phase_id = -1
        self.started = False
        self.frozen = False
        self.manual_phases = False

        self.drop_dict = defaultdict(list)
        self.dq_dict = defaultdict(list)
        self.onedrop_dict = defaultdict(list)

        self.streamer = None
        self.format = ""
        self.player_colors = {}

    def add_players(self, players):
        for p in players:
            if p not in self.players:
                self.players.append(p)

    def remove_players(self, players):
        for p in players:
            if p in self.players and not self.started:
                self.players.remove(p)

    def current_phase(self):
        if 0 <= self.phase_id < len(self.phases):
            return self.phases[self.phase_id]
        return None

    def preset(self, name):
        """Apply a preset by name. Returns True on success."""
        if self.started:
            return False
        return apply_preset(self, name)

    def begin(self):
        if self.started or not self.phase_fns:
            return []
        self.started = True
        self.assign_player_colors()
        self.placements = [(-1, p) for p in self.players]
        self.phase_id = -1
        return self.advance_phase()

    def advance_phase(self):
        if self.completed():
            return []
        self.phase_id += 1
        if self.phase_id >= len(self.phase_fns):
            return []
        graph = self.phase_fns[self.phase_id](self, self._players_for_phase())
        self.phases.append(graph)
        result = graph.begin()
        # Phase 10: snapshot state after phase advance.
        self.save_checkpoint()
        return result

    def _players_for_phase(self):
        """Players entering the current phase. Default: all players still
        in the running (not dropped/dq). Subclasses/presets may override."""
        return [p for p in self.players if not self.is_dropped(p) and not self.is_dq(p)]

    def check_end_of_phase(self):
        graph = self.current_phase()
        if graph is None or not graph.completed():
            return []
        if self.manual_phases:
            return []
        return self.advance_phase()

    def completed(self):
        return (
            self.started
            and len(self.phases) == len(self.phase_fns)
            and (self.current_phase() is None or self.current_phase().completed())
        )

    def winner(self):
        graph = self.current_phase()
        if graph is None or graph.victory_node is None:
            return None
        if not graph.victory_node.completed():
            return None
        # victory_node holds the final winner in players[0] (propagated from finals).
        if graph.victory_node.players:
            return graph.victory_node.players[0]
        return None

    def drop_user(self, user):
        if user not in self.players:
            return []
        self.drop_dict[user].append(self.phase_id)
        self.save_checkpoint()  # Phase 10
        return []

    def dq_user(self, user):
        if user not in self.players:
            return []
        self.dq_dict[user].append(self.phase_id)
        self.save_checkpoint()  # Phase 10
        return []

    def is_dropped(self, user):
        return user in self.drop_dict and len(self.drop_dict[user]) > 0

    def is_dq(self, user):
        return user in self.dq_dict and len(self.dq_dict[user]) > 0

    def has_drop_or_dq(self, players):
        return any(self.is_dropped(p) or self.is_dq(p) for p in players)

    def undo_match(self, p0, p1):
        graph = self.current_phase()
        if graph is None:
            return []
        for p, q in ((p0, p1), (p1, p0)):
            pair = graph.matches_by_pair.get(p, {}).get(q, [])
            if pair:
                last = pair[-1]
                if last.completed():
                    return graph.undo_match(last)
        return []

    def undo_drop_user(self, user):
        if user in self.drop_dict and self.drop_dict[user]:
            self.drop_dict[user].pop()
        return []

    def undo_dq_user(self, user):
        if user in self.dq_dict and self.dq_dict[user]:
            self.dq_dict[user].pop()
        return []

    def undo_phase(self):
        if self.phase_id < 0 or not self.phases:
            return []
        self.phases.pop()
        self.phase_id -= 1
        return []

    def report_score(self, reporter, p0, p1, score):
        graph = self.current_phase()
        if graph is None:
            return False, []
        pair = graph.matches_by_pair.get(p0, {}).get(p1, [])
        for node in reversed(pair):
            if node.awake():
                accepted, effects = graph.report_score(node, reporter, score)
                if accepted:
                    return True, effects
        return False, []

    def report_match_complete(self, node_id, winner_user_id, score):
        """Called from the match_handler completion callback wired by the
        Discord adapter when a launched match finishes.

        Maps the result onto the node and triggers complete_match.
        """
        graph = self.current_phase()
        if graph is None:
            return []
        node = graph.nodes_by_id.get(node_id)
        if node is None or not node.awake():
            return []
        node.score = list(score)
        effects = graph.complete_match(node)
        effects += self.check_end_of_phase()
        return effects

    def set_streamer(self, user):
        self.streamer = user

    def assign_player_colors(self):
        n = max(len(self.players), 1)
        self.player_colors = {}
        for i, p in enumerate(self.players):
            hue = i / n
            r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
            self.player_colors[p] = (int(r * 255), int(g * 255), int(b * 255))

    def visualize(self):
        """Stub for Phase 15 — Graphviz DOT generation lives there."""
        return None

    def save_checkpoint(self):
        """Persist current tournament state. Phase 10 implementation."""
        from axi.handlers import checkpoint_handler
        try:
            return checkpoint_handler.save_checkpoint(self)
        except Exception:
            return None

    def reduce_double_jeopardy(self, players):
        """For RR → DE seeding: prevent rematches by swapping pairs in the
        bottom 1/3 of the seed list. Used by composite presets (Phase 4).

        Mutates and returns `players` (so call sites can chain).
        """
        n = len(players)
        cutoff = (2 * n) // 3
        for i in range(cutoff, n - 1, 2):
            players[i], players[i + 1] = players[i + 1], players[i]
        return players
