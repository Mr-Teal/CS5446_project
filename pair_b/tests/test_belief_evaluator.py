"""BeliefNetworkEvaluator (D6): the belief network behind fow_shared's three LeafEvaluator calls.

A network whose output is a known constant (C for the side to move on every board) lets the
expected values be derived by hand; rule-decided boards must keep their exact values instead.
"""
import math
import random
import shutil

import chess
import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation
from fow_shared.values import fog_legal_moves, rule_score
from pairb.belief_data import ENCODING
from pairb.belief_evaluator import BeliefNetworkEvaluator
from pairb.belief_net import BeliefNetwork
from pairb.net1 import D1_CLIP
from pairb.standin_beliefs import make_turn
from pairb.stockfish import StockfishEvaluator

C = 0.4
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"       # White to move takes the king: +1 for White
QUIET = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"
BLACK_TO_MOVE = "r2qkb1r/ppp2ppp/2n1bn2/3pp3/4P3/2NP1N2/PPP1BPPP/R1BQK2R b KQkq - 3 6"
MIDDLEGAME = "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 2 9"
needs_engine = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")


def constant_net(c=C, use_d1=False):
    """Every board gets c for its side to move (pure), or tanh(atanh(d1) + c) with use_d1."""
    net = BeliefNetwork(blocks=1, channels=8, embed=16, use_d1=use_d1)
    with torch.no_grad():
        net.value[-1].bias.fill_(c if use_d1 else math.atanh(c))
    return net


def evaluator(net=None):
    return BeliefNetworkEvaluator(net or constant_net(), name="test", device="cpu")


def blind_turn(player, fens):
    """A belief over boards the player sees nothing of, so any boards are consistent with it."""
    obs = Observation(player=player, side_to_move=player, ply=8, visible_squares=(), visible_pieces={},
                      legal_moves=("e1d1",) if player == "white" else ("e8d8",))
    return AgentInput(obs, Belief(player, 8, tuple(Hypothesis(f, 1 / len(fens)) for f in fens)), 1000)


# Catches: a board the rules decide getting the network's guess, or values from the wrong side.
def test_beliefs_get_the_networks_values_and_rule_results_exactly():
    black = make_turn(chess.Board(BLACK_TO_MOVE), random.Random(1), n_hypotheses=3, ply=11)
    with evaluator() as ev:
        white_answer, black_answer = ev.evaluate_beliefs([blind_turn("white", [KING_CAPTURE, QUIET]), black])
    assert white_answer.hypothesis_values == pytest.approx((1.0, C), abs=1e-6)
    assert black_answer.hypothesis_values == pytest.approx((C,) * len(black.belief.hypotheses), abs=1e-6)


# Catches: a board scored from its side to move rather than from the player named in the call.
def test_boards_are_scored_from_the_named_players_view():
    with evaluator() as ev:
        assert ev.evaluate_boards([BLACK_TO_MOVE], "black") == pytest.approx([C], abs=1e-6)
        assert ev.evaluate_boards([BLACK_TO_MOVE], "white") == pytest.approx([-C], abs=1e-6)
        assert ev.evaluate_boards([KING_CAPTURE], "black") == [-1.0]


# Catches: children scored for the side to move after the move instead of for the mover.
def test_children_are_scored_for_the_player_making_the_move():
    with evaluator() as ev:
        values = ev.evaluate_children(KING_CAPTURE)
    assert set(values) == {m.uci() for m in fog_legal_moves(chess.Board(KING_CAPTURE))}
    board = chess.Board(KING_CAPTURE)
    for uci, v in values.items():
        child = board.copy()
        child.push(chess.Move.from_uci(uci))
        rule = rule_score(child)
        assert v == pytest.approx(-rule[1] if rule else -C, abs=1e-6), uci


def nudged(use_d1=False):
    torch.manual_seed(0)
    net = BeliefNetwork(blocks=1, channels=8, embed=16, use_d1=use_d1)
    with torch.no_grad():
        for p in net.parameters():
            p.add_(0.1 * torch.randn_like(p))
    return net


