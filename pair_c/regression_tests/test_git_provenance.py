"""Review issue 6: Git provenance in an isolated temporary repository."""

import hashlib
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from pair_c import provenance
from pair_c import run_evaluation


RULES = {"text_extensions": [".py"], "text_filenames": [], "binary_extensions": [".bin"]}


@pytest.mark.parametrize("same_directory", [True, False])
def test_git_root_uses_filesystem_identity(tmp_path, monkeypatch, same_directory):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.py").write_text("example\n", encoding="utf-8")
    git_root = tmp_path / "PROJECT"
    comparisons = []

    def samefile(path, other):
        comparisons.append((path, other))
        return same_directory

    def git(command, **kwargs):
        if command[1:3] == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, os.fsencode(git_root) + b"\n", b"")
        assert command[1] == "ls-files"
        return subprocess.CompletedProcess(command, 0, b"source.py\0", b"")

    monkeypatch.setattr(Path, "samefile", samefile)
    monkeypatch.setattr(provenance.subprocess, "run", git)
    mode, paths, reason = provenance.discover_sources(root)
    assert comparisons == [(git_root, root)]
    assert paths == ["source.py"]
    if same_directory:
        assert mode == "git"
        assert reason is None
    else:
        assert mode == "filesystem"
        assert reason == "Project root is not the Git repository root"


def test_git_provenance_in_temporary_repository(tmp_path, monkeypatch):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True,
            encoding="utf-8",
        ).stdout.strip()

    git("init", "--quiet")
    empty = provenance.git_provenance(tmp_path)
    assert empty["git_commit"] is None
    assert empty["git_status"] == []
    assert empty["git_detection_notes"]["git_commit"]
    assert empty["git_detection_notes"]["git_status"] is None

    tracked = tmp_path / "agent.py"
    tracked.write_text("original\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    git("add", "agent.py", ".gitignore")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "--quiet", "-m", "initial")
    head = git("rev-parse", "HEAD")
    clean = provenance.git_provenance(tmp_path)
    assert clean == {
        "git_commit": head, "git_status": [],
        "git_detection_notes": {"git_commit": None, "git_status": None},
    }

    tracked.write_text("modified\n", encoding="utf-8")
    assert provenance.git_provenance(tmp_path)["git_status"] == [" M agent.py"]
    git("add", "agent.py")
    (tmp_path / "extra folder").mkdir()
    (tmp_path / "extra folder" / "extra.py").write_text("untracked\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("ignored\n", encoding="utf-8")
    dirty = provenance.git_provenance(tmp_path)
    assert dirty["git_commit"] == head
    # Porcelain quotes paths containing spaces even with core.quotePath=false.
    assert dirty["git_status"] == ["M  agent.py", '?? "extra folder/extra.py"']
    assert dirty["git_detection_notes"] == {"git_commit": None, "git_status": None}


def test_git_provenance_reports_unavailable_git(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(provenance.subprocess, "run", unavailable)
    result = provenance.git_provenance(tmp_path)
    assert result["git_commit"] is None
    assert result["git_status"] is None
    assert "git unavailable" in result["git_detection_notes"]["git_commit"]
    assert "git unavailable" in result["git_detection_notes"]["git_status"]


@pytest.mark.parametrize("missing_git", [True, False])
def test_filesystem_fallback_and_read_errors(tmp_path, monkeypatch, missing_git):
    root = tmp_path / "project"
    root.mkdir()
    (root / "cache").mkdir()
    (root / "cache" / "source.py").write_bytes(b"first\r\nsecond\r\n")
    (root / "data.bin").write_bytes(b"binary\r\n\x00")
    (root / "denied.py").write_bytes(b"unreadable")
    (root / "z_after.py").write_bytes(b"after\n")
    if missing_git:
        def missing(*args, **kwargs):
            raise FileNotFoundError("git unavailable")
        monkeypatch.setattr(provenance.subprocess, "run", missing)
    else:
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))

    real_hash = provenance.sha256_tracked_file
    def hash_file(path, rules):
        if path.name == "denied.py":
            raise PermissionError("simulated permission error")
        return real_hash(path, rules)
    monkeypatch.setattr(provenance, "sha256_tracked_file", hash_file)
    monkeypatch.setattr(run_evaluation, "ROOT", root)
    monkeypatch.setattr(run_evaluation, "cpu_model", lambda: "test CPU")
    source = tmp_path / "config.ini"
    source.write_bytes(b"config\r\n")
    config = {"hash_rules": RULES, "hash_rules_path": tmp_path / "rules.json"}
    players = {side: SimpleNamespace(provenance_checkpoint_path=None) for side in ("a", "b")}
    report = run_evaluation.collect_provenance(config, source, "start", players)
    assert report["source_discovery"] == "filesystem"
    assert report["git_commit"] is None and report["git_status"] is None
    assert all(report["git_detection_notes"].values())
    assert report["sha256"]["source_files"] == {
        "cache/source.py": hashlib.sha256(b"first\nsecond\n").hexdigest(),
        "data.bin": hashlib.sha256(b"binary\r\n\x00").hexdigest(),
        "denied.py": {"error": "simulated permission error"},
        "z_after.py": hashlib.sha256(b"after\n").hexdigest(),
    }


def test_git_discovery_failure_does_not_fall_back(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, b"", b"fatal: permission denied")
    monkeypatch.setattr(provenance.subprocess, "run", failed)
    with pytest.raises(RuntimeError, match="permission denied"):
        provenance.discover_sources(tmp_path)


def test_git_index_failure_does_not_fall_back(tmp_path, monkeypatch):
    calls = 0
    def failed_index(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 0, str(tmp_path).encode() + b"\n", b"")
        raise subprocess.CalledProcessError(128, command, stderr=b"index unreadable")
    monkeypatch.setattr(provenance.subprocess, "run", failed_index)
    with pytest.raises(RuntimeError, match="index unreadable"):
        provenance.discover_sources(tmp_path)
