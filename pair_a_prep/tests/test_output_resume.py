"""Output interruptions must remain resumable without changing sampling/RNG."""

import pytest

from pair_a_prep import belief_tracker as module
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.rules_adapter import RulesAdapter

FEN = "7k/8/8/8/8/8/P7/K7 w - - 0 1"
RULES = RulesAdapter()


def signature(belief):
    return [(h.fen, h.history_id, h.candidate_moves, h.weight) for h in belief.hypotheses]


def setup():
    trackers = [BeliefTracker(FEN, sample_size=7, backend="python") for _ in range(2)]
    state = RULES.initial_state(FEN)
    for tracker in trackers:
        tracker.reset("white", 89)
        tracker.update(RULES.observe(state, "white"))
    state = RULES.apply_move(state, "a1b1")
    for tracker in trackers:
        tracker.update(RULES.observe(state, "white"), "a1b1")
    return trackers, RULES.apply_move(state, "h8g8")


@pytest.mark.parametrize("reason", ["time", "memory"])
def test_output_resume_restores_full_sample_and_next_update_rng(monkeypatch, reason):
    (reference, tracker), state = setup()
    observation = RULES.observe(state, "white")
    expected = reference.update(observation)
    with monkeypatch.context() as patch:
        if reason == "time":
            original = module.history_id

            def expire(*args):
                value = original(*args)
                patch.setattr(module, "perf_counter", lambda: 10**10)
                return value
            patch.setattr(module, "history_id", expire)
        else:
            original = tracker._make_belief

            def one_output(nodes, ply, complete, rng, deadline, cap, accounted):
                return original(nodes, ply, complete, rng, deadline,
                                accounted + 512 + 80 * (ply + 1), accounted)
            patch.setattr(tracker, "_make_belief", one_output)
        result = tracker.update_budgeted(observation, time_budget_ms=10000)
    assert result.status == "partial" and result.stopped_by == reason
    assert result.support_complete and result.expansion_complete and tracker.support_complete
    assert len(result.belief.hypotheses) == 1 and result.belief.population_size == 3
    result = tracker.resume(time_budget_ms=10000)
    assert result.status == "complete" and result.support_complete
    assert signature(result.belief) == signature(expected)
    for move in ("b1a1", "g8h8", "a2a3", "h8g8"):
        own = move if RULES.current_player(state) == "white" else None
        state = RULES.apply_move(state, move)
        observation = RULES.observe(state, "white")
        assert signature(tracker.update(observation, own)) == signature(reference.update(observation, own))


def test_advancing_after_output_only_interruption_keeps_exact_support(monkeypatch):
    (_, tracker), state = setup()
    original = module.history_id
    with monkeypatch.context() as patch:
        def expire(*args):
            value = original(*args)
            patch.setattr(module, "perf_counter", lambda: 10**10)
            return value
        patch.setattr(module, "history_id", expire)
        tracker.update_budgeted(RULES.observe(state, "white"), time_budget_ms=10000)
    state = RULES.apply_move(state, "b1a1")
    belief = tracker.update(RULES.observe(state, "white"), "b1a1")
    assert tracker.support_complete and belief.population_size == tracker.population_size
    assert belief.weighting == "uniform"


def test_completed_expansion_without_output_is_not_an_accepted_current_belief(monkeypatch):
    (_, tracker), state = setup()
    with monkeypatch.context() as patch:
        patch.setattr(tracker, "_make_belief", lambda *args: (None, "memory"))
        result = tracker.update_budgeted(RULES.observe(state, "white"))
    assert result.expansion_complete and result.belief is None
    assert not tracker.support_complete and tracker._previous.ply == 1
    assert tracker.resume().status == "complete" and tracker.support_complete
