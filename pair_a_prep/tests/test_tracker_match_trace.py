"""Whole-turn budget instrumentation and failed private-prefix retention."""

from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest

from pair_a_prep import benchmark_tracker_matches as module


@dataclass(frozen=True)
class Turn:
    observation: object
    time_budget_ms: int


@dataclass
class Decision:
    move: str


def setup(tmp_path, monkeypatch, *, limit=20):
    clock = [0.0]
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(module, "memory_usage", lambda: {})
    trace = module.MatchTrace(tmp_path, SimpleNamespace(seed=17), limit)
    trace.turn_started = 0.0
    return clock, trace


def test_agent_receives_remaining_budget_including_tracking(tmp_path, monkeypatch):
    clock, trace = setup(tmp_path, monkeypatch)
    received = []

    def act(turn):
        received.append(turn.time_budget_ms)
        clock[0] += 0.003
        return Decision("a1b1")

    agent = trace.agent(SimpleNamespace(act=act), "white")
    clock[0] = 0.009
    assert agent.act(Turn(SimpleNamespace(ply=0), 20)).move == "a1b1"
    assert 10 <= received[0] <= 11
    row = json.loads((tmp_path / "actions.jsonl").read_text())
    assert row["whole_turn_ms"] == pytest.approx(12)
    assert row["agent_ms"] == pytest.approx(3)
    assert not row["turn_over_budget"]


def test_late_agent_result_is_logged_then_rejected(tmp_path, monkeypatch):
    clock, trace = setup(tmp_path, monkeypatch)

    def act(turn):
        clock[0] = 0.021
        return Decision("a1b1")

    agent = trace.agent(SimpleNamespace(act=act), "white")
    with pytest.raises(module.TurnBudgetError):
        agent.act(Turn(SimpleNamespace(ply=0), 20))
    row = json.loads((tmp_path / "actions.jsonl").read_text())
    assert row["turn_over_budget"] and row["decision"]["move"] == "a1b1"


def test_exhausted_turn_does_not_start_agent(tmp_path, monkeypatch):
    clock, trace = setup(tmp_path, monkeypatch)
    clock[0] = 0.03
    agent = trace.agent(SimpleNamespace(act=lambda turn: pytest.fail("must not search")), "white")
    with pytest.raises(module.TurnBudgetError):
        agent.act(Turn(SimpleNamespace(ply=0), 20))


def test_failed_update_keeps_private_input_and_restores_policy_limit(tmp_path, monkeypatch):
    clock, trace = setup(tmp_path, monkeypatch)
    policy = SimpleNamespace(total_ms=15, last_update=None)

    def update(view, move):
        assert policy.total_ms == pytest.approx(5)
        raise RuntimeError("memory")

    inner = SimpleNamespace(tracker=policy, update=update, reset=lambda player, seed: None)
    tracker = trace.tracker(inner, "white")
    tracker.reset("white", 17)
    clock[0] = 0.015
    from pair_a_prep.rules_adapter import RulesAdapter
    rules = RulesAdapter()
    view = rules.observe(rules.initial_state(), "white")
    with pytest.raises(RuntimeError, match="memory"):
        tracker.update(view)
    assert policy.total_ms == 15
    row = json.loads((tmp_path / "private-stream.jsonl").read_text())
    assert row["observation"]["player"] == "white" and row["own_move"] is None
    assert json.loads((tmp_path / "updates.jsonl").read_text())["error"] == "RuntimeError: memory"
