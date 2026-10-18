"""Belief encoder: orientation and the rule-state planes (castling, en passant, halfmove clock)."""
import chess
import numpy as np
import pytest

from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation
from fow_shared.features import PLANE_NAMES, encode_belief


def turn_for(fen, player, halfmove=0, ply=4):
    """One-hypothesis turn with nothing visible, enough to exercise the encoder."""
    obs = Observation(player=player, side_to_move=player, ply=ply, visible_squares=(), visible_pieces={},
                      legal_moves=(), halfmove_clock=halfmove)
    return AgentInput(obs, Belief(player, ply, (Hypothesis(fen, 1.0),), population_size=1), 1000)


def plane(name):
    return PLANE_NAMES.index(name)


def test_a_position_and_its_colour_swapped_twin_encode_identically():
    # The pitch's promise: Black's view is White's mirrored, so the network learns a pattern once.
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    twin = chess.Board(fen).mirror().fen()  # colours swapped, Black to move
    as_white, _ = encode_belief(turn_for(fen, "white", halfmove=2), lambda board: ())
    as_black, _ = encode_belief(turn_for(twin, "black", halfmove=2), lambda board: ())
    np.testing.assert_array_equal(as_white, as_black)


def test_castling_rights_fill_four_planes_from_the_players_side():
    # White may castle kingside only; Black may castle queenside only.
    planes, _ = encode_belief(turn_for("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1", "white"), lambda board: ())
    got = [planes[0, plane(n)].mean() for n in ("own_kingside_castling", "own_queenside_castling",
                                                "enemy_kingside_castling", "enemy_queenside_castling")]
    assert got == [1.0, 0.0, 0.0, 1.0]


def test_en_passant_square_is_marked_where_the_player_sees_it():
    # After 1.e4 d5 2.e5 f5, White may take en passant on f6: row 2 (rank 6 from White's side), file f.
    planes, _ = encode_belief(turn_for("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
                                       "white"), lambda board: ())
    ep = planes[0, plane("en_passant_square")]
    assert ep[2, 5] == 1 and ep.sum() == 1


def test_halfmove_plane_comes_from_each_hypothesis_not_the_observation():
    # Under the paper's rules the player may not know the true clock (the pair_a_prep fixtures list
    # it as hidden), so each board's own FEN clock is used and the observation's value is ignored.
    boards = ("8/8/8/4k3/8/8/3Q4/4K3 w - - 10 80", "8/8/8/4k3/8/8/3Q4/4K3 w - - 30 80")
    obs = Observation(player="white", side_to_move="white", ply=4, visible_squares=(), visible_pieces={},
                      legal_moves=(), halfmove_clock=0)
    belief = Belief("white", 4, tuple(Hypothesis(fen, 0.5) for fen in boards), population_size=2)
    planes, _ = encode_belief(AgentInput(obs, belief, 1000), lambda board: ())
    assert np.allclose(planes[0, plane("halfmove_clock_over_100")], 0.1)
    assert np.allclose(planes[1, plane("halfmove_clock_over_100")], 0.3)


@pytest.mark.parametrize("fen, player, marked", [
    # After 1.e4 a standard FEN names e3, but no Black pawn can capture there: nothing to mark.
    ("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1", "black", None),
    # b5xc6 exposes White's king on a5 to the rook: only fog rules allow it, and it is marked.
    ("7k/8/8/KPp4r/8/8/8/8 w - c6 0 2", "white", (2, 2)),
])
def test_the_en_passant_plane_marks_only_a_square_the_player_can_capture_on(fen, player, marked):
    planes, _ = encode_belief(turn_for(fen, player), lambda board: ())
    ep = planes[0, plane("en_passant_square")]
    assert ep.sum() == (0 if marked is None else 1)
    if marked is not None:
        assert ep[marked] == 1


def test_a_dead_en_passant_square_encodes_like_none_at_all():
    # Pair A's states write standard FEN; python-chess's default leaves the square out.
    standard = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    default = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    with_square, _ = encode_belief(turn_for(standard, "black"), lambda board: ())
    without, _ = encode_belief(turn_for(default, "black"), lambda board: ())
    np.testing.assert_array_equal(with_square, without)
