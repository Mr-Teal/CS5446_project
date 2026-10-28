import numpy as np
import pytest

from pair_a_prep.toy_games import Node, terminal
from pair_a_prep.zs21.sequence_form import SequenceForm
from pair_a_prep.zs21.sequence_form import SolveError
from pair_a_prep.zs21.gadget import BoundaryError, Gadget, Group, make_subgame, observed_sequence


def leaf(value, ours, theirs):
    node = terminal(value)
    node.observations = (ours, theirs)
    return node


def test_pruned_contributions_and_opponent_information_are_retained():
    roots = []
    for side, payoffs in (("A", (1., -1.)), ("B", (-1., 1.))):
        node = Node(player=1, infoset="reply",
                    children={a: leaf(v, side+a, "opp"+a) for a, v in zip(("L", "R"), payoffs)})
        node.observations = (side, "cut")
        roots.append(node)
    old = SequenceForm(Node(children={"a": roots[0], "b": roots[1]},
                            probabilities={"a": .5, "b": .5})).solve()
    game = make_subgame(old, [roots[0]])
    assert game.groups[0].audit["pruned_terminals"] == 2
    assert game.groups[0].audit["normalization"] == .5
    new = game.form().solve()
    assert new.value == pytest.approx(0.)
    assert new.form.B.nnz == 2


def test_auxiliary_opponent_decisions_can_exist_only_in_b():
    root = leaf(0., "ours", "cut")
    parent = observed_sequence("cut")
    auxiliary = [(1, "in_discarded_branch", parent, ("L", "R"))]
    terms = [(None, ("in_discarded_branch", "L"), 4.),
             (None, ("in_discarded_branch", "R"), -2.)]
    solution = SequenceForm(root, terms, auxiliary).solve()
    assert solution.value == pytest.approx(-2.)
    assert solution.policy(1, "in_discarded_branch")["R"] == 1.


def test_mode_conversion_scales_every_b_entry_and_roundtrips():
    roots = [leaf(.8, "ours", str(i)) for i in range(2)]
    game = Gadget([Group(str(i), [n], [1.], [(observed_sequence(str(i)), -.3)])
                   for i, n in enumerate(roots)])
    first = game.form()
    assert first.solve().value == pytest.approx(.5)
    game.mode = "RESOLVE"
    second = game.form()
    assert second.solve().value == pytest.approx(0.)
    assert sorted(second.B.data) == [-.15, -.15]
    game.mode = "MAXMARGIN"
    third = game.form()
    assert np.array_equal(first.C.toarray(), third.C.toarray())


def test_nonnegative_gift_from_the_same_ancestor_decision():
    good = leaf(-1., "a", "good")
    bad = leaf(.5, "b", "bad")
    root = Node(player=1, infoset="choice", children={"good": good, "bad": bad})
    old = SequenceForm(root).solve()
    game = make_subgame(old, [bad])
    assert game.groups[0].audit["alternate"] == .5
    assert game.groups[0].audit["gift"] == 1.5
    assert game.groups[0].offsets[0][1] == 1.
    assert game.form().solve().value == pytest.approx(1.5)


def test_retained_mass_scales_alternate_and_pruned_payoff_together():
    a, b = leaf(-1., "A", "cut"), leaf(-1., "B", "cut")
    old = SequenceForm(Node(children={"a": a, "b": b}, probabilities={"a": .5, "b": .5})).solve()
    game = make_subgame(old, [a])
    assert game.groups[0].audit["original_alternate"] == -1.
    assert game.groups[0].audit["retained_scale"] == 2.
    assert game.groups[0].audit["alternate"] == -2.
    assert game.form().solve().value == pytest.approx(0.)


def test_zero_counterfactual_reach_fails_without_epsilon_substitution():
    good, bad = leaf(1., "good", "good"), leaf(-1., "bad", "bad")
    root = Node(player=0, infoset="choice", children={"good": good, "bad": bad})
    solution = SequenceForm(root).solve()
    assert solution.policy(0, "choice")["bad"] == 0.
    with pytest.raises(BoundaryError, match="zero counterfactual reach"):
        make_subgame(solution, [bad])


def test_repeated_subgame_construction_does_not_duplicate_prior_b():
    root = leaf(.7, "ours", "cut")
    solution = SequenceForm(root).solve()
    matrices = []
    for _ in range(3):
        game = make_subgame(solution, [root])
        solution = game.form().solve()
        assert solution.value == pytest.approx(0.)
        assert solution.form.B.sum() == pytest.approx(-.7)
        matrices.append(solution.form.C.toarray())
    assert all(np.array_equal(matrices[0], matrix) for matrix in matrices[1:])


def test_initial_completed_lp_survives_incomplete_mode_conversion(monkeypatch):
    root = leaf(-1., "ours", "theirs")
    game = Gadget([Group("theirs", [root], [1.])])
    original = SequenceForm.solve
    calls = []
    def solve(form, deadline=None):
        calls.append(form)
        if len(calls) == 2:
            raise SolveError("injected mode conversion deadline")
        return original(form, deadline)
    monkeypatch.setattr(SequenceForm, "solve", solve)
    result = game.solve(keep_first_on_conversion_failure=True)
    assert result.form is calls[0]
    assert result.value == pytest.approx(-1.)
    assert game.mode == "MAXMARGIN"
    assert game.last_solve_warning == "injected mode conversion deadline"
    assert result.upper - result.lower <= 1e-8
