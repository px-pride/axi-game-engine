import math
from typing import Callable

class Danisen:
    def __init__(self, match_ratings):
        self.match_ratings = match_ratings

    def calculate_deltas(self):
        dan_w = self.match_ratings[0][0]
        pos_w = self.match_ratings[0][1]
        dan_l = self.match_ratings[1][0]
        pos_l = self.match_ratings[1][1]

        delta_dan_w = 0
        delta_pos_w = 0
        delta_dan_l = 0
        delta_pos_l = 0

        potential_delta_pos_w = 1
        potential_delta_pos_l = -1
        if dan_w <= dan_l:
            potential_delta_pos_w = 2 + max(0, dan_l - dan_w)
            potential_delta_pos_l = -2 - max(0, dan_l - dan_w)
        if pos_w + potential_delta_pos_w > 4:
            delta_dan_w += 1
            delta_pos_w = -pos_w
        else:
            delta_pos_w += potential_delta_pos_w
        if pos_l + potential_delta_pos_l < -4:
            delta_dan_l -= 1
            delta_pos_l = -pos_l
        else:
            delta_pos_l -= potential_delta_pos_w

        result = [[delta_dan_w, delta_pos_w], [delta_dan_l, delta_pos_l]]
        return result
