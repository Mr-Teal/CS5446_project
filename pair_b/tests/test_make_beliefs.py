"""End-to-end run of scripts/make_beliefs.py: practice beliefs labelled by Stockfish (D6)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fow_shared.recording import read_records

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_beliefs.py"
PARENTS = [  # (game_id, ply of the parent, parent FEN), as D2 records carry them
    ("g-000001", 9, "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 2 9"),
    ("g-000001", 12, "r2qkb1r/ppp2ppp/2n1bn2/3pp3/4P3/2NP1N2/PPP1BPPP/R1BQK2R b KQkq - 3 6"),
    ("g-000002", 10, "rnbqkb1r/pp2pppp/5n2/2pp4/3P4/4PN2/PPP2PPP/RNBQKB1R w KQkq - 0 4"),
]


def source(tmp_path: Path) -> Path:
    folder = tmp_path / "d2-mini"
    folder.mkdir()
    rows = [{"game_id": g, "ply": ply + 1, "parent_fen": fen, "move": "a2a3"} for g, ply, fen in PARENTS]
    (folder / "part-00.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (folder / "manifest.json").write_text(json.dumps({"dataset": "d2-mini", "created": "2026-10-18T00:00:00+08:00"}))
    return folder


def run(src: Path, out: Path, workers: int):
    cmd = [sys.executable, str(SCRIPT), "--source", str(src), "--parents", "3", "--hypotheses", "3",
           "--label-depth", "3", "--seed", "5", "--workers", str(workers), "--out", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    records = [r for f in sorted(out.glob("part-*.jsonl")) for r in read_records(f)]
    return records, json.loads((out / "manifest.json").read_text())


# Catches: records Teal's reader rejects, labels that do not match their boards, or a manifest that
# misreports the data.
def test_make_beliefs_writes_valid_labelled_records(tmp_path):
    records, manifest = run(source(tmp_path), tmp_path / "d6", workers=1)
    assert len(records) == manifest["records"] == 3
    assert {r.game_id for r in records} == {"g-000001", "g-000002"}
    for r in records:
        n = len(r.agent_input.belief.hypotheses)
        assert 1 < n <= 3 and len(r.hypothesis_values) == n
        weights = [h.weight for h in r.agent_input.belief.hypotheses]
        assert r.root_value == pytest.approx(sum(w * v for w, v in zip(weights, r.hypothesis_values)))
        assert sorted(r.decision.diagnostics) == [f"d1:{i}" for i in range(n)]
    assert manifest["stockfish"]["label_depth"] == 3 and manifest["source"]["dataset"] == "d2-mini"


# Catches: data that depends on how many worker processes ran.
def test_make_beliefs_output_does_not_depend_on_worker_count(tmp_path):
    src = source(tmp_path)
    one, _ = run(src, tmp_path / "w1", workers=1)
    two, _ = run(src, tmp_path / "w2", workers=2)
    key = lambda r: (r.game_id, r.agent_input.observation.ply)
    assert sorted(one, key=key) == sorted(two, key=key)
