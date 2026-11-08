"""A belief tracker that is exact until the state set reaches a tail threshold.

The measurements this answers to. Over all 2,386 Pair A turns of the exact-s16
arm, the number of distinct states the tracker held per turn was:

    median        188        p90      20,791
    mean       19,528        p99     451,806
    p75         2,717        max   2,199,651

So the belief is small on almost every turn and enormous on a few: 11 percent of
turns exceed the 17,264 states Obscuro reports as its average, and 0.5 percent
exceed the 10^6 it gives as a bound. The 63 of 100 games the exact arm lost to
the memory cap were not lost because exact belief is large, they were lost
because one turn in two hundred is.

What the existing pruned arm does about that, and why it is the wrong shape.
`pruned_tracker.PruningBeliefTracker` prunes whenever `population_size` exceeds
its cap, and `population_size` counts histories, not states -- it passes 10,000
within the first dozen plies and reaches 1e9 by the midgame and 3.2e21 by ply
103. A 10,000-history cap therefore binds on essentially every turn after the
opening, which is why that arm's belief peaks at 15,838 states where the exact
arm's peaks at 345,659. It pays the cost of drifting belief on the 99 percent of
turns where exactness was affordable anyway, and it measured 0.481 against the
exact arm's 0.635, a paired difference of 0.210 with a 95 percent interval of
[0.048, 0.387].

This tracker keys on `state_count` instead, which is the quantity that drives
memory (`len(self._nodes)`), and sets the threshold in the tail of the
distribution above rather than below its median. Below the threshold it does
nothing at all and the belief is bit-for-bit the exact one.

Why a history cap can enforce a state target. `BeliefTracker.prune(n)` samples n
histories and rebuilds the DAG from those alone, keying terminal nodes by
`node.key()`, so the surviving state set is at most one state per sampled history
and `state_count <= n` afterwards. Passing the state threshold as the history cap
is therefore sufficient; no search for the right cap is needed.

Pruning happens before the update rather than after, for two reasons. The
hypotheses handed to the search should come from the support the tracker carries
forward, which is the reason `pruned_tracker` gives. The other is mechanical:
`prune()` clears `last_update`, and the runner reads its per-ply diagnostics from
there, so a tracker that pruned after updating would report nothing for that ply.
Pruning first bounds the update's own peak at the threshold times the branching
factor, which at this threshold is the region the recorded maximum already sits
in.

What this gives up. `prune()` sets `_complete` false, so `support_complete`
reports false from the first prune onward, and that is accurate: a pruned belief
retains the true history with probability cap/population, which at these
populations is small. The claim is not that the belief stays exact after a prune.
It is that the prune happens on about one turn in seventy five instead of on all
of them, and that it keeps thirty times as much support when it does. The
threshold itself is derived in make_guard_arm.py from the measured per-update
growth factor, because this wrapper reacts one update late and the peak is the
threshold times that factor.
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
        from pair_a_prep.evaluation_factories import HistoryTrackerFactory

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
