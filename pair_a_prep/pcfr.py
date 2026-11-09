"""PCFR+ on small perfect-recall two-player zero-sum trees with explicit growth.

Local PRM+ follows Farina, Kroer & Sandholm (AAAI 2021), Algorithm 5,
using utilities (the negative of their losses). See docs/pcfr.md for scheduling.

The prediction step (_prepare) walks the tree once per own-history depth with memoised finalised subtrees
instead of once per information set; the result is identical (see _prepare_fast and test_pcfr_fast.py), and
the per-infoset reference walk is kept as _prepare_reference. FOW_PCFR_FAST=0 in the environment, or
PCFRPlus(..., fast_prepare=False), selects the reference.

The round also runs natively (pcfr_kernel.cpp through _pcfr_native.py; build with
`python -m pair_a_prep.build_pcfr_kernel`), with the same results (test_pcfr_native.py). backend="auto" (the
default) uses the kernel when it is built and fast_prepare is on, "python" never, "native" always (an error if
the kernel is missing). FOW_PCFR_BACKEND in the environment sets the default; under it a solver constructed with
fast_prepare=False stays on Python. On the native backend run(n) performs the n rounds in one kernel call, and
expand() appends the grafted subtrees to the compiled tree instead of recompiling it (see _pcfr_native.py). On
the native path the state containers (minimizers, _strategy, _sums, _previous_opponent) are views of flat
arrays, so reading and writing them works as before; a solver whose
_utilities or a minimizer's observe/next_strategy was replaced on the instance (instrumentation) runs its rounds
in Python on those views.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import os
from dataclasses import replace
import json
from pathlib import Path
from typing import Mapping

import numpy as np

from .toy_games import (Node, behavioral_nash_gap, behavioral_value, hidden_coin,
                        information_sets, kuhn_poker, matching_pennies,
                        payoff_matrix, solve_matrix)


class PredictiveRMPlus:
    """Projected regret state and a last-utility-vector predictor.

    next_strategy/observe alternate strictly; prediction never changes the
    accumulated state. Returned arrays are detached from internal storage.
    """

    def __init__(self, actions: int, predictive: bool = True):
        if not isinstance(actions, int) or isinstance(actions, bool) or actions < 1:
            raise ValueError("actions must be a positive integer")
        self.predictive = predictive
        self.regrets = np.zeros(actions)
        self.previous_utility = np.zeros(actions)
        self.strategy = np.full(actions, 1 / actions)
        self._pending = False

    def next_strategy(self, prediction=None) -> np.ndarray:
        if self._pending:
            raise ValueError("observe the pending strategy first")
        prediction = self.previous_utility if prediction is None else np.asarray(prediction, dtype=float)
        if prediction.shape != self.regrets.shape or not np.all(np.isfinite(prediction)):
            raise ValueError("need one finite prediction per action")
        if not self.predictive:
            prediction = np.zeros_like(self.regrets)
        theta = np.maximum(self.regrets + prediction - self.strategy @ prediction, 0)
        self.strategy = theta / theta.sum() if theta.sum() > 0 else np.full(len(theta), 1 / len(theta))
        self._pending = True
        return self.strategy.copy()

    def observe(self, utilities) -> None:
        if not self._pending:
            raise ValueError("request a strategy before observing utilities")
        utilities = np.asarray(utilities, dtype=float)
        if utilities.shape != self.regrets.shape or not np.all(np.isfinite(utilities)):
            raise ValueError("need one finite utility per action")
        self.regrets = np.maximum(self.regrets + utilities - self.strategy @ utilities, 0)
        self.previous_utility = utilities.copy()
        self._pending = False


class PCFRPlus:
    """Full-tree CFR with one PRM+ minimizer per information set.

    Simultaneous rounds produce both strategies before observing either utility
    vector. Alternating rounds feed back and publish player 0, then player 1.
    Expand explicit cutoff leaves between complete rounds with expand().
    Existing information-set actions stay fixed. No sampling, pruning or
    chess-specific expansion policy is implemented.
    """

    FAST_PREPARE = os.environ.get("FOW_PCFR_FAST", "1") != "0"  # the level-wise prediction walk (see module docstring)
    BACKEND = os.environ.get("FOW_PCFR_BACKEND", "auto")  # auto, python or native (see module docstring)

    def __init__(self, root: Node, predictive: bool = True, averaging_power: int = 2,
                 schedule: str = "simultaneous", initial_actions=None, fast_prepare: bool | None = None,
                 backend: str | None = None):
        if schedule not in ("simultaneous", "alternating"):
            raise ValueError("schedule must be simultaneous or alternating")
        self.schedule = schedule
        if averaging_power not in (0, 1, 2):
            raise ValueError("averaging_power must be 0, 1 or 2")
        self.fast_prepare = self.FAST_PREPARE if fast_prepare is None else bool(fast_prepare)
        self.root = root
        self.sets, self._order, self._depth = self._index_tree(root)
        self._previous_opponent = [None, None]
        self.predictive = predictive
        self.averaging_power = averaging_power
        self.rounds = 0
        self.minimizers = tuple({key: PredictiveRMPlus(len(actions), predictive)
                                 for key, actions in sets.items()} for sets in self.sets)
        self._strategy = tuple({key: np.full(len(actions), 1 / len(actions))
                                for key, actions in sets.items()} for sets in self.sets)
        self._sums = tuple({key: np.zeros(len(actions)) for key, actions in sets.items()}
                           for sets in self.sets)
        self._initial_actions = dict(initial_actions or {})
        for (p, key), action in self._initial_actions.items():
            if p not in (0, 1) or key not in self.sets[p] or action not in self.sets[p][key]:
                raise ValueError("invalid initial action")
            strategy = self._strategy[p][key]
            strategy[:] = 0
            strategy[self.sets[p][key].index(action)] = 1
            self.minimizers[p][key].strategy = strategy.copy()
        self._native = None
        self._graft_index = None
        self.backend = self._resolve_backend(backend)
        if self.backend == "native":
            from ._pcfr_native import GraftIndex
            self._graft_index = GraftIndex(root)  # expand() indexes only the grafted subtrees
            self._native_compile()

    def _resolve_backend(self, backend):
        requested = self.BACKEND if backend is None else backend
        if requested not in ("auto", "python", "native"):
            raise ValueError("backend must be auto, python or native")
        if requested == "python":
            return "python"
        if not self.fast_prepare:
            if backend == "native":
                raise ValueError("the native backend implements the level-wise prepare; it needs fast_prepare")
            return "python"
        from ._pcfr_native import library
        if library() is None:
            if requested == "native":
                raise RuntimeError("the native PCFR+ kernel is not built or is stale: "
                                   "python -m pair_a_prep.build_pcfr_kernel")
            return "python"
        return "native"

    def _native_compile(self) -> None:
        """Flatten the tree and move the state into flat arrays (after __init__ and every expand)."""
        from ._pcfr_native import NativeState, library
        state = NativeState(self, library())
        state.bind(self)
        self._native = state

    def __deepcopy__(self, memo):
        result = object.__new__(type(self))
        memo[id(self)] = result
        for name, value in self.__dict__.items():
            result.__dict__[name] = None if name == "_native" else deepcopy(value, memo)
        if self._native is not None:
            result._native_compile()
        return result

    def _index_tree(self, root):
        sets = information_sets(root)
        histories = {}
        self._check_recall(root, ((), ()), histories)
        order = tuple(sorted(player_sets, key=lambda key: len(histories[(p, key)]), reverse=True)
                      for p, player_sets in enumerate(sets))
        # Own-history length of each infoset: the level at which _prepare_fast finalises its strategy.
        depth = tuple({key: len(histories[(p, key)]) for key in player_sets} for p, player_sets in enumerate(sets))
        return sets, order, depth

    def expand(self, replacements: Mapping[tuple[str, ...], Node], *, initial_actions=None) -> None:
        """Atomically replace cutoff leaves by subtrees at root-relative paths.

        Call only between run()/step() calls, never mutate nodes directly.
        Use one batch for related hidden histories. Existing action orders and
        perfect recall must be preserved. Empty batches are no-ops.
        """
        if not isinstance(replacements, Mapping):
            raise ValueError("expansion needs a mapping from action paths to subtrees")
        if not replacements:
            return
        for path, subtree in replacements.items():
            if not isinstance(path, tuple) or not all(isinstance(a, str) for a in path):
                raise ValueError("expansion paths must be tuples of action names")
            leaf = self.root
            for action in path:
                if action not in leaf.children:
                    raise ValueError("unknown expansion path: " + repr(path))
                leaf = leaf.children[action]
            if not leaf.cutoff or leaf.payoff is None:
                raise ValueError("expansion target must be a cutoff leaf: " + repr(path))
            information_sets(subtree)
            if subtree.payoff is not None:
                raise ValueError("expansion must introduce a nonterminal subtree")

        def graft(node, path, subtree):
            if not path:
                return deepcopy(subtree)
            children = dict(node.children)
            children[path[0]] = graft(children[path[0]], path[1:], subtree)
            return replace(node, children=children)

        root = self.root
        for path, subtree in replacements.items():
            root = graft(root, path, subtree)
        if self._graft_index is None:
            sets, order, depth = self._index_tree(root)
            for player in (0, 1):
                for key, actions in self.sets[player].items():
                    if sets[player].get(key) != actions:
                        raise ValueError("expansion must preserve existing infoset actions: " + key)
        else:  # native: the same index from the grafted subtrees alone
            (sets, order, depth), staged = self._graft_index.graft(self, root, tuple(replacements))

        added = tuple({key: PredictiveRMPlus(len(actions), self.predictive)
                       for key, actions in sets[player].items()
                       if key not in self.sets[player]} for player in (0, 1))
        for (player, key), action in (initial_actions or {}).items():
            if player not in (0, 1) or key not in sets[player] or action not in sets[player][key]:
                raise ValueError("initial action must belong to an introduced infoset")
            if key in added[player]:
                minimizer = added[player][key]
                minimizer.strategy[:] = 0
                minimizer.strategy[sets[player][key].index(action)] = 1
        strategies = ({}, {})
        sums = ({}, {})
        for player in (0, 1):
            for key, minimizer in added[player].items():
                # Alternating mode holds a published strategy awaiting feedback.
                strategies[player][key] = minimizer.strategy.copy()
                # Publish the heuristic policy with pending feedback, without
                # advancing PRM+ (which would turn a zero-regret state uniform).
                minimizer._pending = self.schedule == "alternating" and bool(self.rounds)
                sums[player][key] = np.zeros_like(minimizer.regrets)

        self.root, self.sets, self._order, self._depth = root, sets, order, depth
        if self._graft_index is not None:
            self._graft_index.commit(staged)
        incremental = self._native is not None and () not in replacements
        if incremental:
            self._native.extend(self, tuple(replacements), added, strategies)  # appends; no recompilation
        else:
            for player in (0, 1):
                self.minimizers[player].update(added[player])
                self._strategy[player].update(strategies[player])
                self._sums[player].update(sums[player])
            self._previous_opponent = [
                None if previous is None else {
                    **previous, **{key: value.copy() for key, value in strategies[1 - player].items()}}
                for player, previous in enumerate(self._previous_opponent)]
        if self.schedule == "simultaneous" or not self.rounds:
            self._initial_actions.update({(p, key): action for (p, key), action in (initial_actions or {}).items()
                                          if key in added[p]})
        if self._native is not None and not incremental:
            self._native_compile()  # the root itself was replaced: carries every set's state by key

    def _check_recall(self, node, histories, seen):
        if node.payoff is not None:
            return
        if node.player is not None:
            p = node.player
            key = (p, node.infoset)
            if key in seen and seen[key] != histories[p]:
                raise ValueError("perfect recall required: inconsistent own history at " + str(key))
            seen[key] = histories[p]
        for action, child in node.children.items():
            next_histories = list(histories)
            if node.player is not None:
                p = node.player
                next_histories[p] += ((node.infoset, action),)
            self._check_recall(child, tuple(next_histories), seen)

    def _utilities(self, player, opponent=None):
        values = {key: np.zeros(len(actions)) for key, actions in self.sets[player].items()}

        def visit(node, counterfactual_reach):
            if node.payoff is not None:
                return node.payoff if player == 0 else -node.payoff
            if node.player is None:
                return sum(prob * visit(node.children[action], counterfactual_reach * prob)
                           for action, prob in node.probabilities.items())
            p = node.player
            strategy = (opponent if p != player and opponent is not None else self._strategy[p])[node.infoset]
            action_values = np.array([
                visit(child, counterfactual_reach * (strategy[i] if p != player else 1))
                for i, child in enumerate(node.children.values())])
            if p == player:
                # Aggregate all hidden nodes BEFORE projecting the infoset's regrets.
                values[node.infoset] += counterfactual_reach * action_values
            return float(strategy @ action_values)

        visit(self.root, 1.0)
        return values

    def _accumulate_average(self, player, weight):
        seen = set()

        def visit(node, own_reach):
            if node.payoff is not None:
                return
            if node.player == player:
                strategy = self._strategy[player][node.infoset]
                if node.infoset not in seen:
                    self._sums[player][node.infoset] += weight * own_reach * strategy
                    seen.add(node.infoset)
                for i, child in enumerate(node.children.values()):
                    visit(child, own_reach * strategy[i])
            else:
                for child in node.children.values():
                    visit(child, own_reach)

        visit(self.root, 1.0)

    def _prepare(self, player) -> None:
        # Appendix F: predict sequence-form utility using the previous
        # opponent strategy, then propagate through NEW own descendants.
        # Reusing the old local counterfactual vector misses this dependency.
        previous = self._previous_opponent[player]
        if previous is None or not self.fast_prepare:
            self._prepare_reference(player, previous)
        else:
            self._prepare_fast(player, previous)

    def _publish(self, player, key, prediction) -> None:
        """Advance one infoset's minimizer with its prediction and apply a pending initial action."""
        minimizer = self.minimizers[player][key]
        self._strategy[player][key] = minimizer.next_strategy(prediction)
        action = self._initial_actions.pop((player, key), None)
        if action is not None:
            self._strategy[player][key][:] = 0
            self._strategy[player][key][self.sets[player][key].index(action)] = 1
            minimizer.strategy = self._strategy[player][key].copy()

    def _prepare_reference(self, player, previous) -> None:
        """One full-tree walk per infoset, deepest first, so each prediction sees the strategies already
        published for its own descendants. O(infosets x tree) per round; kept as the reference."""
        for key in self._order[player]:
            prediction = (np.zeros_like(self.minimizers[player][key].regrets) if previous is None
                          else self._utilities(player, previous)[key])
            self._publish(player, key, prediction)

    def _prepare_fast(self, player, previous) -> None:
        """The same predictions in one walk per own-history depth.

        An infoset's prediction depends on the previous opponent strategy and on the strategies of its OWN
        descendants, never on its ancestors (own reach is 1 in the counterfactual) or on same-depth infosets
        (disjoint subtrees). So the levels are processed deepest first, every infoset of a level is published
        after that level's walk, and the value of an own node whose infoset is already final is memoised, so
        later walks stop there. Floating-point operations happen in the same order as in the reference.
        """
        depth_of = self._depth[player]
        levels = {}
        for key in self._order[player]:  # already sorted by depth, deepest first
            levels.setdefault(depth_of[key], []).append(key)
        strategies, sets = self._strategy, self.sets[player]
        memo = {}
        for depth in sorted(levels, reverse=True):
            keys = levels[depth]
            values = {key: np.zeros(len(sets[key])) for key in keys}

            def visit(node, counterfactual_reach):
                if node.payoff is not None:
                    return node.payoff if player == 0 else -node.payoff
                cached = memo.get(id(node))
                if cached is not None:
                    return cached
                if node.player is None:
                    return sum(prob * visit(node.children[action], counterfactual_reach * prob)
                               for action, prob in node.probabilities.items())
                p = node.player
                if p == player:
                    strategy = strategies[p][node.infoset]
                    action_values = np.array([visit(child, counterfactual_reach) for child in node.children.values()])
                    if node.infoset in values:
                        values[node.infoset] += counterfactual_reach * action_values
                    value = float(strategy @ action_values)
                    if depth_of[node.infoset] > depth:  # published at an earlier level: final for this round
                        memo[id(node)] = value
                    return value
                strategy = previous[node.infoset]
                action_values = np.array([visit(child, counterfactual_reach * strategy[i])
                                          for i, child in enumerate(node.children.values())])
                return float(strategy @ action_values)

            visit(self.root, 1.0)
            for key in keys:
                self._publish(player, key, values[key])

    def _observe(self, player) -> None:
        utilities = self._utilities(player)
        for key, minimizer in self.minimizers[player].items():
            minimizer.observe(utilities[key])
        self._previous_opponent[player] = {
            key: value.copy() for key, value in self._strategy[1 - player].items()}

    def step(self) -> None:
        native = self._native
        if native is not None and not native.instrumented and "_utilities" not in self.__dict__:
            native.step(self)
            return
        if self.schedule == "simultaneous":
            for player in (0, 1):
                self._prepare(player)
            for player in (0, 1):
                self._observe(player)
        else:
            if self.rounds == 0:
                for player in (0, 1):
                    self._prepare(player)
            # Feed back the held policy, then immediately publish its successor.
            # Player 1 observes the NEW player-0 policy in this same round.
            for player in (0, 1):
                self._observe(player)
                self._prepare(player)
        self.rounds += 1
        for player in (0, 1):
            self._accumulate_average(player, self.rounds ** self.averaging_power)

    def run(self, rounds: int, record=None):
        """Perform this many additional rounds; continuation preserves all state.

        record=(player, key) returns one row per round: that information set's published strategy after the
        round, in action order (policy()[player][key] after each step). On the native backend the rounds run in
        one kernel call with the results of `rounds` step() calls, unless step() or the instrumented methods were
        replaced, in which case they go through step().
        """
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 0:
            raise ValueError("rounds must be a nonnegative integer")
        native = self._native
        if (native is not None and not native.instrumented and "_utilities" not in self.__dict__
                and "step" not in self.__dict__ and type(self).step is _STEP):
            return native.run(self, rounds, record)
        trace = None if record is None else np.empty((rounds, len(self.sets[record[0]][record[1]])))
        for k in range(rounds):
            self.step()
            if trace is not None:
                trace[k] = self._strategy[record[0]][record[1]]
        return trace

    def policy(self, average: bool = False) -> tuple:
        """Detached behavioral strategies in the toy oracle's input format.

        Before averaging has positive reach, use the current local strategy.
        Simultaneous mode returns the profile used in the last round. Alternating
        mode returns the latest published profile, ready for the next feedback.
        """
        policies = []
        for player in (0, 1):
            policy = {}
            for key, actions in self.sets[player].items():
                total = self._sums[player][key]
                strategy = total / total.sum() if average and total.sum() > 0 else self._strategy[player][key]
                policy[key] = dict(zip(actions, map(float, strategy)))
            policies.append(policy)
        return tuple(policies)

    def metrics(self) -> dict:
        report = {"rounds": self.rounds, "schedule": self.schedule}
        for name, average in (("last", False), ("average", True)):
            policy = self.policy(average)
            report[name] = {"value": behavioral_value(self.root, policy),
                            "nash_gap": behavioral_nash_gap(self.root, policy)}
        return report


