"""Persistent value-only nested 1-KLSS and its one-FoW-ply baseline."""

from collections import Counter
from copy import copy
from hashlib import sha256
from math import log2
from random import Random
from time import perf_counter

import chess

from fow_shared.contracts import Decision
from ..toy_games import Node
from .model import (PositionTracker, SearchRules, check_time, BudgetError, position_key,
                    extend_memory, extend_memory_signature, view_signature)
from .engine import EvaluationError, EngineCrashed
from .sequence_form import SolveError
from .gadget import Gadget, Group, make_subgame, observed_sequence, BoundaryError


def nodes_below(roots):
    stack = list(reversed(roots))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(tuple(node.children.values())))


def continuation_value(node, solution):
    if node.payoff is not None:
        return node.payoff
    policy = node.probabilities if node.player is None else solution.policy(node.player, node.infoset)
    return sum(policy[action] * continuation_value(child, solution) for action, child in node.children.items())


def clone_tree(node, deadline):
    check_time(deadline)
    result = copy(node)
    result.children = {action: clone_tree(child, deadline) for action, child in node.children.items()}
    return result


def select_expansions(solution, roots, root_ply, depth_gate, threshold=1e-9):
    """Algorithm 15 parent-first order; D-05 depth catch-up applies afterward."""
    selected, trace = [], []
    for parent in nodes_below(roots):
        leaves = [n for n in parent.children.values() if n.payoff is not None and n.cutoff]
        if not leaves:
            continue
        sequences = solution.form.nodes[id(parent)][0]
        both_parent = solution.x[sequences[0]] > threshold and solution.y[sequences[1]] > threshold
        candidates = leaves if both_parent else [max(leaves, key=lambda n: (n.forcing, n.base))]
        for node in candidates:
            s = solution.form.nodes[id(node)][0]
            ours, theirs = solution.x[s[0]] > threshold, solution.y[s[1]] > threshold
            depth = node.state.ply - root_ply
            allowed = (ours or theirs) and (depth <= depth_gate or (ours and theirs))
            trace.append(dict(ply=node.state.ply, depth=depth, ours=bool(ours), theirs=bool(theirs),
                              both_parent=bool(both_parent), selected=bool(allowed)))
            if allowed:
                selected.append(node)
    return selected, trace


