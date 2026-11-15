"""The belief sampler (kernel/belief_sampler.cpp) for Python.

A sampler keeps, for one player, a capped sample of the positions that fit everything that player
has seen, and writes the 32-plane picture the network reads. It is given views, never the true
board; `step` takes the true board only so that the C++ side can compute both players' views from it.

The picture is the team's belief input (fow_shared.features.PLANE_NAMES) collapsed to one board the
way the team's fuzzy-board policy network reads it (pairb.belief_ablation, mode "marginals"), with
two differences in form only: every plane is stored as 0..255, and rows run from the player's own
side (row 0) outward, which is the order of the network's move output. Plane 23 (capture recency),
which the team's networks leave empty, marks the square where the opponent's last move took a piece.
"""
import ctypes as C
import sys
from pathlib import Path

import chess
import numpy as np

N_PLANES = 32
PLANE_BYTES = N_PLANES * 64
LIBRARY = (Path(__file__).resolve().parent.parent / "kernel" / "build"
           / {"darwin": "belief_sampler.dylib", "win32": "belief_sampler.dll"}.get(sys.platform, "belief_sampler.so"))


class Packed(C.Structure):
    """The team's Board: six piece bitboards, White's pieces, castling rooks, side to move, en passant."""
    _fields_ = [("pieces", C.c_uint64 * 6), ("white", C.c_uint64), ("rights", C.c_uint64),
                ("turn", C.c_uint64), ("ep", C.c_uint64)]


class View(C.Structure):
    """The team's View: what one player sees, the piece it just lost, and its legal moves."""
    _fields_ = [("contents", Packed), ("mask", C.c_uint64), ("captured", C.c_int), ("count", C.c_int),
                ("moves", C.c_int * 256)]


