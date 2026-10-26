"""Budget fallback, continuing solver state, labels and shared-runner checks."""

from dataclasses import replace

import pytest

from fow_shared.evaluation import MatchConfig, play_game
from pair_a_prep.anytime_agent import AnytimeConfig, AnytimePCFRAgent
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.chess_search import SearchBudgetError, build_chess_tree, expand_chess_tree
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.rules_adapter import RulesReferee
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


class CountingLeaf(ConstantLeaf):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def evaluate_children(self, fen):
        self.calls += 1
        return super().evaluate_children(fen)


def agent(config=None, leaf=None, player="white"):
    result = AnytimePCFRAgent(leaf or ConstantLeaf(),
                             config or AnytimeConfig(stop_on_time=False), KINGS)
    result.reset(player, 17)
    return result


def test_agent_continues_same_solver_across_growth_then_finishes_rounds():
    config = AnytimeConfig(max_depth=2, rounds=8, rounds_per_stage=2,
                            final_rounds=2, stop_on_time=False)
    turn = turn_after()
    actual = agent(config)
    record = actual.label(turn, "warm-search")
    tree = build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS, depth=1)
    solver = PCFRPlus(tree.root, schedule="alternating")
    solver.run(2)
    tree = expand_chess_tree(tree, solver, ConstantLeaf())
    solver.run(6)
    assert actual.last_solver.policy() == solver.policy()
    assert actual.last_tree.root == tree.root
    assert record.decision.diagnostics["solver_rounds"] == 8
    assert record.decision.diagnostics["expansions"] == 1
    assert record.root_value == pytest.approx(sum(
        h.weight * v for h, v in zip(turn.belief.hypotheses, record.hypothesis_values)))


@pytest.mark.parametrize("limits,reason", [
    ({"max_nodes": 5}, "node_limit"),
    ({"max_evaluator_calls": 2}, "evaluator_limit"),
])
def test_failed_growth_retains_shallow_solver_and_finishes(limits, reason):
    leaf = CountingLeaf()
    actual = agent(AnytimeConfig(rounds=8, rounds_per_stage=2, final_rounds=2,
                                 stop_on_time=False, **limits), leaf)
    turn = turn_after()
    record = actual.label(turn, "limited")
    reference = PCFRPlus(build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS, depth=1).root,
                         schedule="alternating")
    reference.run(8)
    assert actual.last_solver.policy() == reference.policy()
    assert record.decision.diagnostics["growth_stop:" + reason] == 1
    assert record.decision.diagnostics["search_depth"] == 1
    assert record.decision.diagnostics["evaluator_calls"] == leaf.calls
    assert leaf.calls <= actual.config.max_evaluator_calls


def test_initial_budget_fallback_has_no_invented_labels():
    config = AnytimeConfig(initial_depth=2, max_evaluator_calls=1, stop_on_time=False)
    actual, turn = agent(config), turn_after()
    decision = actual.act(turn)
    decision.validate_for(turn.observation)
    assert decision.diagnostics["fallback"] == 1
    assert len(set(decision.root_policy.values())) == 1
    assert actual.last_result is None
    with pytest.raises(SearchBudgetError):
        actual.label(turn, "not-a-valid-label")


def test_invalid_evaluator_output_propagates_instead_of_silent_fallback():
    class Broken(ConstantLeaf):
        def evaluate_children(self, fen):
            raise RuntimeError("broken evaluator")
    actual = agent(leaf=Broken())
    with pytest.raises(RuntimeError, match="broken evaluator"):
        actual.act(turn_after())
    assert actual.last_result is None


def test_fixed_work_is_repeatable_for_black_with_hidden_histories():
    turn = turn_after(moves=("a1b1",), player="black")
    first, second = agent(player="black"), agent(player="black")
    a, b = first.label(turn, "repeat"), second.label(turn, "repeat")
    assert a.decision.move == b.decision.move
    assert a.decision.root_policy == b.decision.root_policy
    assert a.hypothesis_values == b.hypothesis_values
    assert a.config_id == b.config_id
    assert a.decision.diagnostics["search_nodes"] == b.decision.diagnostics["search_nodes"]


def test_cooperative_deadline_finishes_with_existing_tree(monkeypatch):
    import pair_a_prep.anytime_agent as module
    clock = [0.0]
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    class ClockLeaf(ConstantLeaf):
        def evaluate_children(self, fen):
            answer = super().evaluate_children(fen)
            clock[0] += 0.08
            return answer
    # Builder uses real clock; disable only its own independent wall-clock checks.
    original = module.build_chess_tree
    monkeypatch.setattr(module, "build_chess_tree", lambda *a, **kw:
                        original(*a, **{**kw, "deadline": None}))
    actual = agent(AnytimeConfig(rounds=8, rounds_per_stage=2), ClockLeaf())
    turn = replace(turn_after(), time_budget_ms=100)
    decision = actual.act(turn)
    assert decision.diagnostics["fallback"] == 0
    assert decision.diagnostics["growth_stop:growth_deadline"] == 1
    assert decision.diagnostics["search_depth"] == 1


def test_shared_runner_plays_bounded_short_game():
    config = AnytimeConfig(max_depth=2, rounds=4, rounds_per_stage=1,
                            final_rounds=1, stop_on_time=False)
    players = {p: AnytimePCFRAgent(ConstantLeaf(), config, KINGS) for p in ("white", "black")}
    trackers = {p: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for p in players}
    result = play_game(RulesReferee(KINGS), players, trackers,
                       MatchConfig(10000, 4, 17, "paper_fow_v1_proposed", "constant", 0))
    assert len(result.plies) == 4
    assert result.stopped_at_ply_limit
    assert all(player.last_result is not None for player in players.values())
