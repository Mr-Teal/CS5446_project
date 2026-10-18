"""NetworkEvaluator (D4): Network 1 behind the same three calls as Stockfish.

Network 1 takes a board and Stockfish's depth-1 value, both from the side to move's view, and
returns tanh(atanh(d1) + correction). These tests give it a known correction (C everywhere) and
derive the expected values by hand from StockfishEvaluator's depth-1 values, which are tested
on their own in test_stockfish.py.
"""
import math
import shutil

import chess
import pytest
import torch

from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation
from fow_shared.values import rule_score
from pairb.data import ENCODING
from pairb.net1 import D1_CLIP, Network1
from pairb.network_evaluator import NetworkEvaluator
from pairb.stockfish import StockfishEvaluator

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")

C = 0.5
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"          # White to move: Re2xe8 takes the king
BLACK_KING_CAPTURE = "4k3/4r3/8/8/8/8/8/4K3 b - - 0 1"    # Black to move: Re7xe1 takes the king
BLACK_TO_MOVE = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R b KQkq - 3 3"
CASTLE_OUT_OF_CHECK = "8/8/8/8/8/4k3/4q3/4K2R w K - 0 1"  # only fog rules allow e1g1 here


def correcting_net(c=C):
    """A small Network 1 whose correction is exactly c for every board (last layer: weights 0)."""
    net = Network1(blocks=1, channels=8)
    with torch.no_grad():
        net.fc2.bias.fill_(c)
    return net


def evaluator(net=None):
    return NetworkEvaluator(net or correcting_net(), name="test", device="cpu")


def stm(v):
    """A value in the side to move's own view, after the network adds C to it."""
    return math.tanh(math.atanh(max(-D1_CLIP, min(D1_CLIP, v))) + C)


def turn(player, fens):
    obs = Observation(player=player, side_to_move=player, ply=6, visible_squares=(), visible_pieces={},
                      legal_moves=())
    return AgentInput(obs, Belief(player, 6, tuple(Hypothesis(f, 1 / len(fens)) for f in fens)), 1000)


# Catches: Stockfish's value fed to the network from the wrong side, the network's answer returned
# from the wrong side, or a child that a rule decides being "corrected" by the network.
@pytest.mark.parametrize("fen", [KING_CAPTURE, BLACK_TO_MOVE, CASTLE_OUT_OF_CHECK])
def test_children_are_corrected_from_their_side_to_move_and_rule_results_stay_exact(fen):
    with StockfishEvaluator(depth=1) as sf:
        plain = sf.evaluate_children(fen)
    with evaluator() as ev:
        got = ev.evaluate_children(fen)
    assert set(got) == set(plain)
    board = chess.Board(fen)
    for uci, v in plain.items():
        child = board.copy(stack=False)
        child.push(chess.Move.from_uci(uci))  # push_uci refuses fog-only moves such as e1g1 here
        # The child's side to move is the opponent: it sees -v, and the mover gets the negative back.
        want = v if rule_score(child) is not None else -stm(-v)
        assert got[uci] == pytest.approx(want, abs=1e-5), uci


# Catches: a board's value returned from its side to move rather than the player named in the call.
def test_boards_are_scored_from_the_named_players_view():
    with StockfishEvaluator(depth=1) as sf:
        (plain,) = sf.evaluate_boards([BLACK_TO_MOVE], "black")
    with evaluator() as ev:
        (for_black,) = ev.evaluate_boards([BLACK_TO_MOVE], "black")
        (for_white,) = ev.evaluate_boards([BLACK_TO_MOVE], "white")
        assert ev.evaluate_boards([KING_CAPTURE], "white") == [1.0]
    assert for_black == pytest.approx(stm(plain), abs=1e-5)
    assert for_white == pytest.approx(-for_black, abs=1e-7)


# Catches: boards from different beliefs mixed up when the network scores them in one batch.
def test_each_belief_gets_its_own_boards_back_in_order():
    with StockfishEvaluator(depth=1) as sf:
        (start,) = sf.evaluate_boards([chess.STARTING_FEN], "white")
        (black,) = sf.evaluate_boards([BLACK_TO_MOVE], "black")
    beliefs = [turn("white", [KING_CAPTURE, chess.STARTING_FEN]), turn("black", [BLACK_TO_MOVE, BLACK_KING_CAPTURE])]
    with evaluator() as ev:
        answers = ev.evaluate_beliefs(beliefs)
    assert answers[0].hypothesis_values == pytest.approx((1.0, stm(start)), abs=1e-5)
    assert answers[1].hypothesis_values == pytest.approx((stm(black), 1.0), abs=1e-5)
    for answer, t in zip(answers, beliefs):
        answer.validate_for(t)


# Catches: a saved network loaded without its weights (the correction would be lost).
def test_a_saved_network_is_loaded_with_its_weights(tmp_path):
    net = correcting_net()
    path = tmp_path / "net-test" / "best.pt"
    path.parent.mkdir()
    torch.save({"state_dict": net.state_dict(), "config": net.config, "encoding": ENCODING}, path)
    with StockfishEvaluator(depth=1) as sf:
        (plain,) = sf.evaluate_boards([BLACK_TO_MOVE], "black")
    with NetworkEvaluator.from_checkpoint(path, device="cpu") as ev:
        (got,) = ev.evaluate_boards([BLACK_TO_MOVE], "black")
    assert got == pytest.approx(stm(plain), abs=1e-5)


# Catches: a network trained on different input planes being loaded and silently misread.
def test_a_checkpoint_for_other_input_planes_is_refused(tmp_path):
    net = correcting_net()
    path = tmp_path / "best.pt"
    torch.save({"state_dict": net.state_dict(), "config": net.config, "encoding": "other-planes"}, path)
    with pytest.raises(ValueError):
        NetworkEvaluator.from_checkpoint(path, device="cpu")
