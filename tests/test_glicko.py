"""Tests for GlickoTimeless rating system — calculate_deltas basic properties."""

import math
from unittest.mock import MagicMock


class FakeRating:
    """Minimal stand-in for openskill.Rating with .mu and .sigma."""
    def __init__(self, mu, sigma):
        self.mu = mu
        self.sigma = sigma


class TestGlickoTimelessBasic:

    def _calc(self, mu_w, sigma_w, mu_l, sigma_l, time_decay=0):
        from axi.ratings.glicko_timeless import GlickoTimeless
        r_w = FakeRating(mu_w, sigma_w)
        r_l = FakeRating(mu_l, sigma_l)
        gt = GlickoTimeless([r_w, r_l])
        return gt.calculate_deltas(time_decay=time_decay)

    def test_winner_gains_rating(self):
        result = self._calc(300, 100, 300, 100)
        assert result[0][0] > 0  # winner delta_mu > 0

    def test_loser_loses_rating(self):
        result = self._calc(300, 100, 300, 100)
        assert result[1][0] < 0  # loser delta_mu < 0

    def test_sigma_decreases_for_both(self):
        """After a match, uncertainty (sigma) should decrease for both players."""
        result = self._calc(300, 100, 300, 100)
        # delta_log_sigma should be negative (sigma shrinks)
        assert result[0][1] < 0
        assert result[1][1] < 0

    def test_equal_players_symmetric_magnitude(self):
        """Equal-rated players: winner gains same magnitude as loser loses."""
        result = self._calc(300, 100, 300, 100)
        assert abs(result[0][0] + result[1][0]) < 0.01

    def test_upset_gives_bigger_change(self):
        """Lower-rated player beating higher-rated should produce bigger deltas."""
        normal = self._calc(500, 100, 300, 100)   # favorite wins
        upset = self._calc(300, 100, 500, 100)     # underdog wins
        assert abs(upset[0][0]) > abs(normal[0][0])

    def test_high_sigma_larger_change(self):
        """Player with higher sigma (more uncertain) should change more."""
        low_sigma = self._calc(300, 50, 300, 100)
        high_sigma = self._calc(300, 150, 300, 100)
        assert abs(high_sigma[0][0]) > abs(low_sigma[0][0])

    def test_returns_two_element_list(self):
        result = self._calc(300, 100, 300, 100)
        assert len(result) == 2
        assert len(result[0]) == 2
        assert len(result[1]) == 2

    def test_no_nan_or_inf(self):
        result = self._calc(300, 100, 300, 100)
        for pair in result:
            for val in pair:
                assert not math.isnan(val)
                assert not math.isinf(val)
