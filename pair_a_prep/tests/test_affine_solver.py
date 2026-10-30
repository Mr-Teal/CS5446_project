"""Warm continuation against scratch training in an affine-equivalent game."""

from copy import deepcopy

import numpy as np
import pytest

from pair_a_prep.affine_solver import certify_affine_game, transport_affine_solver
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import Node, terminal


def game():
    return Node(player=0, infoset="I", children={
        "a": Node(player=1, infoset="J", children={"x": terminal(.75), "y": terminal(-.5)}),
        "b": Node(player=1, infoset="J", children={"x": terminal(-.25), "y": terminal(1.)})})


def transformed(root, scale=4., offset=.125):
    root = deepcopy(root)
    def visit(node):
        if node.payoff is not None:
            node.payoff = scale*node.payoff+offset
        else:
            for child in node.children.values():
                visit(child)
    visit(root)
    return root


def assert_same_policies(a, b):
    for average in (False, True):
        for p in (0, 1):
            for key, values in a.policy(average)[p].items():
                assert values == pytest.approx(b.policy(average)[p][key], abs=1e-9)


@pytest.mark.parametrize("scale,offset", [(4., .125), (.25, -.3)])
@pytest.mark.parametrize("partial_chance", [False, True])
@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
@pytest.mark.parametrize("predictive", [False, True])
@pytest.mark.parametrize("averaging_power", [0, 2])
def test_scaled_warm_state_matches_full_target_training(schedule, predictive, averaging_power, partial_chance, scale, offset):
    source = game()
    if partial_chance:
        source = Node(children={"play": source, "outside": terminal(.125)},
                      probabilities={"play": .25, "outside": .75})
    target = transformed(source, scale, offset)
    old = PCFRPlus(source, schedule=schedule, predictive=predictive, averaging_power=averaging_power)
    scratch = PCFRPlus(target, schedule=schedule, predictive=predictive, averaging_power=averaging_power)
    old.run(7)
    scratch.run(7)
    source_policy = deepcopy(old.policy())
    warm, certificate = transport_affine_solver(old, target)
    assert certificate.scale == pytest.approx(scale)
    assert certificate.offset == pytest.approx(offset)
    assert_same_policies(warm, scratch)
    for p in (0, 1):
        for key, item in warm.minimizers[p].items():
            assert item is not old.minimizers[p][key]
            assert item._pending == old.minimizers[p][key]._pending
            np.testing.assert_allclose(item.regrets, scratch.minimizers[p][key].regrets, atol=1e-10)
            expected = scratch.minimizers[p][key].previous_utility
            np.testing.assert_allclose(item.previous_utility-item.previous_utility.mean(),
                                       expected-expected.mean(), atol=1e-10)
            np.testing.assert_allclose(warm._sums[p][key], scratch._sums[p][key], atol=1e-10)
    for _ in range(8):
        warm.step()
        scratch.step()
        assert_same_policies(warm, scratch)
    assert old.rounds == 7 and old.policy() == source_policy


@pytest.mark.parametrize("change", ["negative", "one_leaf", "infoset", "action_order", "chance", "cutoff"])
def test_non_affine_or_structural_changes_are_rejected(change):
    source = game()
    target = transformed(source)
    if change == "negative":
        target = transformed(source, -1., 0.)
    elif change == "one_leaf":
        target.children["a"].children["x"].payoff += .1
    elif change == "infoset":
        target.infoset = "new-I"
    elif change == "action_order":
        target.children = dict(reversed(list(target.children.items())))
    elif change == "chance":
        source = Node(children={"left": source, "right": terminal(.2)}, probabilities={"left": .25, "right": .75})
        target = transformed(source)
        target.probabilities = {"left": .5, "right": .5}
    else:
        target.children["a"].children["x"].cutoff = True
    with pytest.raises(ValueError):
        transport_affine_solver(PCFRPlus(source), target)


def test_constant_game_and_initial_seed_pending_state_are_supported():
    source = Node(player=0, infoset="I", children={"a": terminal(.5), "b": terminal(.5)})
    solver = PCFRPlus(source, initial_actions={(0, "I"): "b"})
    warm, mapping = transport_affine_solver(solver, transformed(source, 1., -.25))
    assert mapping.scale == 1. and mapping.offset == -.25
    assert warm._initial_actions == {(0, "I"): "b"}
    warm.step()
    assert warm.policy()[0]["I"] == {"a": 0., "b": 1.}


def test_coordinate_equivalence_does_not_authorize_resolve_to_maxmargin_state_copy():
    from pair_a_prep.gadgets import SubgameRoot, build_gadget
    from pair_a_prep.gadget_frames import certify_gadget_frames
    roots = [SubgameRoot("root", "J", game(), 3.)]
    resolve = build_gadget(roots, {"J": .2}, "resolve")
    margin = build_gadget(roots, {"J": .2}, "maxmargin")
    assert certify_gadget_frames(resolve, margin).group_masses == {"J": 3.}
    with pytest.raises(ValueError, match="identical topology"):
        transport_affine_solver(PCFRPlus(resolve.tree), margin.tree)


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
@pytest.mark.parametrize("schedule", ["simultaneous", "alternating"])
def test_affine_warm_continuation_on_actual_multigroup_gadget(mode, schedule):
    from pair_a_prep.gadgets import SubgameRoot, build_gadget
    roots = [SubgameRoot("A", "A", game(), 1.),
             SubgameRoot("B", "B", transformed(game(), .5, -.25), 3.)]
    original = build_gadget(roots, {"A": .125, "B": -.25}, mode).tree
    target = transformed(original)
    old, scratch = PCFRPlus(original, schedule=schedule), PCFRPlus(target, schedule=schedule)
    old.run(5)
    scratch.run(5)
    warm, mapping = transport_affine_solver(old, target)
    for p in (0, 1):
        for key in warm.sets[p]:
            np.testing.assert_allclose(warm.minimizers[p][key].regrets,
                                       scratch.minimizers[p][key].regrets, atol=1e-9)
    for _ in range(8):
        warm.step()
        scratch.step()
        assert_same_policies(warm, scratch)
    assert old.rounds == 5
