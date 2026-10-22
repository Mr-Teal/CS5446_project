"""Privacy, history, payoff and label checks for the fixed-depth chess bridge."""

from dataclasses import replace

import chess
import pytest

from fow_shared.contracts import AgentInput, Belief, HistoryEvent, Hypothesis
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.recording import read_records, write_records
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.chess_search import (
    TreeCapacityError, SearchBudgetError, build_chess_tree, reconstruct_roots,
    UnresolvedNoMoveError,
)
from pair_a_prep.label_pilot import KINGS, collect, semantic_records
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.rules_adapter import RulesAdapter, RulesReferee
from pair_a_prep.search_agent import FixedDepthPCFRAgent, SearchConfig
from pair_a_prep.toy_games import behavioral_value, payoff_matrix, solve_matrix
from fow_shared.values import fog_legal_moves


RULES = RulesAdapter()


class ConstantLeaf:
    name = "test-constant-leaf"

    def __init__(self, value=0.4):
        self.value = value

    def evaluate_children(self, fen):
        return {m.uci(): self.value for m in fog_legal_moves(chess.Board(fen))}


def turn_after(fen=KINGS, moves=(), player="white"):
    tracker = BeliefTracker(fen)
    tracker.reset(player, 17)
    state = RULES.initial_state(fen)
    observation = RULES.observe(state, player)
    belief = tracker.update(observation)
    history = []
    for move in moves:
        own = move if RULES.current_player(state) == player else None
        history.append(HistoryEvent(observation, own))
        state = RULES.apply_move(state, move)
        observation = RULES.observe(state, player)
        belief = tracker.update(observation, own)
    return AgentInput(observation, belief, 10000, tuple(history))


def single_path_turn(fen, moves, player):
    # Avoid enumerating an unnecessary exact population for long draw histories.
    state, history = RULES.initial_state(fen), []
    for move in moves:
        observation = RULES.observe(state, player)
        history.append(HistoryEvent(observation, move if RULES.current_player(state) == player else None))
        state = RULES.apply_move(state, move)
    observation = RULES.observe(state, player)
    belief = Belief(player, len(moves), (Hypothesis(state.fen, 1.0, "test", tuple(moves)),))
    return AgentInput(observation, belief, 10000, tuple(history))


def test_hidden_roots_share_own_information_but_not_opponents_private_stream():
    turn = turn_after(moves=("a1b1", "h8g8"))
    roots = reconstruct_roots(turn, RULES, KINGS)
    assert len(roots) == 3
    assert len({r.memories[0] for r in roots}) == 1
    assert len({r.memories[1] for r in roots}) == 3
    tree = build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS)
    assert len({node.infoset for node in tree.continuations}) == 1
    # Black remembers its own hidden move, even after the same White action.
    assert len({node.children["b1a1"].infoset for node in tree.continuations}) == 3
    PCFRPlus(tree.root)  # Also checks perfect recall and equal infoset actions.


def test_same_fen_histories_keep_opponent_memory_distinct():
    turn = turn_after(moves=("a1b1", "h8g8", "b1a1", "g8h8"))
    roots = reconstruct_roots(turn, RULES, KINGS)
    same_fen = {}
    for root in roots:
        same_fen.setdefault(root.state.fen, []).append(root)
    group = next(items for items in same_fen.values() if len(items) > 1)
    assert len({r.memories[0] for r in group}) == 1
    assert len({r.memories[1] for r in group}) == len(group)


def test_only_private_stream_determines_the_result_not_actual_hidden_move():
    a = turn_after(moves=("a1b1", "h8g8"))
    b = turn_after(moves=("a1b1", "h8g7"))
    assert a == b
    agents = [FixedDepthPCFRAgent(ConstantLeaf(), SearchConfig(rounds=3, stop_on_time=False), KINGS)
              for _ in range(2)]
    for agent in agents:
        agent.reset("white", 7)
    left, right = [agent.label(turn, "same-private-game") for agent, turn in zip(agents, (a, b))]
    assert semantic_records([left]) == semantic_records([right])


