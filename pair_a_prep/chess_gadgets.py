"""Bridge private-history chess roots to explicit Resolve/Maxmargin gadgets.

Root belief weights, externally supplied reach masses and Resolve group priors
are separate inputs. This does not compute paper-specific alternate/gift values,
root replenishment or a KLUSS knowledge closure.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from math import fsum
from random import Random
from time import perf_counter
from typing import Mapping, Optional

from fow_shared.contracts import AgentInput, Decision, TrainingRecord
from fow_shared.interfaces import LeafEvaluator
from .chess_search import ChessTree, build_chess_tree, expand_chess_tree, SearchBudgetError
from .gadgets import Gadget, SubgameRoot, build_gadget, regrow_blended
from .pcfr import PCFRPlus
from .toy_games import behavioral_value


RULES_ID = "paper_fow_v1_proposed"
NO_MOVE_RULE = "terminal_draw_v1"


@dataclass(frozen=True)
class ChessRootGroups:
    """A single sampled-root tree, with all tuples in original belief order."""

    turn: AgentInput
    chess_tree: ChessTree
    root_ids: tuple[str, ...]
    opponent_infosets: tuple[str, ...]
    settings: dict

    @property
    def groups(self) -> dict:
        groups = {}
        for root_id, key in zip(self.root_ids, self.opponent_infosets):
            groups.setdefault(key, []).append(root_id)
        return {key: tuple(ids) for key, ids in groups.items()}

    @property
    def belief_weights(self) -> dict:
        return {root_id: h.weight for root_id, h in zip(self.root_ids, self.turn.belief.hypotheses)}

    def build(self, alternate_player0: Mapping[str, float], *,
              reach_mass: Mapping[str, float], mode: str = "resolve",
              group_prior: Optional[Mapping[str, float]] = None) -> ChessGadget:
        """Require explicit root reaches, alternates and Resolve group prior.

        Player 0 is the current chess player, even if Black. NEGATE any alternate
        expressed as opponent utility. No alternate or prior is inferred from a
        leaf value, label, belief weight or history count.
        """
        if set(reach_mass) != set(self.root_ids):
            raise ValueError("reach_mass must cover exactly the sampled root IDs")
        if mode in ("resolve", "blended") and group_prior is None:
            raise ValueError("Resolve and blended gadgets require an explicit group_prior")
        roots = tuple(SubgameRoot(root_id, key, continuation, reach_mass[root_id])
                      for root_id, key, continuation in zip(
                          self.root_ids, self.opponent_infosets, self.chess_tree.continuations))
        gadget = build_gadget(roots, alternate_player0, mode=mode, group_prior=group_prior)
        return ChessGadget(self, gadget, dict(reach_mass),
                           None if group_prior is None else dict(group_prior))


def prepare_chess_roots(turn: AgentInput, evaluator: LeafEvaluator, *,
                        initial_fen: Optional[str] = None, depth: int = 2,
                        max_nodes: int = 5000, deadline=None) -> ChessRootGroups:
    """Build the chess tree once; group by opponent private memory at its cut.

    Root IDs identify hypothetical paths, but NEVER identify a player's infoset.
    In the current public-start, full-history tracker, distinct candidates
    generally have distinct opponent memories: the opponent remembers its own
    different hidden actions. Shared opponent infosets can still occur among
    future continuations when our subsequent actions are invisible to it.
    """
    tree = build_chess_tree(turn, evaluator, initial_fen=initial_fen, depth=depth,
                            max_nodes=max_nodes, deadline=deadline)
    opponent = "black" if turn.observation.player == "white" else "white"
    opponent_index = 0 if opponent == "white" else 1
    root_ids = tuple("chess-root:" + sha256(json.dumps(
        [h.fen, h.candidate_moves], separators=(",", ":")).encode("ascii")).hexdigest()
                     for h in turn.belief.hypotheses)
    if len(set(root_ids)) != len(root_ids):
        raise ValueError("duplicate reconstructed history, even with different history_id aliases")
    groups = tuple(opponent + ":" + root.memories[opponent_index] for root in tree.history_roots)
    return ChessRootGroups(turn, tree, root_ids, groups,
                           dict(initial_fen=initial_fen, depth=depth, max_nodes=max_nodes,
                                evaluator=evaluator.name, root_identity="fen_and_complete_candidate_path",
                                infosets="complete_private_stream", prototype=True))


@dataclass(frozen=True)
class ChessGadgetValues:
    root_policy: dict
    hypothesis_values: tuple[float, ...]
    root_value: float
    # The solver objective, including opt-out/offsets, is NOT the label target.
    gadget_value: float


@dataclass(frozen=True)
class ChessGadget:
    roots: ChessRootGroups
    gadget: Gadget
    reach_mass: dict
    group_prior: Optional[dict]
    # Fast path (Gadget.FAST, blended gadgets): the structural solver on the raw chess tree, kept from the previous
    # expansion while its root is this bridge's raw root. Not part of the bridge's value.
    raw_solver: Optional[PCFRPlus] = field(default=None, compare=False, repr=False)

    def expand(self, solver: PCFRPlus, evaluator: LeafEvaluator, *,
               additional_depth: int = 1, max_nodes: int = 5000,
               max_evaluator_calls: Optional[int] = None, deadline=None,
               selected_paths=None, initialize_best=False) -> ChessGadget:
        """Grow a complete chess frontier cut and preserve gadget solver state.

        Return a new bridge only after an atomic graft. Resolve paths include
        enter; Maxmargin paths include the selected opponent group. Replacement
        nodes are cloned by the original gadget builder, preserving opponent
        key rewriting and the group's payoff offset. max_nodes bounds the raw
        chess tree, not the additional gadget/validation workspace.
        """
        if solver.root is not self.gadget.tree:
            raise ValueError("solver must use this bridge's current gadget tree")
        if evaluator.name != self.roots.settings["evaluator"]:
            raise ValueError("growth must use the same evaluator identity as preparation")
        if not self.roots.chess_tree.frontiers:
            return self
        paths = tuple(self.roots.chess_tree.frontiers) if selected_paths is None else tuple(selected_paths)
        if not paths:
            return self
        # This temporary solver validates the raw graft; it has no trained state.
        # The caller's trained gadget solver is untouched until all preparation
        # and cloning succeed. On the fast path a blended bridge reuses the one
        # its previous expansion grew (expand() then indexes only the graft),
        # and rebuilds only the grown continuations of the gadget.
        fast = Gadget.FAST and self.gadget.mode == "blended" and self.group_prior is not None
        raw_solver = self.raw_solver
        if not (fast and raw_solver is not None and raw_solver.root is self.roots.chess_tree.root
                and raw_solver.schedule == solver.schedule):
            raw_solver = PCFRPlus(self.roots.chess_tree.root, schedule=solver.schedule)
        grown = expand_chess_tree(self.roots.chess_tree, raw_solver, evaluator,
                                  additional_depth=additional_depth, max_nodes=max_nodes,
                                  max_evaluator_calls=max_evaluator_calls, deadline=deadline,
                                  selected_paths=paths)
        settings = {**self.roots.settings,
                    "depth": max(self.roots.settings["depth"], max(len(p) - 1 + additional_depth for p in paths)),
                    "max_nodes": max_nodes,
                    "growth": "uniform_frontier_v1" if selected_paths is None else "selected_history_v1",
                    "growth_steps": [*self.roots.settings.get("growth_steps", []),
                                     dict(rounds_before=solver.rounds,
                                          selected_paths=paths,
                                          additional_depth=additional_depth,
                                          max_nodes=max_nodes)]}
        roots = replace(self.roots, chess_tree=grown, settings=settings)
        if fast:
            # = roots.build(...) for the same alternates, reach masses and group prior; only the tree differs.
            if set(self.reach_mass) != set(roots.root_ids):
                raise ValueError("reach_mass must cover exactly the sampled root IDs")
            grafts = {}  # root_id -> [(path in its continuation, grafted raw subtree)]
            for path in paths:
                node = grown.continuations[int(path[0])]
                for action in path[1:]:
                    node = node.children[action]
                grafts.setdefault(self.roots.root_ids[int(path[0])], []).append((path[1:], node))
            subgame_roots = tuple(SubgameRoot(root_id, key, continuation, self.reach_mass[root_id])
                                  for root_id, key, continuation in zip(
                                      roots.root_ids, roots.opponent_infosets, grown.continuations))
            candidate = ChessGadget(roots, regrow_blended(self.gadget, subgame_roots, grafts, self.group_prior,
                                                          None),
                                    dict(self.reach_mass), dict(self.group_prior), raw_solver)
        else:
            candidate = roots.build(self.gadget.alternate_player0, reach_mass=self.reach_mass,
                                    mode=self.gadget.mode, group_prior=self.group_prior)
        replacements = {}
        for path in paths:
            index = int(path[0])
            root_id = self.roots.root_ids[index]
            if self.gadget.mode == "resolve":
                gadget_path = (root_id, "enter") + path[1:]
            elif self.gadget.mode == "blended":
                gadget_path = (root_id,) + path[1:]
            else:
                gadget_path = (self.roots.opponent_infosets[index], root_id) + path[1:]
            if fast:
                node = candidate.gadget.continuations[root_id]
                for action in path[1:]:
                    node = node.children[action]
            else:
                node = candidate.gadget.tree
                for action in gadget_path:
                    node = node.children[action]
            replacements[gadget_path] = node
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("budget exhausted before gadget expansion commit")
        initial_actions = {}
        if initialize_best:
            from .search_policies import heuristic_actions
            for subtree in replacements.values():
                for key, action in heuristic_actions(subtree).items():
                    initial_actions.setdefault(key, action)
        solver.expand(replacements, initial_actions=initial_actions)
        if fast:  # the regrown gadget is new and ours: set its tree in place, keeping what it has validated
            candidate.gadget.tree = solver.root
            return candidate
        return replace(candidate, gadget=replace(candidate.gadget, tree=solver.root))

    def evaluate_profile(self, profile) -> ChessGadgetValues:
        """Evaluate the SAME raw profile, including unreachable continuations."""
        gadget_value = behavioral_value(self.gadget.tree, profile)
        by_id = self.gadget.continuation_values(profile)
        values = tuple(by_id[root_id] for root_id in self.roots.root_ids)
        value = fsum(h.weight * v for h, v in zip(self.roots.turn.belief.hypotheses, values))
        policy = dict(profile[0][self.roots.chess_tree.root_infoset])
        return ChessGadgetValues(policy, values, value, gadget_value)

    def solve(self, rounds: int = 100, schedule: str = "alternating") -> ChessGadgetSolution:
        """Fixed-work solve; no dynamic growth, purification or mode switching."""
        if type(rounds) is not int or rounds < 1:
            raise ValueError("rounds must be a positive integer")
        solver = PCFRPlus(self.gadget.tree, schedule=schedule)
        solver.run(rounds)
        return self.solution(solver)

    def solution(self, solver: PCFRPlus) -> ChessGadgetSolution:
        """Export a trained current gadget solver without restarting its rounds."""
        if solver.root is not self.gadget.tree or solver.rounds < 1:
            raise ValueError("solution requires a trained solver on this bridge's current tree")
        profile = solver.policy()
        configuration = dict(version=1, chess=self.roots.settings, mode=self.gadget.mode,
                             rules="teal-rules-adapter", rules_id=RULES_ID, no_move_rule=NO_MOVE_RULE,
                             rounds=solver.rounds, schedule=solver.schedule,
                             predictive=solver.predictive, averaging_power=solver.averaging_power,
                             policy="raw_last_iterate",
                             root_ids=self.roots.root_ids,
                             belief_weights=self.roots.belief_weights,
                             root_groups=dict(zip(self.roots.root_ids, self.roots.opponent_infosets)),
                             reach_mass=self.reach_mass, group_prior=self.group_prior,
                             alternate_player0=self.gadget.alternate_player0)
        digest = sha256(json.dumps(configuration, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]
        return ChessGadgetSolution(self.roots.turn, self.evaluate_profile(profile), profile,
                                    configuration, "chess-gadget-prototype-v1:" + digest)


@dataclass(frozen=True)
class ChessGadgetSolution:
    turn: AgentInput
    values: ChessGadgetValues
    profile: tuple
    configuration: dict
    config_id: str

    def training_record(self, *, seed: int, game_id: str) -> TrainingRecord:
        """Sample the raw policy and export unshifted continuation labels."""
        if type(seed) is not int or not game_id.strip():
            raise ValueError("an integer seed and nonblank game_id are required")
        policy = dict(self.values.root_policy)
        draw, total, selected = Random(seed).random(), 0.0, None
        for move, probability in policy.items():
            if probability > 0:
                selected = move
                total += probability
                if draw < total:
                    break
        diagnostics = {"played_policy:" + move: p for move, p in policy.items()}
        diagnostics.update(solver_root_value=self.values.gadget_value,
                           solver_rounds=float(self.configuration["rounds"]),
                           gadget_resolve=float(self.configuration["mode"] == "resolve"))
        decision = Decision(selected, policy, diagnostics)
        return TrainingRecord(self.turn, decision, self.values.root_value,
                              self.values.hypothesis_values, seed,
                              "fixed-depth-chess-gadget-prototype-v1", self.config_id, game_id)
