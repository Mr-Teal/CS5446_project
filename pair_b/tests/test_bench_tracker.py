"""scripts/bench_tracker.py: tracker update times, printed and, with --out, written as JSON."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bench(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "bench_tracker.py"), *map(str, args)],
                          capture_output=True, text=True)


# Catches: the README's tracker timings with no file behind them, or a file whose counts do not add
# up to the updates it timed.
def test_out_writes_the_timings_it_prints(tmp_path):
    out = tmp_path / "bench.json"
    result = bench("--games", "2", "--plies", "6", "--particles", "16", "--out", out)
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text())
    assert report["settings"] == {"games": 2, "plies": 6, "particles": 16, "guesses": 8, "seed": 0, "rules": "pairb-standin"}
    every, unseen = report["every_update"], report["after_unseen_move"]
    assert every["updates"] == sum(g["updates"] for g in report["games"]) and 0 < unseen["updates"] < every["updates"]
    assert 0 <= every["median_ms"] <= every["p95_ms"] <= every["max_ms"]
    assert report["rebuilds"] == sum(g["rebuilds"] for g in report["games"])
    assert f"median {every['median_ms']:.0f} ms" in result.stdout


# Catches: a finished benchmark overwritten.
def test_out_refuses_an_existing_file(tmp_path):
    out = tmp_path / "bench.json"
    out.write_text("{}")
    result = bench("--games", "1", "--plies", "2", "--particles", "4", "--out", out)
    assert result.returncode != 0 and out.read_text() == "{}"
