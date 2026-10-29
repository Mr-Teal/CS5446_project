"""Frozen target identity, warm/cold state differences and additional-round accounting."""

from copy import deepcopy

import numpy as np
import pytest

from pair_a_prep.chess_projection import SavedChessBlueprint, project_chess
from pair_a_prep.chess_search import build_chess_tree
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.frozen_search import compare_frozen, initialize_frozen_solver, state_digest
from pair_a_prep.rules_adapter import RulesAdapter
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


def fixture(schedule="alternating"):
    old = turn_after()
    tree = build_chess_tree(old, ConstantLeaf(), initial_fen=KINGS, depth=3)
    solver = PCFRPlus(tree.root, schedule=schedule)
    solver.run(3)
    own = max(solver.policy()[0][tree.root_infoset], key=solver.policy()[0][tree.root_infoset].get)
    rules = RulesAdapter()
    after = rules.apply_move(rules.initial_state(KINGS), own)
    opponent = rules.legal_moves(after)[0]
    saved = SavedChessBlueprint(old, tree, ((),), solver, .2)
    turn = turn_after(moves=(own, opponent))
    projection = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1,
                              max_nodes=5000, saved=saved)
    return saved, projection


@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_methods_share_target_and_receive_equal_new_rounds_without_source_mutation(schedule, mode):
    saved, projection = fixture(schedule)
    before = state_digest(saved.raw_solver)
    result = compare_frozen(saved, projection, mode=mode, checkpoints=(0, 1, 3), evaluator_name="constant")
    methods = result["methods"]
    assert len({method["target_tree_sha256"] for method in methods}) == 1
    assert methods[0]["retained_infosets"][0] > 0
    assert [method["initial_rounds"] for method in methods] == [3, 0, 3]
    for method in methods:
        assert [row["additional_rounds"] for row in method["checkpoints"]] == [0, 1, 3]
        assert method["checkpoints"][-1]["solver_rounds"] == method["initial_rounds"]+3
        assert method["checkpoints"][-1]["solver_utility_traversals"] > 0
        for row in method["checkpoints"]:
            for profile in row["profiles"].values():
                assert profile["security"]["finite_gap"] >= 0
    assert result["evaluator_calls_during_comparison"] == 0
    assert result["source_unchanged"] and state_digest(saved.raw_solver) == before
    assert compare_frozen(saved, projection, mode=mode, checkpoints=(0, 1, 3), evaluator_name="constant") == result


def test_warm_actually_copies_state_while_cold_does_not():
    saved, projection = fixture()
    target = projection.bridge("maxmargin", "constant").gadget.tree
    warm, retained = initialize_frozen_solver(saved.raw_solver, projection, target, "heuristic_warm")
    cold, _ = initialize_frozen_solver(saved.raw_solver, projection, target, "seeded_cold")
    for key in retained[0]:
        np.testing.assert_array_equal(warm.minimizers[0][key].regrets, saved.raw_solver.minimizers[0][key].regrets)
        np.testing.assert_array_equal(warm._sums[0][key], saved.raw_solver._sums[0][key])
    assert all(np.all(item.regrets == 0) for player in cold.minimizers for item in player.values())
    assert all(np.all(value == 0) for player in cold._sums for value in player.values())


def test_bad_checkpoints_are_rejected():
    saved, projection = fixture()
    for checkpoints in ((1, 2), (0, 2, 1), (0, 0), (0, True)):
        with pytest.raises(ValueError, match="checkpoints"):
            compare_frozen(saved, projection, checkpoints=checkpoints)


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_reported_nonconstant_gaps_match_independent_normal_form_oracle(mode):
    from types import SimpleNamespace
    from pair_a_prep.gadgets import build_gadget, SubgameRoot
    from pair_a_prep.toy_games import Node, terminal, behavioral_nash_gap
    root = Node(player=0, infoset="I", children={
        "a": Node(player=1, infoset="J", children={"x": terminal(.75), "y": terminal(-.5)}),
        "b": Node(player=1, infoset="J", children={"x": terminal(-.25), "y": terminal(1.)})})
    old = PCFRPlus(root, schedule="alternating")
    old.run(5)
    saved = SimpleNamespace(raw_solver=old)
    projection = SimpleNamespace(boundaries=True, root_ids=("r",), current_ids=("r",), groups=("G",),
        tree=SimpleNamespace(continuations=(root,), root_infoset="I", nodes=7), audit={},
        turn=SimpleNamespace(belief=SimpleNamespace(hypotheses=(SimpleNamespace(weight=1.),))),
        bridge=lambda mode, evaluator: SimpleNamespace(gadget=build_gadget(
            [SubgameRoot("r", "G", root, 1.)], {"G": .125}, mode)))
    target = projection.bridge(mode, "toy").gadget.tree
    result = compare_frozen(saved, projection, mode=mode, checkpoints=(0, 1, 4), evaluator_name="toy")
    for method in result["methods"]:
        solver, _ = initialize_frozen_solver(old, projection, target, method["method"])
        done = 0
        for point in method["checkpoints"]:
            solver.run(point["additional_rounds"]-done)
            done = point["additional_rounds"]
            for name, average in (("last", False), ("average", True)):
                expected = behavioral_nash_gap(target, solver.policy(average))
                assert point["profiles"][name]["security"]["finite_gap"] == pytest.approx(expected)
    warm = result["methods"][0]["checkpoints"]
    cold = result["methods"][1]["checkpoints"]
    assert any(abs(a["profiles"]["last"]["security"]["finite_gap"]-
                   b["profiles"]["last"]["security"]["finite_gap"]) > 1e-8 for a, b in zip(warm, cold))


def test_snapshot_collection_preserves_source_moves_and_raw_policy():
    MaterialEvaluator = pytest.importorskip("pairb.material").MaterialEvaluator
    from fow_shared.evaluation import MatchConfig, play_game
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.belief_tracker import BeliefTracker
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pair_a_prep.frozen_search_probe import SnapshotAgent
    from pair_a_prep.rules_adapter import RulesReferee
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3, rounds=6,
        final_rounds=1, max_nodes=10000, max_evaluator_calls=512, stop_on_time=False)
    outputs = []
    for cls in (ChessSubgameAgent, SnapshotAgent):
        agents = {side: cls(MaterialEvaluator(), config, KINGS) for side in ("white", "black")}
        trackers = {side: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for side in agents}
        game = play_game(RulesReferee(KINGS), agents, trackers,
            MatchConfig(10000, 4, 17, "paper_fow_v1_proposed", "material", 0))
        outputs.append(([row.move for row in game.plies],
            {side: agent.last_result.decision.root_policy for side, agent in agents.items()}))
        if cls is SnapshotAgent:
            assert sum(len(agent.snapshots) for agent in agents.values()) == 2
    assert outputs[0] == outputs[1]


def test_offline_target_preparation_enforces_source_evaluator_call_cap():
    from pair_a_prep.frozen_search_probe import PreparationLeaf
    from pair_a_prep.chess_search import SearchBudgetError
    leaf = PreparationLeaf(ConstantLeaf(), 1)
    assert leaf.evaluate_children(KINGS)
    assert leaf.calls == 1
    with pytest.raises(SearchBudgetError, match="preparation evaluator limit"):
        leaf.evaluate_children(KINGS)
    assert leaf.calls == 1
