import math
from typing import Callable

from openskill.constants import Constants
from openskill.util import gamma, util_a, util_c, util_sum_q

from openskill.models.plackett_luce import PlackettLuce
from openskill.rate import team_rating

class PlackettLuceExtended(PlackettLuce):
    def __init__(self, match_ratings):
        match_ratings = [[match_ratings[0]], [match_ratings[1]]]
        super().__init__(match_ratings, team_rating)

    def calculate_deltas(self):
        result = []
        for i, i_team_ratings in enumerate(self.team_ratings):
            omega = 0
            delta = 0
            i_mu, i_sigma_squared, i_team, i_rank = i_team_ratings
            i_mu_over_ce = math.exp(i_mu / self.c)
            for q, q_team_ratings in enumerate(self.team_ratings):
                q_mu, q_sigma_squared, q_team, q_rank = q_team_ratings
                i_mu_over_ce_over_sum_q = i_mu_over_ce / self.sum_q[q]
                if q_rank <= i_rank:
                    delta += (
                        i_mu_over_ce_over_sum_q
                        * (1 - i_mu_over_ce_over_sum_q)
                        / self.a[q]
                    )
                    if q == i:
                        omega += (1 - i_mu_over_ce_over_sum_q) / self.a[q]
                    else:
                        omega -= i_mu_over_ce_over_sum_q / self.a[q]
            omega *= i_sigma_squared / self.c
            delta *= i_sigma_squared / self.c**2
            gamma = self.gamma(self.c, len(self.team_ratings), *i_team_ratings)
            delta *= gamma
            j_players = i_team[0]
            mu = j_players.mu
            sigma = j_players.sigma
            delta_mu = (sigma**2 / i_sigma_squared) * omega
            delta_log_sigma = 0.5 * math.log(
                max(1 - (sigma**2 / i_sigma_squared) * delta, self.EPSILON),
            )
            intermediate_result_per_team = [delta_mu, delta_log_sigma]
            result.append(intermediate_result_per_team)
        return result
