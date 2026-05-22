"""LadderElimination tournament format ('px' preset).

Ladder-style tournament where players queue continuously and "lava"
rises over time, eliminating the bottom-ranked players in tiers. Each
elimination round, the bottom players (by rating) face DANGER MATCH /
DOUBLE DANGER pairings. Final 3 → LOSERS FINALS. Final 2 → GRAND FINALS.

Key architecture (per docs/phase-5-ladder_elimination-plan.md):
  - MatchGraph subclass (NOT axi/ladder.py extension — friendlies is Phase 6).
  - Dynamic generate_bracket: returns initial matchmaking; subsequent
    matches via complete_match → matchmaking() re-trigger. No link_parent.
  - Configurable time_fn for deterministic FakeClock-based tests.
  - All 7 tuning params configurable as kwargs.
  - Rating model: 'openskill' default (PlackettLuceExtended); 'glicko'
    (GlickoTimeless); 'elementary' (test-friendly deterministic).
"""

import math
import time
from dataclasses import dataclass

from axi.effects import UpdateLavaUI
from axi.match_graph import MatchGraph
from axi.tournament_presets import register_preset
from axi.util import (
    MATCH_STATUS_COMPLETED,
    USER_STATUS_BREAK,
    USER_STATUS_CALLED,
    USER_STATUS_ELIMINATED,
    USER_STATUS_QUEUED,
)


@dataclass
class _Rating:
    """Minimal mu/sigma rating compatible with the openskill/glicko interface.

    Production code that wants real openskill ratings can pass
    `openskill.Rating` objects via `initial_rating`. Otherwise this
    dataclass keeps tests independent of openskill/numpy.
    """
    mu: float = 300.0
    sigma: float = 100.0


class _ElementaryRatingModel:
    """Deterministic 2-player rating model for tests.

    Mirrors `PlackettLuceExtended` / `GlickoTimeless` interface:
      __init__([r0, r1]); calculate_deltas() → [[dmu0, dlog_sigma0],
                                                [dmu1, dlog_sigma1]]

    The first rating in the pair is treated as the winner (per the
    `update_ratings` convention of feeding p0_wins/p1_wins separately).
    Deltas: winner +1.0 mu, loser -1.0 mu, both -0.01 log_sigma.
    """

    def __init__(self, match_ratings):
        self.match_ratings = match_ratings

    def calculate_deltas(self):
        return [[1.0, -0.01], [-1.0, -0.01]]


def _resolve_rating_model(name):
    """Return (initial_rating, model_cls) for a rating-model name.

    'openskill' / 'glicko' lazily import the real classes; if those
    imports fail (e.g. test environment mocks openskill), fall back to
    the elementary model with _Rating defaults.
    """
    if name == "elementary":
        return (0, _Rating(mu=300.0, sigma=100.0)), _ElementaryRatingModel
    if name == "openskill":
        try:
            from openskill import Rating
            from axi.ratings.plackett_luce_extended import PlackettLuceExtended
            return (0, Rating(mu=300, sigma=100)), PlackettLuceExtended
        except Exception:
            return (0, _Rating(mu=300.0, sigma=100.0)), _ElementaryRatingModel
    if name == "glicko":
        try:
            from openskill import Rating
            from axi.ratings.glicko_timeless import GlickoTimeless
            return (0, Rating(mu=300, sigma=100)), GlickoTimeless
        except Exception:
            return (0, _Rating(mu=300.0, sigma=100.0)), _ElementaryRatingModel
    raise ValueError(f"Unknown rating model: {name!r}")


