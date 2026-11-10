"""Budgeted sampled-root search with optional selective growth, not full Obscuro."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from time import perf_counter

from fow_shared.contracts import Decision
from .chess_search import build_chess_tree, expand_chess_tree, SearchBudgetError, TreeCapacityError
from .pcfr import PCFRPlus
from .one_sided import OneSidedExpansion
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
    growth: str = "uniform"
    # Nodes under max_nodes that in-turn growth leaves free, so that the next turn's projection of the saved
    # tree (which in fog keeps nearly everything) still has room for fresh roots. 0 = grow to the cap.
    growth_headroom: int = 0

    def __post_init__(self):
        for key in ("initial_depth", "max_depth", "rounds", "rounds_per_stage",
                    "max_nodes", "max_evaluator_calls", "final_rounds"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(key + " must be a positive integer")
        if self.max_depth < self.initial_depth or self.max_nodes < 2:
            raise ValueError("invalid depth or node limits")
        if type(self.growth_headroom) is not int or not 0 <= self.growth_headroom < self.max_nodes:
            raise ValueError("growth_headroom must be an integer in [0, max_nodes)")
        if self.final_rounds > self.rounds or self.schedule not in ("alternating", "simultaneous"):
            raise ValueError("invalid final-round reserve or schedule")
        if type(self.stop_on_time) is not bool or not 0 < self.expansion_fraction < 1:
            raise ValueError("invalid clock configuration")
        if self.growth not in ("uniform", "one_sided"):
            raise ValueError("growth must be uniform or one_sided")


class AnytimePCFRAgent(FixedDepthPCFRAgent):
    """Rebuild per turn, then retain solver state across configured growth steps.

    act() can return an observation-only uniform fallback if initial preparation
    exceeds a budget. solve()/label() instead raise: no values are invented for
    an incomplete tree. Evaluator and invalid-input failures propagate.
    """

    name = "uniform-growth-pcfr-prototype-v1"
    ROUND_BATCH = 32  # most rounds per solver.run() call between two clock checks

    def __init__(self, evaluator, config=None, initial_fen=None):
        super().__init__(evaluator, config or AnytimeConfig(), initial_fen)
        if self.config.growth == "one_sided":
            self.name = "one-sided-pcfr-prototype-v1"
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
                       growth=self.config.growth, policy="raw_last_iterate",
                       initial_policy="heuristic_best" if self.config.growth == "one_sided" else "uniform",
                       evaluation_cache="solve_local_fen_estimates_v1",
                       uniform_depth="per_frontier_cap_v2",
                       no_move_rule="terminal_draw_v1",
                       fallback="uniform_observed_legal_moves_no_labels")
        return self.name + ":" + sha256(json.dumps(
            payload, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]

    def _prepare_tree(self, turn, leaf, deadline):
        return build_chess_tree(turn, leaf, initial_fen=self.initial_fen,
                                depth=self.config.initial_depth, max_nodes=self.config.max_nodes,
                                deadline=deadline)

    def _prepare_solver(self, tree):
        from .search_policies import heuristic_actions
        return PCFRPlus(tree.root, schedule=self.config.schedule,
                        initial_actions=heuristic_actions(tree.root) if self.config.growth == "one_sided" else None)

    def _remember(self, turn, tree, solver):
        pass

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
            def __init__(self):
                self.cache = {}

            def evaluate_children(self, fen):
                nonlocal calls
                if growth_deadline is not None and perf_counter() >= growth_deadline:
                    raise SearchBudgetError("growth_deadline")
                if fen not in self.cache:
                    if calls >= owner.config.max_evaluator_calls:
                        raise SearchBudgetError("evaluator_limit")
                    calls += 1
                    owner.last_evaluator_calls = calls
                    self.cache[fen] = dict(owner.evaluator.evaluate_children(fen))
                return dict(self.cache[fen])

        leaf = CountedLeaf()
        try:
            tree = self._prepare_tree(turn, leaf, growth_deadline)
        except (SearchBudgetError, TreeCapacityError):
            self.last_stop_reason = "initial_budget"
            raise
        solver = self._prepare_solver(tree)
        starting_rounds = solver.rounds
        target_rounds = starting_rounds + self.config.rounds
        initial_ms = (perf_counter() - started) * 1000
        solving_ms = growth_ms = 0.0
        stack, depth = [(tree.root, -1)], 0
        while stack:
            node, level = stack.pop()
            depth = max(depth, level)
            stack.extend((child, level+1) for child in node.children.values())
        expansions, growth_reason = 0, None
        sampler = OneSidedExpansion(self._rng.getrandbits(64)) if self.config.growth == "one_sided" else None
        next_growth = starting_rounds + self.config.rounds_per_stage
        while solver.rounds < target_rounds:
            if deadline is not None and perf_counter() >= deadline:
                break
            # The rounds up to the next growth check (or the target) run as one batch; with a clock, a batch has
            # at most ROUND_BATCH rounds, which is the granularity of the deadline check.
            batch = target_rounds - solver.rounds
            if growth_reason is None:
                batch = min(batch, next_growth - solver.rounds)
            if deadline is not None:
                batch = min(batch, self.ROUND_BATCH)
            stage_started = perf_counter()
            solver.run(batch)
            solving_ms += (perf_counter() - stage_started) * 1000
            if growth_reason is not None or solver.rounds < next_growth:
                continue
            if sampler is None and not any(len(path)-1 < self.config.max_depth for path in tree.frontiers):
                growth_reason = "max_depth"
            elif not tree.frontiers:
                growth_reason = "terminal_tree"
            elif solver.rounds >= target_rounds - self.config.final_rounds:
                growth_reason = "final_round_reserve"
            elif growth_deadline is not None and perf_counter() >= growth_deadline:
                growth_reason = "growth_deadline"
            elif calls >= self.config.max_evaluator_calls:
                growth_reason = "evaluator_limit"
            else:
                stage_started = perf_counter()
                try:
                    proposal = sampler.select(tree, solver, self.config.max_depth, growth_deadline) if sampler else None
                    if sampler and proposal is None:
                        next_growth = solver.rounds + self.config.rounds_per_stage
                        continue
                    tree = expand_chess_tree(tree, solver, leaf, max_nodes=self.config.max_nodes,
                                             deadline=growth_deadline,
                                             selected_paths=(proposal[0],) if sampler else tuple(
                                                 path for path in tree.frontiers if len(path)-1 < self.config.max_depth),
                                             initialize_best=sampler is not None)
                except TreeCapacityError:
                    growth_reason = "node_limit"
                except SearchBudgetError:
                    growth_reason = ("evaluator_limit" if calls >= self.config.max_evaluator_calls
                                     else "growth_deadline")
                else:
                    if sampler:
                        sampler.commit(proposal)
                        depth = max(depth, len(proposal[0]))
                    else:
                        depth = max(depth, max((len(path)-1 for path in tree.frontiers), default=depth))
                    expansions += 1
                    next_growth = solver.rounds + self.config.rounds_per_stage
                finally:
                    growth_ms += (perf_counter() - stage_started) * 1000
        self.last_stop_reason = ("deadline" if solver.rounds < target_rounds else "round_limit")
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
        diagnostics["solver_rounds_this_turn"] = float(solver.rounds - starting_rounds)
        diagnostics.update(initial_ms=initial_ms, solving_ms=solving_ms, growth_ms=growth_ms,
                           finalizing_ms=(perf_counter() - final_started) * 1000)
        diagnostics["stop:" + self.last_stop_reason] = 1.0
        diagnostics["growth_stop:" + (growth_reason or "round_limit")] = 1.0
        diagnostics.update({"played_policy:" + m: p for m, p in policy.items()})
        decision = Decision(move, policy, diagnostics)
        decision.validate_for(turn.observation)
        self.last_tree, self.last_solver = tree, solver
        self.last_result = SearchResult(decision, values, value)
        self._remember(turn, tree, solver)
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
