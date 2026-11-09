"""Attach quick Stockfish's depth-1 value to every hypothesis board of a solver-label folder.

Writes a copy of the folder in which each record's decision.diagnostics gains "d1:<i>" for hypothesis i,
the convention Pair B's loader (pairb.belief_data) and validator (--require-d1) expect: the value from
the acting player's view, finite, in [-1, 1], from StockfishEvaluator(depth=1).evaluate_boards. Records
are copied as raw JSON so nothing else changes; progress.jsonl and manifest.json are copied as they are.
The solver labels themselves are untouched; d1 is an extra input, used only with train_belief_net.py --use-d1.

usage: python add_d1.py <source folder> <destination folder> [--stockfish /usr/games/stockfish] [--workers 4]
Runs where pairb imports (host venv with PYTHONPATH=<repo>:<repo>/pair_b/src); no torch.
"""
import argparse
import json
from multiprocessing import Pool
from pathlib import Path
import shutil
import time

_engine = None


def _init(path):
    global _engine
    from pairb.stockfish import StockfishEvaluator
    _engine = StockfishEvaluator(depth=1, path=path)


def _one_part(args):
    src, dst = args
    n_records = n_boards = 0
    with open(src, encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            record = json.loads(line)
            player = record["agent_input"]["observation"]["player"]
            fens = [h["fen"] for h in record["agent_input"]["belief"]["hypotheses"]]
            values = _engine.evaluate_boards(fens, player)
            diagnostics = record["decision"].setdefault("diagnostics", {})
            for i, v in enumerate(values):
                diagnostics[f"d1:{i}"] = float(max(-1.0, min(1.0, v)))
            fout.write(json.dumps(record) + "\n")
            n_records += 1
            n_boards += len(fens)
    return src.name, n_records, n_boards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("destination")
    ap.add_argument("--stockfish", default="/usr/games/stockfish")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pattern", default="part-*.jsonl")
    a = ap.parse_args()
    src, dst = Path(a.source), Path(a.destination)
    if dst.exists():
        raise SystemExit(f"{dst} exists; refusing to overwrite")
    dst.mkdir(parents=True)
    parts = [p for p in sorted(src.glob(a.pattern)) if p.stat().st_size > 0]
    for extra in ("progress.jsonl", "manifest.json"):
        if (src / extra).exists():
            shutil.copy2(src / extra, dst / extra)
    started = time.perf_counter()
    jobs = [(p, dst / p.name) for p in parts]
    total_r = total_b = 0
    with Pool(a.workers, initializer=_init, initargs=(a.stockfish,)) as pool:
        for name, n_r, n_b in pool.imap_unordered(_one_part, jobs):
            total_r += n_r
            total_b += n_b
            print(f"{name}: {n_r} records, {n_b} boards ({total_r} records so far, {time.perf_counter() - started:.0f} s)", flush=True)
    print(f"done: {len(parts)} parts, {total_r} records, {total_b} boards -> {dst} in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()
