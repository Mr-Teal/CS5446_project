"""Pair B's stand-in for Pair A's observation generator, for practice beliefs (D6).

It follows the visibility of pair_a_prep's rules fixtures (profile paper_fow_v1_proposed): a
player sees the squares of their own pieces and every square a fog-legal move of theirs goes to,
and an en passant capture also reveals the pawn it takes. So a blocked pawn does not see its
blocker, and a pawn sees a diagonal only when there is something to take there. Replace it with
Pair A's rules adapter once `observe()` exists there; tests/test_observe.py checks the fixtures.
"""
import chess

from fow_shared.contracts import Observation
from fow_shared.values import fog_legal_moves, terminal_score


def visible_squares(board: chess.Board, color: chess.Color) -> frozenset[str]:
    """The squares `color` sees on `board`, whichever side is to move."""
    view = board.copy(stack=False)
    if view.turn != color:
        view.turn = color
        view.ep_square = None  # an en passant right belongs to the side to move only
    view.halfmove_clock = 0  # what a player sees does not depend on the fifty-move counter
    seen = set(chess.SquareSet(view.occupied_co[color]))  # own pieces' squares
    for move in fog_legal_moves(view):
        seen.add(move.to_square)
        if view.is_en_passant(move):
            seen.add(move.to_square + (-8 if color == chess.WHITE else 8))
    return frozenset(chess.square_name(sq) for sq in seen)


def observe(board: chess.Board, player: str, ply: int = 0) -> Observation:
    """What `player` ("white" or "black") sees of the true `board`.

    Legal moves are listed only on the player's own turn. The halfmove clock stays unknown, as
    the fixtures hide it, and captured_own_piece_at is not tracked (no move history here).
    """
    color = chess.WHITE if player == "white" else chess.BLACK
    squares = tuple(sorted(visible_squares(board, color)))
    pieces = {sq: (p.symbol() if (p := board.piece_at(chess.parse_square(sq))) else None) for sq in squares}
    to_move = "white" if board.turn == chess.WHITE else "black"
    ended = terminal_score(board)
    moves = ()
    if ended is None and to_move == player:
        moves = tuple(sorted(m.uci() for m in fog_legal_moves(board)))
    outcome = None
    if ended is not None:
        outcome = (ended[1] if to_move == player else -ended[1]) + 0.0
    return Observation(player=player, side_to_move=to_move, ply=ply, visible_squares=squares,
                       visible_pieces=pieces, legal_moves=moves, terminal=ended is not None, outcome=outcome)
