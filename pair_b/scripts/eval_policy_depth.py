"""Evaluate the policy networks trained on the depth labels (stage 2) on the validation positions of each label set.

    torch_policy.sh pair_b/scripts/eval_policy_depth.py

A label set (--sets NAME=FOLDER) holds both splits in one folder and covers a subset of the positions; its
validation positions are those with a good row. Every run in --runs is scored on every set: against that set's Q*
(regret, top-1 agreement with argmax Q* and with the teacher's argmax, argmax Q* in the top 3; as in
eval_policy_net.py) and against its teacher, the last-iteration strategy (pairb.policy_metrics: cross-entropy,
total-variation distance, mass on the teacher's support, top move in the support). Reference movers per set: a
uniformly random move (expected values), the teacher's argmax, the move played in the label game, one-ply lookahead
with value network v2 g237. Position groups: all, genuinely mixed (purify_loss > 0.005) and one-hot. Means come with
95 % intervals from resampling whole validation games, one resampling per set and group shared by every mover, so
paired differences use the same resamples: pooled minus per-board within each set (all and genuinely mixed), and on
the d6 labels the d6-trained minus the d2-trained runs. A (game_id, ply) appearing twice in a set is refused.
Writes --out and prints the tables.

Stage 3 (fine-tuning), with the stage-1 checkpoints used as they are (zero-shot) and the stage-2 runs:
    ... --runs fine-tuned=/labels/policy/runs-depth-ft from-scratch=/labels/policy/runs-depth \\
        zero-shot=/labels/policy/runs:pooled-last-s* zero-shot=/labels/policy/runs:perboard-mean-s* \\
        --pairs finetune --out /labels/policy/eval-depth-ft.json
adds each fine-tuned run minus the stage-1 checkpoint it started from (pair_list).

Stage 4 (convolutional output) on the stage-1 targets, whose validation rows sit in one folder:
    ... --sets sf8=/labels/afterstate/val-sf8 --runs /labels/policy/runs-conv \\
        '/labels/policy/runs:pooled-last-s*' '/labels/policy/runs:perboard-mean-s*' --pairs conv \\
        --out /labels/policy/eval-conv.json
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from eval_policy_net import Bootstrap, Val, fmt, lookahead_choices, val_records
from pairb.policy_data import counts_of, load_positions
from pairb.policy_metrics import (MIXING_WORKS, ONE_HOT, SUPPORT, label_kinds, pure_teacher_metrics,
                                  teacher_metrics, uniform_teacher_metrics)
from pairb.policy_net import PolicyNetwork, predict

METRICS = ("regret", "top1_q", "top1_teacher", "top3_q", "ce_teacher", "tv_teacher", "mass_on_support",
           "top_in_support")
GROUPS = ("all", "mixing_works", "one_hot")
LOOKAHEAD = "one-ply lookahead (value network v2 g237)"
DIGITS = {"regret": 4}
VALUE_TAUS = ("0.01", "0.02", "0.05", "0.1")  # temperatures of the move-value runs, as in their folder names


def renamed(m: dict) -> dict:
    """Val's metrics under this script's names: the teacher is the last iteration (policy_mean equals it here)."""
    out = {k: m[k] for k in ("regret", "top1_q", "top3_q") if k in m}
    out["top1_teacher"] = m["top1_mean"]
    return out


def label_stats(arrays: dict) -> dict:
    """Per split: positions with a good row, share one-hot, and (where rows carry the purification test) share
    genuinely mixed."""
    out = {}
    for s in ("train", "val"):
        ids = np.flatnonzero(arrays["split"] == s)
        kinds = label_kinds(arrays, ids)
        tested = ~np.isnan(arrays["purify"][ids])
        out[s] = {"positions": int(len(ids)), "one_hot_share": round(float(kinds["one_hot"].mean()), 4) if len(ids) else None,
                  "positions_with_purification_test": int(tested.sum()),
                  "mixing_works_share_of_tested": round(float(kinds["mixing_works"][tested].mean()), 4) if tested.any() else None}
    return out


def pair_list(kind: str, name: str, sets: dict) -> list[tuple[str, str]]:
    """The (left, right) movers whose paired differences are reported on label set `name`, seed by seed and for
    the mean over seeds. depth (stage 2): pooled minus per-board of the runs trained on this set; on d6, d6-trained
    minus d2-trained. finetune (stage 3): the same among the fine-tuned runs, and each fine-tuned run minus the
    stage-1 checkpoint it started from, used without fine-tuning (zero-shot)."""
    seeds = [f"-s{k}" for k in range(3)] + [" (mean of 3 seeds)"]
    if kind == "value":  # move-value targets (13 Nov): against the conv runs trained on the solver's strategy, the lookahead
        return [(f"pooled-conv-value-t{t}{s}", other) for t in VALUE_TAUS for s in seeds
                for other in (f"pooled-conv{s}", LOOKAHEAD)]
    if kind == "conv":  # stage 4: the output-layer effect, the belief effect with the new output, the lookahead
        return ([(f"pooled-conv{s}", f"pooled-last{s}") for s in seeds] +
                [(f"pooled-conv{s}", f"per-board-conv{s}") for s in seeds] +
                [(f"pooled-conv{s}", LOOKAHEAD) for s in seeds])
    if kind == "finetune-conv":  # stage 5: the stage-3 comparisons with the convolutional output
        ft = "fine-tuned "
        pairs = [(f"{ft}{name}-pooled-conv{s}", f"{ft}{name}-per-board-conv{s}") for s in seeds]
        if name == "d6" and "d2" in sets:
            pairs += [(f"{ft}d6-{d}{s}", f"{ft}d2-{d}{s}") for d in ("pooled-conv", "per-board-conv") for s in seeds]
        return pairs + [(f"{ft}{name}-{d}-conv{s}", f"{ft}{name}-{d}{s}") for d in ("pooled", "per-board") for s in seeds]
    ft = "fine-tuned " if kind == "finetune" else ""
    pairs = [(f"{ft}{name}-pooled{s}", f"{ft}{name}-per-board{s}") for s in seeds]
    if name == "d6" and "d2" in sets:
        pairs += [(f"{ft}d6-{design}{s}", f"{ft}d2-{design}{s}") for design in ("pooled", "per-board") for s in seeds]
    if kind == "finetune":
        start = {"pooled": "pooled-last", "per-board": "perboard-mean"}  # the stage-1 runs each design starts from
        pairs += [(f"{ft}{name}-{design}{s}", f"zero-shot {start[design]}{s}") for design in start for s in seeds]
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", default=["/labels/policy/runs-depth"],
                    help="[NAME=]FOLDER[:GLOB] of run folders (GLOB default *); a run is called 'NAME run' when NAME is given")
    ap.add_argument("--pairs", choices=("depth", "finetune", "conv", "finetune-conv", "value"), default="depth",
                    help="depth: stage 2's paired differences; finetune: stage 3's (runs named fine-tuned and zero-shot); "
                         "conv: stage 4's (pooled-conv against pooled-last, per-board-conv and the lookahead); "
                         "finetune-conv: stage 5's (fine-tuned conv runs: pooled-conv minus per-board-conv, d6 minus d2, "
                         "conv minus the fully connected fine-tuned runs); value: move-value runs "
                         "(pooled-conv-value-tT) minus pooled-conv and minus the lookahead")
    ap.add_argument("--sets", nargs="+", default=["d2=/labels/policy/depthlabels/d2", "d6=/labels/policy/depthlabels/d6"])
    ap.add_argument("--out", default="/labels/policy/eval-depth.json")
    ap.add_argument("--records", default="/labels/solver-v2-sf8-480")
    ap.add_argument("--cache-dir", default="/labels/policy/cache")
    ap.add_argument("--value-checkpoint", default="/repo/pair_b/checkpoints/belief-solver-v2-sf8-g237/best.pt")
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    device = torch.device(args.device)
    started = time.time()
    sets = dict(s.split("=", 1) for s in args.sets)

    data = {name: load_positions(args.records, [folder], None, args.cache_dir, args.workers, subset=True, unique=True)
            for name, folder in sets.items()}
    vals = {name: np.flatnonzero(a["split"] == "val") for name, a in data.items()}
    keys = {(g, int(p)) for name, a in data.items() for g, p in zip(a["game_id"][vals[name]], a["ply"][vals[name]])}
    found, skipped = val_records(args.records, keys)
    print(f"records re-read for lookahead: {len(found)} validation turns; skipped {skipped}", flush=True)
    order = sorted(found)
    chosen, backend = lookahead_choices([found[k] for k in order], args.value_checkpoint, args.device)
    lookahead = dict(zip(order, chosen.tolist()))

    nets, runs = {}, {}
    for spec in args.runs:
        prefix, _, rest = spec.rpartition("=")
        folder, _, pattern = rest.partition(":")
        for ckpt_path in sorted(Path(folder).glob(f"{pattern or '*'}/best.pt")):
            name = f"{prefix} {ckpt_path.parent.name}" if prefix else ckpt_path.parent.name
            if name in nets:
                raise SystemExit(f"two runs named {name!r}: give the folders different NAME= prefixes")
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
            net = PolicyNetwork(**ckpt["config"])
            net.load_state_dict(ckpt["state_dict"])
            nets[name] = net.to(device)
            s = json.loads((ckpt_path.parent / "summary.json").read_text())
            runs[name] = {"folder": str(ckpt_path.parent), "best_epoch": s["best_epoch"], "epochs_run": s["epochs_run"],
                          "val_ce": s["val"]["val_ce"], "seconds": s["seconds"], "n": s["n"], "init": s.get("init")}

    report = {"metrics": METRICS, "groups": GROUPS, "thresholds": {"support": SUPPORT, "one_hot": ONE_HOT,
              "mixing_works": MIXING_WORKS}, "resamples": args.resamples, "bootstrap_seed": args.seed,
              "lookahead": {"checkpoint": args.value_checkpoint, "leaf_backend": backend, "turns": len(order)},
              "records_skipped": skipped, "runs": runs, "sets": {}}
    for name, arrays in data.items():
        ids = vals[name]
        val = Val(arrays, ids)
        teacher = val.dense["last"]
        legal = arrays["legal"][ids]
        per_position = {}
        for run, net in nets.items():
            probs = predict(net, arrays, ids, device).cpu().numpy()
            per_position[run] = {**renamed(val.distribution_metrics(probs)), **teacher_metrics(probs, teacher)}
        stems = {}
        for run in nets:
            stem, _, seed = run.rpartition("-s")
            stems.setdefault(stem, []).append(run)
        for stem, members in sorted(stems.items()):
            if len(members) > 1:
                per_position[f"{stem} (mean of {len(members)} seeds)"] = {
                    k: np.mean([per_position[r][k] for r in members], axis=0) for k in METRICS}
        per_position["uniform random move (expected)"] = {**renamed(val.uniform_metrics()),
                                                          **uniform_teacher_metrics(legal, teacher)}
        movers = {"teacher (last iteration), argmax": [int(np.argmax(m)) for m in val.last],
                  "move played in the label game": val.played.tolist(),
                  LOOKAHEAD: [lookahead[(g, int(p))] for g, p in zip(arrays["game_id"][ids], arrays["ply"][ids])]}
        for mover, picks in movers.items():
            slots = np.array([val.slots[i][j] for i, j in enumerate(picks)])
            per_position[mover] = {**renamed(val.choice_metrics(picks)), **pure_teacher_metrics(slots, teacher)}

        kinds = label_kinds(arrays, ids)
        masks = {"all": np.ones(len(ids), dtype=bool), "mixing_works": kinds["mixing_works"], "one_hot": kinds["one_hot"]}
        games = arrays["game_id"][ids]
        boots = {g: Bootstrap(games[m], args.resamples, args.seed) for g, m in masks.items() if m.any()}
        tables = {g: {mover: {k: boots[g](m[k][masks[g]]) for k in METRICS if k in m} for mover, m in per_position.items()}
                  for g in boots}
        pairs = pair_list(args.pairs, name, sets)
        missing = [f"{a} minus {b}" for a, b in pairs if a not in per_position or b not in per_position]
        if missing:
            print(f"{name}: pairs without both movers, not reported: {missing}", flush=True)
        paired ={g: {f"{a} minus {b}": {k: boots[g](per_position[a][k][masks[g]] - per_position[b][k][masks[g]])
                                         for k in METRICS if k in per_position[a] and k in per_position[b]}
                      for a, b in pairs if a in per_position and b in per_position}
                  for g in ("all", "mixing_works") if g in boots}
        report["sets"][name] = {
            "folder": sets[name], "counts": counts_of(arrays), "label_stats": label_stats(arrays),
            "val_positions": {g: int(m.sum()) for g, m in masks.items()},
            "val_games": {g: int(len(set(games[m].tolist()))) for g, m in masks.items()},
            "tables": tables, "paired": paired, "missing_pairs": missing}
    report["seconds"] = round(time.time() - started, 1)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nruns: {json.dumps(runs)}")
    for name, r in report["sets"].items():
        print(f"\n=== label set {name} ({r['folder']}): counts {json.dumps(r['counts'])}")
        print(f"label stats: {json.dumps(r['label_stats'])}")
        print(f"val positions {r['val_positions']}, games {r['val_games']}")
        for g, table in r["tables"].items():
            print(f"\n--- {name} labels, {g} positions ({r['val_positions'][g]}); mean [95 % interval over "
                  f"{args.resamples} game resamples]")
            print(f"{'mover':48s} " + " ".join(f"{k:>24s}" for k in METRICS))
            for mover, row in table.items():
                print(f"{mover:48s} " + " ".join(f"{fmt(row.get(k), DIGITS.get(k, 3)):>24s}" for k in METRICS))
        for g, rows in r["paired"].items():
            print(f"\n--- {name} labels, {g} positions: paired differences (left minus right)")
            for pair, row in rows.items():
                print(f"{pair}\n    " + "  ".join(f"{k} {fmt(row[k], DIGITS.get(k, 3))}" for k in METRICS if k in row))
    print(f"-> {args.out} ({report['seconds']} s)")


if __name__ == "__main__":
    main()
