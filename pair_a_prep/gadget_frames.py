"""Derive finite-gadget payoff frames from actual reach masses and offsets.

Certificates cover identical raw sampled roots only. They do not assert that
changed beliefs, sampled histories or different turns have matching CF units.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from math import fsum, isclose

from .value_frames import ValueFrame
from .gadgets import build_gadget


def _node_data(node):
    return [node.player, node.infoset, node.payoff, node.cutoff,
            list(node.probabilities.items()),
            [(action, _node_data(child)) for action, child in node.children.items()]]


def _raw_data(gadget):
    return [(root.root_id, root.opponent_infoset, float(root.reach_mass),
             _node_data(root.continuation)) for root in gadget.roots]


def _same_tree(a, b):
    if (a.player != b.player or a.infoset != b.infoset or a.cutoff != b.cutoff or
            tuple(a.children) != tuple(b.children) or set(a.probabilities) != set(b.probabilities) or
            (a.payoff is None) != (b.payoff is None)):
        return False
    if a.payoff is not None and not isclose(a.payoff, b.payoff, rel_tol=1e-12, abs_tol=1e-12):
        return False
    return all(isclose(value, b.probabilities[key], rel_tol=1e-12, abs_tol=1e-12)
               for key, value in a.probabilities.items()) and all(
                   _same_tree(child, b.children[key]) for key, child in a.children.items())


@dataclass(frozen=True)
class GadgetFrames:
    source: dict
    target: dict
    raw_snapshot_id: str
    group_masses: dict


def certify_gadget_frames(source, target):
    """Declared reach-weighted sum = M_J * local value + M_J * offset_J.

    Resolve's enter-continuation offset is zero. Maxmargin subtracts its
    alternate at every terminal, so its offset is the original alternate.
    This certifies continuation coordinates, not whole-game equivalence:
    Resolve has enter/exit and a prior, while Maxmargin has a free selector.
    """
    for gadget in (source, target):
        prior = None
        if gadget.mode == "resolve":
            if gadget.root_prior is None or set(gadget.root_prior) != {r.root_id for r in gadget.roots}:
                raise ValueError("invalid stored Resolve prior")
            prior = {}
            for root in gadget.roots:
                group = root.opponent_infoset
                prior[group] = prior.get(group, 0.)+gadget.root_prior[root.root_id]
        elif gadget.root_prior is not None:
            raise ValueError("Maxmargin cannot store a fixed root prior")
        expected = build_gadget(gadget.roots, gadget.alternate_player0, gadget.mode, prior)
        if (not _same_tree(expected.tree, gadget.tree) or
                set(expected.continuations) != set(gadget.continuations) or
                any(not _same_tree(tree, gadget.continuations[key]) for key, tree in expected.continuations.items())):
            raise ValueError("stored gadget tree does not match its declared construction")
    source_data, target_data = _raw_data(source), _raw_data(target)
    if source_data != target_data:
        raise ValueError("matching raw roots, reaches and unshifted continuations required")
    if source.mode not in ("resolve", "maxmargin") or target.mode not in ("resolve", "maxmargin"):
        raise ValueError("known gadget modes required")
    snapshot = sha256(json.dumps(source_data, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    groups = {}
    for root in source.roots:
        groups.setdefault(root.opponent_infoset, []).append(root.reach_mass)
    masses = {group: fsum(values) for group, values in groups.items()}
    def frames(gadget):
        return {group: ValueFrame("raw-cf:"+snapshot+":"+group, mass,
                mass*gadget.alternate_player0[group] if gadget.mode == "maxmargin" else 0.)
                for group, mass in masses.items()}
    return GadgetFrames(frames(source), frames(target), snapshot, masses)
