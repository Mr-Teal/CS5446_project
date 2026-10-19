"""Network 1's scoring helpers (D3): the piece-value baseline read straight from the planes."""
import chess
import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from pairb.data import pack
from pairb.encode import encode_board
from pairb.evaluate import material_pred
from pairb.material import MaterialEvaluator


# Catches: eval_net1's piece-value baseline counting from the wrong side or with the wrong values.
@pytest.mark.parametrize("fen", ["4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "q3k3/8/8/8/8/8/8/R3K3 b - - 0 1", chess.STARTING_FEN,
                                 "r2qkb1r/ppp2ppp/2n1bn2/3pp3/4P3/2NP1N2/PPP1BPPP/R1BQK2R b KQkq - 3 6"])
def test_material_from_the_planes_matches_the_piece_value_evaluator(fen):
    board = chess.Board(fen)
    want = MaterialEvaluator().evaluate_boards([fen], "white" if board.turn == chess.WHITE else "black")[0]
    got = material_pred(torch.from_numpy(pack(encode_board(board)[None])))
    assert float(got[0]) == pytest.approx(want, abs=1e-6)
