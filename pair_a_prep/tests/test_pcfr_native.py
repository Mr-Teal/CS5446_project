"""The native PCFR+ round (pcfr_kernel.cpp) must reproduce the Python solver (level-wise prepare).

Mirrors test_pcfr_fast.py: toy games x schedules x predictive, every round for 60 rounds; recorded chess trees
with the material leaf grown through expand_chess_tree every third round. Besides policies and regrets, the whole
state is compared (published strategies, previous utilities, pending flags, sums, previous opponent snapshots,
unconsumed initial actions). Skipped when the kernel is not built (python -m pair_a_prep.build_pcfr_kernel).
"""
from copy import deepcopy
import glob
import os

import numpy as np
import pytest

from pair_a_prep import _pcfr_native
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import Node, frontier, hidden_coin, kuhn_poker, matching_pennies, terminal

pytestmark = pytest.mark.skipif(_pcfr_native.library() is None, reason="native PCFR+ kernel not built")

TOLERANCE = 1e-9


def _close(a, b, what):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    assert a.shape == b.shape, what
    assert np.allclose(a, b, rtol=0, atol=TOLERANCE), (what, float(np.max(np.abs(a - b))))


def _same(python: PCFRPlus, native: PCFRPlus) -> None:
    assert python.backend == "python" and native.backend == "native"
    assert python.rounds == native.rounds and python.sets == native.sets
    for average in (False, True):
        pa, pb = python.policy(average), native.policy(average)
        for player in (0, 1):
            assert pa[player].keys() == pb[player].keys()
            for key in pa[player]:
                assert pa[player][key].keys() == pb[player][key].keys()
                _close(list(pa[player][key].values()), list(pb[player][key].values()), (average, player, key))
    for player in (0, 1):
        assert python.minimizers[player].keys() == native.minimizers[player].keys()
        for key, m in python.minimizers[player].items():
            n = native.minimizers[player][key]
            for attr in ("regrets", "strategy", "previous_utility"):
                _close(getattr(m, attr), getattr(n, attr), (attr, player, key))
            assert m._pending == n._pending, (player, key)
            _close(python._strategy[player][key], native._strategy[player][key], ("published", player, key))
            _close(python._sums[player][key], native._sums[player][key], ("sums", player, key))
        old, new = python._previous_opponent[player], native._previous_opponent[player]
        assert (old is None) == (new is None)
        if old is not None:
            assert old.keys() == new.keys()
            for key in old:
                _close(old[key], new[key], ("previous opponent", player, key))
    assert python._initial_actions == native._initial_actions


def _pair(root, **kwargs):
    return PCFRPlus(deepcopy(root), backend="python", **kwargs), PCFRPlus(deepcopy(root), backend="native", **kwargs)


@pytest.mark.parametrize("game", [matching_pennies, hidden_coin, kuhn_poker])
@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("predictive", [True, False])
def test_toy_games_agree_every_round(game, schedule, predictive):
    python, native = _pair(game(), schedule=schedule, predictive=predictive)
    _same(python, native)
    for _ in range(60):
        python.step()
        native.step()
        _same(python, native)


@pytest.mark.parametrize("power", [0, 1, 2])
def test_initial_actions_and_averaging_power(power):
    root = kuhn_poker()
    first = {(p, key): actions[-1] for p, sets in enumerate(PCFRPlus(root).sets) for key, actions in sets.items()}
    python, native = _pair(root, schedule="alternating", averaging_power=power, initial_actions=first)
    _same(python, native)
    for _ in range(20):
        python.step()
        native.step()
        _same(python, native)


def _walks(solver):
    """The kernel's utilities and average walks against the Python methods, on the solver's current state."""
    for player in (0, 1):
        expected, actual = solver._utilities(player), solver._native.utilities(player)
        for key in expected:
            _close(expected[key], actual[key], ("utilities", player, key))
        opponent = {key: np.full(len(a), 1 / len(a)) for key, a in solver.sets[1 - player].items()}
        expected, actual = solver._utilities(player, opponent), solver._native.utilities(player, opponent)
        for key in expected:
            _close(expected[key], actual[key], ("utilities vs uniform", player, key))
    reference = deepcopy(solver)
    for player in (0, 1):
        PCFRPlus._accumulate_average(reference, player, 9)
        solver._native.accumulate_average(player, 9)
        for key in solver.sets[player]:
            _close(reference._sums[player][key], solver._sums[player][key], ("sums", player, key))


def test_kernel_walks_match_the_python_methods():
    solver = PCFRPlus(kuhn_poker(), backend="native")
    for _ in range(7):
        solver.step()
    _walks(solver)


