"""Reproduce PR4's reported history loss without modifying evaluator source."""
import argparse
import json
import chess
from fow_shared.values import terminal_score
from pairb.stockfish import StockfishEvaluator
from pairb.material import MaterialEvaluator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stockfish-path', default='stockfish')
    parser.add_argument('--source-commit', required=True, help='verified revision under test')
    args = parser.parse_args()
    board = chess.Board('6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1')
    moves = ['f7f6', 'g8h8', 'f6f7', 'h8g8', 'f7f6', 'g8h8', 'f6f7']
    for uci in moves:
        board.push(chess.Move.from_uci(uci))
    child = board.copy(stack=True)
    child.push(chess.Move.from_uci('h8g8'))
    with StockfishEvaluator(depth=1, path=args.stockfish_path) as evaluator:
        actual = evaluator.children_values(board)['h8g8']
    material = MaterialEvaluator().children_values(board)["h8g8"]
    result = dict(source_commit=args.source_commit,
                  initial_fen='6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1', moves=moves,
                  candidate_move='h8g8', child_repetition=child.is_repetition(3),
                  expected_rule=terminal_score(child), expected_white_value=0.0,
                  actual_white_value=actual[0], actual_by_rule=actual[1],
                  bug_reproduced=actual != (0.0, True) or material != (0.0, True),
                  material_with_history=material[0], material_by_rule=material[1],
                  material_fen_only=MaterialEvaluator().evaluate_children(board.fen())['h8g8'],
                  material_note='Public FEN-only method cannot recover history; this differs from Stockfish children_values receiving a Board with history.')
    print(json.dumps(result, indent=2))
    return 1 if result["bug_reproduced"] else 0

if __name__ == '__main__':
    raise SystemExit(main())
