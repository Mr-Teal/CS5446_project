"""Saved-tree I^2 chess projection, fresh roots and combined search mechanisms."""

from dataclasses import replace

import numpy as np
import pytest

from fow_shared.evaluation import MatchConfig, play_game
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.chess_projection import project_chess, SavedChessBlueprint
from pair_a_prep.chess_search import build_chess_tree, SearchBudgetError
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.rules_adapter import RulesReferee
from pair_a_prep.search_policies import purify_policy, StableSupport, heuristic_actions
from pair_a_prep.toy_games import Node, terminal
from pair_a_prep.tests.test_chess_search import KINGS, ConstantLeaf, turn_after, single_path_turn


@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_initial_best_action_is_published_and_receives_first_feedback(schedule):
    root = Node(player=0, infoset="I", children={"bad": terminal(-1), "best": terminal(1)})
    solver = PCFRPlus(root, schedule=schedule, initial_actions=heuristic_actions(root))
    assert solver.policy()[0]["I"] == {"bad": 0., "best": 1.}
    solver.step()
    assert solver.rounds == 1
    np.testing.assert_array_equal(solver.minimizers[0]["I"].regrets, [0, 0])
    # Alternating mode may publish a different successor after feedback. The
    # zero regret vector proves feedback used the seeded best action, not uniform.
    np.testing.assert_array_equal(solver.minimizers[0]["I"].previous_utility, [-1, 1])


def test_purification_preserves_raw_and_moves_excluded_mass_to_top():
    raw = {"a": .4, "b": .25, "c": .15, "d": .1, "e": .1}
    support = StableSupport()
    support.observe(raw, False)
    support.observe(raw, True)
    support.observe({**raw, "b": 0}, True)
    assert purify_policy(raw, "maxmargin", support.stable) == pytest.approx({
        "a": .75, "b": 0, "c": .15, "d": .1, "e": 0})
    assert purify_policy(raw, "resolve", support.stable) == {"a": 1., "b": 0., "c": 0., "d": 0., "e": 0.}
    assert purify_policy(raw, "maxmargin", None)["a"] == 1
    assert raw["b"] == .25


def test_projection_keeps_opponent_neighbours_and_current_labels_separate():
    old_turn = turn_after()
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=3)
    saved = SavedChessBlueprint(old_turn, tree, ((),), PCFRPlus(tree.root), .2)
    turn = turn_after(moves=("a1b1", "h8g8"))
    result = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1, max_nodes=2000, saved=saved)
    assert result.audit["retained"] == 9
    assert result.audit["outside_current"] == 6
    assert len(result.current_ids) == 3
    assert sum(result.boundaries.group_prior.values()) == pytest.approx(1)
    assert min(result.boundaries.group_prior.values()) > 0
    assert sum(r.reach_mass for r in result.boundaries.roots) == pytest.approx(3)
    for mode in ("resolve", "maxmargin"):
        bridge = result.bridge(mode, ConstantLeaf.name)
        PCFRPlus(bridge.gadget.tree).run(2)


def test_shallow_blueprint_adds_fresh_roots_with_explicit_boundaries():
    old_turn = turn_after()
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=1)
    saved = SavedChessBlueprint(old_turn, tree, ((),), PCFRPlus(tree.root), -.6)
    turn = turn_after(moves=("a1b1", "h8g8"))
    result = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1, max_nodes=2000, saved=saved)
    assert result.audit["retained"] == 0 and result.audit["fresh"] == 3
    assert set(result.boundaries.alternate_player0.values()) == {-.6}
    assert all(group.startswith("fresh-perfect-info:") for group in result.groups)
    assert result.audit["incomplete_cut"] == 3
    assert len(set(c.memories[1] for c in result.tree.history_roots)) == 3


