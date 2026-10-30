"""Copy compatible private-infoset solver state into a validated new game.

Tree/boundary changes invalidate equilibrium certificates. Preserved regrets
are an explicit heuristic warm start, not an exact new-game equilibrium.
"""

from copy import deepcopy

from .pcfr import PCFRPlus


def rebase_solver(previous, root, source_keys=None):
    result = PCFRPlus(root, predictive=previous.predictive,
                      averaging_power=previous.averaging_power, schedule=previous.schedule)
    retained = []
    source_keys = source_keys or {}
    result.rounds = previous.rounds
    for p in (0, 1):
        keys = []
        for key, actions in result.sets[p].items():
            source = source_keys.get((p, key), key)
            if previous.sets[p].get(source) == actions:
                result.minimizers[p][key] = deepcopy(previous.minimizers[p][source])
                result._strategy[p][key] = previous._strategy[p][source].copy()
                result._sums[p][key] = previous._sums[p][source].copy()
                keys.append(key)
                if (p, source) in previous._initial_actions:
                    result._initial_actions[p, key] = previous._initial_actions[p, source]
            elif result.schedule == "alternating" and result.rounds:
                result.minimizers[p][key]._pending = True
        retained.append(tuple(keys))
    for p in (0, 1):
        old = previous._previous_opponent[p]
        if old is not None:
            result._previous_opponent[p] = {
                key: (old[source_keys.get((1-p, key), key)].copy() if key in retained[1-p]
                      else result._strategy[1-p][key].copy())
                for key in result.sets[1-p]}
    return result, tuple(retained)
