"""Swappable boundaries: both paper agents use the same inputs and rules adapter."""

from typing import Protocol

from .contracts import AgentInput, Belief, Decision, Observation


class Agent(Protocol):
    name: str

    def reset(self, player: str, seed: int) -> None:
        """Start a new game; clear any previous search tree and belief cache."""

    def act(self, turn: AgentInput) -> Decision:
        """Choose a legal move within turn.time_budget_ms."""


class BeliefTracker(Protocol):
    def reset(self, player: str, seed: int) -> None:
        ...

    def update(self, observation: Observation) -> Belief:
        """Called after every ply for this player, including opponent turns.

        Use only observations and prior internal state; never inspect the true board.
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