def test_all_observed_opponent_sequences_outside_blueprint_support_use_uniform_prior():
    fen = "8/8/8/8/8/3k4/8/K7 w - - 0 1"
    old_turn = turn_after(fen=fen)
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=fen, depth=3)
    solver = PCFRPlus(tree.root)
    # The actual hypothetical opponent plays c2, although the blueprint puts
    # all opponent mass on e3. Our new observation distinguishes that move.
    for key, actions in solver.sets[1].items():
        solver._strategy[1][key][:] = 0
        solver._strategy[1][key][actions.index("d3e3")] = 1
    saved = SavedChessBlueprint(old_turn, tree, ((),), solver, .2)
    turn = single_path_turn(fen, ("a1b2", "d3c2"), "white")
    result = project_chess(turn, ConstantLeaf(), initial_fen=fen, depth=1, max_nodes=5000, saved=saved)
    assert result.boundaries.audit["all_zero_opponent_reach"]
    assert len(set(result.boundaries.group_prior.values())) == 1
    assert sum(result.boundaries.group_prior.values()) == pytest.approx(1)
    agent = ChessSubgameAgent(ConstantLeaf(), AnytimeConfig(growth="one_sided",
        rounds=4, final_rounds=1, stop_on_time=False,
        max_nodes=5000, max_evaluator_calls=256), fen)
    agent.reset("white", 17)
    agent.saved = saved
    decision = agent.act(turn)
    assert decision.diagnostics["fallback"] == 0
    assert decision.diagnostics["zero_reach_uniform_prior"] == 1


@pytest.mark.parametrize("schedule", ["alternating", "simultaneous"])
def test_live_gadget_agent_runs_modes_growth_retention_and_raw_labels(schedule):
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=4,
        rounds=8, rounds_per_stage=2, final_rounds=2, stop_on_time=False,
        max_nodes=2000, max_evaluator_calls=256, schedule=schedule)
    players = {side: ChessSubgameAgent(ConstantLeaf(), config, KINGS) for side in ("white", "black")}
    trackers = {side: BeliefTracker(KINGS, sample_size=3, max_candidates=2000) for side in players}
    result = play_game(RulesReferee(KINGS), players, trackers,
        MatchConfig(10000, 4, 17, "paper2021_fow_no_moves_draw_v1", "constant", 0))
    assert len(result.plies) == 4
    for player in players.values():
        record = player.last_result
        assert player.last_bridge is not None
        assert len(record.hypothesis_values) == len(player.saved.turn.belief.hypotheses)
        assert record.root_value == pytest.approx(sum(
            h.weight*v for h, v in zip(player.saved.turn.belief.hypotheses, record.hypothesis_values)))
        assert record.decision.diagnostics["solver_rounds_this_turn"] == 8
        assert record.decision.diagnostics["projection:retained"] > 0
        assert all(-1 <= v <= 1 for v in record.hypothesis_values)
        assert sum(v > 0 for k, v in record.decision.diagnostics.items() if k.startswith("played_policy:")) <= 3


def test_failed_projection_discards_saved_blueprint_and_next_turn_recovers():
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    agent.act(turn_after())
    saved = agent.saved
    agent.config = replace(config, max_evaluator_calls=1, initial_depth=2)
    turn = turn_after(moves=("a1b1", "h8g8"))
    decision = agent.act(turn)
    assert decision.diagnostics["fallback"] == 1
    assert agent.last_result is None and agent.saved is None
    with pytest.raises(SearchBudgetError):
        agent.label(turn, "no-fabricated-labels")
    agent.config = config
    following = turn_after(moves=("a1b1", "h8g8", "b1a1", "g8h8"))
    assert agent.act(following).diagnostics["fallback"] == 0
    assert agent.last_projection.boundaries is None


