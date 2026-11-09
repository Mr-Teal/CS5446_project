"""The native search loop (A3/A4/D1) must reproduce the Python path exactly.

A3: PCFRPlus.run(n) on the native backend (one kernel call) equals n step() calls bit for bit, including the
recorded root strategy after every round. A4: after every expand() the incrementally extended compiled tree and
state equal a fresh full compile of the same tree (compared through the infoset keys and a parallel walk from the
root, since new sets and nodes are appended rather than renumbered), and sets / _order / _depth equal
_index_tree on the whole tree, in order. D1: OneSidedExpansion.flat_utilities equals utilities() of
solver.policy() exactly, and select() makes the same proposal (path, visited sets, utilities, RNG state) without
building policy dictionaries. End to end, both agents play the same moves with the same diagnostics on either
backend. Skipped when the kernel is not built (python -m pair_a_prep.build_pcfr_kernel).
"""
from copy import deepcopy
import glob

import numpy as np
import pytest

from pair_a_prep import _pcfr_native
from pair_a_prep.one_sided import OneSidedExpansion
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.tests.test_pcfr_native import RECORDS, _same
from pair_a_prep.toy_games import Node, frontier, hidden_coin, kuhn_poker, matching_pennies, terminal

pytestmark = pytest.mark.skipif(_pcfr_native.library() is None, reason="native PCFR+ kernel not built")

STATE = ("regrets", "strategy", "previous_utility", "sums")


def _identical(a: PCFRPlus, b: PCFRPlus) -> None:
    """Bit-equal solver states (two native solvers, or native against Python where the kernel is exact)."""
    assert a.rounds == b.rounds and a.sets == b.sets
    for average in (False, True):
        assert a.policy(average) == b.policy(average)
    for p in (0, 1):
        for key, m in a.minimizers[p].items():
            n = b.minimizers[p][key]
            for attr in ("regrets", "strategy", "previous_utility"):
                assert np.array_equal(getattr(m, attr), getattr(n, attr)), (attr, p, key)
            assert m._pending == n._pending
            assert np.array_equal(a._sums[p][key], b._sums[p][key])
        old, new = a._previous_opponent[p], b._previous_opponent[p]
        assert (old is None) == (new is None)
        if old is not None:
            assert old.keys() == new.keys() and all(np.array_equal(old[k], new[k]) for k in old)
    assert a._initial_actions == b._initial_actions


# A3 ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("game", [matching_pennies, hidden_coin, kuhn_poker])
@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("power", [0, 1, 2])
def test_run_equals_steps_bit_for_bit(game, schedule, power):
    root = game()
    first = {(p, key): actions[-1] for p, sets in enumerate(PCFRPlus(root).sets) for key, actions in sets.items()}
    batched, stepped = (PCFRPlus(deepcopy(root), schedule=schedule, averaging_power=power, backend="native",
                                 initial_actions=first) for _ in range(2))
    key = next(iter(batched.sets[0]))
    for n in (1, 2, 5, 0, 13, 32):  # the first batch starts at round 0 (the alternating schedule's extra prepare)
        trace = batched.run(n, record=(0, key))
        rows = []
        for _ in range(n):
            stepped.step()
            rows.append(stepped.policy()[0][key])
        assert trace.shape == (n, len(batched.sets[0][key]))
        assert [dict(zip(batched.sets[0][key], row.tolist())) for row in trace] == rows
        _identical(batched, stepped)


def test_run_falls_back_to_step_when_step_is_replaced(monkeypatch):
    solver = PCFRPlus(kuhn_poker(), backend="native")
    calls = []
    original = PCFRPlus.step
    monkeypatch.setattr(PCFRPlus, "step", lambda self: (calls.append(1), original(self)))
    solver.run(3)
    assert len(calls) == 3 and solver.rounds == 3


# A4 ------------------------------------------------------------------------------------------------------------

def _levels(state, p):
    side, keys = state.sides[p], {i: k for k, i in state.index[p].items()}
    return [(int(side["level_depth"][level]), [keys[int(i)] for i in
             side["level_sets"][side["level_begin"][level]:side["level_begin"][level + 1]]])
            for level in range(len(side["level_depth"]))]


