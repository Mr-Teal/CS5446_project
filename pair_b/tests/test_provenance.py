"""Provenance: which data files, checkpoint and code a result came from, by SHA-256 (review T9)."""
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pairb import provenance

ROOT = Path(__file__).resolve().parents[1]


def dataset(folder: Path, manifest=None) -> Path:
    folder.mkdir()
    (folder / "part-00.jsonl").write_text('{"a": 1}\n')
    (folder / "part-01.jsonl").write_text('{"a": 2}\n')
    (folder / "games.jsonl").write_text("not a data part\n")
    if manifest is not None:
        (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


# Catches: a data part or the manifest left out of the hashes, a file that is not data hashed,
# or the combined hash depending on the order the files were listed in.
def test_data_files_hashes_each_part_and_the_manifest(tmp_path):
    got = provenance.data_files(dataset(tmp_path / "d", {"seed": 7}))
    assert got["dataset"] == "d"
    assert sorted(got["files_sha256"]) == ["manifest.json", "part-00.jsonl", "part-01.jsonl"]
    assert got["files_sha256"]["part-00.jsonl"] == hashlib.sha256(b'{"a": 1}\n').hexdigest()
    assert got["sha256"] == hashlib.sha256(json.dumps(got["files_sha256"], sort_keys=True).encode()).hexdigest()


# Catches: the frozen evaluation rows (a gzipped part) hashed as a folder without records, or the
# belief scripts' plain pattern hashing parts they do not read.
def test_data_files_hashes_gzipped_parts_unless_a_pattern_says_otherwise(tmp_path):
    folder = dataset(tmp_path / "d", {"seed": 7})
    (folder / "part-02.jsonl.gz").write_bytes(gzip.compress(b'{"a": 3}\n'))
    got = provenance.data_files(folder)
    assert sorted(got["files_sha256"]) == ["manifest.json", "part-00.jsonl", "part-01.jsonl", "part-02.jsonl.gz"]
    plain = provenance.data_files(folder, "part-*.jsonl")
    assert "part-02.jsonl.gz" not in plain["files_sha256"] and "pattern" not in plain


# Catches: a run that read some of the parts (the belief scripts' --pattern) recorded as if it
# had read them all.
def test_data_files_hashes_only_the_parts_a_pattern_picks(tmp_path):
    got = provenance.data_files(dataset(tmp_path / "d", {"seed": 7}), "part-01.jsonl")
    assert sorted(got["files_sha256"]) == ["manifest.json", "part-01.jsonl"]
    assert got["pattern"] == "part-01.jsonl"
    assert "pattern" not in provenance.data_files(tmp_path / "d")


# Catches: manifest fields copied beyond the ones that say how the data were made, or a folder
# without a manifest raising.
def test_data_source_adds_how_the_data_were_made(tmp_path):
    folder = dataset(tmp_path / "d", {"code_sha256": "abc", "seed": 7, "created": "2026-10-16", "command": ["x"],
                                      "stockfish": {"name": "Stockfish 19"}, "records": 10, "machine": "m"})
    got = provenance.data_source(folder)
    assert got["manifest"] == {"code_sha256": "abc", "seed": 7, "created": "2026-10-16", "command": ["x"],
                               "stockfish": {"name": "Stockfish 19"}}
    assert {k: got[k] for k in ("dataset", "files_sha256", "sha256")} == provenance.data_files(folder)
    assert provenance.data_source(dataset(tmp_path / "bare"))["manifest"] == {}


# Catches: a committed report carrying the local user name, through a manifest command that
# names folders by absolute path (the d6 manifests do).
def test_data_source_writes_the_home_folder_as_a_tilde(tmp_path):
    home = str(Path.home())
    folder = dataset(tmp_path / "d", {"command": ["make_beliefs.py", "--source", f"{home}/data/d2-v2"],
                                      "created": f"made in {home}"})
    got = provenance.data_source(folder)["manifest"]
    assert got == {"command": ["make_beliefs.py", "--source", "~/data/d2-v2"], "created": "made in ~"}


# Catches: the commit not being this checkout's HEAD, or a machine without git crashing a run.
def test_git_commit_is_head_or_none_without_git(monkeypatch):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    assert provenance.git_commit() == (head.stdout.strip() if head.returncode == 0 else None)

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(provenance.subprocess, "run", no_git)
    assert provenance.git_commit() is None


# Catches: uncommitted changes left out of a run's record, Python's own caches listed as changes
# (no clean checkout would ever record []), or a machine without git crashing it.
def test_git_status_lists_the_uncommitted_changes_or_none_without_git(monkeypatch):
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    want = [line for line in status.stdout.splitlines() if "__pycache__" not in line and ".egg-info/" not in line]
    assert provenance.git_status() == (want if status.returncode == 0 else None)

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(provenance.subprocess, "run", no_git)
    assert provenance.git_status() is None


def write_run(folder: Path, dataset_name: str) -> Path:
    folder.mkdir()
    (folder / "best.pt").write_bytes(b"checkpoint bytes")
    (folder / "summary.json").write_text(json.dumps({
        "dataset": dataset_name, "device": "mps", "best_epoch": 1, "epochs_run": 6, "created": "2026-10-16T20:47:23+08:00",
        "args": {"data": "data/d2-v2", "seed": 0}, "params": 521425}))
    return folder


def write_provenance(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "write_provenance.py"), *map(str, args)],
                          capture_output=True, text=True)