def test_projected_labels_follow_the_label_definitions_contract():
    # pair_b/docs/label_definitions.md: one value per hypothesis under the raw
    # profile, root_value their belief-weighted mean, raw root policy, played
    # policy recorded. The saved tree is projected (not discarded) and the
    # record says so.
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1,
                           stop_on_time=False, max_evaluator_calls=256, max_nodes=2000)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    agent.act(turn_after())
    turn = turn_after(moves=("a1b1", "h8g8"))
    record = agent.label(turn, "projected")
    assert record.decision.diagnostics["projected_from_saved_tree"] == 1
    assert record.game_id == "projected" and record.config_id == agent.config_id
    assert len(record.hypothesis_values) == len(turn.belief.hypotheses)
    assert record.root_value == pytest.approx(sum(h.weight*v for h, v in zip(turn.belief.hypotheses, record.hypothesis_values)))
    assert set(record.decision.root_policy) == set(turn.observation.legal_moves)
    assert sum(v > 0 for k, v in record.decision.diagnostics.items() if k.startswith("played_policy:")) >= 1
    with pytest.raises(ValueError, match="game_id"):
        agent.label(turn, " ")


class PositionLeaf:
    name = "test-position-dependent-leaf"

    @staticmethod
    def white_value(board):
        import chess
        return (board.king(chess.BLACK)-board.king(chess.WHITE))/100

    def evaluate_children(self, fen):
        import chess
        from fow_shared.values import fog_legal_moves
        board = chess.Board(fen)
        sign = 1 if board.turn else -1
        values = {}
        for action in fog_legal_moves(board):
            child = board.copy()
            child.push(action)
            values[action.uci()] = sign*self.white_value(child)
        return values


@pytest.mark.parametrize("warm", [False, True])
def test_varied_values_follow_input_root_order_and_exclude_gadget_payments(warm):
    import chess
    leaf = PositionLeaf()
    turn = turn_after(moves=("a1b1", "h8g8"))
    hypotheses = tuple(replace(h, weight=w) for h, w in zip(turn.belief.hypotheses, (.1, .2, .7)))
    turn = replace(turn, belief=replace(turn.belief, hypotheses=hypotheses))
    outputs = []
    for hypotheses in (hypotheses, tuple(reversed(hypotheses))):
        current = replace(turn, belief=replace(turn.belief, hypotheses=hypotheses))
        agent = ChessSubgameAgent(leaf, AnytimeConfig(growth="one_sided", initial_depth=1,
            max_depth=1, rounds=8, final_rounds=1, stop_on_time=False,
            max_nodes=5000, max_evaluator_calls=256), KINGS)
        agent.reset("white", 17)
        if warm:
            old = turn_after()
            tree = build_chess_tree(old, leaf, initial_fen=KINGS, depth=3)
            agent.saved = SavedChessBlueprint(old, tree, ((),), PCFRPlus(tree.root), .23)
        result = agent.solve(current)
        expected = []
        for hypothesis in hypotheses:
            board = chess.Board(hypothesis.fen)
            value = 0.
            for action, probability in result.decision.root_policy.items():
                child = board.copy()
                child.push(chess.Move.from_uci(action))
                value += probability*leaf.white_value(child)
            expected.append(value)
        assert len(set(round(v, 8) for v in expected)) > 1
        assert result.hypothesis_values == pytest.approx(expected)
        assert result.root_value == pytest.approx(sum(h.weight*v for h, v in zip(hypotheses, expected)))
        if warm:
            assert agent.last_bridge is not None
            assert result.decision.diagnostics["projected_from_saved_tree"] == 1
        outputs.append(dict(zip((h.fen for h in hypotheses), result.hypothesis_values)))
    assert outputs[0] == pytest.approx(outputs[1])


