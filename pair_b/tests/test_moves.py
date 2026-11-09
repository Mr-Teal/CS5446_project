"""Tests for pairb.moves: the policy head's move encoding must mirror exactly like the planes."""
import chess
import numpy as np

from fow_shared.features import _index
from pairb.moves import N_MOVES, decode, legal_mask, move_index, policy_vector, square_index


def test_square_index_matches_plane_frame():
    for player in ("white", "black"):
        for square in chess.SQUARE_NAMES:
            row, col = _index(square, player)
            assert square_index(square, player) == row * 8 + col


def test_mirroring_makes_colour_twins_identical():
    # e2e4 for White and e7e5 for Black are the same move in the mover's frame.
    assert move_index("e2e4", "white") == move_index("e7e5", "black")
    assert move_index("g1f3", "white") == move_index("g8f6", "black")
    assert move_index("e2e4", "white") != move_index("e2e4", "black")


def test_round_trip_and_promotion_sharing():
    for player in ("white", "black"):
        for uci in ("a2a4", "h7h8q", "e1g1", "b7c8n"):
            index = move_index(uci, player)
            assert 0 <= index < N_MOVES
            assert decode(index, player) == (uci[:2], uci[2:4])
    assert move_index("h7h8q", "white") == move_index("h7h8r", "white")


def test_mask_and_vector_cover_exactly_the_policy():
    legal = ("e2e4", "d2d4", "g1f3")
    policy = {"e2e4": 0.5, "d2d4": 0.3, "g1f3": 0.2}
    mask = legal_mask(legal, "white")
    vec = policy_vector(policy, "white")
    assert mask.sum() == 3 and mask.dtype == bool
    assert np.isclose(vec.sum(), 1.0) and (vec[~mask] == 0).all()
    assert np.isclose(vec[move_index("e2e4", "white")], 0.5)
