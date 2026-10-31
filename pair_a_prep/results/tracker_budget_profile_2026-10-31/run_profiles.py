"""Sequential fixed-input trials; no concurrent workers during timing."""
import json
import argparse
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=here)
parser.add_argument("--input", type=Path, default=here / "private-stream.jsonl")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
cases = [("unbounded", None, None, 1), ("original", 250, 64, 17),
         ("25ms", 25, 64, 10000), ("100ms", 100, 64, 10000),
         ("250ms", 250, 64, 10000), ("1000ms", 1000, 64, 10000),
         ("5000ms", 5000, 64, 10000)]
for trial in range(3):
    for name, size, memory, calls in cases:
        output = args.output / f"{name}-{trial}.json"
        if output.exists(): continue
        command = [sys.executable, str(here / "profile_update.py"), "--input", str(args.input),
                   "--output", str(output), "--max-calls", str(calls)]
        if size is not None: command += ["--slice-ms", str(size)]
        if memory is not None: command += ["--memory-mb", str(memory)]
        process = subprocess.run(command, text=True, capture_output=True, timeout=30)
        if process.returncode:
            print(process.stdout + process.stderr, flush=True)
            raise SystemExit(process.returncode)
        row = json.loads(output.read_text())
        print(json.dumps(dict(case=name, trial=trial, status=row["status"], wall_ms=row["wall_ms"],
                             phases=row["phases"], calls=len(row["calls"]),
                             histories=row["final_owned"]["history_count"])), flush=True)
