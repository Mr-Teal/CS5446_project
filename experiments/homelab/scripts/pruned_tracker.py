"""A belief tracker that is exact within each update and pruned between them.

This exists to answer one question with games rather than argument: does belief
exactness buy wins? BeliefTracker.prune(max_histories) samples uniformly over the
exact represented set and preserves the complete move paths of survivors, which is
what the subgame search requires, but nothing in the repository calls it. Rather
than edit the audited tracker this wraps it, the same way
evaluation_tracking.BudgetedExactTracker does, and it reuses
HistoryTrackerFactory so the rules and start-position validation stay in one place.

Pruning happens before each update rather than after, so the hypotheses handed to
the search are drawn from the support the tracker actually carries forward, not
from a set it is about to discard.

This is deliberately NOT what the paper does. Obscuro keeps every consistent
position and samples only the per-move search infoset, freshly, from that complete
set, so its belief never drifts. Pruning the belief retains the true history with
probability cap/population at each prune, and that compounds: replaying the
recorded games at cap 1,000 loses the true path even on games whose populations
peak below 2,100 states, and aborts one outright with "no descendants of retained
support". This arm measures what that costs in played games.
"""
from __future__ import annotations


class PruningBeliefTracker:
    """Exact updates over a support capped at `max_histories` between plies."""

    def __init__(self, inner, max_histories):
        if max_histories < 1:
            raise ValueError("max_histories must be positive")
        self._inner = inner
        self._max_histories = max_histories
        self.prunes = 0
        self.pruned_away = 0

    # The runner and the search read diagnostics straight off the tracker, so
    # forward rather than enumerate an interface that is not ours to pin down.
    def __getattr__(self, name):
        return getattr(self._inner, name)

    def reset(self, player, seed, *args, **kwargs):
        self.prunes = 0
        self.pruned_away = 0
        return self._inner.reset(player, seed, *args, **kwargs)

    def update(self, observation, own_move=None):
        population = self._inner.population_size
        if population > self._max_histories:
            self._inner.prune(self._max_histories)
            self.prunes += 1
            self.pruned_away += population - self._inner.population_size
        return self._inner.update(observation, own_move)


class Factory:
    """`tracker_factory` entry point. Adds `max_histories` to the exact settings."""

    def __init__(self, settings):
        self.settings = settings

    def create_tracker(self, rules, initial_fen=None):
        from pair_a_prep.evaluation_factories import HistoryTrackerFactory

        if "max_histories" not in self.settings:
            raise ValueError("max_histories is required for the pruning tracker")
        policy = self.settings.get("tracker_policy", "exact").strip()
        if policy != "exact":
            # prune() is a BeliefTracker method; the budgeted wrapper does not
            # expose it, and stacking the two would confuse which limit bound.
            raise ValueError("the pruning tracker requires tracker_policy=exact")
        passthrough = {k: v for k, v in self.settings.items() if k != "max_histories"}
        inner = HistoryTrackerFactory(passthrough).create_tracker(rules, initial_fen)
        return PruningBeliefTracker(inner, int(self.settings["max_histories"]))
