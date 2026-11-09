"""Finite-cut blueprint boundaries following Obscuro Appendix C.2-C.3.

Player 0 maximizes all values, including alternates and gifts. This is not
asynchronous KLUSS: callers explicitly supply a cut and opponent observations.
"""

from dataclasses import dataclass
from math import isfinite, fsum
from time import perf_counter
from hashlib import sha256
import json

import numpy as np

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


class BlendedGadgetControl:
    """Smooth Resolve/Maxmargin transition on one shared tree.

    Obscuro Fig. 9 l.22 and Fig. 10 l.5-13. R_J is a two-action PRM+ (enter,
    exit) per opponent infoset, fed the opponent's utility of entering against
    taking the alternate; the selector is a PRM+ over infosets fed the negated
    margins, which is Maxmargin. The root chance mass entering J is
    p_max*alpha(J)*pi_resolve(J) + (1-p_max)*pi_maxmargin(J) with
    p_max = max_J pi_resolve(J); Resolve mass that exits lands on "exit:J", so
    the distribution always sums to one. Mode is Maxmargin when p_max is zero,
    i.e. every R_J always exits and the strategy is safe (C.1, C.8); the Fig. 8
    l.13 comment states the condition the other way round and is not followed.
    """

    history = None  # a list: every round appends (values, margins, pi_resolve, pi_maxmargin, p_max, mode, root distribution)

    def __init__(self, gadget, alpha, predictive=True, tolerance=1e-10):
        from .pcfr import PredictiveRMPlus
        if gadget.mode != "blended":
            raise ValueError("control requires a blended gadget")
        self.groups = {}
        for r in gadget.roots:
            self.groups.setdefault(r.opponent_infoset, []).append(r)
        self.alpha = dict(alpha)
        if set(self.alpha) != set(self.groups) or abs(fsum(self.alpha.values()) - 1) > 1e-9:
            raise ValueError("alpha must be a distribution over the opponent infosets")
        self.order = tuple(self.groups)
        self.tolerance = tolerance
        self.entry = {j: PredictiveRMPlus(2, predictive) for j in self.order}
        self.selector = PredictiveRMPlus(len(self.order), predictive)
        self.pi_resolve = {j: float(self.entry[j].next_strategy()[0]) for j in self.order}
        self.pi_maxmargin = dict(zip(self.order, map(float, self.selector.next_strategy())))
        self.p_max = max(self.pi_resolve.values())
        self.margins = None
        self.apply(gadget)

    @property
    def mode(self):
        return "maxmargin" if self.p_max <= self.tolerance else "resolve"

    def update(self, gadget, profile):
        """Observe this round's values, advance R_J and the selector, re-blend the root."""
        return self._advance(gadget, gadget.round_values(profile))

    def update_from_solver(self, gadget, solver):
        """update(gadget, solver.policy()); on the native backend the values come from the kernel without the
        profile dictionaries (Gadget.solver_values)."""
        return self._advance(gadget, gadget.solver_values(solver))

    def _advance(self, gadget, values):
        alternate = gadget.alternate_player0
        entering = {j: fsum(r.reach_mass * values[r.root_id] for r in rows) / fsum(r.reach_mass for r in rows)
                    for j, rows in self.groups.items()}
        self.margins = {j: entering[j] - alternate[j] for j in self.order}
        for j in self.order:
            # The opponent minimizes player 0's payoff: its utilities are negated.
            self.entry[j].observe([-entering[j], -alternate[j]])
            self.pi_resolve[j] = float(self.entry[j].next_strategy()[0])
        self.selector.observe([-self.margins[j] for j in self.order])
        self.pi_maxmargin = dict(zip(self.order, map(float, self.selector.next_strategy())))
        self.p_max = max(self.pi_resolve.values())
        self.apply(gadget)
        if self.history is not None:
            self.history.append((dict(values), dict(self.margins), dict(self.pi_resolve), dict(self.pi_maxmargin),
                                 self.p_max, self.mode, dict(gadget.tree.probabilities)))
        return self.margins

    def run(self, gadget, solver, rounds, record=None):
        """`rounds` times solver.run(1, record) followed by update_from_solver(gadget, solver), as the subgame agent's
        gadget rounds. Returns the recorded rows (as solver.run(rounds, record)) and the mode after each round.

        On the native backend (Gadget.FAST, the solver on this blended gadget's tree, no instrumentation) the
        rounds and the controller run in one kernel call, pcfr_run_gadget: the same values walk, the controller's
        PRM+ updates with numpy's operation order (BLAS dot, pairwise sum), math.fsum for the group means, and
        apply()'s probabilities written into the solver's chance array; this object's state and the root's
        probabilities dict are written back after the call.
        """
        nodes = self._native_nodes(gadget, solver)
        if nodes is None:
            rows, modes = [], []
            for _ in range(rounds):
                trace = solver.run(1, record=record)
                self.update_from_solver(gadget, solver)
                if trace is not None:
                    rows.append(trace[0])
                modes.append(self.mode)
            if record is None:
                return None, modes
            width = len(solver.sets[record[0]][record[1]])
            return np.array(rows, dtype=float).reshape(len(rows), width), modes
        return self._run_native(gadget, solver, rounds, record, nodes)

    def _native_nodes(self, gadget, solver):
        from .gadgets import Gadget, _SOLVER_VALUES
        from .pcfr import PCFRPlus, PredictiveRMPlus, _RUN, _STEP
        native = getattr(solver, "_native", None)
        if (native is None or native.instrumented or type(solver).step is not _STEP or type(solver).run is not _RUN
                or any(name in solver.__dict__ for name in ("_utilities", "step", "run"))
                or type(self)._advance is not _ADVANCE or type(self).update_from_solver is not _UPDATE_FROM_SOLVER
                or Gadget.solver_values is not _SOLVER_VALUES):
            return None
        minimizers = [self.entry[j] for j in self.order] + [self.selector]
        if any(type(m) is not PredictiveRMPlus or "observe" in vars(m) or "next_strategy" in vars(m)
               or m.predictive != self.selector.predictive for m in minimizers):
            return None
        return gadget.native_nodes(solver)

    def _run_native(self, gadget, solver, rounds, record, nodes):
        from ._pcfr_native import Control, _pointer
        native = solver._native
        ids = list(gadget.continuations)
        index = {root_id: i for i, root_id in enumerate(ids)}
        reach = {r.root_id: r.reach_mass for rows in self.groups.values() for r in rows}
        probabilities = gadget.tree.probabilities
        slot = {key: i for i, key in enumerate(probabilities)}
        begin = int(native.chance_begin[0])
        order, g = self.order, len(self.order)
        a = dict(
            root_node=np.ascontiguousarray(nodes, dtype=np.int32),
            reach_mass=np.array([reach[root_id] for root_id in ids], dtype=float),
            group_begin=np.cumsum([0] + [len(self.groups[j]) for j in order]).astype(np.int32),
            group_roots=np.array([index[r.root_id] for j in order for r in self.groups[j]], dtype=np.int32),
            alternate=np.array([gadget.alternate_player0[j] for j in order], dtype=float),
            alpha=np.array([self.alpha[j] for j in order], dtype=float),
            group_mass=np.array([fsum(r.reach_mass for r in self.groups[j]) for j in order], dtype=float),
            root_slot=np.array([begin + slot[root_id] for root_id in ids], dtype=np.int32),
            exit_slot=np.array([begin + slot["exit:" + j] for j in order], dtype=np.int32),
            entry_regrets=np.concatenate([self.entry[j].regrets for j in order]).astype(float),
            entry_strategy=np.concatenate([self.entry[j].strategy for j in order]).astype(float),
            entry_previous=np.concatenate([self.entry[j].previous_utility for j in order]).astype(float),
            entry_pending=np.array([self.entry[j]._pending for j in order], dtype=np.int8),
            selector_regrets=np.array(self.selector.regrets, dtype=float),
            selector_strategy=np.array(self.selector.strategy, dtype=float),
            selector_previous=np.array(self.selector.previous_utility, dtype=float),
            selector_pending=np.array([self.selector._pending], dtype=np.int8),
            pi_resolve=np.array([self.pi_resolve[j] for j in order], dtype=float),
            pi_maxmargin=np.array([self.pi_maxmargin[j] for j in order], dtype=float),
            p_max=np.array([self.p_max], dtype=float), margins=np.zeros(g), values=np.zeros(len(ids)),
            entering=np.zeros(g))
        keys = list(probabilities)
        width = len(ids) + 3 * g + 1 + len(keys) if self.history is not None else 0
        control = Control(n_groups=g, n_roots=len(ids), predictive=int(bool(self.selector.predictive)),
                          history_width=width, tolerance=self.tolerance,
                          **{name: _pointer(array) for name, array in a.items()})
        history = np.zeros((rounds, width)) if width else None
        done = solver.rounds
        try:
            trace, p_max = native.run_gadget(solver, control, a, rounds, record, history)
        finally:
            done = solver.rounds - done
            for k, j in enumerate(order):
                m = self.entry[j]
                m.regrets, m.strategy = a["entry_regrets"][2 * k:2 * k + 2].copy(), a["entry_strategy"][2 * k:2 * k + 2].copy()
                m.previous_utility, m._pending = a["entry_previous"][2 * k:2 * k + 2].copy(), bool(a["entry_pending"][k])
            m = self.selector
            m.regrets, m.strategy = a["selector_regrets"].copy(), a["selector_strategy"].copy()
            m.previous_utility, m._pending = a["selector_previous"].copy(), bool(a["selector_pending"][0])
            if done:
                self.pi_resolve = dict(zip(order, map(float, a["pi_resolve"])))
                self.pi_maxmargin = dict(zip(order, map(float, a["pi_maxmargin"])))
                self.p_max = float(a["p_max"][0])
                self.margins = dict(zip(order, map(float, a["margins"])))
                for key in keys:  # apply()'s assignments, in its order of keys (an existing key keeps its place)
                    probabilities[key] = float(native.chance_prob[begin + slot[key]])
                if history is not None:
                    for row in history[:done]:
                        values = dict(zip(ids, map(float, row[:len(ids)])))
                        rest = row[len(ids):]
                        p = float(rest[3 * g])
                        self.history.append((values, dict(zip(order, map(float, rest[:g]))),
                                             dict(zip(order, map(float, rest[g:2 * g]))),
                                             dict(zip(order, map(float, rest[2 * g:3 * g]))), p,
                                             "maxmargin" if p <= self.tolerance else "resolve",
                                             dict(zip(keys, map(float, rest[3 * g + 1:])))))
        return trace, ["maxmargin" if p <= self.tolerance else "resolve" for p in p_max[:done]]

    def apply(self, gadget):
        probabilities = gadget.tree.probabilities
        for j, rows in self.groups.items():
            mass = fsum(r.reach_mass for r in rows)
            entering = self.p_max * self.alpha[j] * self.pi_resolve[j] + (1 - self.p_max) * self.pi_maxmargin[j]
            for r in rows:
                probabilities[r.root_id] = entering * r.reach_mass / mass
            probabilities["exit:" + j] = self.p_max * self.alpha[j] * (1 - self.pi_resolve[j])


_ADVANCE = BlendedGadgetControl._advance  # run() goes native only while these are not replaced (tests patch them)
_UPDATE_FROM_SOLVER = BlendedGadgetControl.update_from_solver


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
