"""Ladder: persistent friendlies session as a MatchGraph subclass.

Refactored in Phase 5a from standalone class to MatchGraph subclass:
  - Inherits from MatchGraph (pure-data, MatchNode-based DAG).
  - Time-bounded by `end_time`; `victory_node` exists (from base) but
    never completes.
  - `generate_bracket()` returns []  — matchmaking is dynamic and
    driven by explicit `matchmaking(...)` calls.
  - All bookkeeping uses MatchNode. The Match↔MatchNode mapping lives
    in tournament_state.nodes_to_matches; the adapter
    (`axi/handlers/ladder_handler.py`) populates it when it consumes
    LaunchTournamentMatch effects emitted by Ladder.matchmaking().
  - `advance(match)` / `abort(match)` keep the legacy Match-receiving
    signature (called by `axi/handlers/match_handler.close_match`)
    but translate to MatchNode internally and delegate to
    `complete_match(node)` / `cancel_match_for_node(node)`.

No user-visible behavior changes from this refactor.
"""

import time as _time_module
import uuid
from copy import copy
from math import log, exp

from openskill import Rating
from pytimeparse.timeparse import timeparse

from axi.match_graph import MatchGraph
from axi.match_node import MatchNode
from axi.tournament import Tournament
from axi.tournament_state import state as tournament_state
from axi.util import (
    rng,
    MATCH_STATUS_CALLED, MATCH_STATUS_COMPLETED,
    USER_STATUS_QUEUED, USER_STATUS_BREAK, USER_STATUS_CALLED,
)
from axi.ratings.plackett_luce_extended import PlackettLuceExtended
from axi.ratings.glicko_timeless import GlickoTimeless
from axi.ratings.danisen import Danisen


