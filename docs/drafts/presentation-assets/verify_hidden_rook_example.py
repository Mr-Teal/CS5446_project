"""Run from a checkout: python docs/drafts/presentation-assets/verify_hidden_rook_example.py."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
import chess
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pair_a_prep.rules_adapter import RulesAdapter
r = RulesAdapter()
evidence = json.loads(Path(__file__).with_name('hidden-rook-example.json').read_text())
states = [r.apply_move(r.initial_state(evidence['public_start_fen']), move)
          for move in evidence['hidden_black_moves']]
observations = [json.loads(json.dumps(asdict(r.observe(state, 'white')))) for state in states]
assert len(states) == 3 and all(o == observations[0] for o in observations)
assert observations[0] == evidence['white_observation']
assert len(observations[0]['legal_moves']) == 8
assert sorted(row['white_move'] for row in evidence['results']) == observations[0]['legal_moves']
for row in evidence['results']:
    actual = []
    for state in states:
        child = r.apply_move(state, row['white_move'])
        captures = []
        for reply in r.legal_moves(child):
            result = r.terminal(r.apply_move(child, reply))
            if result and result.winner == 'black':
                captures.append(reply)
        actual.append(captures)
    assert actual == row['black_king_capture_replies']
for i, possibility in enumerate(evidence['possibilities']):
    risky = [row['white_move'] for row in evidence['results']
             if row['black_king_capture_replies'][i]]
    assert risky == possibility['moves_allowing_immediate_rook_capture']
    board = chess.Board(evidence['fens'][i])
    assert board.is_attacked_by(chess.BLACK, chess.D4) == possibility['king_already_attacked']
assert not any(all(not replies for replies in row['black_king_capture_replies'])
               for row in evidence['results'])
print('Verified eight legal moves, three identical White observations, all 24 move/state capture outcomes and hidden check in C.')
