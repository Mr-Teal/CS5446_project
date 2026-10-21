"""Does a depth-1 call give different values when the engine keeps its hash from an earlier search?

    .venv/bin/python experiments/matches/engine_policy_probe.py --out experiments/matches/engine-policy-probe.json

Bryan's probe on PR #16, committed: the position is scored fresh, then after one search of the start
position with the hash kept (new_game_each_call=False, as inside a search and in play_matches.py within
a game), then the same with the hash cleared before every call (new_game_each_call=True, Bryan's runner).
Reports how many of the position's moves change value and by how much, at depth 1 and depth 11. A few
seconds; depth 11 dominates.
"""
import argparse
import json
import sys
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pairb.stockfish import StockfishEvaluator  # noqa: E402

FEN = "r1bq1bn1/pppppkp1/n2r1p2/7p/2PP4/7N/PPQNPPPP/1RB1KB1R w K - 2 7"  # the position in Bryan's review


def probe(depth: int, keep_hash: bool) -> dict:
    with StockfishEvaluator(depth=depth, new_game_each_call=not keep_hash) as fresh:
        before = fresh.evaluate_children(FEN)
    with StockfishEvaluator(depth=depth, new_game_each_call=not keep_hash) as used:
        used.evaluate_children(chess.STARTING_FEN)
        after = used.evaluate_children(FEN)
    deltas = {m: after[m] - before[m] for m in before}
    changed = {m: d for m, d in deltas.items() if d != 0}
    return {"depth": depth, "hash_kept_between_calls": keep_hash, "moves": len(before), "changed": len(changed),
            "max_abs_change": max((abs(d) for d in deltas.values()), default=0.0),
            "best_move_before": max(before, key=before.get), "best_move_after": max(after, key=after.get)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new file")
    runs = [probe(depth, keep) for depth in (1, 11) for keep in (True, False)]
    with StockfishEvaluator(depth=1) as e:
        engine = e.name
    report = {"fen": FEN, "engine": engine, "runs": runs,
              "note": "hash kept between calls is play_matches.py's within-game policy (cleared before every game); "
                      "hash cleared before every call is pairb.match_experiment's policy"}
    out.write_text(json.dumps(report, indent=2) + "\n")
    for r in runs:
        print(f"depth {r['depth']:2d} hash {'kept' if r['hash_kept_between_calls'] else 'cleared'}: "
              f"{r['changed']} of {r['moves']} values changed, max {r['max_abs_change']:.4f}, "
              f"best move {r['best_move_before']} -> {r['best_move_after']}")


if __name__ == "__main__":
    main()
