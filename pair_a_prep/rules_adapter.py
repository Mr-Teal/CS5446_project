"""History-preserving FoW rules and a private-observation referee.

RulesAdapter(backend="native") answers from a C++ kernel (rules_kernel.cpp, built with
`python -m pair_a_prep.build_rules_kernel`) with the same results (test_rules_native.py); its states carry a packed
board and build the python-chess board only on demand. backend="auto" (the default) uses the kernel when it is
built, and Python otherwise or for subclasses, which may override single rules. FOW_RULES_BACKEND in the
environment sets the default.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

import chess

from fow_shared.values import fog_legal_moves, terminal_score
from fow_shared.contracts import Observation
from .interface_draft import Outcome, Player


@dataclass(frozen=True, eq=False)
class RuleState:
    """Internal full state, for the runner or a tracker candidate only.

    Keep _board private by convention. board_copy() is the supported access path
    and preserves history without exposing the stored mutable board.
    """

    _board: chess.Board = field(repr=False)
    ply: int = 0
    captured_player: Optional[Player] = None
    captured_square: Optional[str] = None

    def __post_init__(self) -> None:
        if self.ply < 0:
            raise ValueError("negative ply")
        object.__setattr__(self, "_board", self._board.copy(stack=True))

    @property
    def fen(self) -> str:
        """Position snapshot only; use board_copy() when history is required."""
        if "_board" not in self.__dict__:
            from . import _rules_native
            return _rules_native.fen(self)
        return self._board.fen(en_passant="fen")

    def __getattr__(self, name):
        # Only states made by the native backend lack _board; build it from their ancestors once.
        if name != "_board" or "_native" not in self.__dict__:
            raise AttributeError(name)
        from . import _rules_native
        board = _rules_native.materialize(self)
        object.__setattr__(self, "_board", board)
        return board

    def board_copy(self) -> chess.Board:
        """Return an independent board with its complete retained move stack."""
        return self._board.copy(stack=True)


class RulesAdapter:
    """Shared rules for the referee and hypothetical tracker branches."""

    BACKEND = os.environ.get("FOW_RULES_BACKEND", "auto")  # auto, python or native (see module docstring)
    backend = "python"  # resolved per instance; subclasses that skip __init__ stay on Python

    def __init__(self, backend: Optional[str] = None):
        requested = self.BACKEND if backend is None else backend
        if requested not in ("auto", "python", "native"):
            raise ValueError("backend must be auto, python or native")
        if requested == "python" or (requested == "auto" and type(self) is not RulesAdapter):
            self.backend = "python"
            return
        from . import _rules_native
        if _rules_native.library() is None:
            if requested == "native":
                raise RuntimeError("native rules kernel is not built; run python -m pair_a_prep.build_rules_kernel")
            self.backend = "python"
        else:
            self.backend = "native"
        if self.backend == "native":
            self._kernel = _rules_native

    @staticmethod
    def _color(player: Player) -> bool:
        if player not in ("white", "black"):
            raise ValueError("player must be white or black")
        return player == "white"

    def visible_squares(self, state: RuleState, player: Player) -> Tuple[str, ...]:
        """Own occupied squares plus reachable destinations, ignoring check.

        Pawn diagonals reveal occupied capturable targets only; blocked forward
        squares stay hidden unless another own piece sees them. Views remain
        available off-turn and after termination. En passant belongs only to the
        actual side to move and reveals both target and capturable pawn.
        """
        color = self._color(player)
        if self.backend == "native":
            return self._kernel.visible_squares(state, player)
        # Visibility depends on the position, never its repetition history.
        board = state._board.copy(stack=False)
        if board.turn != color:
            board.ep_square = None
        board.turn = color
        visible = set(chess.scan_forward(board.occupied_co[color]))
        for move in board.generate_pseudo_legal_moves():
            visible.add(move.to_square)
            if board.is_en_passant(move):
                visible.add(move.to_square + (-8 if color else 8))
        return tuple(sorted(chess.square_name(square) for square in visible))

    def observe(self, state: RuleState, player: Player) -> Observation:
        self._color(player)
        if self.backend == "native":
            return self._kernel.observe(state, player)
        squares = self.visible_squares(state, player)
        pieces = {square: (piece.symbol() if piece else None)
                  for square in squares
                  for piece in [state._board.piece_at(chess.parse_square(square))]}
        ended = self.terminal(state)
        outcome = None if ended is None else (
            0.0 if ended.winner == "draw" else 1.0 if ended.winner == player else -1.0)
        return Observation(
            player=player, side_to_move=self.current_player(state), ply=state.ply,
            visible_squares=squares, visible_pieces=pieces,
            legal_moves=self.legal_moves(state) if player == self.current_player(state) else (),
            halfmove_clock=None,
            captured_own_piece_at=state.captured_square if state.captured_player == player else None,
            terminal=ended is not None, outcome=outcome,
        )

    def initial_state(self, fen: Optional[str] = None) -> RuleState:
        # Do not use Board.is_valid(): ordinary check restrictions reject FoW states.
        board = chess.Board(chess.STARTING_FEN if fen is None else fen)
        if any(len(board.pieces(chess.KING, color)) > 1 for color in chess.COLORS):
            raise ValueError("multiple kings of one color")
        if not board.kings:
            raise ValueError("both kings are missing")
        return RuleState(board)

    def observation_key(self, state: RuleState, player: Player) -> str:
        """chess_search.observation_key(self.observe(state, player))."""
        self._color(player)
        if self.backend == "native":
            return self._kernel.observation_key(state, player)
        from .chess_search import observation_key
        return observation_key(self.observe(state, player))

    def current_player(self, state: RuleState) -> Player:
        if self.backend == "native":
            return self._kernel.current_player(state)
        return "white" if state._board.turn == chess.WHITE else "black"

    def legal_moves(self, state: RuleState) -> Tuple[str, ...]:
        if self.backend == "native":
            return self._kernel.legal_moves(state)
        return tuple(sorted(move.uci() for move in fog_legal_moves(state._board)))

    def terminal(self, state: RuleState) -> Optional[Outcome]:
        result = (self._kernel.terminal_score(state) if self.backend == "native"
                  else terminal_score(state._board))
        if result is None:
            return None
        reason, score = result
        if score == 0:
            winner = "draw"
        elif score > 0:
            winner = self.current_player(state)
        else:
            winner = "black" if self.current_player(state) == "white" else "white"
        reasons = {"king-captured": "king_capture", "fifty-move": "fifty_move",
                   "repetition": "threefold_repetition", "no-moves": "no_legal_moves"}
        return Outcome(winner=winner, reason=reasons[reason])

    def apply_move(self, state: RuleState, move: str) -> RuleState:
        if self.backend == "native":
            return self._kernel.apply_move(state, move, RuleState)
        if move not in self.legal_moves(state):
            raise ValueError("unavailable UCI move: {!r}".format(move))
        action = chess.Move.from_uci(move)
        board = state._board
        captured_square = action.to_square
        if board.is_en_passant(action):
            captured_square += -8 if board.turn == chess.WHITE else 8
        piece = board.piece_at(captured_square)
        # Castling is not a capture. Validated FoW actions never capture own pieces.
        captured = piece is not None and piece.color != board.turn
        captured_player = ("white" if piece.color else "black") if captured else None
        # RuleState makes the one defensive history-preserving copy. Finish the
        # move on that privately owned copy before publishing the successor.
        successor = RuleState(
            board, ply=state.ply + 1, captured_player=captured_player,
            captured_square=chess.square_name(captured_square) if captured else None,
        )
        successor._board.push(action)
        return successor


class RulesReferee:
    """Mutable runner boundary; agents receive only observe() snapshots.

    A custom starting FEN must also be configured publicly in both trackers.
    This constructor does not change the shared reset protocols.
    """

    def __init__(self, initial_fen: Optional[str] = None):
        self._rules = RulesAdapter()
        self._initial_fen = initial_fen
        self.reset(seed=0)

    def reset(self, seed: int) -> None:
        # Rules are deterministic; the seed is accepted for Referee compatibility.
        self._state = self._rules.initial_state(self._initial_fen)

    def current_player(self) -> Player:
        return self._rules.current_player(self._state)

    def is_terminal(self) -> bool:
        return self._rules.terminal(self._state) is not None

    def winner(self) -> str:
        ended = self._rules.terminal(self._state)
        if ended is None:
            raise ValueError("game has not ended")
        return ended.winner

    def observe(self, player: Player) -> Observation:
        return self._rules.observe(self._state, player)

    def apply(self, move: str) -> None:
        self._state = self._rules.apply_move(self._state, move)


def fixture_result(case: dict) -> dict:
    """Bridge for: python -m pair_a_prep.fixtures --adapter ...:fixture_result."""
    from dataclasses import asdict

    rules = RulesAdapter()
    state = rules.initial_state(case.get("initial_fen", case["fen"]))
    for move in case.get("moves_uci", []):
        state = rules.apply_move(state, move)
    result = asdict(rules.observe(state, case["player"]))
    ended = rules.terminal(state)
    result["winner"] = ended.winner if ended else None
    return result
