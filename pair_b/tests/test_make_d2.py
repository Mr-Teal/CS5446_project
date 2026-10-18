"""End-to-end run of scripts/make_d2.py on a tiny configuration (D1 spec §6 files)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_d2.py"


def run(out: Path, workers: int):
    cmd = [sys.executable, str(SCRIPT), "--games", "3", "--parents-per-game", "1", "--max-plies", "30",
           "--label-depth", "3", "--seed", "5", "--workers", str(workers), "--out", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    records = [json.loads(line) for f in sorted(out.glob("part-*.jsonl")) for line in f.read_text().splitlines()]
    games = [json.loads(line) for line in (out / "games.jsonl").read_text().splitlines()]
    manifest = json.loads((out / "manifest.json").read_text())
    return records, games, manifest


# Catches: files that disagree with each other, or a manifest that misreports the data.
def test_make_d2_writes_consistent_files(tmp_path):
    records, games, manifest = run(tmp_path / "d2", workers=1)
    assert len(games) == 3
    assert {g["game_id"] for g in games} == {"g-000000", "g-000001", "g-000002"}
    assert records and {r["game_id"] for r in records} <= {g["game_id"] for g in games}
    assert manifest["records"] == len(records)
    assert manifest["stockfish"]["label_depths"] == [1, 3]


# Catches: results that depend on how many worker processes ran (spec rule 5: reproducible files).
def test_make_d2_output_does_not_depend_on_worker_count(tmp_path):
    one, games_one, _ = run(tmp_path / "w1", workers=1)
    two, games_two, _ = run(tmp_path / "w2", workers=2)
    assert sorted(one, key=lambda r: r["id"]) == sorted(two, key=lambda r: r["id"])
    assert sorted(games_one, key=lambda g: g["game_id"]) == sorted(games_two, key=lambda g: g["game_id"])
