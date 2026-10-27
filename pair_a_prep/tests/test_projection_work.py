"""Preparation budgets and attempt-local evaluation reuse preserve history rules."""

from dataclasses import replace

import chess

from pair_a_prep import chess_search, chess_projection, chess_subgame_agent, one_sided
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.chess_search import HistoryRoot, _build_roots
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.rules_adapter import RuleState
from pair_a_prep.tests.test_chess_search import ConstantLeaf, KINGS, turn_after


def test_preparation_can_finish_after_growth_window_without_fabricating_fallback(monkeypatch):
    clock = [0.]
    for module in (chess_search, chess_projection, chess_subgame_agent, one_sided):
        monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    class CostLeaf(ConstantLeaf):
        def evaluate_children(self, fen):
            result = super().evaluate_children(fen)
            clock[0] += .015
            return result
    agent = ChessSubgameAgent(CostLeaf(), AnytimeConfig(growth="one_sided",
        rounds=8, final_rounds=2, rounds_per_stage=2), KINGS)
    agent.reset("white", 17)
    decision = agent.act(replace(turn_after(), time_budget_ms=20))
    assert decision.diagnostics["fallback"] == 0
    assert decision.diagnostics["evaluator_calls"] == 1
    assert decision.diagnostics["growth_stop:growth_deadline"] == 1
    assert agent.last_result is not None


def test_initial_projection_replays_candidates_once(monkeypatch):
    original = chess_projection.reconstruct_roots
    calls = []
    def replay(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(chess_projection, "reconstruct_roots", replay)
    # Calling build_chess_tree would invoke chess_search's independent replay.
    monkeypatch.setattr(chess_search, "reconstruct_roots", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("second candidate replay")))
    projection = chess_projection.project_chess(turn_after(), ConstantLeaf(),
        initial_fen=KINGS, depth=1, max_nodes=100)
    assert len(calls) == 1 and projection.tree.frontier_leaves == 3


def test_shared_evaluation_cache_does_not_cache_repetition_outcomes():
    board = chess.Board(KINGS)
    for move in ("a1b1", "h8g8", "b1a1", "g8h8", "a1b1", "h8g8", "b1a1"):
        board.push(chess.Move.from_uci(move))
    historical = HistoryRoot(RuleState(board, 7), ("white-memory", "black-memory"))
    no_history = HistoryRoot(RuleState(chess.Board(board.fen()), 7), historical.memories)
    cache = {}
    first = _build_roots((historical,), "black", (1.,), ConstantLeaf(), 1, 100, None,
                         evaluation_cache=cache)
    second = _build_roots((no_history,), "black", (1.,), ConstantLeaf(), 1, 100, None,
                          evaluation_cache=cache)
    assert first.evaluator_calls == 1 and second.evaluator_calls == 0
    assert first.continuations[0].children["g8h8"].payoff == 0
    assert not first.continuations[0].children["g8h8"].cutoff
    assert second.continuations[0].children["g8h8"].payoff == .4
    assert second.continuations[0].children["g8h8"].cutoff
