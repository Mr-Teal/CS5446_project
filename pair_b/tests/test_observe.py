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


# Catches: a finished game hiding what the player's own pieces still see. Pair A's rules adapter
# keeps computing views from each side's pieces after termination (Teal on #6), and so must we.
def test_after_a_king_is_captured_each_side_still_sees_from_its_own_pieces():
    board = chess.Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
    board.push(chess.Move.from_uci("e2e8"))  # the rook takes Black's only piece, the king
    white = observe(board, "white")
    assert {"a8", "h8", "e2", "f1", "e8", "e1"} <= set(white.visible_squares)
    assert (white.terminal, white.outcome, white.legal_moves) == (True, 1.0, ())
    assert visible_squares(board, chess.BLACK) == frozenset()


def _pair_a_rules():
    try:
        from pair_a_prep.rules_adapter import RulesAdapter
    except ImportError:
        return None
    return RulesAdapter() if hasattr(RulesAdapter, "observe") else None


# Catches: any drift between this stand-in and Pair A's observe(), once that is on main.
@pytest.mark.skipif(_pair_a_rules() is None, reason="needs pair_a_prep.rules_adapter with observe()")
def test_matches_pair_as_observe_on_fixtures_and_finished_games():
    import random
    rules, boards = _pair_a_rules(), [board_for_case(c).fen(en_passant="fen") for c in load_suite()["cases"]]
    rng = random.Random(0)
    for _ in range(50):  # random play until a king falls: views after the game ends too
        b = chess.Board()
        while b.king(chess.WHITE) and b.king(chess.BLACK) and b.ply() < 150:
            b.push(rng.choice(list(b.generate_pseudo_legal_moves())))
        boards.append(b.fen(en_passant="fen"))
    for fen in boards:
        state = rules.initial_state(fen)
        for player in ("white", "black"):
            ours, theirs = observe(chess.Board(fen), player), rules.observe(state, player)
            assert (ours.side_to_move, ours.visible_squares, ours.visible_pieces, ours.legal_moves, ours.terminal,
                    ours.outcome) == (theirs.side_to_move, theirs.visible_squares, theirs.visible_pieces,
                                      theirs.legal_moves, theirs.terminal, theirs.outcome), (fen, player)
