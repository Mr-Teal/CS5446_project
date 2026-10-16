"""Shared score conversion and fog-of-war rule checks for leaf evaluation.

Scores are floats in [-1, 1] from the acting player's point of view, as everywhere in
fow_shared. Pair A's search and Pair B's labels import these, so both use one conversion.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

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


def rule_score(board: chess.Board) -> Optional[Tuple[str, float]]:
    """The fog-of-war rule that decides this board, as (rule name, score for the side to move).

    None means no rule applies and the leaf evaluator must score the board. Checked in this
    order. Boards with a rule must never reach Stockfish: Stockfish 19 crashes on a position
    where the side to move can capture the king. Threefold repetition is not checked: a FEN
    cannot show it, so the agent decides it from its own history.
    """
    mover = board.turn
    if board.king(chess.WHITE) is None or board.king(chess.BLACK) is None:
        return "king-missing", (1.0 if board.king(mover) is not None else -1.0)
    if board.was_into_check():
        return "king-capture", 1.0
    if board.is_checkmate():
        return "checkmate", -1.0
    if board.is_stalemate():
        return "stalemate", -1.0  # [1] App. A: a forced win for the stalemating player
    if board.halfmove_clock >= 100:
        return "fifty-move", 0.0
    return None
