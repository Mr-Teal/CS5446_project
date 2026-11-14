"""Safety rule and opponent-aware weights around the search agent (15 Nov 2026; follows the qa4 gap note and the
offline test in fow-work/policy/prior_weights_offline.py).

``factory = pair_a_prep.safety_agent:SafeSearchFactory`` builds the usual search agent (evaluation_factories.
SearchFactory, same settings) and wraps it. Extra settings:

  safety_rule = true|false   After the search picks a move: if that move lets the opponent capture our king at
      once on ANY sampled board, and some legal move does not, play the safe move with the highest solver value
      instead. Solver value of a root move = belief-weighted mean of its per-board value under the solved profile
      (as the re-solve labels compute it; on gadget turns the solver is first mapped back to the raw tree, as
      ChessSubgameAgent.solve does). When no solve is available (a budget fallback), the leaf average of the
      agent's own evaluator ranks the safe moves.
  prior = none|policy-last-move, prior_checkpoint, prior_device   Before the search: each sampled board's weight
      is set proportional to our policy network's probability of the opponent's LAST move on that board's path,
      scored on the board before that move as a one-board belief (the model assumes the opponent sees that board).
      The search uses belief weights only on fresh-tree turns (chess_projection.py:130); the new weights also
      weight the safety rule's solver values.
  wrapper_reserve_ms (default 150)   time kept back from the inner search for the wrapper's own work; the prior's
      time is also taken out of the inner search's budget, so the whole move stays within the turn's budget.

Diagnostics added (floats): safety_override, safety_unsafe_moves, safety_value_from_solver,
safety_blueprint_dropped, prior_applied, prior_max_weight, wrapper_ms.
After an override the inner agent's saved blueprint is discarded, so the next turn is built as a fresh tree.
"""
from __future__ import annotations

import math
from dataclasses import replace
from time import perf_counter
from typing import Mapping

import chess

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis
from fow_shared.values import standard_fen

from .chess_subgame_agent import opponent_key_map
from .evaluation_factories import SearchFactory
from .toy_games import information_sets, value_walk
from .warm_start import rebase_solver


def loses_king(fen: str, move: str) -> bool:
    """True if, on the board `fen` (side to move = us), playing `move` lets the opponent capture our king at once."""
    board = chess.Board(fen)
    me = board.turn
    board.push(chess.Move.from_uci(move))
    if board.king(not me) is None:  # the move captured their king
        return False
    king = board.king(me)
    return king is None or any(m.to_square == king for m in board.pseudo_legal_moves)


def solver_values(agent, turn: AgentInput, moves) -> dict | None:
    """Belief-weighted value of each root move under the agent's last solve of `turn`, or None if there is none."""
    projection, solver, bridge = agent.last_projection, agent.last_solver, agent.last_bridge
    if projection is None or solver is None or projection.turn is not turn:
        return None
    raw = solver if bridge is None else rebase_solver(
        solver, projection.tree.root, opponent_key_map(projection, to_raw=True))[0]
    profile = raw.policy()
    by_id = {}
    for identity, root in zip(projection.root_ids, projection.tree.continuations):
        sets = information_sets(root)
        local = tuple({key: profile[p][key] for key in sets[p]} for p in (0, 1))
        by_id[identity] = {a: value_walk(child, local) for a, child in root.children.items()}
    ids = [projection.aliases.get(k, k) for k in projection.current_ids]
    weights = [h.weight for h in turn.belief.hypotheses]
    total = sum(weights)
    return {a: sum(w / total * by_id[i][a] for w, i in zip(weights, ids)) for a in moves}


def leaf_average(evaluator, turn: AgentInput, moves) -> dict:
    total = sum(h.weight for h in turn.belief.hypotheses)
    out = dict.fromkeys(moves, 0.0)
    for h in turn.belief.hypotheses:
        children = evaluator.evaluate_children(h.fen)
        for a in moves:
            out[a] += h.weight / total * float(children[a])
    return out


