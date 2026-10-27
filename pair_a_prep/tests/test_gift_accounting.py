"""Independent retained/discarded CF arithmetic and nonadditive lineage checks."""

from dataclasses import replace

import pytest

from pair_a_prep.subgame_boundaries import BoundaryRoot, derive_boundaries
from pair_a_prep.gift_accounting import extend_ledger
from pair_a_prep.toy_games import Node, terminal
from pair_a_prep.chess_search import SearchBudgetError
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.subgame_validation import fixture_turn
from pair_a_prep.rules_adapter import RulesAdapter


def example(keep, drop, own_keep):
    root = Node(player=1, infoset="J", children={
        "L": Node(player=0, infoset="I", children={"keep": terminal(keep), "drop": terminal(drop)}),
        "R": terminal(0)})
    profile = ({"I": {"keep": own_keep, "drop": 1-own_keep}}, {"J": {"L": .5, "R": .5}})
    return root, profile, (BoundaryRoot("keep", ("L", "keep"), "cut-J"),)


def test_discarded_branches_still_contribute_to_local_gifts():
    root, profile, cut = example(0, 1, .5)
    boundary = derive_boundaries(root, profile, cut)
    term = boundary.audit["groups"]["cut-J"]["ancestor_gifts"][0]
    # L=.5, root=.25, so delta=.25. Retained terminal is 0, hence
    # every part of this gift comes from branches outside the selected cut.
    assert term["full_delta"] == pytest.approx(.25)
    assert term["retained_delta"] == 0
    assert term["discarded_delta"] == pytest.approx(.25)
    assert boundary.gifts["cut-J"] == pytest.approx(.25)


def test_positive_part_is_taken_after_retained_and_discarded_cancel():
    root, profile, cut = example(1, -1, .25)
    boundary = derive_boundaries(root, profile, cut)
    term = boundary.audit["groups"]["cut-J"]["ancestor_gifts"][0]
    # L=-.5 and root=-.25. Retained contribution has positive delta .125,
    # but discarded contribution -.375 makes the true delta negative.
    assert term["retained_delta"] == pytest.approx(.125)
    assert term["discarded_delta"] == pytest.approx(-.375)
    assert term["full_delta"] == pytest.approx(-.25)
    assert boundary.gifts["cut-J"] == 0


def test_accounting_deadline_is_explicit():
    with pytest.raises(SearchBudgetError, match="boundary accounting"):
        derive_boundaries(*example(1, -1, .25), deadline=0)


def term(gift=.25):
    return dict(infoset="J", action="L", retained_delta=0., discarded_delta=gift,
                full_delta=gift, gift=gift)


def test_ledger_keeps_units_and_prunes_unreachable_branches_without_adding_gifts():
    old = extend_ledger(None, (("old-unit", "J", .25, [term()], ()),
                               ("other-unit", "outside", .5, [term(.5)], ())))
    new = extend_ledger(old, (("new-normalization", "new-J", 0., (), (old.roots[0],)),))
    assert len(new.events) == 2
    assert {event.source_unit for event in new.events} == {"old-unit", "new-normalization"}
    assert next(e for e in new.events if e.event_id == new.roots[0]).local_gift == 0
    assert new.metrics()["gift_ledger_prior_positive_events"] == 1
    assert len(old.events) == 2


def test_shared_lineage_is_deduplicated_and_invalid_gift_sums_are_rejected():
    old = extend_ledger(None, (("unit", "J", .25, [term()], ()),))
    spec = ("next", "J2", 0., (), (old.roots[0], old.roots[0]))
    new = extend_ledger(old, (spec, spec))
    assert len(new.events) == 2 and new.roots[0] == new.roots[1]
    with pytest.raises(ValueError, match="unknown gift ancestor"):
        extend_ledger(None, (("unit", "J", 0., (), ("missing",)),))
    with pytest.raises(ValueError, match="does not match"):
        extend_ledger(None, (("unit", "J", .5, [term()], ()),))


def test_chess_lineage_is_audit_only_and_does_not_change_next_policy_or_labels():
    fen = "7k/8/8/8/8/8/8/K7 w - - 0 1"
    from pair_a_prep.tests.test_chess_search import ConstantLeaf
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3,
        rounds=4, final_rounds=1, max_nodes=2000, max_evaluator_calls=256, stop_on_time=False)
    old = ChessSubgameAgent(ConstantLeaf(), config, fen)
    old.reset("white", 17)
    initial, _ = fixture_turn(dict(fen=fen))
    own = old.act(initial).move
    rules = RulesAdapter()
    opponent = rules.legal_moves(rules.apply_move(rules.initial_state(fen), own))[0]
    turn, _ = fixture_turn(dict(fen=fen, candidate_moves=(own, opponent)))
    outputs = []
    for snapshot in (old.saved, replace(old.saved, gift_ledger=None)):
        agent = ChessSubgameAgent(ConstantLeaf(), config, fen)
        agent.reset("white", 29)
        agent.saved = snapshot
        record = agent.label(turn, "lineage-control")
        outputs.append((record.decision.root_policy, record.hypothesis_values))
        if snapshot.gift_ledger is not None:
            assert record.decision.diagnostics["gift_ledger_ancestor_events"] > 0
        assert agent.saved.gift_ledger is not None
    assert outputs[0] == outputs[1]
