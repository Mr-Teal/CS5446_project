"""Explicit evaluation policy: exact results, bounded retries, honest failures."""

from types import SimpleNamespace

import pytest

from pair_a_prep import evaluation_tracking as module
from pair_a_prep.evaluation_factories import HistoryTrackerFactory
from pair_a_prep.evaluation_tracking import BudgetedExactTracker, TrackingBudgetError
from pairb.rules import pick_rules

RULES = pick_rules("teal")
FEN = "7k/8/8/8/8/8/8/K7 w - - 0 1"


def create(**settings):
    return HistoryTrackerFactory({"public_initial_fen": FEN, **settings}).create_tracker(RULES, FEN)


def test_default_preserves_legacy_limit_and_explicit_policy_removes_it():
    assert create()._max_candidates == 2000
    tracker = create(tracker_policy="budgeted-exact")
    assert tracker.tracker._max_candidates is None
    assert create(max_candidates="none")._max_candidates is None
    assert create(tracker_policy="budgeted-exact", max_candidates="123").tracker._max_candidates == 123


@pytest.mark.parametrize("settings", [
    {"tracker_policy": "truncate"}, {"tracker_slice_ms": "1"},
    {"tracker_policy": "budgeted-exact", "tracker_total_ms": "0"},
    {"tracker_policy": "budgeted-exact", "tracker_slice_ms": "nan"},
    {"tracker_policy": "budgeted-exact", "tracker_memory_mb": "-1"},
    {"tracker_policy": "budgeted-exact", "tracker_max_resumes": "-1"},
])
def test_invalid_or_ignored_limits_are_rejected(settings):
    with pytest.raises(ValueError): create(**settings)


@pytest.mark.parametrize("limits,reason", [
    ({"tracker_slice_ms": "0", "tracker_max_resumes": "0"}, "resume_limit"),
    ({"tracker_memory_mb": "0"}, "memory"),
])
def test_no_candidate_fails_explicitly_and_reset_clears_diagnostics(limits, reason):
    tracker = create(tracker_policy="budgeted-exact", **limits)
    tracker.reset("white", 17)
    with pytest.raises(TrackingBudgetError): tracker.update(RULES.observe(RULES.initial_state(FEN), "white"))
    assert tracker.policy_stop == reason and tracker.last_update.belief is None
    tracker.reset("black", 18)
    assert tracker.last_update is None and tracker.update_calls == 0 and tracker.policy_stop is None


class ScriptedTracker:
    def __init__(self, complete_on=3):
        self.calls = 0
        self.complete_on = complete_on
        self.belief = SimpleNamespace(weighting="uniform")

    def update_budgeted(self, *args, **kwargs):
        self.calls += 1
        complete = self.calls == self.complete_on
        return SimpleNamespace(status="complete" if complete else "partial",
            support_complete=True, expansion_complete=True, belief=self.belief, stopped_by=None if complete else "time")

    resume = update_budgeted


def test_output_only_partial_results_are_resumed_instead_of_submitted():
    source = ScriptedTracker()
    tracker = BudgetedExactTracker(source, slice_ms=100, total_ms=2000, memory_mb=64, max_resumes=2)
    assert tracker.update(None) is source.belief
    assert tracker.update_calls == 3


def test_resume_limit_and_total_wall_time_include_all_calls(monkeypatch):
    tracker = BudgetedExactTracker(ScriptedTracker(), slice_ms=100, total_ms=2000, memory_mb=64, max_resumes=1)
    with pytest.raises(TrackingBudgetError, match="resume_limit"): tracker.update(None)
    assert tracker.update_calls == 2
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "perf_counter", lambda: clock.now)
    source = ScriptedTracker(1)
    original = source.update_budgeted
    def slow(*args, **kwargs):
        clock.now += .020
        return original(*args, **kwargs)
    source.update_budgeted = slow
    tracker = BudgetedExactTracker(source, slice_ms=100, total_ms=10, memory_mb=64, max_resumes=2)
    with pytest.raises(TrackingBudgetError, match="total_time"): tracker.update(None)


def test_explicit_unlimited_memory_preserves_default_and_completes_exact_update():
    assert create(tracker_policy="budgeted-exact").memory_mb == 64
    tracker = create(tracker_policy="budgeted-exact", tracker_memory_mb="none",
                     tracker_slice_ms="16000", tracker_total_ms="16000", tracker_max_resumes="0")
    assert tracker.memory_mb is None
    tracker.reset("white", 17)
    belief = tracker.update(RULES.observe(RULES.initial_state(FEN), "white"))
    assert tracker.support_complete and belief.weighting == "uniform"
    assert tracker.last_update.status == "complete"
