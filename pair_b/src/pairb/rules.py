"""One small rules interface for Fog Lab, used by both the game referee and the belief tracker.

Two implementations sit behind it, and pick_rules chooses one at start-up: Teal's
pair_a_prep.rules_adapter.RulesAdapter, whenever it can be imported, or Pair B's stand-in, which is
python-chess with pairb.observe and fow_shared.values. The stand-in does not fill
Observation.captured_own_piece_at, which is fine while the referee and the tracker use the same
wrapper. A finished game is reported as (winner, reason), with Teal's reason names: king_capture,
fifty_move and threefold_repetition.
"""
import importlib
from dataclasses import dataclass
from typing import Any, Protocol

import chess

from fow_shared.contracts import Observation
from fow_shared.values import fog_legal_moves, terminal_score

from .observe import observe as standin_view

# fow_shared.values.terminal_score's rule names, as Teal's adapter names them
_REASONS = {"king-captured": "king_capture", "fifty-move": "fifty_move", "repetition": "threefold_repetition"}


class Rules(Protocol):
    """What the referee and the tracker need from a rules implementation.

    A state belongs to its implementation and is never changed: apply_move returns a new one.
    legal_moves are sorted UCI strings, and none once the game is over. apply_move raises
    ValueError when the game is over or the move is not legal. terminal is (winner, reason) once
    the game has ended, with winner "white", "black" or "draw", and None before that. board is an
    independent copy of the state's board, with its full move stack.
    """

    name: str   # "pairb-standin" | "teal-rules-adapter"
    label: str  # "Pair B stand-in" | "Teal's RulesAdapter"

    def initial_state(self, fen: str | None = None) -> Any: ...
    def current_player(self, state: Any) -> str: ...
    def legal_moves(self, state: Any) -> tuple[str, ...]: ...
    def apply_move(self, state: Any, move: str) -> Any: ...
    def observe(self, state: Any, player: str) -> Observation: ...
    def terminal(self, state: Any) -> tuple[str, str] | None: ...
    def board(self, state: Any) -> chess.Board: ...


@dataclass(frozen=True, eq=False)  # states compare by identity: a chess.Board is not hashable
class StandinState:
    """A position with its history: the board, move stack included, and the plies played so far.

    StandinRules gives every state a board of its own and leaves it unchanged. Take a copy with
    StandinRules.board before changing anything.
    """

    board: chess.Board
    ply: int


class StandinRules:
    """Pair B's rules: python-chess boards, fow_shared's fog-of-war rules and pairb.observe's views."""

    name = "pairb-standin"
    label = "Pair B stand-in"

    def initial_state(self, fen: str | None = None) -> StandinState:
        board = chess.Board(chess.STARTING_FEN if fen is None else fen)
        # Not Board.is_valid(): the ordinary check rules would reject positions that fog allows.
        if any(len(board.pieces(chess.KING, color)) > 1 for color in chess.COLORS):
            raise ValueError("multiple kings of one color")
        if not board.kings:
            raise ValueError("both kings are missing")
        return StandinState(board, 0)

    def current_player(self, state: StandinState) -> str:
        return "white" if state.board.turn == chess.WHITE else "black"

    def legal_moves(self, state: StandinState) -> tuple[str, ...]:
        return tuple(sorted(move.uci() for move in fog_legal_moves(state.board)))

    def apply_move(self, state: StandinState, move: str) -> StandinState:
        if self.terminal(state) is not None:
            raise ValueError(f"the game is over, so {move!r} cannot be played")
        if move not in self.legal_moves(state):
            raise ValueError(f"{move!r} is not a legal move here")
        board = state.board.copy(stack=True)
        board.push(chess.Move.from_uci(move))  # not push_uci: it refuses moves that only fog rules allow
        return StandinState(board, state.ply + 1)

    def observe(self, state: StandinState, player: str) -> Observation:
        return standin_view(state.board, player, state.ply)

    def terminal(self, state: StandinState) -> tuple[str, str] | None:
        ended = terminal_score(state.board)
        if ended is None:
            return None
        rule, score = ended  # the score is the side to move's
        mover = self.current_player(state)
        if score == 0:
            winner = "draw"
        elif score > 0:
            winner = mover
        else:
            winner = "black" if mover == "white" else "white"
        return winner, _REASONS[rule]

    def board(self, state: StandinState) -> chess.Board:
        return state.board.copy(stack=True)


