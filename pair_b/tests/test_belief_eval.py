"""Scoring helpers for the belief network (D6): the paired interval resamples whole games."""
import numpy as np
import pytest

pytest.importorskip("torch")  # belief_eval needs torch; Intel Macs have none: skip this file there

from pairb.belief_eval import paired_difference


# Catches: an interval that treats beliefs from one game as independent draws, so it comes out too
# narrow when they are correlated (Teal on #6).
def test_the_interval_resamples_whole_games():
    a, b = np.array([1.0] * 100 + [-1.0] * 100), np.zeros(200)
    by_game = paired_difference(a, b, np.array(["g1"] * 100 + ["g2"] * 100), n_boot=2000, seed=0)
    assert by_game["mean"] == 0 and by_game["games"] == 2 and by_game["beliefs"] == 200
    assert by_game["ci95"][1] - by_game["ci95"][0] > 1.5  # two games: the mean can be -1, 0 or +1
    each_its_own = paired_difference(a, b, np.array([f"g{i}" for i in range(200)]), n_boot=2000, seed=0)
    assert each_its_own["ci95"][1] - each_its_own["ci95"][0] < 0.5


# Catches: board errors not weighted by each board's hypothesis weight, rule-decided boards
# counted in them, or the position value not being the weighted mean of the boards' values.
def test_errors_weight_boards_and_score_each_position_as_their_weighted_mean():
    import numpy as np
    from pairb.belief_eval import errors
    arrays = {"belief": np.array([0, 0, 1, 1]), "y": np.array([0.4, -0.2, 0.6, 1.0]),
              "weight": np.array([0.25, 0.75, 0.5, 0.5]), "rule": np.array([False, False, False, True]),
              "root": np.array([0.25 * 0.4 + 0.75 * -0.2, 0.5 * 0.6 + 0.5 * 1.0])}
    pred = np.array([0.6, -0.1, 0.2, 0.0])  # the rule-decided board keeps its rule value, 1.0
    metrics, root_err = errors(pred, arrays, np.array([0, 1]))
    assert metrics["board_mae"] == pytest.approx((0.25 * 0.2 + 0.75 * 0.1 + 0.5 * 0.4) / 1.5, abs=1e-6)
    assert metrics["board_mse"] == pytest.approx((0.25 * 0.04 + 0.75 * 0.01 + 0.5 * 0.16) / 1.5, abs=1e-6)
    assert root_err == pytest.approx([0.125, 0.2])  # |0.075 - (-0.05)| and |0.6 - 0.8|
    assert metrics["root_mae"] == pytest.approx(0.1625, abs=1e-6)
    assert (metrics["beliefs"], metrics["boards"]) == (2, 3)
