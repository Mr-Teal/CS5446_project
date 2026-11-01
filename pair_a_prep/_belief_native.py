"""Optional fast board transitions. Draw history and path retention stay in Python."""

import ctypes as C
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import sys

import chess

from .zs21.native_tracker import Packed, View, pack, view_argument, encode, decode


class Child(C.Structure):
    _fields_ = [("board", Packed), ("action", C.c_int), ("valid", C.c_int), ("zeroing", C.c_int)]


@lru_cache(maxsize=1)
def library():
    root = Path(__file__).parent
    directory = root / "_belief_build"
    if not (directory / "manifest.json").exists():
        return None
    from .build_belief_kernel import source_hashes
    record = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if record["source_sha256"] != source_hashes():
        return None
    from .build_belief_kernel import library_suffix
    path = directory / record.get("library", "belief_kernel" + library_suffix())
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != record["dll_sha256"]:
        return None
    dll = C.CDLL(str(path))
    dll.belief_children.argtypes = [C.POINTER(Packed), C.POINTER(View), C.c_int, C.c_int,
                                    C.POINTER(Child), C.c_int]
    dll.belief_children.restype = C.c_int
    return dll


def transitions(parent, own_move, expected):
    """None selects the Python oracle for unsupported/terminal cases."""
    dll = library()
    observed = expected.observed
    board = parent.board
    if (dll is None or observed.terminal or board.promoted or len(observed.legal_moves) > 256):
        return None
    if not hasattr(expected, "_native_buffers"):
        expected._native_buffers = (view_argument(observed), (Child * 256)())
    argument, output = expected._native_buffers
    count = dll.belief_children(C.byref(pack(board)), C.byref(argument), int(expected.viewer),
                               -1 if own_move is None else encode(own_move), output, 256)
    if count < 0:
        return None

    def generate():
        for row in sorted(output[:count], key=lambda r: decode(r.action)):
            half = 0 if row.zeroing else board.halfmove_clock + 1
            if not row.valid or half >= 100 or (observed.halfmove_clock is not None
                                              and half != observed.halfmove_clock):
                yield None
                continue
            p = row.board
            child = chess.Board(None)
            child.pawns, child.knights, child.bishops, child.rooks, child.queens, child.kings = p.pieces
            child.occupied = (child.pawns | child.knights | child.bishops | child.rooks |
                              child.queens | child.kings)
            child.occupied_co[chess.WHITE] = p.white
            child.occupied_co[chess.BLACK] = child.occupied ^ p.white
            child.turn = bool(p.turn)
            child.castling_rights = p.rights
            child.ep_square = None if p.ep == 64 else p.ep
            child.halfmove_clock = half
            child.fullmove_number = board.fullmove_number + (not board.turn)
            if row.action >> 12:
                child.promoted = chess.BB_SQUARES[(row.action >> 6) & 63]
            yield child, decode(row.action), False
    return generate()
