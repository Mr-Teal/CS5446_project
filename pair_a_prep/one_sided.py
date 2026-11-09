"""Serial one-sided frontier sampling; engineering conventions are documented.

Conditional utilities aggregate all expanded occurrences of an infoset under
the current raw profile. Expansion counts are separate from CFR iterations.

With a native solver (PCFRPlus backend "native") on the sampled tree, select() takes the utilities from the PCFR+
kernel's walk of the compiled tree under the published strategies (flat_utilities, equal to utilities() of
solver.policy()) and reads the strategies of the nodes on the sampled path from the solver's arrays, so no policy
dictionaries are built; the random draws are the same.
"""

from collections.abc import Mapping
from math import sqrt
from random import Random
from time import perf_counter

from .chess_search import SearchBudgetError


class FlatUtilities(Mapping):
    """(player, infoset) -> {action: conditional utility}, read on access from the kernel's per-player arrays;
    the sets and slots are the solver's at the time of the walk."""

    def __init__(self, sets, slots, values):
        self._sets, self._slots, self._values = sets, slots, values

    def __getitem__(self, key):
        player, infoset = key
        start, stop = self._slots[player][infoset]
        return dict(zip(self._sets[player][infoset], self._values[player][start:stop].tolist()))

    def __iter__(self):
        return ((player, infoset) for player in (0, 1) for infoset in self._sets[player])

    def __len__(self):
        return len(self._sets[0]) + len(self._sets[1])


class OneSidedExpansion:
    def __init__(self, seed):
        self.rng = Random(seed)
        self.events = 0
        self.visits = {}
        self.samples = {}

    @property
    def explorer(self):
        return self.events % 2

    def utilities(self, root, profile, deadline=None):
        totals, masses, fallback = {}, {}, {}

        def visit(node, reach):
            if deadline is not None and perf_counter() >= deadline:
                raise SearchBudgetError("growth_deadline")
            if node.payoff is not None:
                return node.payoff
            if node.player is None:
                return sum(p * visit(node.children[a], reach * p)
                           for a, p in node.probabilities.items())
            p, key = node.player, (node.player, node.infoset)
            policy = profile[p][node.infoset]
            values = {a: visit(child, reach * policy[a]) for a, child in node.children.items()}
            totals.setdefault(key, dict.fromkeys(values, 0.0))
            fallback.setdefault(key, [])
            signed = {a: v * (1 if p == 0 else -1) for a, v in values.items()}
            for a in values:
                totals[key][a] += reach * signed[a]
            masses[key] = masses.get(key, 0.0) + reach
            fallback[key].append(signed)
            return sum(policy[a] * v for a, v in values.items())

        visit(root, 1.0)
        return {key: {a: (v / masses[key] if masses[key] > 0 else
                         sum(row[a] for row in fallback[key]) / len(fallback[key]))
                      for a, v in values.items()} for key, values in totals.items()}

    def flat_utilities(self, solver, deadline=None):
        """utilities(solver.root, solver.policy(), deadline) from the native kernel; the deadline is checked before
        and after the walk instead of at every node."""
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("growth_deadline")
        values = solver._native.growth_utilities()
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("growth_deadline")
        return FlatUtilities(solver.sets, solver._native.slots, values)

    def distribution(self, player, infoset, policy, utilities):
        if player != self.explorer:
            return dict(policy)
        key = (player, infoset)
        counts = self.visits.get(key, {})
        total = sum(counts.values())
        def score(action):
            samples = self.samples.get((key, action), (-1.0, 1.0))
            mean = sum(samples) / len(samples)
            variance = sum((v - mean) ** 2 for v in samples) / len(samples)
            return utilities[action] + variance * sqrt(total) / (1 + counts.get(action, 0))
        best = max(policy, key=score)
        support = [a for a, value in policy.items() if value > 0]
        return {a: (0.5 / len(support) if a in support else 0.0) + 0.5 * (a == best)
                for a in policy}

    def select(self, tree, solver, max_depth, deadline=None):
        """Failed grafts leave state unchanged; terminal draws consume RNG only."""
        rng = Random()
        rng.setstate(self.rng.getstate())
        if getattr(solver, "_native", None) is not None and tree.root is solver.root:
            utilities = self.flat_utilities(solver, deadline)
            sets, strategies = solver.sets, solver._strategy

            def policy_of(player, infoset):  # = solver.policy()[player][infoset], for this node only
                return dict(zip(sets[player][infoset], strategies[player][infoset].tolist()))
        else:
            profile = solver.policy()
            utilities = self.utilities(tree.root, profile, deadline)

            def policy_of(player, infoset):
                return profile[player][infoset]
        path, visited, node = (), [], tree.root
        while node.payoff is None:
            if node.player is None:
                policy = node.probabilities
            else:
                key = (node.player, node.infoset)
                policy = self.distribution(*key, policy_of(*key), utilities[key])
            action = rng.choices(list(policy), weights=list(policy.values()), k=1)[0]
            if node.player == self.explorer:
                visited.append(((node.player, node.infoset), action))
            path += (action,)
            node = node.children[action]
        if path not in tree.frontiers or len(path) - 1 >= max_depth:
            # Sampling terminal/depth-limited paths is real work, but no growth.
            self.rng.setstate(rng.getstate())
            return None
        return path, visited, utilities, rng.getstate()

    def commit(self, proposal):
        _, visited, utilities, state = proposal
        for key, action in visited:
            counts = self.visits.setdefault(key, {})
            counts[action] = counts.get(action, 0) + 1
            for a, value in utilities[key].items():
                self.samples.setdefault((key, a), [-1.0, 1.0]).append(value)
        self.rng.setstate(state)
        self.events += 1
