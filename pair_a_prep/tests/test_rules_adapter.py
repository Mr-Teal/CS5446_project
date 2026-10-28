"""State transitions, branch isolation and history-dependent rule outcomes."""

import chess
import pytest

from pair_a_prep.fixtures import compare_result, load_suite
from pair_a_prep.rules_adapter import RulesAdapter


@pytest.mark.parametrize("case", load_suite()["cases"], ids=lambda c: c["id"])
def test_adapter_moves_and_outcomes_match_existing_cases(case):
    rules = RulesAdapter()
    state = rules.initial_state(case.get("initial_fen", case["fen"]))
    for move in case.get("moves_uci", []):
        state = rules.apply_move(state, move)
    assert state.fen == chess.Board(case["fen"]).fen(en_passant="fen")
    ended = rules.terminal(state)
    expected = {k: v for k, v in case["expect"].items()
                if k.startswith("legal") or k in ("terminal", "winner")}
    assert compare_result({**case, "expect": expected}, {
        "legal_moves": rules.legal_moves(state), "terminal": ended is not None,
        "winner": ended.winner if ended else None,
    }) == []


def test_sibling_states_and_exported_boards_are_independent():
    rules = RulesAdapter()
    parent = rules.initial_state()
    left = rules.apply_move(parent, "e2e4")
    right = rules.apply_move(parent, "d2d4")
    grandchild = rules.apply_move(left, "e7e5")
    exported = left.board_copy()
    exported.clear()
    assert parent.fen == chess.STARTING_FEN
    assert (parent.ply, left.ply, right.ply, grandchild.ply) == (0, 1, 1, 2)
    assert left.board_copy().piece_at(chess.E4) == chess.Piece(chess.PAWN, chess.WHITE)
    assert right.board_copy().piece_at(chess.E2) == chess.Piece(chess.PAWN, chess.WHITE)
    assert len(left.board_copy().move_stack) == 1
    assert rules.current_player(left) == "black"


def test_repetition_survives_successors_but_not_fen_restart():
    rules = RulesAdapter()
    state = rules.initial_state()
    for move in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
        parent = state
        state = rules.apply_move(state, move)
    assert rules.terminal(state).reason == "threefold_repetition"
    assert len(parent.board_copy().move_stack) == 7
    assert rules.terminal(rules.initial_state(state.fen)) is None
    with pytest.raises(ValueError):
        rules.apply_move(state, "e2e4")


def test_king_capture_and_forced_loss_are_distinct():
    rules = RulesAdapter()
    before = rules.initial_state("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
    after = rules.apply_move(before, "e2e8")
    assert rules.terminal(before) is None
    assert (rules.terminal(after).winner, rules.terminal(after).reason) == ("white", "king_capture")
    assert (after.captured_player, after.captured_square) == ("black", "e8")
    assert rules.terminal(rules.initial_state("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")) is None


def test_en_passant_capture_metadata_and_reset():
    rules = RulesAdapter()
    state = rules.initial_state("4k3/8/8/4Pp2/8/8/8/4K3 w - f6 0 1")
    captured = rules.apply_move(state, "e5f6")
    assert (captured.captured_player, captured.captured_square) == ("black", "f5")
    assert captured.board_copy().piece_at(chess.F5) is None
    quiet = rules.apply_move(captured, "e8d8")
    assert quiet.captured_player is quiet.captured_square is None


@pytest.mark.parametrize("move", ["e2e5", "0000", "e2e4q", "bad"])
def test_invalid_actions_leave_input_unchanged(move):
    rules = RulesAdapter()
    state = rules.initial_state()
    with pytest.raises(ValueError):
        rules.apply_move(state, move)
    assert state.fen == chess.STARTING_FEN and state.ply == 0
