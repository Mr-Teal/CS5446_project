"""How far a parent's MultiPV depth-1 score of a child is from the child's own depth-1 value.

    .venv/bin/python experiments/readme_checks/d1_parent_vs_own.py <d2-check> checkpoints/belief-v1-d1/d1-parent-vs-own.json

For the first --limit sorted unique parent FENs of the train split, every child row the rules do not
decide: its stored d1 (the parent's MultiPV call at depth 1, as D2 made it) against the child's own
value from StockfishEvaluator(depth=1).board_value, both from White's view, with ucinewgame before
each call as for labels. The belief network trained on boards' own depth-1 values, so this is the
gap a node's children would show it. Refuses to overwrite.
"""
import argparse
import hashlib
import json
import statistics

import chess
import numpy as np

from pairb.data import read_records, split_of
from pairb.provenance import data_files, git_commit, runtime
from pairb.stockfish import StockfishEvaluator


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--stockfish", default="stockfish")
    args = ap.parse_args()
    source = data_files(args.data)
    rows = [r for r in read_records(args.data) if split_of(r["game_id"]) == "train" and r["rule"] is None]
    parents = sorted({r["parent_fen"] for r in rows})[:args.limit]
    chosen = set(parents)
    stored, own, decided = [], [], 0
    with StockfishEvaluator(1, path=args.stockfish, new_game_each_call=True) as sf:
        for r in rows:
            if r["parent_fen"] not in chosen:
                continue
            value, by_rule = sf.board_value(chess.Board(r["fen"]))
            if by_rule:  # decided by a rule only once the history is gone; not a depth-1 value
                decided += 1
                continue
            stored.append(r["d1"]["v"])
            own.append(value)
    diff = np.abs(np.array(stored) - np.array(own))
    report = {
        "source": source, "split": "train", "parents": len(parents),
        "parent_selection": "sorted unique parent FENs, first limit (as scripts/benchmark_linear.py)",
        "parent_fens_sha256": hashlib.sha256("\n".join(parents).encode()).hexdigest(),
        "children": int(len(diff)), "children_decided_by_rule_alone": decided,
        "mean_abs_difference": float(diff.mean()), "median_abs_difference": float(np.median(diff)),
        "p95_abs_difference": float(np.percentile(diff, 95)), "share_over_0.1": float((diff > 0.1).mean()),
        "settings": {"depth": 1, "threads": 1, "hash_mb": 16, "new_game_each_call": True,
                     "stored": "d1.v of the D2 record: the parent's MultiPV depth-1 score of the child, White's view",
                     "own": "StockfishEvaluator(depth=1).board_value(child), White's view"},
        "stored_mean": statistics.mean(stored), "own_mean": statistics.mean(own),
        "git_commit": git_commit(), "runtime": runtime(),
    }
    with open(args.out, "x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(f"{len(diff)} children of {len(parents)} parents: mean |parent's d1 - own d1| {diff.mean():.4f} -> {args.out}")


if __name__ == "__main__":
    main()
