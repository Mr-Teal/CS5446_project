"""Dynamic shared-infoset responses against independent pure-policy enumeration."""

import numpy as np
import pytest

from pair_a_prep.finite_security import finite_security
from pair_a_prep.toy_games import (matching_pennies, hidden_coin, kuhn_poker, information_sets,
    behavioral_nash_gap, Node, terminal)
from pair_a_prep.gadgets import build_gadget, SubgameRoot


@pytest.mark.parametrize("builder", [matching_pennies, hidden_coin, kuhn_poker])
@pytest.mark.parametrize("seed", [17, 29, 41])
def test_finite_bounds_match_enumerated_pure_responses(builder, seed):
    root = builder()
    rng = np.random.default_rng(seed)
    profile = []
    for sets in information_sets(root):
        player = {}
        for key, actions in sets.items():
            weights = rng.random(len(actions))
            player[key] = dict(zip(actions, weights/weights.sum()))
        profile.append(player)
    metrics = finite_security(root, profile)
    assert metrics["finite_gap"] == pytest.approx(behavioral_nash_gap(root, profile), abs=1e-10)


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_gadget_bounds_and_zero_reach_branches(mode):
    roots = [SubgameRoot("a", "A", matching_pennies(), 1.),
             SubgameRoot("b", "B", matching_pennies(), 3.)]
    root = build_gadget(roots, {"A": .2, "B": -.1}, mode).tree
    profile = tuple({key: {a: float(i == 0) for i, a in enumerate(actions)} for key, actions in sets.items()}
                    for sets in information_sets(root))
    assert finite_security(root, profile)["finite_gap"] == pytest.approx(behavioral_nash_gap(root, profile))
    unreachable = Node(children={"off": root, "on": terminal(.37)}, probabilities={"off": 0., "on": 1.})
    assert finite_security(unreachable, profile)["finite_gap"] == pytest.approx(0.)
