"""Information structure and unshifted labels across the chess/gadget bridge."""

from dataclasses import replace

import chess
import pytest

from fow_shared.contracts import AgentInput, Belief, HistoryEvent, Hypothesis
from fow_shared.recording import read_records, write_records
from fow_shared.values import fog_legal_moves
from pair_a_prep.chess_gadgets import prepare_chess_roots
from pair_a_prep.label_pilot import KINGS
from pair_a_prep.rules_adapter import RulesAdapter
from pair_a_prep.toy_games import payoff_matrix, solve_matrix


RULES = RulesAdapter()


class TableLeaf:
    name = "chess-gadget-test-table"

    def __init__(self, scores=None):
        self.scores = scores or {}

    def evaluate_children(self, fen):
        return {move.uci(): self.scores.get(fen, 0.4) for move in fog_legal_moves(chess.Board(fen))}


def make_turn(paths=((),), weights=None, fen=KINGS, viewer="white"):
    hypotheses, private_history, current = [], None, None
    weights = weights or [1 / len(paths)] * len(paths)
    for index, (path, weight) in enumerate(zip(paths, weights)):
        state, history = RULES.initial_state(fen), []
        for move in path:
            history.append(HistoryEvent(RULES.observe(state, viewer),
                                        move if RULES.current_player(state) == viewer else None))
            state = RULES.apply_move(state, move)
        observation = RULES.observe(state, viewer)
        if private_history is None:
            private_history, current = tuple(history), observation
        else:
            assert private_history == tuple(history) and current == observation
        hypotheses.append(Hypothesis(state.fen, weight, f"candidate-{index}", tuple(path)))
    return AgentInput(current, Belief(viewer, current.ply, tuple(hypotheses)), 10000, private_history)


def build(roots, mode="resolve", alternates=None, prior=None):
    keys = tuple(roots.groups)
    if alternates is None:
        alternates = {key: 2.0 for key in keys}
    if prior is None and mode == "resolve":
        prior = {key: 1 / len(keys) for key in keys}
    return roots.build(alternates, reach_mass={root: i + 1 for i, root in enumerate(roots.root_ids)},
                       mode=mode, group_prior=prior)


@pytest.mark.parametrize("viewer,paths", [
    ("white", (("a1b1", "h8g8"), ("a1b1", "h8g7"))),
    ("black", (("a1a2", "h8g8", "a2a3"), ("a1b2", "h8g8", "b2b3"))),
])
def test_root_groups_use_opponents_memory_and_preserve_our_shared_policy(viewer, paths):
    roots = prepare_chess_roots(make_turn(paths, viewer=viewer), TableLeaf(), initial_fen=KINGS, depth=1)
    assert len(roots.groups) == 2  # Opponent remembers its own different actions.
    assert all(key.startswith("black:" if viewer == "white" else "white:") for key in roots.groups)
    bridge = build(roots)
    solution = bridge.solve(10)
    assert len(solution.profile[0]) == 1
    assert set(solution.values.root_policy) == set(roots.turn.observation.legal_moves)
    for root in bridge.gadget.continuations.values():
        assert root.infoset == roots.chess_tree.root_infoset


def test_same_fen_different_opponent_histories_remain_different_root_groups():
    paths = (("a1b1", "h8g8", "b1a1", "g8h8"),
             ("a1b1", "h8g7", "b1a1", "g7h8"))
    turn = make_turn(paths)
    assert turn.belief.hypotheses[0].fen == turn.belief.hypotheses[1].fen
    roots = prepare_chess_roots(turn, TableLeaf(), initial_fen=KINGS, depth=1)
    assert len(set(roots.root_ids)) == 2 and len(roots.groups) == 2
    assert len({node.infoset for node in roots.chess_tree.continuations}) == 1


