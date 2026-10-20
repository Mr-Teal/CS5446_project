"""Explicit cut observations, knowledge depth, freezing and solver integration."""

import pytest

from pair_a_prep.knowledge import CutRoot, knowledge_demo, restrict_cut
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import information_sets, payoff_matrix, solve_matrix, Node, terminal


def test_order_two_knowledge_removes_two_hop_and_disconnected_roots():
    roots, blueprint = knowledge_demo()
    cut = restrict_cut(roots, "current", blueprint)
    assert cut.distances == {"A": 0, "B": 1, "C": 2, "D": 3, "E": None}
    assert cut.current == ("A",) and cut.retained == ("A", "B")
    assert cut.removed == ("C", "D", "E")


@pytest.mark.parametrize("mode, expected", [("klss", -0.5), ("kluss", 0.5)])
def test_frozen_unfrozen_values_match_lp_and_preserve_root_group(mode, expected):
    roots, blueprint = knowledge_demo()
    cut = restrict_cut(roots, "current", blueprint, mode)
    assert cut.frozen == (("outside",) if mode == "klss" else ())
    sets = information_sets(cut.roots[1].continuation)
    assert ("outside" in sets[0]) == (mode == "kluss")
    gadget = cut.gadget({"J0": 2.0})  # opponent prefers entering in this example
    assert len([k for k in information_sets(gadget.tree)[1] if '"enter"' in k]) == 1
    assert solve_matrix(payoff_matrix(gadget.tree)[0])["profile_value"] == pytest.approx(expected)
    solver = PCFRPlus(gadget.tree, schedule="alternating")
    solver.run(200)
    metrics = solver.metrics()
    assert metrics["average"]["nash_gap"] < 0.001
    assert metrics["last"]["value"] == pytest.approx(expected, abs=1e-6)
    assert gadget.continuation_values(solver.policy())["B"] == (-1 if mode == "klss" else 1)
    # Original tree was not mutated by converting the frozen policy to chance.
    assert roots[1].continuation.player == 0


def test_freezing_uses_the_supplied_mixed_blueprint():
    roots, _ = knowledge_demo()
    cut = restrict_cut(roots, "current", {"outside": {"bad": .25, "good": .75}}, "klss")
    node = cut.roots[1].continuation
    assert node.player is None and node.probabilities == {"bad": .25, "good": .75}
    assert solve_matrix(payoff_matrix(cut.gadget({"J0": 2}).tree)[0])["profile_value"] == pytest.approx(.25)


def test_current_observation_includes_all_its_roots():
    roots = [CutRoot("a", "I", "J1", terminal(0)), CutRoot("b", "I", "J2", terminal(1)),
             CutRoot("c", "O", "J2", terminal(-1))]
    cut = restrict_cut(roots, "I", {})
    assert cut.current == ("a", "b") and cut.retained == ("a", "b", "c")


def test_bad_blueprint_and_missing_observations_are_rejected():
    roots, _ = knowledge_demo()
    with pytest.raises(ValueError, match="blueprint"):
        restrict_cut(roots, "current", {}, "klss")
    with pytest.raises(ValueError, match="blueprint"):
        restrict_cut(roots, "current", {"outside": {"bad": -1, "good": 2}}, "klss")
    with pytest.raises(ValueError, match="absent"):
        restrict_cut(roots, "missing", {})
    with pytest.raises(ValueError):
        restrict_cut(roots, "current", {}, "unknown")


def test_action_mismatch_is_not_hidden_by_freezing():
    roots, blueprint = knowledge_demo()
    roots.append(CutRoot("B2", "other", "J0", Node(player=0, infoset="outside",
                 children={"different": terminal(0)})))
    with pytest.raises(ValueError, match="inconsistent actions"):
        restrict_cut(roots, "current", blueprint, "klss")


def test_own_infoset_cannot_forget_the_cut_observation():
    def choice():
        return Node(player=0, infoset="forgot", children={"a": terminal(0), "b": terminal(1)})
    roots = [CutRoot("a", "I", "J", choice()), CutRoot("b", "other", "J", choice())]
    with pytest.raises(ValueError, match="forgets"):
        restrict_cut(roots, "I", {})