class LastMovePrior:
    """Weights of the sampled boards from our policy network's probability of the opponent's last move."""

    def __init__(self, checkpoint: str, device: str):
        from pairb.policy_agent import PolicyFactory
        self.policy = PolicyFactory({"checkpoint_path": checkpoint, "device": device}).load_model()
        self.policy.reset("white", 0)
        from pairb.rules import pick_rules
        self.rules = pick_rules("teal")  # Teal's RulesAdapter behind pairb's wrapper, as the offline test used
        self.cache: dict = {}

    def probability(self, state, move: str) -> float:
        fen = standard_fen(self.rules.board(state))
        key = (fen, move)
        if key not in self.cache:
            player = self.rules.current_player(state)
            obs = self.rules.observe(state, player)
            belief = Belief(player=player, ply=obs.ply, hypotheses=(Hypothesis(fen=fen, weight=1.0),),
                            population_size=1, weighting="uniform")
            probs = self.policy.move_probabilities(AgentInput(obs, belief, 1000, ()))
            p = probs.get(move, probs.get(move[:4] + "q", 0.0)) if len(move) == 5 else probs.get(move, 0.0)
            self.cache[key] = max(p, 1e-6)
        return self.cache[key]

    def weights(self, turn: AgentInput, initial_fen=None) -> list[float]:
        me = turn.observation.player
        raw = []
        for h in turn.belief.hypotheses:
            state, last = self.rules.initial_state(initial_fen), None
            for move in h.candidate_moves:
                if self.rules.current_player(state) != me:
                    last = (state, move)
                state = self.rules.apply_move(state, move)
            raw.append(1.0 if last is None else self.probability(*last))
        total = math.fsum(raw)
        return [r / total for r in raw]


class SafeSearchAgent:
    def __init__(self, inner, safety: bool, prior: LastMovePrior | None, reserve_ms: float, initial_fen=None):
        self.inner, self.safety, self.prior, self.reserve_ms = inner, safety, prior, reserve_ms
        self.initial_fen = initial_fen
        self.name = inner.name + ("+safety" if safety else "") + ("+prior" if prior else "")

    def reset(self, player: str, seed: int) -> None:
        self.inner.reset(player, seed)

    def act(self, turn: AgentInput) -> Decision:
        started = perf_counter()
        inner_turn, extra = turn, {"prior_applied": 0.0, "prior_max_weight": 0.0}
        if self.prior is not None:
            weights = self.prior.weights(turn, self.initial_fen)
            hyps = tuple(replace(h, weight=w) for h, w in zip(turn.belief.hypotheses, weights))
            inner_turn = replace(turn, belief=replace(turn.belief, hypotheses=hyps, weighting="policy-last-move"))
            extra.update(prior_applied=1.0, prior_max_weight=max(weights))
        moves = turn.observation.legal_moves
        unsafe = ({a for a in moves if any(loses_king(h.fen, a) for h in turn.belief.hypotheses)}
                  if self.safety else set())
        spent = (perf_counter() - started) * 1000
        inner_turn = replace(inner_turn, time_budget_ms=max(1, int(turn.time_budget_ms - spent - self.reserve_ms)))
        decision = self.inner.act(inner_turn)
        extra.update(safety_override=0.0, safety_unsafe_moves=float(len(unsafe)), safety_value_from_solver=0.0,
                     safety_blueprint_dropped=0.0)
        if self.safety and decision.move in unsafe and len(unsafe) < len(moves):
            values = solver_values(self.inner, inner_turn, moves)
            extra["safety_value_from_solver"] = float(values is not None)
            if values is None:
                values = leaf_average(self.inner.evaluator, inner_turn, moves)
            move = max((a for a in moves if a not in unsafe), key=lambda a: values[a])
            decision = Decision(move, {a: float(a == move) for a in moves}, dict(decision.diagnostics))
            extra["safety_override"] = 1.0
            # The played move may have zero probability in the solved strategy, and the saved blueprint would then
            # carry zero reach into the next turn's gadget ("zero counterfactual reach at boundary"). Discard it, as
            # ChessSubgameAgent.fallback_decision does when it plays a move the blueprint did not choose.
            if getattr(self.inner, "saved", None) is not None:
                self.inner.saved = None
                extra["safety_blueprint_dropped"] = 1.0
        extra["wrapper_ms"] = (perf_counter() - started) * 1000
        decision = Decision(decision.move, decision.root_policy, {**decision.diagnostics, **extra})
        decision.validate_for(turn.observation)
        return decision


def _true(settings, key, default):
    value = settings.get(key, default).strip().lower()
    if value not in ("true", "false"):
        raise ValueError(f"{key} must be true or false")
    return value == "true"


class SafeSearchFactory:
    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings
        self.inner = SearchFactory(settings)

    def load_model(self) -> SafeSearchAgent:
        s = self.settings
        prior_kind = s.get("prior", "none").strip()
        if prior_kind not in ("none", "policy-last-move"):
            raise ValueError("prior must be none or policy-last-move")
        prior = (LastMovePrior(s["prior_checkpoint"].strip(), s.get("prior_device", "cpu").strip())
                 if prior_kind == "policy-last-move" else None)
        fen = s.get("initial_fen", "").strip() or None
        return SafeSearchAgent(self.inner.load_model(), _true(s, "safety_rule", "true"), prior,
                               float(s.get("wrapper_reserve_ms", "150")), fen)

    def reset_game(self) -> None:
        self.inner.reset_game()
