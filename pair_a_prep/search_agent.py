"""A bounded fixed-depth PCFR+ chess prototype, not a complete Obscuro agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from random import Random
from time import perf_counter
from typing import Optional

from fow_shared.contracts import AgentInput, Decision, TrainingRecord
from fow_shared.interfaces import LeafEvaluator
from .chess_search import build_chess_tree
from .pcfr import PCFRPlus
from .toy_games import behavioral_value, information_sets


@dataclass(frozen=True)
class SearchConfig:
    depth: int = 2
    rounds: int = 16
    max_nodes: int = 5000
    schedule: str = "alternating"
    # Fixed-work label pilots disable the clock for reproducible solver work.
    stop_on_time: bool = True

    def __post_init__(self):
        for key in ("depth", "rounds", "max_nodes"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(key + " must be a positive integer")
        if self.max_nodes < 2 or self.schedule not in ("alternating", "simultaneous"):
            raise ValueError("invalid capacity or schedule")
        if type(self.stop_on_time) is not bool:
            raise ValueError("stop_on_time must be a bool")


@dataclass(frozen=True)
class SearchResult:
    decision: Decision
    hypothesis_values: tuple[float, ...]
    root_value: float


class FixedDepthPCFRAgent:
    name = "fixed-depth-pcfr-prototype-v1"

    def __init__(self, evaluator: LeafEvaluator, config: Optional[SearchConfig] = None,
                 initial_fen: Optional[str] = None):
        self.evaluator = evaluator
        self.config = config or SearchConfig()
        self.initial_fen = initial_fen
        self._player = None
        self._seed = None
        self._rng = Random()
        self.last_result = None

    @property
    def config_id(self):
        """Search identity; label_pilot separately identifies tracker/run settings."""
        configuration = dict(version=1, search=asdict(self.config), leaf=self.evaluator.name,
                             initial_fen=self.initial_fen, root_prior="input_belief_weights",
                             infosets="complete_private_stream", policy="raw_last_iterate",
                             tree="fixed_full_width_no_gadget", no_move_rule="terminal_draw_v1")
        digest = sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()[:16]
        return "fixed-depth-pcfr-v1:" + digest

    def reset(self, player: str, seed: int) -> None:
        if player not in ("white", "black") or type(seed) is not int:
            raise ValueError("reset needs a player and integer seed")
        self._player, self._seed = player, seed
        self._rng = Random(seed)
        self.last_result = None

    def solve(self, turn: AgentInput) -> SearchResult:
        if self._player != turn.observation.player:
            raise ValueError("reset for the acting player before solving")
        self.last_result = None
        started = perf_counter()
        deadline = (started + turn.time_budget_ms / 1000 if self.config.stop_on_time else None)
        tree = build_chess_tree(turn, self.evaluator, initial_fen=self.initial_fen,
                                depth=self.config.depth, max_nodes=self.config.max_nodes,
                                deadline=deadline)
        solver = PCFRPlus(tree.root, schedule=self.config.schedule)
        for _ in range(self.config.rounds):
            if deadline is not None and perf_counter() >= deadline:
                break
            solver.step()
        profile = solver.policy()
        policy = profile[0][tree.root_infoset]
        # The toy oracle validates exact key coverage for each continuation;
        # retain the SAME solved policy while removing unrelated root keys.
        values = tuple(behavioral_value(root, tuple(
            {key: profile[p][key] for key in sets}
            for p, sets in enumerate(information_sets(root)))) for root in tree.continuations)
        root_value = sum(h.weight * value for h, value in zip(turn.belief.hypotheses, values))
        # Draw from the raw policy. There is no paper-specific purification yet.
        draw, total, selected = self._rng.random(), 0.0, None
        for move, probability in policy.items():
            if probability > 0:
                selected = move
                total += probability
                if draw < total:
                    break
        elapsed = (perf_counter() - started) * 1000
        diagnostics = dict(search_nodes=float(tree.nodes), solver_rounds=float(solver.rounds),
                           elapsed_ms=elapsed, over_budget=float(elapsed > turn.time_budget_ms),
                           terminal_leaves=float(tree.terminal_leaves),
                           frontier_leaves=float(tree.frontier_leaves),
                           evaluator_calls=float(tree.evaluator_calls),
                           solver_root_value=float(root_value))
        diagnostics.update({"played_policy:" + m: p for m, p in policy.items()})
        decision = Decision(selected, policy, diagnostics)
        decision.validate_for(turn.observation)
        result = SearchResult(decision, values, root_value)
        self.last_result = result
        return result

    def act(self, turn: AgentInput) -> Decision:
        return self.solve(turn).decision

    def label(self, turn: AgentInput, game_id: str) -> TrainingRecord:
        if not game_id.strip():
            raise ValueError("label runs require a game_id")
        result = self.solve(turn)
        return TrainingRecord(turn, result.decision, result.root_value,
                              result.hypothesis_values, self._seed, self.name,
                              self.config_id, game_id)