class PaperAgent:
    def __init__(self, player, seed, pool, *, baseline=False, initial_fen=None,
                 scale=1., particle_floor=200, max_rounds=None, support_tolerance=1e-9,
                 tracker_backend="native"):
        if scale not in (1., 6.):
            raise ValueError("supported utility variants are 1 and 6")
        self.player = player
        self.other = "black" if player == "white" else "white"
        self.pool = pool
        self.baseline = baseline
        self.scale = scale
        self.floor = particle_floor
        self.max_rounds = max_rounds
        self.support_tolerance = support_tolerance
        if tracker_backend == "native":
            from .native_tracker import NativeTracker
            self.tracker = NativeTracker(player, seed ^ 0x39A312, initial_fen)
        elif tracker_backend == "python":
            self.tracker = PositionTracker(player, seed ^ 0x39A312, initial_fen)
        else:
            raise ValueError("unknown full-I backend")
        self.sampling = Random(seed ^ 0x45F661)
        self.actions = Random(seed ^ 0x705683)
        self.representatives = Random(seed ^ 0xEF5DDD)
        if tracker_backend == "native":
            from .native_tracker import FastRules
            self.rules = FastRules(self.tracker.dll)
        else:
            self.rules = SearchRules()
        self.cache = {}
        self.snapshot = None
        self.gadget = None
        self.trace = {}
        self.timings = {}

    def observe(self, observation, own_move=None, deadline=None):
        self.tracker.update(observation, own_move, deadline)

    def close(self):
        if hasattr(self.tracker, "close"):
            self.tracker.close()

    def _new_node(self, state, memories, draw, forcing=False):
        node = Node(payoff=0., cutoff=self.rules.terminal(state) is None)
        node.state = state
        node.observations = memories
        node.draw = draw
        node.forcing = forcing
        node.base = 0.
        node.sf_depth = 0
        return node

    def _children(self, node, deadline):
        mover = self.rules.current_player(node.state)
        player = 0 if mover == self.player else 1
        children = {}
        actions = self.rules.legal_moves(node.state)
        if not actions:
            raise BoundaryError("defensive check: attempted expansion without a legal FoW action")
        for move in actions:
            check_time(deadline)
            state = self.rules.apply_known_legal(node.state, move)
            view = self.rules.observe(state, self.player)
            other_signature = (self.rules.observe_signature(state, self.other)
                               if hasattr(self.rules, "observe_signature")
                               else view_signature(self.rules.observe(state, self.other)))
            memories = (extend_memory(node.observations[0], view, move if player == 0 else None),
                        extend_memory_signature(node.observations[1], self.other, state.ply,
                                                other_signature, move if player == 1 else None))
            draw = node.draw.advance(view, move if player == 0 else None)
            action = chess.Move.from_uci(move)
            forcing = bool(node.state._board.is_capture(action) or action.promotion or state._board.is_check())
            child = self._new_node(state, memories, draw, forcing)
            child.own_view_signature = view_signature(view)
            children[move] = child
        return children, player, ("move", player, node.observations[player])

    def _estimates(self, nodes, depth, deadline):
        missing = {}
        values = {}
        for node in nodes:
            check_time(deadline)
            ended = self.rules.terminal(node.state)
            if ended is not None:
                base = 0. if ended.winner == "draw" else self.scale * (1. if ended.winner == self.player else -1.)
                values[id(node)] = (base, 0)
            else:
                key = (position_key(node.state._board), depth, self.baseline, self.scale)
                if key not in self.cache:
                    missing.setdefault(key, node.state._board)
        answer = self.pool.evaluate(tuple(missing.values()), self.player, depth=depth,
                                    deadline=deadline, scale=self.scale)
        for key, estimate in zip(missing, answer):
            self.cache[key] = estimate
        for node in nodes:
            if id(node) not in values:
                key = (position_key(node.state._board), depth, self.baseline, self.scale)
                estimate = self.cache[key]
                values[id(node)] = (estimate.value, estimate.depth)
        return values

    @staticmethod
    def _set_estimates(nodes, values):
        for node in nodes:
            node.base, node.sf_depth = values[id(node)]
            node.payoff = node.draw.value(node.base)

    def _prepare_expansion(self, nodes, deadline):
        pending = [(node, *self._children(node, deadline)) for node in nodes]
        children = [child for _, group, _, _ in pending for child in group.values()]
        values = self._estimates(children, 1, deadline)
        self._set_estimates(children, values)
        return pending

    @staticmethod
    def _install(pending):
        saved = []
        for node, children, player, infoset in pending:
            saved.append((node, node.payoff, node.cutoff, node.player, node.infoset, node.children))
            node.payoff = None
            node.cutoff = False
            node.player = player
            node.infoset = infoset
            node.children = children
        return saved

    @staticmethod
    def _rollback(saved):
        for node, payoff, cutoff, player, infoset, children in saved:
            node.payoff, node.cutoff, node.player, node.infoset, node.children = payoff, cutoff, player, infoset, children

    def _retained(self):
        if self.snapshot is None:
            return []
        candidates = [node for _, _, node in self.snapshot.form.nodes.values()
                      if hasattr(node, "state") and node.state.ply == self.tracker.previous.ply
                      and node.observations[0] == self.tracker.memory]
        candidates.sort(key=lambda n: (str(position_key(n.state._board)), n.observations[1]))
        self.representatives.shuffle(candidates)
        unique = {}
        for node in candidates:
            key = position_key(node.state._board)
            if self.tracker.contains(node.state._board):
                unique.setdefault(key, node)
        return [unique[k] for k in sorted(unique, key=str)]

    def _old_conditional_value(self, retained):
        if not retained:
            return float("inf"), "empty"
        solution = self.snapshot
        weights = [solution.form.nodes[id(n)][1]
                   * solution.x[solution.form.nodes[id(n)][0][0]]
                   * solution.y[solution.form.nodes[id(n)][0][1]] for n in retained]
        kind = "joint_reach"
        if sum(weights) <= 0:
            # An observation following an opponent deviation may have zero y reach.
            weights = [solution.form.nodes[id(n)][1] * solution.x[solution.form.nodes[id(n)][0][0]]
                       for n in retained]
            kind = "counterfactual_reach_zero_joint_boundary"
        if sum(weights) <= 0:
            raise BoundaryError("current information set has zero counterfactual reach")
        numerator = sum(w * continuation_value(n, solution) for w, n in zip(weights, retained))
        form = solution.form
        cuts = {form.nodes[id(n)][0][1] for n in retained}
        owned = [False] * len(form.sequences[1])
        conditional_y = [0.] * len(owned)
        for index in range(1, len(owned)):
            parent = form.parents[1][index]
            owned[index] = index in cuts or owned[parent]
            if index in cuts:
                conditional_y[index] = 1.
            elif owned[index]:
                key, action = form.sequences[1][index]
                conditional_y[index] = conditional_y[parent] * solution.policy(1, key)[action]
        # B has no implicit chance factor. Include the same downstream synthetic
        # payments that survive rerooting, not payments before this observation.
        b_row = form.B.getrow(0)
        y = solution.y if kind == "joint_reach" else conditional_y
        numerator += sum(value * y[col] for col, value in zip(b_row.indices, b_row.data) if owned[col])
        own_cut = form.nodes[id(retained[0])][0][0]
        other_b = form.B.tocoo()
        numerator += sum(value * solution.x[row] * solution.y[col]
                         for row, col, value in zip(other_b.row, other_b.col, other_b.data)
                         if row and form.descends(0, row, own_cut))
        return numerator / sum(weights), kind

    def _build(self, deadline):
        start = perf_counter()
        retained = self._retained()
        old_value, boundary = self._old_conditional_value(retained)
        self.timings["retain_and_old_value"] = perf_counter() - start
        start = perf_counter()
        gadget = make_subgame(self.snapshot, retained) if retained else Gadget([])
        self.timings["make_subgame"] = perf_counter() - start
        start = perf_counter()
        # The old snapshot is no longer modified: clone just the retained forest.
        for group in gadget.groups:
            group.roots = [clone_tree(n, deadline) for n in group.roots]
        added = self.tracker.sample_missing(retained, self.sampling, self.floor)
        fresh = []
        for candidate in added:
            identity = sha256(repr((candidate.moves, self.tracker.previous.ply)).encode()).hexdigest()
            memory = "root:" + identity
            node = self._new_node(candidate.state, (self.tracker.memory, memory), self.tracker.draw)
            fresh.append(node)
        self._set_estimates(fresh, self._estimates(fresh, 1, deadline))
        self.timings["clone_sample_evaluate_roots"] = perf_counter() - start
        for node in fresh:
            alternate = min(old_value, node.payoff)
            gadget.groups.append(Group(node.observations[1], [node], [1.],
                                       [(observed_sequence(node.observations[1]), -alternate)],
                                       audit=dict(alternate=alternate, gift=0., new_root=True)))
        unexpanded = [node for node in gadget.roots if node.payoff is not None]
        self.timings["retained_roots"] = len(retained)
        self.timings["fresh_roots"] = len(fresh)
        start = perf_counter()
        self._install(self._prepare_expansion(unexpanded, deadline))
        self.timings["initial_expand"] = perf_counter() - start
        actions = self.tracker.previous.legal_moves
        entropy = {}
        for action in actions:
            counts = Counter(root.children[action].own_view_signature
                             for root in gadget.roots)
            total = len(gadget.roots)
            entropy[action] = -sum((n / total) * log2(n / total) for n in counts.values())
            reward = -2 ** (-entropy[action]) * len(self.tracker.candidates) / 10_000_000
            gadget.information.append(((("move", 0, self.tracker.memory), action), None, reward))
        self.trace = dict(retained=len(retained), added=len(added), roots=len(gadget.roots),
                          population=len(self.tracker.candidates), old_value_boundary=boundary,
                          entropy=entropy, groups=[g.audit for g in gadget.groups], rounds=[],
                          mode_transitions=[], stop_reason="")
        return gadget

    def act(self, deadline):
        view = self.tracker.previous
        if view is None or view.terminal or view.side_to_move != self.player:
            raise ValueError("not an active own turn")
        if hasattr(self.rules, "view_cache"):
            self.rules.view_cache.clear()
        # Leave time for policy sampling, diagnostic materialization and submission.
        initial_deadline = deadline - .5
        work_deadline = deadline - 2.
        self.timings = {"remaining_at_act": deadline - perf_counter()}
        start = perf_counter()
        gadget = self._build(initial_deadline)
        self.timings["build_total"] = perf_counter() - start
        start = perf_counter()
        solution = gadget.solve(initial_deadline, keep_first_on_conversion_failure=True)
        self.timings["initial_solve"] = perf_counter() - start
        self.trace["initial_lp_precision_attempts"] = list(gadget.last_precision_attempts)
        rounds = 0
        depth_gate = 1
        sf_depth = 1
        if gadget.last_solve_warning:
            self.trace["stop_reason"] = "initial_mode_conversion_incomplete: " + gadget.last_solve_warning
        while not gadget.last_solve_warning and (self.max_rounds is None or rounds < self.max_rounds):
            if perf_counter() >= work_deadline:
                self.trace["stop_reason"] = "budget"
                break
            saved, previous_values, pending = [], [], None
            old_mode = gadget.mode
            gadget.last_precision_attempts = []
            try:
                if self.baseline:
                    leaves = [n for n in nodes_below(gadget.roots) if n.payoff is not None and n.cutoff]
                    if not leaves:
                        self.trace["stop_reason"] = "no_frontier"
                        break
                    values = self._estimates(leaves, sf_depth + 1, work_deadline)
                    previous_values = [(n, n.base, n.payoff, n.sf_depth) for n in leaves]
                    self._set_estimates(leaves, values)
                    selection = []
                else:
                    selected, selection = select_expansions(solution, gadget.roots, view.ply,
                                                             depth_gate, self.support_tolerance)
                    if not selected:
                        self.trace["stop_reason"] = "literal_support_stall"
                        break
                    pending = self._prepare_expansion(selected, work_deadline)
                    saved = self._install(pending)
                candidate = gadget.solve(work_deadline)
                solution = candidate
                rounds += 1
                depth_gate += 1
                if self.baseline:
                    sf_depth += 1
                self.trace["rounds"].append(dict(round=rounds, gate=depth_gate-1, value=solution.value,
                                                 mode=gadget.mode, nodes=len(solution.form.nodes),
                                                 sf_depth=sf_depth, selection=selection,
                                                 lp_precision_attempts=list(gadget.last_precision_attempts)))
                if old_mode != gadget.mode:
                    self.trace["mode_transitions"].append([old_mode, gadget.mode])
            except (BudgetError, EvaluationError, SolveError) as exc:
                self._rollback(saved)
                for node, base, payoff, depth in previous_values:
                    node.base, node.payoff, node.sf_depth = base, payoff, depth
                gadget.mode = old_mode
                if isinstance(exc, EngineCrashed):
                    raise
                self.trace["stop_reason"] = type(exc).__name__ + ": " + str(exc)
                self.trace["incomplete_lp_precision_attempts"] = list(gadget.last_precision_attempts)
                exc.__traceback__ = exc.__context__ = exc.__cause__ = None
                pending = None
                break
        if not self.trace["stop_reason"]:
            self.trace["stop_reason"] = "fixed_work_limit"
        check_time(deadline)
        policy = solution.policy(0, ("move", 0, self.tracker.memory))
        move = self.actions.choices(list(policy), weights=list(policy.values()))[0]
        release_start = perf_counter()
        self.snapshot, self.gadget = solution, gadget
        self.timings["snapshot_release"] = perf_counter() - release_start
        self.trace.update(mode=gadget.mode, value=solution.value, gap=solution.upper-solution.lower,
                          flow_error=solution.flow_error, nodes=len(solution.form.nodes),
                          lp_original_shape=solution.form.C.shape, lp_solved_shape=solution.form.solved_shape,
                          lp_precision_attempts=solution.precision_attempts,
                          max_fow_depth=max(n.state.ply-view.ply for n in nodes_below(gadget.roots)),
                          sf_depth=sf_depth, root_policy=policy, move=move)
        decision = Decision(move, policy, dict(value=solution.value, roots=len(gadget.roots),
                                             population=len(self.tracker.candidates), rounds=rounds,
                                             fow_depth=self.trace["max_fow_depth"], sf_depth=sf_depth,
                                             gap=solution.upper-solution.lower))
        decision.validate_for(view)
        check_time(deadline)
        return decision
