"""Copy compatible private-infoset solver state into a validated new game.

Tree/boundary changes invalidate equilibrium certificates. Preserved regrets
are an explicit heuristic warm start, not an exact new-game equilibrium.
"""

from copy import deepcopy

from .pcfr import PCFRPlus


def rebase_solver(previous, root):
    result = PCFRPlus(root, predictive=previous.predictive,
                      averaging_power=previous.averaging_power, schedule=previous.schedule)
    retained = []
    result.rounds = previous.rounds
    for p in (0, 1):
        keys = []
        for key, actions in result.sets[p].items():
            if previous.sets[p].get(key) == actions:
                result.minimizers[p][key] = deepcopy(previous.minimizers[p][key])
                result._strategy[p][key] = previous._strategy[p][key].copy()
                result._sums[p][key] = previous._sums[p][key].copy()
                keys.append(key)
            elif result.schedule == "alternating" and result.rounds:
                result.minimizers[p][key]._pending = True
        retained.append(tuple(keys))
    for p in (0, 1):
        old = previous._previous_opponent[p]
        if old is not None:
            result._previous_opponent[p] = {
                key: (old[key].copy() if key in retained[1-p] else result._strategy[1-p][key].copy())
                for key in result.sets[1-p]}
    return result, tuple(retained)
