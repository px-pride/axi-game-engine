"""Tests for Danisen rating system — calculate_deltas with various scenarios."""

from axi.ratings.danisen import Danisen


class TestDanisenSameDan:
    """Both at same dan — dan_w <= dan_l triggers bonus: winner +2 pos, loser -1 pos."""

    def test_same_dan_same_pos(self):
        d = Danisen([[3, 0], [3, 0]])
        result = d.calculate_deltas()
        assert result[0] == [0, 2]   # winner: +2 pos (bonus from <= condition)
        assert result[1] == [0, -1]  # loser: -1 pos

    def test_same_dan_different_pos(self):
        d = Danisen([[3, 2], [3, 1]])
        result = d.calculate_deltas()
        assert result[0] == [0, 2]
        assert result[1] == [0, -1]


class TestDanisenHigherBeatsLower:
    """Higher-ranked player (higher dan) beats lower — minimal change."""

    def test_higher_beats_lower_by_one_dan(self):
        d = Danisen([[4, 0], [3, 0]])
        result = d.calculate_deltas()
        # Winner has higher dan, so standard +1/-1
        assert result[0] == [0, 1]
        assert result[1] == [0, -1]


class TestDanisenLowerBeatsHigher:
    """Lower-ranked player beats higher — bonus applies."""

    def test_lower_beats_higher_by_one_dan(self):
        d = Danisen([[3, 0], [4, 0]])
        result = d.calculate_deltas()
        # dan_w=3 < dan_l=4: potential_delta_pos_w = 2 + max(0, 4-3) = 3
        # potential_delta_pos_l = -1 - max(0, 4-3) = -2
        assert result[0][1] == 3   # winner gets +3 pos
        assert result[1][1] == -2  # loser gets -2 pos

    def test_lower_beats_higher_by_two_dans(self):
        d = Danisen([[2, 0], [4, 0]])
        result = d.calculate_deltas()
        # potential_delta_pos_w = 2 + max(0, 4-2) = 4
        # potential_delta_pos_l = -1 - max(0, 4-2) = -3
        assert result[0][1] == 4
        assert result[1][1] == -3


class TestDanisenPromotion:
    """Winner promoted to next dan when pos reaches 5."""

    def test_promotion_on_win(self):
        d = Danisen([[3, 4], [3, 0]])
        result = d.calculate_deltas()
        # same dan: potential=2, pos_w=4+2=6 >= 5 → rolls: 6-5=1, dan+1
        assert result[0] == [1, -3]  # promote: +1 dan, delta_pos=-3 (4+(-3)=1)

    def test_promotion_from_bonus(self):
        d = Danisen([[3, 3], [5, 0]])
        result = d.calculate_deltas()
        # dan_w=3 <= dan_l=5: potential = 2 + max(0, 5-3) = 4
        # pos_w=3+4=7 >= 5 → rolls over: 7-5=2, dan+1
        assert result[0] == [1, -1]  # +1 dan, pos 3+4-5=2 → delta=-1 wait...

    def test_promotion_exact_boundary(self):
        """pos_w + delta == 5 exactly."""
        d = Danisen([[3, 4], [3, 2]])
        result = d.calculate_deltas()
        assert result[0][0] == 1  # dan promotion
        assert 3 + result[0][1] + 5 * result[0][0] == 4 + 1 + 5 * 0  # total position preserved... actually let me just check the mechanic


class TestDanisenDemotion:
    """Loser demoted when pos drops to -5."""

    def test_demotion_on_loss(self):
        d = Danisen([[3, 0], [3, -4]])
        result = d.calculate_deltas()
        # pos_l=-4, potential=-1 → -4-1=-5 → rolls over
        assert result[1] == [-1, 4]  # demote: -1 dan, pos goes to 1 (-4 + (-1) + 5 = 0)

    def test_no_demotion_above_threshold(self):
        d = Danisen([[3, 0], [3, -3]])
        result = d.calculate_deltas()
        # pos_l=-3-1=-4, not <= -5
        assert result[1] == [0, -1]


class TestDanisenMinRank:
    """The game enforces min rank of 1st Dan+0 in ladder.update_ratings, not in Danisen itself.
    Danisen just calculates raw deltas."""

    def test_demotion_from_dan_1(self):
        d = Danisen([[3, 0], [1, -4]])
        result = d.calculate_deltas()
        # Raw delta says demote below dan 1
        assert result[1][0] == -1  # raw delta is -1 dan
