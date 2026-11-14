"""Evaluate the policy networks (stage 1) and reference movers on the validation positions.

    torch_policy.sh pair_b/scripts/eval_policy_net.py

Every mover plays one move per validation position. A network plays the argmax of its belief distribution over
the legal slots (a promotion slot plays its queen promotion). Moves are scored against Q*, the solver's value of
each move for the whole belief (pairb.policy_data): regret = max Q* - Q*(move); top-1 agreement with argmax Q*
and with the argmax of the average strategy (a move tied at the top counts as agreement); whether an argmax-Q*
move is in the network's top 3 slots; the cross-entropy of the network's distribution against the average
strategy and against the last iteration. Means come with 95 % percentile intervals from bootstrap resamples of
whole validation games; paired differences use the same resamples. Reference movers: a uniformly random move
(expected values), the solver's average-strategy and last-iteration argmax, the move played in the label game,
one-ply lookahead with value network v2, and the first-attempt policy head. Writes --out and prints a table.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch

from fow_shared.features import encode_belief
from fow_shared.recording import read_records
from pairb.belief_data import ENCODING, belief_batches, opponent_visible, rows_of
from pairb.belief_evaluator import BeliefNetworkEvaluator
from pairb.belief_net import BeliefNetwork
from pairb.data import split_of
from pairb.moves import legal_mask
from pairb.policy_data import counts_of, dense_targets, load_positions
from pairb.policy_net import CE_FLOOR, MASKED, PolicyNetwork, normalised, predict

A = "/labels/afterstate"
TIE = 1e-12  # Q* or strategy values this close to the maximum count as the maximum
METRICS = ("regret", "top1_q", "top1_mean", "top3_q", "ce_mean", "ce_last")
LOOKAHEAD = "one-ply lookahead (value network v2 g237)"
FIRST = "first-attempt policy head (per-board, last iteration)"


class Val:
    """The validation positions' moves, Q*, strategies and dense targets, by local index 0..n-1."""

    def __init__(self, arrays: dict, ids: np.ndarray):
        s = arrays["move_start"]
        self.ids = ids
        self.moves = [arrays["move"][s[i]:s[i + 1]].tolist() for i in ids]
        self.slots = [arrays["slot"][s[i]:s[i + 1]] for i in ids]
        self.q = [arrays["q"][s[i]:s[i + 1]] for i in ids]
        self.mean = [arrays["mean"][s[i]:s[i + 1]] for i in ids]
        self.last = [arrays["last"][s[i]:s[i + 1]] for i in ids]
        self.played = arrays["played"][ids]
        self.dense = {k: dense_targets(arrays, k, ids) for k in ("mean", "last")}
        self.n = len(ids)

    def choice_metrics(self, chosen) -> dict:
        """regret, top1_q and top1_mean of one chosen move index per position."""
        out = {k: np.zeros(self.n) for k in ("regret", "top1_q", "top1_mean")}
        for i, j in enumerate(chosen):
            q, m = self.q[i], self.mean[i]
            out["regret"][i] = q.max() - q[j]
            out["top1_q"][i] = q[j] >= q.max() - TIE
            out["top1_mean"][i] = m[j] >= m.max() - TIE
        return out

    def distribution_metrics(self, probs: np.ndarray) -> dict:
        """All metrics of a (n, 4096) distribution: the argmax slot is played, a promotion slot as a queen."""
        chosen, top3 = np.zeros(self.n, dtype=np.int64), np.zeros(self.n)
        for i in range(self.n):
            slots, p = self.slots[i], probs[i]
            j = int(np.argmax(p[slots]))
            same = np.flatnonzero(slots == slots[j])
            if len(same) > 1:
                queens = [k for k in same if self.moves[i][k].endswith("q")]
                j = queens[0] if queens else int(same[0])
            chosen[i] = j
            uniq = np.unique(slots)
            best = set(slots[self.q[i] >= self.q[i].max() - TIE].tolist())
            top3[i] = bool(best & set(uniq[np.argsort(-p[uniq], kind="stable")[:3]].tolist()))
        out = self.choice_metrics(chosen)
        out["top3_q"] = top3
        logp = np.log(np.maximum(probs, CE_FLOOR))
        for k in ("mean", "last"):
            out[f"ce_{k}"] = -(self.dense[k] * logp).sum(1)
        return out

    def uniform_metrics(self) -> dict:
        """Expected metrics of a uniformly random legal move (cross-entropy: uniform over the legal slots)."""
        out = {k: np.zeros(self.n) for k in METRICS}
        for i in range(self.n):
            q, m, slots = self.q[i], self.mean[i], self.slots[i]
            n_slots = len(np.unique(slots))
            k = len(np.unique(slots[q >= q.max() - TIE]))
            out["regret"][i] = (q.max() - q).mean()
            out["top1_q"][i] = (q >= q.max() - TIE).mean()
            out["top1_mean"][i] = (m >= m.max() - TIE).mean()
            out["top3_q"][i] = 1.0 if n_slots <= 3 else 1 - math.comb(n_slots - k, 3) / math.comb(n_slots, 3)
            out["ce_mean"][i] = out["ce_last"][i] = math.log(n_slots)
        return out


