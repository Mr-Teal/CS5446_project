"""Print where a long run stands: training progress, health, and the hourly matches so far.

    python report.py --name long
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"


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
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    plan_file = RUNS / f"{args.name}-plan.json"
    if not plan_file.exists():
        waiting = alive(f"run_long.py --name {args.name}")
        print(f"Run {args.name!r} has not started yet" + (" (the launcher is waiting to start)." if waiting else
                                                          " and no launcher is running."))
        return
    plan = json.loads(plan_file.read_text())
    now = time.time()
    elapsed = (min(now, plan["end_epoch"]) - plan["start_epoch"]) / 3600
    attempts = lines(RUNS / f"{args.name}-attempts.jsonl")
    folders = sorted(RUNS.glob(f"{args.name}-[0-9]*/"), key=lambda f: int(f.name.rsplit("-", 1)[1]))
    log = lines(folders[-1] / "log.jsonl") if folders else []
    updates = [r for r in log if r["type"] == "update"]
    evals = [r for r in log if r["type"] == "eval"]
    finished = any(a.get("finished") for a in attempts)
    trainer, launcher = alive(f"fowppo.train --name {args.name}-"), alive(f"run_long.py --name {args.name}")
    evaluator = alive(f"hourly_eval.py --name {args.name}")
    log_file = folders[-1] / "log.jsonl" if folders else None
    log_age = now - log_file.stat().st_mtime if log_file and log_file.exists() else None

    print(f"PPO run {args.name!r}: {plan['start'][5:16]} to {plan['end'][5:16]} ({plan['hours']} h planned)")
    if finished:
        state = "FINISHED"
    elif trainer and launcher:
        state = "RUNNING"
    elif launcher:
        state = "RESTARTING (the launcher is alive, no trainer right now)"
    else:
        state = "STOPPED EARLY: no launcher and no trainer are running"
    restarts = max(len(folders) - 1, 0)
    print(f"Status: {state}; {elapsed:.2f} h elapsed; {restarts} restart(s)"
          + (f"; log updated {log_age:.0f} s ago" if log_age is not None and not finished else "")
          + ("" if evaluator or finished else "; WARNING: the hourly evaluator is not running"))
    for a in attempts:
        if not a.get("finished"):
            why = "hang" if a.get("stalled") else f"exit code {a['exit_code']}"
            print(f"  attempt {a['attempt']} stopped after {a['minutes']} min ({why})")
    if updates:
        u = updates[-1]
        print(f"Trained: {u['plies'] / 1e6:.1f} M moves; {u['plies_per_second']:.0f} moves/s in this attempt; "
              f"learning rate {u['learning_rate']:.2e}; entropy {u['entropy']:.2f}; "
              f"self-play game {u['mean_plies'] or 0:.0f} plies; learner share {u['learner_share']:.2f}")
    skipped = sum(u.get("skipped_steps", 0) for u in updates)
    restored = sum(bool(u.get("restored")) for u in updates)
    if skipped or restored:
        print(f"Guard in this attempt: {skipped} training step(s) skipped, {restored} update(s) dropped")
    if evals:
        e = evals[-1]
        score = {(r["opponent"], r["sample"]): r["score"] for r in e["results"]}
        print(f"In-training check at {e['plies'] / 1e6:.1f} M moves ({e['results'][0]['games']} games each): "
              f"random {score[('random', True)]:.3f}; always-capture {score[('greedy', True)]:.3f} sampled, "
              f"{score[('greedy', False)]:.3f} best move")
    table = lines(RUNS / f"{args.name}-hourly" / "table.jsonl")
    print()
    print("Matches in the team's loop (newest saved network, moves sampled from the policy):")
    print("hour  | saved at | moves trained | vs piece-count bot   | vs quick Stockfish   | vs random")
    for row in table:
        hour = "final" if row["label"] == "final" else f"{row['hour']:5.2f}"
        print(f"{hour:5s} | {row['saved_at']} | {row['plies'] / 1e6:10.1f} M  | {cell(row.get('material')):20s} | "
              f"{cell(row.get('stockfish-d1')):20s} | {cell(row.get('random'))}")
    if not table:
        print("(none yet)")


if __name__ == "__main__":
    main()
