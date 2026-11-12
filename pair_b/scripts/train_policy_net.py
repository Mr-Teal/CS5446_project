"""Train the policy network (stage 1) toward the solver's re-solved move distributions.

    torch_policy.sh pair_b/scripts/train_policy_net.py --design pooled --target mean --seed 0 \\
        --out /labels/policy/runs/pooled-mean-s0

Positions come from pairb.policy_data (label records joined with their afterstate-q-v1 rows; test games are
skipped before encoding). --target mean trains toward the average strategy (policy_mean), last toward the last
iteration (policy_last). Batches hold whole beliefs (--batch of them). Keeps the epoch with the lowest
validation cross-entropy against the run's own target type, stopping after --patience epochs without a better
one. The validation cross-entropy is that of the belief distribution (for per-board, the weight-averaged softmax
of its boards). Writes best.pt, metrics.jsonl and summary.json into --out, which must not exist yet.

A label set covering a subset of the positions, both splits in one folder (the stage-2 depth labels):
    ... --target last --targets /labels/policy/depthlabels/d6 --subset
"""
import argparse
import datetime
import json
import time
from pathlib import Path

import numpy as np
import torch

from pairb.belief_data import ENCODING, belief_batches, rows_of
from pairb.policy_data import TARGETS, counts_of, dense_targets, load_positions
from pairb.policy_net import DESIGNS, PolicyNetwork, cross_entropy, policy_loss, predict
from pairb.provenance import runtime, sha256_of

A = "/labels/afterstate"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", choices=DESIGNS, required=True)
    ap.add_argument("--target", choices=TARGETS, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--records", default="/labels/solver-v2-sf8-480")
    ap.add_argument("--train-targets", nargs="+", default=[f"{A}/atlas-sf8", f"{A}/train-sf8-vm"])
    ap.add_argument("--val-targets", default=f"{A}/val-sf8")
    ap.add_argument("--targets", nargs="+", default=None,
                    help="folders holding both splits' rows (filtered by each row's split); replaces --train-targets "
                         "and --val-targets")
    ap.add_argument("--subset", action="store_true",
                    help="use only the positions that have a good target row, instead of refusing the others")
    ap.add_argument("--cache-dir", default="/labels/policy/cache")
    ap.add_argument("--blocks", type=int, default=6)
    ap.add_argument("--channels", type=int, default=64)
    ap.add_argument("--embed", type=int, default=128)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--batch", type=int, default=64, help="beliefs per step")
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--device", default="auto", help="auto, cuda or cpu")
    ap.add_argument("--workers", type=int, default=6, help="processes encoding the records")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    device = torch.device(("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device)
    torch.manual_seed(args.seed)
    started = time.time()

    train_targets, val_targets = (args.targets, None) if args.targets else (args.train_targets, args.val_targets)
    arrays = load_positions(args.records, train_targets, val_targets, args.cache_dir, args.workers, subset=args.subset)
    counts = counts_of(arrays)
    print(f"data: {json.dumps(counts)}", flush=True)
    print(f"test games skipped: {counts['test_games_skipped']} ({counts['test_records_skipped']} records)", flush=True)
    if args.subset:
        print("positions without a good row skipped: " + ", ".join(
            f"{s} {counts[f'{s}_positions_without_good_row_skipped']}" for s in ("train", "val")), flush=True)
    ids = {s: np.flatnonzero(arrays["split"] == s) for s in ("train", "val")}
    if set(np.unique(arrays["split"])) - {"train", "val"}:
        raise SystemExit("positions outside the training and validation splits")
    if not len(ids["train"]) or not len(ids["val"]):
        raise SystemExit(f"need training and validation positions, have {len(ids['train'])} and {len(ids['val'])}")
    sizes = np.bincount(arrays["belief"])
    n = {s: {"positions": int(len(ids[s])), "boards": int(sizes[ids[s]].sum()),
             "games": int(len(set(arrays["game_id"][ids[s]].tolist())))} for s in ids}
    print(f"n: {n}  device: {device}", flush=True)

    planes = torch.from_numpy(arrays.pop("planes")).to(device)  # float16; float32 per batch
    w_all = torch.from_numpy(arrays["weight"]).to(device)
    legal_all = torch.from_numpy(arrays["legal"]).to(device)
    target_all = torch.from_numpy(dense_targets(arrays, args.target)).to(device)
    other = "last" if args.target == "mean" else "mean"
    val_other = torch.from_numpy(dense_targets(arrays, other, ids["val"])).to(device)
    val_ids_t = torch.from_numpy(ids["val"]).to(device)

    net = PolicyNetwork(args.design, args.blocks, args.channels, args.embed, args.hidden).to(device)
    params = sum(p.numel() for p in net.parameters())
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    rng = np.random.default_rng(args.seed)

    best, best_epoch, waited, epoch = None, 0, 0, 0
    with open(out / "metrics.jsonl", "w") as log:
        for epoch in range(1, args.epochs + 1):
            net.train()
            total, seen = 0.0, 0
            for chunk in belief_batches(sizes, rng.permutation(ids["train"]), max_boards=1 << 30, max_beliefs=args.batch):
                rows, local = rows_of(arrays, chunk)
                r = torch.from_numpy(rows).to(device)
                c = torch.from_numpy(chunk).to(device)
                local_t = torch.from_numpy(local).to(device)
                logp = net(planes[r].float(), w_all[r], local_t, len(chunk), legal_all[c])
                loss = policy_loss(args.design, logp, target_all[c], w_all[r], local_t, len(chunk))
                opt.zero_grad()
                loss.backward()
                opt.step()
                total += loss.item() * len(chunk)
                seen += len(chunk)
            probs = predict(net, arrays, ids["val"], device, planes, legal_all)
            val_ce = float(cross_entropy(probs, target_all[val_ids_t]).mean())
            val_ce_other = float(cross_entropy(probs, val_other).mean())
            row = {"epoch": epoch, "train_ce": round(total / seen, 6), f"val_ce_{args.target}": round(val_ce, 6),
                   f"val_ce_{other}": round(val_ce_other, 6), "seconds": round(time.time() - started, 1)}
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row), flush=True)
            if best is None or val_ce < best["val_ce"]:
                best = {"val_ce": round(val_ce, 6), f"val_ce_{other}": round(val_ce_other, 6)}
                best_epoch, waited = epoch, 0
                torch.save({"state_dict": {k: v.cpu() for k, v in net.state_dict().items()}, "config": net.config,
                            "encoding": ENCODING, "target": args.target, "epoch": epoch, "val": best},
                           out / "best.pt")
            else:
                waited += 1
                if waited >= args.patience:
                    break

    summary = {"design": args.design, "target": args.target, "seed": args.seed, "best_epoch": best_epoch,
               "val": best, "epochs_run": epoch, "seconds": round(time.time() - started, 1), "n": n, "data": counts,
               "params": params, "config": net.config, "encoding": ENCODING, "args": vars(args),
               "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "checkpoint_sha256": sha256_of(out / "best.pt"), "runtime": {**runtime(), "torch": torch.__version__}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"best epoch {best_epoch}: validation cross-entropy ({args.target}) {best['val_ce']}; "
          f"{params:,} parameters; {summary['seconds']} s -> {out}", flush=True)


if __name__ == "__main__":
    main()
