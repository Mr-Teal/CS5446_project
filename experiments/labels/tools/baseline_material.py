"""Baselines for the belief network's offline evaluation on solver labels, on one split.

eval_belief_net.py compares the network with quick Stockfish only when the records carry d1 values;
solver labels do not. This gives two reference points on the same records: Pair B's material
evaluator's value of each hypothesis, and the constant 0. A position's value is the belief-weighted
mean of its hypotheses' values, as in the label definition. Reports mean absolute error per board
and per position, with the record count.

Usage: python baseline_material.py <label folder> [train|val|test] [pattern]
Runs where pairb and fow_shared import (the VM container); no torch needed.
"""
import sys
from pathlib import Path
from statistics import mean

from fow_shared.recording import read_records
from pairb.data import split_of
from pairb.material import MaterialEvaluator

folder = Path(sys.argv[1])
split = sys.argv[2] if len(sys.argv) > 2 else "val"
pattern = sys.argv[3] if len(sys.argv) > 3 else "part-*.jsonl"
mat = MaterialEvaluator()
board_err = {"material": [], "zero": []}
pos_err = {"material": [], "zero": []}
records = games = 0
seen_games = set()
for part in sorted(folder.glob(pattern)):
    if part.stat().st_size == 0:
        continue
    for r in read_records(part):
        if split_of(r.game_id) != split:
            continue
        hyps = r.agent_input.belief.hypotheses
        player = r.agent_input.observation.player
        fens = [h.fen for h in hyps]
        weights = [h.weight for h in hyps]
        truth = list(r.hypothesis_values)
        pred = {"material": mat.evaluate_boards(fens, player), "zero": [0.0] * len(fens)}
        for name, values in pred.items():
            board_err[name].extend(abs(p - t) for p, t in zip(values, truth))
            pos_err[name].append(abs(sum(w * p for w, p in zip(weights, values)) - r.root_value))
        records += 1
        seen_games.add(r.game_id)
mat.close()
print(f"{folder} split={split}: {records} records from {len(seen_games)} games, "
      f"{len(board_err['zero'])} boards")
for name in ("material", "zero"):
    if board_err[name]:
        print(f"  {name:>8}: board MAE {mean(board_err[name]):.4f}  position MAE {mean(pos_err[name]):.4f}")