@pytest.mark.parametrize("damage", ["missing_history", "missing_path", "bad_fen", "wrong_own_move"])
def test_inconsistent_or_incomplete_history_is_rejected(damage):
    turn = turn_after(moves=("a1b1", "h8g8"))
    if damage == "missing_history":
        turn = replace(turn, history=())
    elif damage == "wrong_own_move":
        turn = replace(turn, history=(replace(turn.history[0], own_move="a1a2"), turn.history[1]))
    else:
        h = turn.belief.hypotheses[0]
        h = replace(h, **({"candidate_moves": ()} if damage == "missing_path" else {"fen": KINGS}))
        turn = replace(turn, belief=replace(turn.belief, hypotheses=(replace(h, weight=1.0),)))
    with pytest.raises(ValueError):
        build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS)


def test_historyful_repetition_overrides_fen_only_leaf_estimate():
    fen = "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1"
    moves = ["f7f6", "g8h8", "f6f7", "h8g8", "f7f6", "g8h8", "f6f7"]
    turn = single_path_turn(fen, moves, "black")
    tree = build_chess_tree(turn, ConstantLeaf(0.8), initial_fen=fen, depth=1)
    assert tree.continuations[0].children["h8g8"].payoff == 0.0
    assert tree.terminal_leaves >= 1


@pytest.mark.parametrize("fen,player,winning_move", [
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", "white", "e2e8"),
    ("4k3/4r3/8/8/8/8/8/4K3 b - - 0 1", "black", "e7e1"),
])
def test_both_colours_maximize_own_king_capture_value(fen, player, winning_move):
    turn = turn_after(fen, player=player)
    agent = FixedDepthPCFRAgent(ConstantLeaf(-0.5), SearchConfig(depth=1, rounds=8, stop_on_time=False), fen)
    agent.reset(player, 1)
    result = agent.solve(turn)
    assert result.decision.root_policy[winning_move] == pytest.approx(1)
    assert result.decision.move == winning_move
    assert result.root_value == pytest.approx(1)


def test_opponent_frontier_values_are_negated_even_when_root_player_is_black():
    fen = KINGS.replace(" w ", " b ")
    tree = build_chess_tree(turn_after(fen, player="black"), ConstantLeaf(0.4), initial_fen=fen, depth=2)
    for reply in tree.continuations[0].children.values():
        assert reply.player == 1
        assert all(leaf.payoff == -0.4 for leaf in reply.children.values())


def test_per_root_labels_use_one_shared_raw_strategy_and_input_weights():
    turn = turn_after(moves=("a1b1", "h8g8"))
    hs = turn.belief.hypotheses[:2]
    turn = replace(turn, belief=replace(turn.belief, hypotheses=(replace(hs[0], weight=0.75),
                                                               replace(hs[1], weight=0.25))))

    class RootLeaf(ConstantLeaf):
        name = "test-root-values"

        def evaluate_children(self, fen):
            score = 0.8 if fen == hs[0].fen else -0.2
            return {m.uci(): score if m.uci() == "b1a1" else -0.9
                    for m in fog_legal_moves(chess.Board(fen))}

    agent = FixedDepthPCFRAgent(RootLeaf(), SearchConfig(depth=1, rounds=8, stop_on_time=False), KINGS)
    agent.reset("white", 17)
    label = agent.label(turn, "weighted-test")
    assert label.hypothesis_values == pytest.approx((0.8, -0.2))
    assert label.root_value == pytest.approx(0.55)
    assert label.decision.root_policy["b1a1"] == pytest.approx(1)


