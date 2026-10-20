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
