"""Exact inference, observation-only boundaries and shared-runner integration."""

from collections import Counter
from dataclasses import replace
from itertools import product
from random import Random

import chess
import pytest

from fow_shared.contracts import Decision
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.values import fog_legal_moves, standard_fen
from pair_a_prep.belief_tracker import BeliefCapacityError, BeliefTracker
from pair_a_prep.fixtures import load_suite
from pair_a_prep.rules_adapter import RuleState, RulesAdapter, RulesReferee


KINGS = "7k/8/8/8/8/8/8/K7 w - - 0 1"
RULES = RulesAdapter()


def replay(fen, moves, player, **options):
    tracker = BeliefTracker(fen, **options)
    tracker.reset(player, seed=17)
    state = RULES.initial_state(fen)
    belief = tracker.update(RULES.observe(state, player))
    for move in moves:
        mover = RULES.current_player(state)
        state = RULES.apply_move(state, move)
        belief = tracker.update(RULES.observe(state, player), move if mover == player else None)
    return tracker, state, belief


@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("case", load_suite()["cases"], ids=lambda c: c["id"])
def test_all_fixture_starts(case, player):
    # A FEN is a fresh public start, even for a fixture whose original draw needs history.
    tracker, state, belief = replay(case["fen"], (), player)
    assert belief.population_size == tracker.population_size == 1
    assert belief.hypotheses[0].fen == state.fen
    assert belief.hypotheses[0].candidate_moves == ()
    assert belief.hypotheses[0].weight == 1.0


@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("fen,moves", [
    ("k4r2/8/8/8/8/8/8/4K2R w K - 0 1", ["e1g1"]),
    ("k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1", ["e2f2"]),
    ("4k3/8/8/4Pp2/8/8/8/4K3 w - f6 0 1", ["e5f6", "e8d8"]),
    ("4k3/8/8/4KPpr/8/8/8/8 w - g6 0 1", ["f5g6"]),
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", ["e2e8"]),
    ("7k/8/8/5n2/4P3/8/8/K7 w - - 0 1", ["e4f5", "h8g8"]),
    ("7k/8/8/8/8/8/8/K7 b - - 99 80", ["h8g8"]),
] + [("7k/P7/8/8/8/8/8/7K w - - 0 1", ["a7a8" + piece])
     for piece in "qrbn"])
def test_special_transitions_keep_the_true_history(fen, moves, player):
    tracker, state, belief = replay(fen, moves, player)
    assert (state.fen, tuple(moves)) in {
        (h.fen, h.candidate_moves) for h in belief.hypotheses
    }
    assert belief.population_size == tracker.population_size
    assert sum(h.weight for h in belief.hypotheses) == pytest.approx(1.0)


def test_hidden_move_branches_have_hand_derived_support():
    tracker, state, belief = replay(KINGS, ["a1b1", "h8g8"], "white")
    assert {h.candidate_moves for h in belief.hypotheses} == {
        ("a1b1", move) for move in ("h8g8", "h8g7", "h8h7")
    }
    assert tracker.population_size == 3
    assert all(h.weight == pytest.approx(1 / 3) for h in belief.hypotheses)
    assert all(h.fen.split()[3] == "-" for h in belief.hypotheses)


def test_same_fen_different_histories_are_not_merged():
    _, _, belief = replay(KINGS, ["a1b1", "h8g8", "b1a1", "g8h8"], "white")
    paths = [("a1b1", "h8g8", "b1a1", "g8h8"),
             ("a1b1", "h8g7", "b1a1", "g7h8")]
    entries = [next(h for h in belief.hypotheses if h.candidate_moves == p) for p in paths]
    assert entries[0].fen == entries[1].fen
    assert entries[0].history_id != entries[1].history_id
    assert max(Counter(h.fen for h in belief.hypotheses).values()) > 1


@pytest.mark.parametrize("player", ["white", "black"])
def test_threefold_uses_each_candidates_full_history(player):
    moves = ["a1b1", "h8g8", "b1a1", "g8h8"] * 2
    tracker, state, belief = replay(KINGS, moves, player)
    assert RULES.observe(state, player).outcome == 0.0
    assert RULES.terminal(RULES.initial_state(state.fen)) is None
    for h in belief.hypotheses:
        candidate = RULES.initial_state(KINGS)
        for move in h.candidate_moves:
            candidate = RULES.apply_move(candidate, move)
        assert RULES.terminal(candidate).reason == "threefold_repetition"
    with pytest.raises(ValueError, match="terminal"):
        tracker.update(replace(RULES.observe(state, player), ply=9))


