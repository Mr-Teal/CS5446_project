"""How the PPO network's wins and losses look on the board: python how_games_end.py runs/<name> [...]

Each scored game is replayed from its recorded moves. Piece balance is player A's pieces minus the
opponent's (pawn 1, knight 3, bishop 3, rook 5, queen 9) on the last position before the king was taken.
"""
import json
import statistics
import sys
from pathlib import Path

import chess

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def balance(board: chess.Board, white_is_a: bool) -> int:
    total = sum(value * (len(board.pieces(kind, chess.WHITE)) - len(board.pieces(kind, chess.BLACK)))
                for kind, value in VALUES.items())
    return total if white_is_a else -total


def before_last_move(row: dict) -> int:
    board = chess.Board()
    white_is_a = row["player_a_color"] == "white"
    value = 0
    for ply in row["plies"]:
        value = balance(board, white_is_a)
        board.push(chess.Move.from_uci(ply["move"]))
    return value


for name in sys.argv[1:]:
    rows = []
    for path in sorted(Path(name).glob("games-*/games.jsonl")):
        rows += [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]
    rows = [r for r in rows if r["status"] == "completed" and r.get("termination") == "king_capture"]
    print(Path(name).name)
    for label, won in (("wins", True), ("losses", False)):
        group = [r for r in rows if (r["winner"] == r["player_a_color"]) == won]
        if not group:
            print(f"   {label}: none")
            continue
        ends = [before_last_move(r) for r in group]
        ahead, behind = sum(e > 0 for e in ends), sum(e < 0 for e in ends)
        print(f"   {label:6s} {len(group):3d}: piece balance at the end {statistics.mean(ends):+.1f} "
              f"(ahead in {ahead}, level in {len(group) - ahead - behind}, behind in {behind}); "
              f"plies median {statistics.median(len(r['plies']) for r in group):.0f}")
