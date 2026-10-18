"""Shared score conversion and fog-of-war rule checks for leaf evaluation.

Scores are floats in [-1, 1] from the acting player's point of view, as everywhere in
fow_shared. Pair A's search and Pair B's labels import these, so both use one conversion.

Rules follow [1] App. A (profile paper_fow_v1_proposed in pair_a_prep): a player wins by
capturing the king; there is no check, so moving into check is legal, and castling into, out
of or through check is legal. Finished games (terminal_score) are kept apart from positions
decided one move ahead (forced_score), which are not terminal yet.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import chess
import chess.engine

# [5] App. D.1 (ZS21): tanh(x / 6 pawns); [1] App. C.5 (Obscuro) converts "in the same manner".
SCALE_CP = 600

_COLOUR = {"white": chess.WHITE, "black": chess.BLACK}


def cp_to_score(cp: int) -> float:
    return math.tanh(cp / SCALE_CP)


def engine_score(cp: Optional[int] = None, mate: Optional[int] = None) -> float:
    """An engine's centipawn or mate score (side to move's view, as UCI reports it) as a score.

    A forced mate counts as exactly +1 or -1; UCI "mate 0" means the side to move is mated.
    """
    if (cp is None) == (mate is None):
        raise ValueError("give exactly one of cp and mate")
    if mate is not None:
        return 1.0 if mate > 0 else -1.0
    return cp_to_score(cp)


def score_from_pov(pov: chess.engine.PovScore, player: str) -> float:
    """A python-chess engine score as a score from `player`'s view ("white" or "black")."""
    if player not in _COLOUR:
        raise ValueError("player must be 'white' or 'black'")
    score = pov.pov(_COLOUR[player])
    if score.is_mate():
        return 1.0 if score > chess.engine.Cp(0) else -1.0
    return cp_to_score(score.score())


def fog_legal_moves(board: chess.Board) -> List[chess.Move]:
    """Every move allowed under fog-of-war rules; none once the game is over.

    These are python-chess's pseudo-legal moves (which may leave the king attacked) plus
    castling into, out of or through check, which python-chess refuses. Castling still needs
    the right and empty squares between king and rook.
    """
    if terminal_score(board) is not None:
        return []
    moves = list(board.generate_pseudo_legal_moves())
    king = board.king(board.turn)
    rank = 0 if board.turn == chess.WHITE else 7
    if king == chess.square(4, rank):
        for has_right, rook_file, king_to_file, between in (
                (board.has_kingside_castling_rights(board.turn), 7, 6, (5, 6)),
                (board.has_queenside_castling_rights(board.turn), 0, 2, (1, 2, 3))):
            move = chess.Move(king, chess.square(king_to_file, rank))
            if (has_right and move not in moves and board.piece_at(chess.square(rook_file, rank)) is not None
                    and all(board.piece_at(chess.square(f, rank)) is None for f in between)):
                moves.append(move)
    return moves


def terminal_score(board: chess.Board) -> Optional[Tuple[str, float]]:
    """A finished game, as (rule name, score for the side to move), or None while it goes on.

    The game ends when a king has been captured, under the fifty-move rule, or by threefold
    repetition; draws need no claim ([1] App. A). Repetition is seen only when the board
    carries its move history: a FEN alone cannot show it.
    """
    mover = board.turn
    if board.king(chess.WHITE) is None or board.king(chess.BLACK) is None:
        return "king-captured", (1.0 if board.king(mover) is not None else -1.0)
    if board.halfmove_clock >= 100:
        return "fifty-move", 0.0
    if board.is_repetition(3):
        return "repetition", 0.0
    return None


_FORCED = {-1.0: "forced-loss", 0.0: "forced-draw", 1.0: "forced-win"}


def forced_score(board: chess.Board) -> Optional[Tuple[str, float]]:
    """A result decided one move ahead under fog rules, for the side to move, or None.

    The game is not over yet. "king-capture": the side to move can take the king (+1).
    Otherwise every fog-legal move is tried: a move that ends the game (a fifty-move or
    repetition draw) scores that result, and a move that leaves its own king capturable
    scores -1. If every move is one of these, the best of them is the result ("forced-loss"
    or "forced-draw"); orthodox checkmate and stalemate are usually forced losses, unless
    castling out of or through check escapes. Any other move leaves the result open: None.

    Moves are tried on the board itself and undone, so a repetition draw one move ahead is
    seen when the board carries its history. Stockfish 19 crashes on a king-capture
    position, so check this before any engine call.
    """
    if board.was_into_check():
        return "king-capture", 1.0
    best = None
    for move in fog_legal_moves(board):
        board.push(move)
        try:
            ended = terminal_score(board)
            if ended is not None:
                value = -ended[1] + 0.0  # the child's score is for the opponent
            elif board.was_into_check():
                value = -1.0  # the opponent takes the king next move
            else:
                return None  # a safe move: the rules decide nothing here
        finally:
            board.pop()
        best = value if best is None else max(best, value)
    if best is None:
        return None  # no fog-legal move at all (rare): left to the rules adapter
    return _FORCED[best], best


def rule_score(board: chess.Board) -> Optional[Tuple[str, float]]:
    """terminal_score, else forced_score: what the rules decide before any engine call."""
    return terminal_score(board) or forced_score(board)
