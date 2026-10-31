"""Uninstrumented controls, run sequentially after the profiled trials."""
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
for trial in range(3):
    for name, extra in [("raw-unbounded", []), ("raw-15s-512mb", [
        "--slice-ms", "15000", "--total-ms", "15000", "--memory-mb", "512"])]:
        output = args.output / f"{name}-{trial}.json"
        if output.exists(): continue
        command = [sys.executable, str(here / "profile_update.py"), "--input", str(args.input), "--no-instrument",
                   "--output", str(output), *extra]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if completed.returncode: raise RuntimeError(completed.stdout + completed.stderr)
        row = json.loads(output.read_text())
        print(json.dumps(dict(case=name, trial=trial, status=row["status"], wall_ms=row["wall_ms"],
                             signature=row["signature"], owned=row["final_owned"])), flush=True)
