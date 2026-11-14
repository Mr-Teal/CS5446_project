"""Bounded support, honest approximation and private-stream recovery."""
from dataclasses import replace

import pytest

from pair_a_prep.bounded_tracking import BoundedHistoryTracker
from pair_a_prep.evaluation_tracking import TrackingBudgetError
from pair_a_prep.rules_adapter import RulesAdapter

FEN = "7k/8/8/8/8/8/8/K7 w - - 0 1"
R = RulesAdapter()


def test_pruning_preserves_paths_and_reset_restores_exact_support():
    tracker = BoundedHistoryTracker(FEN, sample_size=1, max_histories=1, backend="python")
    tracker.reset("white", 17)
    state = R.initial_state(FEN)
    for move in [None, "a1b1", "h8g8"]:
        if move:
            state = R.apply_move(state, move)
        belief = tracker.update(R.observe(state, "white"), move if move == "a1b1" else None)
    assert tracker.prunes == 1
    assert tracker.tracker.population_size == 1
    assert not tracker.support_complete
    assert belief.population_size is None
    assert belief.weighting == "uniform_over_returned_histories"
    h = belief.hypotheses[0]
    assert len(h.candidate_moves) == 2
    replay = R.initial_state(FEN)
    for event, move in zip(tracker.stream[1:], h.candidate_moves):
        replay = R.apply_move(replay, move)
        assert R.observe(replay, "white") == event[0]
    tracker.reset("white", 17)
    assert tracker.support_complete and tracker.prunes == tracker.rebuilds == 0
    assert not tracker.stream


def test_lost_support_rebuilds_from_all_private_observations(monkeypatch):
    tracker = BoundedHistoryTracker(FEN, sample_size=1, max_histories=1, backend="python")
    tracker.reset("white", 17)
    state = R.initial_state(FEN)
    tracker.update(R.observe(state, "white"))
    previous = tracker.last_update
    monkeypatch.setattr(tracker.tracker, "update_budgeted", lambda *a, **k:
        replace(previous, belief=None, status="no_candidate", support_complete=False,
                generated_valid_count=0, retained_count=0))
    state = R.apply_move(state, "a1b1")
    belief = tracker.update(R.observe(state, "white"), "a1b1")
    assert tracker.rebuilds == 1
    assert len(tracker.stream) == 2
    assert belief.hypotheses[0].candidate_moves == ("a1b1",)
    assert tracker.update_calls == 3  # Failed attempt, initial view, own move.


def test_exhausted_recovery_is_explicit_and_does_not_commit_stale_ply(monkeypatch):
    tracker = BoundedHistoryTracker(FEN, sample_size=1, max_histories=1,
                                    backend="python", rebuild_attempts=0)
    tracker.reset("white", 17)
    tracker.update(R.observe(R.initial_state(FEN), "white"))
    previous = tracker.last_update
    monkeypatch.setattr(tracker.tracker, "update_budgeted", lambda *a, **k:
        replace(previous, belief=None, status="no_candidate", support_complete=False,
                generated_valid_count=0, retained_count=0))
    with pytest.raises(TrackingBudgetError, match="no consistent full path"):
        tracker.update(R.observe(R.apply_move(R.initial_state(FEN), "a1b1"), "white"), "a1b1")
    assert len(tracker.stream) == 1 and tracker.policy_stop == "no_candidate"


def test_nonpositive_deadline_and_small_support_are_rejected():
    with pytest.raises(ValueError):
        BoundedHistoryTracker(FEN, total_ms=0, backend="python")
    with pytest.raises(ValueError):
        BoundedHistoryTracker(FEN, max_histories=1, sample_size=4, backend="python")


def test_factory_requires_explicit_policy_and_rejects_exact_budget_options():
    from pair_a_prep.evaluation_factories import HistoryTrackerFactory
    rules = type("Rules", (), {"name": "teal-rules-adapter"})()
    settings = dict(public_initial_fen=FEN, tracker_policy="bounded-history",
                    tracker_backend="python", tracker_max_histories="16",
                    sample_size="2", tracker_rebuild_attempts="3")
    tracker = HistoryTrackerFactory(settings).create_tracker(rules, FEN)
    assert isinstance(tracker, BoundedHistoryTracker)
    assert tracker.max_histories == 16 and tracker.rebuild_attempts == 3
    with pytest.raises(ValueError, match="bounded-history"):
        HistoryTrackerFactory(dict(settings, tracker_memory_mb="512")).create_tracker(rules, FEN)


def test_deadline_applies_before_work_and_does_not_submit_stale_belief(monkeypatch):
    import pair_a_prep.bounded_tracking as module
    tracker = BoundedHistoryTracker(FEN, sample_size=1, max_histories=1, backend="python")
    tracker.reset("white", 17)
    times = iter([0.0, 100.0])
    monkeypatch.setattr(module, "perf_counter", lambda: next(times))
    with pytest.raises(TrackingBudgetError, match="tracker_total_ms"):
        tracker.update(R.observe(R.initial_state(FEN), "white"))
    assert not tracker.stream and tracker.last_update is None


def test_prune_reuses_dag_positions_without_replaying_board_moves(monkeypatch):
    import chess
    from pair_a_prep.belief_tracker import BeliefTracker
    tracker = BeliefTracker(FEN, sample_size=1, backend="python")
    tracker.reset("white", 17)
    state = R.initial_state(FEN)
    for move in [None, "a1b1", "h8g8"]:
        if move:
            state = R.apply_move(state, move)
        tracker.update(R.observe(state, "white"), move if move == "a1b1" else None)
    assert tracker.population_size == 3
    def forbidden(*args, **kwargs):
        pytest.fail("prune replayed an already represented move")
    monkeypatch.setattr(chess.Board, "push", forbidden)
    tracker.prune(1)
    belief = tracker.sample_current()
    assert len(belief.hypotheses[0].candidate_moves) == 2
    assert tracker.population_size == 1