class Bootstrap:
    """Means over positions with percentile intervals from resampling whole games."""

    def __init__(self, games: np.ndarray, resamples: int, seed: int):
        self.names, self.game = np.unique(games, return_inverse=True)
        self.count = np.bincount(self.game).astype(np.float64)
        self.idx = np.random.default_rng(seed).integers(0, len(self.names), (resamples, len(self.names)))

    def __call__(self, x: np.ndarray) -> dict:
        sums = np.bincount(self.game, weights=x, minlength=len(self.names))
        boot = sums[self.idx].sum(1) / self.count[self.idx].sum(1)
        return {"mean": round(float(x.mean()), 6), "ci95": [round(float(np.percentile(boot, 2.5)), 6),
                                                          round(float(np.percentile(boot, 97.5)), 6)]}


def val_records(records_folder, keys: set) -> tuple[dict, dict]:
    """The label records of the validation positions in `keys`, by (game_id, ply); test games skipped and
    counted, training records passed over."""
    found, test_games, test_records = {}, set(), 0
    for path in sorted(Path(records_folder).glob("part-*.jsonl")):
        for r in read_records(path):
            if split_of(r.game_id) == "test":
                test_games.add(r.game_id)
                test_records += 1
                continue
            key = (r.game_id, r.agent_input.observation.ply)
            if key in keys:
                found[key] = r.agent_input
    return found, {"test_games_skipped": len(test_games), "test_records_skipped": test_records}


def lookahead_choices(turns: list, checkpoint: str, device: str) -> tuple[np.ndarray, str]:
    """For each turn, the legal move with the highest belief-weighted mean of value network v2's child values
    (evaluate_children, from the side to move), the first such move in legal-move order."""
    evaluator = BeliefNetworkEvaluator.from_checkpoint(checkpoint, device=device)
    chosen = np.zeros(len(turns), dtype=np.int64)
    started = time.time()
    for i, turn in enumerate(turns):
        moves, hyps = turn.observation.legal_moves, turn.belief.hypotheses
        total = sum(h.weight for h in hyps)
        scores, answers = np.zeros(len(moves)), {}
        for h in hyps:
            if h.fen not in answers:
                answers[h.fen] = evaluator.evaluate_children(h.fen)
            values = answers[h.fen]
            missing = [m for m in moves if m not in values]
            if missing:
                raise ValueError(f"no child value for {missing} on {h.fen}")
            scores += h.weight / total * np.array([values[m] for m in moves])
        chosen[i] = int(np.argmax(scores))
        if (i + 1) % 500 == 0:
            print(f"  lookahead: {i + 1} positions, {time.time() - started:.0f} s", flush=True)
    return chosen, evaluator.leaf_backend


@torch.no_grad()
def first_attempt_probs(path: Path, arrays: dict, ids: np.ndarray, device, planes, legal) -> np.ndarray:
    """The first attempt's belief distributions: the weight-averaged masked softmax of its per-board logits."""
    ckpt = torch.load(path, map_location="cpu", weights_only=True)
    if ckpt.get("encoding") != ENCODING:
        raise ValueError(f"checkpoint encoding {ckpt.get('encoding')!r}, not {ENCODING!r}")
    net = BeliefNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    net.eval().to(device)
    sizes = np.bincount(arrays["belief"], minlength=len(arrays["move_start"]) - 1)
    out = []
    for chunk in belief_batches(sizes, ids, max_boards=1 << 30, max_beliefs=256):
        rows, local = rows_of(arrays, chunk)
        r, c, lt = (torch.from_numpy(a).to(device) for a in (rows, chunk, local))
        w = normalised(torch.from_numpy(arrays["weight"][rows]).to(device), lt, len(chunk))
        _, logits = net(planes[r].float(), w, lt, len(chunk), None, return_policy=True)
        p = torch.softmax(logits.masked_fill(~legal[c][lt], MASKED), dim=1)
        out.append(p.new_zeros(len(chunk), p.shape[1]).index_add(0, lt, p * w[:, None]))
    return torch.cat(out).cpu().numpy()


