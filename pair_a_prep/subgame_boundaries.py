"""Finite-cut blueprint boundaries following Obscuro Appendix C.2-C.3.

Player 0 maximizes all values, including alternates and gifts. This is not
asynchronous KLUSS: callers explicitly supply a cut and opponent observations.
"""

from dataclasses import dataclass
from math import isfinite, fsum
from time import perf_counter
from hashlib import sha256
import json

from .gadgets import SubgameRoot, build_gadget
from .toy_games import behavioral_value, information_sets


@dataclass(frozen=True)
class BoundaryRoot:
    root_id: str
    path: tuple
    opponent_observation: str


@dataclass(frozen=True)
class BlueprintBoundaries:
    roots: tuple
    alternate_player0: dict
    gifts: dict
    group_prior: dict
    audit: dict

    def gadget(self, mode="resolve"):
        return build_gadget(self.roots, self.alternate_player0, mode,
                            self.group_prior if mode == "resolve" else None)


def derive_boundaries(root, profile, cut, deadline=None):
    """Derive p(h)x(h), current-profile alternates, positive CF gifts and alpha.

    The cut must contain full opponent observation classes selected by the
    caller's knowledge restriction. No belief posterior is substituted for reach.
    Zero opponent reach uses the same class's counterfactual distribution;
    zero player-0/chance reach is rejected rather than assigned fake values.
    """
    sets = information_sets(root)
    for p in (0, 1):
        if set(profile[p]) != set(sets[p]):
            raise ValueError("profile must cover exactly the tree infosets")
        for key, actions in sets[p].items():
            policy = profile[p][key]
            if set(policy) != set(actions) or any(not isfinite(v) or v < 0 for v in policy.values()) or abs(fsum(policy.values()) - 1) > 1e-9:
                raise ValueError("invalid blueprint policy")
    cut = tuple(cut)
    paths = [r.path for r in cut]
    if not cut or len(set(paths)) != len(paths) or len({r.root_id for r in cut}) != len(cut):
        raise ValueError("cut needs distinct paths and root IDs")
    if any(not r.root_id or not r.opponent_observation or not isinstance(r.path, tuple) for r in cut):
        raise ValueError("cut needs nonblank IDs, observations and tuple paths")
    if any(a != b and b[:len(a)] == a for a in paths for b in paths):
        raise ValueError("cut paths must form an antichain")
    nodes, cf = {}, {}
    cut_paths = set(paths)

    def visit(node, path, px, y, opponent_sequence, retained=False):
        if deadline is not None and perf_counter() >= deadline:
            from .chess_search import SearchBudgetError
            raise SearchBudgetError("boundary accounting deadline")
        retained = retained or path in cut_paths
        if node.payoff is not None:
            value = node.payoff
            kept_value = value if retained else 0.
        else:
            policy = node.probabilities if node.player is None else profile[node.player][node.infoset]
            values, kept = {}, {}
            for action, child in node.children.items():
                next_px = px * policy[action] if node.player in (None, 0) else px
                next_y = y * policy[action] if node.player == 1 else y
                sequence = opponent_sequence + ((node.infoset, action),) if node.player == 1 else opponent_sequence
                values[action], kept[action] = visit(child, path + (action,), next_px, next_y, sequence, retained)
            value = fsum(policy[a] * values[a] for a in values)
            kept_value = fsum(policy[a] * kept[a] for a in kept)
            if node.player == 1:
                row = cf.setdefault(node.infoset, dict(value=0.0, actions=dict.fromkeys(values, 0.0),
                    retained_value=0.0, retained_actions=dict.fromkeys(values, 0.0)))
                row["value"] += px * value
                row["retained_value"] += px * kept_value
                for a in values:
                    row["actions"][a] += px * values[a]
                    row["retained_actions"][a] += px * kept[a]
        nodes[path] = (node, px, y, value, opponent_sequence)
        return value, kept_value

    visit(root, (), 1.0, 1.0, ())
    groups = {}
    for entry in cut:
        if entry.path not in nodes:
            raise ValueError("unknown cut path")
        groups.setdefault(entry.opponent_observation, []).append(entry)
    roots, alternates, gifts, y_reaches, audit = [], {}, {}, {}, {}
    for group, entries in groups.items():
        rows = [nodes[r.path] for r in entries]
        sequences = {row[4] for row in rows}
        if len(sequences) != 1:
            raise ValueError("opponent observation forgets its own action sequence")
        mass = fsum(row[1] for row in rows)
        if mass <= 0:
            raise ValueError("zero counterfactual reach at boundary")
        joint = fsum(row[1] * row[2] for row in rows)
        conditional = (fsum(row[1] * row[2] * row[3] for row in rows) / joint if joint > 0 else
                       fsum(row[1] * row[3] for row in rows) / mass)
        sequence = rows[0][4]
        terms = []
        for key, action in sequence:
            row = cf[key]
            full_delta = row["actions"][action]-row["value"]
            retained_delta = row["retained_actions"][action]-row["retained_value"]
            terms.append(dict(infoset=key, action=action, full_delta=full_delta,
                retained_delta=retained_delta, discarded_delta=full_delta-retained_delta,
                gift=max(full_delta, 0.)))
        gift = fsum(term["gift"] for term in terms)
        gifts[group], alternates[group] = gift, conditional - gift
        y_reaches[group] = rows[0][2]
        audit[group] = dict(counterfactual_mass=mass, joint_mass=joint,
                            conditional_value=conditional, ancestor_gifts=terms,
                            zero_joint_fallback=joint <= 0)
        roots.extend(SubgameRoot(r.root_id, group, nodes[r.path][0], nodes[r.path][1]) for r in entries)
    total_y = fsum(y_reaches.values())
    prior = {key: 0.5 / len(groups) + 0.5 * (y / total_y if total_y > 0 else 1 / len(groups))
             for key, y in y_reaches.items()}
    source_unit = sha256(json.dumps(dict(scope="player0_raw_tree_counterfactual_v1",
        profile=profile, chance=[(path, row[0].probabilities) for path, row in nodes.items()
                               if row[0].payoff is None and row[0].player is None]),
        sort_keys=True, allow_nan=False).encode()).hexdigest()
    return BlueprintBoundaries(tuple(roots), alternates, gifts, prior,
                               dict(groups=audit, opponent_sequence_reach=y_reaches,
                                    gift_partition="positive_part_after_retained_plus_discarded",
                                    source_unit_id=source_unit,
                                    all_zero_y_uniform=total_y == 0))