def test_state_views_write_through_and_survive_deepcopy_and_expand():
    root = Node(player=0, infoset="start", children={"L": frontier(0.4), "R": frontier(-0.2)})
    python, native = _pair(root, schedule="alternating", averaging_power=1)
    for solver in (python, native):
        solver.run(3)
        solver.minimizers[0]["start"].regrets *= 2.0             # in place, as affine_solver does
        solver.minimizers[0]["start"].strategy = np.array([0.25, 0.75])  # reassignment, as seed_new does
        solver._strategy[0]["start"] = np.array([0.25, 0.75])
    _same(python, native)
    copy = deepcopy(native)
    assert copy.backend == "native" and copy._native is not native._native
    native.step()
    assert not np.array_equal(copy.minimizers[0]["start"].regrets, native.minimizers[0]["start"].regrets)
    python.step()
    _same(python, native)
    kept = native.minimizers[0]["start"]
    subtrees = {(action,): Node(player=1, infoset="hidden", children={"x": terminal(v), "y": terminal(-v)})
                for action, v in (("L", 1), ("R", -2))}
    for solver in (python, native):
        solver.expand(deepcopy(subtrees), initial_actions={(1, "hidden"): "y"})
    assert native.minimizers[0]["start"] is kept
    _same(python, native)
    for _ in range(10):
        python.step()
        native.step()
        _same(python, native)


def test_backend_selection(monkeypatch):
    assert PCFRPlus(kuhn_poker(), backend="native").backend == "native"
    assert PCFRPlus(kuhn_poker(), backend="python").backend == "python"
    assert PCFRPlus(kuhn_poker(), backend="auto").backend == "native"
    assert PCFRPlus(kuhn_poker(), fast_prepare=False).backend == "python"
    with pytest.raises(ValueError):
        PCFRPlus(kuhn_poker(), backend="native", fast_prepare=False)
    with pytest.raises(ValueError):
        PCFRPlus(kuhn_poker(), backend="fortran")
    monkeypatch.setattr(PCFRPlus, "BACKEND", "python")
    assert PCFRPlus(kuhn_poker()).backend == "python"



def test_chance_probabilities_rewritten_in_place_reach_the_kernel():
    """The blended gadget's controller rewrites its root distribution between rounds (BlendedGadgetControl.apply)."""
    def tree():
        return Node(children={
            "A": Node(player=0, infoset="a", children={"x": Node(player=1, infoset="o", children={
                "l": terminal(1), "r": terminal(-1)}), "y": terminal(0.2)}),
            "B": Node(player=0, infoset="b", children={"x": Node(player=1, infoset="o", children={
                "l": terminal(-1), "r": terminal(2)}), "y": terminal(-0.3)})}, probabilities={"A": 0.5, "B": 0.5})
    python, native = _pair(tree())
    for weight in (0.5, 0.9, 0.2, 0.7):
        for solver in (python, native):
            solver.root.probabilities.update(A=weight, B=1 - weight)
            solver.run(3)
        _same(python, native)

RECORDS = os.environ.get("FOW_TEST_RECORDS") or next(
    (p for p in ("/labels/solver-v2-sf8-g237", "/labels/solver-v2-sf8") if os.path.isdir(p)), "")


@pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"), reason="set FOW_TEST_RECORDS to a label folder")
@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_chess_trees_agree_through_growth(schedule):
    from fow_shared.recording import read_records
    from pair_a_prep.chess_search import build_chess_tree, expand_chess_tree
    from pair_a_prep.search_policies import heuristic_actions
    from pairb.material import MaterialEvaluator

    leaf = MaterialEvaluator()
    checked = 0
    for path in sorted(glob.glob(f"{RECORDS}/part-*.jsonl"))[:3]:
        for record in read_records(path):
            turn = record.agent_input
            if turn.observation.ply < 6 or len(turn.belief.hypotheses) < 4:
                continue
            # Two identical trees (the material leaf is deterministic): a solver and its chess tree share one root.
            trees = [build_chess_tree(turn, leaf, depth=1, max_nodes=16384) for _ in range(2)]
            solvers = [PCFRPlus(tree.root, schedule=schedule, backend=backend,
                                initial_actions=heuristic_actions(tree.root))
                       for tree, backend in zip(trees, ("python", "native"))]
            python, native = solvers
            for round_index in range(12):
                python.step()
                native.step()
                _same(python, native)
                if round_index % 3 == 2 and trees[0].frontiers:  # grow one frontier path, as one-sided growth does
                    path_key = sorted(trees[0].frontiers)[0]
                    for i in range(2):
                        trees[i] = expand_chess_tree(trees[i], solvers[i], leaf, max_nodes=16384,
                                                     selected_paths=(path_key,), initialize_best=True)
                    _same(python, native)
            _walks(native)
            checked += 1
            if checked >= 3:
                return
    assert checked, "no suitable record found"