@torch.no_grad()
def inference_ms(net: PolicyNetwork, turns: list, device, warmup: int = 10, runs: int = 50) -> dict:
    """Per-position time on one belief: encoding (planes and legal mask) plus the network pass and argmax."""
    net.eval().to(device)
    times = []
    for k, turn in enumerate(turns[: warmup + runs]):
        t0 = time.perf_counter()
        p, w = encode_belief(turn, opponent_visible)
        lg = legal_mask(turn.observation.legal_moves, turn.observation.player)
        t1 = time.perf_counter()
        probs = net.belief_probs(torch.from_numpy(p).to(device), torch.from_numpy(w).to(device),
                                 torch.zeros(len(w), dtype=torch.long, device=device), 1,
                                 torch.from_numpy(lg)[None].to(device))
        int(probs[0].argmax())  # waits for the device
        t2 = time.perf_counter()
        if k >= warmup:
            times.append((t2 - t0, t1 - t0, t2 - t1))
    t = np.array(times) * 1000
    return {"device": str(device), "boards": int(len(turns[0].belief.hypotheses)), "runs": len(times),
            "median_total_ms": round(float(np.median(t[:, 0])), 3), "median_encoding_ms": round(float(np.median(t[:, 1])), 3),
            "median_network_ms": round(float(np.median(t[:, 2])), 3)}


