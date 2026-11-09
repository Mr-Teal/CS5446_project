"""The cross-turn gadget path (D2) must reproduce the Python reference exactly.

Gadget.round_values (validated once per gadget, then toy_games.value_walk) and Gadget.solver_values (the kernel's
pcfr_behavioral_values on the solver's flat tree) must equal Gadget.continuation_values bit for bit. End to end,
ChessSubgameAgent replays consecutive own turns of recorded games (turn 2 on through the saved tree's projection
and the blended gadget) with round budgets: the reference (Python solver, Gadget.FAST off) and the fast path
(native solver, FAST on) make the same decisions, root policies and diagnostics, and the controller sees the same
continuation values and produces the same blend every round. Values are compared through repr(), so -0.0 and
0.0 would differ.
"""
import dataclasses
import glob

import pytest

from pair_a_prep import _pcfr_native
from pair_a_prep.gadgets import Gadget, SubgameRoot, build_gadget
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.subgame_boundaries import BlendedGadgetControl
from pair_a_prep.tests.test_pcfr_native import RECORDS
from pair_a_prep.toy_games import Node, terminal

native_only = pytest.mark.skipif(_pcfr_native.library() is None, reason="native PCFR+ kernel not built")
records_only = pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"),
                                  reason="set FOW_TEST_RECORDS to a label folder")


def _toy_roots():
    """Three roots in two opponent groups; one continuation has a chance node whose probabilities dict is in a
    different order from its children, and one is a single cutoff leaf (a lazy neighbour)."""
    shared = lambda: Node(player=0, infoset="mine", children={"L": terminal(1.0), "R": terminal(-0.5)})
    chance = Node(children={"x": shared(), "y": Node(player=1, infoset="theirs", children={
        "u": terminal(0.25), "v": terminal(-2.0)})}, probabilities={"y": 0.3, "x": 0.7})
    return [SubgameRoot("a", "A", chance, 2.0),
            SubgameRoot("b", "A", Node(player=0, infoset="mine", children={
                "L": terminal(-1.0), "R": Node(player=1, infoset="theirs", children={
                    "u": terminal(0.5), "v": terminal(0.75)})}), 1.0),
            SubgameRoot("c", "B", Node(payoff=0.125, cutoff=True), 1.0)]


@native_only
@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_round_and_solver_values_equal_continuation_values_every_round(schedule):
    gadgets = [build_gadget(_toy_roots(), {"A": 0.1, "B": -0.2}, mode="blended", group_prior={"A": .6, "B": .4})
               for _ in range(2)]
    solvers = [PCFRPlus(g.tree, schedule=schedule, backend=b) for g, b in zip(gadgets, ("python", "native"))]
    controls = [BlendedGadgetControl(g, {"A": .6, "B": .4}) for g in gadgets]
    for _ in range(40):
        for gadget, solver, control in zip(gadgets, solvers, controls):
            solver.run(1)
            reference = gadget.continuation_values(solver.policy())
            assert repr(gadget.round_values(solver.policy())) == repr(reference)
            assert repr(gadget.solver_values(solver)) == repr(reference)
            control.update_from_solver(gadget, solver)
        assert repr(gadgets[0].tree.probabilities) == repr(gadgets[1].tree.probabilities)
        assert (controls[0].margins, controls[0].p_max) == (controls[1].margins, controls[1].p_max)
        assert solvers[0].policy() == solvers[1].policy()
    assert gadgets[1].__dict__.get("_checked") == set(gadgets[1].continuations)


def test_round_values_validate_on_the_first_call_of_each_gadget():
    gadget = build_gadget(_toy_roots(), {"A": 0.1, "B": -0.2}, mode="blended", group_prior={"A": .6, "B": .4})
    profile = PCFRPlus(gadget.tree, backend="python").policy()
    bad = (dict(profile[0], mine={"L": 1.5, "R": -0.5}), profile[1])
    with pytest.raises(ValueError, match="invalid strategy distribution"):
        gadget.round_values(bad)
    missing = ({}, profile[1])
    with pytest.raises(KeyError):  # what continuation_values raises for a profile without a set
        gadget.round_values(missing)
    gadget.round_values(profile)  # the first valid call validates the gadget
    assert gadget.__dict__.get("_checked") == set(gadget.continuations)
    fresh = dataclasses.replace(gadget, tree=gadget.tree)  # an expansion's new gadget validates again
    with pytest.raises(ValueError):
        fresh.round_values(bad)


def test_round_values_validate_every_call_when_fast_is_off(monkeypatch):
    monkeypatch.setattr(Gadget, "FAST", False)
    gadget = build_gadget(_toy_roots(), {"A": 0.1, "B": -0.2}, mode="blended", group_prior={"A": .6, "B": .4})
    profile = PCFRPlus(gadget.tree, backend="python").policy()
    gadget.round_values(profile)
    with pytest.raises(ValueError, match="invalid strategy distribution"):
        gadget.round_values((dict(profile[0], mine={"L": 1.5, "R": -0.5}), profile[1]))


# End to end on recorded games ------------------------------------------------------------------------------------

def _games(count, turns):
    """`count` games with at least `turns` own turns of one player, from the first part files, turns in ply order."""
    from fow_shared.recording import read_records
    games = {}
    for path in sorted(glob.glob(f"{RECORDS}/part-*.jsonl"))[:40]:
        for record in read_records(path):
            games.setdefault((record.game_id, record.agent_input.observation.player), []).append(record)
        found = [key for key, rows in games.items() if len(rows) >= turns]
        if len(found) >= count:
            break
    found = [key for key, rows in games.items() if len(rows) >= turns][:count]
    return [(key, sorted(games[key], key=lambda r: r.agent_input.observation.ply)[:turns]) for key in found]


