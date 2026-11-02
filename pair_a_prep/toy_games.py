"""Small extensive-form games and a normal-form LP reference solver.

One action is selected per information set, not per hidden tree node. This is
an offline oracle for small games, not a reproduction of KLSS or PCFR+.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from itertools import permutations, product
import json
import math
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import scipy
from scipy.optimize import linprog


@dataclass
class Node:
    player: Optional[int] = None  # None means chance or terminal.
    infoset: Optional[str] = None
    children: Dict[str, "Node"] = field(default_factory=dict)
    probabilities: Dict[str, float] = field(default_factory=dict)
    payoff: Optional[float] = None  # Player 0 maximizes; player 1 gets -payoff.
    cutoff: bool = False


def terminal(payoff: float) -> Node:
    return Node(payoff=payoff)


def frontier(estimate: float) -> Node:
    """An expandable cutoff with an estimated payoff from player 0's perspective."""
    return Node(payoff=estimate, cutoff=True)


def information_sets(root: Node) -> Tuple[dict, dict]:
    sets = ({}, {})
    active = set()

    def visit(node: Node) -> None:
        if not isinstance(node, Node):
            raise ValueError("tree children must be Nodes")
        if id(node) in active:
            raise ValueError("tree must be finite and acyclic")
        if not isinstance(node.cutoff, bool) or (node.cutoff and node.payoff is None):
            raise ValueError("cutoff must mark a payoff leaf")
        if node.payoff is not None:
            if node.children or not np.isfinite(node.payoff):
                raise ValueError("invalid terminal")
            return
        if not node.children:
            raise ValueError("nonterminal needs children")
        if node.player is None:
            probabilities = list(node.probabilities.values())
            if (set(node.children) != set(node.probabilities)
                    or not all(np.isfinite(p) and p >= 0 for p in probabilities)
                    or not np.isclose(sum(probabilities), 1)):
                raise ValueError("invalid chance probabilities")
        else:
            if node.player not in (0, 1) or not node.infoset:
                raise ValueError("player nodes need a player and an infoset")
            actions = tuple(node.children)
            old = sets[node.player].setdefault(node.infoset, actions)
            if old != actions:
                raise ValueError("nodes in one infoset need the same action order")
        active.add(id(node))
        for child in node.children.values():
            visit(child)
        active.remove(id(node))

    visit(root)
    return sets


def pure_policies(infosets: Mapping[str, Sequence[str]]) -> list:
    keys = tuple(infosets)
    return [dict(zip(keys, actions)) for actions in product(*(infosets[k] for k in keys))]


def pure_value(node: Node, policies: Sequence[Mapping[str, str]]) -> float:
    if node.payoff is not None:
        return node.payoff
    if node.player is None:
        return sum(p * pure_value(node.children[a], policies) for a, p in node.probabilities.items())
    return pure_value(node.children[policies[node.player][node.infoset]], policies)


def payoff_matrix(root: Node, max_profiles: int = 100_000) -> Tuple[np.ndarray, list, list]:
    sets = information_sets(root)
    counts = [math.prod(len(a) for a in s.values()) for s in sets]
    if counts[0] * counts[1] > max_profiles:
        raise ValueError("normal-form oracle is limited to small games")
    row, col = (pure_policies(s) for s in sets)
    matrix = np.array([[pure_value(root, (p, q)) for q in col] for p in row], dtype=float)
    return matrix, row, col


def _distribution(values: Sequence[float], size: int) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.shape != (size,) or not np.all(np.isfinite(result)) or np.any(result < 0):
        raise ValueError("invalid strategy distribution")
    if not np.isclose(result.sum(), 1):
        raise ValueError("strategy must sum to one")
    return result


def security_bounds(matrix: np.ndarray, row: Sequence[float], col: Sequence[float]) -> dict:
    """Nash gap = max row best response - min column best response.

    Some papers call half this gap exploitability. We report the unhalved gap.
    """
    matrix = np.asarray(matrix, dtype=float)
    row = _distribution(row, matrix.shape[0])
    col = _distribution(col, matrix.shape[1])
    lower = float(np.min(row @ matrix))
    upper = float(np.max(matrix @ col))
    return {"lower": lower, "upper": upper, "nash_gap": upper - lower,
            "profile_value": float(row @ matrix @ col)}