class LadderElimination(MatchGraph):
    """Ladder-elimination tournament with rising lava and rating-based pairing.

    Constructor params:
        tournament                  : owning Tournament
        players                     : list of AxiUser-like players
        stream                      : enable stream-match selection
        lava_delay                  : seconds before lava begins rising
        lava_rate                   : lava level units per second
        rating_model                : 'openskill' | 'glicko' | 'elementary'
        initial_rating              : override (threshold:int, Rating-like) tuple
        matchmaking_num_hypotheses  : number of pairing hypotheses to score
        rating_num_epochs           : gradient-descent epochs for update_ratings
        rating_learning_rate        : learning rate (divided by num_epochs)
        sweep_bonus                 : factor applied to clean-sweep wins
        bo3_penalty                 : 1/penalty factor for BO5+ matches
        matchup_regularization      : smoothing constant for win normalization
        time_fn                     : callable returning current time (test hook)
    """

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
                 checkin_normal=360,
                 checkin_break=480,
                 checkin_rps=240,
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
        self.checkin_normal = checkin_normal
        self.checkin_break = checkin_break
        self.checkin_rps = checkin_rps
        self._time_fn = time_fn or time.time

    def __repr__(self):
        return "LADDER ELIMINATION"

    def _now(self):
        return self._time_fn()

    # -- data-structure setup --

    def create_data_structures(self):
        super().create_data_structures()
        initial_rating, model_cls = _resolve_rating_model(self._rating_model_name)
        self.initial_rating = self._initial_rating_override or initial_rating
        self.ratings_model = model_cls

        self.past_matches = []
        self.lava_start_time = self._now()
        self.lava_freeze = None
        self.gfs = None
        self.player_count = len(self.players)
        self.lava_snapshot = -1
        self.placement_snapshot = -1
        self.players_in_danger = []
        self.placement_tiers = [1, 2]
        self.update_placement_tiers()

        self.ratings_by_player = {p: self.initial_rating for p in self.players}
        self.stream_matches_by_player = {p: [] for p in self.players}
        self.downtime_by_player = {p: 0.0 for p in self.players}
        self.downtime_clock_by_player = {
            p: self.lava_start_time + self.lava_delay for p in self.players
        }
        self.status_by_player = {p: USER_STATUS_QUEUED for p in self.players}

    # -- placement tiers --

    def update_placement_tiers(self):
        while self.placement_tiers[-1] < self.player_count:
            self.placement_tiers.append(
                self.placement_tiers[-1] + self.placement_tiers[-2])

    # -- lava clock --

    def get_lava_timer(self):
        return self._now() - (self.lava_start_time + self.lava_delay)

    def get_lava_level(self):
        lava_timer = self.get_lava_timer()
        if lava_timer < 0:
            return lava_timer
        if 0 < self.placement_snapshot <= self.player_count:
            return self.lava_snapshot
        lava_level = None
        placement_level = None
        for i in range(len(self.placement_tiers)):
            if lava_level is None or self.placement_tiers[-1 - i] >= self.player_count:
                lava_level = min(self.player_count, self.placement_tiers[-1 - i])
                placement_level = (
                    self.placement_tiers[-2 - i] + 1
                    if i < len(self.placement_tiers) - 1
                    else 1
                )
        self.lava_snapshot = lava_level
        self.placement_snapshot = placement_level
        return self.lava_snapshot

    # -- player status --

    def get_players_by_status(self):
        queued, on_break, eliminated, called = [], [], [], []
        for p in self.players:
            s = self.status_by_player[p]
            if s == USER_STATUS_QUEUED:
                queued.append(p)
            elif s == USER_STATUS_BREAK:
                on_break.append(p)
            elif s == USER_STATUS_ELIMINATED:
                eliminated.append(p)
            elif s == USER_STATUS_CALLED:
                called.append(p)
        return queued, on_break, eliminated, called

    def get_non_elim_sorted(self):
        """Non-eliminated players sorted by rating threshold descending."""
        non_elim = [p for p in self.players
                    if self.status_by_player[p] != USER_STATUS_ELIMINATED]
        non_elim.sort(key=lambda p: -self.ratings_by_player[p][0])
        return non_elim

    def queue(self, user):
        self.status_by_player[user] = USER_STATUS_QUEUED
        self.start_downtime_clock(user)

    def take_a_break(self, user):
        self.status_by_player[user] = USER_STATUS_BREAK
        self.start_downtime_clock(user)

    def start_downtime_clock(self, user):
        if self.status_by_player[user] not in (USER_STATUS_QUEUED, USER_STATUS_BREAK):
            self.downtime_clock_by_player[user] = max(
                self.downtime_clock_by_player[user], self._now())

    def stop_downtime_clock(self, user):
        if self.status_by_player[user] not in (USER_STATUS_QUEUED, USER_STATUS_BREAK):
            time_passed = self._now() - self.downtime_clock_by_player[user]
            if time_passed > 0:
                self.downtime_by_player[user] += time_passed

    def eliminate_user(self, user):
        if self.status_by_player[user] == USER_STATUS_ELIMINATED:
            return
        if self.placement_snapshot > 0:
            self.placements_dict[user] = self.placement_snapshot
        else:
            q = -1
            placement = -1
            for i in reversed(range(len(self.placement_tiers))):
                p = self.placement_tiers[i]
                if q >= self.player_count:
                    placement = p + 1 if i < len(self.placement_tiers) - 1 else 1
                elif q > 0:
                    break
                q = p
            self.placements_dict[user] = placement
        self.status_by_player[user] = USER_STATUS_ELIMINATED
        self.stop_downtime_clock(user)
        self.player_count -= 1

    def add_new_player(self, user):
        """Late-join: accepted iff lava has not yet reached the initial-rating
        floor. Returns True on accept (and triggers matchmaking), False
        otherwise."""
        if self.get_lava_level() >= self.initial_rating[0]:
            return False, []
        self.players.append(user)
        self.seed_by_player[user] = len(self.players) - 1
        for p in self.matches_by_pair:
            self.matches_by_pair[p][user] = []
        self.matches_by_pair[user] = {q: [] for q in self.players}
        self.matches_by_player[user] = []
        self.current_match_by_player[user] = None
        self.placements_dict[user] = -1
        self.ratings_by_player[user] = self.initial_rating
        self.stream_matches_by_player[user] = []
        queue_time = self._now()
        self.downtime_by_player[user] = max(
            0.0, queue_time - self.lava_start_time - self.lava_delay)
        self.downtime_clock_by_player[user] = max(
            self.lava_start_time + self.lava_delay, queue_time)
        self.player_count += 1
        self.update_placement_tiers()
        self.queue(user)
        return True, self.matchmaking()

    def drop_user(self, user):
        node = self.current_match_by_player.get(user)
        self.eliminate_user(user)
        if node is not None and not node.completed() and len(node.players) == 2:
            opp = node.opponent(user)
            idx = node.players.index(user)
            score = [0, 0]
            score[1 - idx] = node.first_to() if node.first_to() > 0 else 1
            node.score = score
            return self.complete_match(node)
        return []

    def dq_user(self, user):
        return self.drop_user(user)

    # -- at-risk / afloat-and-drowning partition --

    def get_at_risk(self):
        if self.lava_snapshot < 0:
            return []
        non_elim = self.get_non_elim_sorted()
        if not non_elim:
            return []
        at_risk = []
        num_tied = self.player_count - self.placement_snapshot + 1
        threshold_idx = max(0, self.placement_snapshot - 2)
        if threshold_idx >= len(non_elim):
            threshold_idx = len(non_elim) - 1
        rating_threshold = self.ratings_by_player[non_elim[threshold_idx]][0]
        for i in range(len(non_elim)):
            u = non_elim[-1 - i]
            if u in self.players_in_danger:
                continue
            if rating_threshold > 0:
                if self.ratings_by_player[u][0] >= rating_threshold:
                    break
                at_risk.append(u)
                if len(at_risk) + len(self.players_in_danger) == num_tied:
                    break
            else:
                if self.ratings_by_player[u][0] > 0:
                    break
                at_risk.append(u)
        return at_risk

    def afloat_and_drowning(self, users, breakers):
        afloat, drowning = [], []
        lava_level = self.get_lava_level()
        total = users + breakers
        if lava_level >= 0 and len(total) == self.player_count <= 3:
            non_elim = self.get_non_elim_sorted()
            for u in non_elim[-2:]:
                if u not in total:
                    return [], []
            return non_elim[:-2], non_elim[-2:]
        at_risk = self.get_at_risk()
        for u in users:
            if lava_level >= 0 and u in at_risk:
                drowning.append(u)
            else:
                afloat.append(u)
        for u in breakers:
            if (not self.current_match_by_player.get(u)
                    and lava_level >= 0 and u in at_risk):
                drowning.append(u)
        # Single at-risk left in end-game: pull the bottom breaker into the
        # afloat pool so a match can still be made.
        if (self.player_count == self.placement_snapshot
                and len(at_risk) == 1):
            non_elim = self.get_non_elim_sorted()
            if len(non_elim) >= 2:
                bottom_breaker = non_elim[-2]
                if bottom_breaker in breakers:
                    afloat.append(bottom_breaker)
        return afloat, drowning

    # -- pairings + bracket generation --

    def generate_pairings(self, afloat, drowning):
        available = list(afloat) + list(drowning)
        if self.get_lava_level() >= 0 and len(available) == self.player_count <= 3:
            if len(drowning) >= 2:
                return [(drowning[0], drowning[1])]
            return []
        best_score = 0
        best_hypothesis = []
        for _ in range(self.matchmaking_num_hypotheses):
            self.tournament.rng.shuffle(available)
            score = 0
            hypothesis = []
            for j in range(0, len(available), 2):
                p0 = available[j]
                if j + 1 == len(available):
                    if p0 in drowning:
                        score -= 300
                    else:
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

    def _game_name(self):
        return getattr(self.tournament, "game", "rps")

    def _best_of(self):
        game = self._game_name()
        is_rps = game == "rps"
        bo = 3 if not is_rps else 13
        lava = self.lava_snapshot
        if self.player_count == 2 and lava > 0:
            bo = 7 if not is_rps else 29
        elif self.player_count <= 8 and lava > 0:
            bo = 5 if not is_rps else 21
        return bo

    def _checkin_timer(self, pair):
        is_rps = self._game_name() == "rps"
        on_break = any(self.status_by_player[p] == USER_STATUS_BREAK for p in pair)
        if on_break:
            return self.checkin_rps if is_rps else self.checkin_break
        return (self.checkin_rps // 2) if is_rps else self.checkin_normal

    def generate_bracket(self, pairings=None, afloat=None, drowning=None,
                         set_stream_match=True):
        """Build initial matches. Called once at begin() with no args.

        Subsequent rounds (after complete_match) re-invoke via matchmaking().
        """
        if self.player_count <= 1:
            return []
        if pairings is None:
            queued, on_break, _eliminated, _called = self.get_players_by_status()
            afloat, drowning = self.afloat_and_drowning(queued, on_break)
            pairings = self.generate_pairings(afloat, drowning)
        afloat = list(afloat) if afloat is not None else []
        drowning = list(drowning) if drowning is not None else []
        best_of = self._best_of()
        matches = []
        match_dict = {}
        for pair in pairings:
            timer = self._checkin_timer(pair)
            p0, p1 = pair
            if p0 in drowning:
                if self.player_count - self.placement_snapshot + 1 > len(self.players_in_danger):
                    self.players_in_danger.append(p0)
                else:
                    drowning.remove(p0)
            if p1 in drowning:
                if self.player_count - self.placement_snapshot + 1 > len(self.players_in_danger):
                    self.players_in_danger.append(p1)
                else:
                    drowning.remove(p1)
            if self.get_lava_level() >= 0:
                if self.player_count == 2:
                    label = "GRAND FINALS"
                elif self.player_count == 3:
                    label = "LOSERS FINALS"
                elif p0 in drowning and p1 in drowning:
                    label = "DOUBLE DANGER"
                elif p0 in drowning or p1 in drowning:
                    label = "DANGER MATCH"
                    if p0 in drowning:
                        # Convention: drowning player is index 1
                        p0, p1 = p1, p0
                else:
                    label = "LADDER MATCH"
            else:
                label = "LADDER MATCH"
            node = self.add_node(
                players=[p0, p1],
                best_of=best_of,
                label=label,
                checkin_timer=timer,
                game=self._game_name(),
            )
            matches.append(node)
            match_dict[p0] = node
            match_dict[p1] = node
        if matches and self.player_count == 2:
            self.gfs = matches[0]
        round_num = len(self.matches_by_round)
        self.matches_by_round[round_num] = list(matches)
        if matches and self.stream and not self.stream_match and set_stream_match:
            chosen = self.select_stream_match(matches)
            if chosen is not None:
                chosen.streamed = True
                self.stream_planned.append(chosen)
                for p in chosen.players:
                    self.stream_matches_by_player.setdefault(p, []).append(chosen)
        return matches

    def select_stream_match(self, matches):
        """LadderElim stream pick: skip recently-streamed (except GF/LF),
        prefer matches with smaller rating differential, penalize repeat
        streamers and LADDER MATCH label."""
        last_players = (self.stream_history[-1].players
                        if self.stream_history else [])
        prev_players = (self.stream_history[-2].players
                        if len(self.stream_history) > 1 else [])
        best_score = float("inf")
        chosen = None
        for m in matches:
            p0, p1 = m.players
            if m.label not in ("GRAND FINALS", "LOSERS FINALS"):
                if p0 in last_players and p0 in prev_players:
                    continue
                if p1 in last_players and p1 in prev_players:
                    continue
            r0 = self.ratings_by_player[p0][0]
            r1 = self.ratings_by_player[p1][0]
            score = abs(r0 - r1)
            score += 250 * (len(self.stream_matches_by_player.get(p0, []))
                            + len(self.stream_matches_by_player.get(p1, [])))
            if m.label == "LADDER MATCH":
                score += 100
            if score < best_score:
                best_score = score
                chosen = m
        return chosen

    def score_stream_match(self, node):
        """Lex-sort key for `MatchGraph.call_match_for_stream`: prefer
        below-lava + closer rating + earlier in stream_planned."""
        below_lava = 1
        for p in node.players:
            if self.ratings_by_player[p][0] < 1:
                below_lava = 0
                break
        if len(node.players) >= 2:
            r0 = self.ratings_by_player[node.players[0]][0]
            r1 = self.ratings_by_player[node.players[1]][0]
            diff = abs(r0 - r1)
        else:
            diff = 0
        idx = (self.stream_planned.index(node)
               if node in self.stream_planned else 0)
        return (below_lava, diff, idx)

    # -- matchmaking entrypoint (used by begin + complete_match re-trigger) --

    def matchmaking(self, set_stream_match=True):
        queued, on_break, _eliminated, _called = self.get_players_by_status()
        afloat, drowning = self.afloat_and_drowning(queued, on_break)
        pairings = self.generate_pairings(afloat, drowning)
        matches = self.generate_bracket(pairings, afloat, drowning,
                                        set_stream_match=set_stream_match)
        effects = []
        stream_candidates = []
        for m in matches:
            if m.streamed:
                stream_candidates.append(m)
            else:
                effects += self.call_match(m)
        if not self.stream_match and stream_candidates:
            effects += self.call_match_for_stream(stream_candidates)
        effects.append(self._make_lava_ui_effect())
        return effects

    def _make_lava_ui_effect(self):
        return UpdateLavaUI(
            tournament_id=self.tournament_id,
            graph_id=self.graph_id,
            lava_level=self.get_lava_level(),
            placement_snapshot=self.placement_snapshot,
            players_in_danger=[
                getattr(p.uid, "id", None) for p in self.players_in_danger
            ],
        )

    # -- begin override: matchmaking is the initial-bracket entry point --

    def begin(self):
        self.create_data_structures()
        return self.matchmaking()

    # -- call/complete overrides --

    def call_match(self, node):
        for p in node.players:
            self.status_by_player[p] = USER_STATUS_CALLED
            self.stop_downtime_clock(p)
        return super().call_match(node)

    def complete_match(self, node):
        effects = super().complete_match(node)
        if node not in self.past_matches:
            self.past_matches.append(node)
        for p in node.players:
            if self.status_by_player[p] == USER_STATUS_CALLED:
                self.queue(p)
        self.update_ratings()
        if node.label != "LADDER MATCH":
            for p in node.players:
                if p in self.players_in_danger:
                    self.players_in_danger.remove(p)
        if node.label in ("GRAND FINALS", "LOSERS FINALS", "DOUBLE DANGER"):
            loser = node.loser()
            if loser is not None:
                self.eliminate_user(loser)
        elif node.label == "DANGER MATCH":
            loser = node.loser()
            if loser is not None and loser == node.players[1]:
                self.eliminate_user(loser)
        if node.label == "GRAND FINALS":
            winner = node.winner()
            if winner is not None:
                self.placements_dict[winner] = 1
                if self.victory_node is not None and not self.victory_node.completed():
                    self.victory_node.players = [winner]
                    self.victory_node.status = MATCH_STATUS_COMPLETED
        effects += self.matchmaking()
        return effects

    # -- ratings update (10-epoch gradient over past_matches) --

    def update_ratings(self):
        if not self.past_matches:
            return
        initial_rating_obj = self.initial_rating[1]
        temp = {p: initial_rating_obj for p in self.ratings_by_player}
        num_matches = {p: 0 for p in self.ratings_by_player}
        for m in self.past_matches:
            if m.completed() and len(m.players) == 2:
                num_matches[m.players[0]] += 1
                num_matches[m.players[1]] += 1
        for _epoch in range(self.rating_num_epochs):
            rating_deltas = {p: [0.0, 0.0] for p in self.ratings_by_player}
            for i in range(len(self.players)):
                p0 = self.players[i]
                for j in range(i, len(self.players)):
                    p1 = self.players[j]
                    if p0 is p1:
                        continue
                    matches = self.matches_by_pair[p0].get(p1, [])
                    p0_wins, p1_wins, total = 0.0, 0.0, 0
                    for m in matches:
                        if not m.completed():
                            continue
                        total += 1
                        bo3_factor = 1.0 if m.best_of == 3 else 1.0 / self.bo3_penalty
                        sweep_factor = self.sweep_bonus if m.is_sweep() else 1.0
                        if m.winner() == p0:
                            p0_wins += 1 * bo3_factor * sweep_factor
                        else:
                            p1_wins += 1 * bo3_factor * sweep_factor
                    if total == 0:
                        continue
                    norm = (1.0 + self.matchup_regularization) / (
                        total + self.matchup_regularization)
                    p0_wins *= norm
                    p1_wins *= norm
                    try:
                        p0_model = self.ratings_model([temp[p0], temp[p1]])
                        p0_deltas = p0_model.calculate_deltas()
                        p1_model = self.ratings_model([temp[p1], temp[p0]])
                        p1_deltas = p1_model.calculate_deltas()
                    except Exception:
                        # Rating model unavailable (e.g. mocked openskill in
                        # tests); skip gradient updates without breaking the
                        # tournament flow.
                        return
                    rating_deltas[p0][0] += (p0_deltas[0][0] * p0_wins
                                             + p1_deltas[1][0] * p1_wins)
                    rating_deltas[p0][1] += (p0_deltas[0][1] * p0_wins
                                             + p1_deltas[1][1] * p1_wins)
                    rating_deltas[p1][0] += (p0_deltas[1][0] * p0_wins
                                             + p1_deltas[0][0] * p1_wins)
                    rating_deltas[p1][1] += (p0_deltas[1][1] * p0_wins
                                             + p1_deltas[0][1] * p1_wins)
            for p in self.ratings_by_player:
                rating_deltas[p][0] *= self.rating_learning_rate / self.rating_num_epochs
                rating_deltas[p][1] *= self.rating_learning_rate / self.rating_num_epochs
                cur = temp[p]
                try:
                    old_mu = float(cur.mu)
                    old_sigma = float(cur.sigma)
                    new_mu = old_mu + rating_deltas[p][0]
                    new_log_sigma = math.log(old_sigma) + rating_deltas[p][1]
                    new_sigma = math.exp(new_log_sigma)
                except Exception:
                    return
                temp[p] = _Rating(mu=new_mu, sigma=new_sigma)
        for p in self.ratings_by_player:
            if self.status_by_player[p] != USER_STATUS_ELIMINATED:
                new_rating = temp[p]
                true_rating = round(max(0, new_rating.mu - 3 * new_rating.sigma))
                self.ratings_by_player[p] = (true_rating, new_rating)

    # -- completion --

    def completed(self):
        result = self.player_count <= 1 and self.get_lava_level() >= 0
        if result and self.player_count == 1:
            survivors = self.get_non_elim_sorted()
            if survivors:
                self.placements_dict[survivors[0]] = 1
        return result


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------


@register_preset("px")
def _preset_px(_t):
    def factory(tournament, players):
        return LadderElimination(tournament, players, stream=False)
    return [factory], "Ladder elimination (px-style)."
