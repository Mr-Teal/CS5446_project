"""Read-only reach diagnostics for real saved-tree projection transitions.

Current-profile reach ratios are observations, not a conversion of accumulated
CFR regret. Complete solver reuse requires a separate full-game certificate.
"""

from math import fsum, isclose, isfinite

from .affine_solver import certify_affine_game
from .chess_projection import root_identity
from .rules_adapter import RulesAdapter
from .toy_games import information_sets


def _walk(root, path, profile):
    node = root
    cf, joint = [1., 1.], 1.
    for action in path:
        if node.payoff is not None or action not in node.children:
            return None
        probability = (node.probabilities if node.player is None else profile[node.player][node.infoset])[action]
        joint *= probability
        for player in (0, 1):
            if node.player != player:
                cf[player] *= probability
        node = node.children[action]
    return node, cf, joint


def _ratio(old, new):
    if old > 0 and new > 0:
        return dict(status="positive", scale=new/old)
    if old == 0 and new > 0:
        return dict(status="new_positive_from_zero_source", scale=None)
    if old > 0:
        return dict(status="zero_target_reach", scale=None)
    return dict(status="both_zero", scale=None)


def _summary(rows, player):
    ratios = [row["cf_scale_candidates"][player] for row in rows if row["source_path"] is not None]
    positive = [row["scale"] for row in ratios if row["status"] == "positive"]
    return dict(scope="matched roots and current profile only",
        positive_rows=len(positive), min_scale=min(positive) if positive else None,
        max_scale=max(positive) if positive else None,
        uniform_positive_ratios=bool(positive) and all(isclose(x, positive[0], rel_tol=1e-10, abs_tol=1e-12) for x in positive),
        new_positive_from_zero_source=sum(row["status"] == "new_positive_from_zero_source" for row in ratios),
        zero_target_reach=sum(row["status"] == "zero_target_reach" for row in ratios),
        both_zero=sum(row["status"] == "both_zero" for row in ratios))


def audit_transition(saved, projection):
    """Trace full private paths and compare each player's old/new CF root reach.

    Input consists of already available hypothetical states and private paths;
    there is no true-board/referee argument. No solver or tree is mutated.
    """
    if projection.boundaries is None:
        raise ValueError("a projected transition with declared boundaries is required")
    if projection.turn.observation.player != saved.turn.observation.player:
        raise ValueError("utility viewer must remain unchanged")
    if projection.turn.observation.ply <= saved.turn.observation.ply:
        raise ValueError("a later private turn is required")
    expected = (len(projection.paths), len(projection.root_ids), len(projection.groups),
                len(projection.tree.history_roots), len(projection.tree.continuations))
    if len(set(expected)) != 1 or len(set(projection.root_ids)) != expected[0]:
        raise ValueError("projection roots need consistent lengths and distinct history IDs")
    declared = {root.root_id: root.reach_mass for root in projection.boundaries.roots}
    if set(declared) != set(projection.root_ids):
        raise ValueError("boundary IDs must match the projection exactly")
    if any(not isfinite(value) or value < 0 for value in declared.values()):
        raise ValueError("finite nonnegative declared reaches required")
    total = fsum(declared.values())
    if not isfinite(total) or total <= 0:
        raise ValueError("positive declared reach normalizer required")
    if set(projection.tree.root.children) != {str(i) for i in range(expected[0])}:
        raise ValueError("raw chance branch IDs must match projected root order")
    if set(projection.tree.root.probabilities) != set(projection.tree.root.children):
        raise ValueError("raw chance probabilities must cover exactly the branches")
    if saved.raw_solver.root != saved.tree.root:
        raise ValueError("saved raw solver and saved tree disagree")
    profile = saved.raw_solver.policy()
    rows = []
    rules = RulesAdapter()
    for index, (moves, identity, group, context, target) in enumerate(zip(projection.paths,
            projection.root_ids, projection.groups, projection.tree.history_roots, projection.tree.continuations)):
        if identity != root_identity(context.state.fen, moves):
            raise ValueError("private path does not match the declared root identity")
        q = projection.tree.root.probabilities[str(index)]
        if not isclose(q, declared[identity]/total, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("raw projection chance differs from declared normalized reaches")
        record = dict(root_id=identity, candidate_moves=list(moves), group=group,
            declared_reach=declared[identity], target_raw_chance=q, source_path=None,
            source_cf_reach=None, source_joint_reach=None, cf_scale_candidates=None,
            local_affine=None, origin="fresh")
        if not group.startswith("fresh-perfect-info:"):
            matches = []
            for old_index, prefix in enumerate(saved.paths):
                if tuple(moves[:len(prefix)]) == tuple(prefix):
                    path = (str(old_index),)+tuple(moves[len(prefix):])
                    walked = _walk(saved.tree.root, path, profile)
                    if walked is not None:
                        matches.append((old_index, path, walked))
            if len(matches) != 1:
                raise ValueError("retained root must have one full-history ancestor")
            old_index, path, (source, cf, joint) = matches[0]
            state = saved.tree.history_roots[old_index].state
            for action in path[1:]:
                state = rules.apply_move(state, action)
            if state.fen != context.state.fen:
                raise ValueError("retained hypothetical replay disagrees with projected state")
            if not isclose(declared[identity], cf[1], rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError("retained declared mass differs from source player-1 CF reach")
            try:
                mapping = certify_affine_game(source, target)
                local = dict(verified=True, scale=mapping.scale, offset=mapping.offset, reason=None)
            except ValueError as error:
                local = dict(verified=False, scale=None, offset=None, reason=str(error))
            record.update(source_path=list(path), source_cf_reach=cf, source_joint_reach=joint,
                cf_scale_candidates=[_ratio(value, q) for value in cf], local_affine=local,
                origin="retained_cutoff" if source.cutoff else "retained_subtree")
        rows.append(record)
    source_sets, target_sets = saved.raw_solver.sets, information_sets(projection.tree.root)
    infosets = []
    for player in (0, 1):
        compatible = {key for key, actions in target_sets[player].items() if source_sets[player].get(key) == actions}
        infosets.append(dict(compatible_action_keys=len(compatible),
            new_or_changed=len(set(target_sets[player])-compatible),
            removed_or_changed=len(set(source_sets[player])-compatible)))
    try:
        mapping = certify_affine_game(saved.tree.root, projection.tree.root)
        full = dict(verified=True, scale=mapping.scale, offset=mapping.offset, reason=None)
    except ValueError as error:
        full = dict(verified=False, scale=None, offset=None, reason=str(error))
    return dict(scope="instantaneous read-only projection audit; no cumulative-state conversion",
        source_ply=saved.turn.observation.ply, target_ply=projection.turn.observation.ply,
        normalizer=total, rows=rows, cf_scales=[_summary(rows, p) for p in (0, 1)],
        infosets=infosets, full_game_affine=full,
        source_roots=len(saved.paths), target_roots=len(rows),
        fresh_roots=sum(row["origin"] == "fresh" for row in rows),
        local_affine_roots=sum(row["local_affine"] is not None and row["local_affine"]["verified"] for row in rows),
        accumulated_regret_transport_authorized=False)
