"""Opt-in bounded history inference with private-stream replay recovery."""

from dataclasses import replace
from time import perf_counter

from .belief_tracker import BeliefTracker
from .evaluation_tracking import TrackingBudgetError


class BoundedHistoryTracker:
    """Uniformly prune complete paths, and rebuild only from private evidence.

    The retained support is capped after every successful ply. Expansion of a
    single ply and pruning/replay remain cooperative, not hard RSS deadlines.
    Recovery is bounded and may fail; no referee board or unseen move is used.
    """

    evaluation_policy = "bounded-history-replay-v1"

    def __init__(self, initial_fen=None, *, sample_size=4, max_histories=8192,
                 backend="native", total_ms=16000, rebuild_attempts=4):
        self.initial_fen = initial_fen
        self.sample_size, self.max_histories = sample_size, max_histories
        self.backend, self.total_ms = backend, total_ms
        self.rebuild_attempts = rebuild_attempts
        if type(max_histories) is not int or max_histories < sample_size:
            raise ValueError("tracker_max_histories must be >= sample_size")
        if type(rebuild_attempts) is not int or rebuild_attempts < 0:
            raise ValueError("tracker_rebuild_attempts must be nonnegative")
        if not 0 < total_ms < float("inf"):
            raise ValueError("tracker_total_ms must be positive and finite")
        self.tracker = self._new()
        self.last_update = None

    def _new(self):
        return BeliefTracker(self.initial_fen, sample_size=self.sample_size,
                             max_candidates=None, backend=self.backend)

    @property
    def support_complete(self):
        return self.tracker.support_complete

    def reset(self, player, seed):
        self.player, self.seed = player, seed
        self.tracker = self._new()
        self.tracker.reset(player, seed)
        self.stream = []
        self.prunes = self.rebuilds = self.update_calls = 0
        self.policy_stop = self.last_update = None

    def update(self, observation, own_move=None):
        started = perf_counter()
        deadline = started + self.total_ms / 1000
        self.last_update = self.policy_stop = None
        self.update_calls = 0
        prunes_before, rebuilds_before = self.prunes, self.rebuilds
        # Snapshot mutable visible-piece dictionaries for later replay.
        observation = replace(observation, visible_pieces=dict(observation.visible_pieces))
        inputs = self.stream + [(observation, own_move)]

        def advance(tracker, obs, move):
            remaining = (deadline - perf_counter()) * 1000
            if remaining <= 0:
                self.policy_stop = "total_time"
                raise TrackingBudgetError("bounded-history replay exceeded tracker_total_ms")
            self.update_calls += 1
            result = tracker.update_budgeted(obs, move, time_budget_ms=remaining)
            self.last_update = result
            if not result.expansion_complete or result.stopped_by == "time":
                self.policy_stop = "total_time"
                raise TrackingBudgetError("bounded-history update exhausted its time allowance")
            if result.belief is None:
                return None
            if tracker.population_size > self.max_histories:
                tracker.prune(self.max_histories)
                self.prunes += 1
                belief = tracker.sample_current()
            else:
                belief = result.belief
            self.last_update = replace(result, belief=belief,
                status="complete" if tracker.support_complete else "approximate",
                support_complete=tracker.support_complete,
                retained_count=tracker.population_size, state_count=tracker.state_count)
            if perf_counter() > deadline:
                self.policy_stop = "total_time"
                raise TrackingBudgetError("bounded-history pruning exceeded its time allowance")
            return belief

        belief = advance(self.tracker, observation, own_move)
        if belief is None:
            # A pruned path can be needed later. Try independent bounded beams
            # from the SAME complete private stream; never accept a stale belief.
            for _ in range(self.rebuild_attempts):
                self.rebuilds += 1
                candidate = self._new()
                candidate.reset(self.player, self.seed + 1000003 * self.rebuilds)
                for obs, move in inputs:
                    belief = advance(candidate, obs, move)
                    if belief is None:
                        break
                if belief is not None:
                    self.tracker = candidate
                    break
            else:
                self.policy_stop = "no_candidate"
                raise TrackingBudgetError("bounded-history replay found no consistent full path")
        self.stream = inputs
        self.prunes_this_update = self.prunes - prunes_before
        self.rebuilds_this_update = self.rebuilds - rebuilds_before
        return belief