def _compiled_equal(solver: PCFRPlus) -> None:
    """The solver's (incrementally extended) native state against a fresh full compile of the same tree."""
    state, fresh = solver._native, _pcfr_native.NativeState(solver, _pcfr_native.library())
    sets, order, depth = PCFRPlus._index_tree(solver, solver.root)
    assert [list(s.items()) for s in solver.sets] == [list(s.items()) for s in sets]
    assert solver._order == order and solver._depth == depth
    keys = [[{i: k for k, i in s.index[p].items()} for p in (0, 1)] for s in (state, fresh)]
    stack, reached = [(0, 0)], 0
    while stack:
        i, j = stack.pop()
        reached += 1
        assert state.kind[i] == fresh.kind[j] and state.player[i] == fresh.player[j]
        assert state.payoff[i] == fresh.payoff[j]
        if state.kind[i] == 2:
            p = int(state.player[i])
            assert keys[0][p][int(state.infoset[i])] == keys[1][p][int(fresh.infoset[j])]
        a = state.child[state.child_begin[i]:state.child_begin[i + 1]]
        b = fresh.child[fresh.child_begin[j]:fresh.child_begin[j + 1]]
        assert len(a) == len(b)
        pairs = set(zip(a.tolist(), b.tolist()))
        if state.kind[i] == 1:
            ca = state.chance_child[state.chance_begin[i]:state.chance_begin[i + 1]].tolist()
            cb = fresh.chance_child[fresh.chance_begin[j]:fresh.chance_begin[j + 1]].tolist()
            assert set(zip(ca, cb)) <= pairs and len(ca) == len(cb)
            assert np.array_equal(state.chance_prob[state.chance_begin[i]:state.chance_begin[i + 1]],
                                  fresh.chance_prob[fresh.chance_begin[j]:fresh.chance_begin[j + 1]])
        stack.extend(pairs)
    assert reached == len(fresh.kind)
    assert sorted(map(id, state.chance_dicts)) == sorted(map(id, fresh.chance_dicts))
    assert np.array_equal(state.has_previous, fresh.has_previous)
    for p in (0, 1):
        s, f = state.sides[p], fresh.sides[p]
        assert state.index[p].keys() == fresh.index[p].keys() == solver.sets[p].keys()
        assert len(s["depth"]) == len(state.index[p]) and int(s["offset"][-1]) == int(f["offset"][-1])
        for key in solver.sets[p]:
            i, j = state.index[p][key], fresh.index[p][key]
            (a0, a1), (b0, b1) = state.slots[p][key], fresh.slots[p][key]
            assert (s["offset"][i], s["offset"][i + 1]) == (a0, a1) and a1 - a0 == b1 - b0
            for name in STATE:
                assert np.array_equal(s[name][a0:a1], f[name][b0:b1]), (name, p, key)
            assert s["pending"][i] == f["pending"][j] and s["depth"][i] == f["depth"][j]
            assert s["initial_action"][i] == f["initial_action"][j] == -1
        if state.has_previous[p]:
            for key in solver.sets[1 - p]:
                (a0, a1), (b0, b1) = state.slots[1 - p][key], fresh.slots[1 - p][key]
                assert np.array_equal(s["previous_opponent"][a0:a1], f["previous_opponent"][b0:b1])
        assert _levels(state, p) == _levels(fresh, p)


def test_incremental_compile_matches_full_compile_on_toy_growth(monkeypatch):
    """Layer-by-layer growth of Kuhn poker from one cutoff, both schedules, with rounds in between; with the spare
    room shrunk, the state arrays outgrow it several times (views rebound); the root itself is replaced once."""
    from pair_a_prep.tests.test_pcfr_expansion import next_layer
    monkeypatch.setattr(_pcfr_native, "_room", lambda needed: needed + 1)
    for schedule in ("simultaneous", "alternating"):
        full = kuhn_poker()
        python, native = (PCFRPlus(frontier(0), schedule=schedule, backend=b) for b in ("python", "native"))
        buffers = set()
        while batch := next_layer(native.root, full):
            for solver in (python, native):
                solver.expand(deepcopy(batch))
                solver.run(2)
            buffers.add(id(native._native.sides[0]["regrets"]))
            _compiled_equal(native)
            _same(python, native)
        assert len(buffers) >= 2


# D1 and the whole growth loop on recorded chess positions -------------------------------------------------------

def _growth_records(limit):
    from fow_shared.recording import read_records
    found = 0
    for path in sorted(glob.glob(f"{RECORDS}/part-*.jsonl"))[:3]:
        for record in read_records(path):
            turn = record.agent_input
            if turn.observation.ply >= 6 and len(turn.belief.hypotheses) >= 4:
                yield turn
                found += 1
                if found >= limit:
                    return


def test_flat_utilities_on_toy_games_including_unreached_sets():
    for game in (matching_pennies, hidden_coin, kuhn_poker):
        root = game()
        pure = {(p, key): actions[0] for p, sets in enumerate(PCFRPlus(root).sets) for key, actions in sets.items()}
        for initial in (None, pure):  # pure strategies leave sets without reach: the fallback mean
            solver = PCFRPlus(root, backend="native", schedule="alternating", initial_actions=initial)
            sampler = OneSidedExpansion(3)
            for _ in range(6):
                assert dict(sampler.flat_utilities(solver)) == sampler.utilities(root, solver.policy())
                solver.step()


@pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"), reason="set FOW_TEST_RECORDS to a label folder")
@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_chess_growth_loop_agrees_with_python(schedule):
    """Python solver + Python sampler against native solver (batched rounds, incremental compile, flat utilities),
    one-sided growth every two rounds as the agents do; everything compared after every step."""
    from pair_a_prep.chess_search import build_chess_tree, expand_chess_tree
    from pair_a_prep.search_policies import heuristic_actions
    from pairb.material import MaterialEvaluator

    leaf = MaterialEvaluator()
    for turn in _growth_records(3):
        trees = [build_chess_tree(turn, leaf, depth=1, max_nodes=16384) for _ in range(2)]
        python, native = (PCFRPlus(tree.root, schedule=schedule, backend=backend,
                                   initial_actions=heuristic_actions(tree.root))
                          for tree, backend in zip(trees, ("python", "native")))
        samplers = [OneSidedExpansion(11), OneSidedExpansion(11)]
        expansions = 0
        for _ in range(30):
            python.run(2)
            native.run(2)
            _same(python, native)
            assert dict(samplers[1].flat_utilities(native)) == samplers[0].utilities(python.root, python.policy())
            native.policy = None  # select() must not build the profile on the native path
            proposals = [samplers[0].select(trees[0], python, 4), samplers[1].select(trees[1], native, 4)]
            del native.policy
            assert (proposals[0] is None) == (proposals[1] is None)
            assert samplers[0].rng.getstate() == samplers[1].rng.getstate()
            if proposals[0] is None:
                continue
            a, b = proposals
            assert a[0] == b[0] and a[1] == b[1] and a[3] == b[3] and a[2] == dict(b[2])
            for i, (solver, proposal) in enumerate(zip((python, native), proposals)):
                trees[i] = expand_chess_tree(trees[i], solver, leaf, max_nodes=16384,
                                             selected_paths=(proposal[0],), initialize_best=True)
                samplers[i].commit(proposal)
            expansions += 1
            assert samplers[0].__dict__.keys() == samplers[1].__dict__.keys()
            assert samplers[0].visits == samplers[1].visits and samplers[0].samples == samplers[1].samples
            _compiled_equal(native)
            _same(python, native)
        assert expansions >= 5


def _ply_signature(result):
    timing = ("elapsed_ms", "over_budget", "initial_ms", "solving_ms", "growth_ms", "finalizing_ms")
    return [(ply.player, ply.move, {k: v for k, v in ply.diagnostics.items() if k not in timing})
            for ply in result.plies]


@pytest.mark.parametrize("agent_kind", ["subgame", "anytime"])
def test_agents_play_the_same_game_on_both_backends(monkeypatch, agent_kind):
    """Round-count budgets (no clock), four plies with saved blueprints: the subgame agent runs its blended gadget
    (one round per batch, the controller rewriting the root distribution) from the second move on."""
    from fow_shared.evaluation import MatchConfig, play_game
    from pair_a_prep.anytime_agent import AnytimeConfig, AnytimePCFRAgent
    from pair_a_prep.belief_tracker import BeliefTracker
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pair_a_prep.rules_adapter import RulesReferee
    from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS

    config = AnytimeConfig(growth="one_sided", initial_depth=2, max_depth=4, rounds=40, rounds_per_stage=2,
                           final_rounds=2, stop_on_time=False, max_nodes=4000, max_evaluator_calls=512,
                           schedule="alternating")
    games = []
    for backend in ("python", "native"):
        monkeypatch.setattr(PCFRPlus, "BACKEND", backend)
        make = ChessSubgameAgent if agent_kind == "subgame" else AnytimePCFRAgent
        players = {side: make(ConstantLeaf(), config, KINGS) for side in ("white", "black")}
        trackers = {side: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for side in players}
        result = play_game(RulesReferee(KINGS), players, trackers,
                           MatchConfig(10000, 4, 17, "paper2021_fow_no_moves_draw_v1", "constant", 0))
        solvers = [p.last_solver for p in players.values()]
        assert all(s.backend == backend for s in solvers)
        games.append(_ply_signature(result))
    assert games[0] == games[1]
    assert all(diagnostics["expansions"] > 0 for _, _, diagnostics in games[1])
    if agent_kind == "subgame":
        assert any(diagnostics.get("projected_from_saved_tree") for _, _, diagnostics in games[1])