_STEP = PCFRPlus.step  # run() batches natively only while step() is this one (tests may patch it)
_RUN = PCFRPlus.run  # BlendedGadgetControl.run fuses rounds natively only while run() is this one


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=2000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schedule", choices=("simultaneous", "alternating"), default="simultaneous")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    games = {"matching_pennies": matching_pennies(), "revealed_pennies": matching_pennies(True),
             "hidden_coin": hidden_coin(), "revealed_coin": hidden_coin(True), "kuhn": kuhn_poker()}
    report = {"algorithm": "PCFR+", "schedule": args.schedule,
              "prediction": "previous sequence utility, new own descendants (Appendix F)",
              "averaging": "quadratic own-reach weighted", "games": {}}
    for name, root in games.items():
        solver = PCFRPlus(root, schedule=args.schedule)
        checkpoints = sorted({min(n, args.rounds) for n in (1, 10, 100, 1000, args.rounds)})
        trace = []
        for checkpoint in checkpoints:
            solver.run(checkpoint - solver.rounds)
            trace.append(solver.metrics())
        oracle = solve_matrix(payoff_matrix(root)[0])
        report["games"][name] = {"oracle_value": oracle["profile_value"], "trace": trace,
                                 "last_policy": solver.policy(), "average_policy": solver.policy(True)}
        print(name, json.dumps(trace[-1]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
