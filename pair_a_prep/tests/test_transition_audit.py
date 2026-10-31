"""Counterfactual ratios against independent root/path arithmetic."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from pair_a_prep.chess_projection import SavedChessBlueprint, project_chess
from pair_a_prep.chess_search import build_chess_tree
from pair_a_prep.pcfr import PCFRPlus, PredictiveRMPlus
from pair_a_prep.transition_audit import audit_transition
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


def fixture(depth=3, nonuniform=False):
    old = turn_after()
    tree = build_chess_tree(old, ConstantLeaf(), initial_fen=KINGS, depth=depth)
    solver = PCFRPlus(tree.root)
    if nonuniform:
        for p in (0, 1):
            for key, actions in solver.sets[p].items():
                weights = np.arange(1, len(actions)+1, dtype=float)
                solver._strategy[p][key] = weights/weights.sum()
    saved = SavedChessBlueprint(old, tree, ((),), solver, .2)
    turn = turn_after(moves=("a1b1", "h8g8"))
    projected = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1,
                              max_nodes=5000, saved=saved)
    return saved, projected


def test_nonuniform_opponent_reach_cannot_be_replaced_by_one_own_cf_scale():
    saved, projected = fixture(nonuniform=True)
    before, before_root = deepcopy(saved.raw_solver.policy()), deepcopy(saved.tree.root)
    audit = audit_transition(saved, projected)
    assert len(audit["rows"]) == 9 and audit["fresh_roots"] == 0
    assert audit["normalizer"] == pytest.approx(3.)
    for row in audit["rows"]:
        own, opponent = row["candidate_moves"]
        source = saved.tree.continuations[0]
        x = before[0][source.infoset][own]
        y = before[1][source.children[own].infoset][opponent]
        assert row["source_cf_reach"] == pytest.approx([y, x])
        assert row["source_joint_reach"] == pytest.approx(x*y)
        assert row["target_raw_chance"] == pytest.approx(x/3)
        assert row["cf_scale_candidates"][1]["scale"] == pytest.approx(1/3)
    assert not audit["cf_scales"][0]["uniform_positive_ratios"]
    assert audit["cf_scales"][1]["uniform_positive_ratios"]
    assert audit["local_affine_roots"] == 9
    assert not audit["full_game_affine"]["verified"]
    assert not audit["accumulated_regret_transport_authorized"]
    assert saved.raw_solver.policy() == before and saved.tree.root == before_root


def test_uniform_instantaneous_ratios_still_do_not_authorize_cumulative_copy():
    saved, projected = fixture()
    audit = audit_transition(saved, projected)
    assert all(summary["uniform_positive_ratios"] for summary in audit["cf_scales"])
    assert not audit["accumulated_regret_transport_authorized"]
    assert not audit["full_game_affine"]["verified"]


def test_fresh_roots_and_rebuilt_cutoffs_have_distinct_audit_paths():
    saved, projected = fixture(depth=1)
    audit = audit_transition(saved, projected)
    assert audit["fresh_roots"] == 3
    assert all(row["source_path"] is None for row in audit["rows"])
    saved, projected = fixture(depth=2)
    audit = audit_transition(saved, projected)
    assert audit["fresh_roots"] == 0
    assert audit["local_affine_roots"] == 6
    assert sum(not row["local_affine"]["verified"] for row in audit["rows"]) == 3


def test_audit_rejects_forged_path_and_mass_metadata():
    saved, projected = fixture()
    bad = deepcopy(projected)
    bad.paths = ((),)+bad.paths[1:]
    with pytest.raises(ValueError, match="root identity"):
        audit_transition(saved, bad)
    bad = deepcopy(projected)
    bad.tree.root.probabilities["0"] += .1
    with pytest.raises(ValueError, match="normalized reaches"):
        audit_transition(saved, bad)


def test_equal_aggregate_regret_can_hide_different_reweighted_states():
    def first_feedback(weights, history_utilities):
        item = PredictiveRMPlus(2, predictive=False)
        item.next_strategy()
        item.observe(sum(w*np.array(u) for w, u in zip(weights, history_utilities)))
        return item
    histories = (((2., 0.), (0., 0.)), ((0., 0.), (2., 0.)))
    old = [first_feedback((.5, .5), utilities) for utilities in histories]
    new = [first_feedback((.9, .1), utilities) for utilities in histories]
    np.testing.assert_array_equal(old[0].regrets, old[1].regrets)
    np.testing.assert_array_equal(old[0].previous_utility, old[1].previous_utility)
    np.testing.assert_allclose(new[0].regrets, [.9, 0.])
    np.testing.assert_allclose(new[1].regrets, [.1, 0.])
    for item in new:
        item.next_strategy()
        item.observe([0., 1.])
    assert not np.allclose(new[0].next_strategy(), new[1].next_strategy())


def test_live_audit_preserves_moves_and_raw_policies():
    MaterialEvaluator = pytest.importorskip("pairb.material").MaterialEvaluator
    from fow_shared.evaluation import MatchConfig, play_game
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.belief_tracker import BeliefTracker
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pair_a_prep.rules_adapter import RulesReferee
    from pair_a_prep.transition_probe import AuditedAgent
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3, rounds=6,
        final_rounds=1, max_nodes=10000, max_evaluator_calls=512, stop_on_time=False)
    outputs = []
    audited = None
    for agent_type in (ChessSubgameAgent, AuditedAgent):
        agents = {side: agent_type(MaterialEvaluator(), config, KINGS) for side in ("white", "black")}
        trackers = {side: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for side in agents}
        result = play_game(RulesReferee(KINGS), agents, trackers,
            MatchConfig(10000, 4, 17, "paper_fow_v1_proposed", "material", 0))
        outputs.append(([(ply.player, ply.move) for ply in result.plies],
            {side: agent.last_result.decision.root_policy for side, agent in agents.items()}))
        assert result.stopped_at_ply_limit
        if agent_type is AuditedAgent:
            audited = [row["transition"] for agent in agents.values() for row in agent.trace if row["transition"]]
    assert outputs[0] == outputs[1]
    assert len(audited) == 2
    assert all(not audit["accumulated_regret_transport_authorized"] for audit in audited)


def test_probe_output_preserves_capped_null_outcomes_and_counterexample():
    pytest.importorskip("pairb.material")
    from pair_a_prep.transition_probe import run
    report = run(starts=(("kings", KINGS, 4),), seeds=(17,))
    assert report["summary"]["transitions"] == 2
    assert report["games"][0]["status"] == "capped" and report["games"][0]["outcome"] is None
    assert not report["cumulative_state_transfer_enabled"]
    example = report["aggregate_counterexample"]
    assert example["old_regrets"][0] == example["old_regrets"][1]
    assert example["target_regrets"][0] != example["target_regrets"][1]
    assert "fow_shared/values.py" in report["source_sha256"]
