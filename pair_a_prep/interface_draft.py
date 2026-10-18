"""Pair A interface proposal; state/move prototype lives in rules_adapter.py.

These types are deliberately separate from fow_shared. See
docs/interface_draft.md for the update sequence and integration decisions.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Protocol, Tuple, TypeVar

from fow_shared.contracts import Belief, Observation


Player = Literal["white", "black"]
StateT = TypeVar("StateT")


@dataclass(frozen=True)
class Outcome:
    winner: Literal["white", "black", "draw"]
    reason: Literal["king_capture", "threefold_repetition", "fifty_move"]


# Compatibility name for early draft consumers; no second observation schema.
ObservationDraft = Observation


class RulesAdapterDraft(Protocol[StateT]):
    """Use the same rules for referee states and tracker candidate states.

    StateT is implementation-owned: it must retain board and relevant history.
    Agents must never receive the referee's StateT instance.
    """

    def initial_state(self, fen: Optional[str] = None) -> StateT:
        """Start at the standard position, or at a public agreed custom FEN.

        A custom FEN starts a fresh history; it cannot recover prior repetitions.
        """
        ...

    def current_player(self, state: StateT) -> Player:
        ...

    def legal_moves(self, state: StateT) -> Tuple[str, ...]:
        """Return unique UCI moves for the acting player; empty if terminal."""
        ...

    def apply_move(self, state: StateT, move: str) -> StateT:
        """Validate the move; return an independent successor with history.

        Leave the input and sibling states unchanged. Raise ValueError for an
        unavailable move, including any move after a terminal outcome.
        """
        ...

    def observe(self, state: StateT, player: Player) -> ObservationDraft:
        """Return a private snapshot after any ply, including opponent turns."""
        ...

    def terminal(self, state: StateT) -> Optional[Outcome]:
        """Return actual game outcomes only, not heuristic forced losses."""
        ...


class BeliefTrackerDraft(Protocol):
    def reset(
        self, player: Player, seed: int, initial_fen: Optional[str] = None
    ) -> None:
        """Clear candidates; initial_fen must be public to both players."""
        ...

    def update(
        self, observation: ObservationDraft, own_move: Optional[str] = None
    ) -> Belief:
        """Consume the initial observation, then exactly one update per ply.

        own_move is the action leading to THIS observation, supplied only after
        this tracker player's move. Unknown opponent actions are never supplied.
        Reject wrong players, skipped/duplicate plies and inconsistent actions.
        Raise ValueError if no candidate survives; do not invent a true state.
        """
        ...
