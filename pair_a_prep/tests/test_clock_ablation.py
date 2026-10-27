"""Deterministic cooperative-clock limits and isolated purification controls."""

from dataclasses import replace

import pytest
import chess

from pair_a_prep import chess_search, chess_projection, chess_subgame_agent, one_sided
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.chess_search import SearchBudgetError
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


def clock_modules(monkeypatch, clock):
    for module in (chess_search, chess_projection, chess_subgame_agent, one_sided):
        monkeypatch.setattr(module, "perf_counter", lambda: clock[0])


@pytest.mark.parametrize("budget,rounds,elapsed,overrun", [(100, 2, 80, 0), (20, 1, 40, 1)])
def test_clock_guard_cannot_interrupt_an_inflight_round(monkeypatch, budget, rounds, elapsed, overrun):
    clock = [0.]
    clock_modules(monkeypatch, clock)
    original = chess_subgame_agent.PCFRPlus.step
    def step(solver):
        original(solver)
        clock[0] += .04
    monkeypatch.setattr(chess_subgame_agent.PCFRPlus, "step", step)
    config = AnytimeConfig(growth="one_sided", rounds=64, final_rounds=4)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    turn = replace(turn_after(), time_budget_ms=budget)
    decision = agent.act(turn)
    assert decision.diagnostics["solver_rounds_this_turn"] == rounds
    assert decision.diagnostics["over_budget"] == overrun
    assert decision.diagnostics["elapsed_ms"] == pytest.approx(elapsed)
    assert decision.diagnostics["submission_reserve_ms"] == budget*.1
    assert decision.diagnostics["stop:submission_reserve"] == 1


def test_inflight_evaluator_can_overrun_but_cannot_generate_a_label(monkeypatch):
    clock = [0.]
    clock_modules(monkeypatch, clock)
    class Slow(ConstantLeaf):
        def evaluate_children(self, fen):
            result = super().evaluate_children(fen)
            clock[0] += .2
            return result
    agent = ChessSubgameAgent(Slow(), AnytimeConfig(growth="one_sided"), KINGS)
    agent.reset("white", 17)
    turn = replace(turn_after(), time_budget_ms=20)
    decision = agent.act(turn)
    assert decision.diagnostics["fallback"] == 1
    assert decision.diagnostics["over_budget"] == 1
    assert decision.diagnostics["evaluator_calls"] == 1
    assert agent.saved is None and agent.last_result is None
    with pytest.raises(SearchBudgetError):
        agent.label(turn, "no-synthetic-label")


def test_fixed_work_purification_changes_only_played_policy_and_sampling():
    results = []
    for purify in (False, True):
        agent = ChessSubgameAgent(ConstantLeaf(0), AnytimeConfig(growth="one_sided",
            initial_depth=1, max_depth=1, rounds=12, final_rounds=2, stop_on_time=False), chess.STARTING_FEN, purify=purify)
        agent.reset("white", 17)
        results.append(agent.label(turn_after(fen=chess.STARTING_FEN), "purification-control"))
    assert results[0].decision.root_policy == results[1].decision.root_policy
    assert results[0].hypothesis_values == results[1].hypothesis_values
    assert results[0].root_value == results[1].root_value
    assert results[0].config_id != results[1].config_id
    played = [{k: v for k, v in result.decision.diagnostics.items() if k.startswith("played_policy:")}
              for result in results]
    assert played[0] != played[1]
    assert sum(v > 0 for v in played[0].values()) == 20
    assert sum(v > 0 for v in played[1].values()) <= 3


def test_evaluation_factory_exposes_and_identifies_ablation_settings():
    from pair_a_prep.evaluation_factories import SearchFactory
    defaults = SearchFactory({"search_mode": "subgame"}).load_model()
    raw = SearchFactory({"search_mode": "subgame", "purify": "false",
                         "submission_reserve_fraction": "0"}).load_model()
    assert defaults.purify and defaults.submission_reserve_fraction == .1
    assert not raw.purify and raw.submission_reserve_fraction == 0
    assert defaults.config_id != raw.config_id
    with pytest.raises(ValueError, match="purify"):
        SearchFactory({"search_mode": "subgame", "purify": "maybe"}).load_model()


@pytest.mark.parametrize("reserve", [-.1, .5, 1., float("nan"), float("inf")])
def test_reserve_range_is_enforced(reserve):
    with pytest.raises(ValueError, match="reserve fraction"):
        ChessSubgameAgent(ConstantLeaf(), submission_reserve_fraction=reserve)


def test_reserve_alone_changes_configuration_identity():
    a = ChessSubgameAgent(ConstantLeaf(), submission_reserve_fraction=0)
    b = ChessSubgameAgent(ConstantLeaf(), submission_reserve_fraction=.1)
    assert a.config_id != b.config_id


@pytest.mark.parametrize("mode", ["anytime", "retained", "fixed"])
def test_subgame_only_settings_are_not_silently_ignored(mode):
    from pair_a_prep.evaluation_factories import SearchFactory
    with pytest.raises(ValueError, match="require search_mode=subgame"):
        SearchFactory({"search_mode": mode, "purify": "false"}).load_model()