def test_complete_history_oracle_agrees_after_each_ply():
    # Exhaustive Cartesian paths are rebuilt from scratch, without tracker state
    # or its incremental branching algorithm. Keep the game small and auditable.
    moves = ["a1b1", "h8g8", "b1a1", "g8h8"]
    observations = [RULES.observe(RULES.initial_state(KINGS), "white")]
    true = RULES.initial_state(KINGS)
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 2)
    tracker.update(observations[0])
    choices = []
    for ply, actual in enumerate(moves, 1):
        true = RULES.apply_move(true, actual)
        observations.append(RULES.observe(true, "white"))
        choices.append([actual] if ply % 2 else
                       [chess.square_name(a) + chess.square_name(b)
                        for a in chess.SQUARES for b in chess.SQUARES
                        if chess.square_distance(a, b) == 1 and chess.square_rank(a) >= 5
                        and chess.square_rank(b) >= 5])
        expected = set()
        for path in product(*choices):
            board = chess.Board(KINGS)
            for index, uci in enumerate(path, 1):
                action = chess.Move.from_uci(uci)
                if action not in fog_legal_moves(board):
                    break
                board.push(action)
                if RULES.observe(RuleState(board, ply=index), "white") != observations[index]:
                    break
            else:
                expected.add((standard_fen(board), path))
        belief = tracker.update(observations[-1], actual if ply % 2 else None)
        assert {(h.fen, h.candidate_moves) for h in belief.hypotheses} == expected


def test_sampling_preserves_full_population_and_reset_reproducibility():
    moves = ["a1b1", "h8g8", "b1a1", "g8h8"]
    tracker, state, sampled = replay(KINGS, moves, "white", sample_size=1)
    _, _, full = replay(KINGS, moves, "white")
    assert len(sampled.hypotheses) == 1
    assert sampled.population_size == full.population_size > 3
    assert tracker.population_size == full.population_size
    assert sampled.hypotheses[0].weight == 1.0
    tracker.reset("white", 17)
    root = RULES.initial_state(KINGS)
    tracker.update(RULES.observe(root, "white"))
    for index, move in enumerate(moves):
        root = RULES.apply_move(root, move)
        again = tracker.update(RULES.observe(root, "white"), move if index % 2 == 0 else None)
    assert again == sampled


def test_future_observation_can_select_a_history_omitted_from_sample():
    fen = "7k/8/8/8/8/8/8/K6R b - - 0 1"
    tracker = BeliefTracker(fen, sample_size=1)
    tracker.reset("white", 17)
    root = RULES.initial_state(fen)
    tracker.update(RULES.observe(root, "white"))
    # Both g7 and g8 are hidden from the rook on h1; h7 is visible and filtered.
    truth = RULES.apply_move(root, "h8g8")
    sample = tracker.update(RULES.observe(truth, "white"))
    omitted = "h8g7" if sample.hypotheses[0].candidate_moves == ("h8g8",) else "h8g8"
    truth = RULES.apply_move(RULES.apply_move(root, omitted), "h1g1")
    belief = tracker.update(RULES.observe(truth, "white"), "h1g1")
    assert belief.population_size == 1
    assert belief.hypotheses[0].candidate_moves == (omitted, "h1g1")


@pytest.mark.parametrize("changes", [
    {"visible_pieces": {"a1": "Q", "a2": None, "b1": None, "b2": None}},
    {"legal_moves": ("a1a2",)},
    {"captured_own_piece_at": "a1"},
    {"halfmove_clock": 1},
    {"terminal": True, "outcome": 0.0, "legal_moves": ()},
    {"visible_squares": ("a1",), "visible_pieces": {"a1": "K"}},
])
def test_all_observation_evidence_is_used_and_failure_is_retryable(changes):
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 1)
    obs = RULES.observe(RULES.initial_state(KINGS), "white")
    with pytest.raises(ValueError, match="no candidate"):
        tracker.update(replace(obs, **changes))
    assert tracker.update(obs).population_size == 1


def test_terminal_outcome_must_match():
    fen = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"
    tracker, state, _ = replay(fen, (), "white")
    obs = RULES.observe(RULES.apply_move(state, "e2e8"), "white")
    with pytest.raises(ValueError, match="no candidate"):
        tracker.update(replace(obs, outcome=-1.0), "e2e8")
    assert tracker.update(obs, "e2e8").ply == 1


def test_call_sequence_errors_and_input_mutation_do_not_advance_tracker():
    tracker = BeliefTracker(KINGS)
    state = RULES.initial_state(KINGS)
    obs = RULES.observe(state, "white")
    with pytest.raises(ValueError, match="reset"):
        tracker.update(obs)
    tracker.reset("white", 1)
    for wrong, move in [(obs, "a1b1"), (replace(obs, ply=1), None),
                        (RULES.observe(state, "black"), None)]:
        with pytest.raises(ValueError):
            tracker.update(wrong, move)
    tracker.update(obs)
    with pytest.raises(ValueError, match="expected ply"):
        tracker.update(obs)
    state = RULES.apply_move(state, "a1b1")
    next_obs = RULES.observe(state, "white")
    for wrong, move in [(next_obs, None), (next_obs, "bad"),
                        (replace(next_obs, ply=2), "a1b1"),
                        (replace(next_obs, side_to_move="white"), "a1b1")]:
        with pytest.raises(ValueError):
            tracker.update(wrong, move)
    obs.visible_pieces.clear()
    tracker.update(next_obs, "a1b1")
    state = RULES.apply_move(state, "h8g8")
    with pytest.raises(ValueError, match="opponent"):
        tracker.update(RULES.observe(state, "white"), "h8g8")
    assert tracker.update(RULES.observe(state, "white")).population_size == 3


