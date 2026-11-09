"""Small fixed-tree Resolve/Maxmargin gadgets with explicit payoff conventions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import fsum, isfinite
import os
from typing import Mapping, Optional, Sequence

import numpy as np

from .toy_games import Node, behavioral_value, information_sets, terminal, value_walk


PREFIX = "__gadget__:"


def _key(*parts: str) -> str:
    return PREFIX + json.dumps(parts, separators=(",", ":"))


@dataclass(frozen=True)
class SubgameRoot:
    root_id: str
    opponent_infoset: str
    continuation: Node
    reach_mass: float


@dataclass
class Gadget:
    tree: Node
    mode: str
    roots: tuple
    continuations: dict
    alternate_player0: dict
    # Resolve's actual root probabilities; Maxmargin lets player 1 choose J.
    root_prior: Optional[dict]

    def continuation_values(self, policies) -> dict:
        """Evaluate entering each root under the supplied behavioral profile.

        No opt-out or Maxmargin offset enters these values. Restrict the full
        gadget profile to each continuation's infosets without changing actions.
        """
        values = {}
        for root_id, node in self.continuations.items():
            sets = information_sets(node)
            local = tuple({key: policies[p][key] for key in sets[p]} for p in (0, 1))
            values[root_id] = behavioral_value(node, local)
        return values

    # The per-round entry below validates once per gadget; FOW_GADGET_FAST=0 makes it continuation_values every call.
    FAST = os.environ.get("FOW_GADGET_FAST", "1") != "0"

    def round_values(self, policies) -> dict:
        """continuation_values for the per-round controller (BlendedGadgetControl.update), validated once.

        The first call on this gadget is continuation_values itself, with all its checks and errors. Later calls
        walk the continuations only (toy_games.value_walk: the operations of behavioral_value in the same order,
        so the values are identical), without re-deriving their information sets and re-validating the profile:
        a gadget's trees never change (an expansion returns a new Gadget, which validates again), and the
        per-round profile is the solver's, whose strategies are distributions by construction. With FAST off
        every call is continuation_values.
        """
        if not self.FAST or not self.__dict__.get("_validated"):
            values = self.continuation_values(policies)
            self._validated = self.FAST
            return values
        return {root_id: value_walk(node, policies) for root_id, node in self.continuations.items()}

    def solver_values(self, solver) -> dict:
        """round_values(solver.policy()) for the solver that solves this gadget, without the profile dictionaries.

        On the native backend (blended gadget, the solver's root is this gadget's tree, first call done) the kernel
        walks each continuation where it sits in the solver's flat tree, under the published strategies that
        policy() returns, in value_walk's floating-point order (pcfr_behavioral_values). In a blended gadget
        tree.children[root_id] is the continuation: the same object until the first expansion, after it the
        solver's graft of the same structure. Otherwise, and for the first call, round_values(solver.policy()).
        """
        native = getattr(solver, "_native", None)
        if (native is None or not self.FAST or self.mode != "blended" or solver.root is not self.tree
                or not self.__dict__.get("_validated")):
            return self.round_values(solver.policy())
        positions = self.__dict__.get("_positions")
        if positions is None:
            order = {action: i for i, action in enumerate(self.tree.children)}
            positions = self._positions = np.array([order[root_id] for root_id in self.continuations], dtype=np.int64)
        nodes = native.child[native.child_begin[0] + positions]
        return dict(zip(self.continuations, native.behavioral_values(nodes).tolist()))

    def belief_value(self, policies, weights: Mapping[str, float]) -> float:
        """Explicit label weights, independent of the gadget's opponent prior."""
        if set(weights) != set(self.continuations):
            raise ValueError("belief weights must cover exactly the root IDs")
        probabilities = _distribution(weights, "belief weights")
        values = self.continuation_values(policies)
        return fsum(probabilities[key] * values[key] for key in probabilities)


def _distribution(values, name):
    if not values or any(not isfinite(v) or v < 0 for v in values.values()):
        raise ValueError(name + " must be finite and nonnegative")
    total = fsum(values.values())
    if abs(total - 1) > 1e-9:
        raise ValueError(name + " must sum to one")
    return dict(values)


