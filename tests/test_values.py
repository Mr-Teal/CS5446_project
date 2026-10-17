"""Shared score conversion and fog-of-war rule checks (fow_shared/values.py).

Scores are from the acting player's point of view. Expected numbers are hand-derived:
tanh(1) = 0.7615941559557649; small values from the series x - x^3/3 + 2x^5/15.
"""
import chess
import chess.engine
import pytest

from fow_shared.values import (cp_to_score, engine_score, fog_legal_moves, forced_score, rule_score,
                               score_from_pov, terminal_score)
from pair_a_prep.fixtures import board_for_case, compare_result, load_suite

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


# --- Finished games: terminal_score -------------------------------------------------------

@pytest.mark.parametrize("fen, want", [
    ("8/8/8/8/8/8/8/4K3 w - - 0 1", ("king-captured", 1.0)),   # Black's king is gone; White to move
    ("8/8/8/8/8/8/8/4K3 b - - 0 1", ("king-captured", -1.0)),  # Black to move has lost its king
    ("8/8/8/4k3/8/8/3Q4/4K3 w - - 100 80", ("fifty-move", 0.0)),
])
def test_terminal_score_reports_finished_games(fen, want):
    assert terminal_score(chess.Board(fen)) == want


def test_threefold_repetition_needs_the_move_history():
    board = chess.Board()
    for uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
        board.push_uci(uci)
    assert terminal_score(board) == ("repetition", 0.0)
    assert terminal_score(chess.Board(board.fen())) is None  # a FEN alone cannot show it


@pytest.mark.parametrize("fen", [
    "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",           # orthodox checkmate: Black must still move
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",           # orthodox stalemate
    "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1",          # the king can be taken, but has not been yet
    "8/8/8/4k3/8/8/8/4KN2 w - - 0 1",           # king and knight v king is not a draw here
    chess.STARTING_FEN,
])
def test_games_that_are_not_over_are_not_terminal(fen):
    assert terminal_score(chess.Board(fen)) is None


# --- Decided one move ahead: forced_score -----------------------------------------------

@pytest.mark.parametrize("fen, want", [
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", ("king-capture", 1.0)),   # White to move takes the king
    ("4k3/4r3/8/8/8/8/8/4K3 b - - 0 1", ("king-capture", 1.0)),   # Black to move takes the king
    ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", ("forced-loss", -1.0)),    # every move leaves the king capturable
    ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", ("forced-loss", -1.0)),    # orthodox stalemate loses too
    ("8/8/8/8/8/6k1/5q2/7K w - - 0 1", ("forced-loss", -1.0)),
    ("8/8/8/8/8/4k3/4q3/4K2R w K - 0 1", None),                   # castling out of check escapes (e1g1)
    (chess.STARTING_FEN, None),
])
def test_forced_score_looks_one_move_ahead_under_fog_rules(fen, want):
    assert forced_score(chess.Board(fen)) == want


def test_rule_score_checks_finished_games_before_forced_results():
    assert rule_score(chess.Board("8/8/8/8/8/8/8/4K3 b - - 0 1")) == ("king-captured", -1.0)
    assert rule_score(chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")) == ("forced-loss", -1.0)
    assert rule_score(chess.Board("8/8/8/8/8/4k3/4q3/4K2R w K - 0 1")) is None


# --- Fog-of-war legal moves, checked against Pair A's rules fixtures ---------------------

def _winner(board, terminal):
    if terminal is None:
        return None
    if terminal[1] == 0:
        return "draw"
    mover = "white" if board.turn == chess.WHITE else "black"
    return mover if terminal[1] > 0 else ("black" if mover == "white" else "white")


@pytest.mark.parametrize("case", load_suite()["cases"], ids=lambda case: case["id"])
def test_fog_legal_moves_pass_the_rules_fixtures(case):
    board = board_for_case(case)
    terminal = terminal_score(board)
    result = {"legal_moves": [m.uci() for m in fog_legal_moves(board)],
              "terminal": terminal is not None, "winner": _winner(board, terminal)}
    # Only the legal-move and game-over expectations; visibility belongs to the rules adapter.
    expect = {k: v for k, v in case["expect"].items() if k.startswith("legal") or k in ("terminal", "winner")}
    assert compare_result({**case, "expect": expect}, result) == []