# Catches: a sidecar that names the wrong checkpoint or data bytes, drops the training summary's
# device, epochs or arguments, or does not say it was written after training.
def test_write_provenance_records_the_data_and_checkpoint_a_run_was_trained_on(tmp_path):
    data = dataset(tmp_path / "d2-v2", {"code_sha256": "abc", "seed": 2026, "created": "2026-10-16T20:43:53+08:00",
                                        "command": ["make_d2.py"], "records": 3})
    run = write_run(tmp_path / "run", "d2-v2")
    result = write_provenance("--run", run, "--data", data)
    assert result.returncode == 0, result.stderr
    got = json.loads((run / "provenance.json").read_text())
    assert got["source"] == {**provenance.data_source(data), "files_last_modified": got["source"]["files_last_modified"]}
    assert got["checkpoint_sha256"] == hashlib.sha256(b"checkpoint bytes").hexdigest()
    assert got["training"] == {"device": "mps", "best_epoch": 1, "epochs_run": 6, "created": "2026-10-16T20:47:23+08:00",
                               "args": {"data": "data/d2-v2", "seed": 0}}
    assert "after training" in got["note"]


# Catches: a sidecar silently replaced, or written for a data folder the run was not trained on.
def test_write_provenance_refuses_to_overwrite_or_to_pair_a_run_with_other_data(tmp_path):
    data = dataset(tmp_path / "d2-v2", {"seed": 2026})
    run = write_run(tmp_path / "run", "d2-v2")
    assert write_provenance("--run", run, "--data", data).returncode == 0
    again = write_provenance("--run", run, "--data", data)
    assert again.returncode != 0 and "exists" in again.stderr
    other = write_run(tmp_path / "other", "d6-v1")
    wrong = write_provenance("--run", other, "--data", data)
    assert wrong.returncode != 0 and "d6-v1" in wrong.stderr
    assert not (other / "provenance.json").exists()


@pytest.mark.parametrize("missing", ["best.pt", "summary.json"])
# Catches: a sidecar written for a folder that holds no trained run.
def test_write_provenance_needs_a_checkpoint_and_its_summary(tmp_path, missing):
    data = dataset(tmp_path / "d2-v2", {"seed": 2026})
    run = write_run(tmp_path / "run", "d2-v2")
    (run / missing).unlink()
    result = write_provenance("--run", run, "--data", data)
    assert result.returncode != 0 and missing in result.stderr
