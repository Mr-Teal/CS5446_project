"""Finite saved-tree I^2 projection and explicit fresh chess-root boundaries.

Knowledge closure is exact within the saved sampled tree at a synchronized cut,
not the entire set of legal histories. No actual hidden board is accepted.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from math import fsum
from time import perf_counter

from .chess_search import (ChessTree, HistoryRoot, _build_roots, _extend_key,
                           reconstruct_roots, observation_key, SearchBudgetError,
                           TreeCapacityError, build_chess_tree)
from .chess_gadgets import ChessRootGroups
from .rules_adapter import RulesAdapter
from .subgame_boundaries import BoundaryRoot, BlueprintBoundaries, derive_boundaries
from .gadgets import SubgameRoot
from .toy_games import Node, behavioral_value, information_sets
from .search_policies import heuristic_actions


def root_identity(fen, moves):
    return "projected:" + sha256(repr((fen, tuple(moves))).encode()).hexdigest()


def position_key(fen):
    """Obscuro's position (footnote 7): placement, turn, castling and en passant.

    The move counters are dropped: two histories that differ only in their
    clocks are the same position when sampling the set P of possible positions.
    """
    return " ".join(fen.split()[:4])


@dataclass
class SavedChessBlueprint:
    turn: object
    tree: ChessTree
    paths: tuple
    raw_solver: object
    previous_value: float
    gift_ledger: object = None


@dataclass
class ChessProjection:
    turn: object
    tree: ChessTree
    paths: tuple
    root_ids: tuple
    groups: tuple
    current_ids: tuple
    boundaries: object
    audit: dict
    parent_events: tuple = ()
    # current_id -> root_id for hypotheses whose position already had a root.
    aliases: dict = field(default_factory=dict)

    def bridge(self, mode, evaluator_name):
        roots = ChessRootGroups(self.turn, self.tree, self.root_ids, self.groups,
            dict(evaluator=evaluator_name, depth=self.audit["depth"],
                 prototype=True, knowledge="saved_sampled_tree_I2"))
        return roots.build(self.boundaries.alternate_player0,
            reach_mass={r.root_id: r.reach_mass for r in self.boundaries.roots}, mode=mode,
            group_prior=self.boundaries.group_prior if mode in ("resolve", "blended") else None)


def project_chess(turn, evaluator, *, initial_fen, depth, max_nodes, saved=None, deadline=None):
    if type(depth) is not int or depth < 1:
        raise ValueError("depth must be a positive integer")
    if type(max_nodes) is not int or max_nodes < 2:
        raise ValueError("max_nodes must be an integer of at least two")
    if turn.observation.terminal:
        raise ValueError("cannot project a terminal turn")
    if 1+len(turn.belief.hypotheses) > max_nodes:
        raise TreeCapacityError("sampled root nodes alone exceed max_nodes")
    rules = RulesAdapter()
    viewer = turn.observation.player
    own_index = 0 if viewer == "white" else 1
    current = reconstruct_roots(turn, rules, initial_fen, deadline)
    current_ids = tuple(root_identity(h.fen, h.candidate_moves) for h in turn.belief.hypotheses)
    if saved is None:
        tree = _build_roots(current, viewer, tuple(h.weight for h in turn.belief.hypotheses),
                            evaluator, depth, max_nodes, deadline)
        groups = tuple(("black" if viewer == "white" else "white")+":"+c.memories[1-own_index] for c in current)
        return ChessProjection(turn, tree, tuple(h.candidate_moves for h in turn.belief.hypotheses),
            current_ids, groups, current_ids, None, dict(retained=0, fresh=len(current),
                knowledge_roots=len(current), outside_current=0, depth=depth, incomplete_cut=0))
    if saved.turn.observation.player != viewer or turn.observation.ply <= saved.turn.observation.ply:
        raise ValueError("saved blueprint needs the same player and an earlier turn")
    if tuple(turn.history[:len(saved.turn.history)]) != tuple(saved.turn.history):
        raise ValueError("private stream does not extend saved blueprint")
    if observation_key(turn.history[saved.turn.observation.ply].observation) != observation_key(saved.turn.observation):
        raise ValueError("saved private observation changed")
    delta = turn.observation.ply-saved.turn.observation.ply
    cut, incomplete = [], 0

    def visit(node, context, path, moves, remaining):
        nonlocal incomplete
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("chess projection deadline")
        if rules.terminal(context.state) is not None:
            return
        if remaining == 0:
            cut.append((path, node, context, moves))
            return
        if node.payoff is not None:
            incomplete += 1
            return
        mover = rules.current_player(context.state)
        for action, child in node.children.items():
            state = rules.apply_move(context.state, action)
            # = _extend(memory, rules.observe(state, p), ...): the adapter's observation_key is
            # observation_key(observe(...)) without building the Observation on the native backend.
            memories = tuple(_extend_key(context.memories[i], rules.observation_key(state, p),
                                         action if p == mover else None)
                             for i, p in enumerate(("white", "black")))
            visit(child, HistoryRoot(state, memories), path+(action,), moves+(action,), remaining-1)

    for i, context in enumerate(saved.tree.history_roots):
        visit(saved.tree.continuations[i], context, (str(i),), saved.paths[i], delta)
    own_memory = current[0].memories[own_index]
    touching = {context.memories[1-own_index] for _, _, context, _ in cut
                if context.memories[own_index] == own_memory}
    selected = [row for row in cut if row[2].memories[1-own_index] in touching]
    # This is the synchronized I^2 closure: include all histories sharing the
    # opponent memory of a current-I history, even when our own memory differs.
    boundary = None
    if selected:
        entries = tuple(BoundaryRoot(root_identity(c.state.fen, moves), path,
                                     "opponent:"+c.memories[1-own_index])
                        for path, _, c, moves in selected)
        boundary = derive_boundaries(saved.tree.root, saved.raw_solver.policy(), entries, deadline=deadline)
    branches, contexts, paths, ids, groups, frontiers = [], [], [], [], [], {}
    reaches, alternates, gifts, y = {}, {}, {}, {}
    if boundary:
        alternates.update(boundary.alternate_player0)
        gifts.update(boundary.gifts)
        y.update(boundary.audit["opponent_sequence_reach"])
    calls, retained, fresh = 0, 0, 0
    prepared_nodes = 1
    parent_events = []
    lazy_neighbours = 0
    evaluation_cache = {}

    def append(context, moves, node=None, old_path=None):
        nonlocal calls, retained, fresh, prepared_nodes, lazy_neighbours
        index = len(branches)
        identity = root_identity(context.state.fen, moves)
        if old_path is None:
            memories = list(context.memories)
            memories[1-own_index] = sha256(("perfect-root:"+identity+":"+memories[1-own_index]).encode()).hexdigest()
            context = HistoryRoot(context.state, tuple(memories))
        if node is not None and node.cutoff and context.memories[own_index] != own_memory:
            # Keep the old estimate at an outside-I knowledge neighbour. It
            # remains an explicit expandable root frontier, not a pruned root.
            continuation = deepcopy(node)
            frontiers[(str(index),)] = context
            lazy_neighbours += 1
        elif node is None or node.payoff is not None:
            built = _build_roots((context,), viewer, (1.,), evaluator, depth,
                                 max_nodes-prepared_nodes+1, deadline,
                                 evaluation_cache=evaluation_cache)
            continuation = built.continuations[0]
            frontiers.update({(str(index),)+p[1:]: c for p, c in built.frontiers.items()})
            calls += built.evaluator_calls
        else:
            continuation = deepcopy(node)
            frontiers.update({(str(index),)+p[len(old_path):]: c for p, c in saved.tree.frontiers.items()
                              if p[:len(old_path)] == old_path})
        if old_path is not None:
            group = "opponent:"+context.memories[1-own_index]
            reaches[identity] = next(r.reach_mass for r in boundary.roots if r.root_id == identity)
            retained += 1
        else:
            # Newly added roots are separated for the opponent, implementing
            # the paper's perfect-information-at-new-root assumption.
            group = "fresh-perfect-info:"+identity
            actions = heuristic_actions(continuation)
            sets = information_sets(continuation)
            policy = tuple({key: {a: float(a == actions[p, key]) for a in legal}
                            for key, legal in sets[p].items()} for p in (0, 1))
            heuristic = behavioral_value(continuation, policy)
            alternates[group] = min(heuristic, saved.previous_value)
            gifts[group] = 0.
            # Prior and CF reach are not known at a novel history. Unit values
            # are explicit replenishment conventions, never belief weights.
            reaches[identity], y[group] = 1., 1.
            fresh += 1
        stack = [continuation]
        while stack:
            if deadline is not None and perf_counter() >= deadline:
                raise SearchBudgetError("chess projection deadline")
            child = stack.pop()
            prepared_nodes += 1
            if prepared_nodes > max_nodes:
                raise TreeCapacityError("projected knowledge tree exceeds max_nodes")
            stack.extend(child.children.values())
        branches.append(continuation)
        contexts.append(context)
        paths.append(moves)
        ids.append(identity)
        groups.append(group)
        parent_events.append(None if old_path is None or saved.gift_ledger is None else
                             saved.gift_ledger.roots[int(old_path[0])])

    for path, node, context, moves in selected:
        append(context, moves, node, path)
    # Fresh roots follow Fig. 9 lines 9-13: states are drawn from P \ I, and P
    # is a set of POSITIONS. The tracker samples histories, so two hypotheses can
    # name one position; the second is aliased to the first root rather than
    # duplicating its subtree with a second unit of root mass.
    by_position = {position_key(c.state.fen): identity for c, identity in zip(contexts, ids)
                   if c.memories[own_index] == own_memory}
    aliases = {}
    for h, context, identity in zip(turn.belief.hypotheses, current, current_ids):
        if identity in ids:
            continue
        twin = by_position.get(position_key(context.state.fen))
        if twin is not None:
            aliases[identity] = twin
            continue
        by_position[position_key(context.state.fen)] = identity
        append(context, h.candidate_moves)
    total = fsum(reaches.values())
    root = Node(children={str(i): n for i, n in enumerate(branches)},
                probabilities={str(i): reaches[key]/total for i, key in enumerate(ids)})
    nodes = terminals = depth_seen = 0
    stack = [(root, -1)]
    while stack:
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("chess projection deadline")
        node, level = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise TreeCapacityError("projected knowledge tree exceeds max_nodes")
        depth_seen = max(depth_seen, level)
        terminals += int(node.payoff is not None and not node.cutoff)
        stack.extend((child, level+1) for child in node.children.values())
    root_infoset = viewer+":"+own_memory
    tree = ChessTree(root, tuple(branches), root_infoset, nodes, len(frontiers), terminals,
                     calls, tuple(contexts), frontiers, viewer)
    total_y = fsum(y.values())
    prior = {j: .5/len(y)+.5*(mass/total_y if total_y > 0 else 1/len(y)) for j, mass in y.items()}
    roots = tuple(SubgameRoot(key, group, node, reaches[key]) for key, group, node in zip(ids, groups, branches))
    boundaries = BlueprintBoundaries(roots, alternates, gifts, prior,
        dict(saved_cut=None if boundary is None else boundary.audit,
             fresh_boundary="min(heuristic_minimax_proxy, previous_unshifted_value)",
             all_zero_opponent_reach=total_y == 0,
             fresh_mass="unit_counterfactual_and_opponent_sequence_reach"))
    return ChessProjection(turn, tree, tuple(paths), tuple(ids), tuple(groups), current_ids,
        boundaries, dict(retained=retained, fresh=fresh, knowledge_roots=len(branches),
            outside_current=sum(c.memories[own_index] != own_memory for c in contexts),
            depth=depth_seen, incomplete_cut=incomplete, lazy_neighbours=lazy_neighbours,
            fresh_duplicates=len(aliases)),
        tuple(parent_events), aliases)
