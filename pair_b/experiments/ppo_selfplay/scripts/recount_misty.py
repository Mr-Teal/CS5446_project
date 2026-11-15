"""Recount the misty match by replaying every game: python scripts/recount_misty.py <run folder>

The run folder holds worker-*/games.jsonl as the misty harness wrote them. Each game is replayed with
python-chess from its recorded moves. The winner is the side whose opponent's king is gone; a draw is
a threefold repetition or the fifty-move rule. The replayed result must equal the record's own result.
"Ours" is the PPO network. This script needs only python-chess.
"""
import json
import math
import sys
from pathlib import Path

import chess


def wilson(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    denominator = 1 + z * z / n
    centre = (score + z * z / (2 * n)) / denominator
    half = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def replay(moves: list[str]) -> str | None:
    board = chess.Board()
    for uci in moves:
        board.push(chess.Move.from_uci(uci))
    if board.king(chess.WHITE) is None:
        return "black"
    if board.king(chess.BLACK) is None:
        return "white"
    if board.is_repetition(3) or board.halfmove_clock >= 100:
        return "draw"
    return None


def main():
    folder = Path(sys.argv[1])
    rows = []
    for path in sorted(folder.glob("worker-*/games.jsonl")):
        rows += [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]
    rows.sort(key=lambda r: r["game"])
    tally = {"white": [0, 0, 0], "black": [0, 0, 0]}
    print("game  seed  ours   result  plies")
    for r in rows:
        winner = replay(r["moves"])
        if r["status"] != "completed" or winner is None:
            print(f"{r['game']:4d}  {r['seed']}  {r['our_color']:5s}  not scored ({r.get('error')})")
            continue
        assert winner == r["winner"], f"game {r['game']}: the board says {winner}, the record says {r['winner']}"
        index = 1 if winner == "draw" else 0 if winner == r["our_color"] else 2
        tally[r["our_color"]][index] += 1
        print(f"{r['game']:4d}  {r['seed']}  {r['our_color']:5s}  {('win', 'draw', 'loss')[index]:6s}  {len(r['moves'])}")
    w, d, l = (tally["white"][i] + tally["black"][i] for i in range(3))
    n = w + d + l
    score = (w + d / 2) / n
    low, high = wilson(score, n)
    print(f"\nours: {w}-{d}-{l} of {n}, score {score:.3f} [{low:.3f}, {high:.3f}]; "
          f"as White {'-'.join(map(str, tally['white']))}, as Black {'-'.join(map(str, tally['black']))}")


if __name__ == "__main__":
    main()
