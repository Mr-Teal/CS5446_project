import math
import chess
import chess.engine
import pytest

from pair_a_prep.zs21.engine import mapped_score, canonical_board, stockfish_board, EnginePool
from pair_a_prep.zs21.engine import EngineCrashed, EvaluationError
from concurrent.futures import Future


@pytest.mark.parametrize("turn", [chess.WHITE, chess.BLACK])
@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("n", [-12, -3, -2, -1, 0, 1, 2, 3, 12])
def test_mate_distance_and_perspective(n, turn, player):
    score = chess.engine.PovScore(chess.engine.Mate(n), turn)
    value = -.9 if n == 0 else math.copysign(.9 * .78 ** (abs(n)-1), n)
    expected = value * (1 if turn == (player == "white") else -1)
    assert mapped_score(score, turn, player) == pytest.approx(expected)
    assert mapped_score(score, turn, player, 6) == pytest.approx(expected * 6)


def test_canonical_fen_preserves_fog_only_en_passant():
    board = chess.Board('k3r3/8/8/3pP3/8/8/8/4K3 w - d6 51 30')
    normalized = canonical_board(board)
    assert normalized.ep_square == chess.D6
    assert normalized.halfmove_clock == 0
    assert normalized.fullmove_number == 1
    assert board.halfmove_clock == 51


@pytest.mark.parametrize("fen", [
    "r3k1nr/p1p2ppp/8/1pP1n3/2PP2b1/8/PP3PPP/RNBK1B1R w kq b6 0 1",
    "k3r3/8/8/3pP3/8/8/8/4K3 w - d6 51 30",
])
def test_sf_only_ep_filter_preserves_orthodox_moves_and_fog_input(fen):
    board = chess.Board(fen)
    original = board.fen(en_passant="fen")
    converted = stockfish_board(board)
    assert board.has_pseudo_legal_en_passant()
    assert canonical_board(board).ep_square == board.ep_square
    assert converted.ep_square is None
    assert set(converted.legal_moves) == set(board.legal_moves)
    assert board.fen(en_passant="fen") == original

    class Recorder:
        def analyse(self, received, *args, **kwargs):
            assert received.ep_square is None
            return {"score": chess.engine.PovScore(chess.engine.Cp(630), received.turn),
                    "depth": 1, "nodes": 43}
    result = EnginePool._one(Recorder(), board, "white", 1, None, 1.)
    assert result.value == pytest.approx(math.tanh(630 / 600))


def test_sf_keeps_orthodox_legal_ep():
    board = chess.Board("k7/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    assert stockfish_board(board).ep_square == chess.D6


@pytest.mark.parametrize("fatal", [EngineCrashed("engine exit"), ValueError("bad score")])
def test_worker_timeout_does_not_mask_fatal_error(fatal):
    errors = [fatal, EvaluationError("deadline"), EvaluationError("deadline"), EvaluationError("deadline")]
    class Executor:
        def submit(self, function, index):
            future = Future()
            future.set_exception(errors[index])
            return future
    pool = object.__new__(EnginePool)
    pool.executor = Executor()
    with pytest.raises(type(fatal), match=str(fatal)):
        pool.evaluate([chess.Board()], "white")
    assert all(error.__traceback__ is None for error in errors[1:])
