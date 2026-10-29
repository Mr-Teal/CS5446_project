"""Exact best-response bounds in a finite perfect-recall sampled game.

This avoids enumerating every pure policy. It is not full-chess exploitability:
all cutoffs, sampled roots and gadget payments remain part of the finite game.
"""

from functools import lru_cache
from math import fsum

from .pcfr import PCFRPlus
from .toy_games import behavioral_value


def best_response_value(root, profile, player):
    """Optimize one shared action per infoset, deepest own history first."""
    if player not in (0, 1):
        raise ValueError("player must be 0 or 1")
    behavioral_value(root, profile)
    structure = PCFRPlus(root)
    occurrences = {key: [] for key in structure.sets[player]}
    nodes = {}
    def collect(node, cf):
        nodes[id(node)] = node
        if node.payoff is not None:
            return
        if node.player == player:
            occurrences[node.infoset].append((node, cf))
        probabilities = node.probabilities if node.player is None else profile[node.player][node.infoset]
        for action, child in node.children.items():
            collect(child, cf if node.player == player else cf*probabilities[action])
    collect(root, 1.)
    chosen = {}
    @lru_cache(None)
    def value(identity):
        node = nodes[identity]
        if node.payoff is not None:
            return node.payoff
        if node.player == player:
            return value(id(node.children[chosen[node.infoset]]))
        probabilities = node.probabilities if node.player is None else profile[node.player][node.infoset]
        return fsum(probabilities[action]*value(id(child)) for action, child in node.children.items())
    for key in structure._order[player]:
        action_values = {action: fsum(cf*value(id(node.children[action])) for node, cf in occurrences[key])
                         for action in structure.sets[player][key]}
        chosen[key] = (max if player == 0 else min)(action_values, key=action_values.get)
    return float(value(id(root)))


def finite_security(root, profile):
    current = behavioral_value(root, profile)
    upper = best_response_value(root, profile, 0)
    lower = best_response_value(root, profile, 1)
    if upper < current-1e-9 or lower > current+1e-9 or upper < lower-1e-9:
        raise ValueError("inconsistent finite-game best-response bounds")
    return dict(value=float(current), lower=lower, upper=upper, finite_gap=max(0., upper-lower))
