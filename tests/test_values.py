"""Shared score conversion and fog-of-war rule checks (fow_shared/values.py).

Scores are from the acting player's point of view. Expected numbers are hand-derived:
tanh(1) = 0.7615941559557649; small values from the series x - x^3/3 + 2x^5/15.
"""
import chess
import chess.engine
import pytest

from fow_shared.values import cp_to_score, engine_score, rule_score, score_from_pov

Cp, Mate, PovScore = chess.engine.Cp, chess.engine.Mate, chess.engine.PovScore


@pytest.mark.parametrize("cp, want", [(0, 0.0), (600, 0.7615941559557649), (-600, -0.7615941559557649),
                                      (38, 0.0632487899)])
def test_centipawns_use_tanh_over_600(cp, want):
    assert cp_to_score(cp) == pytest.approx(want, abs=1e-9)


@pytest.mark.parametrize("kwargs, want", [({"mate": 3}, 1.0), ({"mate": -2}, -1.0), ({"mate": 0}, -1.0),
                                          ({"cp": 600}, 0.7615941559557649)])
def test_engine_score_counts_a_forced_mate_as_exactly_one(kwargs, want):
    # UCI "mate 0" means the side to move is already mated.
    assert engine_score(**kwargs) == pytest.approx(want, abs=1e-12)


def test_engine_score_needs_exactly_one_of_cp_and_mate():
    with pytest.raises(ValueError):
        engine_score()
    with pytest.raises(ValueError):
        engine_score(cp=10, mate=2)


def test_python_chess_scores_are_turned_to_the_named_players_view():
    # Black to move; Stockfish says -26 cp from Black's side, i.e. +26 for White.
    pov = PovScore(Cp(-26), chess.BLACK)
    assert score_from_pov(pov, "white") == pytest.approx(0.0433062302, abs=1e-9)
    assert score_from_pov(pov, "black") == pytest.approx(-0.0433062302, abs=1e-9)
    assert score_from_pov(PovScore(Mate(2), chess.WHITE), "black") == -1.0
    with pytest.raises(ValueError):
        score_from_pov(pov, "w")


@pytest.mark.parametrize("fen, want", [
    ("8/8/8/8/8/8/8/4K3 w - - 0 1", ("king-missing", 1.0)),       # Black has no king, White to move
    ("8/8/8/8/8/8/8/4K3 b - - 0 1", ("king-missing", -1.0)),      # Black to move has no king
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", ("king-capture", 1.0)),  # White to move takes the king
    ("4k3/4r3/8/8/8/8/8/4K3 b - - 0 1", ("king-capture", 1.0)),  # Black to move takes the king
    ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", ("checkmate", -1.0)),     # Black to move is mated
    ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", ("stalemate", -1.0)),     # stalemate loses for the side to move
    ("8/8/8/8/8/6k1/5q2/7K w - - 0 1", ("stalemate", -1.0)),
    ("8/8/8/4k3/8/8/3Q4/4K3 w - - 100 80", ("fifty-move", 0.0)),
])
def test_rule_score_decides_fog_of_war_positions_from_the_side_to_moves_view(fen, want):
    assert rule_score(chess.Board(fen)) == want


@pytest.mark.parametrize("fen", [chess.STARTING_FEN, "8/8/8/4k3/8/8/3Q4/4K3 w - - 99 80",
                                 "8/8/8/4k3/8/8/8/4KN2 w - - 0 1"])  # K+N v K is not a draw here
def test_rule_score_leaves_ordinary_positions_to_the_evaluator(fen):
    assert rule_score(chess.Board(fen)) is None