def solve_matrix(matrix: np.ndarray) -> dict:
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or not matrix.size or not np.all(np.isfinite(matrix)):
        raise ValueError("need a finite nonempty payoff matrix")
    m, n = matrix.shape
    # Maximize v subject to A.T p >= v and p in the probability simplex.
    row_lp = linprog(np.r_[np.zeros(m), -1.0],
                     A_ub=np.c_[-matrix.T, np.ones(n)], b_ub=np.zeros(n),
                     A_eq=[np.r_[np.ones(m), 0]], b_eq=[1],
                     bounds=[(0, None)] * m + [(None, None)], method="highs")
    # Minimize w subject to A q <= w and q in the probability simplex.
    col_lp = linprog(np.r_[np.zeros(n), 1.0],
                     A_ub=np.c_[matrix, -np.ones(m)], b_ub=np.zeros(m),
                     A_eq=[np.r_[np.ones(n), 0]], b_eq=[1],
                     bounds=[(0, None)] * n + [(None, None)], method="highs")
    if not row_lp.success or not col_lp.success:
        raise RuntimeError(f"LP failed: {row_lp.message}; {col_lp.message}")
    row = np.maximum(row_lp.x[:m], 0)
    col = np.maximum(col_lp.x[:n], 0)
    row /= row.sum()
    col /= col.sum()
    return {"row_strategy": row.tolist(), "column_strategy": col.tolist(),
            **security_bounds(matrix, row, col)}


def behavioral_value(root: Node, policies: Sequence[Mapping[str, Mapping[str, float]]]) -> float:
    """Evaluate two behavior strategies keyed by each player's own infosets."""
    for player, sets in enumerate(information_sets(root)):
        if set(policies[player]) != set(sets):
            raise ValueError("policy needs exactly this player's infosets")
        for key, actions in sets.items():
            if set(policies[player][key]) != set(actions):
                raise ValueError("wrong actions at infoset")
            _distribution([policies[player][key][a] for a in actions], len(actions))

    def visit(node: Node) -> float:
        if node.payoff is not None:
            return node.payoff
        probs = node.probabilities if node.player is None else policies[node.player][node.infoset]
        return sum(probs[a] * visit(child) for a, child in node.children.items())

    return visit(root)


def behavioral_nash_gap(root: Node, policies: Sequence[Mapping[str, Mapping[str, float]]]) -> float:
    behavioral_value(root, policies)  # Validate before calculating best responses.
    sets = information_sets(root)
    def deterministic(policy, player):
        return {key: {a: float(a == chosen) for a in sets[player][key]}
                for key, chosen in policy.items()}
    responses = []
    for player in (0, 1):
        candidates = []
        for pure in pure_policies(sets[player]):
            profile = list(policies)
            profile[player] = deterministic(pure, player)
            candidates.append(behavioral_value(root, profile))
        responses.append(max(candidates) if player == 0 else min(candidates))
    return responses[0] - responses[1]


def nash_gap(root: Node, policies: Sequence[Mapping[str, Mapping[str, float]]]) -> float:
    """behavioral_nash_gap without enumerating pure strategies.

    Each best response is one pass: infosets are decided deepest own-history
    first, so when an infoset is reached every player node below it already has
    its reply fixed and subtree values can be memoized. Linear in the tree, where
    the oracle above is exponential in the number of infosets; both agree.
    """
    behavioral_value(root, policies)  # Validate before calculating best responses.
    return _best_response_value(root, policies, 0) - _best_response_value(root, policies, 1)