def test_tree_and_clock_limits_fail_without_publishing_partial_labels():
    turn = turn_after()
    with pytest.raises(TreeCapacityError):
        build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS, max_nodes=2)
    with pytest.raises(SearchBudgetError):
        build_chess_tree(turn, ConstantLeaf(), initial_fen=KINGS, deadline=0)
    agent = FixedDepthPCFRAgent(ConstantLeaf(), SearchConfig(max_nodes=2), KINGS)
    agent.reset("white", 17)
    with pytest.raises(TreeCapacityError):
        agent.label(turn, "capacity-test")
    assert agent.last_result is None


def test_blocked_custom_position_does_not_silently_become_a_draw():
    # The blocked position supplied in Colin's PR #15 review.
    fen = "7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1"
    turn = turn_after(fen)
    assert not turn.observation.legal_moves and not turn.observation.terminal
    with pytest.raises(UnresolvedNoMoveError):
        build_chess_tree(turn, ConstantLeaf(), initial_fen=fen)


def test_bad_leaf_coverage_or_nonfinite_scores_fail_explicitly():
    class BadLeaf:
        def evaluate_children(self, fen):
            return {}
    with pytest.raises(ValueError, match="leaf evaluator"):
        build_chess_tree(turn_after(), BadLeaf(), initial_fen=KINGS, depth=1)
    with pytest.raises(ValueError, match="leaf evaluator"):
        build_chess_tree(turn_after(), ConstantLeaf(float("nan")), initial_fen=KINGS, depth=1)


def test_hidden_chess_actions_form_one_opponent_infoset_and_match_lp_oracle():
    class MatrixLeaf(ConstantLeaf):
        def evaluate_children(self, fen):
            # Black cannot see which of White's three king moves happened.
            # Values are supplied from Black's view, then negated by the builder.
            white = chess.Board(fen).king(chess.WHITE)
            row = {chess.A2: (1.0, -1.0, 0.0), chess.B1: (-1.0, 1.0, 0.0),
                   chess.B2: (-0.5, -0.5, -0.5)}[white]
            return {move: -value for move, value in zip(("h8g7", "h8g8", "h8h7"), row)}

    tree = build_chess_tree(turn_after(), MatrixLeaf(), initial_fen=KINGS)
    replies = tree.continuations[0].children.values()
    assert len({reply.infoset for reply in replies}) == 1
    matrix, _, _ = payoff_matrix(tree.root)
    assert matrix.shape == (3, 3)
    oracle = solve_matrix(matrix)
    solver = PCFRPlus(tree.root, schedule="alternating")
    solver.run(300)
    assert behavioral_value(tree.root, solver.policy()) == pytest.approx(oracle["profile_value"], abs=1e-5)


def test_shared_match_runner_drives_agent_and_both_exact_trackers():
    config = SearchConfig(depth=2, rounds=2, stop_on_time=False)
    result = play_game(RulesReferee(KINGS),
                       {p: FixedDepthPCFRAgent(ConstantLeaf(), config, KINGS) for p in ("white", "black")},
                       {p: BeliefTracker(KINGS, sample_size=3, max_candidates=500) for p in ("white", "black")},
                       MatchConfig(10000, 4, 17, "paper_fow_v1_proposed", "test-constant-leaf", 2))
    assert len(result.plies) == 4
    assert result.stopped_at_ply_limit
    assert all(p.search_nodes > 0 for p in result.plies)


def test_pilot_repeats_semantics_and_roundtrips_shared_training_records(tmp_path):
    kwargs = dict(games=1, max_plies=4, config=SearchConfig(rounds=2, stop_on_time=False))
    first, games = collect(ConstantLeaf(), **kwargs)
    repeat, _ = collect(ConstantLeaf(), **kwargs)
    assert semantic_records(first) == semantic_records(repeat)
    path = tmp_path / "part-000.jsonl"
    write_records(path, first)
    assert semantic_records(list(read_records(path))) == semantic_records(first)
    assert games[0]["outcome"] is None and games[0]["stopped_at_ply_limit"]
    assert max(u["population_size"] for u in games[0]["tracker_updates"]) > 1