# Catches: one belief's boards changing another belief's values when they are scored in one call.
def test_beliefs_scored_together_match_beliefs_scored_alone():
    a = make_turn(chess.Board(MIDDLEGAME), random.Random(2), n_hypotheses=5, ply=16)
    b = make_turn(chess.Board(BLACK_TO_MOVE), random.Random(3), n_hypotheses=4, ply=11)
    with evaluator(nudged()) as ev:
        together = ev.evaluate_beliefs([a, b])
        alone = ev.evaluate_beliefs([a]) + ev.evaluate_beliefs([b])
    for x, y in zip(together, alone):
        assert x.hypothesis_values == pytest.approx(y.hypothesis_values, abs=1e-6)


# Catches: with quick Stockfish as input, its value fed from the wrong side, or the per-move call
# feeding the parent's MultiPV score of a child instead of the child's own depth-1 value, which is
# what the network trained on (make_beliefs scores each board on its own; review of #6).
@needs_engine
def test_with_quick_stockfish_each_board_gets_its_own_depth_1_value_from_its_side_to_move():
    stm = lambda v: math.tanh(math.atanh(max(-D1_CLIP, min(D1_CLIP, v))) + C)
    board = chess.Board(MIDDLEGAME)
    with StockfishEvaluator(depth=1) as sf:
        (plain,) = sf.evaluate_boards([BLACK_TO_MOVE], "black")
        own = {}
        for move in fog_legal_moves(board):
            child = board.copy()
            child.push(move)
            own[move.uci()] = (sf.evaluate_boards([child.fen(en_passant="fen")], "black")[0], rule_score(child))
    with BeliefNetworkEvaluator(constant_net(use_d1=True), name="test", device="cpu") as ev:
        assert ev.evaluate_boards([BLACK_TO_MOVE], "white") == pytest.approx([-stm(plain)], abs=1e-5)
        got = ev.evaluate_children(MIDDLEGAME)
    assert set(got) == set(own)
    for uci, (child_value, rule) in own.items():  # child_value is for Black, the side to move after White's move
        assert got[uci] == pytest.approx(-rule[1] if rule else -stm(child_value), abs=1e-5), uci


# Catches: a saved network loaded without its weights, or one for other input planes accepted.
def test_checkpoints_load_with_their_weights_and_their_planes_are_checked(tmp_path):
    net = constant_net()
    good, bad = tmp_path / "belief-test" / "best.pt", tmp_path / "best.pt"
    good.parent.mkdir()
    torch.save({"state_dict": net.state_dict(), "config": net.config, "encoding": ENCODING}, good)
    torch.save({"state_dict": net.state_dict(), "config": net.config, "encoding": "other"}, bad)
    with BeliefNetworkEvaluator.from_checkpoint(good, device="cpu") as ev:
        assert ev.name == "belief-test"
        assert ev.evaluate_boards([QUIET], "white") == pytest.approx([C], abs=1e-6)
    with pytest.raises(ValueError):
        BeliefNetworkEvaluator.from_checkpoint(bad, device="cpu")


# Catches: a rule-decided board whose quick-Stockfish value the record leaves out being read as 0 in
# training and evaluation but as its rule value by the evaluator; through the belief summary that
# moves the other boards' values (review of #6).
@needs_engine
def test_training_path_and_evaluator_agree_on_a_belief_with_a_rule_board():
    import numpy as np
    from fow_shared.contracts import Decision, TrainingRecord
    from pairb.belief_data import build_arrays
    from pairb.belief_eval import predict
    turn = blind_turn("white", [KING_CAPTURE, QUIET])
    with StockfishEvaluator(depth=1) as sf:
        (quiet_d1,) = sf.evaluate_boards([QUIET], "white")
    record = TrainingRecord(turn, Decision("e1d1", {"e1d1": 1.0}, {"d1:1": quiet_d1}), 0.8, (1.0, 0.6), 0, "t", "t", "g-1")
    net = nudged(use_d1=True)
    via_training = predict(net, build_arrays([record]), np.array([0]), torch.device("cpu"))
    with BeliefNetworkEvaluator(net, name="test", device="cpu") as ev:
        (answer,) = ev.evaluate_beliefs([turn])
    assert answer.hypothesis_values[1] == pytest.approx(float(via_training[1]), abs=1e-5)
