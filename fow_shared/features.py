"""Candidate v2 belief encoder: N x 32 x 8 x 8 float32.

Planes 0..25 are the proposal's numbered list: 17 hypothesis-specific and 9
shared (the slide's phrase "17 + 8" is a counting error). Planes 26..31 add the
rule state a FEN carries and the rules depend on: castling rights, the en
passant square and the halfmove clock, each read from the hypothesis itself.
Keep this versioned; Pair A and Pair B should jointly sign off before
generating a label dataset.
"""

from __future__ import annotations

import math
from typing import Callable, Mapping, Optional, Sequence, Tuple

import chess
import numpy as np

from .contracts import AgentInput, _square


PLANE_NAMES = (
    "own_pawn", "own_knight", "own_bishop", "own_rook", "own_queen", "own_king",
    "enemy_pawn", "enemy_knight", "enemy_bishop", "enemy_rook", "enemy_queen", "enemy_king",
    "our_visible_squares", "enemy_pieces_actually_visible",
    "enemy_pawn_probability", "enemy_knight_probability", "enemy_bishop_probability",
    "enemy_rook_probability", "enemy_queen_probability", "enemy_king_probability",
    "log2_population_over_15", "their_visible_squares", "our_pieces_visible_to_them",
    "capture_recency", "ply_over_200", "search_depth_over_4",
    "own_kingside_castling", "own_queenside_castling",
    "enemy_kingside_castling", "enemy_queenside_castling",
    "en_passant_square", "halfmove_clock_over_100",
)


def _index(square: str, player: str) -> Tuple[int, int]:
    """Own home rank is always row 7. A Black position is mirrored top to bottom,
    with files unchanged, so a position and its colour-swapped twin encode
    identically and the network learns each pattern once for both colours."""
    sq = chess.parse_square(square)
    file_index = chess.square_file(sq)
    rank_index = chess.square_rank(sq)
    return ((7 - rank_index, file_index) if player == "white"
            else (rank_index, file_index))


def encode_belief(
    turn: AgentInput,
    opponent_visible_squares: Callable[[chess.Board], Sequence[str]],
    *,
    search_depth: int = 0,
    capture_recency: Optional[Mapping[str, float]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return planes and normalized hypothesis weights.

    `opponent_visible_squares` must implement the agreed rules. It is called on
    each *hypothesis*, never on the referee's true board. `capture_recency`
    contains public/history-derived values in [0,1], not hidden information.
    """
    capture_recency = capture_recency or {}
    if search_depth < 0:
        raise ValueError("search depth must be nonnegative")
    if any(not _square(sq) or not math.isfinite(v) or not 0 <= v <= 1
           for sq, v in capture_recency.items()):
        raise ValueError("invalid capture recency")
    obs, belief = turn.observation, turn.belief
    player_white = obs.player == "white"
    boards = [chess.Board(h.fen) for h in belief.hypotheses]
    weights = np.asarray([h.weight for h in belief.hypotheses], dtype=np.float32)
    planes = np.zeros((len(boards), len(PLANE_NAMES), 8, 8), dtype=np.float32)
    own = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING)
    for i, board in enumerate(boards):
        if board.turn != player_white:
            raise ValueError("hypothesis has wrong side to move")
        for sq, piece in board.piece_map().items():
            name = chess.square_name(sq)
            row, col = _index(name, obs.player)
            offset = 0 if piece.color == player_white else 6
            planes[i, offset + own.index(piece.piece_type), row, col] = 1
            if piece.color != player_white:
                planes[:, 14 + own.index(piece.piece_type), row, col] += weights[i]
        for square in opponent_visible_squares(board):
            if not _square(square):
                raise ValueError("opponent visibility callback returned invalid square")
            row, col = _index(square, obs.player)
            planes[i, 21, row, col] = 1
            piece = board.piece_at(chess.parse_square(square))
            if piece is not None and piece.color == player_white:
                planes[i, 22, row, col] = 1
    for square in obs.visible_squares:
        row, col = _index(square, obs.player)
        planes[:, 12, row, col] = 1
        piece = obs.visible_pieces[square]
        if piece is not None and (piece.isupper() != player_white):
            planes[:, 13, row, col] = 1
        for i, board in enumerate(boards):
            actual = board.piece_at(chess.parse_square(square))
            if (actual.symbol() if actual else None) != piece:
                raise ValueError("hypothesis contradicts observed piece")
    for square, value in capture_recency.items():
        row, col = _index(square, obs.player)
        planes[:, 23, row, col] = value
    own_colour = chess.WHITE if player_white else chess.BLACK
    for i, board in enumerate(boards):
        planes[i, 26] = board.has_kingside_castling_rights(own_colour)
        planes[i, 27] = board.has_queenside_castling_rights(own_colour)
        planes[i, 28] = board.has_kingside_castling_rights(not own_colour)
        planes[i, 29] = board.has_queenside_castling_rights(not own_colour)
        if board.ep_square is not None:
            row, col = _index(chess.square_name(board.ep_square), obs.player)
            planes[i, 30, row, col] = 1
        # Each hypothesis's own clock: under the paper's rules the player may not know the true one.
        planes[i, 31] = min(board.halfmove_clock / 100, 1.0)
    population = belief.population_size or len(boards)
    planes[:, 20] = min(math.log2(population) / 15, 1.0)
    planes[:, 24] = min(obs.ply / 200, 1.0)
    planes[:, 25] = min(search_depth / 4, 1.0)
    return planes, weights
