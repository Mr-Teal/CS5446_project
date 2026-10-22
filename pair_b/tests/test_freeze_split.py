"""scripts/freeze_split.py: one split of a D2 dataset as a single gzip part that reads back the same."""
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pairb.data import read_records, split_of
from pairb.provenance import data_source

ROOT = Path(__file__).resolve().parents[1]
FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"


def line(game_id, n, rule=None):
    # Spacing unlike json.dumps' default, so a copy that re-serialises the records shows up.
    return json.dumps({"id": f"{game_id}-{n}", "game_id": game_id, "fen": FEN, "rule": rule, "parent_fen": "p",
                       "d1": {"cp": 10, "mate": None, "v": 0.01}, "d11": {"cp": 20, "mate": None, "v": 0.03}},
                      separators=(",", ":"))


def source(folder: Path) -> list[str]:
    """Two parts; train games g-000000 and g-000001, validation g-000002, test g-000013."""
    assert [split_of(g) for g in ("g-000000", "g-000001", "g-000002", "g-000013")] == ["train", "train", "val", "test"]
    folder.mkdir()
    first = [line("g-000000", 0), line("g-000002", 1), line("g-000000", 2, rule="checkmate")]
    second = [line("g-000013", 3), line("g-000001", 4)]
    (folder / "part-00.jsonl").write_text("\n".join(first) + "\n")
    (folder / "part-01.jsonl").write_text("\n".join(second) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"dataset": folder.name, "created": "2026-10-16", "records": 5,
                                                      "seed": 7, "code_sha256": "abc"}))
    return [first[0], first[2], second[1]]  # the train lines, in order


def freeze(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "freeze_split.py"), *map(str, args)],
                          capture_output=True, text=True)


# Catches: a frozen split that drops rule-decided rows, mixes in other splits, reorders the rows,
# rewrites their bytes, or lacks the manifest that ties it to its source.
def test_freezes_the_split_s_lines_in_order_with_a_manifest(tmp_path):
    train_lines = source(tmp_path / "d2-check")
    result = freeze("--data", tmp_path / "d2-check", "--split", "train", "--out", tmp_path / "frozen")
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (tmp_path / "frozen").iterdir()) == ["manifest.json", "part-00.jsonl.gz"]
    text = gzip.decompress((tmp_path / "frozen" / "part-00.jsonl.gz").read_bytes()).decode()
    assert text == "".join(f"{x}\n" for x in train_lines)
    assert read_records(tmp_path / "frozen") == [json.loads(x) for x in train_lines]
    manifest = json.loads((tmp_path / "frozen" / "manifest.json").read_text())
    assert (manifest["dataset"], manifest["records"], manifest["split"]) == ("frozen", 3, "train")
    assert "sha1" in manifest["split_rule"] and manifest["created"]
    assert manifest["source"] == data_source(tmp_path / "d2-check")


# Catches: gzip bytes that change with the time they were written, so the committed file could
# not be checked by making it again.
def test_freezing_twice_gives_the_same_bytes_and_never_overwrites(tmp_path):
    source(tmp_path / "d2-check")
    for out in ("a", "b"):
        assert freeze("--data", tmp_path / "d2-check", "--split", "train", "--out", tmp_path / out).returncode == 0
    digest = [hashlib.sha256((tmp_path / out / "part-00.jsonl.gz").read_bytes()).hexdigest() for out in ("a", "b")]
    assert digest[0] == digest[1]
    again = freeze("--data", tmp_path / "d2-check", "--split", "train", "--out", tmp_path / "a")
    assert again.returncode != 0 and "exists" in again.stderr
