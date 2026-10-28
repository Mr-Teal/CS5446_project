"""Independent arithmetic, information constraints and equilibrium checks."""

import numpy as np
import pytest
import json
from pathlib import Path

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


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_nonuniform_matrix_equilibrium_and_continuation(schedule):
    matrix = [[2, -1], [-2, 3]]
    root = Node(player=0, infoset="row", children={str(i): Node(player=1, infoset="column",
        children={str(j): terminal(matrix[i][j]) for j in range(2)}) for i in range(2)})
    solver = PCFRPlus(root, schedule=schedule)
    solver.run(300)
    solver.run(700)
    result = solver.metrics()
    assert result["average"]["nash_gap"] < 0.002
    assert solver.policy(True)[0]["row"]["0"] == pytest.approx(5 / 8, abs=0.002)
    direct = PCFRPlus(root, schedule=schedule); direct.run(1000)
    assert solver.policy() == direct.policy()


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_kuhn_value_and_gap_against_known_equilibrium(schedule):
    solver = PCFRPlus(kuhn_poker(), schedule=schedule)
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


def test_alternating_feedback_sees_the_new_opponent_policy():
    matrix = [[2, -1], [-2, 3]]
    root = Node(player=0, infoset="row", children={str(i): Node(player=1, infoset="column",
        children={str(j): terminal(matrix[i][j]) for j in range(2)}) for i in range(2)})
    solver = PCFRPlus(root, schedule="alternating")
    solver.step()
    assert list(solver.policy()[0]["row"].values()) == pytest.approx([0.5, 0.5])
    assert list(solver.policy()[1]["column"].values()) == pytest.approx([1, 0])
    solver.step()
    # Row responds to column's pure first action. Column immediately sees the
    # NEW pure first row: utility [-2, 1], not its stale [-0, -1] vector.
    assert list(solver.policy()[0]["row"].values()) == pytest.approx([1, 0])
    assert solver.minimizers[1]["column"].previous_utility == pytest.approx([-2, 1])
    assert list(solver.policy()[1]["column"].values()) == pytest.approx([1 / 13, 12 / 13])
    assert all(m._pending for player in solver.minimizers for m in player.values())


@pytest.mark.parametrize("factory, expected", [
    (matching_pennies, 0.0), (lambda: matching_pennies(True), -1.0),
    (hidden_coin, 0.5), (lambda: hidden_coin(True), 1.0)])
def test_alternating_chance_and_hidden_information(factory, expected):
    solver = PCFRPlus(factory(), schedule="alternating")
    solver.run(100)
    metrics = solver.metrics()
    assert metrics["last"]["value"] == pytest.approx(expected, abs=1e-5)
    assert metrics["average"]["nash_gap"] < 1e-5


def test_schedule_validation():
    with pytest.raises(ValueError, match="schedule"):
        PCFRPlus(matching_pennies(), schedule="unknown")


def test_alternating_kuhn_replays_committed_early_checkpoints():
    # Early transients pin the predictor/schedule. Equilibrium-only tests also
    # pass with stale local utilities or ancestor-first predictor preparation.
    path = Path(__file__).resolve().parents[1] / "results/pcfr_alternating_reference.json"
    reference = json.loads(path.read_text(encoding="utf-8"))["games"]["kuhn"]["trace"]
    solver = PCFRPlus(kuhn_poker(), schedule="alternating")
    for expected in reference:
        if expected["rounds"] > 100:
            break
        solver.run(expected["rounds"] - solver.rounds)
        actual = solver.metrics()
        for profile in ("last", "average"):
            for metric in ("value", "nash_gap"):
                assert actual[profile][metric] == pytest.approx(
                    expected[profile][metric], abs=1e-12, rel=0)
