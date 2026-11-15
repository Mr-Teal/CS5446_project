"""Run the long training and keep it alive until the planned end time.

    python run_long.py --name long --hours 12

Each attempt is one `python -m fowppo.train` under caffeinate (the Mac does not go to sleep while it
runs; keep the lid open and the power connected). Attempt k writes runs/<name>-k/ and
runs/<name>-k.out. If an attempt stops before the end time (a crash), or its log stands still for
--stall-minutes (a hang), it is stopped and the next attempt continues from the newest saved
weights for the time that is left, with the learning rate where the schedule had it.

runs/<name>-plan.json holds the start and end times; runs/<name>-attempts.jsonl lists the attempts.
--wait-for NAME delays the start while a process whose command line contains NAME is running (at
most --wait-minutes), so that training does not share the GPU with a timed match.

To stop the run: `pkill -f run_long.py`, then `pkill -f fowppo.train`. The newest weights are in the
last attempt's latest.pt.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
LR_START, LR_END = 3e-4, 3e-5
# The long run: 512 games on 8 worker processes, 64 plies between updates, 2 passes over each
# batch; 70% self-play, the rest against earlier copies of the network and the two hand-made
# players; every game opens with 0 to 8 random plies; evaluation games open with 2 to 8, as the
# team's matches do.
LONG_RUN = ["--envs", "512", "--steps", "64", "--workers", "8", "--epochs", "2",
            "--rivals", "self=0.70,past=0.15,greedy=0.10,random=0.05",
            "--opening", "0", "8", "--eval-opening", "2", "8",
            "--eval-minutes", "20", "--eval-games", "200", "--snapshot-minutes", "30"]
SMOKE = ["--envs", "64", "--steps", "16", "--workers", "2", "--epochs", "2",
         "--rivals", "self=0.70,past=0.15,greedy=0.10,random=0.05", "--pool-updates", "5",
         "--opening", "0", "8", "--eval-opening", "2", "8", "--worker-timeout", "8", "--device", "cpu",
         "--eval-minutes", "0.5", "--eval-games", "20", "--snapshot-minutes", "0.5"]


def newest_weights(name: str):
    """The most recently written latest.pt or snapshot of any attempt, or None."""
    files = [f for pattern in ("latest.pt", "snapshot-*.pt") for f in RUNS.glob(f"{name}-[0-9]*/{pattern}")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def running(needle: str) -> bool:
    """Whether some other process has `needle` in its command line."""
    listing = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True, text=True).stdout
    # A command line that names --wait-for is this launcher or the shell that started it.
    return any(needle in line and "--wait-for" not in line for line in listing.splitlines())


def stop(process: subprocess.Popen) -> None:
    """Stop an attempt and everything it started (it runs in its own process group)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            continue


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--hours", type=float, required=True)
    parser.add_argument("--max-attempts", type=int, default=30)
    parser.add_argument("--stall-minutes", type=float, default=10.0, help="a log this old means the attempt hangs")
    parser.add_argument("--wait-for", default=None, help="do not start while a process with this text in its command runs")
    parser.add_argument("--wait-minutes", type=float, default=45.0, help="the longest --wait-for delays the start")
    parser.add_argument("--smoke", action="store_true", help="tiny settings, to test this launcher")
    args = parser.parse_args()
    if (RUNS / f"{args.name}-plan.json").exists() or list(RUNS.glob(f"{args.name}-[0-9]*")):
        sys.exit(f"a run named {args.name} exists in runs/; choose a new --name")
    RUNS.mkdir(exist_ok=True)
    waited_from = time.time()
    while args.wait_for and running(args.wait_for) and time.time() - waited_from < args.wait_minutes * 60:
        time.sleep(15)
    total = args.hours * 3600
    start = time.time()
    end = start + total
    (RUNS / f"{args.name}-plan.json").write_text(json.dumps({
        "name": args.name, "hours": args.hours, "start_epoch": start, "end_epoch": end,
        "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start)),
        "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end)),
        "waited_minutes": round((start - waited_from) / 60, 1), "settings": SMOKE if args.smoke else LONG_RUN,
        "learning_rate": [LR_START, LR_END]}, indent=2) + "\n")
    settings = SMOKE if args.smoke else LONG_RUN
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    attempt, resume = 0, None
    while attempt < args.max_attempts:
        remaining = end - time.time()
        if remaining < 60:
            break
        attempt += 1
        rate = LR_START + (LR_END - LR_START) * (1 - remaining / total)
        name = f"{args.name}-{attempt}"
        command = ["caffeinate", "-is", sys.executable, "-W", "ignore::DeprecationWarning", "-m", "fowppo.train",
                   "--name", name, "--minutes", f"{remaining / 60:.2f}", "--lr", f"{rate:.6g}", "--lr-end", f"{LR_END:.6g}",
                   "--seed", str(attempt - 1), *settings]
        if resume is not None:
            command += ["--resume", str(resume)]
        started = time.time()
        log = RUNS / name / "log.jsonl"
        stalled = False
        with open(RUNS / f"{name}.out", "w") as output:
            process = subprocess.Popen(command, cwd=HERE, env=environment, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            while process.poll() is None:
                time.sleep(10)
                last_sign = log.stat().st_mtime if log.exists() else started
                if time.time() - last_sign > args.stall_minutes * 60:
                    stalled = True
                    stop(process)
            code = process.returncode
        finished = (RUNS / name / "final.pt").exists()
        with open(RUNS / f"{args.name}-attempts.jsonl", "a") as record:
            record.write(json.dumps({"attempt": attempt, "name": name, "exit_code": code, "finished": finished,
                                     "stalled": stalled,
                                     "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
                                     "minutes": round((time.time() - started) / 60, 2),
                                     "resumed_from": str(resume.relative_to(HERE)) if resume else None,
                                     "learning_rate": rate}) + "\n")
        if code == 0 and finished:
            break
        resume = newest_weights(args.name)
        time.sleep(5)


if __name__ == "__main__":
    main()
