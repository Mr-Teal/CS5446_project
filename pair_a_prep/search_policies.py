"""Heuristic initial policies and explicit raw-to-played purification."""

from math import isfinite


def heuristic_actions(root):
    """First DFS occurrence chooses each infoset's maximizing/minimizing child."""
    result = {}
    def visit(node):
        if node.payoff is not None:
            return node.payoff
        values = {a: visit(child) for a, child in node.children.items()}
        if node.player is None:
            return sum(node.probabilities[a] * v for a, v in values.items())
        best = (max if node.player == 0 else min)(values, key=values.get)
        result.setdefault((node.player, node.infoset), best)
        return values[best]
    visit(root)
    return result


class StableSupport:
    """Intersect observed raw supports from the half-budget threshold onward."""

    def __init__(self):
        self.stable = None

    def observe(self, policy, after_half):
        if after_half:
            support = {a for a, p in policy.items() if p > 0}
            self.stable = support if self.stable is None else self.stable & support


def seed_new(solver, retained=((), ())):
    """Initialize only new local policies and keep held-feedback caches aligned."""
    for (p, key), action in heuristic_actions(solver.root).items():
        if key in retained[p]:
            continue
        policy = solver._strategy[p][key]
        policy[:] = 0
        policy[solver.sets[p][key].index(action)] = 1
        solver.minimizers[p][key].strategy = policy.copy()
        if solver.rounds == 0 or solver.schedule == "simultaneous":
            solver._initial_actions[p, key] = action
    for p in (0, 1):
        if solver._previous_opponent[p] is not None:
            for key in solver.sets[1-p]:
                if key not in retained[1-p]:
                    solver._previous_opponent[p][key] = solver._strategy[1-p][key].copy()


def purify_policy(raw, mode, stable):
    """Keep top 3 stable actions in Maxmargin; Resolve plays the top action.

    The top action is always eligible. Excluded mass moves to it. No stability
    observations means no secondary action is eligible, not assumed stability.
    """
    if mode not in ("resolve", "maxmargin") or not raw or any(
            not isfinite(p) or p < 0 for p in raw.values()) or abs(sum(raw.values())-1) > 1e-9:
        raise ValueError("valid raw policy and gadget mode required")
    top = max(raw, key=raw.get)
    eligible = {top}
    if mode == "maxmargin":
        others = sorted((a for a in raw if a != top and a in (stable or set()) and raw[a] > 0),
                        key=lambda a: raw[a], reverse=True)
        eligible.update(others[:2])
    played = {a: (p if a in eligible else 0.) for a, p in raw.items()}
    played[top] += sum(p for a, p in raw.items() if a not in eligible)
    return played
