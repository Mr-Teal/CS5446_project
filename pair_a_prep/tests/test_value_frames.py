"""Independent arithmetic and normal-form oracle for explicit payoff transport."""

import numpy as np
import pytest

from pair_a_prep.value_frames import (ValueFrame, transport_value, transport_delta,
    transport_resolve_prior, margin_in_source_units)
from pair_a_prep.gadgets import SubgameRoot, build_gadget
from pair_a_prep.toy_games import Node, terminal, payoff_matrix, solve_matrix


def resolve_fixture():
    old = {"A": ValueFrame("common"), "B": ValueFrame("common")}
    new = {"A": ValueFrame("common", 2., .3), "B": ValueFrame("common", .25, -.1)}
    values = {"A": {"a": 1., "b": -.5}, "B": {"a": -.25, "b": .75}}
    alternates, prior = {"A": .2, "B": .1}, {"A": .7, "B": .3}
    roots = lambda table: [SubgameRoot(group, group,
        Node(player=0, infoset="shared-own", children={a: terminal(v) for a, v in row.items()}), 1.)
        for group, row in table.items()]
    source = build_gadget(roots(values), alternates, "resolve", prior)
    transformed = {g: {a: transport_value(v, old[g], new[g]) for a, v in row.items()}
                   for g, row in values.items()}
    transported = transport_resolve_prior(prior, old, new)
    target = build_gadget(roots(transformed),
        {g: transport_value(v, old[g], new[g]) for g, v in alternates.items()},
        "resolve", transported.prior)
    return source, target, transported


def test_scalar_roundtrip_and_margin_preserve_common_units():
    old, new = ValueFrame("common", 3., -.2), ValueFrame("common", .5, .4)
    for value in (-1., 0., .8):
        converted = transport_value(value, old, new)
        assert new.scale*converted+new.offset == pytest.approx(old.scale*value+old.offset)
        assert transport_value(converted, new, old) == pytest.approx(value)
    value, alternate = transport_value(.8, old, new), transport_value(.1, old, new)
    assert margin_in_source_units(value, alternate, old, new) == pytest.approx(.7)
    assert transport_delta(.3, old, new) == pytest.approx(1.8)


def test_resolve_matrix_and_lp_value_are_affine_equivalent():
    old, new, conversion = resolve_fixture()
    old_matrix, new_matrix = payoff_matrix(old.tree)[0], payoff_matrix(new.tree)[0]
    np.testing.assert_allclose(old_matrix, conversion.scale*new_matrix+conversion.offset)
    assert conversion.prior == pytest.approx({"A": 1.4/1.475, "B": .075/1.475})
    assert conversion.scale == pytest.approx(1.475)
    assert conversion.offset == pytest.approx(.18)
    old_value, new_value = solve_matrix(old_matrix)["profile_value"], solve_matrix(new_matrix)["profile_value"]
    assert conversion.source_expected_value(new_value) == pytest.approx(old_value)
    # Keeping the old prior under different per-group scales changes the game.
    assert conversion.prior != {"A": .7, "B": .3}


def test_unweighted_maxmargin_selector_can_flip_under_group_rescaling():
    source = ValueFrame("common")
    frames = {"A": ValueFrame("common", .1), "B": ValueFrame("common", 1.)}
    original = {"A": .2, "B": .3}
    local = {g: transport_delta(v, source, frames[g]) for g, v in original.items()}
    assert min(original, key=original.get) == "A"
    assert min(local, key=local.get) == "B"
    corrected = {g: margin_in_source_units(v, 0., source, frames[g]) for g, v in local.items()}
    assert corrected == pytest.approx(original)
    assert min(corrected, key=corrected.get) == "A"


@pytest.mark.parametrize("scale,offset", [(0, 0), (-1, 0), (float("inf"), 0), (1, float("nan"))])
def test_invalid_frames_are_rejected(scale, offset):
    with pytest.raises(ValueError):
        ValueFrame("common", scale, offset)


def test_unknown_units_and_invalid_priors_are_not_guessed():
    with pytest.raises(ValueError, match="common units"):
        transport_value(.3, ValueFrame("old-unproven"), ValueFrame("new-unproven"))
    with pytest.raises(ValueError, match="sum to one"):
        transport_resolve_prior({"A": .5}, {"A": ValueFrame("u")}, {"A": ValueFrame("u")})
    with pytest.raises(ValueError):
        transport_value(float("inf"), ValueFrame("u"), ValueFrame("u"))


def test_maxmargin_lp_needs_scaled_rows_not_only_transferred_alternates():
    roots = lambda values: [SubgameRoot(g, g, terminal(v), 1.) for g, v in values.items()]
    alternates = {"A": 0., "B": 0.}
    source = build_gadget(roots({"A": .2, "B": .3}), alternates, "maxmargin")
    local = build_gadget(roots({"A": 2., "B": .3}), alternates, "maxmargin")
    corrected = build_gadget(roots({"A": .1*2., "B": 1.*.3}), alternates, "maxmargin")
    value = lambda gadget: solve_matrix(payoff_matrix(gadget.tree)[0])["profile_value"]
    assert value(source) == pytest.approx(.2)
    assert value(local) == pytest.approx(.3)
    assert value(corrected) == pytest.approx(.2)
