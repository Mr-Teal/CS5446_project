"""Knowledge restriction on an explicitly observed, synchronized toy-game cut."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

from .gadgets import SubgameRoot, build_gadget
from .toy_games import Node, information_sets, terminal


@dataclass(frozen=True)
class CutRoot:
    root_id: str
    own_observation: str
    opponent_observation: str
    continuation: Node
    reach_mass: float = 1.0


@dataclass
class RestrictedSubgame:
    roots: tuple
    distances: dict
    current: tuple
    retained: tuple
    removed: tuple
    frozen: tuple
    active_own: tuple
    mode: str

    def gadget(self, alternate_player0, mode="resolve", group_prior=None):
        return build_gadget(self.roots, alternate_player0, mode, group_prior)


def restrict_cut(roots: Sequence[CutRoot], current_observation: str,
                 blueprint: Mapping[str, Mapping[str, float]], mode="kluss") -> RestrictedSubgame:
    """Restrict a synchronized cut to I^2, then freeze or unfreeze player 0.

    Both players' observations at the cut are EXPLICIT caller data, including
    the nonacting player's observation. They cannot be inferred from Node.player.
    KLSS freezes own continuation infosets not touching the downward closure of
    I^1. KLUSS keeps the same I^2 roots and optimizes all retained own infosets.
    This finite-cut implementation is not a general asynchronous-history graph.
    """
    if mode not in ("klss", "kluss"):
        raise ValueError("mode must be klss or kluss")
    roots = tuple(roots)
    if not roots or len({r.root_id for r in roots}) != len(roots):
        raise ValueError("nonempty roots with unique IDs required")
    for r in roots:
        if any(not isinstance(v, str) or not v for v in
               (r.root_id, r.own_observation, r.opponent_observation)):
            raise ValueError("cut IDs and both observations must be nonempty strings")
    current = {r.root_id for r in roots if r.own_observation == current_observation}
    if not current:
        raise ValueError("current observation is absent from cut")
    # Explicit observation partitions define the cut's knowledge graph.
    distance = {r.root_id: None for r in roots}
    by_id = {r.root_id: r for r in roots}
    queue = deque(sorted(current))
    for key in current:
        distance[key] = 0
    while queue:
        key = queue.popleft()
        a = by_id[key]
        for b in roots:
            if distance[b.root_id] is None and (a.own_observation == b.own_observation or
                                              a.opponent_observation == b.opponent_observation):
                distance[b.root_id] = distance[key] + 1
                queue.append(b.root_id)
    kept = tuple(r for r in roots if distance[r.root_id] is not None and distance[r.root_id] < 2)
    active = set().union(*(set(information_sets(r.continuation)[0]) for r in roots if r.root_id in current))
    retained_own = set().union(*(set(information_sets(r.continuation)[0]) for r in kept))
    frozen = retained_own - active if mode == "klss" else set()
    # Validate same infoset actions across retained roots before converting any
    # nodes to chance, so freezing cannot hide inconsistent definitions.
    action_sets = {}
    own_memory = {}
    for r in kept:
        for p, sets in enumerate(information_sets(r.continuation)):
            for key, actions in sets.items():
                if p == 0:
                    if key in own_memory and own_memory[key] != r.own_observation:
                        raise ValueError("own continuation infoset forgets the cut observation")
                    own_memory[key] = r.own_observation
                identity = (p, key)
                if identity in action_sets and action_sets[identity] != actions:
                    raise ValueError("inconsistent actions across cut roots")
                action_sets[identity] = actions
    for key in frozen:
        if key not in blueprint:
            raise ValueError("missing blueprint at frozen infoset " + key)
        policy = blueprint[key]
        if set(policy) != set(action_sets[(0, key)]) or any(
                not isfinite(v) or v < 0 for v in policy.values()) or abs(sum(policy.values()) - 1) > 1e-9:
            raise ValueError("invalid blueprint at " + key)

    def clone(node):
        if node.payoff is not None:
            return terminal(node.payoff)
        children = {a: clone(child) for a, child in node.children.items()}
        if node.player == 0 and node.infoset in frozen:
            return Node(children=children, probabilities=dict(blueprint[node.infoset]))
        return Node(player=node.player, infoset=node.infoset, children=children,
                    probabilities=dict(node.probabilities))

    kept_ids = {r.root_id for r in kept}
    selected = tuple(SubgameRoot(r.root_id, r.opponent_observation, clone(r.continuation), r.reach_mass)
                     for r in kept)
    return RestrictedSubgame(selected, distance, tuple(sorted(current)), tuple(r.root_id for r in kept),
                             tuple(r.root_id for r in roots if r.root_id not in kept_ids), tuple(sorted(frozen)),
                             tuple(sorted(active)), mode)


def knowledge_demo():
    """A--B--C--D observation chain, plus disconnected E; I^2 retains A,B.

    B's bad blueprint becomes a fixed chance distribution in KLSS. KLUSS can
    improve it. C/D/E have large payoffs to expose accidental inclusion.
    """
    from .toy_games import matching_pennies
    def outside():
        return Node(player=0, infoset="outside", children={"bad": terminal(-1), "good": terminal(1)})
    return [CutRoot("A", "current", "J0", matching_pennies()),
            CutRoot("B", "other", "J0", outside()),
            CutRoot("C", "other", "J1", outside()),
            CutRoot("D", "far", "J1", terminal(10)),
            CutRoot("E", "disconnected", "J2", terminal(-10))], {"outside": {"bad": 1.0, "good": 0.0}}
