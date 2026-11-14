"""Verify the rook-capture history example with the project's RulesAdapter.

Run from repository root with pair_a_prep and fow_shared on PYTHONPATH.
The current-view projection deliberately excludes ply and capture-event history.
"""
from dataclasses import asdict
from pathlib import Path
import json
import chess
from pair_a_prep.rules_adapter import RulesAdapter


def current_view(observation):
    return {k: observation[k] for k in ('player', 'side_to_move', 'visible_squares',
            'visible_pieces', 'legal_moves', 'terminal', 'outcome')}


def example():
    rules = RulesAdapter()
    before_fen = '8/5k2/3N3r/8/3K4/8/8/8 b - - 0 1'
    before = rules.initial_state(before_fen)
    after = rules.apply_move(before, 'h6d6')
    first, second = [asdict(rules.observe(state, 'white')) for state in (before, after)]
    assert 'r' not in first['visible_pieces'].values()
    assert 'r' not in second['visible_pieces'].values()
    assert first['visible_pieces']['d6'] == 'N'
    assert first['visible_pieces']['f7'] == 'k'
    assert second['visible_pieces']['d4'] == 'K'
    assert 'd6' not in second['visible_squares']
    assert second['captured_own_piece_at'] == 'd6'
    assert len(second['legal_moves']) == 8
    assert before.board_copy().is_attacked_by(chess.WHITE, chess.F7)
    assert chess.square_distance(chess.F7, chess.D6) == 2
    assert 'f7d6' not in rules.legal_moves(before)
    assert after.board_copy().is_attacked_by(chess.BLACK, chess.D4)
    branches = []
    for square in chess.SQUARES:
        if square in (chess.D4, chess.D6, chess.F7):
            continue
        board = chess.Board(None)
        for sq, piece in [(chess.D4, 'K'), (chess.D6, 'N'), (chess.F7, 'k'), (square, 'r')]:
            board.set_piece_at(sq, chess.Piece.from_symbol(piece))
        board.turn = chess.BLACK
        candidate = rules.initial_state(board.fen())
        if asdict(rules.observe(candidate, 'white')) != first:
            continue
        for move in rules.legal_moves(candidate):
            child = rules.apply_move(candidate, move)
            if asdict(rules.observe(child, 'white')) == second:
                branches.append({'rook_before': chess.square_name(square), 'move': move, 'after_fen': child.fen})
    assert len(branches) == 9
    assert {branch['after_fen'] for branch in branches} == {after.fen}
    alternatives = []
    for label, sq in zip('ABC', ['c6', 'e6', 'd6']):
        board = after.board_copy()
        board.remove_piece_at(chess.D6)
        board.set_piece_at(chess.parse_square(sq), chess.Piece.from_symbol('r'))
        observation = asdict(rules.observe(rules.initial_state(board.fen()), 'white'))
        assert current_view(observation) == current_view(second)
        alternatives.append({'label': label, 'rook_square': sq, 'fen': board.fen(),
                             'history_consistent': sq == 'd6'})
    return {'purpose': 'Illustrative history-based state inference, not a strength result',
            'assumptions': 'Known remaining material: White king and knight; Black king and rook. Black makes exactly one move between the views. Its king is visible before the capture; the rook is hidden. The rook starting square is not supplied to the player.',
            'white_king_square': 'd4', 'captured_knight_square': 'd6',
            'before_fen': before_fen, 'hidden_black_move': 'h6d6', 'after_fen': after.fen,
            'white_before': first, 'white_after': second,
            'current_view_only': current_view(second),
            'current_view_scope': 'Current visible squares, pieces and legal moves, without ply or capture-event history. This is the information shown on the standalone fog-view slide.',
            'matching_hidden_transitions': branches, 'current_view_alternatives': alternatives,
            'inference': 'The rook must have captured on d6 and is there immediately afterward. The previously visible black king cannot reach the knight in one king move. Distance, not check legality, excludes it. White king stays on d4 throughout, as in the opening example. A/B/C reuse the opening rook locations; only C explains the capture history. Later opponent moves require belief propagation.'}


if __name__ == '__main__':
    data = example()
    path = Path(__file__).with_name('capture-history-example.json')
    normalized = json.loads(json.dumps(data))
    if path.exists():
        assert json.loads(path.read_text()) == normalized
    else:
        path.write_text(json.dumps(data, indent=2))
    print('Verified hidden rook capture, unchanged White king, eight legal moves, three identical current views and nine historical branches converging to the rook on the capture square.')
