"""Optional native rules fast path (rules_kernel.cpp) behind RulesAdapter(backend="native").

A state made by the native backend keeps a packed board (zs21.native_tracker.Packed, as bytes), its counters and
the FoW position keys of the positions that a repetition check can see; its python-chess board (RuleState._board,
with the full move stack) is rebuilt only when something asks for it, by replaying the moves from the nearest
ancestor that has one. States made by the Python backend are packed on first use, so both kinds mix freely.

Build with `python -m pair_a_prep.build_rules_kernel`; library() returns None when the build is missing or stale.
"""

import ctypes as C
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

import chess

from fow_shared.contracts import Observation, SCHEMA_VERSION
from .zs21.native_tracker import Packed, pack, encode

_PACKED = C.sizeof(Packed)
_BUFFER = 1 << 16


@lru_cache(maxsize=1)
def library():
    directory = Path(__file__).parent / "_rules_build"
    if not (directory / "manifest.json").exists():
        return None
    from .build_rules_kernel import source_hashes
    record = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if record["source_sha256"] != source_hashes():
        return None
    path = directory / record["library"]
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != record["dll_sha256"]:
        return None
    dll = C.CDLL(str(path))
    dll.rk_analyze.argtypes, dll.rk_analyze.restype = [C.c_char_p, C.c_char_p, C.c_int], C.c_int
    dll.rk_play.argtypes, dll.rk_play.restype = [C.c_char_p, C.c_int, C.c_char_p], C.c_int
    dll.zs_fen.argtypes, dll.zs_fen.restype = [C.c_char_p, C.c_int, C.c_int, C.c_char_p, C.c_int], C.c_int
    dll.buffer = C.create_string_buffer(_BUFFER)
    dll.board = C.create_string_buffer(_PACKED)
    return dll


class Native:
    """The native side of one RuleState (stored on it as `_native`)."""
    __slots__ = ("board", "white", "half", "full", "keys", "parent", "move", "info", "ended", "fen")

    def __init__(self, board, white, half, full, keys, parent=None, move=None):
        self.board, self.white, self.half, self.full, self.keys = board, white, half, full, keys
        self.parent, self.move = parent, move
        self.info = self.ended = self.fen = None


class Info:
    __slots__ = ("kings", "count", "key", "moves", "moves_json", "views")

    def __init__(self, text):
        lines = text.split("\n")
        kw, kb, count = lines[0].split()
        self.kings = (kw == "1", kb == "1")
        self.count = int(count)
        self.key = lines[1]
        self.moves = tuple(lines[2].split())
        self.moves_json = lines[3]
        # Per player: (squares, letters, visible_pieces JSON, visible_squares JSON), White first.
        self.views = (tuple(lines[4:8]), tuple(lines[8:12]))


def _analyze(board):
    dll = library()
    size = dll.rk_analyze(board, dll.buffer, _BUFFER)
    if size < 0:
        raise RuntimeError("native rules analysis failed")
    return Info(dll.buffer.raw[:size].decode("ascii"))


def _key(board):
    return _analyze(board).key


def native(state):
    """The state's native data, packing a Python-made state (and its repetition window) on first use."""
    data = state.__dict__.get("_native")
    if data is None:
        board = state._board
        plies = min(len(board.move_stack), board.halfmove_clock)
        probe = board.copy(stack=plies)
        keys = []
        for _ in range(plies):
            probe.pop()
            keys.append(_key(bytes(pack(probe))))
        data = Native(bytes(pack(board)), board.turn, board.halfmove_clock, board.fullmove_number,
                      tuple(reversed(keys)))
        object.__setattr__(state, "_native", data)
    return data


def info(data):
    if data.info is None:
        data.info = _analyze(data.board)
    return data.info


def terminal_score(state):
    """fow_shared.values.terminal_score(state._board), without the board."""
    data = native(state)
    if data.ended is None:
        facts = info(data)
        if not all(facts.kings):
            ended = "king-captured", (1.0 if facts.kings[0 if data.white else 1] else -1.0)
        elif data.half >= 100:
            ended = "fifty-move", 0.0
        elif len(data.keys) >= 4 and data.keys.count(facts.key) >= 2:
            ended = "repetition", 0.0
        elif facts.count == 0:
            ended = "no-moves", 0.0
        else:
            ended = False
        data.ended = ended
    return data.ended or None


