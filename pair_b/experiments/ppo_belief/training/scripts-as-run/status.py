"""Where the belief-input run stands, next to the first PPO run (no belief input).

    python status.py --name belief

Prints training progress and health, the trainer's own checks against the two hand-made players,
and the half-hourly matches against the team's players (team_match.py, 100 games each). Beside each
match row is the first run's network of the same hour, if there is one, and the first run's hourly
network that had trained on the nearest number of moves.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
PLAIN = HERE.parent / "ppo-pilot-2026-11-14" / "runs"


def lines(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:  # a line still being written
            pass
    return rows


def alive(needle: str) -> bool:
    listing = subprocess.run(["ps", "-Ao", "command="], capture_output=True, text=True).stdout
    return any(needle in line for line in listing.splitlines())


def cell(result) -> str:
    if result is None:
        return "-"
    if "error" in result:
        return "failed"
    text = f"{result['score']:.3f} ({result['wins']}-{result['draws']}-{result['losses']})"
    return text + (f", {result['errors']} failed" if result["errors"] else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", default="belief")
    args = parser.parse_args()
    plan = json.loads((RUNS / f"{args.name}-plan.json").read_text())
    now = time.time()
    elapsed = (min(now, plan["end_epoch"]) - plan["start_epoch"]) / 3600
    attempts = lines(RUNS / f"{args.name}-attempts.jsonl")
    folders = sorted(RUNS.glob(f"{args.name}-[0-9]*/"), key=lambda f: int(f.name.rsplit("-", 1)[1]))
    updates, evals = [], []
    for folder in folders:
        log = lines(folder / "log.jsonl")
        updates += [r for r in log if r["type"] == "update"]
        evals += [dict(r, attempt=folder.name) for r in log if r["type"] == "eval"]
    trainer, launcher = alive(f"fowppo.train --name {args.name}-"), alive(f"run_long.py --name {args.name}")
    evaluator = alive(f"hourly_eval.py --name {args.name}")
    print(f"Run {args.name!r}: {elapsed:.2f} of {plan['hours']:.2f} hours ({plan['start'][11:16]} to {plan['end'][11:16]}); "
          f"trainer {'running' if trainer else 'not running'}, launcher {'running' if launcher else 'not running'}, "
          f"match loop {'running' if evaluator else 'not running'}; attempts started {len(folders)}, "
          f"ended early {sum(1 for a in attempts if not a.get('finished'))}")
    if updates:
        last, recent = updates[-1], updates[-100:]
        speed = (recent[-1]["plies"] - recent[0]["plies"]) / max((recent[-1]["minutes"] - recent[0]["minutes"]) * 60, 1e-9)
        skipped = sum(r.get("skipped_steps", 0) for r in updates)
        restored = sum(bool(r.get("restored")) for r in updates)
        mean = lambda key: sum(r[key] for r in recent) / len(recent)  # noqa: E731
        print(f"Training: {last['plies'] / 1e6:.1f} million moves in {last['updates']} updates; last 100 updates: "
              f"{speed:,.0f} moves/s (collect {mean('collect_seconds'):.1f} s, train {mean('train_seconds'):.1f} s), "
              f"entropy {mean('entropy'):.2f}, explained variance {mean('explained_variance'):.2f}, "
              f"game length {sum(r['mean_plies'] or 0 for r in recent) / len(recent):.0f} plies, draws {mean('draws'):.3f}, "
              f"learning rate {last['learning_rate']:.2e}; invalid-number guard: {skipped} steps skipped, {restored} updates dropped")
    if evals:
        print("\nTrainer's own check, 200 games each (sampled moves / most likely move):")
        print("  moves trained   random player    always-capture player")
        for r in evals:
            by = {(x["opponent"], x["sample"]): x["score"] for x in r["results"]}
            print(f"  {r['plies'] / 1e6:8.1f} M     {by[('random', True)]:.3f} / {by[('random', False)]:.3f}    "
                  f"{by[('greedy', True)]:.3f} / {by[('greedy', False)]:.3f}")
    table = lines(RUNS / f"{args.name}-hourly" / "table.jsonl")
    plain = lines(PLAIN / "long-hourly" / "table.jsonl")
    print("\nMatches in the team's loop, 100 games each (score, wins-draws-losses):")
    print("  hours  moves trained  piece-count bot      quick Stockfish      | first run, same hour             | first run, nearest moves")
    for row in table:
        same = next((p for p in plain if abs(p["hour"] - row["hour"]) < 1e-6 and p["label"] != "final"), None)
        near = min((p for p in plain if p["label"] != "final"), key=lambda p: abs(p["plies"] - row["plies"]), default=None)
        same_text = "-" if same is None else f"{same['material']['score']:.3f} / {same['stockfish-d1']['score']:.3f} ({same['plies'] / 1e6:.0f} M)"
        near_text = "-" if near is None else (f"hour {near['hour']:.0f}, {near['plies'] / 1e6:.0f} M: "
                                              f"{near['material']['score']:.3f} / {near['stockfish-d1']['score']:.3f}")
        extra = "" if "random" not in row else f"   random player {cell(row['random'])}"
        print(f"  {row['hour']:5.2f}  {row['plies'] / 1e6:8.1f} M     {cell(row.get('material')):20s} {cell(row.get('stockfish-d1')):20s} "
              f"| {same_text:32s} | {near_text}{extra}")
    if not table:
        print("  (none finished yet)")


if __name__ == "__main__":
    main()
