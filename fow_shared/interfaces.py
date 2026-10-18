"""Swappable boundaries: both paper agents use the same inputs and rules adapter."""

from typing import Mapping, Optional, Protocol, Sequence

from .contracts import AgentInput, Belief, Decision, LeafValues, Observation


class Agent(Protocol):
    name: str

    def reset(self, player: str, seed: int) -> None:
        """Start a new game; clear any previous search tree and belief cache."""

    def act(self, turn: AgentInput) -> Decision:
        """Choose a legal move within turn.time_budget_ms."""


class BeliefTracker(Protocol):
    def reset(self, player: str, seed: int) -> None:
        ...

    def update(self, observation: Observation, own_move: Optional[str] = None) -> Belief:
        """Called after every ply for this player, including opponent turns.

        own_move is this player's move that led to this observation. It is given right after
        the player moves, and is None at the start and after an opponent's move, which stays
        unknown. HistoryEvent.own_move instead pins a move to the snapshot BEFORE it.
        Use only observations, own moves and prior internal state; never inspect the true board.
        """


class Referee(Protocol):
    """Only the match runner may hold a Referee; agents receive AgentInput."""

    def reset(self, seed: int) -> None:
        ...

    def current_player(self) -> str:
        ...

    def is_terminal(self) -> bool:
        ...

    def winner(self) -> str:
        """Return 'white', 'black', or 'draw' after a terminal state."""

    def observe(self, player: str) -> Observation:
        """Return this player's view after each ply, even if it is not their turn."""

    def apply(self, move: str) -> None:
        """Reject a move absent from the current player's observation.legal_moves."""


class LeafEvaluator(Protocol):
    """Scores positions at the edge of the search tree, where searching stops.

    The plug for the leaf: Stockfish at depth 1 (Obscuro's own leaf), Stockfish at depth 11,
    or Pair B's networks all answer the same three calls, so a match changes only which
    evaluator the agent is given. Scores are in [-1, 1] from the acting player's view, and
    positions decided by a rule are scored with fow_shared.values.rule_score. A first search
    may send one node or belief per call; the calls take batches so it can send more later.
    """

    name: str  # recorded as MatchConfig.engine_id, e.g. "stockfish-19-d1"

    def evaluate_children(self, fen: str) -> Mapping[str, float]:
        """Score of every legal move at this node, from the moving player's view.

        One call per expanded node, as Obscuro does with one MultiPV Stockfish call
        ([1] App. C.5). A finished game has no children: return {}.
        """

    def evaluate_boards(self, fens: Sequence[str], player: str) -> Sequence[float]:
        """One score per board, in the same order, from `player`'s view ("white" or "black")."""

    def evaluate_beliefs(self, turns: Sequence[AgentInput]) -> Sequence[LeafValues]:
        """One LeafValues per belief, in order, each valid for its own turn.

        Each answer keeps its own hypotheses in order, so a batch never mixes boards from
        different beliefs. Weights, observations and legal moves travel with each belief,
        as a belief-pooling network needs them; board-only evaluators may ignore them.
        """
