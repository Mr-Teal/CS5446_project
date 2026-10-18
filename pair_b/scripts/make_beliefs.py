"""Make practice beliefs for the belief network (D6), labelled by Stockfish.

    .venv/bin/python scripts/make_beliefs.py --source data/d2-v2 --parents 12000 --out data/d6-v1

Each decision point of a D2 dataset (a parent position, the side to move deciding) becomes one
fow_shared TrainingRecord: a belief of up to --hypotheses boards (pairb.standin_beliefs), each
scored by Stockfish at --label-depth from the deciding player's view, with quick Stockfish's
scores kept as "d1:<i>" diagnostics for comparison. Positions the rules already decide are
skipped. Writes part-NN.jsonl and manifest.json into --out, which must not exist yet. Every
belief is seeded by (--seed, game, ply), so the files do not depend on --workers.
"""
import argparse
import datetime
import hashlib
import json
import multiprocessing as mp
import platform
import random
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

import chess

from fow_shared.recording import write_records
from pairb.standin_beliefs import make_turn, record_for
from pairb.stockfish import StockfishEvaluator
from pairb.values import rule_value

SPEC = "d6-standin-v1"
ROOT = Path(__file__).resolve().parents[1]


def decision_points(folder: Path) -> list[tuple[str, int, str]]:
    """(game_id, ply, FEN) of every parent in a D2 dataset, in a fixed order."""
    found = set()
    for f in sorted(folder.glob("part-*.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            found.add((r["game_id"], r["ply"] - 1, r["parent_fen"]))
    return sorted(found)


def run_worker(task):
    worker, points, cfg = task
    label = f"standin-stockfish-d{cfg['label_depth']}"
    records, sizes, skipped = [], Counter(), 0
    with StockfishEvaluator(depth=1) as quick, StockfishEvaluator(depth=cfg["label_depth"]) as careful:
        for game_id, ply, fen in points:
            board = chess.Board(fen)
            if rule_value(board) is not None:
                skipped += 1
                continue
            seed = zlib.crc32(f"{cfg['seed']}-{game_id}-{ply}".encode())
            turn = make_turn(board, random.Random(seed), n_hypotheses=cfg["hypotheses"], ply=ply)
            fens, player = [h.fen for h in turn.belief.hypotheses], turn.observation.player
            values = careful.evaluate_boards(fens, player)
            d1 = quick.evaluate_boards(fens, player)
            records.append(record_for(turn, values, seed, game_id, label,
                                      diagnostics={f"d1:{i}": v for i, v in enumerate(d1)}))
            sizes[len(fens)] += 1
        engine_name = quick.engine.id.get("name", "unknown")
    write_records(Path(cfg["out"]) / f"part-{worker:02d}.jsonl", records)
    return len(records), sizes, skipped, engine_name


def code_sha256() -> str:
    h = hashlib.sha256()
    for path in sorted([*ROOT.glob("src/pairb/*.py"), Path(__file__).resolve()]):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="a D2 dataset folder; its parents become decisions")
    ap.add_argument("--parents", type=int, default=12000, help="how many decision points to use (all if fewer)")
    ap.add_argument("--hypotheses", type=int, default=8, help="boards per belief, the truth included")
    ap.add_argument("--label-depth", type=int, default=11)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--run-by", default="Pair B")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out, src = Path(args.out), Path(args.source)
    points = decision_points(src)
    if args.parents < len(points):
        points = sorted(random.Random(args.seed).sample(points, args.parents))
    out.mkdir(parents=True, exist_ok=False)  # never edit a finished dataset
    cfg = {**vars(args), "out": str(out)}
    workers = max(1, min(args.workers, len(points)))
    tasks = [(w, points[w::workers], cfg) for w in range(workers)]

    start = time.time()
    with mp.Pool(workers) as pool:
        results = pool.map(run_worker, tasks)

    source_manifest = json.loads((src / "manifest.json").read_text())
    sizes = sum((r[1] for r in results), Counter())
    manifest = {
        "dataset": out.name,
        "spec": SPEC,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_by": args.run_by,
        "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "code_sha256": code_sha256(),
        "machine": f"{platform.platform()}; Python {platform.python_version()}; python-chess {chess.__version__}",
        "source": {"dataset": source_manifest.get("dataset", src.name), "created": source_manifest.get("created")},
        "format": "fow_shared TrainingRecord JSONL (fow_shared.recording)",
        "beliefs": "pairb.standin_beliefs: the true board plus alternatives moving unseen opponent pieces; "
                   "visibility from pairb.observe, a stand-in matching pair_a_prep's rules fixtures",
        "labels": "hypothesis_values: Stockfish at label_depth per board, deciding player's view; "
                  "root_value: their weighted mean; decision.diagnostics d1:<i>: Stockfish depth 1",
        "stockfish": {"name": results[0][3], "threads": 1, "hash_mb": 16, "label_depth": args.label_depth,
                      "new_game_before_each_call": True},
        "seed": args.seed,
        "decision_points": len(points),
        "skipped_rule_decided": sum(r[2] for r in results),
        "records": sum(r[0] for r in results),
        "hypotheses_per_belief": {str(k): v for k, v in sorted(sizes.items())},
        "files": sorted(p.name for p in out.glob("part-*.jsonl")),
        "seconds": round(time.time() - start, 1),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{manifest['records']} beliefs in {manifest['seconds']} s -> {out}")


if __name__ == "__main__":
    main()
