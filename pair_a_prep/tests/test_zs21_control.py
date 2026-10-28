from dataclasses import replace
from collections import Counter
from math import log2
from types import SimpleNamespace
from time import perf_counter

import numpy as np
import pytest

from pair_a_prep.toy_games import Node, terminal
from pair_a_prep.zs21.agent import PaperAgent, select_expansions
from pair_a_prep.zs21.gadget import observed_sequence, Gadget
from pair_a_prep.zs21.sequence_form import SequenceForm, SolveError
from pair_a_prep.zs21.validation import report, realization
from pair_a_prep.zs21.model import Referee
from pair_a_prep.tests.test_zs21_agent import FixedEvaluator


def test_paper_examples_and_exploitability_counterexample():
    report()


def test_continuation_value_includes_downstream_b_and_excludes_past_payment():
    leaf = terminal(1.)
    leaf.observations = ("new", "cut")
    root = Node(player=0, infoset="move", children={"a": leaf})
    root.observations = ("old", "old_other")
    form = SequenceForm(root, [(None, observed_sequence("cut"), 2.),
                               (None, observed_sequence("old_other"), 99.)])
    agent = PaperAgent("white", 1, FixedEvaluator())
    agent.snapshot = form.solve()
    assert agent._old_conditional_value([leaf]) == (3., "joint_reach")
    agent.close()


def test_opponent_zero_policy_does_not_mean_zero_counterfactual_reach():
    a, b = terminal(-1.), terminal(1.)
    a.observations, b.observations = ("a", "a"), ("b", "b")
    form = SequenceForm(Node(player=1, infoset="choice", children={"a": a, "b": b}),
                        [(None, observed_sequence("b"), 2.)])
    agent = PaperAgent("white", 2, FixedEvaluator())
    agent.snapshot = form.solve()
    value, boundary = agent._old_conditional_value([b])
    assert value == 3. and boundary == "counterfactual_reach_zero_joint_boundary"
    agent.close()


def test_parent_first_support_gate_and_literal_stall():
    children = {}
    for i in range(3):
        child = terminal(float(i))
        child.cutoff, child.forcing, child.base = True, i==2, float(i)
        child.state = SimpleNamespace(ply=5)
        children[str(i)] = child
    root = Node(player=0, infoset="choice", children=children)
    form = SequenceForm(root)
    answer = form.solve()
    x, y = answer.x.copy(), answer.y.copy()
    x[form.nodes[id(root)][0][0]] = .5
    for i, child in enumerate(children.values()):
        x[form.nodes[id(child)][0][0]] = (0., .5, 0.)[i]
    # Parent both supported: one-sided child still waits at depth 5 > gate 1.
    y[0] = .5
    selected, _ = select_expansions(replace(answer,x=x,y=y), [root], 0, 1)
    assert selected == [children["1"]]
    y[0] = 0.
    selected, _ = select_expansions(replace(answer,x=x,y=y), [root], 0, 10)
    assert selected == []  # Most interesting is unsupported; no second choice.


@pytest.mark.parametrize("threshold,expected", [(1e-7,False),(1e-9,False),(1e-11,True)])
def test_support_threshold_changes_only_expansion_mask(threshold, expected):
    leaf = terminal(1.)
    leaf.cutoff, leaf.forcing, leaf.base, leaf.state = True, False, 1., SimpleNamespace(ply=1)
    root = Node(player=0, infoset="move", children={"a": leaf})
    answer = SequenceForm(root).solve()
    x, y = answer.x.copy(), answer.y.copy()
    x[:] = 1e-9
    y[:] = 0.
    selected, _ = select_expansions(replace(answer,x=x,y=y), [root], 0, 1, threshold)
    assert bool(selected) == expected
    assert np.array_equal(x, np.full_like(x, 1e-9))


def test_incomplete_expansion_rolls_back_to_current_valid_tree(monkeypatch):
    referee = Referee()
    agent = PaperAgent("white", 42, FixedEvaluator(), max_rounds=1)
    agent.observe(referee.observe("white"))
    original = Gadget.solve
    calls = 0
    def failing(game, deadline, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SolveError("injected interrupted expanded LP")
        return original(game, deadline, **kwargs)
    monkeypatch.setattr(Gadget, "solve", failing)
    result = agent.act(perf_counter()+30)
    assert result.diagnostics["rounds"] == 0
    assert agent.trace["max_fow_depth"] == 1
    assert "injected" in agent.trace["stop_reason"]
    assert agent.snapshot.form.C.shape == agent.gadget.form().C.shape
    result.validate_for(referee.observe("white"))
    agent.close()


def test_entropy_uses_uniform_sample_but_penalty_uses_full_population_and_same_m():
    referee = Referee()
    agents = [PaperAgent("black", 113, FixedEvaluator(), scale=scale, particle_floor=7, max_rounds=0)
              for scale in (1.,6.)]
    try:
        for agent in agents:
            agent.observe(referee.observe("black"))
        referee.apply("e2e4")
        games = []
        for agent in agents:
            agent.observe(referee.observe("black"))
            game = agent._build(perf_counter()+30)
            assert len(game.roots) == 7 and len(agent.tracker.candidates) == 20
            for (sequence, _, reward) in game.information:
                action = sequence[1]
                counts = Counter(n.children[action].own_view_signature for n in game.roots)
                entropy = -sum(count/7*log2(count/7) for count in counts.values())
                assert agent.trace["entropy"][action] == entropy
                assert reward == pytest.approx(-2**(-entropy)*20/1e7, abs=1e-20)
            games.append(game)
        assert games[0].information == games[1].information
        assert np.allclose(games[1].form().A.toarray(), 6*games[0].form().A.toarray())
        assert [g.audit["alternate"] for g in games[1].groups] == pytest.approx(
            [6*g.audit["alternate"] for g in games[0].groups])
    finally:
        for agent in agents:
            agent.close()
