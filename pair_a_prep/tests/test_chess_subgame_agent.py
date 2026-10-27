"""Saved-tree I^2 chess projection, fresh roots and combined search mechanisms."""

from dataclasses import replace

import numpy as np
import pytest

from fow_shared.evaluation import MatchConfig, play_game
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.chess_projection import project_chess, SavedChessBlueprint
from pair_a_prep.chess_search import build_chess_tree, SearchBudgetError
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.rules_adapter import RulesReferee
from pair_a_prep.search_policies import purify_policy, StableSupport, heuristic_actions
from pair_a_prep.toy_games import Node, terminal
from pair_a_prep.tests.test_chess_search import KINGS, ConstantLeaf, turn_after, single_path_turn


@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_initial_best_action_is_published_and_receives_first_feedback(schedule):
    root = Node(player=0, infoset="I", children={"bad": terminal(-1), "best": terminal(1)})
    solver = PCFRPlus(root, schedule=schedule, initial_actions=heuristic_actions(root))
    assert solver.policy()[0]["I"] == {"bad": 0., "best": 1.}
    solver.step()
    assert solver.rounds == 1
    np.testing.assert_array_equal(solver.minimizers[0]["I"].regrets, [0, 0])
    # Alternating mode may publish a different successor after feedback. The
    # zero regret vector proves feedback used the seeded best action, not uniform.
    np.testing.assert_array_equal(solver.minimizers[0]["I"].previous_utility, [-1, 1])


def test_purification_preserves_raw_and_moves_excluded_mass_to_top():
    raw = {"a": .4, "b": .25, "c": .15, "d": .1, "e": .1}
    support = StableSupport()
    support.observe(raw, False)
    support.observe(raw, True)
    support.observe({**raw, "b": 0}, True)
    assert purify_policy(raw, "maxmargin", support.stable) == pytest.approx({
        "a": .75, "b": 0, "c": .15, "d": .1, "e": 0})
    assert purify_policy(raw, "resolve", support.stable) == {"a": 1., "b": 0., "c": 0., "d": 0., "e": 0.}
    assert purify_policy(raw, "maxmargin", None)["a"] == 1
    assert raw["b"] == .25


def test_projection_keeps_opponent_neighbours_and_current_labels_separate():
    old_turn = turn_after()
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=3)
    saved = SavedChessBlueprint(old_turn, tree, ((),), PCFRPlus(tree.root), .2)
    turn = turn_after(moves=("a1b1", "h8g8"))
    result = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1, max_nodes=2000, saved=saved)
    assert result.audit["retained"] == 9
    assert result.audit["outside_current"] == 6
    assert len(result.current_ids) == 3
    assert sum(result.boundaries.group_prior.values()) == pytest.approx(1)
    assert min(result.boundaries.group_prior.values()) > 0
    assert sum(r.reach_mass for r in result.boundaries.roots) == pytest.approx(3)
    for mode in ("resolve", "maxmargin"):
        bridge = result.bridge(mode, ConstantLeaf.name)
        PCFRPlus(bridge.gadget.tree).run(2)


def test_shallow_blueprint_adds_fresh_roots_with_explicit_boundaries():
    old_turn = turn_after()
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=1)
    saved = SavedChessBlueprint(old_turn, tree, ((),), PCFRPlus(tree.root), -.6)
    turn = turn_after(moves=("a1b1", "h8g8"))
    result = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1, max_nodes=2000, saved=saved)
    assert result.audit["retained"] == 0 and result.audit["fresh"] == 3
    assert set(result.boundaries.alternate_player0.values()) == {-.6}
    assert all(group.startswith("fresh-perfect-info:") for group in result.groups)
    assert result.audit["incomplete_cut"] == 3
    assert len(set(c.memories[1] for c in result.tree.history_roots)) == 3


def test_all_observed_opponent_sequences_outside_blueprint_support_use_uniform_prior():
    fen = "8/8/8/8/8/3k4/8/K7 w - - 0 1"
    old_turn = turn_after(fen=fen)
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=fen, depth=3)
    solver = PCFRPlus(tree.root)
    # The actual hypothetical opponent plays c2, although the blueprint puts
    # all opponent mass on e3. Our new observation distinguishes that move.
    for key, actions in solver.sets[1].items():
        solver._strategy[1][key][:] = 0
        solver._strategy[1][key][actions.index("d3e3")] = 1
    saved = SavedChessBlueprint(old_turn, tree, ((),), solver, .2)
    turn = single_path_turn(fen, ("a1b2", "d3c2"), "white")
    result = project_chess(turn, ConstantLeaf(), initial_fen=fen, depth=1, max_nodes=5000, saved=saved)
    assert result.boundaries.audit["all_zero_opponent_reach"]
    assert len(set(result.boundaries.group_prior.values())) == 1
    assert sum(result.boundaries.group_prior.values()) == pytest.approx(1)


@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_live_gadget_agent_runs_modes_growth_retention_and_raw_labels(schedule):
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=4,
        rounds=8, rounds_per_stage=2, final_rounds=2, stop_on_time=False,
        max_nodes=2000, max_evaluator_calls=256, schedule=schedule)
    players = {side: ChessSubgameAgent(ConstantLeaf(), config, KINGS) for side in ("white", "black")}
    trackers = {side: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for side in players}
    result = play_game(RulesReferee(KINGS), players, trackers,
        MatchConfig(10000, 4, 17, "paper2021_fow_no_moves_draw_v1", "constant", 0))
    assert len(result.plies) == 4
    for player in players.values():
        record = player.last_result
        assert player.last_bridge is not None
        assert len(record.hypothesis_values) == len(player.saved.turn.belief.hypotheses)
        assert record.root_value == pytest.approx(sum(
            h.weight*v for h, v in zip(player.saved.turn.belief.hypotheses, record.hypothesis_values)))
        assert record.decision.diagnostics["solver_rounds_this_turn"] == 8
        assert record.decision.diagnostics["projection:retained"] > 0
        assert all(-1 <= v <= 1 for v in record.hypothesis_values)
        assert sum(v > 0 for k, v in record.decision.diagnostics.items() if k.startswith("played_policy:")) <= 3


def test_failed_projection_does_not_replace_saved_blueprint():
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    agent.act(turn_after())
    saved = agent.saved
    agent.config = replace(config, max_evaluator_calls=1, initial_depth=2)
    turn = turn_after(moves=("a1b1", "h8g8"))
    decision = agent.act(turn)
    assert decision.diagnostics["fallback"] == 1
    assert agent.last_result is None and agent.saved is saved
    with pytest.raises(SearchBudgetError):
        agent.label(turn, "no-fabricated-labels")