def _load():
    if not LIBRARY.exists():
        raise RuntimeError(f"{LIBRARY} is missing: run `python pair_b/experiments/ppo_belief/player/kernel/build.py`")
    dll = C.CDLL(str(LIBRARY))
    pointer, board, view = C.c_void_p, C.POINTER(Packed), C.POINTER(View)
    signatures = {
        "bs_create": ([], pointer), "bs_destroy": ([pointer], None),
        "bs_reset": ([pointer, board, C.c_int, C.c_uint64, C.c_int], None),
        "bs_update": ([pointer, view, C.c_int, C.c_int], C.c_int),
        "bs_step": ([pointer, pointer, board, C.c_int, C.c_int, C.c_int, C.c_int], None),
        "bs_planes": ([pointer, C.c_void_p], None),
        "bs_count": ([pointer], C.c_int),
        "bs_get": ([pointer, C.c_int, board, C.POINTER(C.c_double), C.POINTER(C.c_double)], C.c_int),
        "bs_log2_population": ([pointer], C.c_double),
        "bs_counters": ([pointer, C.POINTER(C.c_uint)], None),
        "bs_check": ([pointer], C.c_int),
        "bs_weight_of": ([pointer, board], C.c_double),
        "bs_view": ([pointer, view], None),
        "zs_observe": ([board, C.c_int, C.c_int, view], None),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = arguments, result
    return dll


dll = _load()
_board = Packed()          # one buffer for the calls below: they are made one at a time
_board_ref = C.byref(_board)


def _fill(board: chess.Board):
    pieces = _board.pieces
    pieces[0], pieces[1], pieces[2] = board.pawns, board.knights, board.bishops
    pieces[3], pieces[4], pieces[5] = board.rooks, board.queens, board.kings
    _board.white = board.occupied_co[chess.WHITE]
    _board.rights = board.clean_castling_rights()
    _board.turn = int(board.turn)
    _board.ep = 64 if board.ep_square is None else board.ep_square
    return _board_ref


def pack(board: chess.Board) -> Packed:
    """`board` as the team's Board, in a buffer of its own."""
    _fill(board)
    return Packed.from_buffer_copy(bytes(_board))


def encode_move(move: chess.Move) -> int:
    return move.from_square | move.to_square << 6 | (move.promotion or 0) << 12


def create() -> int:
    handle = dll.bs_create()
    if not handle:
        raise MemoryError("cannot create a belief sampler")
    return handle


def destroy(handle: int) -> None:
    dll.bs_destroy(handle)


def reset(handle: int, board: chess.Board, color: chess.Color, seed: int, cap: int) -> None:
    """Start a game at `board`, which both players know."""
    dll.bs_reset(handle, _fill(board), int(color), seed, cap)


def step(white: int, black: int, board: chess.Board, move: chess.Move, captured: int, mover: chess.Color,
         ply: int) -> None:
    """Self-play: `mover` played `move` and `board` is the true board after it. Each sampler is
    given its own player's view of that board, computed in C++ by the team's zs_observe."""
    dll.bs_step(white, black, _fill(board), encode_move(move), captured, int(mover), ply)


def planes_into(handle: int, address: int) -> None:
    """Write the picture for the sampler's player, PLANE_BYTES bytes, at a memory address."""
    dll.bs_planes(handle, address)


def planes(handle: int) -> np.ndarray:
    out = np.zeros((N_PLANES, 64), dtype=np.uint8)
    dll.bs_planes(handle, out.ctypes.data)
    return out


def view_of(observation, captured: int) -> View:
    """A fow_shared Observation as the team's View. `captured` is the square where the opponent's
    last move took one of this player's pieces, or -1."""
    view = View()
    view.contents.turn = int(observation.side_to_move == "white")
    mask = white = 0
    pieces = [0] * 6
    for name, symbol in observation.visible_pieces.items():
        bit = chess.BB_SQUARES[chess.parse_square(name)]
        mask |= bit
        if symbol:
            pieces[chess.PIECE_SYMBOLS.index(symbol.lower()) - 1] |= bit
            if symbol.isupper():
                white |= bit
    view.mask, view.contents.white = mask, white
    for kind in range(6):
        view.contents.pieces[kind] = pieces[kind]
    view.captured = captured
    moves = sorted(encode_move(chess.Move.from_uci(uci)) for uci in observation.legal_moves)
    if len(moves) > 256:
        raise ValueError("more than 256 legal moves")
    view.count = len(moves)
    for i, action in enumerate(moves):
        view.moves[i] = action
    return view


def update(handle: int, view: View, own_move, ply: int) -> int:
    """Match play: the player's next view, and its own move (a chess.Move) if it just moved.
    Returns 0 if successors of the sample fit, 1 if the sample was repaired, 2 if it is blank."""
    return dll.bs_update(handle, C.byref(view), -1 if own_move is None else encode_move(own_move), ply)


# ---- for tests and measurements only; the player never calls these ----

def count(handle: int) -> int:
    return dll.bs_count(handle)


def unpack(packed: Packed, halfmove: int = 0) -> chess.Board:
    board = chess.Board(None)
    (board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings) = packed.pieces
    board.occupied = board.pawns | board.knights | board.bishops | board.rooks | board.queens | board.kings
    board.occupied_co[chess.WHITE] = packed.white
    board.occupied_co[chess.BLACK] = board.occupied ^ packed.white
    board.turn = bool(packed.turn)
    board.castling_rights = packed.rights
    board.ep_square = None if packed.ep == 64 else packed.ep
    board.halfmove_clock = halfmove
    return board


def sample(handle: int) -> list:
    """[(board bytes, weight, mean halfmove clock)] of the kept positions."""
    rows, packed, weight, half = [], Packed(), C.c_double(), C.c_double()
    counters = (C.c_uint * 6)()
    dll.bs_counters(handle, counters)
    for i in range(counters[5]):
        dll.bs_get(handle, i, C.byref(packed), C.byref(weight), C.byref(half))
        rows.append((bytes(packed), weight.value, half.value))
    return rows


def board_of(blob: bytes, halfmove: int = 0) -> chess.Board:
    return unpack(Packed.from_buffer_copy(blob), halfmove)


def counters(handle: int) -> dict:
    out = (C.c_uint * 6)()
    dll.bs_counters(handle, out)
    return {"updates": out[0], "prunes": out[1], "repairs": out[2], "blanks": out[3], "blank": bool(out[4]),
            "boards": out[5]}


def check(handle: int) -> int:
    """How many kept positions do not fit the newest view (0 unless there is a fault)."""
    return dll.bs_check(handle)


def weight_of(handle: int, board: chess.Board) -> float:
    """The weight the sample gives to `board` (0 if it is not kept). A measurement, made with the true board."""
    return dll.bs_weight_of(handle, _fill(board))


def log2_population(handle: int) -> float:
    return dll.bs_log2_population(handle)


def observe(board: chess.Board, color: chess.Color, captured: int = -1) -> View:
    """The team's C++ view of `board` for one player."""
    view = View()
    dll.zs_observe(_fill(board), int(color), captured, C.byref(view))
    return view


def stored_view(handle: int) -> View:
    view = View()
    dll.bs_view(handle, C.byref(view))
    return view