def fmt(cell: dict | None, digits: int) -> str:
    if cell is None:
        return "-"
    return f"{cell['mean']:.{digits}f} [{cell['ci95'][0]:.{digits}f}, {cell['ci95'][1]:.{digits}f}]"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default="/labels/policy/runs")
    ap.add_argument("--out", default="/labels/policy/eval-val.json")
    ap.add_argument("--records", default="/labels/solver-v2-sf8-480")
    ap.add_argument("--train-targets", nargs="+", default=[f"{A}/atlas-sf8", f"{A}/train-sf8-vm"])
    ap.add_argument("--val-targets", default=f"{A}/val-sf8")
    ap.add_argument("--cache-dir", default="/labels/policy/cache")
    ap.add_argument("--value-checkpoint", default="/repo/pair_b/checkpoints/belief-solver-v2-sf8-g237/best.pt")
    ap.add_argument("--first-attempt", default="/labels/runs/belief-solver-v2-sf8-policy-pw1.0-lr1e-3/best.pt")
    ap.add_argument("--timing-run", default="pooled-mean-s0")
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    device = torch.device(args.device)
    started = time.time()

    arrays = load_positions(args.records, args.train_targets, args.val_targets, args.cache_dir)
    counts = counts_of(arrays)
    ids = np.flatnonzero(arrays["split"] == "val")
    val = Val(arrays, ids)
    boot = Bootstrap(arrays["game_id"][ids], args.resamples, args.seed)
    print(f"{val.n} validation positions in {len(boot.names)} games; test games skipped when the positions were "
          f"built: {counts['test_games_skipped']}", flush=True)
    planes = torch.from_numpy(arrays.pop("planes")).to(device)
    legal = torch.from_numpy(arrays["legal"]).to(device)

    per_position, notes, info = {}, [], {}
    for ckpt_path in sorted(Path(args.runs).glob("*/best.pt")):
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
        if ckpt.get("input", "full") != "full":
            raise SystemExit(f"{ckpt_path}: input {ckpt['input']!r}; this script feeds every board (use eval_policy_depth.py)")
        net = PolicyNetwork(**ckpt["config"])
        net.load_state_dict(ckpt["state_dict"])
        probs = predict(net.to(device), arrays, ids, device, planes, legal).cpu().numpy()
        per_position[ckpt_path.parent.name] = val.distribution_metrics(probs)
        print(f"  scored {ckpt_path.parent.name} (epoch {ckpt['epoch']})", flush=True)
    groups = {}
    for name in per_position:
        stem, _, seed = name.rpartition("-s")
        if stem and seed.isdigit():
            groups.setdefault(stem, []).append(name)
    for stem, names in sorted(groups.items()):
        if len(names) > 1:
            per_position[f"{stem} (mean of {len(names)} seeds)"] = {
                k: np.mean([per_position[n][k] for n in names], axis=0) for k in METRICS}

    first = Path(args.first_attempt)
    if first.exists():
        try:
            per_position[FIRST] = val.distribution_metrics(first_attempt_probs(first, arrays, ids, device, planes, legal))
            splits = json.loads((first.parent / "splits.json").read_text())
            seen = set(splits["train"]) | set(splits["val"])
            info["first_attempt"] = {"checkpoint": str(first), "trained_games": len(splits["train"]),
                                     "val_games_in_its_train_or_val": len(seen & set(boot.names.tolist())),
                                     "val_games_in_its_train": len(set(splits["train"]) & set(boot.names.tolist()))}
        except Exception as exc:  # the stage asks to skip it with a note when it does not load
            notes.append(f"first attempt skipped: {exc!r}")
    else:
        notes.append(f"first attempt skipped: {first} missing")

    per_position["uniform random move (expected)"] = val.uniform_metrics()
    per_position["solver average strategy, argmax"] = val.choice_metrics([int(np.argmax(m)) for m in val.mean])
    per_position["solver last iteration, argmax"] = val.choice_metrics([int(np.argmax(m)) for m in val.last])
    per_position["move played in the label game"] = val.choice_metrics(val.played)

    keys = {(g, int(p)) for g, p in zip(arrays["game_id"][ids], arrays["ply"][ids])}
    found, skipped = val_records(args.records, keys)
    print(f"records re-read for lookahead and timing: {len(found)} validation turns; skipped {skipped}", flush=True)
    turns = [found[(g, int(p))] for g, p in zip(arrays["game_id"][ids], arrays["ply"][ids])]
    for i, t in enumerate(turns):
        if list(t.observation.legal_moves) != val.moves[i]:
            raise SystemExit(f"validation position {i}: record and cached moves differ")
    chosen, backend = lookahead_choices(turns, args.value_checkpoint, args.device)
    per_position[LOOKAHEAD] = val.choice_metrics(chosen)
    info["lookahead"] = {"checkpoint": args.value_checkpoint, "leaf_backend": backend}

    table = {name: {k: boot(m[k]) for k in METRICS if k in m} for name, m in per_position.items()}
    pairs = []
    for left, right in (("pooled-mean", "perboard-mean"), ("pooled-mean", "pooled-last"), ("pooled-mean", None)):
        for s in [f"-s{i}" for i in range(3)] + [" (mean of 3 seeds)"]:
            a = left + s
            b = (right + s) if right else LOOKAHEAD
            if a in per_position and b in per_position:
                pairs.append((a, b))
    paired = {f"{a} minus {b}": {k: boot(per_position[a][k] - per_position[b][k])
                                 for k in METRICS if k in per_position[a] and k in per_position[b]} for a, b in pairs}

    targets = {"entropy_mean": boot(-(val.dense["mean"] * np.log(np.maximum(val.dense["mean"], CE_FLOOR))).sum(1)),
               "entropy_last": boot(-(val.dense["last"] * np.log(np.maximum(val.dense["last"], CE_FLOOR))).sum(1)),
               "argmax_mean_differs_from_argmax_last": boot(np.array(
                   [float(np.argmax(m) != np.argmax(l)) for m, l in zip(val.mean, val.last)])),
               "total_variation_mean_last": boot(np.array([0.5 * np.abs(m - l).sum() for m, l in zip(val.mean, val.last)])),
               "max_prob_mean": boot(np.array([m.max() for m in val.mean])),
               "promotion_positions": int(sum(len(np.unique(s)) < len(s) for s in val.slots))}
    timing = None
    run_ckpt = Path(args.runs) / args.timing_run / "best.pt"
    if run_ckpt.exists():
        ckpt = torch.load(run_ckpt, map_location="cpu", weights_only=True)
        net = PolicyNetwork(**ckpt["config"])
        net.load_state_dict(ckpt["state_dict"])
        sixteen = [t for t in turns if len(t.belief.hypotheses) == 16]
        timing = {"run": args.timing_run, **inference_ms(net, sixteen, device)}

    report = {"positions": val.n, "games": len(boot.names), "resamples": args.resamples, "bootstrap_seed": args.seed,
              "data": counts, "metrics": METRICS, "tie_tolerance": TIE, "table": table, "paired": paired,
              "targets": targets, "inference": timing, "info": info, "notes": notes,
              "seconds": round(time.time() - started, 1)}
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")

    digits = {"regret": 4, "top1_q": 3, "top1_mean": 3, "top3_q": 3, "ce_mean": 3, "ce_last": 3}
    print(f"\n{val.n} validation positions, {len(boot.names)} games; mean [95 % interval over "
          f"{args.resamples} game resamples]")
    print(f"{'mover':54s} " + " ".join(f"{k:>24s}" for k in METRICS))
    for name, row in table.items():
        print(f"{name:54s} " + " ".join(f"{fmt(row.get(k), digits[k]):>24s}" for k in METRICS))
    print("\npaired differences (left minus right)")
    for name, row in paired.items():
        print(f"{name}\n    " + "  ".join(f"{k} {fmt(row[k], digits[k])}" for k in METRICS if k in row))
    print(f"\ntargets: {json.dumps(targets)}\ninference: {json.dumps(timing)}\ninfo: {json.dumps(info)}\nnotes: {notes}")
    print(f"-> {args.out} ({report['seconds']} s)")


if __name__ == "__main__":
    main()
