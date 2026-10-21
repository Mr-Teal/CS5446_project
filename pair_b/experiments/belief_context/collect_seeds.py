"""Collect the belief-network seed reruns into one table.

    .venv/bin/python experiments/belief_context/collect_seeds.py --runs runs/belief-seeds --out experiments/belief_context/seeds.json

Reads every <variant>-s<seed>/ folder under --runs (variants ctx, noctx, pure, as trained by
scripts/train_belief_net.py with --use-d1, --use-d1 --no-context, and neither) plus the three committed
seed-0 runs under checkpoints/, takes each run's eval-d6-check-train.json, and writes per-variant board
and position errors by seed with their mean, standard deviation and range, and the context effect
(ctx minus noctx) per seed. Copies each run's summary.json and eval JSON next to the output, under
seed_runs/<variant>-s<seed>/ (runs/ is git-ignored), with home-folder paths written as ~, so the numbers
are in the repository without the checkpoints. A folder without both files is skipped and named.
"""
import argparse
import json
import shutil
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = {"ctx": "belief-v1-d1", "noctx": "belief-v1-d1-noctx", "pure": "belief-v1-pure"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    keep = out.parent / "seed_runs"
    rows = {v: {} for v in COMMITTED}
    sources = {}
    for variant, name in COMMITTED.items():
        sources[(variant, 0)] = ROOT / "checkpoints" / name
    for folder in sorted(Path(args.runs).glob("*-s*")):
        variant, seed = folder.name.rsplit("-s", 1)
        if variant in COMMITTED:
            sources[(variant, int(seed))] = folder
    home = str(Path.home())

    def tidy(obj):
        if isinstance(obj, str):
            return obj.replace(home, "~") if obj.startswith(home) else obj
        if isinstance(obj, dict):
            return {k: tidy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [tidy(v) for v in obj]
        return obj
    for (variant, seed), folder in sorted(sources.items()):
        if not all((folder / f).is_file() for f in ("summary.json", "eval-d6-check-train.json")):
            print(f"skipping {folder}: no summary or eval yet")
            continue
        ev = json.loads((folder / "eval-d6-check-train.json").read_text())
        summary = json.loads((folder / "summary.json").read_text())
        rows[variant][seed] = {"board_mae": ev["network"]["board_mae"], "root_mae": ev["network"]["root_mae"],
                              "best_epoch": summary["best_epoch"], "seconds": summary["seconds"],
                              "code": ev.get("git_commit") or summary.get("git_commit") or "the 18 October run"}
        target = keep / f"{variant}-s{seed}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "summary.json").write_text(json.dumps(tidy(summary), indent=2) + "\n")
        (target / "eval-d6-check-train.json").write_text(json.dumps(tidy(ev), indent=2) + "\n")
    baseline = json.loads((ROOT / "checkpoints" / "belief-v1-d1" / "eval-d6-check-train.json").read_text())["baseline"]

    def stats(values):
        return {"mean": statistics.fmean(values), "sd": statistics.stdev(values) if len(values) > 1 else None,
                "min": min(values), "max": max(values), "n": len(values)}
    report = {"data": "d6-check train bucket (3,818 beliefs, 30,406 boards)", "training": "d6-v1, scripts/train_belief_net.py",
              "quick_stockfish_alone": {"board_mae": baseline["board_mae"], "root_mae": baseline["root_mae"]},
              "variants": {}}
    for variant, by_seed in rows.items():
        seeds = sorted(by_seed)
        report["variants"][variant] = {
            "flags": {"ctx": "--use-d1", "noctx": "--use-d1 --no-context", "pure": "(planes only)"}[variant],
            "seeds": seeds, "by_seed": {str(s): by_seed[s] for s in seeds},
            "board_mae": stats([by_seed[s]["board_mae"] for s in seeds]),
            "root_mae": stats([by_seed[s]["root_mae"] for s in seeds])}
    shared = sorted(set(rows["ctx"]) & set(rows["noctx"]))
    diffs = [rows["ctx"][s]["board_mae"] - rows["noctx"][s]["board_mae"] for s in shared]
    rdiffs = [rows["ctx"][s]["root_mae"] - rows["noctx"][s]["root_mae"] for s in shared]
    report["context_effect_ctx_minus_noctx"] = {"seeds": shared, "board_mae_by_seed": diffs, "board_mae": stats(diffs),
                                                 "root_mae_by_seed": rdiffs, "root_mae": stats(rdiffs)}
    out.write_text(json.dumps(report, indent=2) + "\n")
    for variant, r in report["variants"].items():
        b = r["board_mae"]
        print(f"{variant:6s} board {b['mean']:.4f} sd {b['sd'] if b['sd'] is None else round(b['sd'], 4)} range {b['min']:.4f} to {b['max']:.4f} over {b['n']} seeds")
    c = report["context_effect_ctx_minus_noctx"]["board_mae"]
    print(f"context effect (ctx - noctx) on board error: mean {c['mean']:+.4f}, range {c['min']:+.4f} to {c['max']:+.4f}")


if __name__ == "__main__":
    main()
