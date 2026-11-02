"""A belief tracker that is exact until the state set reaches a tail threshold.

The measurements this answers to. Over all 2,386 Pair A turns of the exact-s16
strength arm, the number of distinct states the tracker held per turn was:

    median        188        p90      20,791
    mean       19,528        p99     451,806
    p75         2,717        max   2,199,651

So the belief is small on almost every turn and enormous on a few: 11 percent of
turns exceed the 17,264 states Obscuro reports as its average, and 0.5 percent
exceed the 10^6 it gives as a bound. The 63 of 100 games the exact arm lost to
the memory cap were not lost because exact belief is large, they were lost
because one turn in two hundred is.

A history cap is the wrong shape for that. `population_size` counts histories,
not states: it passes 10,000 within the first dozen plies and 3.2e21 by ply 103,
so a 10,000-history cap binds on essentially every turn after the opening and
pays for a drifting belief on the 99 percent of turns where exactness was
affordable (0.481 against the exact arm's 0.635, paired difference 0.210).

This tracker keys on `state_count`, the quantity that drives memory
(`len(self._nodes)`), with the threshold in the tail of the distribution above.
Below the threshold it does nothing and the belief is bit-for-bit the exact one.

Why a history cap can enforce a state target: `BeliefTracker.prune(n)` samples n
histories and rebuilds the DAG from those alone, keying terminal nodes by
`node.key()`, so afterwards `state_count <= n`.

Pruning happens before the update, not after: the hypotheses handed to the search
come from the support the tracker carries forward, and `prune()` clears
`last_update`, which the runner reads for its per-ply diagnostics. Pruning first
bounds the update's own peak at the threshold times one update's growth factor
(measured up to 23x), which is how the threshold is sized to a memory cap:
reserve about two thirds of the cap for the belief at 1,444 bytes per state,
giving 96,000 for a 4.5 GB container, 175,000 for 8 GB and 300,000 for 15 GiB.

What this gives up. `prune()` sets `_complete` false, so `support_complete`
reports false from the first prune onward, and that is accurate: a pruned belief
retains the true history with probability cap/population. The claim is not that
the belief stays exact after a prune; it is that the prune happens on about one
turn in seventy five instead of on all of them.
"""
from __future__ import annotations


class TailGuardedBeliefTracker:
    """Exact belief, pruned only when the state set exceeds `max_states`."""

    def __init__(self, inner, max_states):
        if max_states < 1:
            raise ValueError("max_states must be positive")
        self._inner = inner
        self._max_states = max_states
        self.guards = 0
        self.guarded_states_away = 0

    # The runner and the search read diagnostics straight off the tracker, so
    # forward rather than enumerate an interface that is not ours to pin down.
    def __getattr__(self, name):
        return getattr(self._inner, name)

    def reset(self, player, seed, *args, **kwargs):
        self.guards = 0
        self.guarded_states_away = 0
        return self._inner.reset(player, seed, *args, **kwargs)

    def update(self, observation, own_move=None):
        states = self._inner.state_count
        if states > self._max_states:
            # prune() needs a current observation; the first update has none, and
            # on that turn state_count is 1 and this branch cannot be taken.
            self._inner.prune(self._max_states)
            self.guards += 1
            self.guarded_states_away += states - self._inner.state_count
        return self._inner.update(observation, own_move)


class Factory:
    """`tracker_factory` entry point. Adds `max_states` to the exact settings."""

    def __init__(self, settings):
        self.settings = settings

    def create_tracker(self, rules, initial_fen=None):
        from .evaluation_factories import HistoryTrackerFactory

        if "max_states" not in self.settings:
            raise ValueError("max_states is required for the tail-guarded tracker")
        policy = self.settings.get("tracker_policy", "exact").strip()
        if policy != "exact":
            # prune() is a BeliefTracker method; the budgeted wrapper does not
            # expose it, and stacking the two would confuse which limit bound.
            raise ValueError("the tail-guarded tracker requires tracker_policy=exact")
        passthrough = {k: v for k, v in self.settings.items() if k != "max_states"}
        inner = HistoryTrackerFactory(passthrough).create_tracker(rules, initial_fen)
        return TailGuardedBeliefTracker(inner, int(self.settings["max_states"]))
