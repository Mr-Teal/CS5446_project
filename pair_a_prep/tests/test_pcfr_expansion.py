"""Incremental tree growth, state migration and fixed-tree regression checks."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import (
    Node, behavioral_nash_gap, frontier, hidden_coin, information_sets,
    kuhn_poker, matching_pennies, payoff_matrix, solve_matrix, terminal,
)


def cut(root, depth):
    if root.payoff is not None:
        return deepcopy(root)
    if depth == 0:
        return frontier(0.0)
    return replace(root, children={a: cut(c, depth - 1) for a, c in root.children.items()},
                   probabilities=dict(root.probabilities))


def next_layer(partial, full, path=()):
    if partial.cutoff:
        return {path: cut(full, 1)}
    batch = {}
    for action, child in partial.children.items():
        batch.update(next_layer(child, full.children[action], path + (action,)))
    return batch


def assert_arrays_equal(actual, expected):
    assert set(actual) == set(expected)
    for key in actual:
        np.testing.assert_array_equal(actual[key], expected[key])


def assert_state_equal(actual, expected):
    assert actual.root == expected.root
    assert actual.rounds == expected.rounds
    assert actual.sets == expected.sets
    assert actual._order == expected._order
    for player in (0, 1):
        assert_arrays_equal(actual._strategy[player], expected._strategy[player])
        assert_arrays_equal(actual._sums[player], expected._sums[player])
        old = expected._previous_opponent[player]
        if old is None:
            assert actual._previous_opponent[player] is None
        else:
            assert_arrays_equal(actual._previous_opponent[player], old)
        assert actual.minimizers[player].keys() == expected.minimizers[player].keys()
        for key, minimizer in actual.minimizers[player].items():
            other = expected.minimizers[player][key]
            assert minimizer.predictive == other.predictive
            assert minimizer._pending == other._pending
            for attr in ("regrets", "strategy", "previous_utility"):
                np.testing.assert_array_equal(getattr(minimizer, attr), getattr(other, attr))


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("predictive", [False, True])
@pytest.mark.parametrize("rounds", [0, 7])
def test_existing_state_preserved_and_new_state_initialized(schedule, predictive, rounds):
    original = Node(player=0, infoset="start",
                    children={"L": frontier(0.4), "R": frontier(-0.2)})
    solver = PCFRPlus(original, schedule=schedule, predictive=predictive, averaging_power=1)
    solver.run(rounds)
    before = deepcopy(solver)
    old_minimizer = solver.minimizers[0]["start"]
    subtrees = {
        (action,): Node(player=1, infoset="hidden", children={
            "x": terminal(value), "y": terminal(-value)})
        for action, value in (("L", 1), ("R", -2))
    }
    solver.expand(subtrees)
    assert solver.rounds == rounds
    assert solver.minimizers[0]["start"] is old_minimizer
    for attr in ("regrets", "strategy", "previous_utility"):
        np.testing.assert_array_equal(getattr(old_minimizer, attr),
                                      getattr(before.minimizers[0]["start"], attr))
    assert old_minimizer._pending == before.minimizers[0]["start"]._pending
    assert_arrays_equal(solver._strategy[0], before._strategy[0])
    assert_arrays_equal(solver._sums[0], before._sums[0])
    new = solver.minimizers[1]["hidden"]
    assert new.predictive == predictive
    assert new._pending == (schedule == "alternating" and rounds > 0)
    np.testing.assert_array_equal(new.regrets, [0, 0])
    np.testing.assert_array_equal(new.previous_utility, [0, 0])
    np.testing.assert_array_equal(solver._sums[1]["hidden"], [0, 0])
    np.testing.assert_array_equal(solver._strategy[1]["hidden"], [0.5, 0.5])
    if rounds:
        np.testing.assert_array_equal(solver._previous_opponent[0]["hidden"], [0.5, 0.5])
        assert_arrays_equal(solver._previous_opponent[1], before._previous_opponent[1])
    else:
        assert solver._previous_opponent == [None, None]
    assert original == before.root
    subtrees[("L",)].children["x"].payoff = 999
    assert solver.root.children["L"].children["x"].payoff == 1
    solver.run(5)
    assert solver.rounds == rounds + 5
    assert np.isfinite(solver.metrics()["last"]["value"])


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("factory", [
    matching_pennies, lambda: matching_pennies(True),
    hidden_coin, lambda: hidden_coin(True), kuhn_poker,
], ids=["pennies", "revealed-pennies", "coin", "revealed-coin", "kuhn"])
def test_progressive_growth_average_converges_against_full_game_oracle(schedule, factory):
    full = factory()
    solver = PCFRPlus(frontier(0), schedule=schedule)
    expansions = 0
    while batch := next_layer(solver.root, full):
        solver.run(5)
        solver.expand(batch)
        expansions += 1
        for policy in (solver.policy(), solver.policy(True)):
            for player in policy:
                for actions in player.values():
                    assert sum(actions.values()) == pytest.approx(1)
                    assert all(np.isfinite(p) and p >= 0 for p in actions.values())
    assert expansions >= 2
    assert solver.root == full
    solver.run(2000)
    oracle = solve_matrix(payoff_matrix(full)[0])
    metrics = solver.metrics()
    assert metrics["average"]["value"] == pytest.approx(oracle["profile_value"], abs=0.001)
    assert behavioral_nash_gap(full, solver.policy(True)) < 0.002
    assert np.isfinite(metrics["last"]["nash_gap"])
    if schedule == "alternating":
        assert metrics["last"]["nash_gap"] < 0.002


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_expanding_before_first_round_matches_fixed_tree_exactly(schedule):
    full = kuhn_poker()
    growing = PCFRPlus(frontier(0), schedule=schedule)
    while batch := next_layer(growing.root, full):
        growing.expand(batch)
    fixed = PCFRPlus(full, schedule=schedule)
    growing.run(8)
    growing.run(12)
    fixed.run(20)
    assert_state_equal(growing, fixed)
    before = deepcopy(growing)
    growing.expand({})
    assert_state_equal(growing, before)
    growing.run(10)
    fixed.run(10)
    assert_state_equal(growing, fixed)


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_new_hidden_occurrence_reuses_minimizer_and_chance_weighted_updates(schedule):
    full = hidden_coin()
    partial = deepcopy(full)
    partial.children["T"] = frontier(0)
    solver = PCFRPlus(partial, schedule=schedule)
    solver.run(3)
    minimizer = solver.minimizers[0]["guess_hidden"]
    sums = solver._sums[0]["guess_hidden"].copy()
    solver.expand({("T",): full.children["T"]})
    assert solver.minimizers[0]["guess_hidden"] is minimizer
    np.testing.assert_array_equal(solver._sums[0]["guess_hidden"], sums)
    assert solver._utilities(0)["guess_hidden"] == pytest.approx([0.5, -0.5])
    solver.step()
    assert minimizer.previous_utility == pytest.approx([0.5, -0.5])


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_new_descendants_are_prepared_bottom_up_and_zero_reach_is_not_backfilled(schedule):
    root = Node(player=0, infoset="start",
                children={"stop": terminal(2), "go": frontier(-1)})
    solver = PCFRPlus(root, schedule=schedule)
    solver.run(10)
    assert solver.policy()[0]["start"]["go"] == 0
    solver.expand({("go",): Node(player=0, infoset="later",
        children={"bad": terminal(-1), "good": terminal(1)})})
    assert solver._order[0] == ["later", "start"]
    assert solver._utilities(0)["later"] == pytest.approx([-1, 1])
    np.testing.assert_array_equal(solver._sums[0]["later"], [0, 0])
    assert solver.policy(True)[0]["later"] == {"bad": 0.5, "good": 0.5}
    solver.step()
    assert solver.minimizers[0]["later"].previous_utility == pytest.approx([-1, 1])
    np.testing.assert_array_equal(solver._sums[0]["later"], [0, 0])
    assert solver.policy(True)[0]["later"] == solver.policy()[0]["later"]


def test_grafting_one_history_does_not_mutate_aliased_parent_or_input():
    parent = Node(player=0, infoset="shared",
                  children={"go": frontier(0), "stop": terminal(0)})
    root = Node(children={"L": parent, "R": parent}, probabilities={"L": 0.5, "R": 0.5})
    solver = PCFRPlus(root)
    solver.expand({("L", "go"): Node(player=1, infoset="reply",
                                   children={"x": terminal(1)})})
    assert solver.root.children["R"].children["go"].cutoff
    assert root.children["L"].children["go"].cutoff
    assert solver.root.children["L"].children["go"].infoset == "reply"


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("power", [0, 1, 2])
def test_new_infoset_average_starts_at_birth_with_global_round_weight(schedule, power):
    full = matching_pennies()
    solver = PCFRPlus(cut(full, 1), schedule=schedule, averaging_power=power)
    solver.run(4)
    solver.expand(next_layer(solver.root, full))
    np.testing.assert_array_equal(solver._sums[1]["p1_hidden"], [0, 0])
    solver.step()
    # One contribution per infoset, not one per hidden history.
    assert solver._sums[1]["p1_hidden"].sum() == pytest.approx(5 ** power)


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_growth_continuation_is_deterministic(schedule):
    full = kuhn_poker()
    first = PCFRPlus(frontier(0), schedule=schedule)
    second = PCFRPlus(frontier(0), schedule=schedule)
    while batch := next_layer(first.root, full):
        first.run(7)
        second.run(3)
        second.run(4)
        first.expand(batch)
        second.expand(deepcopy(batch))
        assert_state_equal(first, second)
    first.run(15)
    second.run(15)
    assert_state_equal(first, second)


def test_chance_subtree_and_zero_probability_history_are_supported():
    full = Node(children={"live": hidden_coin(), "unreachable": matching_pennies()},
                probabilities={"live": 1.0, "unreachable": 0.0})
    solver = PCFRPlus(frontier(0), schedule="alternating")
    solver.run(2)
    solver.expand({(): full})
    solver.run(20)
    assert solver.metrics()["average"]["value"] == pytest.approx(0.5, abs=0.001)
    np.testing.assert_array_equal(solver.minimizers[1]["p1_hidden"].regrets, [0, 0])


def test_reexpanding_a_grown_path_is_rejected_without_reset():
    solver = PCFRPlus(frontier(0), schedule="alternating")
    solver.expand({(): matching_pennies()})
    solver.run(3)
    before = deepcopy(solver)
    with pytest.raises(ValueError, match="cutoff"):
        solver.expand({(): hidden_coin()})
    assert_state_equal(solver, before)


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("bad_batch, message", [
    ([], "mapping"),
    ({"a": matching_pennies()}, "tuples"),
    ({(1,): matching_pennies()}, "tuples"),
    ({("missing",): matching_pennies()}, "unknown"),
    ({(): matching_pennies()}, "cutoff"),
    ({("done",): matching_pennies()}, "cutoff"),
    ({("a",): terminal(1)}, "nonterminal"),
    ({("a",): frontier(1)}, "nonterminal"),
    ({("a",): None}, "Nodes"),
    ({("a",): Node()}, "children"),
    ({("a",): Node(children={"x": terminal(0)}, probabilities={"x": 0.5})}, "chance"),
    ({("a",): Node(player=0, infoset="start", children={"x": terminal(0)})}, "action order"),
    ({("a",): Node(player=1, infoset="hidden", children={"x": terminal(0)}),
      ("b",): Node(player=1, infoset="hidden", children={"y": terminal(0)})}, "action order"),
    ({("a",): Node(player=0, infoset="forgot", children={"x": terminal(0)}),
      ("b",): Node(player=0, infoset="forgot", children={"x": terminal(0)})}, "perfect recall"),
    ({("a",): matching_pennies(), ("missing",): hidden_coin()}, "unknown"),
], ids=["mapping", "path", "action", "missing", "internal", "true-terminal",
        "terminal-subtree", "cutoff-subtree", "not-node", "empty-node", "chance",
        "old-actions", "new-actions", "recall", "late-invalid-path"])
def test_invalid_batch_is_atomic_and_solver_can_continue(schedule, bad_batch, message):
    root = Node(player=0, infoset="start", children={
        "a": frontier(0), "b": frontier(1), "done": terminal(2)})
    solver = PCFRPlus(root, schedule=schedule)
    solver.run(3)
    before = deepcopy(solver)
    with pytest.raises(ValueError, match=message):
        solver.expand(bad_batch)
    assert solver.root is root
    assert_state_equal(solver, before)
    solver.step()
    before.step()
    assert_state_equal(solver, before)


def test_cycle_is_rejected_without_changing_solver():
    subtree = Node(player=0, infoset="loop")
    subtree.children["again"] = subtree
    solver = PCFRPlus(frontier(0))
    with pytest.raises(ValueError, match="acyclic"):
        solver.expand({(): subtree})
    assert solver.root == frontier(0)
    assert solver.rounds == 0


@pytest.mark.parametrize("node", [
    frontier(float("nan")), frontier(float("inf")),
    Node(cutoff=True, children={"x": terminal(0)}, probabilities={"x": 1}),
    Node(payoff=0, cutoff=True, children={"x": terminal(0)}),
])
def test_invalid_cutoff_is_rejected(node):
    with pytest.raises(ValueError):
        information_sets(node)
