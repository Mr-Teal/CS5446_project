"""Evaluate a trained belief network on one split of a belief dataset (D6).

    .venv/bin/python scripts/eval_belief_net.py --run runs/belief-v1 --data data/d6-check --split train

Writes eval-<dataset>-<split>.json into the run folder: the network's and quick Stockfish's board
and position errors on the same beliefs, and the paired difference in position error with a 95%
bootstrap interval. The test split needs --final: keep it for the final report.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

import numpy as np
import torch

from pairb.belief_data import ENCODING, load_arrays
from pairb.belief_eval import baseline_pred, errors, paired_difference, predict
from pairb.belief_net import BeliefNetwork
from pairb.data import split_of

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a folder written by train_belief_net.py")
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", choices=["train", "val", "test"], default="val")
    ap.add_argument("--final", action="store_true", help="allow the test split (final evaluation only)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pattern", default="part-*.jsonl", help="the record files to read in --data")
    ap.add_argument("--max-boards", type=int, default=4096, help="at most this many boards per network pass")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    args = ap.parse_args()
    if args.split == "test" and not args.final:
        sys.exit("the test split is for the final evaluation: pass --final to use it")

    run = Path(args.run)
    ckpt = torch.load(run / "best.pt", map_location="cpu")
    if ckpt.get("encoding") != ENCODING:
        sys.exit(f"checkpoint was trained on {ckpt.get('encoding')!r}, this reader makes {ENCODING!r}")
    net = BeliefNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    device = torch.device(args.device)
    net.to(device)

    arrays = load_arrays(args.data, args.cache_dir, args.workers, args.pattern)
    beliefs = np.flatnonzero(np.array([split_of(g) for g in arrays["game_id"]]) == args.split)
    if not len(beliefs):
        sys.exit(f"no {args.split} beliefs in {args.data}")
    try:
        network, net_err = errors(predict(net, arrays, beliefs, device, args.max_boards), arrays, beliefs)
    except ValueError as exc:  # e.g. a d1-reading network on records without quick-Stockfish values
        sys.exit(str(exc))
    report = {"run": run.name, "data": Path(args.data).name, "split": args.split, "network": network,
              "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    d1 = baseline_pred(arrays, beliefs)
    if d1 is not None:
        report["baseline"], base_err = errors(d1, arrays, beliefs)
        report["root_mae_difference"] = paired_difference(net_err, base_err, arrays["game_id"][beliefs], args.n_boot)
    (run / f"eval-{Path(args.data).name}-{args.split}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
