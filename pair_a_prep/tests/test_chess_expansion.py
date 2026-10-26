"""History preservation, uniform growth and transactional budget checks."""

from copy import deepcopy
from time import perf_counter

import numpy as np
import pytest

from pair_a_prep.chess_search import (
    build_chess_tree, expand_chess_tree, SearchBudgetError, TreeCapacityError,
)
from pair_a_prep.gadgets import SubgameRoot, build_gadget
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import frontier, information_sets
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


@pytest.mark.parametrize("moves,player", [
    ((), "white"), (("a1b1",), "black"),
    (("a1b1", "h8g8"), "white"),
])
def test_growth_equals_direct_tree_and_preserves_trained_minimizers(moves, player):
    turn = turn_after(moves=moves, player=player)
    leaf = ConstantLeaf()
    tree = build_chess_tree(turn, leaf, initial_fen=KINGS, depth=1)
    solver = PCFRPlus(tree.root, schedule="alternating")
    solver.run(3)
    old = [{key: (item, item.regrets.copy()) for key, item in group.items()}
           for group in solver.minimizers]
    for depth in (2, 3):
        tree = expand_chess_tree(tree, solver, leaf, max_nodes=20000)
        direct = build_chess_tree(turn, leaf, initial_fen=KINGS, depth=depth, max_nodes=20000)
        assert tree.root == direct.root
        assert tree.nodes == direct.nodes
        assert tree.terminal_leaves == direct.terminal_leaves
        assert tree.frontiers.keys() == direct.frontiers.keys()
        for path, context in tree.frontiers.items():
            expected = direct.frontiers[path]
            assert context.state.fen == expected.state.fen
            assert context.state.board_copy().move_stack == expected.state.board_copy().move_stack
            assert context.memories == expected.memories
        assert solver.rounds == 3
        for p in (0, 1):
            for key, (item, regrets) in old[p].items():
                assert solver.minimizers[p][key] is item
                np.testing.assert_array_equal(item.regrets, regrets)
    solver.run(2)
    assert solver.rounds == 5


@pytest.mark.parametrize("limits,error", [
    ({"max_nodes": 5}, TreeCapacityError),
    ({"max_evaluator_calls": 1}, SearchBudgetError),
    ({"deadline": 0}, SearchBudgetError),
])
def test_failed_growth_leaves_solver_and_context_unchanged(limits, error):
    tree = build_chess_tree(turn_after(), ConstantLeaf(), initial_fen=KINGS, depth=1)
    solver = PCFRPlus(tree.root, schedule="alternating")
    solver.run(2)
    root, profile, paths = solver.root, deepcopy(solver.policy()), tuple(tree.frontiers)
    with pytest.raises(error):
        expand_chess_tree(tree, solver, ConstantLeaf(), **limits)
    assert solver.root is root
    assert solver.policy() == profile
    assert solver.rounds == 2
    assert tuple(tree.frontiers) == paths


def test_deadline_checked_after_slow_evaluator_before_commit():
    tree = build_chess_tree(turn_after(), ConstantLeaf(), initial_fen=KINGS, depth=1)
    solver = PCFRPlus(tree.root)

    class SlowLeaf(ConstantLeaf):
        def evaluate_children(self, fen):
            import time
            time.sleep(0.02)
            return super().evaluate_children(fen)

    with pytest.raises(SearchBudgetError):
        expand_chess_tree(tree, solver, SlowLeaf(), deadline=perf_counter() + 0.01)
    assert solver.root is tree.root


def test_actual_king_capture_is_never_expanded():
    fen = "k7/8/8/8/8/8/Q7/7K w - - 0 1"
    tree = build_chess_tree(turn_after(fen=fen), ConstantLeaf(), initial_fen=fen, depth=1)
    capture = tree.continuations[0].children["a2a8"]
    assert capture.payoff == 1 and not capture.cutoff
    assert ("0", "a2a8") not in tree.frontiers
    solver = PCFRPlus(tree.root)
    grown = expand_chess_tree(tree, solver, ConstantLeaf(), max_nodes=10000)
    assert grown.continuations[0].children["a2a8"] == capture
    assert grown.terminal_leaves >= tree.terminal_leaves


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_gadget_clones_preserve_cutoff_and_offsets(mode):
    gadget = build_gadget([SubgameRoot("r", "j", frontier(0.7), 1)],
                          {"j": 0.2}, mode=mode)
    def cutoffs(node):
        return ([node.payoff] if node.cutoff else []) + [
            value for child in node.children.values() for value in cutoffs(child)]
    assert cutoffs(gadget.tree) == pytest.approx([0.7 if mode == "resolve" else 0.5])
    information_sets(gadget.tree)
