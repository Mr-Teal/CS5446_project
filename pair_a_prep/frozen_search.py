"""Controlled initialization comparisons on one immutable projected target game."""

from copy import deepcopy
from hashlib import sha256
import json

from .chess_subgame_agent import opponent_key_map
from .finite_security import finite_security
from .gadget_frames import _node_data
from .pcfr import PCFRPlus
from .search_policies import heuristic_actions, seed_new
from .warm_start import rebase_solver


METHODS = ("heuristic_warm", "seeded_cold", "round_aligned_seeded_cold")


def tree_digest(root):
    return sha256(json.dumps(_node_data(root), allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def state_digest(solver):
    data = dict(tree=tree_digest(solver.root), rounds=solver.rounds, policy=solver.policy(),
        initial_actions=[(p, key, action) for (p, key), action in solver._initial_actions.items()],
        minimizers=[{key: dict(regrets=item.regrets.tolist(), previous_utility=item.previous_utility.tolist(),
                    strategy=item.strategy.tolist(), pending=item._pending) for key, item in player.items()}
                    for player in solver.minimizers],
        sums=[{key: value.tolist() for key, value in player.items()} for player in solver._sums],
        previous_opponent=[None if player is None else {key: value.tolist() for key, value in player.items()}
                           for player in solver._previous_opponent])
    return sha256(json.dumps(data, allow_nan=False, sort_keys=True).encode()).hexdigest()


def initialize_frozen_solver(previous, projection, target_root, method):
    if method not in METHODS:
        raise ValueError("unknown frozen initialization method")
    if method == "heuristic_warm":
        solver, retained = rebase_solver(previous, deepcopy(target_root), opponent_key_map(projection))
        seed_new(solver, retained)
    else:
        solver = PCFRPlus(deepcopy(target_root), predictive=previous.predictive,
            averaging_power=previous.averaging_power, schedule=previous.schedule,
            initial_actions=heuristic_actions(target_root))
        retained = ((), ())
        if method == "round_aligned_seeded_cold":
            solver.rounds = previous.rounds
            if solver.schedule == "alternating" and solver.rounds:
                # Publish the fresh seeded policies before held-feedback stepping.
                for player in (0, 1):
                    solver._prepare(player)
    return solver, retained


def compare_frozen(saved, projection, *, mode="maxmargin", checkpoints=(0, 1, 4, 8), evaluator_name="material"):
    """Equal additional full CFR rounds; no evaluator calls, growth or mode switch.

    Historical sums/predictors are part of the warm initialization bundle.
    Equal rounds are not claimed to equalize wall time or all arithmetic work.
    """
    if projection.boundaries is None:
        raise ValueError("a projected boundary game is required")
    if (not checkpoints or checkpoints[0] != 0 or any(type(n) is not int or n < 0 for n in checkpoints)
            or tuple(sorted(set(checkpoints))) != tuple(checkpoints)):
        raise ValueError("checkpoints must be increasing distinct nonnegative integers starting at zero")
    source_before = state_digest(saved.raw_solver)
    bridge = projection.bridge(mode, evaluator_name)
    target = bridge.gadget.tree
    fingerprint = tree_digest(target)
    target_nodes, stack = 0, [target]
    while stack:
        node = stack.pop()
        target_nodes += 1
        stack.extend(node.children.values())
    results = []
    for method in METHODS:
        solver, retained = initialize_frozen_solver(saved.raw_solver, projection, target, method)
        started_round = solver.rounds
        initial_state = state_digest(solver)
        traversals = [0]
        original = solver._utilities
        def counted(player, opponent=None):
            traversals[0] += 1
            return original(player, opponent)
        solver._utilities = counted
        rows, completed = [], 0
        for checkpoint in checkpoints:
            solver.run(checkpoint-completed)
            completed = checkpoint
            profiles = {}
            for label, average in (("last", False), ("average", True)):
                profile = solver.policy(average)
                values = bridge.gadget.continuation_values(profile)
                selected = [values[key] for key in projection.current_ids]
                profiles[label] = dict(security=finite_security(solver.root, profile),
                    root_policy=profile[0][projection.tree.root_infoset], input_hypothesis_values=selected,
                    input_belief_continuation_value=sum(h.weight*v for h, v in
                        zip(projection.turn.belief.hypotheses, selected)))
            if tree_digest(solver.root) != fingerprint:
                raise AssertionError("target tree changed during frozen solve")
            rows.append(dict(additional_rounds=checkpoint, solver_rounds=solver.rounds,
                solver_utility_traversals=traversals[0], profiles=profiles))
        results.append(dict(method=method, target_tree_sha256=fingerprint,
            initial_rounds=started_round, initial_state_sha256=initial_state,
            retained_infosets=[len(keys) for keys in retained], checkpoints=rows))
    source_after = state_digest(saved.raw_solver)
    if source_after != source_before:
        raise AssertionError("frozen comparison mutated the saved source")
    return dict(scope="same finite target game; initialization bundle comparison only", mode=mode,
        target_tree_sha256=fingerprint, target_nodes=target_nodes, raw_chess_nodes=projection.tree.nodes,
        active_gadget_infosets=[len(PCFRPlus(target).sets[p]) for p in (0, 1)],
        source_rounds=saved.raw_solver.rounds, input_roots=len(projection.current_ids),
        solved_roots=len(projection.root_ids), projection_audit=projection.audit,
        source_state_sha256=source_before, source_unchanged=True,
        evaluator_calls_during_comparison=0, tree_growth=False, mode_switches=False,
        metrics_scope="finite estimated sampled gadget; not full-game exploitability or strength",
        methods=results)
