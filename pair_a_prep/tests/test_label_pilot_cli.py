"""Exercise the real pilot CLI in source archives and failed setup paths."""

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from pair_a_prep.label_pilot import git_metadata


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def archive(tmp_path):
    folder = tmp_path / "source-archive"
    ignore = shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", "local_runs",
                                   "tests", "docs", "results", "board_viewer_assets")
    for package in ("pair_a_prep", "fow_shared"):
        shutil.copytree(ROOT / package, folder / package, ignore=ignore)
    shutil.copytree(ROOT / "pair_b/src/pairb", folder / "pair_b/src/pairb", ignore=ignore)
    assert not (folder / ".git").exists()
    return folder


def run_archive(archive, output, *extra, hide_git=False):
    environment = dict(os.environ, PYTHONPATH=str(archive / "pair_b/src"),
                       PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if hide_git:
        environment["PATH"] = ""
    return subprocess.run(
        [sys.executable, "-m", "pair_a_prep.label_pilot", "--out", str(output),
         "--games", "1", "--max-plies", "1", "--rounds", "1", *extra],
        cwd=archive, env=environment, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )


@pytest.mark.parametrize("hide_git", [False, True], ids=["no-git-directory", "no-git-command"])
def test_archive_cli_exports_labels_without_inventing_git_provenance(archive, tmp_path, hide_git):
    output = tmp_path / "archive-cli-probe"
    result = run_archive(archive, output, hide_git=hide_git)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed" and report["records"] == 1
    assert report["commit"] is None and report["git_status"] is None
    assert report["git_metadata_available"] is False and report["git_errors"]
    for relative, digest in report["source_sha256"].items():
        assert digest == sha256((archive / relative).read_bytes()).hexdigest()
    assert report["source_sha256"]["pair_a_prep/label_pilot.py"]
    assert report["validation"] == {"errors": [], "warnings": []}
    assert (output / "part-000.jsonl").is_file()


@pytest.mark.parametrize("extra,exception", [
    (("--rounds", "0"), "ValueError"),
    (("--include-d1", "--stockfish", "missing-pilot-engine-executable"), "FileNotFoundError"),
])
def test_setup_failure_keeps_source_hashes_and_writes_report(archive, tmp_path, extra, exception):
    output = tmp_path / "failed-pilot"
    result = run_archive(archive, output, *extra)
    assert result.returncode != 0
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and exception in report["error"]
    assert report["source_sha256"] and report["commit"] is None
    assert not (output / "part-000.jsonl").exists()
    saved_report = (output / "report.json").read_bytes()
    retry = run_archive(archive, output)
    assert retry.returncode != 0 and "output already exists" in retry.stderr
    assert (output / "report.json").read_bytes() == saved_report


def test_partial_git_failure_does_not_report_an_unknown_status_as_clean(monkeypatch, tmp_path):
    def read(command, **kwargs):
        if "--show-toplevel" in command:
            return str(tmp_path) + "\n"
        if "HEAD" in command:
            return "a" * 40 + "\n"
        raise subprocess.CalledProcessError(128, command, stderr="status unavailable")

    monkeypatch.setattr(subprocess, "check_output", read)
    metadata = git_metadata(tmp_path)
    assert metadata["commit"] == "a" * 40
    assert metadata["git_status"] is None and not metadata["git_metadata_available"]
    assert metadata["git_errors"] == {"git_status": "status unavailable"}


def test_archive_inside_another_repository_does_not_inherit_its_commit(monkeypatch, tmp_path):
    def read(command, **kwargs):
        assert "--show-toplevel" in command
        return str(tmp_path.parent)

    monkeypatch.setattr(subprocess, "check_output", read)
    metadata = git_metadata(tmp_path)
    assert metadata["commit"] is None and metadata["git_status"] is None
    assert not metadata["git_metadata_available"] and "repository" in metadata["git_errors"]
