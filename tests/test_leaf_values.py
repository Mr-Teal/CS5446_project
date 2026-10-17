"""LeafValues: a leaf evaluator's answer for one belief (LeafEvaluator.evaluate_beliefs)."""
import chess
import pytest

from fow_shared.contracts import AgentInput, Belief, Hypothesis, LeafValues, Observation


def two_board_turn():
    first = chess.Board()
    second = first.copy()
    second.remove_piece_at(chess.D8)
    obs = Observation(player="white", ply=0, visible_squares=(), visible_pieces={},
                      legal_moves=("a2a3", "a2a4"), halfmove_clock=0)
    belief = Belief("white", 0, (Hypothesis(first.fen(), 0.5), Hypothesis(second.fen(), 0.5)))
    return AgentInput(obs, belief, 1000)


def test_an_answer_with_one_value_per_board_and_a_full_policy_is_accepted():
    LeafValues((0.1, 0.4), {"a2a3": 0.25, "a2a4": 0.75}).validate_for(two_board_turn())
    LeafValues((0.1, 0.4)).validate_for(two_board_turn())  # the policy is optional


@pytest.mark.parametrize("answer", [
    LeafValues((0.1,)),                                     # one value for two boards
    LeafValues((0.1, 1.5)),                                 # outside [-1, 1]
    LeafValues((0.1, 0.4), {"a2a3": 1.0}),                  # policy misses a legal move
    LeafValues((0.1, 0.4), {"a2a3": 0.5, "a2a4": 0.4}),     # probabilities do not sum to one
    LeafValues((0.1, 0.4), {"a2a3": 1.2, "a2a4": -0.2}),    # negative probability
])
def test_answers_that_do_not_fit_the_belief_are_rejected(answer):
    with pytest.raises(ValueError):
        answer.validate_for(two_board_turn())
