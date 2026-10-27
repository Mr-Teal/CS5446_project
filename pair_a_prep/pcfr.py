"""PCFR+ on small perfect-recall two-player zero-sum trees with explicit growth.

Local PRM+ follows Farina, Kroer & Sandholm (AAAI 2021), Algorithm 5,
using utilities (the negative of their losses). See docs/pcfr.md for scheduling.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
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

    def __init__(self, root: Node, predictive: bool = True, averaging_power: int = 2,
                 schedule: str = "simultaneous", initial_actions=None):
        if schedule not in ("simultaneous", "alternating"):
            raise ValueError("schedule must be simultaneous or alternating")
        self.schedule = schedule
        if averaging_power not in (0, 1, 2):
            raise ValueError("averaging_power must be 0, 1 or 2")
        self.root = root
        self.sets, self._order = self._index_tree(root)
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

    def _index_tree(self, root):
        sets = information_sets(root)
        histories = {}
        self._check_recall(root, ((), ()), histories)
        order = tuple(sorted(player_sets, key=lambda key: len(histories[(p, key)]), reverse=True)
                      for p, player_sets in enumerate(sets))
        return sets, order

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
        sets, order = self._index_tree(root)
        for player in (0, 1):
            for key, actions in self.sets[player].items():
                if sets[player].get(key) != actions:
                    raise ValueError("expansion must preserve existing infoset actions: " + key)

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
        previous_opponent = [
            None if previous is None else {
                **previous, **{key: value.copy() for key, value in strategies[1 - player].items()}}
            for player, previous in enumerate(self._previous_opponent)]

        self.root, self.sets, self._order = root, sets, order
        for player in (0, 1):
            self.minimizers[player].update(added[player])
            self._strategy[player].update(strategies[player])
            self._sums[player].update(sums[player])
        self._previous_opponent = previous_opponent
        if self.schedule == "simultaneous" or not self.rounds:
            self._initial_actions.update({(p, key): action for (p, key), action in (initial_actions or {}).items()
                                          if key in added[p]})

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
        for key in self._order[player]:
            minimizer = self.minimizers[player][key]
            prediction = (np.zeros_like(minimizer.regrets) if previous is None
                          else self._utilities(player, previous)[key])
            self._strategy[player][key] = minimizer.next_strategy(prediction)
            action = self._initial_actions.pop((player, key), None)
            if action is not None:
                self._strategy[player][key][:] = 0
                self._strategy[player][key][self.sets[player][key].index(action)] = 1
                minimizer.strategy = self._strategy[player][key].copy()

    def _observe(self, player) -> None:
        utilities = self._utilities(player)
        for key, minimizer in self.minimizers[player].items():
            minimizer.observe(utilities[key])
        self._previous_opponent[player] = {
            key: value.copy() for key, value in self._strategy[1 - player].items()}

    def step(self) -> None:
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

    def run(self, rounds: int) -> None:
        """Perform this many additional rounds; continuation preserves all state."""
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 0:
            raise ValueError("rounds must be a nonnegative integer")
        for _ in range(rounds):
            self.step()

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
