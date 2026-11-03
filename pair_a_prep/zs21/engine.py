"""Four persistent single-thread SF13 workers and the agreed utility mapping."""

from concurrent.futures import ThreadPoolExecutor
from collections import deque
from dataclasses import dataclass
from math import tanh
from pathlib import Path
from time import perf_counter
import subprocess
import threading
import queue
import json
import ctypes as C

import chess
import chess.engine

from .rule_profile import has_fow_moves

# Windows-only flag that hides the engine console; 0 is the no-op default elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EvaluationError(RuntimeError):
    pass


class EngineCrashed(EvaluationError):
    pass


class UCIWorker:
    """Batch command writes avoid an asyncio round trip for each UCI handshake."""

    def __init__(self, executable, network):
        from .native_tracker import library, pack
        self._fen_dll, self._pack = library(), pack
        self._fen_buffer = C.create_string_buffer(160)
        self.last_queries, self.tail = deque(maxlen=8), deque(maxlen=12)
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, creationflags=_NO_WINDOW)
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.id, self.options = {}, []
        self._write("uci\n")
        while True:
            line = self._line(perf_counter()+5)
            if line == "uciok":
                break
            if line.startswith("id "):
                _, key, value = line.split(" ", 2)
                self.id[key] = value
            if line.startswith("option "):
                self.options.append(line)
        self._write("setoption name Threads value 1\nsetoption name Hash value 16\n"
                    "setoption name Use NNUE value true\n"
                    f"setoption name EvalFile value {network}\nisready\n")
        while self._line(perf_counter()+5) != "readyok":
            pass
        self.supports_batch = any(line.startswith("option name ZS Batch Protocol ") for line in self.options)

    def _read(self):
        for line in self.process.stdout:
            self.tail.append(line.strip())
            self.lines.put(line.strip())
        self.lines.put(None)

    def _write(self, command):
        try:
            self.process.stdin.write(command)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise self.crash("Stockfish pipe closed") from exc

    def crash(self, message):
        return EngineCrashed(message + ": " + json.dumps(dict(returncode=self.process.poll(),
                              queries=list(self.last_queries), output=list(self.tail))))

    def _line(self, deadline):
        try:
            line = self.lines.get(timeout=max(.001, deadline-perf_counter()))
        except queue.Empty as exc:
            raise EvaluationError("Stockfish response deadline") from exc
        if line is None:
            raise self.crash("Stockfish exited unexpectedly")
        return line

    def _fen(self, board):
        if board.chess960:
            fen = board.fen(en_passant="fen")
        else:
            value = self._pack(board)
            size = self._fen_dll.zs_fen(C.byref(value), board.halfmove_clock, board.fullmove_number,
                                        self._fen_buffer, len(self._fen_buffer))
            if size < 0:
                raise EvaluationError("FEN serialization capacity exceeded")
            fen = self._fen_buffer.value.decode("ascii")
        return fen

    @staticmethod
    def _score_info(line, turn):
        tokens = line.split()
        if tokens[:1] != ["info"] or "score" not in tokens:
            return None
        score_at = tokens.index("score")
        kind, value = tokens[score_at+1:score_at+3]
        score = chess.engine.Cp(int(value)) if kind == "cp" else chess.engine.Mate(int(value))
        info = {"score": chess.engine.PovScore(score, turn)}
        for key in ("depth", "nodes"):
            if key in tokens:
                info[key] = int(tokens[tokens.index(key)+1])
        for key in ("lowerbound", "upperbound"):
            if key in tokens:
                info[key] = True
        return info

    def analyse(self, board, limit, **unused):
        fen = self._fen(board)
        self.last_queries.append(dict(fen=fen,depth=limit.depth,time=limit.time))
        timeout = perf_counter() + (limit.time if limit.time is not None else 5.)
        timing = "" if limit.time is None else f" movetime {max(1, int(limit.time * 1000))}"
        self._write(f"ucinewgame\nposition fen {fen}\ngo depth {limit.depth}{timing}\n")
        info = {}
        while True:
            try:
                line = self._line(timeout + .02)
            except EngineCrashed:
                raise
            except EvaluationError:
                self._write("stop\n")
                # Finish this query before a later task can use the same worker.
                while not self._line(perf_counter()+1).startswith("bestmove"):
                    pass
                raise
            if line.startswith("bestmove"):
                return info
            update = self._score_info(line, board.turn)
            if update is not None:
                info = update

    def analyse_many(self, boards, depth, deadline):
        if not 1 <= len(boards) <= 64 or not self.supports_batch:
            raise ValueError("unsupported native UCI batch")
        fens = [self._fen(board) for board in boards]
        remaining = 60. if deadline is None else deadline-perf_counter()-.005
        if remaining <= 0:
            raise EvaluationError("deadline before engine batch")
        for fen in fens:
            self.last_queries.append(dict(fen=fen, depth=depth, time=remaining, batch=True))
        timeout = perf_counter()+remaining
        self._write(f"zs_batch {depth} {max(1, int(remaining*1000))} {len(boards)}\n"
                    + "\n".join(fens) + "\n")
        results, info = [], {}
        while True:
            try:
                line = self._line(timeout+.02)
            except EngineCrashed:
                raise
            except EvaluationError:
                self._write("stop\n")
                # The engine checks one shared deadline before every query.
                while not self._line(perf_counter()+1).startswith("zs_batch_done "):
                    pass
                raise
            if line.startswith("zs_batch_done "):
                fields = line.split()
                if fields != ["zs_batch_done", str(len(boards)), "ok"] or len(results) != len(boards):
                    raise EvaluationError("engine batch did not complete before deadline")
                return results
            if line.startswith("bestmove"):
                results.append(info)
                info = {}
            elif len(results) < len(boards):
                update = self._score_info(line, boards[len(results)].turn)
                if update is not None:
                    info = update

    def quit(self):
        if self.process.poll() is None:
            try:
                self._write("quit\n")
            except EngineCrashed:
                pass
            try:
                self.process.wait(timeout=2.)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.reader.join(timeout=1.)

    def close(self):
        self.quit()


