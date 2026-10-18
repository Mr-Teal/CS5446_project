"""State and move prototype; private observation generation is not implemented."""

from dataclasses import dataclass, field
from typing import Optional, Tuple

import chess

from fow_shared.values import fog_legal_moves, terminal_score
from .interface_draft import Outcome, Player


@dataclass(frozen=True, eq=False)
class RuleState:
    """Internal full state, for the runner or a tracker candidate only.

    Keep _board private by convention. board_copy() is the supported access path
    and preserves history without exposing the stored mutable board.
    """

    _board: chess.Board = field(repr=False)
    ply: int = 0
    captured_player: Optional[Player] = None
    captured_square: Optional[str] = None

    def __post_init__(self) -> None:
        if self.ply < 0:
            raise ValueError("negative ply")
        object.__setattr__(self, "_board", self._board.copy(stack=True))

    @property
    def fen(self) -> str:
        """Position snapshot only; use board_copy() when history is required."""
        return self._board.fen(en_passant="fen")

    def board_copy(self) -> chess.Board:
        """Return an independent board with its complete retained move stack."""
        return self._board.copy(stack=True)


class RulesAdapter:
    """Implements the state/move subset of RulesAdapterDraft, not observe()."""

    def initial_state(self, fen: Optional[str] = None) -> RuleState:
        # Do not use Board.is_valid(): ordinary check restrictions reject FoW states.
        board = chess.Board(chess.STARTING_FEN if fen is None else fen)
        if any(len(board.pieces(chess.KING, color)) > 1 for color in chess.COLORS):
            raise ValueError("multiple kings of one color")
        if not board.kings:
            raise ValueError("both kings are missing")
        return RuleState(board)

    def current_player(self, state: RuleState) -> Player:
        return "white" if state._board.turn == chess.WHITE else "black"

    def legal_moves(self, state: RuleState) -> Tuple[str, ...]:
        return tuple(sorted(move.uci() for move in fog_legal_moves(state._board)))

    def terminal(self, state: RuleState) -> Optional[Outcome]:
        result = terminal_score(state._board)
        if result is None:
            return None
        reason, score = result
        if score == 0:
            winner = "draw"
        elif score > 0:
            winner = self.current_player(state)
        else:
            winner = "black" if self.current_player(state) == "white" else "white"
        reasons = {"king-captured": "king_capture", "fifty-move": "fifty_move",
                   "repetition": "threefold_repetition"}
        return Outcome(winner=winner, reason=reasons[reason])

    def apply_move(self, state: RuleState, move: str) -> RuleState:
        if move not in self.legal_moves(state):
            raise ValueError("unavailable UCI move: {!r}".format(move))
        action = chess.Move.from_uci(move)
        board = state.board_copy()
        captured_square = action.to_square
        if board.is_en_passant(action):
            captured_square += -8 if board.turn == chess.WHITE else 8
        piece = board.piece_at(captured_square)
        # Castling is not a capture. Validated FoW actions never capture own pieces.
        captured = piece is not None and piece.color != board.turn
        captured_player = ("white" if piece.color else "black") if captured else None
        board.push(action)
        return RuleState(
            board, ply=state.ply + 1, captured_player=captured_player,
            captured_square=chess.square_name(captured_square) if captured else None,
        )
