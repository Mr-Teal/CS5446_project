"""Reach-weighted continuation arithmetic against actual constructed gadgets."""

from copy import deepcopy
from dataclasses import replace

import pytest

from pair_a_prep.gadgets import SubgameRoot, build_gadget
from pair_a_prep.gadget_frames import certify_gadget_frames
from pair_a_prep.value_frames import transport_value
from pair_a_prep.toy_games import Node, terminal, behavioral_value
from pair_a_prep.pcfr import PCFRPlus


def fixture():
    # Hidden roots share our infoset, with nonuniform mass within each group.
    values = (("a1", "A", 1., .8), ("a2", "A", 3., -.4), ("b", "B", 2., .2))
    roots = tuple(SubgameRoot(name, group, Node(player=0, infoset="I", children={
        "L": terminal(value), "R": terminal(-value)}), mass)
        for name, group, mass, value in values)
    alternates = {"A": .15, "B": -.25}
    return roots, build_gadget(roots, alternates, "resolve", {"A": .8, "B": .2}), build_gadget(roots, alternates, "maxmargin")


def test_actual_cf_mass_and_maxmargin_offset_determine_frames():
    roots, resolve, margin = fixture()
    certificate = certify_gadget_frames(resolve, margin)
    assert certificate.group_masses == {"A": 4., "B": 2.}
    assert certificate.source["A"].scale == 4.
    assert certificate.source["A"].offset == 0.
    assert certificate.target["A"].offset == pytest.approx(.6)
    assert certificate.target["B"].offset == pytest.approx(-.5)
    # Evaluate actual shifted Maxmargin branches, independently of frame arithmetic.
    for left_probability in (.1, .5, .9):
        for group, mass in certificate.group_masses.items():
            conditional_raw = sum(r.reach_mass*(left_probability*r.continuation.children["L"].payoff+
                (1-left_probability)*r.continuation.children["R"].payoff) for r in roots
                if r.opponent_infoset == group)/mass
            branch = margin.tree.children[group]
            local = behavioral_value(branch, ({"I": {"L": left_probability, "R": 1-left_probability}}, {}))
            converted = transport_value(conditional_raw, certificate.source[group], certificate.target[group])
            assert converted == pytest.approx(local)
            assert certificate.target[group].scale*local+certificate.target[group].offset == pytest.approx(mass*conditional_raw)


@pytest.mark.parametrize("change", ["mass", "history", "payoff", "group", "order"])
def test_changed_sample_or_cf_weights_do_not_get_a_free_unit_correspondence(change):
    roots, source, _ = fixture()
    changed = list(deepcopy(roots))
    if change == "mass":
        changed[0] = replace(changed[0], reach_mass=2.)
    elif change == "history":
        changed[0] = replace(changed[0], root_id="different-private-history")
    elif change == "payoff":
        changed[0].continuation.children["L"].payoff += .1
    elif change == "group":
        changed[0] = replace(changed[0], opponent_infoset="B")
    else:
        changed.reverse()
    target = build_gadget(changed, {"A": .15, "B": -.25}, "maxmargin")
    with pytest.raises(ValueError, match="matching raw roots"):
        certify_gadget_frames(source, target)


def test_mutated_gadget_tree_cannot_be_certified_from_stale_metadata():
    _, source, target = fixture()
    target.tree.children["A"].children["a1"].children["L"].payoff += .1
    with pytest.raises(ValueError, match="declared construction"):
        certify_gadget_frames(source, target)


def test_valid_fractional_root_prior_survives_reconstruction_roundoff():
    roots = [SubgameRoot(str(i), "A", terminal(.2), m) for i, m in enumerate((.1, .2, .4))]
    roots.append(SubgameRoot("b", "B", terminal(.3), 1.))
    source = build_gadget(roots, {"A": 0., "B": 0.}, "resolve", {"A": .3, "B": .7})
    target = build_gadget(roots, {"A": 0., "B": 0.}, "maxmargin")
    certificate = certify_gadget_frames(source, target)
    assert certificate.group_masses["A"] == pytest.approx(.7)