def canonical_board(board):
    result = board.copy(stack=False)
    result.halfmove_clock = 0
    result.fullmove_number = 1
    if not any(result.generate_pseudo_legal_ep()):
        result.ep_square = None
    return result


def stockfish_board(board):
    result = canonical_board(board)
    if not result.has_legal_en_passant():
        result.ep_square = None
    return result


def mapped_score(score, side_to_move, player, scale=1.):
    sign = 1. if side_to_move == (player == "white") else -1.
    relative = score.relative
    if relative.is_mate():
        n = relative.mate()
        if n is None:
            raise EvaluationError("mate score has no distance")
        value = -0.9 if n == 0 else (1 if n > 0 else -1) * 0.9 * 0.78 ** (abs(n) - 1)
    else:
        cp = relative.score()
        if cp is None:
            raise EvaluationError("engine returned no centipawn value")
        value = tanh(cp / 600)
    return scale * sign * value


@dataclass(frozen=True)
class Estimate:
    value: float
    source: str
    depth: int
    nodes: int = 0


class EnginePool:
    def __init__(self, executable, workers=4):
        if workers != 4:
            raise ValueError("the agreed reproduction uses one pool of four engines")
        executable = Path(executable).resolve()
        network = executable.with_name("nn-62ef826d1a6d.nnue")
        self.engines = []
        try:
            for _ in range(workers):
                engine = UCIWorker(executable, network)
                self.engines.append(engine)
                if engine.id.get("name") != "Stockfish 13":
                    raise EvaluationError("expected exact engine identity Stockfish 13")
        except Exception:
            self.close()
            raise
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="zs21-sf13")
        self.metadata = {"identity": self.engines[0].id, "workers": workers,
                         "threads": 1, "hash_mb": 16, "network": str(network),
                         "options": self.engines[0].options,
                         "transport": "native_uci_batches" if self.engines[0].supports_batch else "batched_uci"}

    def close(self):
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=True, cancel_futures=True)
        for engine in getattr(self, "engines", ()):
            try:
                engine.quit()
            except (chess.engine.EngineError, TimeoutError):
                engine.close()
        self.engines = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def _guard(board, player, scale):
        if board.king(chess.WHITE) is None or board.king(chess.BLACK) is None:
            winner = "white" if board.king(chess.WHITE) is not None else "black"
            return Estimate(scale * (1 if player == winner else -1), "king_capture_terminal", 0)
        if not has_fow_moves(board):
            return Estimate(0., "no_legal_moves_terminal", 0)
        if board.was_into_check():
            # Orthodox SF13 cannot legally search a capture of the opponent king.
            # This is a one-ply FoW threat estimate, not a referee termination.
            sign = 1 if board.turn == (player == "white") else -1
            return Estimate(scale * sign * .9, "fow_immediate_king_capture", 0)
        return None

    @staticmethod
    def _result(info, board, player, depth, scale):
        score = info.get("score")
        completed = info.get("depth", 0)
        if score is None or (completed < depth and not score.is_mate() and any(board.generate_legal_moves())):
            raise EvaluationError("query did not produce a complete requested-depth value")
        if info.get("lowerbound") or info.get("upperbound"):
            raise EvaluationError("unresolved engine score bound")
        return Estimate(mapped_score(score, board.turn, player, scale), "stockfish13",
                        completed, info.get("nodes", 0))

    @staticmethod
    def _one(engine, board, player, depth, deadline, scale):
        guarded = EnginePool._guard(board, player, scale)
        if guarded is not None:
            return guarded
        remaining = None if deadline is None else deadline - perf_counter() - .005
        if remaining is not None and remaining <= 0:
            raise EvaluationError("deadline before engine query")
        limit = chess.engine.Limit(depth=depth, time=remaining)
        try:
            info = engine.analyse(stockfish_board(board), limit, game=object(),
                                  info=chess.engine.INFO_SCORE | chess.engine.INFO_BASIC)
        except (chess.engine.EngineError, TimeoutError) as exc:
            raise EvaluationError(str(exc)) from exc
        return EnginePool._result(info, board, player, depth, scale)

    def _many(self, worker, boards, player, depth, deadline, scale):
        result, indices, prepared = [], [], []
        engine = self.engines[worker]
        def finish():
            if prepared:
                answers = engine.analyse_many(prepared, depth, deadline)
                result.extend((i, self._result(info, boards[i], player, depth, scale))
                              for i, info in zip(indices, answers))
                indices.clear()
                prepared.clear()
        for i in range(worker, len(boards), 4):
            guarded = self._guard(boards[i], player, scale)
            if guarded is not None:
                result.append((i, guarded))
            else:
                indices.append(i)
                prepared.append(stockfish_board(boards[i]))
                if len(prepared) == 64:
                    finish()
        finish()
        return result

    def evaluate(self, boards, player, *, depth=1, deadline=None, scale=1.):
        boards = tuple(boards)
        if not boards:
            return ()
        def batch(worker):
            if depth == 1 and self.engines[worker].supports_batch:
                return self._many(worker, boards, player, depth, deadline, scale)
            return [(i, self._one(self.engines[worker], boards[i], player, depth, deadline, scale))
                    for i in range(worker, len(boards), 4)]
        futures = [self.executor.submit(batch, worker) for worker in range(4)]
        result = [None] * len(boards)
        error = None
        def priority(exc):
            return 2 if isinstance(exc, EngineCrashed) else 1 if isinstance(exc, EvaluationError) else 3
        for future in futures:
            try:
                for i, value in future.result():
                    result[i] = value
            except Exception as exc:
                if error is None or priority(exc) > priority(error):
                    error = exc
        if error is not None:
            for future in futures:
                failure = future.exception()
                if failure is not None:
                    failure.__traceback__ = failure.__context__ = failure.__cause__ = None
            futures.clear()
            raise error
        return tuple(result)
