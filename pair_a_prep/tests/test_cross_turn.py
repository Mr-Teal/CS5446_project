"""History-safe root retention, floor replenishment and repeated live turns."""

from dataclasses import replace

import pytest

from fow_shared.contracts import Hypothesis
from fow_shared.evaluation import MatchConfig, play_game
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.chess_search import build_chess_tree
from pair_a_prep.cross_turn import replenish_histories, retain_tree, RetainedPCFRAgent
from pair_a_prep.rules_adapter import RulesReferee
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


def test_replenishment_keeps_history_identity_and_floor_is_not_cap():
    a = Hypothesis(KINGS, .5, "a", ("a1b1", "h8g8", "b1a1", "g8h8"))
    b = Hypothesis(KINGS, .5, "b", ("a1a2", "h8h7", "a2a1", "h7h8"))
    assert replenish_histories((a,), (a, b), 2, 17) == (a, b)
    assert replenish_histories((a, b), (), 1, 17) == (a, b)
    assert replenish_histories((a,), (), 5, 17) == (a,)


def test_retained_tree_matches_direct_history_reconstruction():
    old_turn = turn_after()
    old_tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=3)
    turn = turn_after(moves=("a1b1", "h8g8"))
    tree, audit = retain_tree(old_turn, old_tree, turn, ConstantLeaf(),
                              initial_fen=KINGS, depth=1, max_nodes=5000)
    reference = build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS, depth=1)
    assert tree.root == reference.root
    assert tree.nodes == reference.nodes
    assert tree.frontiers.keys() == reference.frontiers.keys()
    assert tree.evaluator_calls == 0 and audit["reused_roots"] == len(turn.belief.hypotheses)
    for path in tree.frontiers:
        assert tree.frontiers[path].state.fen == reference.frontiers[path].state.fen
        assert tree.frontiers[path].memories == reference.frontiers[path].memories


def test_missing_saved_descendants_are_fresh_and_changed_history_is_rejected():
    old_turn = turn_after()
    old_tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=1)
    turn = turn_after(moves=("a1b1", "h8g8"))
    tree, audit = retain_tree(old_turn, old_tree, turn, ConstantLeaf(),
                              initial_fen=KINGS, depth=1, max_nodes=5000)
    assert audit["fresh_roots"] == len(turn.belief.hypotheses) and tree.evaluator_calls > 0
    bad = replace(turn, history=(replace(turn.history[0], observation=replace(
        turn.history[0].observation, halfmove_clock=99)),) + turn.history[1:])
    with pytest.raises(ValueError, match="observation changed"):
        retain_tree(old_turn, old_tree, bad, ConstantLeaf(), initial_fen=KINGS, depth=1, max_nodes=5000)


@pytest.mark.parametrize("growth", ["uniform", "one_sided"])
def test_live_game_retains_state_and_reserves_new_rounds_each_turn(growth):
    config = AnytimeConfig(initial_depth=3, max_depth=3, rounds=4,
                            final_rounds=1, stop_on_time=False, max_nodes=2000, growth=growth)
    players = {side: RetainedPCFRAgent(ConstantLeaf(), config, KINGS) for side in ("white", "black")}
    trackers = {side: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for side in players}
    result = play_game(RulesReferee(KINGS), players, trackers,
                       MatchConfig(10000, 4, 17, "paper2021_fow_no_moves_draw_v1", "constant", 0))
    assert len(result.plies) == 4
    for player in players.values():
        diagnostics = player.last_result.decision.diagnostics
        assert diagnostics["solver_rounds_this_turn"] == 4
        assert diagnostics["solver_rounds"] == 8
        assert diagnostics["retention:reused_roots"] > 0
        assert diagnostics["retention:retained_infosets"] > 0
        player.reset(player._player, 19)
        assert player.saved is None


def test_mixed_reused_and_fresh_roots_restore_every_shallow_frontier():
    from pair_a_prep.chess_search import expand_chess_tree
    from pair_a_prep.pcfr import PCFRPlus
    old_turn = turn_after()
    old = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=2)
    solver = PCFRPlus(old.root)
    old = expand_chess_tree(old, solver, ConstantLeaf(),
        selected_paths=(("0", "a1b1", "h8h7"),), max_nodes=5000)
    turn = turn_after(moves=("a1b1", "h8g8"))
    tree, audit = retain_tree(old_turn, old, turn, ConstantLeaf(),
        initial_fen=KINGS, depth=2, max_nodes=5000)
    assert audit["reused_roots"] > 0 and audit["fresh_roots"] > 0
    assert audit["restored_frontiers"] > 0
    reference = build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS, depth=2)
    assert tree.root == reference.root
    assert min(len(path)-1 for path in tree.frontiers) == 2


def test_retained_restore_deduplicates_evaluator_work_across_frontiers():
    class CountingLeaf(ConstantLeaf):
        def __init__(self):
            super().__init__()
            self.calls = []
        def evaluate_children(self, fen):
            self.calls.append(fen)
            return super().evaluate_children(fen)
    leaf = CountingLeaf()
    config = AnytimeConfig(initial_depth=3, max_depth=3, rounds=4,
        final_rounds=1, stop_on_time=False, max_nodes=2000)
    agent = RetainedPCFRAgent(leaf, config, KINGS)
    agent.reset("white", 17)
    agent.solve(turn_after())
    leaf.calls.clear()
    agent.solve(turn_after(moves=("a1b1", "h8g8")))
    assert leaf.calls and len(leaf.calls) == len(set(leaf.calls))
