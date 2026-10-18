"""Board encoding for the networks (D1 spec §7).

Network 1 uses planes 0-18: everything a FEN carries, seen from the side to move. For Black to
move the board is mirrored (python-chess Board.mirror swaps colours and flips the ranks), so
"our" pieces always start on rows 0-1 and play up the board, as in AlphaZero.
"""
import chess
import numpy as np

N_PLANES = 19
_PIECES = [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]


def encode_board(board: chess.Board) -> np.ndarray:
    """(19, 8, 8) float32 planes; row = rank from the mover's side, column = file a-h."""
    b = board if board.turn == chess.WHITE else board.mirror()
    x = np.zeros((N_PLANES, 8, 8), dtype=np.float32)
    for i, piece in enumerate(_PIECES):
        for sq in b.pieces(piece, chess.WHITE):
            x[i, chess.square_rank(sq), chess.square_file(sq)] = 1
        for sq in b.pieces(piece, chess.BLACK):
            x[6 + i, chess.square_rank(sq), chess.square_file(sq)] = 1
    x[12] = 1  # "us" is the side to move for Network 1
    x[13] = b.has_kingside_castling_rights(chess.WHITE)
    x[14] = b.has_queenside_castling_rights(chess.WHITE)
    x[15] = b.has_kingside_castling_rights(chess.BLACK)
    x[16] = b.has_queenside_castling_rights(chess.BLACK)
    # Only if a capture is possible: Pair A's standard FENs name the square after every two-square
    # pawn move, while D2's (python-chess default) named it only then. Both now encode alike.
    if b.has_pseudo_legal_en_passant():
        x[17, chess.square_rank(b.ep_square), chess.square_file(b.ep_square)] = 1
    x[18] = b.halfmove_clock / 100
    return x


def stm_sign(board: chess.Board) -> float:
    """+1 if White is to move, else -1. Multiplying by it turns a White-view value into the
    mover's view, and back again."""
    return 1.0 if board.turn == chess.WHITE else -1.0
