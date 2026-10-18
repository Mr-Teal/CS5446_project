"""Board encoding for Network 1: planes 0-18 of the D1 spec §7, from the side to move's view.

Expected planes are hand-derived. Rows are ranks seen from the side to move (row 0 = its back
rank), columns are files a-h. For Black to move the board is mirrored, so Black's pieces sit on
the bottom rows exactly as White's would.
"""
import chess
import numpy as np
import pytest

from pairb.encode import N_PLANES, encode_board, stm_sign

OUR_PAWN, OUR_KING, THEIR_PAWN, THEIR_KING = 0, 5, 6, 11
US_TO_MOVE, OUR_K_CASTLE, OUR_Q_CASTLE, THEIR_K_CASTLE, THEIR_Q_CASTLE, EP, HALFMOVE = 12, 13, 14, 15, 16, 17, 18


def test_encoding_has_nineteen_planes_of_eight_by_eight():
    assert N_PLANES == 19
    assert encode_board(chess.Board()).shape == (19, 8, 8)


# Catches: pieces on the wrong plane, rank or file.
def test_start_position_puts_each_side_on_its_own_planes():
    x = encode_board(chess.Board())
    assert x[OUR_PAWN, 1].tolist() == [1] * 8 and x[OUR_PAWN].sum() == 8
    assert x[THEIR_PAWN, 6].tolist() == [1] * 8 and x[THEIR_PAWN].sum() == 8
    assert x[OUR_KING, 0, 4] == 1 and x[OUR_KING].sum() == 1          # e1
    assert x[THEIR_KING, 7, 4] == 1 and x[THEIR_KING].sum() == 1      # e8
    assert x[US_TO_MOVE].min() == 1
    for p in (OUR_K_CASTLE, OUR_Q_CASTLE, THEIR_K_CASTLE, THEIR_Q_CASTLE):
        assert x[p].min() == 1
    assert x[EP].sum() == 0 and x[HALFMOVE].sum() == 0


# Catches: Black to move encoded from White's side (no mirror), so the network sees two views.
def test_black_to_move_is_mirrored_so_black_plays_up_the_board():
    x = encode_board(chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"))
    assert x[OUR_PAWN, 1].tolist() == [1] * 8                         # Black's pawns, mirrored
    assert x[OUR_KING, 0, 4] == 1                                     # Black's king e8 -> row 0
    assert x[THEIR_PAWN, 4, 4] == 1                                   # White's e4 pawn -> e5
    assert x[THEIR_PAWN, 6].tolist() == [1, 1, 1, 1, 0, 1, 1, 1]      # the other seven


# Catches: castling rights assigned to the wrong side or the wrong wing after mirroring.
@pytest.mark.parametrize("fen, want", [
    ("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1", [1, 0, 0, 1]),  # White: K only; Black: q only
    ("r3k2r/8/8/8/8/8/8/R3K2R b Kq - 0 1", [0, 1, 1, 0]),  # same rights, seen from Black
])
def test_castling_planes_follow_the_side_to_move(fen, want):
    x = encode_board(chess.Board(fen))
    got = [int(x[p, 0, 0]) for p in (OUR_K_CASTLE, OUR_Q_CASTLE, THEIR_K_CASTLE, THEIR_Q_CASTLE)]
    assert got == want


# Catches: the en passant square left unmirrored for Black to move.
def test_en_passant_square_is_marked_from_the_movers_side():
    # White has just played e2-e4; Black's d4 pawn may take en passant on e3 (mirrored: e6).
    x = encode_board(chess.Board("rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 3"))
    assert x[EP, 5, 4] == 1 and x[EP].sum() == 1


def test_halfmove_clock_is_scaled_by_one_hundred():
    x = encode_board(chess.Board("8/8/8/4k3/8/8/3Q4/4K3 w - - 50 80"))
    assert np.allclose(x[HALFMOVE], 0.5)


# Catches: values flipped the wrong way between White's view and the side to move's view.
def test_stm_sign_converts_between_whites_view_and_the_movers_view():
    assert stm_sign(chess.Board()) == 1.0
    assert stm_sign(chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")) == -1.0


# Catches: Pair A's standard FENs (they name the en passant square after every two-square pawn
# move) lighting a plane Network 1 never saw lit in training, where D2's FENs named the square only
# when a capture existed.
def test_a_dead_en_passant_square_encodes_like_none_at_all():
    standard = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    default = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    np.testing.assert_array_equal(encode_board(standard), encode_board(default))


# Catches: ordinary chess's en passant rule, which forbids b5xc6 here (it exposes White's king on a5
# to the rook); fog-of-war rules allow it.
def test_an_en_passant_capture_only_fog_rules_allow_is_marked():
    x = encode_board(chess.Board("7k/8/8/KPp4r/8/8/8/8 w - c6 0 2"))
    assert x[EP, 5, 2] == 1 and x[EP].sum() == 1
