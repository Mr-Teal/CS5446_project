"""Observation: the halfmove clock may be unknown, and every snapshot says whose turn it is."""
import pytest

from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation

AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


def observation(**extra):
    return Observation(player="white", side_to_move="white", ply=0, visible_squares=(), visible_pieces={},
                       legal_moves=(), **extra)


def snapshot(player, side_to_move, legal_moves=()):
    return Observation(player=player, side_to_move=side_to_move, ply=1, visible_squares=(),
                       visible_pieces={}, legal_moves=legal_moves)


def test_the_halfmove_clock_may_be_left_unknown():
    assert observation().halfmove_clock is None
    assert observation(halfmove_clock=None).halfmove_clock is None
    assert observation(halfmove_clock=12).halfmove_clock == 12


def test_a_negative_halfmove_clock_is_still_rejected():
    with pytest.raises(ValueError):
        observation(halfmove_clock=-1)


def test_a_view_taken_on_the_opponents_turn_is_valid():
    # White's own view right after 1.e4: Black is to move, so White has no moves to list.
    view = snapshot("white", "black")
    assert (view.player, view.side_to_move, view.legal_moves) == ("white", "black", ())


def test_only_the_side_to_move_has_legal_moves():
    with pytest.raises(ValueError):
        snapshot("white", "black", legal_moves=("a2a3",))


def test_side_to_move_must_be_a_colour():
    with pytest.raises(ValueError):
        snapshot("white", "w")


def test_an_agent_is_never_handed_a_view_from_the_opponents_turn():
    belief = Belief("white", 1, (Hypothesis(AFTER_E4, 1.0),))
    with pytest.raises(ValueError):
        AgentInput(snapshot("white", "black"), belief, 1000)
