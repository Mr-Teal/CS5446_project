"""Analytic gadget values, hidden roots and raw continuation-value separation."""

import pytest

from pair_a_prep.gadgets import SubgameRoot, build_gadget
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import Node, terminal, information_sets, payoff_matrix, solve_matrix


def oracle(gadget):
    return solve_matrix(payoff_matrix(gadget.tree)[0])["profile_value"]


def shared_action_roots():
    return [SubgameRoot("a", "A", Node(player=0, infoset="decision", children={
        "L": terminal(1), "R": terminal(-1)}), 3),
        SubgameRoot("b", "B", Node(player=0, infoset="decision", children={
        "L": terminal(-1), "R": terminal(1)}), 1)]


@pytest.mark.parametrize("continuation, alternate, expected", [
    (0.4, -0.2, -0.2), (-0.6, -0.2, -0.6), (0.3, 0.3, 0.3)])
def test_resolve_opponent_exits_only_when_it_improves_opponent_payoff(continuation, alternate, expected):
    gadget = build_gadget([SubgameRoot("r", "J", terminal(continuation), 1)], {"J": alternate})
    assert oracle(gadget) == pytest.approx(expected)
    solver = PCFRPlus(gadget.tree, schedule="alternating"); solver.run(50)
    assert solver.metrics()["last"]["value"] == pytest.approx(expected)
    assert gadget.continuation_values(solver.policy()) == {"r": continuation}
    assert gadget.belief_value(solver.policy(), {"r": 1}) == continuation


def test_resolve_exit_decision_cannot_see_hidden_root_identity():
    gadget = build_gadget([SubgameRoot("good", "J", terminal(1), 0.5),
                           SubgameRoot("bad", "J", terminal(-1), 0.5)], {"J": -0.25})
    # One decision shared across both hidden roots: min(E[value]=0, -.25).
    # Illegally revealing the root would give (.5 * -1 + .5 * -.25) = -.625.
    assert len(information_sets(gadget.tree)[1]) == 1
    assert oracle(gadget) == pytest.approx(-0.25)


def test_maxmargin_offsets_and_resolve_are_different_objectives():
    roots = shared_action_roots()
    alternate = {"A": 0.0, "B": 0.4}
    resolve = build_gadget(roots, alternate)
    margin = build_gadget(roots, alternate, mode="maxmargin")
    assert oracle(resolve) == pytest.approx(0)
    # max_p min(2p-1, 1-2p-.4) occurs at p=.4 with margin -.2.
    assert oracle(margin) == pytest.approx(-0.2)
    solver = PCFRPlus(margin.tree, schedule="alternating"); solver.run(1000)
    assert solver.policy(True)[0]["decision"]["L"] == pytest.approx(0.4, abs=0.002)
    assert solver.metrics()["average"]["nash_gap"] < 0.002
    values = margin.continuation_values(solver.policy(True))
    assert values["a"] == pytest.approx(-0.2, abs=0.004)
    assert values["b"] == pytest.approx(0.2, abs=0.004)  # NOT offset to -.2
    assert margin.root_prior is None


def test_nonuniform_resolve_prior_and_label_weights_are_separate():
    gadget = build_gadget(shared_action_roots(), {"A": 0, "B": 0.4},
                          group_prior={"A": 0.25, "B": 0.75})
    assert gadget.root_prior == {"a": 0.25, "b": 0.75}
    assert oracle(gadget) == pytest.approx(0.2)
    solver = PCFRPlus(gadget.tree, schedule="alternating"); solver.run(1000)
    profile = solver.policy(True)
    values = gadget.continuation_values(profile)
    assert gadget.belief_value(profile, {"a": 0.9, "b": 0.1}) == pytest.approx(
        0.9 * values["a"] + 0.1 * values["b"])
    assert profile[0]["decision"]["L"] == pytest.approx(0.3, abs=0.002)
    with pytest.raises(ValueError):
        gadget.belief_value(profile, {"a": 1})


