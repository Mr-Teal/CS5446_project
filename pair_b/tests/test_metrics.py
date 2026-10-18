"""Move-choice metrics: does a scorer pick the move that the depth-11 score says is best?

Values are in the child's side-to-move view (the opponent of the player choosing), so the
chooser's best child is the one with the LOWEST value. Expected numbers are worked by hand.
"""
import numpy as np
import pytest

from pairb.metrics import choice_metrics


# Parent A: truth picks child 1 (-0.2); the predictor picks child 2 (-0.3), whose true value is
# 0.1, so it loses 0.1 - (-0.2) = 0.3. Parent B: both pick child 0, losing nothing.
def test_choice_metrics_counts_agreement_and_the_value_lost():
    parents = np.array(["A", "A", "A", "B", "B"])
    y = np.array([0.5, -0.2, 0.1, 0.0, 0.3])
    pred = np.array([0.4, 0.0, -0.3, -0.1, 0.2])
    m = choice_metrics(parents, pred, y)
    assert m["top1"] == pytest.approx(0.5)
    assert m["regret"] == pytest.approx(0.15)
    assert m["parents"] == 2


# Catches: a tie in the true values (two equally good moves) counted as a miss.
def test_choice_metrics_counts_an_equally_good_move_as_agreement():
    parents = np.array(["A", "A", "A"])
    y = np.array([-1.0, -1.0, 0.4])
    pred = np.array([0.0, -0.5, 0.3])
    assert choice_metrics(parents, pred, y)["top1"] == 1.0


# Catches: groups mixed up when rows of the same parent are not next to each other.
def test_choice_metrics_groups_rows_by_parent_wherever_they_are():
    parents = np.array(["B", "A", "B", "A", "A"])
    y = np.array([0.0, 0.5, 0.3, -0.2, 0.1])
    pred = np.array([-0.1, 0.4, 0.2, 0.0, -0.3])
    m = choice_metrics(parents, pred, y)
    assert m["top1"] == pytest.approx(0.5) and m["regret"] == pytest.approx(0.15)


# Catches: a confidence interval that ignores the pairing, or reports the difference with the wrong sign.
def test_paired_regret_difference_is_negative_when_the_network_chooses_better():
    from pairb.metrics import paired_regret_difference
    parents = np.repeat(np.arange(20), 2).astype(str)          # 20 parents, 2 children each
    y = np.tile([0.0, 0.1], 20)                                  # child 0 is always best
    net = np.tile([-1.0, 1.0], 20)                               # the network always picks child 0
    base = np.tile([1.0, -1.0], 20)                              # the baseline always picks child 1
    d = paired_regret_difference(parents, net, base, y, n_boot=200, seed=0)
    assert d["mean"] == pytest.approx(-0.1)
    assert d["ci95"] == pytest.approx([-0.1, -0.1])


def test_paired_regret_difference_interval_straddles_zero_when_they_tie_on_average():
    from pairb.metrics import paired_regret_difference
    parents = np.repeat(np.arange(40), 2).astype(str)
    y = np.tile([0.0, 0.1], 40)
    net = np.tile([[-1.0, 1.0], [1.0, -1.0]], (20, 1)).ravel()   # right on even parents, wrong on odd
    base = np.tile([[1.0, -1.0], [-1.0, 1.0]], (20, 1)).ravel()  # the opposite
    d = paired_regret_difference(parents, net, base, y, n_boot=500, seed=0)
    assert d["mean"] == pytest.approx(0.0)
    assert d["ci95"][0] < 0 < d["ci95"][1]
