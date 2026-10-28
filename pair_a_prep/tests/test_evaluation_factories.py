"""The handoff must preserve public-start/rule boundaries and independent state."""

import pytest

from pairb.rules import pick_rules
from pair_a_prep.evaluation_factories import SearchFactory, HistoryTrackerFactory
from pair_a_prep.tests.test_chess_search import KINGS, turn_after


SETTINGS = dict(public_initial_fen=KINGS, solver_rounds="4", rounds_per_stage="1",
                final_rounds="1", max_depth="2", leaf_depth="0")


@pytest.mark.parametrize("mode", ["anytime", "fixed"])
def test_agent_factory_returns_independent_agents_and_valid_decisions(mode):
    a, b = [SearchFactory({**SETTINGS, "search_mode": mode}).load_model() for _ in range(2)]
    assert a is not b and a.evaluator is not b.evaluator
    try:
        for agent in (a, b):
            agent.reset("white", 17)
            agent.act(turn_after()).validate_for(turn_after().observation)
    finally:
        a.close()
        b.close()


def test_tracker_factory_makes_fresh_path_preserving_trackers():
    factory, rules = HistoryTrackerFactory(SETTINGS), pick_rules("teal")
    trackers = [factory.create_tracker(rules, KINGS) for _ in range(2)]
    assert trackers[0] is not trackers[1]
    for tracker in trackers:
        tracker.reset("white", 17)
        state = rules.initial_state(KINGS)
        tracker.update(rules.observe(state, "white"))
        state = rules.apply_move(state, "a1b1")
        tracker.update(rules.observe(state, "white"), "a1b1")
        state = rules.apply_move(state, "h8g8")
        belief = tracker.update(rules.observe(state, "white"))
        assert all(len(h.candidate_moves) == 2 for h in belief.hypotheses)


def test_mismatched_start_and_standin_rules_are_rejected():
    factory = HistoryTrackerFactory(SETTINGS)
    with pytest.raises(ValueError, match="public_initial_fen"):
        factory.create_tracker(pick_rules("teal"), None)
    with pytest.raises(ValueError, match="rules=teal"):
        factory.create_tracker(pick_rules("standin"), KINGS)


def test_material_depth_metadata_cannot_silently_name_an_engine_depth():
    with pytest.raises(ValueError, match="leaf_depth=0"):
        SearchFactory({**SETTINGS, "leaf_depth": "11"}).load_model()
