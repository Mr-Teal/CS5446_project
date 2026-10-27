"""Selective history grafts, shared policies and seeded exploration contracts."""

from copy import deepcopy

import numpy as np
import pytest

from pair_a_prep.anytime_agent import AnytimeConfig, AnytimePCFRAgent
from pair_a_prep.chess_search import build_chess_tree, expand_chess_tree, SearchBudgetError
from pair_a_prep.one_sided import OneSidedExpansion
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after
from pair_a_prep.toy_games import Node, terminal


def test_support_mixture_and_other_player_unchanged():
    sampler = OneSidedExpansion(17)
    policy = {"a": 0.9, "b": 0.1, "c": 0.0}
    values = {"a": 0.0, "b": 0.2, "c": 0.8}
    assert sampler.distribution(0, "I", policy, values) == {"a": 0.25, "b": 0.25, "c": 0.5}
    assert sampler.distribution(1, "I", policy, values) == policy


def test_utilities_aggregate_hidden_histories_with_chance_weights_and_sign():
    root = Node(children={
        "A": Node(player=1, infoset="hidden", children={"x": terminal(1), "y": terminal(-1)}),
        "B": Node(player=1, infoset="hidden", children={"x": terminal(-1), "y": terminal(1)}),
    }, probabilities={"A": 0.8, "B": 0.2})
    solver = PCFRPlus(root)
    values = OneSidedExpansion(17).utilities(root, solver.policy())[(1, "hidden")]
    assert values == pytest.approx({"x": -0.6, "y": 0.6})


def test_variance_bonus_uses_population_variance_with_two_prior_samples():
    sampler = OneSidedExpansion(17)
    sampler.visits[(0, "I")] = {"a": 4, "b": 0}
    # Both variances are 1 from [-1,+1]. The bonus is .4 for a and 2 for b.
    assert sampler.distribution(0, "I", {"a": 1.0, "b": 0.0}, {"a": 1.0, "b": 0.0}) == {
        "a": 0.5, "b": 0.5}


def test_selective_growth_preserves_unselected_histories_and_old_regrets():
    tree = build_chess_tree(turn_after(), ConstantLeaf(), initial_fen=KINGS, depth=1)
    solver = PCFRPlus(tree.root, schedule="alternating")
    solver.run(3)
    old = {key: (item, item.regrets.copy()) for key, item in solver.minimizers[0].items()}
    sampler = OneSidedExpansion(17)
    proposal = sampler.select(tree, solver, 3)
    path = proposal[0]
    grown = expand_chess_tree(tree, solver, ConstantLeaf(), selected_paths=(path,), initialize_best=True)
    sampler.commit(proposal)
    assert sampler.events == 1 and sampler.explorer == 1
    assert set(tree.frontiers) - {path} <= set(grown.frontiers)
    assert path not in grown.frontiers
    assert len(grown.frontiers) == len(tree.frontiers) + 2
    for key, (item, regrets) in old.items():
        assert solver.minimizers[0][key] is item
        np.testing.assert_array_equal(item.regrets, regrets)
    for item in solver.minimizers[1].values():
        assert np.count_nonzero(item.strategy) == 1
        assert item._pending
    solver.run(3)


def test_failed_growth_is_atomic_for_sampler_and_solver():
    tree = build_chess_tree(turn_after(), ConstantLeaf(), initial_fen=KINGS, depth=1)
    solver = PCFRPlus(tree.root)
    sampler = OneSidedExpansion(19)
    before = deepcopy(sampler.__dict__)
    proposal = sampler.select(tree, solver, 3)
    with pytest.raises(SearchBudgetError):
        expand_chess_tree(tree, solver, ConstantLeaf(), selected_paths=(proposal[0],), deadline=0)
    assert sampler.events == 0 and sampler.visits == before["visits"]
    assert sampler.rng.getstate() == before["rng"].getstate()
    assert solver.root is tree.root


@pytest.mark.parametrize("player,moves", [("white", ()), ("black", ("a1b1",))])
def test_seeded_budgeted_agent_runs_for_both_colours(player, moves):
    turn = turn_after(moves=moves, player=player)
    outputs = []
    for _ in range(2):
        agent = AnytimePCFRAgent(ConstantLeaf(), AnytimeConfig(
            growth="one_sided", stop_on_time=False, rounds=12, rounds_per_stage=2,
            final_rounds=2, max_depth=3), KINGS)
        agent.reset(player, 17)
        result = agent.label(turn, "one-sided-check")
        result.decision.validate_for(turn.observation)
        assert result.decision.diagnostics["expansions"] > 0
        assert agent.name == "one-sided-pcfr-prototype-v1"
        outputs.append((result.decision.move, result.decision.root_policy, result.hypothesis_values))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_growth_seed_survives_until_first_feedback_after_completed_rounds(schedule):
    root = Node(player=0, infoset="I", children={
        "stay": terminal(0), "grow": Node(payoff=0, cutoff=True)})
    solver = PCFRPlus(root, schedule=schedule)
    solver.run(2)
    solver.expand({("grow",): Node(player=1, infoset="J", children={
        "best": terminal(0), "other": terminal(0)})}, initial_actions={(1, "J"): "best"})
    observed = []
    item = solver.minimizers[1]["J"]
    original = item.observe
    def observe(utilities):
        observed.append(item.strategy.copy())
        original(utilities)
    item.observe = observe
    solver.step()
    np.testing.assert_array_equal(observed[0], [1, 0])