@pytest.mark.parametrize("mode", ["resolve", "maxmargin"])
def test_opponent_shares_hidden_future_actions_but_can_react_to_visible_actions(mode):
    fen = "8/8/8/2k5/8/K7/8/8 w - - 0 1"
    roots = prepare_chess_roots(make_turn(fen=fen), TableLeaf(), initial_fen=fen, depth=2)
    bridge = build(roots, mode)
    continuation = bridge.gadget.continuations[roots.root_ids[0]]
    hidden_a = continuation.children["a3a2"]
    hidden_b = continuation.children["a3b2"]
    visible = continuation.children["a3b4"]
    assert hidden_a.player == hidden_b.player == visible.player == 1
    assert hidden_a.infoset == hidden_b.infoset
    assert visible.infoset != hidden_a.infoset
    solution = bridge.solve(10)
    # A single dictionary entry controls both invisible histories. A distinct
    # observed stream permits a different distribution, even off the played path.
    profile = solution.profile
    hidden_actions = tuple(hidden_a.children)
    visible_actions = tuple(visible.children)
    profile[1][hidden_a.infoset] = {a: float(a == hidden_actions[0]) for a in hidden_actions}
    profile[1][visible.infoset] = {a: float(a == visible_actions[-1]) for a in visible_actions}
    bridge.evaluate_profile(profile)  # Valid complete executable behavior profile.
    assert profile[1][hidden_a.infoset] == profile[1][hidden_b.infoset]
    assert profile[1][visible.infoset] != profile[1][hidden_a.infoset]


@pytest.mark.parametrize("mode,expected_objective", [("resolve", -0.46), ("maxmargin", -0.4)])
def test_labels_exclude_prior_optouts_and_offsets_and_match_independent_lp(mode, expected_objective, tmp_path):
    paths = (("a1b1", "h8g8"), ("a1b1", "h8g7"))
    turn = make_turn(paths, weights=(0.9, 0.1))
    leaf = TableLeaf({turn.belief.hypotheses[0].fen: 0.8, turn.belief.hypotheses[1].fen: -0.6})
    roots = prepare_chess_roots(turn, leaf, initial_fen=KINGS, depth=1)
    keys = roots.opponent_infosets
    masses = dict(zip(roots.root_ids, (7.0, 3.0)))
    prior = {keys[0]: 0.1, keys[1]: 0.9} if mode == "resolve" else None
    alternates = {keys[0]: 2.0, keys[1]: 2.0} if mode == "resolve" else {keys[0]: 0.3, keys[1]: -0.2}
    bridge = roots.build(alternates, reach_mass=masses, mode=mode, group_prior=prior)
    solution = bridge.solve(50)
    oracle = solve_matrix(payoff_matrix(bridge.gadget.tree)[0])["profile_value"]
    assert solution.values.gadget_value == pytest.approx(oracle)
    assert oracle == pytest.approx(expected_objective)
    assert solution.values.hypothesis_values == pytest.approx((0.8, -0.6))
    assert solution.values.root_value == pytest.approx(0.66)
    if mode == "resolve":
        assert bridge.gadget.root_prior == dict(zip(roots.root_ids, (0.1, 0.9)))
    record = solution.training_record(seed=17, game_id="chess-gadget-test")
    assert record.root_value == pytest.approx(0.66)
    assert record.decision.diagnostics["solver_root_value"] == pytest.approx(expected_objective)
    path = tmp_path / "part-000.jsonl"
    write_records(path, [record])
    assert next(read_records(path)) == record


@pytest.mark.parametrize("mode,alternate,expected_objective", [("resolve", -2.0, -2.0),
                                                             ("maxmargin", 2.0, -1.6)])
def test_black_labels_are_continuations_even_if_opponent_always_exits(mode, alternate, expected_objective):
    fen = KINGS.replace(" w ", " b ")
    roots = prepare_chess_roots(make_turn(fen=fen, viewer="black"), TableLeaf(), initial_fen=fen, depth=1)
    bridge = build(roots, mode, alternates={next(iter(roots.groups)): alternate})
    solution = bridge.solve(20)
    assert solution.values.gadget_value == pytest.approx(expected_objective)
    assert solution.values.hypothesis_values == pytest.approx((0.4,))
    record = solution.training_record(seed=17, game_id="black-gadget-test")
    assert record.root_value == pytest.approx(0.4)
    assert record.agent_input.observation.player == "black"


