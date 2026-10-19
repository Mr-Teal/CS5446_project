"""Score conversion and fog-of-war rule overrides (D1 spec §2 rule 3 and §5).

Expected values are hand-derived: tanh(1) = 0.7615941559557649, and the small
tanh values come from the series x - x^3/3 + 2x^5/15.
"""
import chess
import chess.engine
import pytest

from pairb.values import cp_to_value, pov_to_value, rule_value, score_to_value

Cp, Mate, MateGiven, PovScore = chess.engine.Cp, chess.engine.Mate, chess.engine.MateGiven, chess.engine.PovScore


# Catches: a wrong scale (e.g. 400 instead of the papers' 600) or a sign slip.
@pytest.mark.parametrize("cp, want", [
    (0, 0.0),
    (600, 0.7615941559557649),
    (-600, -0.7615941559557649),
    (38, 0.0632487899),
])
def test_cp_to_value_uses_tanh_over_600(cp, want):
    assert cp_to_value(cp) == pytest.approx(want, abs=1e-9)


# Catches: mates squashed to something short of exactly +1/-1, or mated scored as mating.
@pytest.mark.parametrize("score, want", [
    (Mate(3), 1.0),
    (Mate(-2), -1.0),
    (MateGiven, 1.0),
    (Mate(0), -1.0),  # python-chess's Mate(0) means "is mated"
])
def test_score_to_value_counts_mate_as_exactly_one(score, want):
    assert score_to_value(score) == want


# Catches: forgetting to flip Stockfish's side-to-move score to White's view.
def test_pov_to_value_reports_white_view_when_black_is_to_move():
    # Spec §2 example: Black to move, Stockfish says -26 cp from Black's view.
    assert pov_to_value(PovScore(Cp(-26), chess.BLACK)) == pytest.approx(0.0433062302, abs=1e-9)


# Catches: a missing rule, a rule scored from the wrong side, or Stockfish's chess verdict
# (stalemate = draw) leaking through where fog-of-war rules differ.
@pytest.mark.parametrize("fen, want", [
    ("8/8/8/8/8/8/8/4K3 b - - 0 1", ("king-captured", 1.0)),       # Black has no king
    ("4k3/8/8/8/8/8/8/8 w - - 0 1", ("king-captured", -1.0)),      # White has no king
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", ("king-capture", 1.0)),   # White to move takes the king
    ("4k3/4r3/8/8/8/8/8/4K3 b - - 0 1", ("king-capture", -1.0)),  # Black to move takes the king
    ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", ("forced-loss", 1.0)),     # Black is mated
    ("8/8/8/8/8/6k1/6q1/6K1 w - - 0 1", ("forced-loss", -1.0)),   # White is mated
    ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", ("forced-loss", 1.0)),     # Black stalemated: White wins
    ("8/8/8/8/8/6k1/5q2/7K w - - 0 1", ("forced-loss", -1.0)),    # White stalemated: Black wins
    ("8/8/8/4k3/8/8/3Q4/4K3 w - - 100 80", ("fifty-move", 0.0)),
    ("8/8/8/4k3/8/8/3Q4/4K3 w - - 99 80", ("forced-draw", 0.0)),   # every White move hits 100
])
def test_rule_value_scores_fog_of_war_overrides_from_whites_view(fen, want):
    assert rule_value(chess.Board(fen)) == want


# Catches: rules firing on ordinary positions, including one move before the fifty-move draw.
@pytest.mark.parametrize("fen", [
    chess.STARTING_FEN,
    "8/8/8/4k3/8/8/3QP3/4K3 w - - 99 80",  # a pawn move resets the clock, so nothing is decided
    "8/8/8/4k3/8/8/8/4KN2 w - - 0 1",  # king and knight vs king: not a draw under fog rules
    "8/8/8/8/8/4k3/4q3/4K2R w K - 0 1",  # orthodox mate, but castling out of check escapes (Teal)
])
def test_rule_value_leaves_ordinary_positions_to_the_evaluator(fen):
    assert rule_value(chess.Board(fen)) is None
