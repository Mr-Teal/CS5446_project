"""Gadget path translation, payoff offsets and warm solver continuation."""

from copy import deepcopy

import numpy as np
import pytest

from pair_a_prep.chess_gadgets import prepare_chess_roots
from pair_a_prep.chess_search import SearchBudgetError, TreeCapacityError
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import behavioral_value, information_sets
from pair_a_prep.tests.test_chess_gadgets import TableLeaf, make_turn, build, KINGS


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
@pytest.mark.parametrize("viewer,paths", [
    ("white", (("a1b1", "h8g8"), ("a1b1", "h8g7"))),
    ("black", (("a1a2", "h8g8", "a2a3"), ("a1b2", "h8g8", "b2b3"))),
])
def test_grown_gadget_matches_direct_tree_and_keeps_solver_state(mode, viewer, paths):
    turn, evaluator = make_turn(paths, weights=(0.8, 0.2), viewer=viewer), TableLeaf()
    roots = prepare_chess_roots(turn, evaluator, initial_fen=KINGS, depth=1)
    alternates = dict(zip(roots.groups, (0.3, -0.2)))
    bridge = build(roots, mode, alternates=alternates)
    solver = PCFRPlus(bridge.gadget.tree, schedule="alternating")
    solver.run(3)
    old = [{key: (item, item.regrets.copy()) for key, item in group.items()}
           for group in solver.minimizers]
    for depth in (2, 3):
        previous = bridge
        bridge = bridge.expand(solver, evaluator, max_nodes=20000)
        direct_roots = prepare_chess_roots(turn, evaluator, initial_fen=KINGS,
                                          depth=depth, max_nodes=20000)
        direct = build(direct_roots, mode, alternates=alternates)
        assert bridge.gadget.tree == direct.gadget.tree
        assert bridge.gadget.continuations == direct.gadget.continuations
        assert information_sets(bridge.gadget.tree) == information_sets(direct.gadget.tree)
        assert solver.root is bridge.gadget.tree
        assert solver.rounds == 3
        for p in (0, 1):
            for key, (item, regrets) in old[p].items():
                assert solver.minimizers[p][key] is item
                np.testing.assert_array_equal(item.regrets, regrets)
        with pytest.raises(ValueError, match="current gadget tree"):
            previous.expand(solver, evaluator)
    solver.run(2)
    solution = bridge.solution(solver)
    assert solution.configuration["rounds"] == 5
    values = solution.values.hypothesis_values
    assert solution.values.root_value == pytest.approx(0.8 * values[0] + 0.2 * values[1])
    assert solution.values.gadget_value == pytest.approx(behavioral_value(solver.root, solver.policy()))
    record = solution.training_record(seed=17, game_id="growth-test")
    assert record.hypothesis_values == values


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
@pytest.mark.parametrize("kwargs,error", [
    ({"max_nodes": 5}, TreeCapacityError),
    ({"max_evaluator_calls": 1}, SearchBudgetError),
    ({"deadline": 0}, SearchBudgetError),
])
def test_failed_preparation_does_not_change_gadget_solver(mode, kwargs, error):
    roots = prepare_chess_roots(make_turn(), TableLeaf(), initial_fen=KINGS, depth=1)
    bridge = build(roots, mode)
    solver = PCFRPlus(bridge.gadget.tree, schedule="alternating")
    solver.run(3)
    root, profile = solver.root, deepcopy(solver.policy())
    with pytest.raises(error):
        bridge.expand(solver, TableLeaf(), **kwargs)
    assert solver.root is root
    assert solver.policy() == profile
    assert solver.rounds == 3
    assert bridge.solution(solver).configuration["rounds"] == 3


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_terminal_king_capture_keeps_offset_and_labels_stay_unshifted(mode):
    fen = "k7/8/8/8/8/8/Q7/7K w - - 0 1"
    roots = prepare_chess_roots(make_turn(fen=fen), TableLeaf(), initial_fen=fen, depth=1)
    bridge = build(roots, mode, alternates={key: 0.25 for key in roots.groups})
    solver = PCFRPlus(bridge.gadget.tree, schedule="alternating")
    solver.run(1)
    bridge = bridge.expand(solver, TableLeaf(), max_nodes=10000)
    root_id = roots.root_ids[0]
    assert bridge.gadget.continuations[root_id].children["a2a8"].payoff == 1.0
    node = (solver.root.children[root_id].children["enter"] if mode == "resolve"
            else solver.root.children[roots.opponent_infosets[0]].children[root_id])
    assert node.children["a2a8"].payoff == (1.0 if mode == "resolve" else 0.75)
    solver.run(100)
    values = bridge.solution(solver).values
    assert values.root_value == pytest.approx(1.0)
    assert values.gadget_value == pytest.approx(0.25 if mode == "resolve" else 0.75)


def test_configuration_distinguishes_growth_timing_at_same_final_depth_and_rounds():
    ids = []
    for before in (1, 2):
        roots = prepare_chess_roots(make_turn(), TableLeaf(), initial_fen=KINGS, depth=1)
        bridge = build(roots)
        solver = PCFRPlus(bridge.gadget.tree, schedule="alternating")
        solver.run(before)
        bridge = bridge.expand(solver, TableLeaf())
        solver.run(4 - before)
        solution = bridge.solution(solver)
        assert solution.configuration["rounds"] == 4
        assert solution.configuration["chess"]["depth"] == 2
        assert solution.configuration["chess"]["growth_steps"][0]["rounds_before"] == before
        ids.append(solution.config_id)
    assert ids[0] != ids[1]
