"""How much faster quick Stockfish and Network 1 are inside a search (new_game_each_call=False)
than when every call starts a new game (True, as for labels).

    .venv/bin/python experiments/readme_checks/time_new_game_each_call.py <d2-check> checkpoints/timing-new-game-each-call.json

On the 300 parents scripts/benchmark_linear.py times (the first 300 sorted unique parent FENs of
the train split), each evaluator scores every parent's children --repeats times, in an order that
rotates between evaluators, after one warm-up call each that is not timed. Network 1 runs on
--device. Writes the medians and the two ratios. Refuses to overwrite.
"""
import argparse
import hashlib
import json
import statistics
import time
from contextlib import ExitStack
from pathlib import Path

from pairb.data import read_records, split_of
from pairb.network_evaluator import NetworkEvaluator
from pairb.provenance import data_files, git_commit, runtime
from pairb.stockfish import StockfishEvaluator

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--device", default="mps", help="where Network 1 runs")
    ap.add_argument("--stockfish", default="stockfish")
    args = ap.parse_args()
    if Path(args.out).exists():
        raise SystemExit(f"{args.out} exists")
    parents = sorted({r["parent_fen"] for r in read_records(args.data) if split_of(r["game_id"]) == "train"})[:300]
    checkpoint = ROOT / "checkpoints" / "net1-v2" / "best.pt"
    with ExitStack() as stack:
        evaluators = {}
        for fresh in (True, False):
            evaluators[f"stockfish_d1_new_game_{fresh}".lower()] = stack.enter_context(
                StockfishEvaluator(1, path=args.stockfish, new_game_each_call=fresh))
            evaluators[f"network1_new_game_{fresh}".lower()] = stack.enter_context(NetworkEvaluator.from_checkpoint(
                checkpoint, stockfish_path=args.stockfish, device=args.device, new_game_each_call=fresh))
        for ev in evaluators.values():
            ev.evaluate_children(parents[0])  # warm-up, not timed
        names, times = list(evaluators), {name: [] for name in evaluators}
        for repeat in range(args.repeats):
            for fen in parents:
                for name in names[repeat % len(names):] + names[:repeat % len(names)]:
                    started = time.perf_counter()
                    evaluators[name].evaluate_children(fen)
                    times[name].append((time.perf_counter() - started) * 1000)
    medians = {name: statistics.median(t) for name, t in times.items()}
    report = {
        "source": data_files(args.data), "split": "train", "parents": len(parents), "repeats": args.repeats,
        "parent_selection": "sorted unique parent FENs, first 300 (as scripts/benchmark_linear.py)",
        "parent_fens_sha256": hashlib.sha256("\n".join(parents).encode()).hexdigest(),
        "network_device": args.device, "engine_options": {"threads": 1, "hash_mb": 16, "depth": 1},
        "median_ms": medians,
        "speedup_stockfish_d1": medians["stockfish_d1_new_game_true"] / medians["stockfish_d1_new_game_false"],
        "speedup_network1": medians["network1_new_game_true"] / medians["network1_new_game_false"],
        "git_commit": git_commit(), "runtime": runtime(),
    }
    with open(args.out, "x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print({k: round(v, 2) for k, v in medians.items()},
          f"speed-up: Stockfish {report['speedup_stockfish_d1']:.2f}x, Network 1 {report['speedup_network1']:.2f}x")


if __name__ == "__main__":
    main()
