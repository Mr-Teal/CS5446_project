"""Material-backed integrated search on public positions and retained draw stacks."""

import json

import pytest

from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.subgame_validation import CASES, fixture_turn


POSITIONS = json.loads(CASES.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", POSITIONS, ids=lambda case: case["id"])
def test_integrated_search_exports_legal_raw_labels_and_true_terminal_overrides(case):
    MaterialEvaluator = pytest.importorskip("pairb.material").MaterialEvaluator
    turn, _ = fixture_turn(case)
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1,
        initial_depth=1, max_depth=2, max_nodes=1024, max_evaluator_calls=48, stop_on_time=False)
    agent = ChessSubgameAgent(MaterialEvaluator(), config, case["fen"])
    agent.reset(turn.observation.player, 17)
    record = agent.label(turn, "corpus-"+case["id"])
    record.decision.validate_for(turn.observation)
    assert set(case["required_moves"]) <= set(record.decision.root_policy)
    assert len(record.hypothesis_values) == 1
    assert record.root_value == pytest.approx(record.hypothesis_values[0])
    assert record.decision.diagnostics["fallback"] == 0
    root = agent.last_projection.tree.continuations[0]
    for move, reason in case.get("terminal_after", {}).items():
        child = root.children[move]
        assert child.payoff == (1. if reason == "king_capture" else 0.)
        assert not child.cutoff
    played = {key.removeprefix("played_policy:"): value for key, value in record.decision.diagnostics.items()
              if key.startswith("played_policy:")}
    assert sum(played.values()) == pytest.approx(1)
    assert sum(value > 0 for value in played.values()) <= 3


def test_declared_fow_ep_history_has_an_explicit_readiness_gate():
    from pair_a_prep.subgame_validation import rule_history_checks
    checks = rule_history_checks()
    assert checks[0]["expected_terminal"] is None
    from fow_shared import values
    expected = "passed" if hasattr(values, "fog_position_key") else "blocked_pending_PR37_shared_rule_fix"
    assert checks[0]["status"] == expected


def test_run_exports_capped_terminal_populations_and_complete_provenance():
    pytest.importorskip("pairb.material")
    from pair_a_prep.subgame_validation import run
    report = run(cases=POSITIONS[:1], starts=(("capped", "7k/8/8/8/8/8/8/K7 w - - 0 1", 2),
        ("terminal", "8/8/8/8/8/8/k7/K7 w - - 0 1", 1)), seeds=(17,))
    capped, terminal = report["games"]
    assert capped["status"] == "capped" and capped["outcome"] is None
    assert terminal["status"] == "terminal" and terminal["outcome"] == "white"
    assert len(capped["plies"]) == 2
    assert all(capped["peak_populations"][p] >= capped["final_populations"][p] for p in ("white", "black"))
    assert "fow_shared/values.py" in report["source_sha256"]
    assert report["rules_id"] == "paper_fow_v1_proposed"


def test_run_preserves_action_trace_when_tracker_capacity_interrupts_game():
    pytest.importorskip("pairb.material")
    from pair_a_prep.subgame_validation import run, PeakTracker
    from pair_a_prep.belief_tracker import BeliefCapacityError
    class LimitedTracker(PeakTracker):
        def update(self, observation, *args, **kwargs):
            if observation.ply >= 1:
                raise BeliefCapacityError("forced capacity regression")
            return super().update(observation, *args, **kwargs)
    report = run(cases=[], starts=(("capacity", "7k/8/8/8/8/8/8/K7 w - - 0 1", 4),),
                 seeds=(17,), tracker_type=LimitedTracker)
    game = report["games"][0]
    assert game["status"] == "tracker_capacity" and game["outcome"] is None
    assert game["plies"] is None and game["completed_action_count"] == 1
    assert len(game["actions"]) == 1