def test_deep_blueprint_forced_fallback_then_real_next_turn_starts_cold(monkeypatch):
    from pair_a_prep.rules_adapter import RulesAdapter
    fen = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"
    rules = RulesAdapter()
    config = AnytimeConfig(growth="one_sided", initial_depth=4, max_depth=5, rounds=8,
        final_rounds=2, stop_on_time=False, max_nodes=50000, max_evaluator_calls=700)
    agent = ChessSubgameAgent(ConstantLeaf(), config, fen)
    agent.reset("white", 17)
    first = agent.act(single_path_turn(fen, (), "white"))
    assert first.diagnostics["fallback"] == 0
    saved = agent.saved
    def height(node):
        return 0 if not node.children else 1+max(height(child) for child in node.children.values())
    assert height(saved.tree.root)-1 >= 4
    moves = [first.move]
    state = rules.apply_move(rules.initial_state(fen), first.move)
    moves.append(rules.legal_moves(state)[0])
    state = rules.apply_move(state, moves[-1])
    original = agent.solve
    def force_fallback(turn):
        raise SearchBudgetError("forced budget failure with deep saved blueprint")
    monkeypatch.setattr(agent, "solve", force_fallback)
    fallback = agent.act(single_path_turn(fen, tuple(moves), "white"))
    assert fallback.diagnostics["fallback"] == 1
    assert agent.saved is None
    moves.append(fallback.move)
    state = rules.apply_move(state, fallback.move)
    moves.append(rules.legal_moves(state)[0])
    monkeypatch.setattr(agent, "solve", original)
    following = agent.act(single_path_turn(fen, tuple(moves), "white"))
    assert following.diagnostics["fallback"] == 0
    assert agent.last_projection.boundaries is None


def test_budget_failure_after_solver_exists_plays_its_strategy_not_a_random_move(monkeypatch):
    # Obscuro Fig. 8: the move comes from the strategy computed so far. The
    # solver is published before the first round, so a failure inside the
    # round loop leaves its (heuristically seeded) root policy to play.
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False,
                           max_nodes=2000, max_evaluator_calls=256)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    turn = turn_after()
    def fail_first_round(self):
        raise SearchBudgetError("forced failure inside the solving loop")
    monkeypatch.setattr(PCFRPlus, "step", fail_first_round)
    decision = agent.act(turn)
    assert decision.diagnostics["fallback"] == 1
    assert decision.diagnostics["fallback_policy:partial_solver"] == 1
    assert decision.diagnostics["solver_rounds"] == 0
    assert max(decision.root_policy.values()) == 1 and decision.move in turn.observation.legal_moves
    assert sum(v > 0 for k, v in decision.diagnostics.items() if k.startswith("played_policy:")) == 1
    assert agent.saved is None and agent.last_projection is None


def test_projection_failure_falls_back_to_the_heuristic_best_child_not_uniform():
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    agent.act(turn_after())
    agent.config = replace(config, max_evaluator_calls=1, initial_depth=2)
    turn = turn_after(moves=("a1b1", "h8g8"))
    decision = agent.act(turn)
    assert decision.diagnostics["fallback"] == 1
    assert decision.diagnostics["fallback_policy:heuristic_depth1"] == 1
    assert "fallback_policy:uniform" not in decision.diagnostics
    assert sorted(decision.root_policy.values(), reverse=True)[0] == 1
    assert decision.move == max(decision.root_policy, key=decision.root_policy.get)
    assert set(decision.root_policy) == set(turn.observation.legal_moves)


def test_fresh_roots_are_distinct_positions_and_aliased_hypotheses_share_values():
    # Fig. 9 line 11 draws states from P, a set of positions. Two opponent
    # histories (via g8 or via h7, say) reach the same king square; the tracker
    # returns both, the projection builds one root and aliases the other.
    old_turn = turn_after()
    tree = build_chess_tree(old_turn, ConstantLeaf(), initial_fen=KINGS, depth=1)
    saved = SavedChessBlueprint(old_turn, tree, ((),), PCFRPlus(tree.root), .2)
    turn = turn_after(moves=("a1b1", "h8g8", "b1a1", "g8h8"))
    fens = [" ".join(h.fen.split()[:4]) for h in turn.belief.hypotheses]
    assert len(fens) > len(set(fens)), "fixture must contain two histories of one position"
    result = project_chess(turn, ConstantLeaf(), initial_fen=KINGS, depth=1, max_nodes=5000, saved=saved)
    assert result.audit["retained"] == 0
    assert result.audit["fresh_duplicates"] == len(fens) - len(set(fens)) == len(result.aliases)
    assert result.audit["fresh"] == len(set(fens))
    assert set(result.aliases.values()) <= set(result.root_ids)
    assert not set(result.aliases) & set(result.root_ids)
    agent = ChessSubgameAgent(ConstantLeaf(), AnytimeConfig(growth="one_sided", rounds=4,
        final_rounds=1, stop_on_time=False, max_nodes=5000, max_evaluator_calls=256), KINGS)
    agent.reset("white", 17)
    agent.saved = saved
    solved = agent.solve(turn)
    assert len(solved.hypothesis_values) == len(turn.belief.hypotheses)
    by_id = dict(zip(result.current_ids, solved.hypothesis_values))
    for alias, root in result.aliases.items():
        assert by_id[alias] == by_id[root]


