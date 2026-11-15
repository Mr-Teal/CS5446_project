"""Actions: 64 move types x 64 from-squares = 4,096, in the mover's own frame.

The move types follow AlphaZero's layout without under-promotions: 56 "queen moves" (8 directions
x 7 distances) and 8 knight moves. A pawn that reaches the last rank becomes a queen. Castling is
the king's two-square move, as in UCI. Black's squares are mirrored top to bottom (square ^ 56),
so both colours play "up the board" and the network learns each pattern once.

    action = move_type * 64 + from_square

which is the flattened order of a (64 move types, 8 ranks, 8 files) policy output.
"""
import chess

N_ACTIONS = 4096
_DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))  # (rank step, file step)
_KNIGHT = ((2, 1), (1, 2), (-1, 2), (-2, 1), (-2, -1), (-1, -2), (1, -2), (2, -1))

TYPE_OF = [[-1] * 64 for _ in range(64)]  # [from][to] -> move type, -1 if no piece moves that way
TO_OF = [[-1] * 64 for _ in range(64)]  # [from][move type] -> to, -1 if it leaves the board


def _fill_tables():
    for start in range(64):
        rank, file = divmod(start, 8)
        steps = [(d * 7 + dist - 1, dr * dist, df * dist)
                 for d, (dr, df) in enumerate(_DIRECTIONS) for dist in range(1, 8)]
        steps += [(56 + j, dr, df) for j, (dr, df) in enumerate(_KNIGHT)]
        for kind, dr, df in steps:
            r, f = rank + dr, file + df
            if 0 <= r < 8 and 0 <= f < 8:
                TYPE_OF[start][r * 8 + f] = kind
                TO_OF[start][kind] = r * 8 + f


_fill_tables()


def action_of(move: chess.Move, black: bool) -> int:
    """The action index of `move` for the side that plays it (`black`: that side is Black)."""
    start, end = move.from_square, move.to_square
    if black:
        start, end = start ^ 56, end ^ 56
    return TYPE_OF[start][end] * 64 + start


def move_of(action: int, board: chess.Board) -> chess.Move:
    """The move that `action` means for the side to move on `board`."""
    start, kind = action & 63, action >> 6
    end = TO_OF[start][kind]
    if board.turn == chess.BLACK:
        start, end = start ^ 56, end ^ 56
    promotion = None
    if board.piece_type_at(start) == chess.PAWN and chess.square_rank(end) in (0, 7):
        promotion = chess.QUEEN
    return chess.Move(start, end, promotion)