def choose_mode(minimum_margin, tolerance=1e-10):
    """Use Maxmargin when every margin is nonnegative within tolerance."""
    if not isfinite(minimum_margin) or not isfinite(tolerance) or tolerance < 0:
        raise ValueError("finite margin and nonnegative tolerance required")
    return "maxmargin" if minimum_margin >= -tolerance else "resolve"


def current_minimum_margin(gadget, profile):
    values = gadget.continuation_values(profile)
    groups = {}
    for r in gadget.roots:
        groups.setdefault(r.opponent_infoset, []).append(r)
    return min(fsum(r.reach_mass * values[r.root_id] for r in rows) / fsum(r.reach_mass for r in rows)
               - gadget.alternate_player0[key] for key, rows in groups.items())


class BoundarySession:
    """Serial mode switching with copied compatible minimizers between gadgets."""

    def __init__(self, boundaries, schedule="alternating"):
        from .pcfr import PCFRPlus
        self.gadgets = {mode: boundaries.gadget(mode) for mode in ("resolve", "maxmargin")}
        self.mode = "maxmargin"
        self.solver = PCFRPlus(self.gadgets[self.mode].tree, schedule=schedule)
        self.transitions = []

    def step(self):
        from .warm_start import rebase_solver
        self.solver.step()
        margin = current_minimum_margin(self.gadgets[self.mode], self.solver.policy())
        target = choose_mode(margin)
        if target != self.mode:
            old_mode = self.mode
            self.solver, retained = rebase_solver(self.solver, self.gadgets[target].tree)
            self.mode = target
            self.transitions.append(dict(round=self.solver.rounds, previous=old_mode,
                                         mode=target, margin=margin,
                                         retained=[len(keys) for keys in retained]))
        return margin
