"""Verify the illustrative capture-history example with the project rules.

Run from repository root with pair_a_prep and fow_shared on PYTHONPATH.
"""
from dataclasses import asdict
from pathlib import Path
import json
import chess
from pair_a_prep.rules_adapter import RulesAdapter

def example():
    rules = RulesAdapter()
    before_fen = '8/8/8/5k2/3N3q/8/8/K7 b - - 0 1'
    before = rules.initial_state(before_fen)
    after = rules.apply_move(before, 'h4d4')
    first, second = [asdict(rules.observe(s, 'white')) for s in (before, after)]
    assert 'q' not in first['visible_pieces'].values()
    assert 'q' not in second['visible_pieces'].values()
    assert first['visible_pieces']['d4'] == 'N'
    assert first['visible_pieces']['f5'] == 'k'
    assert 'd4' not in second['visible_squares']
    assert second['captured_own_piece_at'] == 'd4'
    assert not any(p == 'N' for p in second['visible_pieces'].values())
    assert before.board_copy().is_attacked_by(chess.WHITE, chess.F5)
    assert chess.square_distance(chess.F5, chess.D4) == 2
    assert 'f5d4' not in rules.legal_moves(before)
    # All hidden queen locations consistent with the first complete private view.
    branches = []
    for square in chess.SQUARES:
        if square in (chess.A1, chess.D4, chess.F5):
            continue
        board = chess.Board(None)
        for sq, p in [(chess.A1, 'K'), (chess.D4, 'N'), (chess.F5, 'k'), (square, 'q')]:
            board.set_piece_at(sq, chess.Piece.from_symbol(p))
        board.turn = chess.BLACK
        candidate = rules.initial_state(board.fen())
        if asdict(rules.observe(candidate, 'white')) != first:
            continue
        for move in rules.legal_moves(candidate):
            child = rules.apply_move(candidate, move)
            if asdict(rules.observe(child, 'white')) == second:
                branches.append({'queen_before': chess.square_name(square), 'move': move, 'after_fen': child.fen})
    assert len(branches) > 1
    assert {x['after_fen'] for x in branches} == {after.fen}
    assert all(chess.Board(x['after_fen']).piece_at(chess.D4).symbol() == 'q' for x in branches)
    # Current view alone also permits these other queen squares, even holding Kf5 fixed.
    alternatives = []
    for sq in ['d4', 'e4', 'h4']:
        b = after.board_copy();b.remove_piece_at(chess.D4)
        b.set_piece_at(chess.parse_square(sq), chess.Piece.from_symbol('q'))
        obs = asdict(rules.observe(rules.initial_state(b.fen()), 'white'))
        # Captured-square feedback and ply belong to history, not a board snapshot.
        for key in ['ply', 'captured_own_piece_at']:
            obs[key] = second[key]
        assert obs == second
        alternatives.append({'queen_square': sq, 'fen': b.fen(), 'history_consistent': sq == 'd4'})
    return {'purpose': 'Illustrative history-based state inference, not a strength result',
            'assumptions': 'Known remaining material: White king and knight; Black king and queen. Black makes exactly one move between views. The visible black king starts on f5. The hidden queen starting square is not supplied to the player.',
            'before_fen': before_fen, 'hidden_black_move': 'h4d4', 'after_fen': after.fen,
            'white_before': first, 'white_after': second, 'matching_hidden_transitions': branches,
            'current_view_alternatives': alternatives,
            'inference': 'The queen must have captured on d4 and is there immediately after this Black move. The king on f5 cannot reach d4 in one king move. Its being attacked by the knight is illustrative; distance, not check legality, rules it out. The queen may move again later, requiring belief propagation.'}

if __name__ == '__main__':
    data = example()
    path = Path(__file__).with_name('capture-history-example.json')
    if path.exists():
        assert json.loads(path.read_text()) == json.loads(json.dumps(data))
    else:
        path.write_text(json.dumps(data, indent=2))
    print(f"Verified queen hidden in both views, capture on d4, king excluded by distance, {len(data['matching_hidden_transitions'])} consistent transitions collapsing to one successor board.")
