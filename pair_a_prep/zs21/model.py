"""Observation-only inference, position transpositions and path-local draw caps."""

from collections import Counter
from dataclasses import dataclass, replace
from hashlib import sha256
from random import Random
from time import perf_counter

import chess

from fow_shared.values import fog_position_key as position_key

from ..rules_adapter import RuleState, RulesAdapter, RulesReferee
from ..interface_draft import Outcome
from .engine import canonical_board
from .rule_profile import has_fow_moves


class BudgetError(RuntimeError):
    pass


def check_time(deadline):
    if deadline is not None and perf_counter() >= deadline:
        raise BudgetError("decision budget exhausted")


class SearchRules(RulesAdapter):
    """D-09 ignores hidden draw history in the agent's position model."""

    def terminal(self, state):
        board = state._board
        if board.king(chess.WHITE) is None:
            return Outcome(winner="black", reason="king_capture")
        if board.king(chess.BLACK) is None:
            return Outcome(winner="white", reason="king_capture")
        if not self._has_moves(state):
            return Outcome(winner="draw", reason="no_legal_moves")
        return None

    def _has_moves(self, state):
        return has_fow_moves(state._board)

    def legal_moves(self, state):
        from fow_shared.values import fog_legal_moves
        return tuple(sorted(m.uci() for m in fog_legal_moves(canonical_board(state._board))))

    def apply_known_legal(self, state, move):
        action = chess.Move.from_uci(move)
        board = canonical_board(state._board)
        square = action.to_square
        if board.is_en_passant(action):
            square += -8 if board.turn else 8
        piece = board.piece_at(square)
        captured = piece is not None and piece.color != board.turn
        board.push(action)
        board.clear_stack()
        board.halfmove_clock = 0
        return RuleState(board, state.ply + 1,
                         ("white" if piece.color else "black") if captured else None,
                         chess.square_name(square) if captured else None)

    def apply_move(self, state, move):
        if move not in self.legal_moves(state):
            raise ValueError("unavailable FoW action " + move)
        return self.apply_known_legal(state, move)


class RefereeRules(RulesAdapter):
    """Use shared FoW adjudication; retain the legacy no-move replay switch."""

    def __init__(self, *, no_move_draw=True):
        self.no_move_draw = no_move_draw

    def terminal(self, state):
        outcome = super().terminal(state)
        if outcome is not None and outcome.reason == "no_legal_moves" and not self.no_move_draw:
            return None
        return outcome

    def legal_moves(self, state):
        if self.terminal(state) is not None:
            return ()
        return SearchRules().legal_moves(state)


class Referee(RulesReferee):
    def __init__(self, initial_fen=None, *, no_move_draw=True):
        self._rules = RefereeRules(no_move_draw=no_move_draw)
        self._initial_fen = initial_fen
        self.reset(0)


def view_signature(view):
    cached = getattr(view, "_zs21_signature", None)
    if cached is not None:
        return cached
    return (view.side_to_move, tuple(sorted(view.visible_pieces.items())),
            tuple(sorted(view.legal_moves)), view.captured_own_piece_at,
            view.terminal, view.outcome, view.halfmove_clock)


def extend_memory(memory, view, own_move):
    return extend_memory_signature(memory, view.player, view.ply, view_signature(view), own_move)


