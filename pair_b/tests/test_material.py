"""MaterialEvaluator: the crudest leaf, counting pieces (pawn 1, knight 3, bishop 3, rook 5, queen 9).

The balance goes through the same tanh(cp / 600) as Stockfish's centipawns, so being a pawn up
counts like Stockfish's +100. Hand-derived: tanh(5/6) = 0.68226, tanh(2/3) = 0.58278.
"""
import chess
import pytest

from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation
from pairb.material import MaterialEvaluator

ROOK_UP = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"            # White has an extra rook
ROOK_TAKES_QUEEN = "q3k3/8/8/8/8/8/8/R3K3 w - - 0 1"  # White's rook against Black's queen; Ra1xa8 wins it
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"      # Re2xe8 takes the king


# Catches: piece values or the centipawn scale wrong, or the balance from the wrong side.
def test_a_rook_up_is_worth_what_stockfish_plus_500_is_worth():
    ev = MaterialEvaluator()
    assert ev.evaluate_boards([ROOK_UP], "white") == [pytest.approx(0.68226, abs=1e-4)]
    assert ev.evaluate_boards([ROOK_UP], "black") == [pytest.approx(-0.68226, abs=1e-4)]


# Catches: children scored from the side to move after the move (the opponent) instead of the mover.
def test_children_are_scored_for_the_player_making_the_move():
    values = MaterialEvaluator().evaluate_children(ROOK_TAKES_QUEEN)
    assert values["a1a8"] == pytest.approx(0.68226, abs=1e-4)   # rook against nothing: +5
    assert values["a1a2"] == pytest.approx(-0.58278, abs=1e-4)  # rook against queen: -4


# Catches: a position the rules decide being scored by counting pieces.
def test_rule_results_stay_exact():
    ev = MaterialEvaluator()
    assert ev.evaluate_children(KING_CAPTURE)["e2e8"] == 1.0
    assert ev.evaluate_boards([KING_CAPTURE], "black") == [-1.0]


# Catches: answers for one belief built from another belief's boards.
def test_each_belief_is_answered_with_its_own_boards():
    def turn(player, fens):
        obs = Observation(player=player, side_to_move=player, ply=4, visible_squares=(), visible_pieces={},
                          legal_moves=())
        return AgentInput(obs, Belief(player, 4, tuple(Hypothesis(f, 1 / len(fens)) for f in fens)), 1000)

    beliefs = [turn("white", [ROOK_UP, KING_CAPTURE]), turn("black", ["4k2r/8/8/8/8/8/8/4K3 b - - 0 1"])]
    answers = MaterialEvaluator().evaluate_beliefs(beliefs)
    assert answers[0].hypothesis_values == pytest.approx((0.68226, 1.0), abs=1e-4)
    assert answers[1].hypothesis_values == pytest.approx((0.68226,), abs=1e-4)  # Black's extra rook
    for answer, t in zip(answers, beliefs):
        answer.validate_for(t)
