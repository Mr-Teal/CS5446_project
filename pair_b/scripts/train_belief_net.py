"""Train the belief network on belief records (D6). It is also the retrain command for new labels.

    .venv/bin/python scripts/train_belief_net.py --data data/d6-v1 --out runs/belief-v1

--data is a folder of fow_shared TrainingRecord part files with a manifest.json: Pair B's practice
beliefs now, Pair A's solver labels later. Trains on the training games, keeps the epoch with the
lowest board error on the validation games, and never reads the test games. Writes best.pt,
metrics.jsonl and summary.json into --out, which must not exist yet.
"""
import argparse
import datetime
import json
import time
from pathlib import Path

import numpy as np
import torch

from pairb.belief_data import ENCODING, load_arrays, rows_of
from pairb.belief_eval import baseline_pred, errors, predict
from pairb.belief_net import BeliefNetwork
from pairb.data import split_of

ROOT = Path(__file__).resolve().parents[1]


def device_of(name: str) -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    return torch.device(name)


def sync(device):
    if device.type == "mps":
        torch.mps.synchronize()
    elif device.type == "cuda":
        torch.cuda.synchronize()


@torch.no_grad()
def ms_per_belief(net, device, beliefs: int, boards: int = 8) -> float:
    """Milliseconds per belief of `boards` boards, scoring `beliefs` beliefs in one call."""
    net.eval().to(device)
    n = beliefs * boards
    args = (torch.zeros(n, 32, 8, 8, device=device), torch.full((n,), 1 / boards, device=device),
            torch.arange(beliefs, device=device).repeat_interleave(boards), beliefs)
    d1 = torch.zeros(n, device=device) if net.use_d1 else None
    for _ in range(3):
        net(*args, d1)
    sync(device)
    start, runs = time.perf_counter(), 10
    for _ in range(runs):
        net(*args, d1)
    sync(device)
    return round((time.perf_counter() - start) / runs / beliefs * 1000, 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="a folder of belief records with manifest.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--blocks", type=int, default=6)
    ap.add_argument("--channels", type=int, default=64)
    ap.add_argument("--embed", type=int, default=128)
    ap.add_argument("--use-d1", action="store_true", help="also read quick Stockfish's value of each board")
    ap.add_argument("--no-context", action="store_true", help="ablation: ignore the rest of the belief")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--patience", type=int, default=5, help="stop after this many epochs without a better validation score")
    ap.add_argument("--batch", type=int, default=64, help="beliefs per step")
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="auto", help="auto, cuda, mps or cpu")
    ap.add_argument("--workers", type=int, default=8, help="processes encoding the records")
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    device = device_of(args.device)
    torch.manual_seed(args.seed)
    started = time.time()

    arrays = load_arrays(args.data, args.cache_dir, args.workers)
    split = np.array([split_of(g) for g in arrays["game_id"]])
    ids = {name: np.flatnonzero(split == name) for name in ("train", "val", "test")}
    n = {name: {"beliefs": int(len(ids[name])), "boards": int(len(rows_of(arrays, ids[name])[0]))}
         for name in ("train", "val")}
    n["test_held_out"] = {"beliefs": int(len(ids["test"]))}
    if not len(ids["val"]):
        raise SystemExit("the dataset has no validation games")
    print(f"beliefs: {n}  device: {device}", flush=True)

    planes = torch.from_numpy(arrays["planes"]).to(device)  # float16 on the device; float32 per batch
    d1 = baseline_pred(arrays, ids["val"])
    baseline = errors(d1, arrays, ids["val"])[0] if d1 is not None else None
    if args.use_d1 and d1 is None:
        raise SystemExit("--use-d1 needs records carrying d1:<i> diagnostics")
    print(f"quick Stockfish on validation: {baseline}", flush=True)

    net = BeliefNetwork(args.blocks, args.channels, args.embed, use_d1=args.use_d1,
                        use_context=not args.no_context).to(device)
    params = sum(p.numel() for p in net.parameters())
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    steps = (len(ids["train"]) + args.batch - 1) // args.batch
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs * steps)
    rng = np.random.default_rng(args.seed)
    y_all, w_all = torch.from_numpy(arrays["y"]).to(device), torch.from_numpy(arrays["weight"]).to(device)
    keep_all = torch.from_numpy(~arrays["rule"]).to(device).float()
    d1_all = torch.from_numpy(np.nan_to_num(arrays["d1"])).to(device)

    best, best_epoch, waited, epoch = None, 0, 0, 0
    with open(out / "metrics.jsonl", "w") as log:
        for epoch in range(1, args.epochs + 1):
            net.train()
            order, total, weight_seen = rng.permutation(ids["train"]), 0.0, 0.0
            for i in range(steps):
                rows, local = rows_of(arrays, order[i * args.batch:(i + 1) * args.batch])
                r = torch.from_numpy(rows).to(device)
                pred = net(planes[r].float(), w_all[r], torch.from_numpy(local).to(device), int(local.max()) + 1,
                           d1_all[r] if args.use_d1 else None)
                w = w_all[r] * keep_all[r]  # boards the rules decide are not learned
                loss = (w * (pred - y_all[r]) ** 2).sum() / w.sum().clamp_min(1e-12)
                opt.zero_grad()
                loss.backward()
                opt.step()
                sched.step()
                total += loss.item() * float(w.sum())
                weight_seen += float(w.sum())
            val = errors(predict(net, arrays, ids["val"], device, planes=planes), arrays, ids["val"])[0]
            row = {"epoch": epoch, "train_mse": round(total / max(weight_seen, 1e-12), 6), "val": val,
                   "seconds": round(time.time() - started, 1)}
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row), flush=True)
            if best is None or val["board_mse"] < best["board_mse"]:
                best, best_epoch, waited = val, epoch, 0
                torch.save({"state_dict": {k: v.cpu() for k, v in net.state_dict().items()}, "config": net.config,
                            "encoding": ENCODING, "dataset": Path(args.data).name, "epoch": epoch, "val": val},
                           out / "best.pt")
            else:
                waited += 1
                if waited >= args.patience:
                    break

    ckpt = torch.load(out / "best.pt", map_location="cpu")
    net = BeliefNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    speed = {f"{device.type}_64_beliefs": ms_per_belief(net, device, 64), f"{device.type}_1_belief": ms_per_belief(net, device, 1)}
    if device.type != "cpu":
        speed["cpu_1_belief"] = ms_per_belief(net, torch.device("cpu"), 1)
    summary = {
        "dataset": Path(args.data).name, "encoding": ENCODING, "config": ckpt["config"], "params": params,
        "device": device.type, "n": n, "baseline": baseline, "val": best, "best_epoch": best_epoch,
        "epochs_run": epoch, "ms_per_belief_of_8_boards": speed, "seconds": round(time.time() - started, 1),
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "args": vars(args),
    }
    if baseline:
        summary["board_mae_vs_quick_stockfish_pct"] = round(100 * (1 - best["board_mae"] / baseline["board_mae"]), 1)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"best epoch {best_epoch}: validation board MAE {best['board_mae']} (quick Stockfish "
          f"{baseline['board_mae'] if baseline else 'n/a'}); {params:,} parameters -> {out}", flush=True)


if __name__ == "__main__":
    main()
