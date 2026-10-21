"""Score a trained Network 1 against the depth-1 baseline on one split of a D2-format dataset.

    .venv/bin/python scripts/eval_net1.py --run runs/net1-v2 --data data/d2-v2 --split val

Network 1, the depth-1 value and the piece-value baseline are scored on the same positions.
Move choice is compared parent by parent, with a 95% bootstrap interval that resamples whole
games. The test split is for the final evaluation only and needs --final. Writes
eval-<dataset>-<split>.json into the run folder.
"""
import argparse
import datetime
import json
from pathlib import Path

import numpy as np
import torch

from pairb.data import ENCODING, load_arrays, split_of
from pairb.evaluate import errors, material_pred, predict
from pairb.metrics import paired_regret_difference
from pairb.net1 import Network1

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a folder written by train_net1.py")
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", choices=["train", "val", "test"], default="val")
    ap.add_argument("--final", action="store_true", help="allow the test split (final evaluation only)")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    args = ap.parse_args()
    if args.split == "test" and not args.final:
        ap.error("the test split is for the final evaluation only; pass --final to use it")

    if args.device == "auto":
        args.device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    device = torch.device(args.device)
    run = Path(args.run)
    ckpt = torch.load(run / "best.pt", map_location="cpu", weights_only=True)
    if ckpt.get("encoding") != ENCODING:
        ap.error(f"the checkpoint was trained on input planes {ckpt.get('encoding')!r}, this reader makes {ENCODING!r}")
    net = Network1(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    net.to(device)

    arrays = load_arrays(args.data, args.cache_dir)
    m = np.array([split_of(g) for g in arrays["game_id"]]) == args.split
    planes, d1, y = (torch.from_numpy(arrays[k][m]).to(device) for k in ("planes", "d1", "y"))
    parents, games = arrays["parent"][m], arrays["game_id"][m]
    pred = predict(net, planes, d1)

    report = {
        "run": run.name, "data": Path(args.data).name, "split": args.split, "n": int(m.sum()),
        "checkpoint_epoch": ckpt["epoch"],
        "network": errors(pred, y, parents, d1),
        "baseline": errors(d1, y, parents, d1),
        "material": errors(material_pred(planes).to(device), y, parents, d1),
        "regret_difference": paired_regret_difference(parents, pred.cpu().numpy(), d1.cpu().numpy(),
                                                      y.cpu().numpy(), games=games, n_boot=args.n_boot),
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (run / f"eval-{Path(args.data).name}-{args.split}.json").write_text(json.dumps(report, indent=2) + "\n")
    rd = report["regret_difference"]
    print(f"{args.split}: MAE network {report['network']['mae']} vs depth-1 {report['baseline']['mae']}; "
          f"top-1 move {report['network']['choice']['top1']:.3f} vs {report['baseline']['choice']['top1']:.3f}; "
          f"regret difference {rd['mean']:+.4f} (95% CI {rd['ci95'][0]:+.4f} to {rd['ci95'][1]:+.4f}) "
          f"over {rd['parents']} parents from {rd['games']} games")


if __name__ == "__main__":
    main()
