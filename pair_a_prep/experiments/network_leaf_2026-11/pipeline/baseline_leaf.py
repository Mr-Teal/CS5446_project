"""Offline baselines for the belief network on solver labels, on one split: the value a fixed leaf
evaluator gives each hypothesis board, against the solver's per-hypothesis label.

Same measure as baseline_material.py (board MAE, and position MAE on the belief-weighted mean) but
with a choice of leaf: material, the constant 0, and Stockfish at any depth. The solver-v2 labels
were produced with a Stockfish depth-8 leaf, so Stockfish d1 (Obscuro's leaf / Pair B's quick
Stockfish) and d8 (the label leaf itself) are the references that matter.

Usage: python baseline_leaf.py <label folder> [train|val|test] --stockfish /usr/games/stockfish --depths 1,8
Runs where pairb and fow_shared import (host venv with PYTHONPATH=<repo>:<repo>/pair_b/src); no torch.
"""
import argparse
from pathlib import Path
from statistics import mean
import time

from fow_shared.recording import read_records
from pairb.data import split_of
from pairb.material import MaterialEvaluator
from pairb.stockfish import StockfishEvaluator

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("split", nargs="?", default="val", choices=["train", "val", "test"])
ap.add_argument("--pattern", default="part-*.jsonl")
ap.add_argument("--stockfish", default="/usr/games/stockfish")
ap.add_argument("--depths", default="1,8", help="Stockfish depths to evaluate, comma separated; empty for none")
ap.add_argument("--limit", type=int, default=0, help="stop after this many records (0 = all)")
args = ap.parse_args()
if args.split == "test":
    raise SystemExit("the test split is held out for the single final evaluation")

evaluators = {"material": MaterialEvaluator()}
for d in [int(x) for x in args.depths.split(",") if x.strip()]:
    evaluators[f"stockfish-d{d}"] = StockfishEvaluator(depth=d, path=args.stockfish)
names = list(evaluators) + ["zero"]
board_err = {n: [] for n in names}
pos_err = {n: [] for n in names}
records, seen_games, started = 0, set(), time.perf_counter()
for part in sorted(Path(args.folder).glob(args.pattern)):
    if part.stat().st_size == 0:
        continue
    for r in read_records(part):
        if split_of(r.game_id) != args.split:
            continue
        hyps = r.agent_input.belief.hypotheses
        player = r.agent_input.observation.player
        fens = [h.fen for h in hyps]
        weights = [h.weight for h in hyps]
        truth = list(r.hypothesis_values)
        pred = {n: ev.evaluate_boards(fens, player) for n, ev in evaluators.items()}
        pred["zero"] = [0.0] * len(fens)
        for n, values in pred.items():
            board_err[n].extend(abs(p - t) for p, t in zip(values, truth))
            pos_err[n].append(abs(sum(w * p for w, p in zip(weights, values)) - r.root_value))
        records += 1
        seen_games.add(r.game_id)
        if args.limit and records >= args.limit:
            break
    if args.limit and records >= args.limit:
        break
for ev in evaluators.values():
    close = getattr(ev, "close", None)
    if close:
        close()
print(f"{args.folder} split={args.split}: {records} records from {len(seen_games)} games, "
      f"{len(board_err['zero'])} boards, {time.perf_counter() - started:.0f} s")
for n in names:
    if board_err[n]:
        print(f"  {n:>13}: board MAE {mean(board_err[n]):.4f}  position MAE {mean(pos_err[n]):.4f}")
