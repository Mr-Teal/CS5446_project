"""Checked warm-state transport for one global positive affine payoff change.

This API deliberately rejects topology, chance/reach, action and infoset changes.
It is independent of rebase_solver's heuristic reuse under a changed game.
"""

from copy import deepcopy
from dataclasses import dataclass
from math import isclose, isfinite

import numpy as np

from .pcfr import PCFRPlus
from .warm_start import rebase_solver


@dataclass(frozen=True)
class AffineGameMap:
    scale: float
    offset: float
    leaves: int
    max_residual: float


def certify_affine_game(source, target):
    """Check identical extensive-form structure and new_u = a*old_u+b, a>0."""
    PCFRPlus(source)
    PCFRPlus(target)
    pairs = []
    def visit(old, new):
        if (old.player != new.player or old.infoset != new.infoset or old.cutoff != new.cutoff
                or tuple(old.children) != tuple(new.children) or old.probabilities != new.probabilities
                or (old.payoff is None) != (new.payoff is None)):
            raise ValueError("identical topology, actions, infosets, cutoff flags and chance probabilities required")
        if old.payoff is not None:
            if not isfinite(old.payoff) or not isfinite(new.payoff):
                raise ValueError("finite payoffs required")
            pairs.append((old.payoff, new.payoff))
        else:
            for action in old.children:
                visit(old.children[action], new.children[action])
    visit(source, target)
    low, high = min(pairs), max(pairs)
    if low[0] == high[0]:
        scale, offset = 1., low[1]-low[0]
    else:
        scale = (high[1]-low[1])/(high[0]-low[0])
        offset = low[1]-scale*low[0]
    if not isfinite(scale) or not isfinite(offset) or scale <= 0:
        raise ValueError("a positive finite global payoff scale is required")
    residuals = []
    for old, new in pairs:
        expected = scale*old+offset
        if not isfinite(expected) or not isclose(expected, new, abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError("terminal payoffs do not share one global affine map")
        residuals.append(abs(expected-new))
    return AffineGameMap(float(scale), float(offset), len(pairs), max(residuals))


def transport_affine_solver(previous, target_root):
    """Copy pending/current/average policies; scale regret and utility differences.

    Global payoff offsets add an action-independent CF baseline at each infoset.
    PRM+ is insensitive to that baseline. previous_utility is therefore kept in
    a baseline-free gauge (scaled, not claimed equal to raw target utilities).
    Own-reach average accumulators and cached opponent policies are unchanged.
    """
    certificate = certify_affine_game(previous.root, target_root)
    result, retained = rebase_solver(previous, deepcopy(target_root))
    if any(set(retained[p]) != set(previous.sets[p]) for p in (0, 1)):
        raise ValueError("all original minimizers must survive affine transport")
    for player in result.minimizers:
        for minimizer in player.values():
            minimizer.regrets *= certificate.scale
            minimizer.previous_utility *= certificate.scale
            if not np.all(np.isfinite(minimizer.regrets)) or not np.all(np.isfinite(minimizer.previous_utility)):
                raise ValueError("scaled warm state overflowed")
    return result, certificate
