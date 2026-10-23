"""History-based, fixed-depth chess trees for the existing PCFR+ solver.

This is a sampled-root game, not the paper's KLUSS subgame construction.
Only player-visible observations and that player's actions enter infoset keys.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter
from typing import Optional

from fow_shared.contracts import AgentInput, Observation
from fow_shared.interfaces import LeafEvaluator
from .rules_adapter import RuleState, RulesAdapter
from .toy_games import Node, terminal


class TreeCapacityError(RuntimeError):
    """The complete requested tree did not fit; no partial tree is returned."""


class SearchBudgetError(RuntimeError):
    """Tree construction exceeded its cooperative wall-clock budget."""


class UnresolvedNoMoveError(RuntimeError):
    """The rule profile supplies neither an action nor a terminal outcome."""


def observation_key(observation: Observation) -> str:
    """Canonical private evidence, independent of dictionary/set ordering."""
    value = asdict(observation)
    value["visible_squares"] = sorted(value["visible_squares"])
    value["legal_moves"] = sorted(value["legal_moves"])
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _extend(memory: str, observation: Observation, own_move: Optional[str]) -> str:
    payload = json.dumps([memory, own_move, observation_key(observation)], separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoryRoot:
    state: RuleState
    # White and Black private streams, not hashes of the full hypothetical path.
    memories: tuple[str, str]


def reconstruct_roots(turn: AgentInput, rules: RulesAdapter,
                      initial_fen: Optional[str] = None, deadline=None) -> tuple[HistoryRoot, ...]:
    """Replay sampled hypothetical paths from the publicly configured start.

    Complete own history is required after ply zero. FEN-only roots cannot
    reconstruct repetition or the opponent's private stream and are rejected.
    No true midgame board or opponent's actual action is an argument.
    """
    if [e.observation.ply for e in turn.history] != list(range(turn.observation.ply)):
        raise ValueError("search needs the complete private observation history from ply zero")
    viewer = turn.observation.player
    roots = []
    for hypothesis in turn.belief.hypotheses:
        if len(hypothesis.candidate_moves) != turn.observation.ply:
            raise ValueError("hypothesis needs a complete candidate_moves path")
        state = rules.initial_state(initial_fen)
        memories = ["", ""]
        for ply in range(turn.observation.ply + 1):
            if deadline is not None and perf_counter() >= deadline:
                raise SearchBudgetError("budget exhausted during candidate replay")
            views = [rules.observe(state, p) for p in ("white", "black")]
            for i, view in enumerate(views):
                previous_move = (hypothesis.candidate_moves[ply - 1]
                                 if ply and view.player != rules.current_player(state) else None)
                memories[i] = _extend(memories[i], view, previous_move)
            observed = views[0 if viewer == "white" else 1]
            expected = (turn.history[ply].observation if ply < turn.observation.ply
                        else turn.observation)
            if observation_key(observed) != observation_key(expected):
                raise ValueError("candidate path disagrees with private observation history")
            if ply < turn.observation.ply:
                move = hypothesis.candidate_moves[ply]
                own_move = move if rules.current_player(state) == viewer else None
                if turn.history[ply].own_move != own_move:
                    raise ValueError("candidate path disagrees with known own action")
                state = rules.apply_move(state, move)
        if state.fen != hypothesis.fen:
            raise ValueError("candidate path does not reconstruct its hypothesis FEN")
        roots.append(HistoryRoot(state, tuple(memories)))
    own_index = 0 if viewer == "white" else 1
    if len({r.memories[own_index] for r in roots}) != 1:
        raise ValueError("sampled roots must share the current player's private history")
    return tuple(roots)


@dataclass
class ChessTree:
    root: Node
    continuations: tuple[Node, ...]
    root_infoset: str
    nodes: int
    frontier_leaves: int
    terminal_leaves: int
    evaluator_calls: int
    # Internal sampled histories aligned with continuations and the input belief.
    history_roots: tuple[HistoryRoot, ...] = ()


def build_chess_tree(turn: AgentInput, evaluator: LeafEvaluator, *,
                     initial_fen: Optional[str] = None, depth: int = 2,
                     max_nodes: int = 5000, deadline=None) -> ChessTree:
    """Expand every legal action to a common ply depth, without action pruning.

    Player 0 is the acting player (including Black). Chance selects hypotheses
    with their input weights. Real terminal outcomes use the retained history;
    remaining frontier values come from evaluate_children, in mover perspective.
    """
    if type(depth) is not int or depth < 1:
        raise ValueError("depth must be a positive integer")
    if type(max_nodes) is not int or max_nodes < 2:
        raise ValueError("max_nodes must be an integer of at least two")
    if turn.observation.terminal:
        raise ValueError("cannot search a terminal turn")
    if 1 + len(turn.belief.hypotheses) > max_nodes:
        raise TreeCapacityError("sampled root nodes alone exceed max_nodes")
    rules = RulesAdapter()
    roots = reconstruct_roots(turn, rules, initial_fen, deadline)
    viewer = turn.observation.player
    stats = dict(nodes=0, frontier_leaves=0, terminal_leaves=0, evaluator_calls=0)
    cache = {}

    def reserve():
        if deadline is not None and perf_counter() >= deadline:
            raise SearchBudgetError("budget exhausted during tree construction")
        stats["nodes"] += 1
        if stats["nodes"] > max_nodes:
            raise TreeCapacityError(f"requested tree exceeds max_nodes={max_nodes}")

    def ended_value(state):
        ended = rules.terminal(state)
        if ended is None:
            return None
        return 0.0 if ended.winner == "draw" else 1.0 if ended.winner == viewer else -1.0

    def expand(state, memories, remaining):
        reserve()
        value = ended_value(state)
        if value is not None:
            stats["terminal_leaves"] += 1
            return terminal(value)
        mover = rules.current_player(state)
        actions = rules.legal_moves(state)
        if not actions:
            raise UnresolvedNoMoveError("no legal move and no rule result; no draw/loss/pass assumed")
        index = 0 if mover == "white" else 1
        node = Node(player=0 if mover == viewer else 1,
                    infoset=mover + ":" + memories[index])
        children = {action: rules.apply_move(state, action) for action in actions}
        estimates = None
        if remaining == 1 and any(ended_value(c) is None for c in children.values()):
            if state.fen not in cache:
                answer = dict(evaluator.evaluate_children(state.fen))
                stats["evaluator_calls"] += 1
                if set(answer) != set(actions) or any(
                        not isfinite(v) or not -1 <= v <= 1 for v in answer.values()):
                    raise ValueError("leaf evaluator must return one finite [-1,1] value per legal action")
                cache[state.fen] = answer
            estimates = cache[state.fen]
        for action, child in children.items():
            if remaining == 1:
                reserve()
                value = ended_value(child)
                if value is None:
                    stats["frontier_leaves"] += 1
                    value = estimates[action] * (1 if mover == viewer else -1)
                else:
                    stats["terminal_leaves"] += 1
                # A blocked frontier is unresolved even if an evaluator guesses a draw.
                if ended_value(child) is None and not rules.legal_moves(child):
                    raise UnresolvedNoMoveError("blocked frontier has no agreed rule result")
                node.children[action] = terminal(float(value))
            else:
                next_memories = tuple(_extend(memories[i], rules.observe(child, p),
                                              action if p == mover else None)
                                      for i, p in enumerate(("white", "black")))
                node.children[action] = expand(child, next_memories, remaining - 1)
        return node

    reserve()  # The sampled-root chance node also counts against the capacity.
    branches = tuple(expand(r.state, r.memories, depth) for r in roots)
    root = Node(children={str(i): n for i, n in enumerate(branches)},
                probabilities={str(i): h.weight for i, h in enumerate(turn.belief.hypotheses)})
    keys = {n.infoset for n in branches}
    if len(keys) != 1:
        raise ValueError("root policy is not shared across sampled hypotheses")
    return ChessTree(root, branches, branches[0].infoset, history_roots=roots, **stats)
