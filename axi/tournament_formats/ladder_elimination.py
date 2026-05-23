"""LadderElimination — rising-lava tournament format ('px' preset).

Phase 5b: thin subclass of `Ladder` (Phase 5a refactored) that adds
the lava elimination mechanic. Inherits all matchmaking, streaming,
per-match bookkeeping, MatchNode usage, and time_fn injection from
Ladder. Overrides only the lava-specific lifecycle:

  - Lava timer + Fibonacci placement_tiers + afloat/drowning partition.
  - 5 match-label state machine: LADDER MATCH / DANGER MATCH (drowning
    at idx 1) / DOUBLE DANGER / LOSERS FINALS (count==3) / GRAND FINALS
    (count==2).
  - Escalating best_of: bo3 default → bo5 (count<=8 post-lava) → bo7
    (count==2 post-lava). RPS variant: 13/21/29.
  - Checkin timer: 360s normal / 480s on break / 240s RPS on break /
    120s RPS normal.
  - 10-epoch gradient `update_ratings` (overrides Ladder's per-match).
  - `eliminate_user`, `USER_STATUS_ELIMINATED`.
  - `UpdateLavaUI` effect from matchmaking.
  - `add_new_player` gated on `lava_level < initial_rating[0]`.
  - `completed()` overrides to `player_count <= 1 and lava >= 0`.
  - `select_stream_match` adds the source's LADDER MATCH penalty (+100).
"""

import math

from axi.effects import UpdateLavaUI
from axi.ladder import Ladder
from axi.match_node import MatchNode
from axi.tournament_presets import register_preset
from axi.util import (
    MATCH_STATUS_COMPLETED,
    USER_STATUS_BREAK,
    USER_STATUS_CALLED,
    USER_STATUS_ELIMINATED,
    USER_STATUS_QUEUED,
)


# Bring in or define the rating helpers. _Rating is needed by tests and
# also as the safe fallback when openskill is mocked.
class _Rating:
    """Minimal mu/sigma rating compatible with openskill/glicko interface."""
    def __init__(self, mu=300.0, sigma=100.0):
        self.mu = mu
        self.sigma = sigma


class _ElementaryRatingModel:
    """Deterministic 2-player rating model for tests."""

    def __init__(self, match_ratings):
        self.match_ratings = match_ratings

    def calculate_deltas(self):
        # [winner_at_idx0, loser_at_idx1]: winner +1 mu, loser -1 mu.
        return [[1.0, -0.01], [-1.0, -0.01]]


