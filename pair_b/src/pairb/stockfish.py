"""Stockfish leaf evaluators with the LeafEvaluator calls of fow_shared (D1 spec v0.3 §3).

`StockfishEvaluator(depth=1)` is the paper's leaf ([1] App. C.5): one MultiPV call
at depth 1 scores every child of the node being expanded.

Values crossing to Pair A follow fow_shared's rule: from the acting player's point of view.
`children_scores` stays in White's view: it feeds Pair B's own practice data (D2).
Moves come from fow_shared.values.fog_legal_moves, so castling into, out of or through
check and moves into check are covered; positions decided by a rule never reach Stockfish.
"""
import threading

import chess
import chess.engine

from fow_shared.contracts import LeafValues
from fow_shared.values import fog_legal_moves, terminal_score

from .values import pov_to_value, rule_value, score_to_value

_SIGN = {"white": 1.0, "black": -1.0}  # White-view value -> that player's view


def _sign(player: str) -> float:
    if player not in _SIGN:
        raise ValueError(f"player must be 'white' or 'black', got {player!r}")
    return _SIGN[player]


class StockfishEvaluator:
    def __init__(self, depth: int, path: str = "stockfish", hash_mb: int = 16, new_game_each_call: bool = True,
                 call_timeout_s: float = 60.0):
        """new_game_each_call=True sends ucinewgame before every call, so no result depends on
        earlier searches (needed for labels). Inside a search, False is about 3.4x faster (1.5 against
        5.2 ms per expanded node on 300 positions from real games,
        checkpoints/timing-new-game-each-call.json).

        call_timeout_s is a wall-clock limit on each Stockfish call. The search itself stays depth
        only, so values do not change; python-chess sets no time limit on a depth-only search, so an
        engine that stops answering would otherwise leave the call waiting forever. When the limit
        passes, the engine is closed and the call raises TimeoutError; alive() is then False, so a
        caller can reopen the engine as after a crash. The default, 60 s, is far above a normal call
        (depth 11: median 204 ms, p95 667 ms per evaluate_children, checkpoints/timing-stockfish-d11.json).
        It is read on every call, so it can be changed between calls."""
        self.depth = depth
        self.new_game_each_call = new_game_each_call
        self.call_timeout_s = call_timeout_s
        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self.engine.configure({"Threads": 1, "Hash": hash_mb})
        self.name = f"{self.engine.id.get('name', 'stockfish').lower().replace(' ', '-')}-d{depth}"
        self._game = object()

    def new_game(self) -> None:
        """Start a new game: the next call sends ucinewgame, so nothing earlier searches left in the
        hash carries over. With new_game_each_call=False this is how one game's calls share the hash
        while separate games stay independent."""
        self._game = object()

    def alive(self) -> bool:
        """Whether the engine process still answers; False once it has died or been closed."""
        try:
            self.engine.ping()
            return True
        except (chess.engine.EngineError, TimeoutError):  # the process is gone, or hangs: not alive either way
            return False

    def close(self):
        """Stop the engine. If quit() fails or times out (a crash, or an engine that has stopped
        answering), the engine is shut down anyway: python-chess closes the transport, which kills
        the process, and stops its event loop, so nothing is left running beside a replacement.
        Never raises, so a run's clean-up never ends with a traceback."""
        try:
            self.engine.quit()
        except (chess.engine.EngineError, TimeoutError):
            try:
                self.engine.close()
            except RuntimeError:  # its event loop already ended with the process
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _game_token(self):
        # python-chess sends ucinewgame whenever this token changes.
        if self.new_game_each_call:
            self._game = object()
        return self._game

    def _analyse(self, board: chess.Board, **kwargs):
        """engine.analyse at Limit(depth=self.depth), the position alone, within call_timeout_s.

        A watchdog thread closes the engine if the limit passes; python-chess then ends the pending
        call with EngineTerminatedError, which is raised again here as TimeoutError. The watchdog is
        cancelled and joined before this returns, so no thread outlives the call."""
        timed_out = threading.Event()

        def stop():
            timed_out.set()
            self.engine.close()  # thread-safe: kills the process and ends python-chess's event loop

        watchdog = threading.Timer(self.call_timeout_s, stop)
        watchdog.daemon = True
        watchdog.start()
        try:
            return self.engine.analyse(board.copy(stack=False), chess.engine.Limit(depth=self.depth),
                                       game=self._game_token(), **kwargs)
        except Exception as error:
            if timed_out.is_set():
                raise TimeoutError(f"no answer from the engine at depth {self.depth} within "
                                   f"{self.call_timeout_s:g} s (call_timeout_s); the engine was closed") from error
            raise
        finally:
            watchdog.cancel()
            watchdog.join()

    def evaluate_boards(self, fens: list[str], player: str) -> list[float]:
        """One value per board, same order, from `player`'s view ("white" or "black")."""
        sign = _sign(player)
        return [sign * self.board_value(chess.Board(fen))[0] for fen in fens]

    def evaluate_children(self, fen: str) -> dict[str, float]:
        """{move: value} for every fog-of-war legal move, from the moving player's view.

        A finished game has no children: {}.
        """
        board = chess.Board(fen)
        if terminal_score(board) is not None:
            return {}
        sign = 1.0 if board.turn == chess.WHITE else -1.0
        return {uci: sign * v for uci, (v, _) in self.children_values(board).items()}

    def evaluate_beliefs(self, turns) -> list[LeafValues]:
        """One LeafValues per belief (fow_shared AgentInput), each board scored on its own."""
        answers = []
        for turn in turns:
            fens = [h.fen for h in turn.belief.hypotheses]
            answer = LeafValues(tuple(self.evaluate_boards(fens, turn.observation.player)))
            answer.validate_for(turn)
            answers.append(answer)
        return answers

    def children_scores(self, board: chess.Board) -> dict[str, chess.engine.Score]:
        """Stockfish's White-view score for every orthodox legal move here, from one MultiPV call.

        The board must not be decided by a rule (check rule_value first). Stockfish gets the
        position alone, as everywhere here: the rules use the board's history, the engine does not.
        """
        infos = self._analyse(board, multipv=board.legal_moves.count())
        return {info["pv"][0].uci(): info["score"].white() for info in infos}

    def board_value(self, board: chess.Board) -> tuple[float, bool]:
        """One board's value from White's view, and whether a rule decided it: by rule; one move
        ahead when orthodox chess has no move but fog rules do (castling out of check); a draw,
        flagged as decided, when there is no fog-legal move either; otherwise Stockfish."""
        rule = rule_value(board)
        if rule is not None:
            return rule[1], True
        if not any(board.generate_legal_moves()):
            children = [v for v, _ in self.children_values(board).values()]
            if not children:
                # No fog-legal move and no rule result (every piece blocked). Scored as a draw here,
                # an explicit choice until Pair A's rules adapter decides such positions: its
                # rules_adapter.md says it does not silently declare them ordinary-chess draws.
                return 0.0, True
            return (max(children) if board.turn == chess.WHITE else min(children)), False
        # Send the position alone: python-chess would otherwise replay the moves that led here,
        # and a fog-only move (castling out of check) from an orthodox-illegal start kills Stockfish.
        info = self._analyse(board)
        return pov_to_value(info["score"]), False

    def children_values(self, board: chess.Board) -> dict[str, tuple[float, bool]]:
        """White-view value of every fog-legal child, and whether a rule decided it: by rule, from
        the parent's MultiPV call, or, for a fog-only move to a safe square, by scoring the child.

        Each child keeps the board's history, so a repetition draw is seen when the board carries
        it; a board built from a FEN has none to keep."""
        engine = {}
        if not board.was_into_check() and any(board.generate_legal_moves()):
            engine = self.children_scores(board)
        values = {}
        for move in fog_legal_moves(board):
            child = board.copy()
            child.push(move)
            rule = rule_value(child)
            if rule is not None:
                values[move.uci()] = (rule[1], True)
            elif move.uci() in engine:
                values[move.uci()] = (score_to_value(engine[move.uci()]), False)
            else:
                values[move.uci()] = self.board_value(child)
        return values
