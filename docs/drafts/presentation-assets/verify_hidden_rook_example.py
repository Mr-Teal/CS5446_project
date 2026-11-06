"""Run from a repository checkout: python docs/drafts/presentation-assets/verify_hidden_rook_example.py."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pair_a_prep.rules_adapter import RulesAdapter
r = RulesAdapter()
evidence = json.loads(Path(__file__).with_name('hidden-rook-example.json').read_text())
start = evidence['public_start_fen']
states = [r.apply_move(r.initial_state(start), move) for move in evidence['hidden_black_moves']]
assert asdict(r.observe(states[0], 'white')) == asdict(r.observe(states[1], 'white'))
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
print('Same White evidence and all displayed immediate-capture consequences verified.')
