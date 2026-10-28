"""Budgeted sampled-root search with uniform growth, not complete Obscuro."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from time import perf_counter

from fow_shared.contracts import Decision
from .chess_search import build_chess_tree, expand_chess_tree, SearchBudgetError, TreeCapacityError
from .pcfr import PCFRPlus
from .search_agent import FixedDepthPCFRAgent, SearchResult
from .toy_games import behavioral_value, information_sets


@dataclass(frozen=True)
class AnytimeConfig:
    initial_depth: int = 1
    max_depth: int = 3
    rounds: int = 24
    rounds_per_stage: int = 4
    final_rounds: int = 4
    max_nodes: int = 5000
    max_evaluator_calls: int = 128
    schedule: str = "alternating"
    stop_on_time: bool = True
    expansion_fraction: float = 0.7

    def __post_init__(self):
        for key in ("initial_depth", "max_depth", "rounds", "rounds_per_stage",
                    "max_nodes", "max_evaluator_calls", "final_rounds"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(key + " must be a positive integer")
        if self.max_depth < self.initial_depth or self.max_nodes < 2:
            raise ValueError("invalid depth or node limits")
        if self.final_rounds > self.rounds or self.schedule not in ("alternating", "simultaneous"):
            raise ValueError("invalid final-round reserve or schedule")
        if type(self.stop_on_time) is not bool or not 0 < self.expansion_fraction < 1:
            raise ValueError("invalid clock configuration")


class AnytimePCFRAgent(FixedDepthPCFRAgent):
    """Rebuild per turn, then retain solver state across uniform growth steps.

    act() can return an observation-only uniform fallback if initial preparation
    exceeds a budget. solve()/label() instead raise: no values are invented for
    an incomplete tree. Evaluator and invalid-input failures propagate.
    """

    name = "uniform-growth-pcfr-prototype-v1"

    def __init__(self, evaluator, config=None, initial_fen=None):
        super().__init__(evaluator, config or AnytimeConfig(), initial_fen)
        self.last_stop_reason = None
        self.last_tree = self.last_solver = None
        self.last_evaluator_calls = 0

    def reset(self, player, seed):
        super().reset(player, seed)
        self.last_stop_reason = None
        self.last_tree = self.last_solver = None
        self.last_evaluator_calls = 0

    @property
    def config_id(self):
        payload = dict(version=1, search=asdict(self.config), initial_fen=self.initial_fen,
                       leaf={"name": self.evaluator.name, **{
                           key: getattr(self.evaluator, key) for key in
                           ("depth", "new_game_each_call", "call_timeout_s")
                           if hasattr(self.evaluator, key)}},
                       roots="input_belief_weights", infosets="complete_private_stream",
                       growth="uniform_all_frontiers", policy="raw_last_iterate",
                       no_move_rule="terminal_draw_v1",
                       fallback="uniform_observed_legal_moves_no_labels")
        return "uniform-growth-v1:" + sha256(json.dumps(
            payload, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]

    def solve(self, turn):
        if self._player != turn.observation.player:
            raise ValueError("reset for the acting player before solving")
        if turn.observation.terminal or not turn.observation.legal_moves:
            raise ValueError("search requires a nonterminal acting observation with legal moves")
        self.last_result = None
        self.last_tree = self.last_solver = None
        self.last_stop_reason = None
        self.last_evaluator_calls = 0
        started = perf_counter()
        deadline = started + turn.time_budget_ms / 1000 if self.config.stop_on_time else None
        growth_deadline = (started + turn.time_budget_ms / 1000 * self.config.expansion_fraction
                           if self.config.stop_on_time else None)
        calls = 0
        owner = self

        class CountedLeaf:
            def evaluate_children(self, fen):
                nonlocal calls
                if calls >= owner.config.max_evaluator_calls:
                    raise SearchBudgetError("evaluator_limit")
                if growth_deadline is not None and perf_counter() >= growth_deadline:
                    raise SearchBudgetError("growth_deadline")
                calls += 1
                owner.last_evaluator_calls = calls
                return owner.evaluator.evaluate_children(fen)

        leaf = CountedLeaf()
        try:
            tree = build_chess_tree(turn, leaf, initial_fen=self.initial_fen,
                                    depth=self.config.initial_depth, max_nodes=self.config.max_nodes,
                                    deadline=growth_deadline)
        except (SearchBudgetError, TreeCapacityError):
            self.last_stop_reason = "initial_budget"
            raise
        solver = PCFRPlus(tree.root, schedule=self.config.schedule)
        initial_ms = (perf_counter() - started) * 1000
        solving_ms = growth_ms = 0.0
        depth, expansions, growth_reason = self.config.initial_depth, 0, None
        next_growth = self.config.rounds_per_stage
        while solver.rounds < self.config.rounds:
            if deadline is not None and perf_counter() >= deadline:
                break
            stage_started = perf_counter()
            solver.step()
            solving_ms += (perf_counter() - stage_started) * 1000
            if growth_reason is not None or solver.rounds < next_growth:
                continue
            if depth >= self.config.max_depth:
                growth_reason = "max_depth"
            elif not tree.frontiers:
                growth_reason = "terminal_tree"
            elif solver.rounds >= self.config.rounds - self.config.final_rounds:
                growth_reason = "final_round_reserve"
            elif growth_deadline is not None and perf_counter() >= growth_deadline:
                growth_reason = "growth_deadline"
            elif calls >= self.config.max_evaluator_calls:
                growth_reason = "evaluator_limit"
            else:
                stage_started = perf_counter()
                try:
                    tree = expand_chess_tree(tree, solver, leaf, max_nodes=self.config.max_nodes,
                                             deadline=growth_deadline)
                except TreeCapacityError:
                    growth_reason = "node_limit"
                except SearchBudgetError:
                    growth_reason = ("evaluator_limit" if calls >= self.config.max_evaluator_calls
                                     else "growth_deadline")
                else:
                    depth += 1
                    expansions += 1
                    next_growth = solver.rounds + self.config.rounds_per_stage
                finally:
                    growth_ms += (perf_counter() - stage_started) * 1000
        self.last_stop_reason = ("deadline" if solver.rounds < self.config.rounds else "round_limit")
        final_started = perf_counter()
        profile = solver.policy()
        policy = profile[0][tree.root_infoset]
        values = tuple(behavioral_value(root, tuple(
            {key: profile[p][key] for key in sets}
            for p, sets in enumerate(information_sets(root)))) for root in tree.continuations)
        value = sum(h.weight * v for h, v in zip(turn.belief.hypotheses, values))
        move = self._rng.choices(list(policy), weights=list(policy.values()), k=1)[0]
        elapsed = (perf_counter() - started) * 1000
        diagnostics = dict(search_nodes=float(tree.nodes), solver_rounds=float(solver.rounds),
                           search_depth=float(depth), expansions=float(expansions),
                           evaluator_calls=float(calls), elapsed_ms=elapsed,
                           over_budget=float(elapsed > turn.time_budget_ms),
                           terminal_leaves=float(tree.terminal_leaves),
                           frontier_leaves=float(tree.frontier_leaves), solver_root_value=value,
                           fallback=0.0)
        diagnostics.update(initial_ms=initial_ms, solving_ms=solving_ms, growth_ms=growth_ms,
                           finalizing_ms=(perf_counter() - final_started) * 1000)
        diagnostics["stop:" + self.last_stop_reason] = 1.0
        diagnostics["growth_stop:" + (growth_reason or "round_limit")] = 1.0
        diagnostics.update({"played_policy:" + m: p for m, p in policy.items()})
        decision = Decision(move, policy, diagnostics)
        decision.validate_for(turn.observation)
        self.last_tree, self.last_solver = tree, solver
        self.last_result = SearchResult(decision, values, value)
        return self.last_result

    def act(self, turn):
        started = perf_counter()
        try:
            return self.solve(turn).decision
        except (SearchBudgetError, TreeCapacityError):
            moves = turn.observation.legal_moves
            policy = {move: 1 / len(moves) for move in moves}
            elapsed = (perf_counter() - started) * 1000
            diagnostics = {"fallback": 1.0, "stop:initial_budget": 1.0,
                           "elapsed_ms": elapsed, "over_budget": float(elapsed > turn.time_budget_ms),
                           "evaluator_calls": float(self.last_evaluator_calls),
                           "solver_rounds": 0.0, "expansions": 0.0, "search_depth": 0.0}
            diagnostics.update({"played_policy:" + m: p for m, p in policy.items()})
            decision = Decision(self._rng.choice(moves), policy, diagnostics)
            decision.validate_for(turn.observation)
            return decision