def _best_response_value(root: Node, policies, player: int) -> float:
    members, depth = {}, {}

    def collect(node: Node, reach: float, own_length: int) -> None:
        if node.payoff is not None:
            return
        if node.player == player:
            members.setdefault(node.infoset, []).append((node, reach))
            depth[node.infoset] = own_length
            for child in node.children.values():
                collect(child, reach, own_length + 1)
        else:
            probs = node.probabilities if node.player is None else policies[node.player][node.infoset]
            for action, child in node.children.items():
                collect(child, reach * probs[action], own_length)

    collect(root, 1.0, 0)
    chosen, memo = {}, {}

    def value(node: Node) -> float:
        if node.payoff is not None:
            return node.payoff
        if id(node) in memo:
            return memo[id(node)]
        if node.player == player:
            result = value(node.children[chosen[node.infoset]])
        else:
            probs = node.probabilities if node.player is None else policies[node.player][node.infoset]
            result = sum(probs[a] * value(child) for a, child in node.children.items())
        memo[id(node)] = result
        return result

    for infoset in sorted(members, key=depth.get, reverse=True):
        actions = list(members[infoset][0][0].children)
        totals = {a: sum(reach * value(node.children[a]) for node, reach in members[infoset]) for a in actions}
        chosen[infoset] = (max if player == 0 else min)(totals, key=totals.get)
    return value(root)


def matching_pennies(reveal_first_action: bool = False) -> Node:
    root = Node(player=0, infoset="p0")
    for first in ("H", "T"):
        root.children[first] = Node(player=1,
            infoset=f"p1_after_{first}" if reveal_first_action else "p1_hidden",
            children={second: terminal(1 if first == second else -1) for second in ("H", "T")})
    return root


def hidden_coin(reveal_coin: bool = False) -> Node:
    root = Node(probabilities={"H": 0.75, "T": 0.25})
    for coin in ("H", "T"):
        root.children[coin] = Node(player=0,
            infoset=f"guess_{coin}" if reveal_coin else "guess_hidden",
            children={guess: terminal(1 if guess == coin else -1) for guess in ("H", "T")})
    return root


def kuhn_poker() -> Node:
    """Three cards, ante 1, one bet of 1; each player sees only their own card."""
    root = Node()
    for first, second in permutations(range(3), 2):
        sign = 1 if first > second else -1
        p0_reply = Node(player=0, infoset=f"p0:{first}:check_bet",
                        children={"fold": terminal(-1), "call": terminal(2 * sign)})
        p1_after_check = Node(player=1, infoset=f"p1:{second}:check",
                             children={"check": terminal(sign), "bet": p0_reply})
        p1_after_bet = Node(player=1, infoset=f"p1:{second}:bet",
                           children={"fold": terminal(1), "call": terminal(2 * sign)})
        deal = f"{first}{second}"
        root.children[deal] = Node(player=0, infoset=f"p0:{first}:start",
                                   children={"check": p1_after_check, "bet": p1_after_bet})
        root.probabilities[deal] = 1 / 6
    return root


def reference_report() -> dict:
    games = {"matching_pennies_hidden": (matching_pennies(), 0.0),
             "matching_pennies_revealed": (matching_pennies(True), -1.0),
             "coin_hidden": (hidden_coin(), 0.5), "coin_revealed": (hidden_coin(True), 1.0),
             "kuhn_poker": (kuhn_poker(), -1 / 18)}
    reports = {}
    for name, (root, expected) in games.items():
        matrix, row, col = payoff_matrix(root)
        solution = solve_matrix(matrix)
        if abs(solution["profile_value"] - expected) > 1e-8 or solution["nash_gap"] > 1e-8:
            raise AssertionError(f"reference mismatch for {name}")
        reports[name] = {"shape": list(matrix.shape), "expected_value": expected,
                         **solution, "row_pure_policies": row, "column_pure_policies": col}
    reports["biased_matrix"] = solve_matrix(np.array([[2, -1], [-2, 3]]))
    return {"scope": "small-game reference only; no chess agent or KLSS implemented",
            "solver": "scipy.optimize.linprog(method='highs'), full normal form",
            "numpy_version": np.__version__, "scipy_version": scipy.__version__,
            "payoff_perspective": "player_0", "gap_convention": "unhalved best-response gap",
            "games": reports}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = reference_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, result in report["games"].items():
        print(f"{name}: value={result['profile_value']:.10f}, gap={result['nash_gap']:.3g}")


if __name__ == "__main__":
    main()