TIMING = ("elapsed_ms", "over_budget")


def _replay(backend, fast, player, turns, check_values=False):
    """One ChessSubgameAgent over the turns (material leaf, round budgets, no clock). Returns per turn the decision,
    its non-timing diagnostics, the raw root profile and the controller's trace of every round."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        return _replay_patched(monkeypatch, backend, fast, player, turns, check_values)


def _replay_patched(monkeypatch, backend, fast, player, turns, check_values):
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pairb.material import MaterialEvaluator

    monkeypatch.setattr(PCFRPlus, "BACKEND", backend)
    monkeypatch.setattr(Gadget, "FAST", fast)
    if not fast:  # the reference keys private observations as before D2: observation_key(observe(...))
        from pair_a_prep.chess_search import observation_key
        from pair_a_prep.rules_adapter import RulesAdapter
        monkeypatch.setattr(RulesAdapter, "observation_key", lambda self, state, player: observation_key(
            self.observe(state, player)))
    trace = []
    advance = BlendedGadgetControl._advance

    def recorded(self, gadget, values):
        margins = advance(self, gadget, values)
        trace.append(repr((values, margins, self.pi_resolve, self.pi_maxmargin, self.p_max, self.mode,
                           gadget.tree.probabilities)))
        return margins

    monkeypatch.setattr(BlendedGadgetControl, "_advance", recorded)
    if check_values:
        solver_values = Gadget.solver_values

        def checked(self, solver):
            values = solver_values(self, solver)
            assert repr(values) == repr(self.continuation_values(solver.policy()))
            return values

        monkeypatch.setattr(Gadget, "solver_values", checked)
        from pair_a_prep.chess_gadgets import ChessGadget
        expand = ChessGadget.expand

        def compared(self, solver, *args, **kwargs):
            """The fast expansion's bridge equals the one the reference builds from the same grown chess tree."""
            checked = self.gadget.__dict__.get("_checked", frozenset())
            bridge = expand(self, solver, *args, **kwargs)
            if bridge is self:
                return bridge
            grown = {self.roots.root_ids[int(path[0])] for path in kwargs["selected_paths"]}
            assert bridge.gadget.__dict__.get("_checked") == checked - grown  # grown continuations validate again
            reference = bridge.roots.build(self.gadget.alternate_player0, reach_mass=self.reach_mass,
                                           mode="blended", group_prior=self.group_prior)
            assert bridge == reference.__class__(reference.roots, bridge.gadget, reference.reach_mass,
                                                 reference.group_prior)
            got, want = bridge.gadget, reference.gadget
            assert (got.mode, got.roots, got.alternate_player0) == (want.mode, want.roots, want.alternate_player0)
            assert repr(got.root_prior) == repr(want.root_prior)
            assert list(got.continuations) == list(want.continuations)
            for root_id, continuation in want.continuations.items():
                assert got.continuations[root_id] == continuation
                assert solver.root.children[root_id] == continuation  # the solver's graft has the same structure
            raw = bridge.raw_solver
            assert raw.root is bridge.roots.chess_tree.root
            assert raw.sets == PCFRPlus(raw.root, backend="python").sets
            return bridge

        monkeypatch.setattr(ChessGadget, "expand", compared)
    config = AnytimeConfig(growth="one_sided", rounds=48, max_nodes=16384, max_evaluator_calls=4096,
                           stop_on_time=False, initial_depth=1, max_depth=2, rounds_per_stage=2, final_rounds=2,
                           schedule="alternating")
    agent = ChessSubgameAgent(MaterialEvaluator(), config, None)
    agent.reset(player, 7)
    rows = []
    for record in turns:
        turn = record.agent_input
        trace.clear()
        try:
            decision = agent.act(turn)
            refused = None
        except ValueError as exc:  # the recorded own move is the label agent's: see profile_move.py
            refused = str(exc)
            agent.saved = None
            decision = agent.act(turn)
        assert agent.last_solver.backend == backend
        diagnostics = {k: v for k, v in decision.diagnostics.items() if k not in TIMING}
        projection = agent.last_projection
        boundaries = projection.boundaries
        rows.append(dict(move=decision.move, policy=repr(decision.root_policy), diagnostics=repr(diagnostics),
                         refused=refused, profile=repr(agent.last_solver.policy()), trace=list(trace),
                         projection=repr((projection.root_ids, projection.groups, projection.current_ids,
                                          projection.aliases, projection.audit, projection.paths,
                                          projection.tree.frontiers.keys(), projection.tree.root_infoset,
                                          [c.memories for c in projection.tree.history_roots],
                                          None if boundaries is None else (
                                              boundaries.alternate_player0, boundaries.gifts,
                                              boundaries.group_prior, boundaries.audit,
                                              [(r.root_id, r.opponent_infoset, r.reach_mass)
                                               for r in boundaries.roots]))),
                         tree=projection.tree.root))  # compared with Node == (the whole structure)
    return rows


@native_only
@records_only
def test_recorded_games_replay_identically_through_the_gadget():
    games = _games(3, 7)
    assert len(games) == 3
    gadget_turns = 0
    for (game_id, player), turns in games:
        reference = _replay("python", False, player, turns)
        fast = _replay("native", True, player, turns, check_values=True)
        for index, (a, b) in enumerate(zip(reference, fast)):
            for field in a:
                assert a[field] == b[field], (game_id, index, field)
        gadget_turns += sum(bool(row["trace"]) for row in fast)
    assert gadget_turns >= 6  # turns that solved through the blended gadget, not fresh trees
