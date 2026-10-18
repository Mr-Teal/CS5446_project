"""Observation.halfmove_clock is optional: None when the rules do not show it to the player."""
import pytest

from fow_shared.contracts import Observation


def observation(**extra):
    return Observation(player="white", ply=0, visible_squares=(), visible_pieces={}, legal_moves=(), **extra)


def test_the_halfmove_clock_may_be_left_unknown():
    assert observation().halfmove_clock is None
    assert observation(halfmove_clock=None).halfmove_clock is None
    assert observation(halfmove_clock=12).halfmove_clock == 12


def test_a_negative_halfmove_clock_is_still_rejected():
    with pytest.raises(ValueError):
        observation(halfmove_clock=-1)
