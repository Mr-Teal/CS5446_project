"""Lossless path DAG and history-sensitive rule state for BeliefTracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from struct import pack
from zlib import crc32

import chess

from fow_shared.contracts import Observation
from fow_shared.values import _available_fog_moves


def position_key(board: chess.Board, *, effective_ep: bool = True) -> bytes:
    ep = board.ep_square
    if effective_ep and not board.has_pseudo_legal_en_passant():
        ep = None
    return pack("<10Q", board.pawns, board.knights, board.bishops, board.rooks,
                board.queens, board.kings, board.occupied_co[chess.WHITE],
                board.clean_castling_rights(), int(board.turn), 64 if ep is None else ep)


@dataclass(slots=True, eq=False)
class PathNode:
    # Each incoming edge represents ALL paths of that parent, followed by move.
    incoming: list[tuple[PathNode, str]] = field(default_factory=list)
    count: int = 1
    position: bytes = b""
    recent: int = 0

    def path_at(self, index: int) -> tuple[str, ...]:
        if not 0 <= index < self.count:
            raise IndexError(index)
        moves = []
        node = self
        while node.incoming:
            for parent, move in node.incoming:
                if index < parent.count:
                    moves.append(move)
                    node = parent
                    break
                index -= parent.count
            else:
                raise AssertionError("invalid path multiplicity")
        return tuple(reversed(moves))


@dataclass(slots=True, eq=False)
class StateNode:
    board: chess.Board
    paths: PathNode

    def key(self) -> tuple:
        b = self.board
        return (position_key(b, effective_ep=False), b.promoted, b.halfmove_clock,
                b.fullmove_number)


def position_bit(key: bytes) -> int:
    """Only a negative membership prefilter; collisions NEVER discard a path."""
    return 1 << (crc32(key) & 1023)


def repetition_paths(node: PathNode, key: bytes, horizon: int, draw: bool,
                     check=lambda: None) -> PathNode | None:
    """Retain paths with (draw) / without two prior occurrences of child key.

    The DAG preserves past positions, so different repetition contexts need not
    duplicate the CURRENT chess board. Filter only the relevant recent suffix;
    shared unaffected prefixes and exact path multiplicities stay intact.
    """
    bit = position_bit(key)
    memo = {}

    def visit(current, left, needed):
        check()
        if needed <= 0:
            return current if draw else None
        if left <= 0 or not current.recent & bit:
            return None if draw else current
        identity = (current, left, needed)
        if identity in memo:
            return memo[identity]
        needed -= current.position == key
        if needed <= 0:
            result = current if draw else None
        elif not current.incoming:
            result = None if draw else current
        else:
            incoming = []
            unchanged = True
            for parent, move in current.incoming:
                filtered = visit(parent, left - 1, needed)
                unchanged &= filtered is parent
                if filtered is not None:
                    incoming.append((filtered, move))
            result = (current if unchanged else
                      PathNode(incoming, sum(p.count for p, _ in incoming),
                               current.position, current.recent) if incoming else None)
        memo[identity] = result
        return result

    return visit(node, horizon, 2)


def history_id(root: str, moves: tuple[str, ...]) -> str:
    identity = root
    for move in moves:
        identity = sha256((identity + ":" + move).encode("ascii")).hexdigest()
    return identity


class ObservationFilter:
    """Reject cheap mismatches before materializing boards, paths, FENs or views."""

    def __init__(self, observed: Observation):
        self.observed = observed
        self.viewer = observed.player == "white"
        self.turn = observed.side_to_move == "white"
        self.mask = 0
        self.pieces = [0] * 6
        self.white = 0
        for square, symbol in observed.visible_pieces.items():
            bit = chess.BB_SQUARES[chess.parse_square(square)]
            self.mask |= bit
            if symbol:
                piece = chess.Piece.from_symbol(symbol)
                self.pieces[piece.piece_type - 1] |= bit
                if piece.color:
                    self.white |= bit
        self.actions = frozenset(observed.legal_moves)

    def cheap(self, board: chess.Board, captured: str | None) -> bool:
        o = self.observed
        return (board.turn == self.turn and captured == o.captured_own_piece_at
                and (o.halfmove_clock is None or board.halfmove_clock == o.halfmove_clock)
                and all((bits & self.mask) == expected for bits, expected in zip(
                    (board.pawns, board.knights, board.bishops, board.rooks,
                     board.queens, board.kings), self.pieces))
                and board.occupied_co[chess.WHITE] & self.mask == self.white)

    def board_outcome(self, board: chess.Board):
        if not board.kings & board.occupied_co[chess.WHITE]:
            outcome = -1.0 if self.viewer else 1.0
        elif not board.kings & board.occupied_co[chess.BLACK]:
            outcome = 1.0 if self.viewer else -1.0
        elif board.halfmove_clock >= 100:
            outcome = 0.0
        elif next(board.generate_pseudo_legal_moves(), None) is None and not _available_fog_moves(board):
            outcome = 0.0
        else:
            outcome = None
        return outcome

    def full(self, board: chess.Board, repetition_count: int) -> bool:
        o = self.observed
        outcome = self.board_outcome(board)
        if outcome is None and repetition_count >= 3:
            outcome = 0.0
        if (outcome is not None) != o.terminal or outcome != o.outcome:
            return False
        if self.viewer == board.turn and outcome is None:
            if frozenset(m.uci() for m in _available_fog_moves(board)) != self.actions:
                return False
        elif self.actions:
            return False
        # Match RulesAdapter.visible_squares exactly, including terminal views
        # and its ordinary pseudo-legal castling visibility convention.
        turn, ep = board.turn, board.ep_square
        if turn != self.viewer:
            board.ep_square = None
        board.turn = self.viewer
        try:
            visible = board.occupied_co[self.viewer]
            for move in board.generate_pseudo_legal_moves():
                visible |= chess.BB_SQUARES[move.to_square]
                if board.is_en_passant(move):
                    visible |= chess.BB_SQUARES[move.to_square + (-8 if self.viewer else 8)]
            return visible == self.mask
        finally:
            board.turn, board.ep_square = turn, ep


def successors(parent: StateNode, own_move: str | None, expected: ObservationFilter):
    """Yield valid transitions; reuse one temporary board with push/pop."""
    board = parent.board.copy(stack=False)
    actions = ([chess.Move.from_uci(own_move)] if own_move is not None
               else sorted(_available_fog_moves(board), key=lambda m: m.uci()))
    for action in actions:
        captured = None
        if board.turn != expected.viewer:
            target = action.to_square
            if board.is_en_passant(action):
                target += -8 if board.turn else 8
            if board.occupied_co[expected.viewer] & chess.BB_SQUARES[target]:
                captured = chess.square_name(target)
        if captured != expected.observed.captured_own_piece_at:
            yield None
            continue
        board.push(action)
        try:
            if not expected.cheap(board, captured):
                yield None
                continue
            # Visible geometry depends only on the board and declared terminal
            # feedback. History-dependent repetition is filtered in the DAG.
            draw = expected.observed.terminal and expected.observed.outcome == 0
            if not expected.full(board, 3 if draw else 0):
                yield None
                continue
            needs_repetition = draw if expected.board_outcome(board) is None else None
            yield board, action.uci(), needs_repetition
        finally:
            board.pop()