def build_gadget(roots: Sequence[SubgameRoot], alternate_player0: Mapping[str, float],
                 mode: str = "resolve", group_prior: Optional[Mapping[str, float]] = None) -> Gadget:
    """Player 0 resolves; player 1 is the opponent and minimizes player-0 payoff.

    alternate_player0[J] is player 0's payoff if the opponent exits at J
    (NEGATE an alternate value expressed as opponent utility before passing it).
    Resolve: chance picks a root, then opponent chooses enter/exit knowing J.
    Maxmargin: opponent selects J, chance selects a root conditional on J,
    and continuation terminal payoffs subtract alternate_player0[J].
    Blended (Obscuro Fig. 9 l.16-23, Fig. 10 l.7-13): one shared continuation
    tree under a chance root whose distribution over J is re-blended every
    round by subgame_boundaries.BlendedGadgetControl; "exit:J" children carry
    the Resolve mass that takes the alternate, so the opponent has no root move
    and the gadget never has to be rebuilt to change mode.
    reach_mass supplies externally computed nonnegative conditional root mass;
    this module does not compute blueprint reaches, gifts or Obscuro's C.3 prior.
    """
    if mode not in ("resolve", "maxmargin", "blended"):
        raise ValueError("mode must be resolve, maxmargin or blended")
    roots = tuple(roots)
    if not roots or any(not isinstance(r.root_id, str) or not r.root_id or
                        not isinstance(r.opponent_infoset, str) or not r.opponent_infoset for r in roots):
        raise ValueError("nonempty roots and root/infoset IDs required")
    if len({r.root_id for r in roots}) != len(roots):
        raise ValueError("duplicate root ID")
    groups = {}
    for r in roots:
        if not isfinite(r.reach_mass) or r.reach_mass < 0:
            raise ValueError("reach mass must be finite and nonnegative")
        groups.setdefault(r.opponent_infoset, []).append(r)
        for sets in information_sets(r.continuation):
            if any(key.startswith(PREFIX) for key in sets):
                raise ValueError("continuation uses reserved gadget namespace")
    masses = {j: fsum(r.reach_mass for r in group) for j, group in groups.items()}
    if any(m <= 0 for m in masses.values()):
        raise ValueError("each opponent infoset needs positive total reach mass")
    if set(alternate_player0) != set(groups) or any(not isfinite(v) for v in alternate_player0.values()):
        raise ValueError("one finite alternate payoff per opponent infoset required")
    if mode == "maxmargin" and group_prior is not None:
        raise ValueError("Maxmargin has an opponent selector, not a fixed group prior")
    if group_prior is not None and set(group_prior) != set(groups):
        raise ValueError("group prior must cover exactly the opponent infosets")
    total = fsum(masses.values())
    prior = _distribution(group_prior, "group prior") if group_prior is not None else {
        j: m / total for j, m in masses.items()}

    def clone(node, group, offset=0.0):
        if node.payoff is not None:
            return Node(payoff=node.payoff - offset, cutoff=node.cutoff)
        # Opponent remembers J and its gadget action. Player 0 is NOT told J
        # or root identity: preserve all its original cross-root infoset keys.
        key = (_key("continuation", group, node.infoset) if node.player == 1 else node.infoset)
        return Node(player=node.player, infoset=key,
                    children={a: clone(child, group, offset) for a, child in node.children.items()},
                    probabilities=dict(node.probabilities))

    continuations = {r.root_id: clone(r.continuation, r.opponent_infoset) for r in roots}
    conditional = {r.root_id: r.reach_mass / masses[r.opponent_infoset] for r in roots}
    if mode == "resolve":
        root_prior = {r.root_id: prior[r.opponent_infoset] * conditional[r.root_id] for r in roots}
        tree = Node(probabilities=root_prior.copy(), children={r.root_id: Node(
            player=1, infoset=_key("enter", r.opponent_infoset), children={
                "enter": continuations[r.root_id],
                "exit": terminal(alternate_player0[r.opponent_infoset])}) for r in roots})
    elif mode == "blended":
        # Starts as Resolve's distribution with no exit mass; the controller
        # overwrites tree.probabilities in place before the first round.
        root_prior = {r.root_id: prior[r.opponent_infoset] * conditional[r.root_id] for r in roots}
        root_prior.update({"exit:" + j: 0.0 for j in groups})
        children = {r.root_id: continuations[r.root_id] for r in roots}
        children.update({"exit:" + j: terminal(alternate_player0[j]) for j in groups})
        tree = Node(probabilities=root_prior, children=children)
    else:
        root_prior = None
        tree = Node(player=1, infoset=_key("select"), children={j: Node(
            probabilities={r.root_id: conditional[r.root_id] for r in group},
            children={r.root_id: clone(r.continuation, j, alternate_player0[j]) for r in group})
            for j, group in groups.items()})
    # Reuse solver validation to reject incompatible actions/own histories
    # across roots; importing here avoids any dependency on chess or Pair B.
    from .pcfr import PCFRPlus
    PCFRPlus(tree)
    return Gadget(tree, mode, roots, continuations, dict(alternate_player0), root_prior)


def main() -> None:
    """Write a reproducible tiny-game comparison against the LP oracle."""
    import argparse
    from pathlib import Path
    from .pcfr import PCFRPlus
    from .toy_games import payoff_matrix, solve_matrix

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=2000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    roots = [SubgameRoot("a", "A", Node(player=0, infoset="decision", children={
        "L": terminal(1), "R": terminal(-1)}), 3),
        SubgameRoot("b", "B", Node(player=0, infoset="decision", children={
        "L": terminal(-1), "R": terminal(1)}), 1)]
    report = {"scope": "fixed-tree gadget verification, not KLUSS or full Obscuro",
              "payoffs": "player_0", "label_weights": {"a": 0.9, "b": 0.1}, "games": {}}
    for name, mode, prior in [("resolve", "resolve", None),
                               ("resolve_custom_prior", "resolve", {"A": 0.25, "B": 0.75}),
                               ("maxmargin", "maxmargin", None)]:
        gadget = build_gadget(roots, {"A": 0, "B": 0.4}, mode=mode, group_prior=prior)
        solver = PCFRPlus(gadget.tree, schedule="alternating")
        solver.run(args.rounds)
        result = {"oracle_value": solve_matrix(payoff_matrix(gadget.tree)[0])["profile_value"],
                  "metrics": solver.metrics(), "root_prior": gadget.root_prior,
                  "alternate_player0": gadget.alternate_player0}
        for label, average in (("last", False), ("average", True)):
            policy = solver.policy(average)
            result[label] = {"policy": policy,
                             "continuation_values": gadget.continuation_values(policy),
                             "belief_value": gadget.belief_value(policy, report["label_weights"])}
        report["games"][name] = result
        print(name, json.dumps(result["metrics"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
