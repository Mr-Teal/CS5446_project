import chess

from pair_a_prep.fixtures import board_for_case, compare_result, load_suite


def test_fixture_replays_and_orthodox_reference_annotations():
    suite = load_suite()
    for case in suite["cases"]:
        board = board_for_case(case)
        orthodox = case.get("orthodox", {})
        for move in orthodox.get("illegal_moves", []):
            assert chess.Move.from_uci(move) not in board.legal_moves
        for name in ("checkmate", "stalemate", "insufficient_material"):
            if name in orthodox:
                assert getattr(board, "is_" + name)() == orthodox[name]
        if case["id"] == "threefold_needs_history":
            assert board.is_repetition(3)
            assert not chess.Board(case["fen"]).is_repetition(3)


def test_partial_expectations_detect_wrong_visibility_and_hidden_counters():
    case = next(c for c in load_suite()["cases"] if c["id"] == "initial_white")
    errors = compare_result(case, {"terminal": False, "legal_moves": [],
                                  "visible_squares": ["e8"], "halfmove_clock": 0})
    assert any("legal" in error for error in errors)
    assert any("visible" in error for error in errors)
    assert "hidden field exposed: halfmove_clock" in errors


def test_empty_visible_square_cannot_be_replaced_by_missing_information():
    case = next(c for c in load_suite()["cases"] if c["id"] == "pawn_capture_reveals_target")
    errors = compare_result(case, {"terminal": False, "legal_moves": ["e4f5"],
                                  "visible_squares": ["f5", "e5"], "visible_pieces": {"f5": "n"}})
    assert "wrong/missing observed piece at e5" in errors


def test_review_counterexample_castle_reaches_an_unattacked_square():
    case = next(c for c in load_suite()["cases"] if c["id"] == "castle_escapes_orthodox_checkmate")
    board = board_for_case(case)
    assert board.is_checkmate() and board.has_kingside_castling_rights(chess.WHITE)
    assert board.piece_at(chess.F1) is None and board.piece_at(chess.G1) is None
    # push applies a supplied move without validating legality; this check is
    # geometry only. A future FoW adapter must independently generate this move.
    board.push(chess.Move.from_uci("e1g1"))
    assert board.king(chess.WHITE) == chess.G1
    assert not board.is_attacked_by(chess.BLACK, chess.G1)
