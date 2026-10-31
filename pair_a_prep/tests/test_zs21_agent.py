from time import perf_counter
from copy import deepcopy

from pair_a_prep.zs21.agent import PaperAgent
from pair_a_prep.zs21.engine import Estimate
from pair_a_prep.zs21.model import Referee


class FixedEvaluator:
    def evaluate(self, boards, player, *, depth, deadline, scale):
        return tuple(Estimate(scale * .1, "test_fixture", depth) for _ in boards)


def test_cold_start_and_repeated_private_history_are_deterministic():
    results = []
    for _ in range(2):
        ref = Referee()
        agent = PaperAgent("white", 23, FixedEvaluator(), max_rounds=1)
        agent.observe(ref.observe("white"))
        result = agent.act(perf_counter() + 30)
        assert agent.trace["max_fow_depth"] >= 2
        assert result.diagnostics["roots"] == 1
        trace = deepcopy(agent.trace)
        # Wall-clock telemetry varies; every algorithmic trace field must match.
        attempts = [trace["initial_lp_precision_attempts"], trace["lp_precision_attempts"]]
        attempts.extend(r["lp_precision_attempts"] for r in trace["rounds"])
        checked = set()
        for group in attempts:
            for attempt in group:
                for call in attempt["lp_results"]:
                    if id(call) in checked:
                        continue
                    checked.add(id(call))
                    assert call.pop("seconds") >= 0
                    assert call["options"].pop("time_limit") > 0
        results.append((result.move, result.root_policy, trace))
        agent.close()
    assert results[0] == results[1]


def test_baseline_keeps_one_real_ply_and_deepens_engine():
    ref = Referee()
    agent = PaperAgent("black", 31, FixedEvaluator(), baseline=True, max_rounds=1)
    agent.observe(ref.observe("black"))
    ref.apply("e2e4")
    agent.observe(ref.observe("black"))
    result = agent.act(perf_counter() + 30)
    assert agent.trace["max_fow_depth"] == 1
    assert agent.trace["sf_depth"] == 2
    assert result.diagnostics["roots"] == 20


def test_both_observations_advance_before_second_own_decision():
    ref = Referee()
    agent = PaperAgent("white", 33, FixedEvaluator(), max_rounds=2)
    agent.observe(ref.observe("white"))
    result = agent.act(perf_counter() + 30)
    ref.apply(result.move)
    agent.observe(ref.observe("white"), result.move)
    ref.apply(ref.observe("black").legal_moves[0])
    agent.observe(ref.observe("white"))
    result = agent.act(perf_counter() + 30)
    assert agent.tracker.previous.ply == 2
    result.validate_for(ref.observe("white"))