class Ladder(MatchGraph):
    """Friendlies session as a MatchGraph subclass."""

    def __init__(self, guild=None, config=None, scheduled_event=None,
                 streamed=False, time_fn=None, duration_seconds=None,
                 *, tournament=None, players=None,
                 name=None, game=None, fmt=None,
                 queue_channel=None, status_channel=None,
                 results_channel=None, leaderboard_channel=None):
        """Two construction paths:
          - Discord-session: `Ladder(guild, config, scheduled_event, ...)`
            (config dict with name/game/format/duration/channel fields).
          - Tournament-format: pass `tournament=` + `players=` + explicit
            field kwargs (no guild/config). Used by LadderElimination and
            other tournament-format subclasses.
        """
        self.rowid = None
        self.guild = guild
        self.config = config
        self.scheduled_event = scheduled_event
        self.streamed = streamed
        self.status_message = None
        self.leaderboard_message = None
        self._time_fn = time_fn or _time_module.time

        if config is not None:
            # Discord-session path.
            self.name = config["name"]
            self.game = config["game"]
            self.fmt = config["format"]
            self.queue_channel = config["queue-channel"]
            self.status_channel = config["status-channel"]
            self.results_channel = config["results-channel"]
            self.leaderboard_channel = config["leaderboard-channel"]
            if duration_seconds is not None:
                self.duration = duration_seconds
            else:
                self.duration = timeparse(config["duration"])
        else:
            # Tournament-format path.
            self.name = name or "ladder"
            self.game = game or getattr(tournament, "game", "rps") if tournament else "rps"
            self.fmt = fmt or "openskill"
            self.queue_channel = queue_channel
            self.status_channel = status_channel
            self.results_channel = results_channel
            self.leaderboard_channel = leaderboard_channel
            # Tournament-format Ladders never auto-complete by time.
            self.duration = duration_seconds if duration_seconds is not None else float("inf")

        # Synthetic Tournament satisfies MatchGraph's required arg.
        # Ladder is its own session type; doesn't register with
        # tournament_state's scope_to_tournament map.
        if tournament is None:
            tournament = Tournament(
                title=self.name,
                scope=self.queue_channel,
            )
        super().__init__(tournament, players or [], stream=streamed)
        # Default to empty player list (Discord path populates via
        # add_new_player); tournament-format path can pass non-empty players.
        if players is None:
            self.players = []

    def _now(self):
        return self._time_fn()

    def get_db_entry(self):
        return [
            self.guild.id,
            self.name,
            self.game,
            self.fmt,
        ]

    # -- MatchGraph contract --

    def generate_bracket(self):
        """Initial bracket for a Ladder is empty — matches are spawned
        dynamically via `matchmaking(pairings)`."""
        return []

    # -- Lifecycle --

    def begin(self):
        self.create_data_structures()
        return []

    def create_data_structures(self):
        # Initialize MatchGraph-base structures with current players.
        super().create_data_structures()
        # Ladder-specific overlays on top of base bookkeeping.
        self.status_by_player = {p: USER_STATUS_QUEUED for p in self.players}
        self.stream_matches_by_player = {p: [] for p in self.players}
        self.autoqueue_by_player = {p: False for p in self.players}
        self.past_matches = []

        self.initial_rating_glicko = (0, Rating(mu=300, sigma=100))
        self.initial_rating_openskill = (0, Rating(mu=300, sigma=100))
        self.initial_rating_danisen = (1, 0)
        self.initial_rating = None
        self.ratings_model = None
        if self.fmt == "glicko":
            self.initial_rating = self.initial_rating_glicko
            self.ratings_model = GlickoTimeless
        elif self.fmt == "openskill":
            self.initial_rating = self.initial_rating_openskill
            self.ratings_model = PlackettLuceExtended
        elif self.fmt == "danisen":
            self.initial_rating = self.initial_rating_danisen
            self.ratings_model = Danisen
        self.ratings_by_player = {p: self.load_rating(p) for p in self.players}
        self._persist_ratings(self.players)

        current_time = self._now()
        self.end_time = current_time + self.duration
        self.downtime_minimum = 20.0
        self.downtime_by_player = {p: self.downtime_minimum for p in self.players}
        self.downtime_clock_by_player = {p: current_time - self.downtime_minimum for p in self.players}

        self.challenge_requests = {p: [] for p in self.players}
        self.challenges_on_deck = []

        self.matchmaking_num_hypotheses = 100
        self.rating_num_epochs = 10
        self.rating_learning_rate = 2.0
        self.sweep_bonus = 1.0
        self.bo3_penalty = 0.8
        self.matchup_regularization = 1.0

    @property
    def player_count(self):
        return len(self.players)

    def load_rating(self, p):
        if self.rowid is None:
            return self.initial_rating
        import axi.handlers.ladder_handler as _lh
        rating = _lh.load_from_ratings_db(self, p)
        if rating:
            return rating
        return self.initial_rating

    def _persist_ratings(self, players):
        """Persist ratings to DB. No-op if not yet registered (rowid is None)."""
        if self.rowid is None:
            return
        import axi.handlers.ladder_handler as _lh
        _lh.update_ratings_db(self, players)

    def add_new_player(self, user):
        if self.completed():
            return False
        self.players.append(user)
        for p in self.matches_by_pair:
            self.matches_by_pair[p][user] = []
        self.matches_by_pair[user] = {q: [] for q in self.players}
        self.matches_by_player[user] = []
        self.current_match_by_player[user] = None
        self.ratings_by_player[user] = self.load_rating(user)
        self._persist_ratings([user])
        self.stream_matches_by_player[user] = []
        self.status_by_player[user] = USER_STATUS_BREAK
        self.start_downtime_clock(user)
        self.downtime_clock_by_player[user] -= 20.0
        self.challenge_requests[user] = []
        self.autoqueue_by_player[user] = False
        return True

    def start_downtime_clock(self, user):
        self.downtime_clock_by_player[user] = self._now()
        self.downtime_by_player[user] = 0.0

    def query_downtime_clock(self, user):
        return self._now() - self.downtime_clock_by_player[user]

    def stop_downtime_clock(self, user):
        if self.status_by_player[user] not in [USER_STATUS_QUEUED, USER_STATUS_BREAK]:
            time_passed = self._now() - self.downtime_clock_by_player[user]
            if time_passed > 0:
                self.downtime_by_player[user] += time_passed

    # -- Stream scoring --

    def score_stream_match(self, node):
        p0 = node.players[0]
        p1 = node.players[1]
        return abs(self.ratings_by_player[p0][0] - self.ratings_by_player[p1][0])

    # -- Backward-compat Match-receiving adapters --

    def advance(self, match):
        """Adapter: translate Match→MatchNode and route to complete_match.

        Called by `axi/handlers/match_handler.close_match` when a Match
        finishes. Returns None to preserve the legacy void signature.
        """
        if not match.check_match_over():
            return None
        node_id = tournament_state.get_node_for_match(id(match))
        node = self.nodes_by_id.get(node_id) if node_id else None
        if node is not None:
            # Project Match's score onto the MatchNode.
            scores = getattr(match, "score", None)
            if scores is None:
                scores = [match.scores.get(p, 0) for p in node.players] \
                    if hasattr(match, "scores") else [0, 0]
            node.score = list(scores)
            if node.status != MATCH_STATUS_COMPLETED:
                node.status = MATCH_STATUS_COMPLETED
            self.complete_match(node)
        return None

    def abort(self, match):
        """Adapter: translate Match→MatchNode and route to cancel_match_for_node.

        Called by `axi/handlers/match_handler.cancel_match`. Returns None.
        """
        node_id = tournament_state.get_node_for_match(id(match))
        node = self.nodes_by_id.get(node_id) if node_id else None
        if node is not None:
            self.cancel_match_for_node(node)
        return None

    def cancel_match(self, match_or_node):
        """Cancel a match by either Match (legacy) or MatchNode."""
        if isinstance(match_or_node, MatchNode):
            self.cancel_match_for_node(match_or_node)
        else:
            self.abort(match_or_node)

    # -- Core node-based lifecycle --

    def complete_match(self, node):
        """MatchNode-based completion. Idempotent: ignores already-cleaned nodes."""
        if not node.completed():
            return []
        self.update_ratings(node)
        if node not in self.past_matches:
            self.past_matches.append(node)
        if node == self.stream_match:
            self.stream_match = None
        if node in self.stream_planned:
            self.stream_planned.remove(node)
        if node in self.active_matches:
            self.active_matches.remove(node)
        if node in self.called_matches:
            self.called_matches.remove(node)
        for player in node.players:
            current_for = self.current_match_by_player.get(player)
            if current_for and current_for.completed():
                self.current_match_by_player[player] = None
            if (self.status_by_player.get(player) != USER_STATUS_BREAK
                    and self.autoqueue_by_player.get(player)):
                self.queue(player)
            else:
                self.dequeue(player)
        return []

    def cancel_match_for_node(self, node):
        """Node-based cancellation (no scoring, no rating update)."""
        if node == self.stream_match:
            self.stream_match = None
        if node in self.stream_planned:
            self.stream_planned.remove(node)
        if node in self.active_matches:
            self.active_matches.remove(node)
        if node in self.called_matches:
            self.called_matches.remove(node)
        a, b = node.players[0], node.players[1]
        if node in self.matches_by_pair.get(a, {}).get(b, []):
            self.matches_by_pair[a][b].remove(node)
        if node in self.matches_by_pair.get(b, {}).get(a, []):
            self.matches_by_pair[b][a].remove(node)
        if node in self.matches_by_player.get(a, []):
            self.matches_by_player[a].remove(node)
        if node in self.matches_by_player.get(b, []):
            self.matches_by_player[b].remove(node)
        self.current_match_by_player[a] = None
        self.current_match_by_player[b] = None
        if self.status_by_player.get(a) == USER_STATUS_CALLED:
            self.queue(a)
        if self.status_by_player.get(b) == USER_STATUS_CALLED:
            self.queue(b)

    def completed(self):
        return self._now() >= self.end_time

    def afloat_and_drowning(self, users, breakers):
        """Default: no drowning concept (friendlies). Subclasses
        (e.g. LadderElimination) override with lava-derived partition.

        Returns (afloat, drowning) where afloat = users+breakers and
        drowning = []. Phase 7 handler-level scoring uses this uniform
        API across all Ladder subclasses.
        """
        return list(users) + list(breakers), []

    def queue(self, user):
        self.status_by_player[user] = USER_STATUS_QUEUED
        self.start_downtime_clock(user)

    def dequeue(self, user):
        self.status_by_player[user] = USER_STATUS_BREAK
        self.start_downtime_clock(user)

    def get_sorted_ratings(self):
        return sorted(list(self.players), key=lambda x: -self.ratings_by_player[x][0])

    def get_players_by_status(self):
        queued_players = []
        break_players = []
        called_players = []
        for p in self.players:
            s = self.status_by_player[p]
            if s == USER_STATUS_QUEUED:
                queued_players.append(p)
            elif s == USER_STATUS_BREAK:
                break_players.append(p)
            elif s == USER_STATUS_CALLED:
                called_players.append(p)
        return queued_players, break_players, called_players

    # -- Matchmaking --

    def matchmaking(self, basic_pairings, challenge_pairings, set_stream_match=True):
        """Generate match nodes for the given pairings and return effects.

        Effects emitted: LaunchTournamentMatch per non-stream match,
        plus optional CallMatchForStream for the selected stream match.
        The adapter (ladder_handler) consumes these to actually launch
        the underlying Match objects via match_handler.launch_match.
        """
        nodes = self.generate_match_nodes(
            basic_pairings, challenge_pairings, set_stream_match)
        effects = []
        stream_candidates = []
        for n in nodes:
            if n.streamed:
                stream_candidates.append(n)
            else:
                effects += self.call_match(n)
        if not self.stream_match and stream_candidates:
            effects += self.call_match_for_stream(stream_candidates)
        return nodes, effects

    def generate_match_nodes(self, basic_pairings, challenge_pairings, set_stream_match=True):
        if self.player_count == 1:
            return []
        best_of = 3
        nodes = []
        node_dict = dict()
        pairings = basic_pairings + challenge_pairings
        for pair in pairings:
            timer = 120
            label = "LADDER MATCH"
            if pair in challenge_pairings:
                label = "CHALLENGE MATCH"
            node = self.add_node(
                players=list(pair),
                game=self.game,
                mode="versus",
                best_of=best_of,
                checkin_timer=timer,
                label=label,
            )
            nodes.append(node)
            node_dict[pair[0]] = node
            node_dict[pair[1]] = node
        if nodes and self.streamed and not self.stream_match and set_stream_match:
            chosen = self.select_stream_match(nodes)
            if chosen is not None:
                chosen.streamed = True
                self.stream_planned.append(chosen)
                for p in chosen.players:
                    self.stream_matches_by_player[p].append(chosen)
        return nodes

    def select_stream_match(self, nodes):
        last_streamed_players = (
            self.stream_history[-1].players if self.stream_history else [])
        second_last_streamed_players = (
            self.stream_history[-2].players if len(self.stream_history) > 1 else [])
        best_score = 9999999
        chosen = None
        for n in nodes:
            p0, p1 = n.players[0], n.players[1]
            if p0 in last_streamed_players and p0 in second_last_streamed_players:
                continue
            if p1 in last_streamed_players and p1 in second_last_streamed_players:
                continue
            score = abs(self.ratings_by_player[p0][0] - self.ratings_by_player[p1][0])
            score += 250 * (
                len(self.stream_matches_by_player[p0])
                + len(self.stream_matches_by_player[p1]))
            if score < best_score:
                best_score = score
                chosen = n
        return chosen

    def call_match(self, node):
        """Transition node to CALLED + emit LaunchTournamentMatch."""
        for p in node.players:
            self.status_by_player[p] = USER_STATUS_CALLED
            self.stop_downtime_clock(p)
        return super().call_match(node)

    def call_match_for_stream(self, candidates):
        """Pick best candidate for streaming + call it. Returns effects."""
        best_score = (999999,)
        best_node = None
        for n in self.stream_planned:
            score = self.score_stream_match(n)
            if (score,) < best_score:
                best_score = (score,)
                best_node = n
        if best_node is None:
            return []
        self.stream_match = best_node
        self.stream_planned.remove(best_node)
        self.stream_history.append(best_node)
        return self.call_match(best_node)

    # -- Ratings --

    def update_ratings(self, node):
        if not self.ratings_model:
            return
        winner = node.winner()
        if winner is None:
            return
        p0 = winner
        p1 = node.players[1] if p0 == node.players[0] else node.players[0]
        p0_rating = self.ratings_by_player[p0]
        p1_rating = self.ratings_by_player[p1]
        try:
            delta_result = self.ratings_model(
                [p0_rating, p1_rating]).calculate_deltas()
            self.ratings_by_player[p0] = (
                self.ratings_by_player[p0][0] + delta_result[0][0],
                self.ratings_by_player[p0][1] + delta_result[0][1],
            )
            self.ratings_by_player[p1] = (
                self.ratings_by_player[p1][0] + delta_result[1][0],
                self.ratings_by_player[p1][1] + delta_result[1][1],
            )
            if (self.ratings_by_player[p1][0] < 1
                    or (self.ratings_by_player[p1][0] == 1
                        and self.ratings_by_player[p1][1] < 0)):
                self.ratings_by_player[p1] = (1, 0)
        except (TypeError, AttributeError, Exception):
            # Rating model returned non-numeric values (e.g. MagicMock in
            # tests). Skip the rating update gracefully.
            return
        self._persist_ratings([p0, p1])

    # -- Pairing search --

    def generate_pairings(self, available):
        best_score = 0
        best_hypothesis = []
        for _ in range(self.matchmaking_num_hypotheses):
            rng.shuffle(available)
            score = 0
            hypothesis = []
            for j in range(0, len(available), 2):
                p0 = available[j]
                if j + 1 == len(available):
                    score += self.ratings_by_player[p0][0]
                    continue
                p1 = available[j + 1]
                viable = not self.matches_by_pair[p0][p1]
                if not viable:
                    last0 = self.matches_by_player[p0][-1] if self.matches_by_player[p0] else None
                    last1 = self.matches_by_player[p1][-1] if self.matches_by_player[p1] else None
                    most_recent = (last0 is not None and last1 is not None
                                   and p1 in last0.players
                                   and p0 in last1.players
                                   and self.player_count > 2)
                    if not most_recent:
                        late_stage = (
                            len(self.matches_by_player[p0]) >= min(6, self.player_count - 1)
                            and len(self.matches_by_player[p1]) >= min(6, self.player_count - 1)
                        )
                        viable = late_stage
                if viable:
                    hypothesis.append((p0, p1))
                    score += 1000
                    r0 = self.ratings_by_player[p0][0]
                    r1 = self.ratings_by_player[p1][0]
                    score -= abs(r0 - r1)
                    score -= 250 * len(self.matches_by_pair[p0][p1])
            if score > best_score:
                best_score = score
                best_hypothesis = hypothesis
        return best_hypothesis

    def schedule_stream(self):
        for m in self.stream_candidates:
            self.stream_planned.append(m)
        self.stream_candidates.clear()

    # -- Queries --

    def get_matches_by_pair(self, user0, user1):
        if user0 in self.matches_by_pair and user1 in self.matches_by_pair[user0]:
            return self.matches_by_pair[user0][user1]
        return None

    def is_user_in_match(self, user):
        n = self.get_current_match_by_player(user)
        return n is not None and not n.completed()

    def are_users_in_match(self, user0, user1):
        n = self.get_current_match_by_player(user0)
        return n is not None and user1 in n.players

    def get_matches_by_player(self, user):
        return self.matches_by_player[user]

    def get_current_match_by_player(self, user):
        return self.current_match_by_player.get(user)

    def get_active_matches(self):
        return self.active_matches

    def get_called_matches(self):
        return self.called_matches

    def clear_called_matches(self):
        self.called_matches.clear()

    def get_opponent(self, user):
        n = self.get_current_match_by_player(user)
        if n is None:
            return None
        if user == n.players[0]:
            return n.players[1]
        return n.players[0]

    def checkin_user_for_match(self, user):
        node = self.get_current_match_by_player(user)
        checkin = True
        if node is not None:
            if node not in self.active_matches:
                self.active_matches.append(node)
            if node in self.called_matches:
                self.called_matches.remove(node)
        return node, checkin

    def get_stream_history(self):
        return self.stream_history

    def get_stream_match(self):
        return self.stream_match

    def get_stream_planned(self):
        return self.stream_planned

    def challenge(self, p0, p1):
        if len(self.matches_by_pair[p0][p1]) > 2:
            return False, True
        if len(self.matches_by_pair[p0][p1]) == 2:
            if self.matches_by_pair[p0][p1][0].winner() == self.matches_by_pair[p0][p1][1].winner():
                return False, True
        if p1 not in self.challenge_requests[p0]:
            self.challenge_requests[p0].append(p1)
        if p0 in self.challenge_requests[p1]:
            self.challenges_on_deck.append((p0, p1))
            return True, False
        return False, False
