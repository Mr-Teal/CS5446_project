"""Opt-in exact-or-fail policy for the evaluation runner's tracker interface."""

from time import perf_counter

from .belief_tracker import BeliefTracker


class TrackingBudgetError(RuntimeError):
    """The configured policy could not supply a complete uniform belief."""


class BudgetedExactTracker:
    """Resume within explicit cooperative limits; never return partial support.

    Each update has one total wall-time allowance shared by its first call and
    all resumes. Memory is the tracker's logical allocation budget, not RSS.
    No pruning, hidden-board recovery or fallback action is performed.
    """

    evaluation_policy = "budgeted-exact"

    def __init__(self, tracker: BeliefTracker, *, slice_ms, total_ms, memory_mb, max_resumes):
        self.tracker = tracker
        self.slice_ms, self.total_ms = slice_ms, total_ms
        self.memory_mb, self.max_resumes = memory_mb, max_resumes
        self.last_update = None
        self.update_calls = 0
        self.policy_stop = None

    @property
    def support_complete(self):
        return self.tracker.support_complete

    def reset(self, player, seed):
        self.tracker.reset(player, seed)
        self.last_update = None
        self.update_calls = 0
        self.policy_stop = None

    def _fail(self, reason):
        self.policy_stop = reason
        result = self.last_update
        status = result.status if result is not None else "no_candidate"
        raise TrackingBudgetError(
            f"budgeted-exact tracking stopped: {reason}; status={status}; "
            f"calls={self.update_calls}; partial beliefs are not submitted")

    def update(self, observation, own_move=None):
        began = perf_counter()
        self.last_update = None
        self.update_calls = 0
        self.policy_stop = None
        while True:
            remaining = self.total_ms - (perf_counter() - began) * 1000
            if remaining <= 0:
                self._fail("total_time")
            budget = min(self.slice_ms, remaining)
            first = self.update_calls == 0
            self.update_calls += 1
            if first:
                result = self.tracker.update_budgeted(
                    observation, own_move, time_budget_ms=budget, memory_budget_mb=self.memory_mb)
            else:
                result = self.tracker.resume(time_budget_ms=budget, memory_budget_mb=self.memory_mb)
            self.last_update = result
            # Include output materialization and all resumes in the same limit.
            if (perf_counter() - began) * 1000 > self.total_ms:
                self._fail("total_time")
            if (result.status == "complete" and result.support_complete
                    and result.belief is not None and result.belief.weighting == "uniform"):
                return result.belief
            if result.stopped_by != "time":
                self._fail(result.stopped_by or "incomplete_support")
            if self.update_calls > self.max_resumes:
                self._fail("resume_limit")
