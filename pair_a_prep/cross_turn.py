"""Opt-in sampled-history retention; no hidden-board or tracker mutation."""

from copy import deepcopy
from random import Random
from time import perf_counter

from .anytime_agent import AnytimePCFRAgent
from .chess_search import (ChessTree, reconstruct_roots, _build_roots,
                           observation_key, SearchBudgetError, TreeCapacityError)
from .rules_adapter import RulesAdapter
from .toy_games import Node
from .warm_start import rebase_solver


def history_identity(hypothesis):
    return hypothesis.fen, hypothesis.candidate_moves


def replenish_histories(retained, population, target, seed):
    """Keep all retained histories, then sample unseen paths without replacement.

    Returns candidate objects, not a normalized posterior. The caller owns
    evidence filtering and weights. The target is a floor, never a retained cap.
    No position-only merging or generation of unverified histories occurs here.
    """
    if type(target) is not int or target < 1:
        raise ValueError("target must be a positive integer")
    retained, population = tuple(retained), tuple(population)
    seen = {history_identity(h) for h in retained}
    if len(seen) != len(retained):
        raise ValueError("duplicate retained history")
    missing = {}
    for h in population:
        if history_identity(h) not in seen:
            missing.setdefault(history_identity(h), h)
    rng = Random(seed)
    keys = list(missing)
    added = rng.sample(keys, min(max(0, target-len(retained)), len(keys)))
    return retained + tuple(missing[key] for key in added)


def retain_tree(previous_turn, previous_tree, turn, evaluator, *, initial_fen,
                depth, max_nodes, deadline=None):
    """Reuse only validated candidate-prefix subtrees from the same player's turn.

    New input belief weights remain authoritative. Roots not present in that
    belief are not inserted with guessed weights. Fresh candidate roots use
    the ordinary builder; callers can replenish their belief separately.
    """
    if turn.observation.player != previous_turn.observation.player:
        raise ValueError("cross-turn utility perspective must stay unchanged")
    delta = turn.observation.ply - previous_turn.observation.ply
    if delta <= 0:
        raise ValueError("retention requires a later observation")
    expected = tuple(previous_turn.history)
    if tuple(turn.history[:len(expected)]) != expected or len(turn.history) <= previous_turn.observation.ply:
        raise ValueError("new private history must extend the saved history")
    event = turn.history[previous_turn.observation.ply]
    if observation_key(event.observation) != observation_key(previous_turn.observation):
        raise ValueError("saved observation changed")
    rules = RulesAdapter()
    contexts = reconstruct_roots(turn, rules, initial_fen, deadline)
    branches, frontiers = [], {}
    nodes, terminals, calls, reused = 1, 0, 0, 0
    used_old = set()
    for index, (hypothesis, context) in enumerate(zip(turn.belief.hypotheses, contexts)):
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("retention_deadline")
        found = None
        for old_index, old in enumerate(previous_turn.belief.hypotheses):
            if hypothesis.candidate_moves[:len(old.candidate_moves)] != old.candidate_moves:
                continue
            path = (str(old_index),) + hypothesis.candidate_moves[len(old.candidate_moves):]
            candidate = previous_tree.root
            for action in path:
                candidate = candidate.children.get(action)
                if candidate is None:
                    break
            if candidate is not None and candidate.payoff is None:
                found = (path, candidate)
                used_old.add(old_index)
                break
        if found is None:
            fresh = _build_roots((context,), turn.observation.player, (1.,), evaluator,
                                 depth, max_nodes-nodes+1, deadline)
            branches.append(fresh.continuations[0])
            nodes += fresh.nodes-1
            terminals += fresh.terminal_leaves
            calls += fresh.evaluator_calls
            frontiers.update({(str(index),)+path[1:]: value for path, value in fresh.frontiers.items()})
        else:
            old_path, candidate = found
            expected_key = turn.observation.player + ":" + context.memories[0 if turn.observation.player == "white" else 1]
            if candidate.player != 0 or candidate.infoset != expected_key:
                raise ValueError("retained root private memory does not match the new turn")
            candidate = deepcopy(candidate)
            stack = [candidate]
            while stack:
                if deadline is not None and perf_counter() >= deadline:
                    raise SearchBudgetError("retention_deadline")
                node = stack.pop()
                nodes += 1
                terminals += int(node.payoff is not None and not node.cutoff)
                stack.extend(node.children.values())
            branches.append(candidate)
            frontiers.update({(str(index),)+path[len(old_path):]: value
                              for path, value in previous_tree.frontiers.items()
                              if path[:len(old_path)] == old_path})
            reused += 1
        if nodes > max_nodes:
            raise TreeCapacityError("retained plus fresh tree exceeds max_nodes")
    root = Node(children={str(i): node for i, node in enumerate(branches)},
                probabilities={str(i): h.weight for i, h in enumerate(turn.belief.hypotheses)})
    tree = ChessTree(root, tuple(branches), branches[0].infoset, nodes, len(frontiers),
                     terminals, calls, contexts, frontiers, turn.observation.player)
    return tree, dict(reused_roots=reused, fresh_roots=len(branches)-reused,
                      discarded_previous_roots=len(previous_turn.belief.hypotheses)-len(used_old))


class RetainedPCFRAgent(AnytimePCFRAgent):
    """Opt-in warm-start agent; full gadget/KLUSS boundary projection is absent."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "retained-" + self.name
        self.saved = None
        self.retention = {}

    def reset(self, player, seed):
        super().reset(player, seed)
        self.saved = None
        self.retention = {}

    @property
    def config_id(self):
        return super().config_id + ":private-history-warm-v1"

    def _prepare_tree(self, turn, leaf, deadline):
        if self.saved is None:
            self.retention = dict(reused_roots=0, fresh_roots=len(turn.belief.hypotheses))
            return super()._prepare_tree(turn, leaf, deadline)
        old_turn, old_tree, _ = self.saved
        tree, self.retention = retain_tree(old_turn, old_tree, turn, leaf,
            initial_fen=self.initial_fen, depth=self.config.initial_depth,
            max_nodes=self.config.max_nodes, deadline=deadline)
        return tree

    def _prepare_solver(self, tree):
        if self.saved is None:
            return super()._prepare_solver(tree)
        solver, retained = rebase_solver(self.saved[2], tree.root)
        if self.config.growth == "one_sided":
            from .search_policies import seed_new
            seed_new(solver, retained)
        self.retention["retained_infosets"] = sum(len(keys) for keys in retained)
        return solver

    def _remember(self, turn, tree, solver):
        self.saved = turn, tree, solver
        self.last_result.decision.diagnostics.update({"retention:"+key: float(value)
                                                      for key, value in self.retention.items()})
