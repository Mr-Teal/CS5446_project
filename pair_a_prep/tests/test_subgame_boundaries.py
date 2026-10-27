"""Independent finite-tree arithmetic for C.2/C.3 and compatible warm starts."""

from copy import deepcopy

import numpy as np
import pytest

from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.subgame_boundaries import (
    BoundaryRoot, BoundarySession, derive_boundaries, choose_mode, current_minimum_margin)
from pair_a_prep.toy_games import Node, terminal, payoff_matrix, solve_matrix
from pair_a_prep.warm_start import rebase_solver


def fixture(probability=0.25):
    root = Node(player=1, infoset="opponent", children={
        "mistake": Node(player=0, infoset="own-A", children={"x": terminal(1), "y": terminal(0)}),
        "safe": Node(player=0, infoset="own-B", children={"x": terminal(-1), "y": terminal(0)}),
    })
    profile = ({"own-A": {"x": 1.0, "y": 0.0}, "own-B": {"x": 1.0, "y": 0.0}},
               {"opponent": {"mistake": probability, "safe": 1-probability}})
    cut = (BoundaryRoot("A", ("mistake",), "JA"), BoundaryRoot("B", ("safe",), "JB"))
    return root, profile, cut


def test_current_profile_gifts_and_mixed_opponent_prior():
    root, profile, cut = fixture()
    boundaries = derive_boundaries(root, profile, cut)
    # Blueprint root value is -.5. Positive gift at mistake is 1 - (-.5).
    assert boundaries.gifts == pytest.approx({"JA": 1.5, "JB": 0})
    assert boundaries.alternate_player0 == pytest.approx({"JA": 2.5, "JB": -1})
    assert boundaries.group_prior == pytest.approx({"JA": 0.375, "JB": 0.625})
    assert [r.reach_mass for r in boundaries.roots] == [1, 1]


def test_conditional_boundary_uses_chance_and_player_zero_reach():
    decision = lambda value: Node(player=0, infoset="own", children={"a": terminal(value), "b": terminal(0)})
    root = Node(children={"a": decision(1), "b": decision(-1)}, probabilities={"a": .8, "b": .2})
    boundaries = derive_boundaries(root, ({"own": {"a": 1., "b": 0.}}, {}), (
        BoundaryRoot("a", ("a",), "J"), BoundaryRoot("b", ("b",), "J")))
    assert boundaries.alternate_player0["J"] == pytest.approx(.6)
    assert [r.reach_mass for r in boundaries.roots] == [.8, .2]
    assert boundaries.group_prior == {"J": 1}


def test_zero_opponent_reach_is_explicit_and_prior_stays_positive():
    root, profile, cut = fixture(0)
    boundaries = derive_boundaries(root, profile, cut)
    assert boundaries.audit["groups"]["JA"]["zero_joint_fallback"]
    assert boundaries.group_prior == {"JA": .25, "JB": .75}


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_derived_gadgets_have_finite_lp_oracles_and_unshifted_continuations(mode):
    root, profile, cut = fixture()
    gadget = derive_boundaries(root, profile, cut).gadget(mode)
    value = solve_matrix(payoff_matrix(gadget.tree)[0])["profile_value"]
    assert np.isfinite(value)
    solver = PCFRPlus(gadget.tree, schedule="alternating")
    solver.run(100)
    assert gadget.continuation_values(solver.policy())["A"] <= 1
    assert current_minimum_margin(gadget, solver.policy()) <= -1.5 + 1e-8
    assert choose_mode(current_minimum_margin(gadget, solver.policy())) == "resolve"


@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_rebase_preserves_compatible_state_and_old_solver_is_independent(schedule):
    root, _, _ = fixture()
    old = PCFRPlus(root, schedule=schedule)
    old.run(3)
    before = deepcopy(old.policy())
    changed = deepcopy(root)
    changed.children["safe"].infoset = "new-own"
    new, retained = rebase_solver(old, changed)
    assert retained[0] == ("own-A",)
    assert new.rounds == 3
    np.testing.assert_array_equal(new.minimizers[0]["own-A"].regrets, old.minimizers[0]["own-A"].regrets)
    assert new.minimizers[0]["own-A"] is not old.minimizers[0]["own-A"]
    new.run(2)
    assert old.rounds == 3 and old.policy() == before


def test_cut_and_mode_validation():
    root, profile, cut = fixture()
    with pytest.raises(ValueError, match="antichain"):
        derive_boundaries(root, profile, (cut[0], BoundaryRoot("z", (), "J")))
    assert choose_mode(0) == "maxmargin"
    assert choose_mode(-.1) == "resolve"


def test_mode_session_switches_without_discarding_continuation_state():
    root, profile, cut = fixture()
    session = BoundarySession(derive_boundaries(root, profile, cut))
    for _ in range(6):
        session.step()
    assert session.mode == "resolve"
    assert session.solver.rounds == 6
    assert session.transitions[0]["retained"][0] == 2