def legal_moves(state):
    return () if terminal_score(state) is not None else info(native(state)).moves


def visible_squares(state, player):
    squares = info(native(state)).views[player != "white"][0]
    return tuple(squares.split()) if squares else ()


def current_player(state):
    return "white" if native(state).white else "black"


def fen(state):
    data = native(state)
    if data.fen is None:
        dll = library()
        size = dll.zs_fen(data.board, data.half, data.full, dll.buffer, _BUFFER)
        data.fen = dll.buffer.raw[:size].decode("ascii")
    return data.fen


def outcome(state, player):
    """Observation.outcome: None while the game goes on, else -1, 0 or 1 for `player`."""
    ended = terminal_score(state)
    if ended is None:
        return None
    if ended[1] == 0:
        return 0.0
    mover = current_player(state)
    winner = mover if ended[1] > 0 else ("black" if mover == "white" else "white")
    return 1.0 if winner == player else -1.0


def observe(state, player):
    data = native(state)
    squares, letters, _, _ = info(data).views[player != "white"]
    names = tuple(squares.split()) if squares else ()
    mover = current_player(state)
    value = outcome(state, player)
    return Observation(
        player=player, side_to_move=mover, ply=state.ply, visible_squares=names,
        visible_pieces={name: (None if letter == "." else letter) for name, letter in zip(names, letters)},
        legal_moves=legal_moves(state) if player == mover else (), halfmove_clock=None,
        captured_own_piece_at=state.captured_square if state.captured_player == player else None,
        terminal=value is not None, outcome=value)


_OUTCOME = {None: "null", 0.0: "0.0", 1.0: "1.0", -1.0: "-1.0"}


def observation_key(state, player):
    """chess_search.observation_key(observe(state, player)), built from the kernel's JSON pieces."""
    data = native(state)
    facts = info(data)
    _, _, pieces, squares = facts.views[player != "white"]
    mover = current_player(state)
    value = outcome(state, player)
    moves = facts.moves_json if player == mover and value is None else "[]"
    captured = ('"' + state.captured_square + '"') if state.captured_player == player else "null"
    return ('{"captured_own_piece_at":' + captured + ',"halfmove_clock":null,"legal_moves":' + moves
            + ',"outcome":' + _OUTCOME[value] + ',"player":"' + player + '","ply":' + str(state.ply)
            + ',"schema_version":' + str(SCHEMA_VERSION) + ',"side_to_move":"' + mover + '","terminal":'
            + ("false" if value is None else "true") + ',"visible_pieces":' + pieces
            + ',"visible_squares":' + squares + '}')


def apply_move(state, move, state_type):
    """RulesAdapter.apply_move: a successor RuleState without a python-chess board."""
    if move not in legal_moves(state):
        raise ValueError("unavailable UCI move: {!r}".format(move))
    data = native(state)
    dll = library()
    result = dll.rk_play(data.board, encode(move), dll.board)
    board = dll.board.raw[:_PACKED]
    square, zeroing = result & 255, result >> 8
    mover = "white" if data.white else "black"
    successor = object.__new__(state_type)
    object.__setattr__(successor, "ply", state.ply + 1)
    object.__setattr__(successor, "captured_player",
                       None if square == 64 else ("black" if mover == "white" else "white"))
    object.__setattr__(successor, "captured_square", None if square == 64 else chess.square_name(square))
    keys = () if zeroing else data.keys + (info(data).key,)
    object.__setattr__(successor, "_native", Native(
        board, not data.white, 0 if zeroing else data.half + 1, data.full + (not data.white), keys, state, move))
    return successor


def materialize(state):
    """The python-chess board of a native-made state: replay from the nearest ancestor that keeps one."""
    moves = []
    while "_board" not in state.__dict__:
        data = state.__dict__["_native"]
        moves.append(data.move)
        state = data.parent
    board = state.__dict__["_board"].copy(stack=True)
    for move in reversed(moves):
        board.push(chess.Move.from_uci(move))
    return board
