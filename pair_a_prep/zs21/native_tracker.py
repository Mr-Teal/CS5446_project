"""C ABI bridge: full-I inference with position-only merging, never particles."""

import ctypes as C
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import chess

from ..rules_adapter import RuleState
from .model import PositionTracker, Candidate, BudgetError, extend_memory, SearchRules, view_signature
from fow_shared.contracts import Observation
from .rule_profile import RULES_ID


class Packed(C.Structure):
    _fields_ = [("pieces", C.c_uint64*6), ("white", C.c_uint64), ("rights", C.c_uint64),
                ("turn", C.c_uint64), ("ep", C.c_uint64)]


class View(C.Structure):
    _fields_ = [("contents", Packed), ("mask", C.c_uint64), ("captured", C.c_int),
                ("count", C.c_int), ("moves", C.c_int*256)]


def pack(board):
    return Packed((C.c_uint64*6)(board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings),
                  board.occupied_co[chess.WHITE], board.clean_castling_rights(), int(board.turn),
                  64 if board.ep_square is None else board.ep_square)


def unpack(value):
    board = chess.Board(None)
    for kind, pieces in enumerate(value.pieces, 1):
        for square in chess.scan_forward(pieces):
            board.set_piece_at(square, chess.Piece(kind, bool(value.white & chess.BB_SQUARES[square])))
    board.turn = bool(value.turn)
    board.castling_rights = value.rights
    board.ep_square = None if value.ep == 64 else value.ep
    return board


@lru_cache(maxsize=8192)
def encode(move):
    action = chess.Move.from_uci(move)
    return action.from_square | action.to_square << 6 | (action.promotion or 0) << 12


@lru_cache(maxsize=8192)
def decode(action):
    return chess.Move(action & 63, (action >> 6) & 63, action >> 12 or None).uci()


def view_argument(view):
    result = View()
    result.contents.turn = int(view.side_to_move == "white")
    for name, symbol in view.visible_pieces.items():
        bit = chess.BB_SQUARES[chess.parse_square(name)]
        result.mask |= bit
        if symbol:
            piece = chess.Piece.from_symbol(symbol)
            result.contents.pieces[piece.piece_type-1] |= bit
            if piece.color:
                result.contents.white |= bit
    result.captured = -1 if view.captured_own_piece_at is None else chess.parse_square(view.captured_own_piece_at)
    result.count = len(view.legal_moves)
    if result.count > 256:
        raise ValueError("native view action capacity exceeded")
    for i, action in enumerate(sorted(map(encode, view.legal_moves))):
        result.moves[i] = action
    return result


