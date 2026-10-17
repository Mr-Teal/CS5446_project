import numpy as np
import pytest

from pair_a_prep.toy_games import (
    behavioral_nash_gap, hidden_coin, information_sets, kuhn_poker,
    matching_pennies, payoff_matrix, security_bounds, solve_matrix,
)


def test_information_set_constraint_changes_the_game_value():
    hidden, _, _ = payoff_matrix(matching_pennies())
    revealed, _, _ = payoff_matrix(matching_pennies(True))
    assert hidden.shape == (2, 2)
    assert revealed.shape == (2, 4)
    assert solve_matrix(hidden)["profile_value"] == pytest.approx(0)
    assert solve_matrix(revealed)["profile_value"] == pytest.approx(-1)


def test_biased_matrix_has_known_nonuniform_strategy():
    answer = solve_matrix(np.array([[2, -1], [-2, 3]]))
    assert answer["row_strategy"] == pytest.approx([5 / 8, 3 / 8])
    assert answer["column_strategy"] == pytest.approx([1 / 2, 1 / 2])
    assert answer["profile_value"] == pytest.approx(1 / 2)
    assert answer["nash_gap"] < 1e-9


@pytest.mark.parametrize("reveal, expected", [(False, 0.5), (True, 1.0)])
def test_chance_weighting_and_private_information(reveal, expected):
    matrix, _, _ = payoff_matrix(hidden_coin(reveal))
    assert solve_matrix(matrix)["profile_value"] == pytest.approx(expected)


def test_kuhn_oracle_has_known_value_with_private_card_information_sets():
    root = kuhn_poker()
    assert [len(s) for s in information_sets(root)] == [6, 6]
    matrix, _, _ = payoff_matrix(root)
    assert matrix.shape == (64, 64)
    answer = solve_matrix(matrix)
    assert answer["profile_value"] == pytest.approx(-1 / 18, abs=1e-9)
    assert answer["nash_gap"] < 1e-9


def test_behavioral_best_response_detects_predictable_strategy():
    root = matching_pennies()
    uniform = ({"p0": {"H": 0.5, "T": 0.5}},
               {"p1_hidden": {"H": 0.5, "T": 0.5}})
    pure = ({"p0": {"H": 1.0, "T": 0.0}},
            {"p1_hidden": {"H": 1.0, "T": 0.0}})
    assert behavioral_nash_gap(root, uniform) == pytest.approx(0)
    assert behavioral_nash_gap(root, pure) == pytest.approx(2)


def test_oracle_rejects_bad_strategies_and_large_normal_forms():
    with pytest.raises(ValueError, match="sum"):
        security_bounds(np.eye(2), [0.1, 0.1], [0.5, 0.5])
    with pytest.raises(ValueError, match="small"):
        payoff_matrix(kuhn_poker(), max_profiles=100)