def test_set_order_and_revealed_clock():
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 1)
    obs = RULES.observe(RULES.initial_state(KINGS), "white")
    assert tracker.update(replace(obs, visible_squares=obs.visible_squares[::-1],
                                  legal_moves=obs.legal_moves[::-1], halfmove_clock=0)).ply == 0


def test_capacity_exhaustion_does_not_silently_truncate_or_commit():
    tracker, state, _ = replay(KINGS, ["a1b1"], "white", max_candidates=1)
    next_obs = RULES.observe(RULES.apply_move(state, "h8g8"), "white")
    for _ in range(2):
        with pytest.raises(BeliefCapacityError, match="not committed"):
            tracker.update(next_obs)
        assert tracker.population_size == 1


@pytest.mark.parametrize("name,value", list(product(["sample_size", "max_candidates"],
                                                   [0, -1, 1.5, True])))
def test_invalid_configuration(name, value):
    with pytest.raises(ValueError):
        BeliefTracker(**{name: value})


def test_reset_override_is_game_local_and_black_can_move_first():
    tracker = BeliefTracker(KINGS)
    custom = KINGS.replace(" w ", " b ")
    tracker.reset("black", 1, initial_fen=custom)
    obs = RULES.observe(RULES.initial_state(custom), "black")
    tracker.update(obs)
    with pytest.raises(ValueError):
        tracker.reset("red", 1)
    with pytest.raises(ValueError):
        tracker.reset("black", 1.5)
    tracker.reset("white", 1)
    belief = tracker.update(RULES.observe(RULES.initial_state(KINGS), "white"))
    assert belief.hypotheses[0].fen == KINGS


def test_identical_private_streams_produce_identical_beliefs():
    _, _, a = replay(KINGS, ["a1b1", "h8g8"], "white", sample_size=2)
    _, _, b = replay(KINGS, ["a1b1", "h8g7"], "white", sample_size=2)
    assert a == b


def test_fen_keeps_double_push_en_passant_square():
    _, _, belief = replay(None, ["e2e4"], "white")
    assert belief.hypotheses[0].fen.split()[3] == "e3"


def test_hidden_promotions_remain_separate_possibilities():
    fen = "7k/8/8/8/8/8/p7/7K b - - 0 1"
    _, _, belief = replay(fen, ["a2a1q"], "white")
    assert {h.candidate_moves for h in belief.hypotheses} >= {
        ("a2a1" + piece,) for piece in "qrbn"
    }


@pytest.mark.parametrize("seed", range(8))
def test_random_short_games_keep_actual_path_in_exact_population(seed):
    rng = Random(seed)
    state = RULES.initial_state(KINGS)
    trackers = {p: BeliefTracker(KINGS) for p in ("white", "black")}
    for player, tracker in trackers.items():
        tracker.reset(player, seed)
        tracker.update(RULES.observe(state, player))
    path = ()
    for _ in range(6):
        if RULES.terminal(state):
            break
        mover = RULES.current_player(state)
        move = rng.choice(RULES.legal_moves(state))
        path += (move,)
        state = RULES.apply_move(state, move)
        for player, tracker in trackers.items():
            belief = tracker.update(RULES.observe(state, player), move if player == mover else None)
            assert (state.fen, path) in {(h.fen, h.candidate_moves) for h in belief.hypotheses}


@pytest.mark.parametrize("fen,moves,winner", [
    (None, ["e2e4", "f7f6", "d1h5", "g7g5", "h5e8"], "white"),
    ("4k3/4r3/8/8/8/8/8/4K3 b - - 0 1", ["e7e1"], "black"),
])
def test_shared_match_loop_with_real_trackers(fen, moves, winner):
    class ScriptedAgent:
        name = "belief-integration-script"

        def reset(self, player, seed):
            pass

        def act(self, turn):
            move = moves[turn.observation.ply]
            assert turn.belief.hypotheses
            return Decision(move, {m: float(m == move) for m in turn.observation.legal_moves})

    class RecordingTracker(BeliefTracker):
        def update(self, observation, own_move=None):
            belief = super().update(observation, own_move)
            self.last = observation
            return belief

    trackers = {p: RecordingTracker(fen, sample_size=4) for p in ("white", "black")}
    result = play_game(RulesReferee(fen), {p: ScriptedAgent() for p in trackers}, trackers,
                       MatchConfig(1000, 10, 17, "paper_fow_v1_proposed", "none", 1))
    assert result.winner == winner and not result.stopped_at_ply_limit
    assert all(t.last.terminal and t.last.ply == len(moves) for t in trackers.values())
