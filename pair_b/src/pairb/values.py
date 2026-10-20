"""Score conversion and fog-of-war rule checks in White's view, for Pair B's own data.

Both come from the team's shared module, fow_shared.values, so Pair A's search and Pair B's
labels use one conversion and one set of rules. This file only turns their side-to-move
scores into White's view, which the D2 files use.
"""
from __future__ import annotations

import chess
import chess.engine

from fow_shared.values import cp_to_score, rule_score


def cp_to_value(cp: int) -> float:
    return cp_to_score(cp)


def score_to_value(score: chess.engine.Score) -> float:
    """A White-view score as a value; a forced mate counts as exactly +1 or -1."""
    if score.is_mate():
        return 1.0 if score > chess.engine.Cp(0) else -1.0
    return cp_to_value(score.score())


def pov_to_value(pov: chess.engine.PovScore) -> float:
    """Stockfish reports from the side to move; D2 values are from White's view."""
    return score_to_value(pov.white())


def rule_value(board: chess.Board) -> tuple[str, float] | None:
    """The fog-of-war rule that decides this board, as (rule name, value from White's view).

    None means no rule applies. See fow_shared.values.rule_score: finished games
    ("king-captured", "fifty-move", "repetition") and positions decided one move ahead
    ("king-capture", "forced-loss", "forced-draw"). Boards with a rule must never reach Stockfish.
    """
    rule = rule_score(board)
    if rule is None:
        return None
    to_white = 1.0 if board.turn == chess.WHITE else -1.0
    return rule[0], to_white * rule[1] + 0.0  # + 0.0 turns -0.0 into 0.0