def test_reordering_roots_keeps_identity_and_label_values_in_input_order():
    paths = (("a1b1", "h8g8"), ("a1b1", "h8g7"))
    turn = make_turn(paths, weights=(0.9, 0.1))
    leaf = TableLeaf({turn.belief.hypotheses[0].fen: 0.8, turn.belief.hypotheses[1].fen: -0.6})
    a = prepare_chess_roots(turn, leaf, initial_fen=KINGS, depth=1)
    reverse = replace(turn, belief=replace(turn.belief, hypotheses=tuple(reversed(turn.belief.hypotheses))))
    b = prepare_chess_roots(reverse, leaf, initial_fen=KINGS, depth=1)
    assert b.root_ids == tuple(reversed(a.root_ids))
    assert b.opponent_infosets == tuple(reversed(a.opponent_infosets))
    left, right = build(a).solve(10), build(b).solve(10)
    assert right.values.hypothesis_values == pytest.approx(tuple(reversed(left.values.hypothesis_values)))
    assert left.values.root_value == pytest.approx(right.values.root_value)


def test_alias_ids_do_not_change_groups_and_duplicate_paths_are_rejected():
    turn = make_turn((("a1b1", "h8g8"), ("a1b1", "h8g7")))
    changed = replace(turn, belief=replace(turn.belief, hypotheses=tuple(
        replace(h, history_id=f"new-alias-{i}") for i, h in enumerate(turn.belief.hypotheses))))
    a = prepare_chess_roots(turn, TableLeaf(), initial_fen=KINGS, depth=1)
    b = prepare_chess_roots(changed, TableLeaf(), initial_fen=KINGS, depth=1)
    assert a.root_ids == b.root_ids and a.opponent_infosets == b.opponent_infosets
    h = turn.belief.hypotheses[0]
    duplicate = replace(turn, belief=replace(turn.belief, hypotheses=(replace(h, weight=0.5),
                        replace(h, weight=0.5, history_id="other-alias"))))
    with pytest.raises(ValueError, match="duplicate reconstructed history"):
        prepare_chess_roots(duplicate, TableLeaf(), initial_fen=KINGS, depth=1)


def test_explicit_inputs_and_complete_maps_are_required():
    roots = prepare_chess_roots(make_turn(), TableLeaf(), initial_fen=KINGS, depth=1)
    key, root_id = roots.opponent_infosets[0], roots.root_ids[0]
    with pytest.raises(ValueError, match="explicit group_prior"):
        roots.build({key: 0.0}, reach_mass={root_id: 1.0})
    invalid = [({}, {root_id: 1.0}, {key: 1.0}, "resolve"),
               ({key: 0.0}, {}, {key: 1.0}, "resolve"),
               ({key: 0.0}, {root_id: -1.0}, {key: 1.0}, "resolve"),
               ({key: 0.0}, {root_id: 0.0}, {key: 1.0}, "resolve"),
               ({key: float("nan")}, {root_id: 1.0}, {key: 1.0}, "resolve"),
               ({key: 0.0}, {root_id: 1.0}, {key: 0.5}, "resolve"),
               ({key: 0.0}, {root_id: 1.0}, {key: 1.0}, "maxmargin")]
    for alternate, masses, prior, mode in invalid:
        with pytest.raises(ValueError):
            roots.build(alternate, reach_mass=masses, group_prior=prior, mode=mode)


def test_gadget_configuration_identifies_rules_and_hashes_rule_revisions(monkeypatch):
    from pair_a_prep import chess_gadgets
    roots = prepare_chess_roots(make_turn(), TableLeaf(), initial_fen=KINGS, depth=1)
    first = build(roots).solve(2)
    assert first.configuration["rules"] == "teal-rules-adapter"
    assert first.configuration["rules_id"] == "paper_fow_v1_proposed"
    assert first.configuration["no_move_rule"] == "terminal_draw_v1"
    monkeypatch.setattr(chess_gadgets, "NO_MOVE_RULE", "legacy_unresolved")
    second = build(roots).solve(2)
    assert first.config_id != second.config_id
    monkeypatch.setattr(chess_gadgets, "RULES_ID", "another_rule_revision")
    assert build(roots).solve(2).config_id != second.config_id
