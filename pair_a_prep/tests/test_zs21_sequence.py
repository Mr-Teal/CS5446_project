import numpy as np
import pytest
import gc
import weakref

from pair_a_prep.toy_games import (matching_pennies, hidden_coin, kuhn_poker,
                                   behavioral_nash_gap, payoff_matrix, solve_matrix, Node, terminal)
from pair_a_prep.zs21.sequence_form import SequenceForm


@pytest.mark.parametrize("game", [matching_pennies(), matching_pennies(True),
                                 hidden_coin(), hidden_coin(True), kuhn_poker()])
def test_sparse_solver_against_independent_normal_form(game):
    form = SequenceForm(game)
    answer = form.solve()
    oracle = solve_matrix(payoff_matrix(game)[0])
    assert answer.value == pytest.approx(oracle["profile_value"], abs=1e-9)
    assert behavioral_nash_gap(game, answer.profile()) < 1e-8
    values, _ = form.counterfactual(answer.x)
    assert values[0] == pytest.approx(answer.lower, abs=1e-9)


def test_additive_b_changes_payoff_and_strategy_without_changing_a():
    root = matching_pennies()
    original = SequenceForm(root)
    form = SequenceForm(root, [(('p0', 'H'), None, -0.5)])
    assert np.allclose(original.A.toarray(), form.A.toarray())
    answer = form.solve()
    assert answer.value == pytest.approx(-0.25)
    assert answer.policy(1, 'p1_hidden')['H'] == pytest.approx(0.625)


def test_observations_do_not_reveal_hidden_nodes():
    root = hidden_coin()
    for child in root.children.values():
        child.observations = ("same-own-view", "same-opponent-view")
    answer = SequenceForm(root).solve()
    assert answer.value == pytest.approx(0.5)
    assert answer.policy(0, 'guess_hidden') == {'H': 1.0, 'T': 0.0}


def test_imperfect_recall_is_rejected():
    shared = lambda: Node(player=0, infoset='forgot', children={'x': terminal(0), 'y': terminal(1)})
    root = Node(player=0, infoset='first', children={'a': shared(), 'b': shared()})
    with pytest.raises(ValueError, match="imperfect recall"):
        SequenceForm(root)


@pytest.mark.parametrize("game", [matching_pennies(), hidden_coin(), kuhn_poker()])
def test_forced_flow_elimination_matches_unreduced_game(game):
    # Use independent full histories; this fixture intentionally has perfect information.
    def full_history(node, path="root"):
        node.observations = (path, path)
        if node.player is not None:
            node.infoset = (node.infoset, path)
        for action, child in node.children.items():
            full_history(child, path + "/" + action)
    full_history(game)
    form = SequenceForm(game)
    compact = form.solve()
    shape = form.solved_shape
    original = form.solve(eliminate_forced=False)
    assert compact.value == pytest.approx(original.value, abs=1e-9)
    assert sum(shape) < sum(form.C.shape)
    assert compact.flow_error < 1e-8
    assert compact.upper - compact.lower < 1e-8


def test_forced_flow_elimination_includes_b_and_auxiliary_sequences():
    root = Node(player=0, infoset="ours", children={"a": terminal(1.), "b": terminal(-1.)})
    for name, child in root.children.items():
        child.observations = (name, name)
    cut = (("observe", "a"), "seen")
    auxiliary = [(1, "discarded_forced", cut, ("only",))]
    form = SequenceForm(root, [(None, ("discarded_forced", "only"), -.4)], auxiliary)
    compact, original = form.solve(), form.solve(eliminate_forced=False)
    assert compact.value == pytest.approx(original.value, abs=1e-9)
    assert compact.value == pytest.approx(.6)
    assert compact.inequality_error < 1e-8


def test_old_form_is_released_without_waiting_for_cyclic_gc():
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        form = SequenceForm(matching_pennies())
        reference = weakref.ref(form)
        del form
        assert reference() is None
    finally:
        if was_enabled:
            gc.enable()