def extend_memory_signature(memory, player, ply, signature, own_move):
    payload = (memory, own_move, player, ply, signature)
    return sha256(repr(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DrawMemory:
    counts: dict
    quiet: int
    capped: bool
    previous: object

    @staticmethod
    def empty():
        return DrawMemory({}, 0, False, None)

    def advance(self, view, own_move=None):
        previous = self.previous
        if previous is not None and view.ply == previous.ply:
            if view_signature(view) != view_signature(previous) or own_move is not None:
                raise ValueError("conflicting duplicate observation")
            return self
        if previous is not None and view.ply != previous.ply + 1:
            raise ValueError("draw monitor requires every completed ply")
        reset = view.captured_own_piece_at is not None
        if previous is not None:
            old, new = previous.visible_pieces, view.visible_pieces
            if own_move is not None:
                reset |= old.get(own_move[:2], "").lower() == "p"
                reset |= old.get(own_move[2:4]) is not None
                # A legal diagonal pawn move to a known empty square is EP.
                reset |= (old.get(own_move[:2], "").lower() == "p"
                          and own_move[0] != own_move[2])
            else:
                enemy_pawn = "p" if view.player == "white" else "P"
                # Both endpoints must have been visible to confirm a change.
                reset |= any(old[s] != new[s] and (old[s] == enemy_pawn or new[s] == enemy_pawn)
                             for s in old.keys() & new.keys())
        quiet = 0 if reset or previous is None else self.quiet + 1
        counts = self.counts.copy()
        signature = view_signature(view)
        counts[signature] = counts.get(signature, 0) + 1
        return DrawMemory(counts, quiet,
                          self.capped or counts[signature] >= 3 or quiet >= 100, view)

    def value(self, base):
        return min(base, 0.) if self.capped else base


@dataclass(frozen=True)
class Candidate:
    state: RuleState
    moves: tuple


class PositionTracker:
    """Full I up to D-09 transpositions; L never limits this population."""

    def __init__(self, player, seed, initial_fen=None):
        self.player = player
        self.rng = Random(seed)
        self.rules = SearchRules()
        self.candidates = (Candidate(self.rules.initial_state(initial_fen), ()),)
        self.previous = None
        self.memory = ""
        self.draw = DrawMemory.empty()
        self.last_stats = {}

    def update(self, view, own_move=None, deadline=None):
        if view.player != self.player:
            raise ValueError("another player's observation")
        expected = 0 if self.previous is None else self.previous.ply + 1
        if view.ply != expected:
            raise ValueError(f"expected ply {expected}")
        if self.previous is not None:
            ours = self.previous.side_to_move == self.player
            if ours != (own_move is not None) or (ours and own_move not in self.previous.legal_moves):
                raise ValueError("missing or unauthorized own action")
        elif own_move is not None:
            raise ValueError("initial own action")
        # Terminal notifications are public facts; no next decision needs I.
        if view.terminal:
            self.previous = view
            self.memory = extend_memory(self.memory, view, own_move)
            self.draw = self.draw.advance(view, own_move)
            return
        candidates = []
        attempted = 0
        expected_signature = view_signature(view)
        for parent in self.candidates:
            check_time(deadline)
            moves = (None,) if self.previous is None else ((own_move,) if own_move else self.rules.legal_moves(parent.state))
            for move in moves:
                attempted += 1
                state = parent.state if move is None else self.rules.apply_known_legal(parent.state, move)
                # A cheap necessary condition before constructing the full view.
                if any((state._board.piece_at(chess.parse_square(s)).symbol()
                        if state._board.piece_at(chess.parse_square(s)) else None) != p
                       for s, p in view.visible_pieces.items()):
                    continue
                if view_signature(self.rules.observe(state, self.player)) == expected_signature:
                    candidates.append(Candidate(state, parent.moves + (() if move is None else (move,))))
        if not candidates:
            raise ValueError("empty full information set; no referee fallback")
        candidates.sort(key=lambda c: (str(position_key(c.state._board)), c.moves))
        random_state = self.rng.getstate()
        try:
            self.rng.shuffle(candidates)
            unique = {}
            for candidate in candidates:
                unique.setdefault(position_key(candidate.state._board), candidate)
            check_time(deadline)
        except Exception:
            self.rng.setstate(random_state)
            raise
        self.candidates = tuple(unique[k] for k in sorted(unique, key=str))
        self.memory = extend_memory(self.memory, view, own_move)
        self.draw = self.draw.advance(view, own_move)
        self.previous = view
        self.last_stats = dict(attempted=attempted, histories=len(candidates), positions=len(unique))

    def sample_missing(self, retained, rng, floor=200):
        existing = {position_key(n.state._board) for n in retained}
        missing = [c for c in self.candidates if position_key(c.state._board) not in existing]
        count = min(max(0, floor - len(retained)), len(missing))
        return tuple(missing[i] for i in sorted(rng.sample(range(len(missing)), count)))

    def contains(self, board):
        key = position_key(board)
        return any(position_key(c.state._board) == key for c in self.candidates)