def test_solve_reports_a_finite_last_iterate_nash_gap_and_minimum_margin():
    from math import isfinite
    leaf = PositionLeaf()
    agent = ChessSubgameAgent(leaf, AnytimeConfig(growth="one_sided", initial_depth=1, max_depth=2,
        rounds=8, final_rounds=1, stop_on_time=False, max_nodes=5000, max_evaluator_calls=256), KINGS)
    agent.reset("white", 17)
    cold = agent.act(turn_after()).diagnostics
    assert isfinite(cold["solver_nash_gap"]) and cold["solver_nash_gap"] >= 0
    assert cold["minimum_margin"] == 0  # no gadget on the first turn
    warm = agent.act(turn_after(moves=("a1b1", "h8g8"))).diagnostics
    assert isfinite(warm["solver_nash_gap"]) and warm["solver_nash_gap"] >= 0
    assert isfinite(warm["minimum_margin"])
    assert warm["projected_from_saved_tree"] == 1


def test_growth_headroom_keeps_in_turn_growth_under_the_cap():
    # At native speed a full-clock move grows to max_nodes; the saved tree keeps nearly all of it through the
    # next projection (fog reveals little), leaving no room for fresh roots. The headroom is what growth leaves.
    fen = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"
    base = AnytimeConfig(growth="one_sided", initial_depth=1, max_depth=4, rounds=80, rounds_per_stage=1,
                         final_rounds=1, stop_on_time=False, max_nodes=300, max_evaluator_calls=10000)
    nodes = {}
    for headroom in (0, 120):
        agent = ChessSubgameAgent(ConstantLeaf(), replace(base, growth_headroom=headroom), fen)
        agent.reset("white", 17)
        decision = agent.act(single_path_turn(fen, (), "white"))
        assert decision.diagnostics["fallback"] == 0
        nodes[headroom] = decision.diagnostics["search_nodes"]
    assert nodes[0] > 300-120, nodes            # without headroom growth passes the line the headroom draws
    assert nodes[120] <= 300-120, nodes         # with it, growth stops there
    with pytest.raises(ValueError):
        AnytimeConfig(max_nodes=300, growth_headroom=300)


def test_projection_overflow_drops_the_saved_tree_instead_of_falling_back(monkeypatch):
    import pair_a_prep.chess_subgame_agent as module
    from pair_a_prep.chess_search import TreeCapacityError
    config = AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False)
    agent = ChessSubgameAgent(ConstantLeaf(), config, KINGS)
    agent.reset("white", 17)
    agent.act(turn_after())
    assert agent.saved is not None
    original = module.project_chess
    calls = []
    def overflowing(turn, leaf, **kwargs):
        calls.append(kwargs["saved"] is not None)
        if kwargs["saved"] is not None:
            raise TreeCapacityError("projected knowledge tree exceeds max_nodes")
        return original(turn, leaf, **kwargs)
    monkeypatch.setattr(module, "project_chess", overflowing)
    turn = turn_after(moves=("a1b1", "h8g8"))
    decision = agent.act(turn)
    assert calls == [True, False]
    assert decision.diagnostics["fallback"] == 0
    assert decision.diagnostics["projection:dropped_for_capacity"] == 1
    assert agent.last_projection.boundaries is None   # a fresh turn, no gadget
    assert agent.saved is not None                      # and it saved a new blueprint
    record = agent.label(turn, "labels-after-a-dropped-projection")
    assert len(record.hypothesis_values) == len(turn.belief.hypotheses)
