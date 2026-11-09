"""Optional native data path (leaf_kernel.cpp) of pairb's BeliefNetworkEvaluator.evaluate_children.

children(fen) gives, for every fog-legal move of the parent in fow_shared.values.fog_legal_moves order, the UCI
move, whether the fog-of-war rules decide the child and its White-view rule value (pairb.values.rule_value), and
the 32 x 8 x 8 float32 planes that fow_shared.features.encode_belief makes of the one-board belief the evaluator
builds for an undecided child. The network pass stays in the evaluator.

Build with `python -m pair_a_prep.build_leaf_kernel`; library() returns None when the build is missing or stale.
"""

import ctypes as C
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

import chess
import numpy as np

from .zs21.native_tracker import Packed, pack

_PACKED = C.sizeof(Packed)
_MAX = 256  # more than any position's fog-legal moves (at most 218 + 2 castles)
_TEXT = 1 << 16
_FENS = _MAX * 100


@lru_cache(maxsize=1)
def library():
    directory = Path(__file__).parent / "_leaf_build"
    if not (directory / "manifest.json").exists():
        return None
    from .build_leaf_kernel import source_hashes
    record = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if record["source_sha256"] != source_hashes():
        return None
    path = directory / record["library"]
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != record["dll_sha256"]:
        return None
    dll = C.CDLL(str(path))
    dll.lk_children.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p,
                                C.c_void_p, C.POINTER(C.c_int), C.c_char_p, C.c_int, C.c_char_p, C.c_char_p, C.c_int]
    dll.lk_children.restype = C.c_int
    dll.actions = np.zeros(_MAX, dtype=np.int32)
    dll.white = np.zeros(_MAX, dtype=np.float64)
    dll.rule = np.zeros(_MAX, dtype=np.uint8)
    dll.names = C.create_string_buffer(_TEXT)
    return dll


class Children:
    """One parent's children: moves (UCI, in evaluate_children's order), white (rule values, White's view; 0 where
    no rule decides), rule (bool), planes (float32, one 32 x 8 x 8 block per undecided child, or per child with
    all_planes), and with details the packed child boards (bytes) and their standard FENs."""
    __slots__ = ("moves", "white", "rule", "planes", "boards", "fens")


def children(fen: str, all_planes: bool = False, details: bool = False) -> Children:
    dll = library()
    board = chess.Board(fen)
    planes = np.empty((_MAX, 32, 8, 8), dtype=np.float32)
    encoded = C.c_int()
    boards = C.create_string_buffer(_PACKED * _MAX) if details else None
    fens = C.create_string_buffer(_FENS) if details else None
    n = dll.lk_children(bytes(pack(board)), board.halfmove_clock, board.fullmove_number, int(all_planes),
                        dll.actions.ctypes.data, dll.white.ctypes.data, dll.rule.ctypes.data, planes.ctypes.data,
                        C.byref(encoded), dll.names, _TEXT, boards, fens, _FENS)
    if n < 0:
        raise RuntimeError("native leaf kernel failed")
    result = Children()
    result.moves = dll.names.value.decode("ascii").split() if n else []
    result.white = dll.white[:n].tolist()
    result.rule = dll.rule[:n].astype(bool)
    result.planes = planes[:encoded.value]
    result.boards = [boards.raw[i * _PACKED:(i + 1) * _PACKED] for i in range(n)] if details else None
    result.fens = (fens.value.decode("ascii").split("\n") if n else []) if details else None
    return result
