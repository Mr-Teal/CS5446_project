"""FoW repetition rights and agreement between the shared and ZS21 referees."""
import chess
import pytest

from fow_shared.values import fog_legal_moves, standard_fen, terminal_score
from pair_a_prep.rules_adapter import RuleState, RulesAdapter
from pair_a_prep.zs21.model import RefereeRules, position_key


def history(fen, cycle, mirror):
    board = chess.Board(fen)
    moves = [chess.Move.from_uci(uci) for uci in cycle.split()]
    if mirror:
        board = board.mirror()
        moves = [chess.Move(chess.square_mirror(m.from_square),
                            chess.square_mirror(m.to_square)) for m in moves]
    return board, moves


def check_referees(board, draw):
    before = standard_fen(board), tuple(board.move_stack), standard_fen(board.root())
    state = RuleState(board, len(board.move_stack))
    shared, zs21 = RulesAdapter(), RefereeRules()
    expected = ("repetition", 0.0) if draw else None
    assert terminal_score(board) == expected
    assert shared.terminal(state) == zs21.terminal(state)
    assert (shared.terminal(state) is not None) == draw
    for player in ("white", "black"):
        assert shared.observe(state, player) == zs21.observe(state, player)
    assert shared.legal_moves(state) == zs21.legal_moves(state)
    assert bool(fog_legal_moves(board)) != draw
    assert before == (standard_fen(board), tuple(board.move_stack), standard_fen(board.root()))


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("fen, cycle", [
    ("r3k1nr/p1p2ppp/8/1pP1n3/2PP2b1/8/PP3PPP/RNBK1B1R w kq b6 0 1",
     "b1c3 e5f3 c3b1 f3e5"),
    ("4k1n1/8/8/K2pP2r/8/8/8/1N6 w - d6 0 1", "b1c3 g8f6 c3b1 f6g8"),
], ids=["in-check", "exposes-king"])
def test_fow_only_ep_right_prevents_premature_repetition(fen, cycle, mirror):
    board, moves = history(fen, cycle, mirror)
    assert board.has_pseudo_legal_en_passant() and not board.has_legal_en_passant()
    initial = position_key(board)
    for move in moves * 2:
        check_referees(board, draw=False)
        assert move in fog_legal_moves(board)
        board.push(move)
    assert board.is_repetition(3)
    assert position_key(board) != initial
    check_referees(board, draw=False)
    board.push(moves[0])
    check_referees(board, draw=True)
    assert terminal_score(chess.Board(standard_fen(board))) is None


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("capturer", [False, True])
def test_only_an_available_ep_capture_distinguishes_positions(capturer, mirror):
    board, moves = history("2k5/8/8/1pP5/8/8/8/KN6 w - b6 0 1",
                           "b1c3 c8d8 c3b1 d8c8", mirror)
    if not capturer:
        board.remove_piece_at(chess.square_mirror(chess.C5) if mirror else chess.C5)
    assert board.has_pseudo_legal_en_passant() == capturer
    assert board.has_legal_en_passant() == capturer
    initial = position_key(board)
    for move in moves * 2:
        assert move in fog_legal_moves(board)
        board.push(move)
    assert (position_key(board) == initial) != capturer
    check_referees(board, draw=not capturer)
    if capturer:
        board.push(moves[0])
        check_referees(board, draw=True)


@pytest.mark.parametrize("mirror", [False, True])
def test_lost_castling_rights_still_distinguish_repeated_piece_placement(mirror):
    board, moves = history("4k1n1/8/8/8/8/8/8/4K2R w K - 0 1",
                           "h1h2 g8f6 h2h1 f6g8", mirror)
    initial = position_key(board)
    for move in moves * 2:
        assert move in fog_legal_moves(board)
        board.push(move)
    assert position_key(board) != initial
    check_referees(board, draw=False)
    board.push(moves[0])
    check_referees(board, draw=True)