class LadderElimination(Ladder):
    """Rising-lava elimination ladder. Tournament-format subclass of Ladder.

    Constructor: `(tournament, players, stream=False, lava_delay=150,
    lava_rate=1/6, ...)`. See Phase 5b design doc for the full param list.
    """

    def __init__(self, tournament, players, stream=False,
                 lava_delay=150, lava_rate=1 / 6,
                 rating_model="openskill",
                 initial_rating_override=None,
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
        super().__init__(
            tournament=tournament,
            players=list(players),
            streamed=stream,
            time_fn=time_fn,
        )
        self.lava_delay = lava_delay
        self.lava_rate = lava_rate
        self._rating_model_name = rating_model
        self._initial_rating_override = initial_rating_override
        self.matchmaking_num_hypotheses = matchmaking_num_hypotheses
        self.rating_num_epochs = rating_num_epochs
        self.rating_learning_rate = rating_learning_rate
        self.sweep_bonus = sweep_bonus
        self.bo3_penalty = bo3_penalty
        self.matchup_regularization = matchup_regularization
        self.checkin_normal = checkin_normal
        self.checkin_break = checkin_break
        self.checkin_rps = checkin_rps

    def __repr__(self):
        return "LADDER ELIMINATION"

    # Override Ladder's read-only player_count property with a settable
    # attribute. Eliminations decrement this counter without removing
    # players from self.players.
    @property
    def player_count(self):
        return getattr(self, "_player_count", len(self.players))

    @player_count.setter
    def player_count(self, value):
        self._player_count = value

    # -- data structures --

    def create_data_structures(self):
        super().create_data_structures()
        # Override Ladder's rating model resolution with our own.
        initial_rating, model_cls = _resolve_rating_model(self._rating_model_name)
        self.initial_rating = self._initial_rating_override or initial_rating
        self.ratings_model = model_cls
        self.ratings_by_player = {p: self.initial_rating for p in self.players}

        # Lava-specific state.
        self.lava_start_time = self._now()
        self.player_count = len(self.players)
        self.lava_snapshot = -1
        self.placement_snapshot = -1
        self.players_in_danger = []
        self.placement_tiers = [1, 2]
        self.update_placement_tiers()

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
        non_elim = [p for p in self.players
                    if self.status_by_player[p] != USER_STATUS_ELIMINATED]
        non_elim.sort(key=lambda p: -self.ratings_by_player[p][0])
        return non_elim

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
        # Late-join: only allow before lava reaches initial-rating floor.
        if self.get_lava_level() >= self.initial_rating[0]:
            return False
        result = super().add_new_player(user)
        if result:
            self.player_count += 1
            self.update_placement_tiers()
        return result

    # -- at-risk / afloat-and-drowning --

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
        if (self.player_count == self.placement_snapshot
                and len(at_risk) == 1):
            non_elim = self.get_non_elim_sorted()
            if len(non_elim) >= 2:
                bottom_breaker = non_elim[-2]
                if bottom_breaker in breakers:
                    afloat.append(bottom_breaker)
        return afloat, drowning

    # -- pairings + bracket --

    def generate_pairings(self, afloat, drowning=None):
        """LadderElim variant: drowning-aware. When called from
        super().matchmaking() with `available=afloat+drowning`, the
        drowning arg is None — fall back to no-drowning behavior."""
        if drowning is None:
            return super().generate_pairings(afloat)
        available = list(afloat) + list(drowning)
        if self.get_lava_level() >= 0 and len(available) == self.player_count <= 3:
            if len(drowning) >= 2:
                return [(drowning[0], drowning[1])]
            return []
        best_score = 0
        best_hypothesis = []
        from axi.util import rng
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

    def _best_of(self):
        is_rps = self.game == "rps"
        bo = 3 if not is_rps else 13
        lava = self.lava_snapshot
        if self.player_count == 2 and lava > 0:
            bo = 7 if not is_rps else 29
        elif self.player_count <= 8 and lava > 0:
            bo = 5 if not is_rps else 21
        return bo

    def _checkin_timer(self, pair):
        is_rps = self.game == "rps"
        on_break = any(self.status_by_player[p] == USER_STATUS_BREAK for p in pair)
        if on_break:
            return self.checkin_rps if is_rps else self.checkin_break
        return (self.checkin_rps // 2) if is_rps else self.checkin_normal

    def generate_bracket_for(self, pairings, afloat, drowning, set_stream_match=True):
        """Build MatchNodes for the given pairings. Mirrors
        Ladder.generate_match_nodes but adds lava-driven label/bo/timer."""
        if self.player_count <= 1:
            return []
        afloat = list(afloat)
        drowning = list(drowning)
        best_of = self._best_of()
        matches = []
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
                        p0, p1 = p1, p0  # convention: drowning at idx 1
                else:
                    label = "LADDER MATCH"
            else:
                label = "LADDER MATCH"
            node = self.add_node(
                players=[p0, p1],
                best_of=best_of,
                label=label,
                checkin_timer=timer,
                game=self.game,
            )
            matches.append(node)
        round_num = len(self.matches_by_round)
        self.matches_by_round[round_num] = list(matches)
        if matches and self.streamed and not self.stream_match and set_stream_match:
            chosen = self.select_stream_match(matches)
            if chosen is not None:
                chosen.streamed = True
                self.stream_planned.append(chosen)
                for p in chosen.players:
                    self.stream_matches_by_player.setdefault(p, []).append(chosen)
        return matches

    def select_stream_match(self, nodes):
        """LadderElim stream pick: source's heuristic with LADDER MATCH penalty."""
        last_players = (self.stream_history[-1].players
                        if self.stream_history else [])
        prev_players = (self.stream_history[-2].players
                        if len(self.stream_history) > 1 else [])
        best_score = float("inf")
        chosen = None
        for m in nodes:
            p0, p1 = m.players[0], m.players[1]
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

    # -- matchmaking entry point (no args; drives the lava loop) --

    def matchmaking(self, *args, set_stream_match=True):
        """LadderElim's matchmaking: derives pairings from afloat/drowning
        and emits UpdateLavaUI. The base Ladder.matchmaking takes
        explicit pairings — LadderElim overrides to derive them.

        Returns (nodes, effects). The args are accepted but ignored to
        keep the Ladder caller-shape compatible.
        """
        queued, on_break, _eliminated, _called = self.get_players_by_status()
        afloat, drowning = self.afloat_and_drowning(queued, on_break)
        pairings = self.generate_pairings(afloat, drowning)
        matches = self.generate_bracket_for(
            pairings, afloat, drowning, set_stream_match=set_stream_match)
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
        return matches, effects

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

    # -- begin: matchmaking is the initial-bracket entry point --

    def begin(self):
        self.create_data_structures()
        _matches, effects = self.matchmaking()
        return effects

    # -- complete_match: add elimination + lava-driven rematchmaking --

    def complete_match(self, node):
        # Inline the Ladder.complete_match logic but skip its
        # autoqueue-based re-routing (we have our own state machine).
        if not node.completed():
            return []
        # NB: we call update_ratings ourselves (the 10-epoch override).
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
            if self.status_by_player.get(player) == USER_STATUS_CALLED:
                # Default: re-queue. Eliminations below override.
                self.queue(player)
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
        # Re-run matchmaking (lava may have shifted).
        _matches, more_effects = self.matchmaking()
        return more_effects

    # -- 10-epoch gradient update_ratings (overrides Ladder's per-match) --

    def update_ratings(self, *args):
        if not self.past_matches:
            return
        initial_rating_obj = self.initial_rating[1]
        temp = {p: initial_rating_obj for p in self.ratings_by_player}
        for _epoch in range(self.rating_num_epochs):
            rating_deltas = {p: [0.0, 0.0] for p in self.ratings_by_player}
            for i in range(len(self.players)):
                p0 = self.players[i]
                for j in range(i, len(self.players)):
                    p1 = self.players[j]
                    if p0 is p1:
                        continue
                    pair_matches = self.matches_by_pair[p0].get(p1, [])
                    p0_wins, p1_wins, total = 0.0, 0.0, 0
                    for m in pair_matches:
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

    # -- completed: player_count <= 1 + lava >= 0 --

    def completed(self):
        result = self.player_count <= 1 and self.get_lava_level() >= 0
        if result and self.player_count == 1:
            survivors = self.get_non_elim_sorted()
            if survivors:
                self.placements_dict[survivors[0]] = 1
        return result


def _resolve_rating_model(name):
    """Return (initial_rating, model_cls) for a rating-model name."""
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


@register_preset("px")
def _preset_px(_t):
    def factory(tournament, players):
        return LadderElimination(tournament, players, stream=False)
    return [factory], "Ladder elimination (px-style)."
