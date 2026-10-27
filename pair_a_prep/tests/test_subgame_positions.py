"""Material-backed integrated search on public positions and retained draw stacks."""

import json

import pytest
from pairb.material import MaterialEvaluator

from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.subgame_validation import CASES, fixture_turn


POSITIONS = json.loads(CASES.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", POSITIONS, ids=lambda case: case["id"])
def test_integrated_search_exports_legal_raw_labels_and_true_terminal_overrides(case):
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
