"""Make the D2 stand-in dataset (D1 spec §6).

    .venv/bin/python scripts/make_d2.py --games 2500 --out data/d2-v1

Writes part-NN.jsonl (one per worker), games.jsonl and manifest.json into --out, which must
not exist yet. Every game is seeded by (--seed, game index), so the files do not depend on
--workers.
"""
import argparse
import datetime
import hashlib
import json
import multiprocessing as mp
import platform
import sys
import time
from collections import Counter
from pathlib import Path

import chess

from pairb.d2 import label_parent, pick_parents, play_game
from pairb.stockfish import StockfishEvaluator

SPEC_VERSION = "0.2"
ROOT = Path(__file__).resolve().parents[1]


def run_worker(task):
    worker, indices, cfg = task
    games, n_records, rules = [], 0, Counter()
    with StockfishEvaluator(depth=1) as ev1, StockfishEvaluator(depth=cfg["label_depth"]) as ev_deep, \
            open(Path(cfg["out"]) / f"part-{worker:02d}.jsonl", "w") as f:
        for index in indices:
            game_id, seed = f"g-{index:06d}", cfg["seed"] * 1_000_000 + index
            moves, info = play_game(seed, ev1.engine, cfg["max_plies"], (cfg["eps_min"], cfg["eps_max"]))
            parents = pick_parents(len(moves), cfg["parents_per_game"], seed, cfg["min_ply"])
            board = chess.Board()
            for ply in range(len(moves) + 1):
                if ply in parents:
                    for record in label_parent(board, game_id, ply, ev1, ev_deep):
                        f.write(json.dumps(record) + "\n")
                        n_records += 1
                        if record["rule"]:
                            rules[record["rule"]["name"]] += 1
                if ply < len(moves):
                    board.push_uci(moves[ply])
            games.append({"game_id": game_id, "white": "d2-selfplay", "black": "d2-selfplay",
                          "result": info["result"], "termination": info["termination"], "plies": len(moves),
                          "seed": seed, "eps": info["eps"], "opening_plies": info["opening_plies"],
                          "parents": parents})
        engine_name = ev1.engine.id.get("name", "unknown")
    return games, n_records, rules, engine_name


def code_sha256() -> str:
    h = hashlib.sha256()
    for path in sorted([*ROOT.glob("src/pairb/*.py"), Path(__file__).resolve()]):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=2500)
    ap.add_argument("--parents-per-game", type=int, default=3)
    ap.add_argument("--min-ply", type=int, default=8, help="earliest parent; skips the shared opening")
    ap.add_argument("--max-plies", type=int, default=300)
    ap.add_argument("--eps-min", type=float, default=0.02, help="random-move rate per game: lower bound")
    ap.add_argument("--eps-max", type=float, default=0.15, help="random-move rate per game: upper bound")
    ap.add_argument("--label-depth", type=int, default=11, help="depth of the deep label, stored as d11")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--run-by", default="Pair B")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)  # never edit a finished dataset
    cfg = {**vars(args), "out": str(out)}
    workers = max(1, min(args.workers, args.games))
    tasks = [(w, list(range(w, args.games, workers)), cfg) for w in range(workers)]

    start = time.time()
    with mp.Pool(workers) as pool:
        results = pool.map(run_worker, tasks)

    games = sorted((g for r in results for g in r[0]), key=lambda g: g["game_id"])
    with open(out / "games.jsonl", "w") as f:
        for g in games:
            f.write(json.dumps(g) + "\n")
    rules = sum((r[2] for r in results), Counter())
    manifest = {
        "dataset": out.name,
        "spec_version": SPEC_VERSION,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_by": args.run_by,
        "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "code_sha256": code_sha256(),
        "machine": f"{platform.platform()}; Python {platform.python_version()}; python-chess {chess.__version__}",
        "stockfish": {
            "name": results[0][3], "threads": 1, "hash_mb": 16,
            "label_depths": [1, args.label_depth],
            "label_mode": "MultiPV at the parent: one score per child, as in [1] App. C.5",
            "new_game_before_each_label": True,
        },
        "value_conversion": "v = tanh(cp / 600); a forced mate is exactly +1 or -1; White's view",
        "games": {
            "count": len(games),
            "rules": "ordinary chess moves (a stand-in); results scored with fog-of-war rules where they differ",
            "policy": "2-8 random opening moves, then Stockfish depth-1 moves with a random move at rate eps, "
                      f"eps drawn per game from U({args.eps_min}, {args.eps_max})",
            "terminations": dict(Counter(g["termination"] for g in games)),
        },
        "parents": {"per_game": args.parents_per_game, "min_ply": args.min_ply,
                    "count": sum(len(g["parents"]) for g in games)},
        "seed": args.seed,
        "records": sum(r[1] for r in results),
        "rule_counts": dict(rules),
        "files": sorted(p.name for p in out.glob("part-*.jsonl")) + ["games.jsonl"],
        "seconds": round(time.time() - start, 1),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{manifest['records']} records from {len(games)} games in {manifest['seconds']} s -> {out}")


if __name__ == "__main__":
    main()
