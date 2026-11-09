"""Train the belief network on belief records (D6). It is also the retrain command for new labels.

    .venv/bin/python scripts/train_belief_net.py --data data/d6-v1 --out runs/belief-v1

--data is a folder of fow_shared TrainingRecord JSONL files (--pattern; manifest.json optional):
Pair B's practice beliefs now, Pair A's solver labels later. Trains on the training games, keeps
the epoch with the lowest board error on the validation games, and never reads the test games.
A step holds whole beliefs, at most --batch of them and --max-boards boards, so large beliefs
(Pair A plans 256 or more boards) keep steps bounded; --planes-on host keeps the encoded planes
in main memory when they would not fit on the GPU. Writes best.pt, metrics.jsonl, splits.json
(the games used) and summary.json into --out, which must not exist yet. summary.json records the
SHA-256 of the data files and of best.pt, the commit and the library versions.
"""
import argparse
import datetime
import json
import time
from pathlib import Path

import numpy as np
import torch

from pairb.belief_ablation import LEAF_MODES, MODES, collapse
from pairb.belief_data import ENCODING, belief_batches, load_arrays, rows_of
from pairb.belief_eval import baseline_pred, errors, predict, require_d1
from pairb.belief_net import BeliefNetwork
from pairb.data import split_of
from pairb.policy_eval import policy_metrics
from pairb.provenance import data_source, git_commit, runtime, sha256_of

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
    ap.add_argument("--input", choices=MODES + LEAF_MODES, default="full",
                    help="ablation of the state representation: full = every sampled hypothesis board; marginals = "
                         "one pseudo-board per belief with the observation and the belief marginals, no sampling; "
                         "observation = one pseudo-board with the fogged observation only; alone = every board as a "
                         "belief of its own, i.e. train the network the way the search's per-board leaf call uses it "
                         "(see pairb.belief_ablation); with alone, raise --batch so a step holds thousands of boards")
    ap.add_argument("--policy-weight", type=float, default=0.0,
                    help="also train a policy head on the solver's raw root policy (pairb.moves slots), with this "
                         "weight on its cross-entropy next to the value loss; 0 = no policy head")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--patience", type=int, default=5, help="stop after this many epochs without a better validation score")
    ap.add_argument("--batch", type=int, default=64, help="at most this many beliefs per step")
    ap.add_argument("--max-boards", type=int, default=4096, help="at most this many boards per step")
    ap.add_argument("--planes-on", choices=["auto", "device", "host"], default="auto",
                    help="where the encoded planes live; auto puts them on the device up to 2 GiB")
    ap.add_argument("--pattern", default="part-*.jsonl", help="the record files to read in --data")
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

    source = data_source(args.data, args.pattern)  # the bytes read below
    arrays = collapse(load_arrays(args.data, args.cache_dir, args.workers, args.pattern), args.input)
    split = np.array([split_of(g) for g in arrays["game_id"]])
    ids = {name: np.flatnonzero(split == name) for name in ("train", "val", "test")}
    n = {name: {"beliefs": int(len(ids[name])), "boards": int(len(rows_of(arrays, ids[name])[0]))}
         for name in ("train", "val")}
    n["test_held_out"] = {"beliefs": int(len(ids["test"]))}
    if not len(ids["val"]):
        raise SystemExit("the dataset has no validation games")
    print(f"beliefs: {n}  device: {device}", flush=True)

    on_device = args.planes_on == "device" or (args.planes_on == "auto" and arrays["planes"].nbytes <= 2 * 2 ** 30)
    planes = torch.from_numpy(arrays["planes"]).to(device) if on_device else None  # float16; float32 per batch
    d1 = baseline_pred(arrays, ids["val"])
    baseline = errors(d1, arrays, ids["val"])[0] if d1 is not None else None
    if args.use_d1:
        try:  # every board the network will read, training and validation alike
            require_d1(arrays, np.concatenate([ids["train"], ids["val"]]))
        except ValueError as exc:
            raise SystemExit(f"--use-d1: {exc}")
    print(f"quick Stockfish on validation: {baseline}", flush=True)

    net = BeliefNetwork(args.blocks, args.channels, args.embed, use_d1=args.use_d1,
                        use_context=not args.no_context, policy_head=args.policy_weight > 0).to(device)
    params = sum(p.numel() for p in net.parameters())
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    rng = np.random.default_rng(args.seed)
    sizes = np.bincount(arrays["belief"])
    epochs = [belief_batches(sizes, rng.permutation(ids["train"]), args.max_boards, args.batch)
              for _ in range(args.epochs)]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=sum(len(e) for e in epochs))
    # The games actually in the training batches and the validation set, so a check can confirm
    # no test game was trained or selected on.
    trained = np.unique(np.concatenate([np.concatenate(e) for e in epochs]))
    (out / "splits.json").write_text(json.dumps({
        "train": sorted(set(arrays["game_id"][trained].tolist())),
        "val": sorted(set(arrays["game_id"][ids["val"]].tolist())),
        "test_held_out_games": len(set(arrays["game_id"][ids["test"]].tolist()))}) + "\n")
    y_all, w_all = torch.from_numpy(arrays["y"]).to(device), torch.from_numpy(arrays["weight"]).to(device)
    keep_all = torch.from_numpy(~arrays["rule"]).to(device).float()
    d1_all = torch.from_numpy(np.nan_to_num(arrays["d1"])).to(device)
    use_policy = args.policy_weight > 0
    if use_policy and "policy" not in arrays:
        raise SystemExit("--policy-weight needs the policy arrays: a cache from CACHE_VERSION 3 and an input mode that keeps them")
    pol_all = torch.from_numpy(arrays["policy"].astype(np.float32)).to(device) if use_policy else None
    legal_all = torch.from_numpy(arrays["legal"]).to(device) if use_policy else None

    best, best_epoch, waited, epoch = None, 0, 0, 0
    with open(out / "metrics.jsonl", "w") as log:
        for epoch in range(1, args.epochs + 1):
            net.train()
            total, weight_seen = 0.0, 0.0
            pol_total, pol_weight = 0.0, 0.0
            for chunk in epochs[epoch - 1]:
                rows, local = rows_of(arrays, chunk)
                r = torch.from_numpy(rows).to(device)
                local_t = torch.from_numpy(local).to(device)
                x = planes[r] if planes is not None else torch.from_numpy(arrays["planes"][rows]).to(device)
                result = net(x.float(), w_all[r], local_t, len(chunk), d1_all[r] if args.use_d1 else None,
                             return_policy=use_policy)
                pred, logits = result if use_policy else (result, None)
                w = w_all[r] * keep_all[r]  # boards the rules decide are not learned
                loss = value_loss = (w * (pred - y_all[r]) ** 2).sum() / w.sum().clamp_min(1e-12)
                if use_policy:
                    chunk_t = torch.from_numpy(chunk).to(device)
                    target, legal = pol_all[chunk_t][local_t], legal_all[chunk_t][local_t]
                    logp = torch.log_softmax(logits.masked_fill(~legal, -1e9), dim=1)
                    ce = -(target * logp).sum(1)  # every board of a belief learns that belief's root policy
                    policy_loss = (w_all[r] * ce).sum() / w_all[r].sum().clamp_min(1e-12)
                    loss = value_loss + args.policy_weight * policy_loss
                    pol_total += policy_loss.item() * float(w_all[r].sum())
                    pol_weight += float(w_all[r].sum())
                opt.zero_grad()
                loss.backward()
                opt.step()
                sched.step()
                total += value_loss.item() * float(w.sum())
                weight_seen += float(w.sum())
            val = errors(predict(net, arrays, ids["val"], device, args.max_boards, planes), arrays, ids["val"])[0]
            if use_policy:
                val["policy"] = policy_metrics(net, arrays, ids["val"], device, args.max_boards, planes)
            row = {"epoch": epoch, "train_mse": round(total / max(weight_seen, 1e-12), 6), "val": val,
                   "seconds": round(time.time() - started, 1)}
            if use_policy:
                row["train_policy_ce"] = round(pol_total / max(pol_weight, 1e-12), 6)
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row), flush=True)
            if best is None or val["board_mse"] < best["board_mse"]:
                best, best_epoch, waited = val, epoch, 0
                torch.save({"state_dict": {k: v.cpu() for k, v in net.state_dict().items()}, "config": net.config,
                            "encoding": ENCODING, "input": args.input, "dataset": Path(args.data).name,
                            "epoch": epoch, "val": val},
                           out / "best.pt")
            else:
                waited += 1
                if waited >= args.patience:
                    break

    ckpt = torch.load(out / "best.pt", map_location="cpu", weights_only=True)
    net = BeliefNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    speed = {f"{device.type}_64_beliefs": ms_per_belief(net, device, 64), f"{device.type}_1_belief": ms_per_belief(net, device, 1)}
    if device.type != "cpu":
        speed["cpu_1_belief"] = ms_per_belief(net, torch.device("cpu"), 1)
    summary = {
        "dataset": Path(args.data).name, "encoding": ENCODING, "input": args.input, "config": ckpt["config"], "params": params,
        "device": device.type, "planes_on": "device" if on_device else "host", "n": n, "baseline": baseline,
        "val": best, "best_epoch": best_epoch,
        "epochs_run": epoch, "ms_per_belief_of_8_boards": speed, "seconds": round(time.time() - started, 1),
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "args": vars(args),
        "source": source, "checkpoint_sha256": sha256_of(out / "best.pt"), "git_commit": git_commit(),
        "runtime": {**runtime(), "torch": torch.__version__},
    }
    if baseline:
        summary["board_mae_vs_quick_stockfish_pct"] = round(100 * (1 - best["board_mae"] / baseline["board_mae"]), 1)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"best epoch {best_epoch}: validation board MAE {best['board_mae']} (quick Stockfish "
          f"{baseline['board_mae'] if baseline else 'n/a'}); {params:,} parameters -> {out}", flush=True)


if __name__ == "__main__":
    main()
