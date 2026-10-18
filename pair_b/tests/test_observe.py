"""Pair B's stand-in for Pair A's observation generator, checked against Pair A's rules fixtures.

A player sees the squares of their own pieces and every square a fog-legal move of theirs goes to;
an en passant capture also reveals the pawn it takes. The fixtures (profile paper_fow_v1_proposed)
are the acceptance cases Pair A wrote for its own rules adapter.
"""
import chess
import pytest

from pair_a_prep.fixtures import board_for_case, compare_result, load_suite
from pairb.observe import observe, visible_squares


def winner(obs):
    if not obs.terminal:
        return None
    other = "black" if obs.player == "white" else "white"
    return {1.0: obs.player, -1.0: other, 0.0: "draw"}[obs.outcome]


# Catches: any square seen that Pair A's rules hide (a pawn's blocker, an empty diagonal, the far
# side of a capture), or one hidden that they show; and legal moves or game ends that disagree.
@pytest.mark.parametrize("case", load_suite()["cases"], ids=lambda c: c["id"])
def test_the_stand_in_observation_meets_pair_as_rules_fixtures(case):
    board = board_for_case(case)
    obs = observe(board, case["player"], ply=len(board.move_stack))
    result = {"legal_moves": obs.legal_moves, "visible_squares": obs.visible_squares,
              "visible_pieces": obs.visible_pieces, "terminal": obs.terminal, "winner": winner(obs),
              "halfmove_clock": obs.halfmove_clock}
    assert compare_result(case, result) == []


# Catches: the other side's view computed with the mover's pieces or the mover's en passant right.
def test_the_waiting_player_sees_from_their_own_pieces():
    # After 1.e4, Black (to move) and White (waiting) each see their own side of the board.
    board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    black = visible_squares(board, chess.BLACK)
    white = visible_squares(board, chess.WHITE)
    assert {"e7", "e6", "e5", "a6", "c6", "f6", "h6"} <= black and not {"e4", "e3", "d2"} & black
    assert {"e4", "e5", "d3", "d4", "a3", "f3", "h3"} <= white and not {"e7", "e6", "d7"} & white


# Catches: en passant visibility given to the side that cannot capture en passant.
def test_only_the_side_to_move_sees_through_an_en_passant_capture():
    # White's e5 pawn may take f5 en passant (White to move); Black, waiting, gains nothing from it.
    board = chess.Board("7k/8/8/4Pp2/8/8/8/K7 w - f6 0 2")
    assert {"f5", "f6"} <= visible_squares(board, chess.WHITE)
    assert "e5" not in visible_squares(board, chess.BLACK)


# Catches: a waiting player handed legal moves, or the side to move left unnamed.
def test_only_the_side_to_move_has_legal_moves():
    board = chess.Board()
    assert observe(board, "black").legal_moves == ()
    assert observe(board, "black").side_to_move == "white"
    assert len(observe(board, "white").legal_moves) == 20
