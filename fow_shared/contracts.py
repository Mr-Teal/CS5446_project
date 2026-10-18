"""Versioned data crossing the rules, belief, agent, training, and evaluation boundaries.

No field in Observation or AgentInput contains the referee's true hidden board.
Squares use algebraic names, pieces use FEN letters, and moves use UCI strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping, Optional, Tuple


SCHEMA_VERSION = 1
FILES = "abcdefgh"
RANKS = "12345678"
PIECES = set("PNBRQKpnbrqk")


def _square(value: str) -> bool:
    return isinstance(value, str) and len(value) == 2 and value[0] in FILES and value[1] in RANKS


def _move(value: str) -> bool:
    return (isinstance(value, str) and len(value) in (4, 5)
            and _square(value[:2]) and _square(value[2:4])
            and (len(value) == 4 or value[4] in "qrbn"))


def _colour(value: str) -> bool:
    return value in ("white", "black")


@dataclass(frozen=True)
class Observation:
    player: str
    ply: int
    visible_squares: Tuple[str, ...]
    # Every visible square is present; None means visibly empty.
    visible_pieces: Mapping[str, Optional[str]]
    legal_moves: Tuple[str, ...]
    # None when the rules do not show the clock to the player (paper_fow_v1_proposed lists it
    # as hidden); the referee and each hypothesis FEN keep their own counters.
    halfmove_clock: Optional[int] = None
    # A captured own piece is observable. Do not encode an unseen opponent move here.
    captured_own_piece_at: Optional[str] = None
    terminal: bool = False
    outcome: Optional[float] = None  # From this player's perspective: -1, 0, +1.
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or not _colour(self.player):
            raise ValueError("unsupported observation version or player")
        if self.ply < 0 or (self.halfmove_clock is not None and self.halfmove_clock < 0):
            raise ValueError("negative move counter")
        if len(set(self.visible_squares)) != len(self.visible_squares) or not all(map(_square, self.visible_squares)):
            raise ValueError("visible_squares must be unique board squares")
        if set(self.visible_pieces) != set(self.visible_squares):
            raise ValueError("visible_pieces must include exactly the visible squares")
        if any(p is not None and p not in PIECES for p in self.visible_pieces.values()):
            raise ValueError("invalid piece symbol")
        if len(set(self.legal_moves)) != len(self.legal_moves) or not all(map(_move, self.legal_moves)):
            raise ValueError("legal_moves must be unique UCI moves")
        if self.captured_own_piece_at is not None and not _square(self.captured_own_piece_at):
            raise ValueError("invalid captured piece square")
        if self.terminal != (self.outcome is not None):
            raise ValueError("terminal and outcome must be supplied together")
        if self.outcome is not None and self.outcome not in (-1.0, 0.0, 1.0):
            raise ValueError("outcome must be -1, 0, or 1")
        if self.terminal and self.legal_moves:
            raise ValueError("terminal observation cannot have legal moves")


@dataclass(frozen=True)
class Hypothesis:
    # Complete FEN, including side to move, castling rights and en-passant square.
    fen: str
    weight: float
    # Distinguishes candidate histories that reach the same FEN. Assigned by the
    # belief tracker, never copied from a referee's private move log.
    history_id: str = ""
    # Optional hypothetical move path consistent with this player's observations.
    candidate_moves: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fen or len(self.fen.split()) != 6:
            raise ValueError("hypothesis needs a six-field FEN")
        if not isfinite(self.weight) or self.weight <= 0:
            raise ValueError("hypothesis weight must be positive and finite")
        if not all(map(_move, self.candidate_moves)):
            raise ValueError("candidate_moves must be UCI moves")


@dataclass(frozen=True)
class Belief:
    player: str
    ply: int
    hypotheses: Tuple[Hypothesis, ...]
    # Number of consistent states before sampling; None if unknown.
    population_size: Optional[int] = None
    # "uniform" or a documented model identifier. Weights are conditional on this sample.
    weighting: str = "uniform"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or not _colour(self.player) or self.ply < 0:
            raise ValueError("unsupported belief version, player, or ply")
        if not self.hypotheses or len({(h.fen, h.history_id) for h in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("belief needs distinct position/history hypotheses")
        if abs(sum(h.weight for h in self.hypotheses) - 1.0) > 1e-6:
            raise ValueError("sample weights must sum to one")
        if self.population_size is not None and self.population_size < len(self.hypotheses):
            raise ValueError("population_size cannot be smaller than sample")
        if not self.weighting:
            raise ValueError("weighting method must be named")


@dataclass(frozen=True)
class HistoryEvent:
    """One past observation of this player, and their action if they moved next.

    Events are snapshots after each ply, including plies when the opponent acts.
    They contain no referee board or unseen opponent action.
    """

    observation: Observation
    own_move: Optional[str] = None

    def __post_init__(self) -> None:
        if self.own_move is not None and self.own_move not in self.observation.legal_moves:
            raise ValueError("history contains an unavailable own move")


@dataclass(frozen=True)
class AgentInput:
    observation: Observation
    belief: Belief
    time_budget_ms: int
    history: Tuple[HistoryEvent, ...] = ()

    def __post_init__(self) -> None:
        if (self.observation.player, self.observation.ply) != (self.belief.player, self.belief.ply):
            raise ValueError("observation and belief must refer to the same turn")
        if self.time_budget_ms <= 0:
            raise ValueError("time budget must be positive")
        if any(event.observation.player != self.observation.player for event in self.history):
            raise ValueError("history contains another player's observation")
        plies = [event.observation.ply for event in self.history]
        if plies != sorted(set(plies)) or (plies and plies[-1] >= self.observation.ply):
            raise ValueError("history must contain distinct earlier plies in order")


@dataclass(frozen=True)
class Decision:
    move: str
    # Raw solver policy, before any Obscuro-style purification.
    root_policy: Mapping[str, float]
    diagnostics: Mapping[str, float] = field(default_factory=dict)

    def validate_for(self, observation: Observation) -> None:
        if observation.terminal or self.move not in observation.legal_moves:
            raise ValueError("agent selected an unavailable move")
        if set(self.root_policy) != set(observation.legal_moves):
            raise ValueError("root policy must cover exactly the legal actions")
        if any(not isfinite(v) or v < 0 for v in self.root_policy.values()):
            raise ValueError("invalid root-policy probability")
        if abs(sum(self.root_policy.values()) - 1.0) > 1e-6:
            raise ValueError("root-policy probabilities must sum to one")
        if any(not isfinite(v) for v in self.diagnostics.values()):
            raise ValueError("diagnostics must be finite numbers")


@dataclass(frozen=True)
class TrainingRecord:
    """Teacher output. Values are from the acting player's perspective in [-1, 1]."""

    agent_input: AgentInput
    decision: Decision
    root_value: float
    hypothesis_values: Tuple[float, ...]
    seed: int
    agent_name: str
    config_id: str
    # Identifies the game this decision came from, so training, validation and test
    # data can be split by whole game. Set it in label runs; "" in older files.
    game_id: str = ""

    def __post_init__(self) -> None:
        self.decision.validate_for(self.agent_input.observation)
        if len(self.hypothesis_values) != len(self.agent_input.belief.hypotheses):
            raise ValueError("one value is required per hypothesis")
        if any(not isfinite(v) or not -1 <= v <= 1 for v in (self.root_value, *self.hypothesis_values)):
            raise ValueError("values must be finite and in [-1, 1]")
        if not self.agent_name or not self.config_id:
            raise ValueError("agent_name and config_id are required")


@dataclass(frozen=True)
class LeafValues:
    """A leaf evaluator's answer for one belief (LeafEvaluator.evaluate_beliefs).

    One score per hypothesis, in the belief's order, from the acting player's view in
    [-1, 1]. An evaluator with a policy head may add move probabilities over the
    observation's legal moves.
    """

    hypothesis_values: Tuple[float, ...]
    policy: Optional[Mapping[str, float]] = None

    def validate_for(self, turn: AgentInput) -> None:
        if len(self.hypothesis_values) != len(turn.belief.hypotheses):
            raise ValueError("one value is required per hypothesis")
        if any(not isfinite(v) or not -1 <= v <= 1 for v in self.hypothesis_values):
            raise ValueError("values must be finite and in [-1, 1]")
        if self.policy is None:
            return
        if set(self.policy) != set(turn.observation.legal_moves):
            raise ValueError("policy must cover exactly the legal moves")
        if any(not isfinite(p) or p < 0 for p in self.policy.values()):
            raise ValueError("invalid policy probability")
        if abs(sum(self.policy.values()) - 1.0) > 1e-6:
            raise ValueError("policy probabilities must sum to one")