def library():
    dll = C.CDLL(str(Path(__file__).with_name("native") / "inference.dll"))
    try:
        dll.zs_rules_id.argtypes, dll.zs_rules_id.restype = [], C.c_char_p
        rules_id = dll.zs_rules_id().decode("ascii")
    except AttributeError as exc:
        raise RuntimeError("outdated native inference DLL; rebuild with scripts/build_inference.py") from exc
    if rules_id != RULES_ID:
        raise RuntimeError("native inference rule version does not match Python")
    pointer, U, I = C.c_void_p, C.c_uint64, C.c_int
    signatures = {
        "zs_create": ([C.POINTER(Packed), I, U], pointer),
        "zs_destroy": ([pointer], None), "zs_error": ([pointer], C.c_char_p),
        "zs_count": ([pointer], U), "zs_attempts": ([pointer], U), "zs_accepted": ([pointer], U),
        "zs_validate": ([pointer, C.POINTER(View)], I),
        "zs_update": ([pointer, C.POINTER(View), I, C.c_double], I),
        "zs_index": ([pointer, C.POINTER(Packed)], U),
        "zs_get": ([pointer, U, C.POINTER(Packed), C.POINTER(I), I], I),
        "zs_moves": ([C.POINTER(Packed), C.POINTER(I)], I),
        "zs_has_moves": ([C.POINTER(Packed)], I),
        "zs_visible": ([C.POINTER(Packed), I], U),
        "zs_observe": ([C.POINTER(Packed), I, I, C.POINTER(View)], None),
        "zs_play": ([C.POINTER(Packed), I, C.POINTER(Packed), C.POINTER(I)], None),
        "zs_fen": ([C.POINTER(Packed), I, I, C.POINTER(C.c_char), I], I),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = arguments, result
    return dll


class FastRules(SearchRules):
    """Reuse Python transitions; intern equivalent privately visible frames."""
    def __init__(self, dll):
        self.dll = dll
        self.view_cache = {}

    def legal_moves(self, state):
        value, actions = pack(state._board), (C.c_int*512)()
        count = self.dll.zs_moves(C.byref(value), actions)
        return tuple(sorted(decode(a) for a in actions[:count]))

    def _has_moves(self, state):
        value = pack(state._board)
        return bool(self.dll.zs_has_moves(C.byref(value)))

    def _signature(self, state, player):
        value, frame = pack(state._board), View()
        captured = state.captured_square if state.captured_player == player else None
        self.dll.zs_observe(C.byref(value), int(player == "white"),
                            -1 if captured is None else chess.parse_square(captured), C.byref(frame))
        if frame.count < 0:
            raise ValueError("native view action capacity exceeded")
        key = (C.string_at(C.addressof(frame), View.moves.offset + frame.count * C.sizeof(C.c_int)), state.ply, player)
        if key not in self.view_cache:
            contents = {}
            for square in chess.scan_forward(frame.mask):
                symbol = None
                for kind, bits in enumerate(frame.contents.pieces, 1):
                    if bits & chess.BB_SQUARES[square]:
                        symbol = ("PNBRQK" if frame.contents.white & chess.BB_SQUARES[square] else "pnbrqk")[kind-1]
                        break
                contents[chess.square_name(square)] = symbol
            signature = ("white" if frame.contents.turn else "black", tuple(sorted(contents.items())),
                         tuple(sorted(decode(a) for a in frame.moves[:frame.count])), captured, False, None, None)
            self.view_cache[key] = [signature, None]
        return self.view_cache[key]

    def observe_signature(self, state, player):
        if self.terminal(state) is not None:
            return view_signature(super().observe(state, player))
        return self._signature(state, player)[0]

    def observe(self, state, player):
        if self.terminal(state) is not None:
            return super().observe(state, player)
        entry = self._signature(state, player)
        if entry[1] is None:
            signature = entry[0]
            contents = dict(signature[1])
            view = Observation(player, signature[0], state.ply, tuple(contents), contents,
                               signature[2], captured_own_piece_at=signature[3])
            object.__setattr__(view, "_zs21_signature", signature)
            entry[1] = view
        return entry[1]


class Candidates:
    def __init__(self, tracker):
        self.tracker = tracker

    def __len__(self):
        return int(self.tracker.dll.zs_count(self.tracker.handle))

    def __getitem__(self, index):
        if not 0 <= index < len(self):
            raise IndexError(index)
        tracker = self.tracker
        value = Packed()
        size = 0 if tracker.previous is None else tracker.previous.ply
        path = (C.c_int * max(size, 1))()
        count = tracker.dll.zs_get(tracker.handle, index, C.byref(value), path, size)
        if count != size:
            raise RuntimeError("native candidate history length mismatch")
        captured = tracker.previous.captured_own_piece_at if tracker.previous else None
        state = RuleState(unpack(value), size, tracker.player if captured else None, captured)
        return Candidate(state, tuple(decode(a) for a in path[:count]))


class NativeTracker(PositionTracker):
    def __init__(self, player, seed, initial_fen=None):
        super().__init__(player, seed, initial_fen)
        initial = pack(self.candidates[0].state._board)
        self.dll = library()
        self.handle = self.dll.zs_create(C.byref(initial), int(player == "white"), seed)
        if not self.handle:
            raise MemoryError("cannot create full-I tracker")
        self.candidates = Candidates(self)

    def close(self):
        if self.handle:
            self.dll.zs_destroy(self.handle)
            self.handle = None

    def __del__(self):
        if getattr(self, "handle", None):
            self.close()

    def contains(self, board):
        return self.index(board) != 2**64-1

    def index(self, board):
        value = pack(board)
        return self.dll.zs_index(self.handle, C.byref(value))

    def update(self, view, own_move=None, deadline=None):
        if view.player != self.player or view.ply != (0 if self.previous is None else self.previous.ply+1):
            raise ValueError("unexpected player or ply")
        if self.previous is not None:
            ours = self.previous.side_to_move == self.player
            if ours != (own_move is not None) or (ours and own_move not in self.previous.legal_moves):
                raise ValueError("missing or unauthorized own action")
        elif own_move is not None:
            raise ValueError("initial own action")
        if not view.terminal:
            argument = view_argument(view)
            if self.previous is None:
                good = self.dll.zs_validate(self.handle, C.byref(argument))
            else:
                seconds = -1. if deadline is None else max(0., deadline-perf_counter())
                good = self.dll.zs_update(self.handle, C.byref(argument),
                                          -1 if own_move is None else encode(own_move), seconds)
            if not good:
                message = self.dll.zs_error(self.handle).decode() or "initial observation mismatch"
                if "deadline" in message:
                    raise BudgetError(message)
                raise ValueError(message)
        self.memory = extend_memory(self.memory, view, own_move)
        self.draw = self.draw.advance(view, own_move)
        self.previous = view
        self.last_stats = dict(attempted=int(self.dll.zs_attempts(self.handle)),
                               histories=int(self.dll.zs_accepted(self.handle)), positions=len(self.candidates),
                               backend="native_full_I_reservoir_representatives")

    def sample_missing(self, retained, rng, floor=200):
        excluded = {self.index(node.state._board) for node in retained}
        excluded.discard(2**64-1)
        population = len(self.candidates)
        count = min(max(0, floor-len(retained)), population-len(excluded))
        indices = set()
        if population-len(excluded) < 2*count:
            indices = set(rng.sample([i for i in range(population) if i not in excluded], count))
        else:
            while len(indices) < count:
                index = rng.randrange(population)
                if index not in excluded:
                    indices.add(index)
        return tuple(self.candidates[i] for i in sorted(indices))