class TealRules:
    """Teal's RulesAdapter, passed through as it is. Only the result and the board are translated."""

    name = "teal-rules-adapter"
    label = "Teal's RulesAdapter"

    def __init__(self) -> None:
        from pair_a_prep.rules_adapter import RulesAdapter  # not imported until it is wanted
        self._adapter = RulesAdapter()

    def initial_state(self, fen: str | None = None) -> Any:
        return self._adapter.initial_state(fen)

    def current_player(self, state: Any) -> str:
        return self._adapter.current_player(state)

    def legal_moves(self, state: Any) -> tuple[str, ...]:
        return self._adapter.legal_moves(state)

    def apply_move(self, state: Any, move: str) -> Any:
        return self._adapter.apply_move(state, move)

    def observe(self, state: Any, player: str) -> Observation:
        return self._adapter.observe(state, player)

    def terminal(self, state: Any) -> tuple[str, str] | None:
        outcome = self._adapter.terminal(state)
        return None if outcome is None else (outcome.winner, outcome.reason)

    def board(self, state: Any) -> chess.Board:
        return state.board_copy()


def teal_available() -> bool:
    """Whether Teal's pair_a_prep.rules_adapter can be imported in this checkout."""
    try:
        importlib.import_module("pair_a_prep.rules_adapter")
    except ImportError:
        return False
    return True


def pick_rules(choice: str = "auto") -> Rules:
    """The rules to use: "teal", "standin", or "auto", which is Teal's when it can be imported."""
    if choice == "standin":
        return StandinRules()
    if choice == "teal":
        if not teal_available():
            raise ValueError("Teal's rules adapter is not in this checkout")
        return TealRules()
    if choice == "auto":
        return TealRules() if teal_available() else StandinRules()
    raise ValueError(f"choice must be 'auto', 'teal' or 'standin', not {choice!r}")


class GameReferee:
    """The match runner's referee (fow_shared's Referee): the only holder of the true state.

    Agents never see it; they get observations. true_board is for the app's inspection only. Use
    one referee from one thread at a time: python-chess's repetition check replays moves on the
    stored board.
    """

    def __init__(self, rules: Rules, initial_fen: str | None = None):
        self._rules = rules
        self._initial_fen = initial_fen
        self.reset(0)

    def reset(self, seed: int) -> None:
        """Back to the start position. The rules are deterministic, so the seed is not used."""
        self._state = self._rules.initial_state(self._initial_fen)
        self._ply = 0

    def current_player(self) -> str:
        return self._rules.current_player(self._state)

    def is_terminal(self) -> bool:
        return self._rules.terminal(self._state) is not None

    def winner(self) -> str:
        """'white', 'black' or 'draw'. ValueError while the game goes on."""
        ended = self._rules.terminal(self._state)
        if ended is None:
            raise ValueError("the game has not ended")
        return ended[0]

    def result(self) -> tuple[str, str] | None:
        """(winner, reason) once the game has ended, otherwise None."""
        return self._rules.terminal(self._state)

    def observe(self, player: str) -> Observation:
        return self._rules.observe(self._state, player)

    def apply(self, move: str) -> None:
        """Play `move` for the side to move. ValueError, with the game unchanged, if the game is
        over or the move is not legal."""
        self._state = self._rules.apply_move(self._state, move)
        self._ply += 1

    def true_board(self) -> chess.Board:
        """An independent copy of the true board with its move stack, for the app's inspection only."""
        return self._rules.board(self._state)

    @property
    def ply(self) -> int:
        """Moves played so far."""
        return self._ply
