"""Time careful Stockfish (depth 11) on the parents the README's other timings use.

    .venv/bin/python experiments/readme_checks/time_stockfish_d11.py <d2-check> checkpoints/timing-stockfish-d11.json

One StockfishEvaluator(depth=11).evaluate_children call on every --step-th of the 300 parents
scripts/benchmark_linear.py times (the first 300 sorted unique parent FENs of the train split;
the first few sorted FENs alone are not typical), with new_game_each_call=False as inside a
search, after one warm-up call that is not timed. Writes the median, 95th percentile and mean, and
the settings. Refuses to overwrite.
"""
import argparse
import hashlib
import json
import shutil
import statistics
import time
from pathlib import Path

import numpy as np

from pairb.data import read_records, split_of
from pairb.provenance import data_files, git_commit, runtime
from pairb.stockfish import StockfishEvaluator


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--step", type=int, default=10, help="time every step-th of the 300 parents (10: 30 of them)")
    ap.add_argument("--stockfish", default="stockfish")
    args = ap.parse_args()
    source = data_files(args.data)
    everything = sorted({r["parent_fen"] for r in read_records(args.data) if split_of(r["game_id"]) == "train"})
    parents = everything[:300][::args.step]
    times, children = [], []
    with StockfishEvaluator(11, path=args.stockfish, new_game_each_call=False) as sf:
        sf.evaluate_children(parents[0])  # warm-up, not timed
        for fen in parents:
            started = time.perf_counter()
            values = sf.evaluate_children(fen)
            times.append((time.perf_counter() - started) * 1000)
            children.append(len(values))
        engine = dict(sf.engine.id)
    binary = shutil.which(args.stockfish)
    report = {
        "source": source, "split": "train", "parents": len(parents),
        "parent_selection": "every step-th of the first 300 sorted unique parent FENs (scripts/benchmark_linear.py's 300)",
        "step": args.step,
        "parent_fens_sha256": hashlib.sha256("\n".join(parents).encode()).hexdigest(),
        "first_300_parent_fens_sha256": hashlib.sha256("\n".join(everything[:300]).encode()).hexdigest(),
        "engine_options": {"threads": 1, "hash_mb": 16, "depth": 11, "new_game_each_call": False},
        "engine_id": engine, "engine_binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest() if binary else None,
        "mean_children": statistics.mean(children),
        "median_ms": statistics.median(times), "p95_ms": float(np.percentile(times, 95)), "mean_ms": statistics.mean(times),
        "git_commit": git_commit(), "runtime": runtime(),
    }
    with open(args.out, "x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(f"depth 11: median {report['median_ms']:.0f} ms per node over {len(parents)} parents -> {args.out}")


if __name__ == "__main__":
    main()
