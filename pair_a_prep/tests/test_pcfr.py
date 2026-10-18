"""Independent arithmetic, information constraints and equilibrium checks."""

import numpy as np
import pytest

from pair_a_prep.pcfr import PCFRPlus, PredictiveRMPlus
from pair_a_prep.toy_games import (Node, terminal, hidden_coin, matching_pennies,
                                   kuhn_poker, behavioral_value)


def test_predictive_projection_and_actual_regret_are_separate():
    m = PredictiveRMPlus(2)
    assert m.next_strategy() == pytest.approx([0.5, 0.5])
    m.observe([3, 1])
    assert m.regrets == pytest.approx([1, 0])
    assert m.next_strategy() == pytest.approx([1, 0])
    m.observe([0, 2])
    assert m.regrets == pytest.approx([1, 2])
    assert m.next_strategy() == pytest.approx([0.2, 0.8])
    # Predicted regret affects the decision but is not added to accumulated state.
    assert m.regrets == pytest.approx([1, 2])


def test_prediction_switch_is_not_ordinary_cfr_plus():
    predictive, ordinary = PredictiveRMPlus(2), PredictiveRMPlus(2, predictive=False)
    for m in (predictive, ordinary):
        m.next_strategy(); m.observe([3, 1])
        m.next_strategy(); m.observe([0, 2])
    assert predictive.next_strategy() == pytest.approx([0.2, 0.8])
    assert ordinary.next_strategy() == pytest.approx([1 / 3, 2 / 3])


def test_chance_weighted_hidden_nodes_aggregate_before_clipping():
    solver = PCFRPlus(hidden_coin())
    solver.step()
    # H has probability .75, T .25, so action utilities are [.5, -.5].
    assert solver.minimizers[0]["guess_hidden"].regrets == pytest.approx([0.5, 0])
    # Splitting this infoset by the hidden coin would illegally give value 1.
    solver.run(30)
    assert behavioral_value(solver.root, solver.policy()) == pytest.approx(0.5)


def test_zero_own_reach_does_not_skip_counterfactual_regret():
    root = Node(player=0, infoset="start", children={
        "stop": terminal(0), "go": Node(player=0, infoset="later",
            children={"bad": terminal(-1), "good": terminal(1)})})
    solver = PCFRPlus(root)
    solver._strategy[0]["start"] = np.array([1.0, 0.0])
    assert solver._utilities(0)["later"] == pytest.approx([-1, 1])
    solver._accumulate_average(0, 1)
    assert solver._sums[0]["later"] == pytest.approx([0, 0])


def test_imperfect_recall_is_rejected():
    def reply():
        return Node(player=0, infoset="forgot", children={"x": terminal(0), "y": terminal(1)})
    root = Node(player=0, infoset="start", children={"a": reply(), "b": reply()})
    with pytest.raises(ValueError, match="perfect recall"):
        PCFRPlus(root)


def test_nonuniform_matrix_equilibrium_and_continuation():
    matrix = [[2, -1], [-2, 3]]
    root = Node(player=0, infoset="row", children={str(i): Node(player=1, infoset="column",
        children={str(j): terminal(matrix[i][j]) for j in range(2)}) for i in range(2)})
    solver = PCFRPlus(root)
    solver.run(300)
    solver.run(700)
    result = solver.metrics()
    assert result["average"]["nash_gap"] < 0.002
    assert solver.policy(True)[0]["row"]["0"] == pytest.approx(5 / 8, abs=0.002)
    direct = PCFRPlus(root); direct.run(1000)
    assert solver.policy() == direct.policy()


def test_kuhn_value_and_gap_against_known_equilibrium():
    solver = PCFRPlus(kuhn_poker())
    solver.run(2000)
    metrics = solver.metrics()
    assert metrics["average"]["value"] == pytest.approx(-1 / 18, abs=0.0001)
    assert metrics["average"]["nash_gap"] < 0.0001
    # Last-iterate behavior is measured separately, never inferred from averaging.
    assert metrics["last"]["nash_gap"] < 0.0001


def test_api_order_and_validation():
    m = PredictiveRMPlus(2)
    with pytest.raises(ValueError):
        m.observe([1, 0])
    m.next_strategy()
    with pytest.raises(ValueError):
        m.next_strategy()
    with pytest.raises(ValueError):
        m.observe([float("nan"), 0])
    solver = PCFRPlus(matching_pennies())
    detached = solver.policy()
    detached[0]["p0"]["H"] = 99
    assert solver.policy()[0]["p0"]["H"] == 0.5
    with pytest.raises(ValueError):
        solver.run(-1)
