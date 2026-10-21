"""Train Network 1 on a D2-format dataset (D3). This is also the D7 retrain command.

    .venv/bin/python scripts/train_net1.py --data data/d2-v1 --out runs/net1-v1

Trains on the training games, keeps the epoch with the lowest error on the validation games,
and never reads the test games, which stay untouched until the final evaluation. Writes
best.pt, metrics.jsonl and summary.json into --out, which must not exist yet.
"""
import argparse
import datetime
import json
import time
from pathlib import Path

import numpy as np
import torch

from pairb.data import ENCODING, load_arrays, split_of
from pairb.evaluate import as_float, errors, predict
from pairb.net1 import Network1

ROOT = Path(__file__).resolve().parents[1]


def device_of(name: str) -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    return torch.device(name)


def sync(device):
    if device.type == "mps":
        torch.mps.synchronize()


@torch.no_grad()
def ms_per_board(net, device, batch: int) -> float:
    net.eval().to(device)
    planes, d1 = torch.zeros(batch, 19, 8, 8, device=device), torch.zeros(batch, device=device)
    for _ in range(5):
        net(planes, d1)
    sync(device)
    start, runs = time.perf_counter(), 20
    for _ in range(runs):
        net(planes, d1)
    sync(device)
    return round((time.perf_counter() - start) / runs / batch * 1000, 5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="a D2-format dataset folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--blocks", type=int, default=6)
    ap.add_argument("--channels", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--patience", type=int, default=5, help="stop after this many epochs without a better validation score")
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="auto", help="auto, cuda, mps or cpu")
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    device = device_of(args.device)
    torch.manual_seed(args.seed)
    started = time.time()

    arrays = load_arrays(args.data, args.cache_dir)
    split = np.array([split_of(g) for g in arrays["game_id"]])
    tensors, used = {}, {}
    for name in ("train", "val"):
        m = split == name
        tensors[name] = [torch.from_numpy(arrays[k][m]).to(device) for k in ("planes", "d1", "y")]
        used[name] = sorted(set(arrays["game_id"][m].tolist()))
    # The games each split actually used, so a check can confirm no test game was trained or
    # selected on.
    (out / "splits.json").write_text(json.dumps({**used, "test_held_out_games": len(set(arrays["game_id"][split == "test"]))}) + "\n")
    n = {"train": len(tensors["train"][2]), "val": len(tensors["val"][2]), "test_held_out": int((split == "test").sum())}
    if n["val"] == 0:
        raise SystemExit("the dataset has no validation games")
    print(f"examples: {n}  device: {device}", flush=True)

    vp, vd1, vy = tensors["val"]
    val_parents = arrays["parent"][split == "val"]
    baseline = errors(vd1, vy, val_parents, vd1)
    print(f"baseline (depth-1 value as the prediction) on validation: {baseline}", flush=True)

    net = Network1(args.blocks, args.channels).to(device)
    params = sum(p.numel() for p in net.parameters())
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    tp, td1, ty = tensors["train"]
    steps = (n["train"] + args.batch - 1) // args.batch
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs * steps)
    gen = torch.Generator().manual_seed(args.seed)

    best, best_epoch, waited = None, 0, 0
    with open(out / "metrics.jsonl", "w") as log:
        for epoch in range(1, args.epochs + 1):
            net.train()
            perm = torch.randperm(n["train"], generator=gen).to(device)
            total = 0.0
            for i in range(steps):
                idx = perm[i * args.batch:(i + 1) * args.batch]
                loss = torch.mean((net(as_float(tp[idx]), td1[idx]) - ty[idx]) ** 2)
                opt.zero_grad()
                loss.backward()
                opt.step()
                sched.step()
                total += loss.item() * len(idx)
            val = errors(predict(net, vp, vd1), vy, val_parents, vd1)
            row = {"epoch": epoch, "train_mse": round(total / n["train"], 6), "val": val, "seconds": round(time.time() - started, 1)}
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row), flush=True)
            if best is None or val["mse"] < best["mse"]:
                best, best_epoch, waited = val, epoch, 0
                torch.save({"state_dict": {k: v.cpu() for k, v in net.state_dict().items()}, "config": net.config,
                            "encoding": ENCODING, "dataset": Path(args.data).name, "epoch": epoch, "val": val},
                           out / "best.pt")
            else:
                waited += 1
                if waited >= args.patience:
                    break

    ckpt = torch.load(out / "best.pt", map_location="cpu", weights_only=True)
    net = Network1(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    speed = {f"{device.type}_batch_{b}": ms_per_board(net, device, b) for b in (32, 1024)}
    if device.type != "cpu":
        speed["cpu_batch_32"] = ms_per_board(net, torch.device("cpu"), 32)
    summary = {
        "dataset": Path(args.data).name, "encoding": ENCODING, "config": ckpt["config"], "params": params,
        "device": device.type, "n": n, "baseline": baseline, "val": best, "best_epoch": best_epoch,
        "epochs_run": epoch, "mae_improvement_pct": round(100 * (1 - best["mae"] / baseline["mae"]), 1),
        "ms_per_board": speed, "seconds": round(time.time() - started, 1),
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "args": vars(args),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"best epoch {best_epoch}: validation MAE {best['mae']} vs depth-1 baseline {baseline['mae']} "
          f"({summary['mae_improvement_pct']}% better); {params:,} parameters -> {out}", flush=True)


if __name__ == "__main__":
    main()
