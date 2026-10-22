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


# Catches: the report's bands drifting: close is |y| < 0.3 and decided is |y| > 0.9, both strict,
# and the close-by-d1 band uses the depth-1 value, not the label.
def test_errors_bands_follow_their_definitions():
    from pairb.evaluate import errors
    y = torch.tensor([0.1, -0.2, 0.5, 0.95, -0.99, 0.3, -0.9])
    pred = torch.tensor([0.2, -0.2, 0.3, 0.75, -0.89, 0.0, -0.5])  # |error| 0.1, 0, 0.2, 0.2, 0.1, 0.3, 0.4
    d1 = torch.tensor([0.4, 0.1, -0.2, 0.9, -0.5, 0.25, -0.3])
    out = errors(pred, y, [f"p{i}" for i in range(7)], d1)
    assert out["mae"] == pytest.approx(1.3 / 7, abs=1e-6)
    assert out["mae_close"] == pytest.approx(0.05, abs=1e-6)  # rows 0 and 1; |y| = 0.3 is not close
    assert out["mae_decided"] == pytest.approx(0.15, abs=1e-6)  # rows 3 and 4; |y| = 0.9 is not decided
    assert out["mae_close_by_d1"] == pytest.approx(0.5 / 3, abs=1e-6)  # rows 1, 2 and 5
