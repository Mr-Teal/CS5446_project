"""Paired comparison of belief-network runs on the same validation beliefs (state-representation ablation).

usage, inside tools/torch.sh:
    compare_runs.py --data /labels/<dataset> --runs /labels/runs/<reference> /labels/runs/<other> ... [--split val] [--out file]

The first run is the reference. For every run it reports the network's board and position errors; for every
other run also the mean paired difference in position error (other minus reference) with a 95 % bootstrap
interval over whole games (pairb.metrics.paired_difference; negative = the other run errs less). Each
checkpoint records the input ablation it was trained with ("input": full / marginals / observation), and the
dataset arrays are collapsed accordingly, so every run is scored on exactly the same beliefs. The test split
needs --final and is for the final report only.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

import numpy as np
import torch

from pairb.belief_ablation import collapse
from pairb.belief_data import ENCODING, load_arrays
from pairb.belief_eval import errors, paired_difference, predict
from pairb.belief_net import BeliefNetwork
from pairb.data import split_of


LEAF_MODE_OF = {"full": "alone", "marginals": "alone-marginals"}


def score(run: Path, base: dict, split: str, device, max_boards: int, leaf_mode: bool = False):
    ckpt = torch.load(run / "best.pt", map_location="cpu", weights_only=True)
    if ckpt.get("encoding") != ENCODING:
        sys.exit(f"{run}: trained on {ckpt.get('encoding')!r}, this reader makes {ENCODING!r}")
    net = BeliefNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    net.to(device)
    mode = ckpt.get("input", "full")
    if leaf_mode:
        if mode not in LEAF_MODE_OF:
            sys.exit(f"{run}: a network trained on {mode!r} inputs has no leaf mode")
        mode = LEAF_MODE_OF[mode]
    arrays = collapse(base, mode)
    beliefs = np.flatnonzero(np.array([split_of(g) for g in arrays["game_id"]]) == split)
    metrics, root_err = errors(predict(net, arrays, beliefs, device, max_boards), arrays, beliefs)
    return {"run": run.name, "input": mode, "config": ckpt["config"], "epoch": ckpt.get("epoch"),
            "network": metrics}, root_err, arrays["game_id"][beliefs]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--runs", nargs="+", required=True, help="run folders; the first is the reference")
    ap.add_argument("--split", choices=["train", "val", "test"], default="val")
    ap.add_argument("--final", action="store_true", help="allow the test split (final evaluation only)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-boards", type=int, default=4096)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--cache-dir", default="/labels/cache")
    ap.add_argument("--out", default=None, help="write the report here as JSON (also printed)")
    ap.add_argument("--leaf-mode", action="store_true",
                    help="score every board as a one-board belief, the way the search's evaluate_children "
                         "presents boards to the leaf (see pairb.belief_ablation LEAF_MODES)")
    args = ap.parse_args()
    if args.split == "test" and not args.final:
        sys.exit("the test split is for the final evaluation: pass --final to use it")
    device = torch.device(args.device)
    base = load_arrays(args.data, args.cache_dir, args.workers)
    ref, ref_err, ref_games = score(Path(args.runs[0]), base, args.split, device, args.max_boards, args.leaf_mode)
    report = {"data": Path(args.data).name, "split": args.split, "leaf_mode": args.leaf_mode, "reference": ref, "runs": [],
              "bootstrap": {"resamples": args.n_boot, "seed": 0, "unit": "whole games"},
              "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    for run in args.runs[1:]:
        entry, err, games = score(Path(run), base, args.split, device, args.max_boards, args.leaf_mode)
        if len(err) != len(ref_err) or (games != ref_games).any():
            sys.exit(f"{run}: scored on different beliefs than the reference")
        entry["root_mae_difference_vs_reference"] = paired_difference(err, ref_err, games, args.n_boot)
        report["runs"].append(entry)
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