def test_conditional_root_masses_and_input_tree_isolation():
    source = terminal(1)
    roots = [SubgameRoot("a", "J", source, 1), SubgameRoot("b", "J", terminal(-1), 3)]
    gadget = build_gadget(roots, {"J": -0.25})
    assert gadget.root_prior == {"a": 0.25, "b": 0.75}
    assert oracle(gadget) == pytest.approx(-0.5)
    source.payoff = 99
    assert oracle(gadget) == pytest.approx(-0.5)


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_opponent_can_remember_selected_infoset_in_continuation(mode):
    # Same local key is refined by J for the opponent, but not by hidden root.
    def reply():
        return Node(player=1, infoset="reply", children={"x": terminal(1), "y": terminal(-1)})
    gadget = build_gadget([SubgameRoot("a", "A", reply(), 1), SubgameRoot("b", "B", reply(), 1)],
                          {"A": 0, "B": 0}, mode=mode)
    solver = PCFRPlus(gadget.tree, schedule="alternating"); solver.run(50)
    assert oracle(gadget) == pytest.approx(-1)
    assert gadget.continuation_values(solver.policy()) == {"a": -1, "b": -1}


def test_linear_nash_gap_matches_the_pure_strategy_oracle():
    from pair_a_prep.toy_games import behavioral_nash_gap, hidden_coin, kuhn_poker, matching_pennies, nash_gap
    games = [matching_pennies(), hidden_coin(), kuhn_poker(),
             build_gadget(shared_action_roots(), {"A": 0, "B": 0.4}).tree,
             build_gadget(shared_action_roots(), {"A": 0, "B": 0.4}, mode="maxmargin").tree]
    for root in games:
        solver = PCFRPlus(root, schedule="alternating")
        for rounds in (0, 3, 40):
            solver.run(rounds)
            for average in (False, True):
                policy = solver.policy(average)
                assert nash_gap(root, policy) == pytest.approx(behavioral_nash_gap(root, policy), abs=1e-12)
        assert nash_gap(root, solver.policy(True)) >= -1e-12


def test_blended_gadget_conserves_mass_and_its_mode_follows_p_max():
    from pair_a_prep.subgame_boundaries import BlendedGadgetControl
    roots, alpha = shared_action_roots(), {"A": .5, "B": .5}
    # Alternates far below every continuation: Resolve's opponent always exits,
    # p_max reaches exactly zero and the root follows the Maxmargin selector.
    safe = build_gadget(roots, {"A": -5., "B": -5.}, mode="blended", group_prior=alpha)
    control = BlendedGadgetControl(safe, alpha)
    solver = PCFRPlus(safe.tree, schedule="alternating")
    for _ in range(40):
        solver.step()
        margins = control.update(safe, solver.policy())
        assert sum(safe.tree.probabilities.values()) == pytest.approx(1)
        assert 0 <= control.p_max <= 1
    assert control.mode == "maxmargin" and control.p_max == 0
    assert safe.tree.probabilities["exit:A"] == 0 == safe.tree.probabilities["exit:B"]
    assert min(margins.values()) > 0
    # An infeasible alternate at A: Resolve enters there with certainty, so
    # p_max is one; B still exits, and its Resolve mass alpha_B lands on exit:B.
    unsafe = build_gadget(roots, {"A": 2.5, "B": -5.}, mode="blended", group_prior=alpha)
    control = BlendedGadgetControl(unsafe, alpha)
    solver = PCFRPlus(unsafe.tree, schedule="alternating")
    for _ in range(40):
        solver.step()
        control.update(unsafe, solver.policy())
    assert control.mode == "resolve" and control.p_max == pytest.approx(1)
    assert unsafe.tree.probabilities["exit:A"] == pytest.approx(0)
    assert unsafe.tree.probabilities["exit:B"] == pytest.approx(.5)
    assert sum(unsafe.tree.probabilities.values()) == pytest.approx(1)
    # The continuation layer is the shared tree: same player infosets as Maxmargin.
    reference = build_gadget(roots, {"A": 2.5, "B": -5.}, mode="maxmargin")
    assert information_sets(unsafe.tree)[0] == information_sets(reference.tree)[0]
    with pytest.raises(ValueError):
        BlendedGadgetControl(reference, alpha)


def test_invalid_gadget_configuration():
    r = SubgameRoot("r", "J", terminal(0), 1)
    for roots, alt, kwargs in [([], {}, {}), ([r, r], {"J": 0}, {}),
                              ([r], {}, {}), ([r], {"J": float("nan")}, {}),
                              ([r], {"J": 0}, {"group_prior": {"J": 0.5}}),
                              ([r], {"J": 0}, {"mode": "maxmargin", "group_prior": {"J": 1}}),
                              ([SubgameRoot("r", "J", terminal(0), 0)], {"J": 0}, {})]:
        with pytest.raises(ValueError):
            build_gadget(roots, alt, **kwargs)
