"""Time complete evaluate_children calls on D2 parents, including encoding and Stockfish.

Uses search mode (new_game_each_call=False). Reports wall time, not playing strength.
Optional Network 1 runs on CPU so timings have an explicit device and need no GPU sync.
"""
import argparse
import hashlib
import statistics
import shutil
import time
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from pairb.data import read_records, split_of
from pairb.linear_evaluator import LinearEvaluator
from pairb.linear_workflow import provenance, runtime, write_json
from pairb.material import MaterialEvaluator
from pairb.stockfish import StockfishEvaluator


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", choices=["train", "val", "test"], default="val")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--stockfish-path", default="stockfish")
    ap.add_argument("--net1-run")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.limit < 1 or args.repeats < 1:
        ap.error("limit and repeats must be positive")
    if args.split == "test" and not args.final:
        ap.error("test split is reserved for final evaluation; pass --final")
    source = provenance(args.data)
    parents = sorted({r["parent_fen"] for r in read_records(args.data)
                      if split_of(r["game_id"]) == args.split})[:args.limit]
    if provenance(args.data) != source:
        ap.error("dataset changed while reading; use a finished label run")
    if not parents:
        ap.error("no parents in requested split")
    checkpoint = Path(args.run) / "best.npz"
    report = {"source": source, "runtime": runtime(), "split": args.split,
              "parents": len(parents), "repeats": args.repeats,
              "parent_selection": "sorted unique parent FENs, first limit",
              "parent_fens_sha256": hashlib.sha256("\n".join(parents).encode()).hexdigest(),
              "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
              "engine_options": {"threads": 1, "hash_mb": 16, "depth": 1,
                                 "new_game_each_call": False}, "evaluators": {}}
    with ExitStack() as stack:
        sf = stack.enter_context(StockfishEvaluator(1, path=args.stockfish_path, new_game_each_call=False))
        linear = stack.enter_context(LinearEvaluator.from_checkpoint(
            checkpoint, stockfish_path=args.stockfish_path, new_game_each_call=False))
        evaluators = {"material": MaterialEvaluator(), "d1": sf, "linear": linear}
        report["engine_id"] = dict(sf.engine.id)
        binary = shutil.which(args.stockfish_path)
        report["engine_binary_sha256"] = hashlib.sha256(Path(binary).read_bytes()).hexdigest() if binary else None
        if args.net1_run:
            from pairb.network_evaluator import NetworkEvaluator
            evaluators["network_cpu"] = stack.enter_context(NetworkEvaluator.from_checkpoint(
                Path(args.net1_run) / "best.pt", stockfish_path=args.stockfish_path,
                new_game_each_call=False, device="cpu"))
            report["network_checkpoint_sha256"] = hashlib.sha256(
                (Path(args.net1_run) / "best.pt").read_bytes()).hexdigest()
        samples = {name: [] for name in evaluators}
        counts = []
        for ev in evaluators.values():
            ev.evaluate_children(parents[0])  # warm up, excluded from timing
        # Rotate evaluator order to reduce systematic ordering bias; engines are separate.
        names = list(evaluators)
        for repeat in range(args.repeats):
            for fen in parents:
                coverage = None
                for name in names[repeat % len(names):] + names[:repeat % len(names)]:
                    start = time.perf_counter()
                    values = evaluators[name].evaluate_children(fen)
                    samples[name].append((time.perf_counter() - start) * 1000)
                    if coverage is not None and set(values) != coverage:
                        raise ValueError("evaluator legal-move coverage mismatch")
                    coverage = set(values)
                counts.append(len(coverage))
        report["mean_children"] = statistics.mean(counts)
        for name, times in samples.items():
            report["evaluators"][name] = {"name": evaluators[name].name,
                "calls": len(times), "median_ms": statistics.median(times),
                "p95_ms": float(np.percentile(times, 95)), "mean_ms": statistics.mean(times)}
    write_json(args.out, report)
    print({k: round(v["median_ms"], 3) for k, v in report["evaluators"].items()})


if __name__ == "__main__":
    main()
