"""The level-wise prediction walk (_prepare_fast) must reproduce the per-infoset reference exactly.

Toy games cover chance nodes, hidden information and several own-history depths; the chess case builds the
subgame tree of recorded positions with the material leaf, grows it, and compares the two solvers after every
round, including the published strategies that growth seeds with heuristic initial actions.
"""
import glob
import json
import os

import numpy as np
import pytest

from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import hidden_coin, kuhn_poker, matching_pennies


def _pair(root, **kwargs):
    return (PCFRPlus(root, fast_prepare=False, **kwargs), PCFRPlus(root, fast_prepare=True, **kwargs))


def _same(a: PCFRPlus, b: PCFRPlus) -> None:
    for average in (False, True):
        pa, pb = a.policy(average), b.policy(average)  # a tuple of two per-player dicts
        assert len(pa) == len(pb) == 2
        for player in (0, 1):
            assert pa[player].keys() == pb[player].keys()
            for key in pa[player]:
                assert pa[player][key].keys() == pb[player][key].keys()
                assert np.allclose(list(pa[player][key].values()), list(pb[player][key].values()), rtol=0, atol=1e-12), (average, player, key)
    for player in (0, 1):
        for key, m in a.minimizers[player].items():
            assert np.allclose(m.regrets, b.minimizers[player][key].regrets, rtol=0, atol=1e-12)


@pytest.mark.parametrize("game", [matching_pennies, hidden_coin, kuhn_poker])
@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("predictive", [True, False])
def test_toy_games_agree_every_round(game, schedule, predictive):
    reference, fast = _pair(game(), schedule=schedule, predictive=predictive)
    for _ in range(60):
        reference.step()
        fast.step()
        _same(reference, fast)


def test_environment_switch_and_default():
    assert PCFRPlus(kuhn_poker()).fast_prepare == PCFRPlus.FAST_PREPARE
    assert PCFRPlus(kuhn_poker(), fast_prepare=False).fast_prepare is False


# A folder of label part files; the chess case is skipped without one. The VM's GPU container mounts the label
# folders at /labels, so that location is tried when the variable is unset.
RECORDS = os.environ.get("FOW_TEST_RECORDS") or next(
    (p for p in ("/labels/solver-v2-sf8-g237", "/labels/solver-v2-sf8") if os.path.isdir(p)), "")


@pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"), reason="set FOW_TEST_RECORDS to a label folder")
def test_chess_trees_agree_through_growth():
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
            reference = PCFRPlus(trees[0].root, schedule="alternating", fast_prepare=False,
                                 initial_actions=heuristic_actions(trees[0].root))
            fast = PCFRPlus(trees[1].root, schedule="alternating", fast_prepare=True,
                            initial_actions=heuristic_actions(trees[1].root))
            solvers = [reference, fast]
            for round_index in range(12):
                reference.step()
                fast.step()
                _same(reference, fast)
                if round_index % 3 == 2 and trees[0].frontiers:  # grow one frontier path, as one-sided growth does
                    path_key = sorted(trees[0].frontiers)[0]
                    for i in range(2):
                        trees[i] = expand_chess_tree(trees[i], solvers[i], leaf, max_nodes=16384,
                                                     selected_paths=(path_key,), initialize_best=True)
                    _same(reference, fast)
            checked += 1
            if checked >= 3:
                return
    assert checked, "no suitable record found"
