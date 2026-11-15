"""Every half hour of a run, play the newest saved network against the team's players.

    python hourly_eval.py --name belief

The first run's script, with the step set to half an hour (--every-hours 0.5) and 4 match processes.

It reads runs/<name>-plan.json (written by run_long.py) for the start and end times. At each full
hour of the run, and once more when the run has ended, it copies the newest saved weights to
runs/<name>-hourly/hour-NN.pt (or final.pt), plays --games games against each opponent with
team_match.py, and appends one line to runs/<name>-hourly/table.jsonl. The matches run on the CPU,
so they do not take the GPU from training. A failed match is recorded and the loop goes on.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"


def newest_weights(name: str, final_only: bool = False):
    patterns = ("final.pt",) if final_only else ("latest.pt", "snapshot-*.pt", "final.pt")
    files = [f for pattern in patterns for f in RUNS.glob(f"{name}-[0-9]*/{pattern}")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def play(checkpoint: Path, opponent: str, games: int, jobs: int, out: Path) -> dict:
    command = [sys.executable, "-W", "ignore::DeprecationWarning", str(HERE / "team_match.py"), "--checkpoint",
               str(checkpoint), "--opponent", opponent, "--games", str(games), "--jobs", str(jobs), "--out", str(out)]
    try:
        with open(f"{out}.log", "w") as log:
            subprocess.run(command, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, timeout=45 * 60, check=True)
        summary = json.loads((out / "summary.json").read_text())
        score = summary["score_a"]
        return {"score": score["mean"], "wilson95": score["wilson95"], "wins": summary["ppo_wins"],
                "draws": summary["draws"], "losses": summary["ppo_losses"], "errors": summary["errors"],
                "plies_mean": summary["plies_mean"], "seconds": summary["seconds"]}
    except Exception as exc:  # the loop must outlive one bad match
        return {"error": f"{type(exc).__name__}: {exc}"}


def evaluate(name: str, label: str, hour: float, source: Path, args) -> None:
    folder = RUNS / f"{name}-hourly"
    folder.mkdir(exist_ok=True)
    copy = folder / f"{label}.pt"
    shutil.copy2(source, copy)
    saved = torch.load(copy, map_location="cpu")
    row = {"label": label, "hour": hour, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "source": str(source.relative_to(HERE)), "plies": saved["plies"], "updates": saved["updates"],
           "saved_at": time.strftime("%H:%M:%S", time.localtime(source.stat().st_mtime))}
    for opponent in args.opponents:
        row[opponent] = play(copy, opponent, args.games, args.jobs, folder / f"{label}-vs-{opponent}")
    with open(folder / "table.jsonl", "a") as table:
        table.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--opponents", nargs="+", default=["material", "stockfish-d1"])
    parser.add_argument("--final-opponents", nargs="+", default=["random", "material", "stockfish-d1"])
    parser.add_argument("--every-hours", type=float, default=0.5)
    parser.add_argument("--delay-seconds", type=float, default=90.0, help="wait this long after the hour for the save")
    args = parser.parse_args()
    plan_file = RUNS / f"{args.name}-plan.json"
    while not plan_file.exists():
        time.sleep(5)
    plan = json.loads(plan_file.read_text())
    start, end = plan["start_epoch"], plan["end_epoch"]
    step = args.every_hours * 3600
    k = 1
    while start + k * step < end - 60:
        due = start + k * step + args.delay_seconds
        time.sleep(max(0.0, due - time.time()))
        source = newest_weights(args.name)
        if source is not None:
            hour = k * args.every_hours
            label = f"hour-{int(hour):02d}" if float(hour).is_integer() else f"hour-{hour:.2f}"
            evaluate(args.name, label, hour, source, args)
        k += 1
    # The end of the run: wait for final.pt (the launcher may still be finishing an attempt).
    deadline = end + 20 * 60
    while newest_weights(args.name, final_only=True) is None and time.time() < deadline:
        time.sleep(10)
    source = newest_weights(args.name, final_only=True) or newest_weights(args.name)
    if source is not None:
        args.opponents = args.final_opponents
        evaluate(args.name, "final", plan["hours"], source, args)


if __name__ == "__main__":
    main()
