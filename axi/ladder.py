from time import time
from math import log, exp
from copy import copy
from numpy import abs
from openskill import Rating
from pytimeparse.timeparse import timeparse

from axi.util import rng, MATCH_STATUS_CALLED, USER_STATUS_QUEUED, USER_STATUS_BREAK, USER_STATUS_CALLED
from axi.ratings.plackett_luce_extended import PlackettLuceExtended
from axi.ratings.glicko_timeless import GlickoTimeless
from axi.ratings.danisen import Danisen
import axi.handlers.ladder_handler as ladder_handler
import axi.handlers.match_handler as match_handler
import axi.handlers.discord_handler as discord_handler

class Ladder:
    def __init__(self, guild, config, scheduled_event, streamed=False):
        self.rowid = None
        self.guild = guild
        self.config = config
        self.name = config["name"]
        self.game = config["game"]
        self.fmt = config["format"]
        self.queue_channel = config["queue-channel"]
        self.status_channel = config["status-channel"]
        self.results_channel = config["results-channel"]
        self.leaderboard_channel = config["leaderboard-channel"]
        self.duration = timeparse(config["duration"])
        self.scheduled_event = scheduled_event
        self.streamed = streamed
        self.players = []
        self.status_message = None
        self.leaderboard_message = None

    def get_db_entry(self):
        return [
            self.guild.id,
            self.name,
            self.game,
            self.fmt,
        ]

    def create_data_structures(self):
        self.matches_by_pair = {p: {q: [] for q in self.players} for p in self.players}
        self.matches_by_player = {p: [] for p in self.players}
        self.current_match_by_player = {p: None for p in self.players}
        self.status_by_player = {p: USER_STATUS_QUEUED for p in self.players}
        self.stream_matches_by_player = {p: [] for p in self.players}
        self.stream_history = []  # strictly ordered
        self.stream_planned = []  # not strictly ordered
        self.stream_candidates = []
        self.stream_match = None
        self.autoqueue_by_player = {p: False for p in self.players}

        self.active_matches = []  # graph nodes of matches being waited on
        self.called_matches = []
        self.past_matches = []

        self.initial_rating_glicko = (0, Rating(mu=300, sigma=100))  # (mean - 2*stdev), (mean, stdev)
        self.initial_rating_openskill = (0, Rating(mu=300, sigma=100))  # (mean - 2*stdev), (mean, stdev)
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
        ladder_handler.update_ratings_db(self, self.players)

        current_time = time()
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
        rating = ladder_handler.load_from_ratings_db(self, p)
        if rating:
            return rating
        return self.initial_rating

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
        ladder_handler.update_ratings_db(self, [user])
        self.stream_matches_by_player[user] = []
        self.status_by_player[user] = USER_STATUS_BREAK
        self.start_downtime_clock(user)
        self.downtime_clock_by_player[user] -= 20.0
        self.challenge_requests[user] = []
        self.autoqueue_by_player[user] = False
        return True

    def start_downtime_clock(self, user):
        self.downtime_clock_by_player[user] = time()
        self.downtime_by_player[user] = 0.0

    def query_downtime_clock(self, user):
        time_passed = time() - self.downtime_clock_by_player[user]
        return time_passed

    def stop_downtime_clock(self, user):
        if self.status_by_player[user] not in [USER_STATUS_QUEUED, USER_STATUS_BREAK]:
            time_passed = time() - self.downtime_clock_by_player[user]
            if time_passed > 0:
                self.downtime_by_player[user] += time_passed

    def score_stream_match(self, match):
        p0 = match.players[0]
        p1 = match.players[1]
        return abs(self.ratings_by_player[p0][0] - self.ratings_by_player[p1][0])

    def cancel_match(self, match):
        if match == self.stream_match:
            self.stream_match = None
        if match in self.stream_planned:
            self.stream_planned.remove(match)
        if match in self.get_active_matches():
            self.get_active_matches().remove(match)
        if match in self.get_called_matches():
            self.get_called_matches().remove(match)
        a, b = match.players
        self.matches_by_pair[a][b].remove(match)
        self.matches_by_pair[b][a].remove(match)
        self.matches_by_player[a].remove(match)
        self.matches_by_player[b].remove(match)
        self.current_match_by_player[a] = None
        self.current_match_by_player[b] = None
        if self.status_by_player[a] == USER_STATUS_CALLED:
            self.queue(a)
        if self.status_by_player[b] == USER_STATUS_CALLED:
            self.queue(b)

    def completed(self):
        return time() >= self.end_time

    def queue(self, user):
        self.status_by_player[user] = USER_STATUS_QUEUED
        self.start_downtime_clock(user)

    def dequeue(self, user):
        self.status_by_player[user] = USER_STATUS_BREAK
        self.start_downtime_clock(user)

    def advance(self, match):
        if not match.check_match_over():
            return
        self.update_ratings(match)
        self.past_matches.append(match)
        if match == self.stream_match:
            self.stream_match = None
        if match in self.stream_planned:
            self.stream_planned.remove(match)
        if match in self.get_active_matches():
            self.get_active_matches().remove(match)
        if match in self.get_called_matches():
            self.get_called_matches().remove(match)
        for player in match.players:
            current_for = self.current_match_by_player[player]
            if current_for and current_for.check_match_over():
                self.current_match_by_player[player] = None
            if self.status_by_player[player] != USER_STATUS_BREAK and self.autoqueue_by_player[player]:
                self.queue(player)
            else:
                self.dequeue(player)

    def abort(self, match):
        if match == self.stream_match:
            self.stream_match = None
        if match in self.stream_planned:
            self.stream_planned.remove(match)
        if match in self.get_active_matches():
            self.get_active_matches().remove(match)
        if match in self.get_called_matches():
            self.get_called_matches().remove(match)
        for player in match.players:
            self.current_match_by_player[player] = None
            if self.status_by_player[player] != USER_STATUS_BREAK and self.autoqueue_by_player[player]:
                self.queue(player)
            else:
                self.dequeue(player)

    def get_sorted_ratings(self):
        sorted_ratings = []
        for p in self.players:
            sorted_ratings.append(p)
        sorted_ratings.sort(key=lambda x: -self.ratings_by_player[x][0])
        return sorted_ratings

    def get_players_by_status(self):
        queued_players = []
        break_players = []
        called_players = []
        for p in self.players:
            if self.status_by_player[p] == USER_STATUS_QUEUED:
                queued_players.append(p)
            elif self.status_by_player[p] == USER_STATUS_BREAK:
                break_players.append(p)
            elif self.status_by_player[p] == USER_STATUS_CALLED:
                called_players.append(p)
        return queued_players, break_players, called_players

    def begin(self):
        self.create_data_structures()

    def matchmaking(self, basic_pairings, challenge_pairings, set_stream_match=True):
        matches_to_call = self.generate_match_nodes(basic_pairings, challenge_pairings, set_stream_match)
        stream_candidates = []
        for m in matches_to_call:
            if m.streamed:
                stream_candidates.append(m)
            else:
                self.call_match(m)
        if not self.stream_match:
            self.call_match_for_stream(stream_candidates)
        return matches_to_call

    def generate_match_nodes(self, basic_pairings, challenge_pairings, set_stream_match=True):
        if self.player_count == 1:
            return []
        best_of = 3
        matches = []
        match_dict = dict()
        pairings = basic_pairings + challenge_pairings
        for pair in pairings:
            timer = 120
            label = "LADDER MATCH"
            if pair in challenge_pairings:
                label = "CHALLENGE MATCH"
            m = match_handler.launch_match(
                self.game, pair, mode="versus", ladder=self, best_of=best_of, checkin_timer=timer, label=label)
            matches.append(m)
            match_dict[pair[0]] = m
            match_dict[pair[1]] = m
        stream_match = None
        if set_stream_match and self.streamed and not self.stream_match:
            stream_match = self.select_stream_match(matches)
        if stream_match:
            stream_match.streamed = True
            self.stream_planned.append(stream_match)
            for p in stream_match.players:
                self.stream_matches_by_player[p].append(stream_match)
        return matches

    def select_stream_match(self, matches):
        stream_match = None
        last_streamed_players = self.stream_history[-1].players if len(self.stream_history) > 0 else []
        second_last_streamed_players = self.stream_history[-2].players if len(self.stream_history) > 1 else []
        best_score = 9999999
        for m in matches:
            p0 = m.players[0]
            p1 = m.players[1]
            if p0 in last_streamed_players and p0 in second_last_streamed_players:
                continue
            if p1 in last_streamed_players and p1 in second_last_streamed_players:
                continue
            score = abs(self.ratings_by_player[p0][0] - self.ratings_by_player[p1][0])
            score += 250 * (len(self.stream_matches_by_player[p0]) + len(self.stream_matches_by_player[p1]))
            if score < best_score:
                best_score = score
                stream_match = m
        return stream_match

    def call_match(self, match):
        for p in match.players:
            self.status_by_player[p] = USER_STATUS_CALLED
            self.stop_downtime_clock(p)
        a, b = match.players
        self.current_match_by_player[a] = match
        self.current_match_by_player[b] = match
        if match not in self.matches_by_pair[a][b]:
            self.matches_by_pair[a][b].append(match)
        if match not in self.matches_by_pair[b][a]:
            self.matches_by_pair[b][a].append(match)
        if match not in self.matches_by_player[a]:
            self.matches_by_player[a].append(match)
        if match not in self.matches_by_player[b]:
            self.matches_by_player[b].append(match)
        self.called_matches.append(match)

    def update_ratings(self, m_):
        if not self.ratings_model:
            return
        p0 = m_.winner()
        p1 = m_.players[1] if p0 == m_.players[0] else m_.players[0]
        p0_rating = self.ratings_by_player[p0]
        p1_rating = self.ratings_by_player[p1]
        delta_result = self.ratings_model([p0_rating, p1_rating]).calculate_deltas()
        self.ratings_by_player[p0] = (
                self.ratings_by_player[p0][0] + delta_result[0][0],
                self.ratings_by_player[p0][1] + delta_result[0][1],
        )
        self.ratings_by_player[p1] = (
                self.ratings_by_player[p1][0] + delta_result[1][0],
                self.ratings_by_player[p1][1] + delta_result[1][1],
        )
        ladder_handler.update_ratings_db(self, [p0, p1])

    def generate_pairings(self, available):
        best_score = 0
        best_hypothesis = []
        for i in range(self.matchmaking_num_hypotheses):
            rng.shuffle(available)
            score = 0
            hypothesis = []
            for j in range(0, len(available), 2):
                p0 = available[j]
                if j + 1 == len(available):
                    score += self.ratings_by_player[p0][0]
                    continue
                p1 = available[j+1]
                viable = not self.matches_by_pair[p0][p1]
                if not viable:
                    most_recently_played = p1 in self.matches_by_player[p0][-1].players
                    most_recently_played = most_recently_played and p0 in self.matches_by_player[p1][-1].players
                    most_recently_played = most_recently_played and self.player_count > 2
                    if not most_recently_played:
                        late_stage = len(self.matches_by_player[p0]) >= min(6, self.player_count - 1)
                        late_stage = len(self.matches_by_player[p1]) >= min(6, self.player_count - 1) and late_stage
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

    def get_matches_by_pair(self, user0, user1):
        if user0 in self.matches_by_pair and user1 in self.matches_by_pair[user0]:
            return self.matches_by_pair[user0][user1]
        return None

    def is_user_in_match(self, user):
        m = self.get_current_match_by_player(user)
        return m and not m.check_match_over()

    def are_users_in_match(self, user0, user1):
       m = self.get_current_match_by_player(user0)
       return user1 in m.players

    def get_matches_by_player(self, user):
        return self.matches_by_player[user]

    def get_current_match_by_player(self, user):
        return self.current_match_by_player[user]

    def get_active_matches(self):
        return self.active_matches

    def get_called_matches(self):
        return self.called_matches

    def clear_called_matches(self):
        self.called_matches.clear()

    def get_opponent(self, user):
        match = self.get_current_match_by_player(user)
        if user == match.players[0]:
            return match.players[1]
        return match.players[0]

    def checkin_user_for_match(self, user):
        match = self.get_current_match_by_player(user)
        checkin = True#(match.status == MATCH_STATUS_CALLED) and (user not in match.checkins)
        if True:#match.checkin_user(user):
            self.active_matches.append(match)
            self.called_matches.remove(match)
        return match, checkin

    def call_match_for_stream(self, matches):
        best_score = (999999,)
        best_match = None
        for m in self.stream_planned:
            score = self.score_stream_match(m)
            if score < best_score:
                best_score = score
                best_match = m
        if best_match in self.stream_planned:
            self.stream_match = best_match
            self.stream_planned.remove(best_match)
            self.stream_history.append(self.stream_match)
            self.call_match(self.stream_match)

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

