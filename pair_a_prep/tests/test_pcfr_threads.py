"""The kernel's root-parallel walks (C) give the single-thread results bit for bit.

With more than one thread (pcfr_set_threads) the utilities walk, each prediction level, the average and the growth
utilities walk the root's children in parallel, each subtree into a log of its own, and the logs are applied in root
order; the gadget controller's continuation values and pcfr_behavioral_values are walked in parallel per subtree.
These tests run the same solvers with 1 and with 2, 4 and 6 threads, the parallel path forced on every tree size,
and compare every state array, the policies, the recorded root rows, the flat growth utilities, the behavioral values
and the controller's numbers with ==, every round: toy games, the toy blended gadget, and recorded chess positions
grown by one-sided growth (trees up to a few thousand nodes). Skipped when the kernel is not built.
"""
import glob

import numpy as np
import pytest

from pair_a_prep import _pcfr_native
from pair_a_prep.gadgets import Gadget, build_gadget
from pair_a_prep.one_sided import OneSidedExpansion
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.subgame_boundaries import BlendedGadgetControl
from pair_a_prep.tests.test_gadget_native import _state, _toy_roots
from pair_a_prep.tests.test_native_loop import _growth_records, _identical
from pair_a_prep.tests.test_pcfr_native import RECORDS
from pair_a_prep.toy_games import hidden_coin, kuhn_poker, matching_pennies

pytestmark = pytest.mark.skipif(_pcfr_native.library() is None, reason="native PCFR+ kernel not built")

THREADS = (2, 4, 6)


@pytest.fixture
def threads():
    """Yields a setter (threads -> None) that forces the parallel path on every tree; restores 1 thread after."""
    previous = _pcfr_native.set_threads(1, 0)
    yield lambda n: _pcfr_native.set_threads(n, 0)
    _pcfr_native.set_threads(previous, 1024)


def _walks():
    return _pcfr_native.library().pcfr_parallel_walks()


@pytest.mark.parametrize("game", [matching_pennies, hidden_coin, kuhn_poker])
@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_toy_rounds_equal_single_thread(threads, game, schedule):
    solvers = [PCFRPlus(game(), schedule=schedule, backend="native") for _ in (1,) + THREADS]
    key = next(iter(solvers[0].sets[0]))
    before = _walks()
    for _ in range(40):
        rows = []
        for n, solver in zip((1,) + THREADS, solvers):
            threads(n)
            rows.append(solver.run(1, record=(0, key)))
            sampler = OneSidedExpansion(3)
            rows.append(dict(sampler.flat_utilities(solver)))
            rows.append(solver._native.utilities(1).items())
        threads(1)
        for solver in solvers[1:]:
            _identical(solvers[0], solver)
        for k in range(1, len(solvers)):
            assert np.array_equal(rows[0], rows[3 * k]) and rows[1] == rows[3 * k + 1]
            assert all(np.array_equal(a, b) for (_, a), (_, b) in zip(rows[2], rows[3 * k + 2]))
    assert _walks() > before  # the parallel path ran


def test_gadget_control_equals_single_thread(threads, monkeypatch):
    monkeypatch.setattr(Gadget, "FAST", True)
    runs = []
    for n in (1,) + THREADS:
        threads(n)
        history = []
        monkeypatch.setattr(BlendedGadgetControl, "history", history)
        gadget = build_gadget(_toy_roots(), {"A": 0.1, "B": -0.2}, mode="blended", group_prior={"A": .6, "B": .4})
        solver = PCFRPlus(gadget.tree, schedule="alternating", backend="native")
        control = BlendedGadgetControl(gadget, {"A": .6, "B": .4})
        key = next(iter(solver.sets[0]))
        rows = []
        for batch in (1, 3, 7, 5):
            trace, modes = control.run(gadget, solver, batch, record=(0, key))
            rows.append((trace.tolist(), modes, _state(control), repr(gadget.tree.probabilities),
                         repr(gadget.solver_values(solver))))
        runs.append((rows, repr(history), repr(solver.policy()), repr(solver.policy(True))))
    threads(1)
    assert all(run == runs[0] for run in runs[1:])


@pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"), reason="set FOW_TEST_RECORDS to a label folder")
@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_recorded_chess_growth_equals_single_thread(threads, schedule):
    """Native solvers on recorded positions, one per thread count, two rounds per growth attempt as the agents do;
    after every batch: the whole state (_identical), the recorded root rows, the flat growth utilities and the
    behavioral values of the root's subtrees, all bit-equal."""
    from pair_a_prep.chess_search import build_chess_tree, expand_chess_tree
    from pair_a_prep.search_policies import heuristic_actions
    from pairb.material import MaterialEvaluator

    leaf = MaterialEvaluator()
    before = _walks()
    for turn in _growth_records(2):
        counts = (1,) + THREADS
        trees = [build_chess_tree(turn, leaf, depth=1, max_nodes=16384) for _ in counts]
        solvers = [PCFRPlus(tree.root, schedule=schedule, backend="native", initial_actions=heuristic_actions(tree.root))
                   for tree in trees]
        samplers = [OneSidedExpansion(13) for _ in counts]
        for _ in range(25):
            rows, flat, values = [], [], []
            for n, solver, sampler in zip(counts, solvers, samplers):
                threads(n)
                rows.append(solver.run(2, record=(0, trees[0].root_infoset)))
                flat.append(dict(sampler.flat_utilities(solver)))
                native = solver._native
                values.append(native.behavioral_values(native.child[native.child_begin[0]:native.child_begin[1]]))
            threads(1)
            for k in range(1, len(counts)):
                _identical(solvers[0], solvers[k])
                assert np.array_equal(rows[0], rows[k]) and flat[0] == flat[k]
                assert np.array_equal(values[0], values[k])
            proposals = [sampler.select(tree, solver, 4) for sampler, tree, solver in zip(samplers, trees, solvers)]
            assert all((p is None) == (proposals[0] is None) for p in proposals)
            if proposals[0] is None:
                continue
            for i, (solver, proposal) in enumerate(zip(solvers, proposals)):
                trees[i] = expand_chess_tree(trees[i], solver, leaf, max_nodes=16384,
                                             selected_paths=(proposal[0],), initialize_best=True)
                samplers[i].commit(proposal)
        assert trees[0].root == trees[-1].root and trees[0].nodes > 400
    assert _walks() > before
