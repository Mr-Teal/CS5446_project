"""How many different games an arm holds: python different_games.py <records>/<arm> [...]

From the standard start a player that always plays its most likely move repeats itself, and the other
side can win the same short game many times. For each arm this prints the number of different games
(same colours, same moves), the result when each different game counts once, the results of games of
at most 20 plies and of longer games, and the move lists that were played more than once.
"""
import json
import sys
from collections import Counter
from pathlib import Path


def main():
    for name in sys.argv[1:]:
        rows = []
        for path in sorted(Path(name).glob("games-*/games.jsonl")):
            rows += [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]
        rows = [r for r in rows if r["status"] == "completed" and not r["stopped_at_ply_limit"]]

        def outcome(r):
            return "draw" if r["winner"] == "draw" else "win" if r["winner"] == r["player_a_color"] else "loss"

        def tally(part):
            count = Counter(part)
            return f"{count['win']}-{count['draw']}-{count['loss']}"

        lines = Counter((r["player_a_color"], tuple(p["move"] for p in r["plies"])) for r in rows)
        once = {(r["player_a_color"], tuple(p["move"] for p in r["plies"])): outcome(r) for r in rows}
        print(f"{Path(name).name}: {len(rows)} scored games, {len(lines)} different; each different game once: "
              f"{tally(once.values())}; games of at most 20 plies: {tally(outcome(r) for r in rows if len(r['plies']) <= 20)}; "
              f"longer games: {tally(outcome(r) for r in rows if len(r['plies']) > 20)}")
        for (colour, moves), times in lines.most_common():
            if times > 1:
                print(f"    {times} times with player A as {colour}, {len(moves)} plies: {' '.join(moves)}")


if __name__ == "__main__":
    main()
