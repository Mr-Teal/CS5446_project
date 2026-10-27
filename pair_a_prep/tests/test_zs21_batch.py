from pathlib import Path
from random import Random
from time import perf_counter

import chess
import chess.engine
import pytest

from pair_a_prep.zs21.engine import EnginePool, EvaluationError


@pytest.fixture(scope="module")
def batch_pool():
    from pair_a_prep.zs21.config import load
    with EnginePool(load()["engine"]) as pool:
        yield pool


def test_batch_and_individual_searches_preserve_scores_nodes_and_order(batch_pool):
    board = chess.Board()
    rng = Random(210606068)
    boards = [board.copy()]
    for _ in range(160):
        if board.is_game_over():
            board = chess.Board()
        board.push(rng.choice(list(board.legal_moves)))
        boards.append(board.copy(stack=False))
    boards.extend(chess.Board(fen) for fen in (
        "r1bnr1k1/pp3ppp/5n2/2N5/8/P7/1P2K1PP/R1B1qB1R w - - 0 1",
        "r3k1nr/p1p2ppp/8/1pP1n3/2PP2b1/8/PP3PPP/RNBK1B1R w kq b6 0 1",
        "8/8/8/8/8/8/4k3/4K3 w - - 0 1",
        "8/8/8/8/8/8/8/4K3 b - - 0 1",
        "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    ))
    batched = batch_pool.evaluate(boards, "white")
    try:
        for engine in batch_pool.engines:
            engine.supports_batch = False
        individual = batch_pool.evaluate(boards, "white")
    finally:
        for engine in batch_pool.engines:
            engine.supports_batch = True
    assert batched == individual
    assert batch_pool.evaluate(tuple(reversed(boards)), "white") == tuple(reversed(individual))


def test_batch_deadline_is_shared_and_worker_is_reusable(batch_pool):
    engine = batch_pool.engines[0]
    board = chess.Board()
    before = engine.analyse(board, chess.engine.Limit(depth=1))
    start = perf_counter()
    with pytest.raises(EvaluationError, match="deadline|batch"):
        engine.analyse_many([board] * 64, 40, start+.025)
    assert perf_counter()-start < 1.
    after = engine.analyse(board, chess.engine.Limit(depth=1))
    assert before == after
