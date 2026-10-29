"""Review issue 4: saved provenance schema for CPU and GPU players."""

import configparser
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pair_c import provenance, run_evaluation
from pair_c.regression_tests.test_reset_game import LegalMoveAgent


class ProvenanceFactory:
    """Lightweight player exposing device and nested engine metadata."""

    def __init__(self, settings):
        self.settings = settings

    def load_model(self):
        agent = LegalMoveAgent(self.settings["name"])
        agent.scorer = SimpleNamespace(
            device=self.settings["device"],
            provenance_checkpoint_path=self.settings["checkpoint_path"],
            stockfish=SimpleNamespace(
                engine=SimpleNamespace(id={"name": "Test Stockfish", "author": "Test author"}),
                provenance_executable_path=self.settings["stockfish_path"],
            ),
        )
        return agent

    def reset_game(self):
        pass


@pytest.mark.parametrize("gpu_device", ["cuda:0", "mps"])
def test_saved_provenance_fields(tmp_path, monkeypatch, gpu_device):
    """Check saved values using explicit loader metadata and simulated hardware."""
    fake_torch = SimpleNamespace(
        __version__="test-torch",
        version=SimpleNamespace(cuda="test-cuda" if gpu_device.startswith("cuda") else None),
        device=lambda value: SimpleNamespace(
            index=int(value.split(":")[1]) if ":" in value else None,
        ),
        cuda=SimpleNamespace(current_device=lambda: 0, get_device_name=lambda index: "Test GPU"),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(run_evaluation, "cpu_model", lambda: "Test CPU")
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-git-config"))
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True)
    text_file = repo / "source.py"
    binary_file = repo / "weights.pt"
    unknown_file = repo / "unknown.dat"
    text_file.write_bytes(b"first\r\nsecond\r\n")
    binary_file.write_bytes(b"binary\r\nbytes\x00")
    unknown_file.write_bytes(b"unknown\r\nbytes")
    subprocess.run(["git", "-C", str(repo), "add", "source.py", "weights.pt", "unknown.dat"],
                   check=True, capture_output=True)
    monkeypatch.setattr(run_evaluation, "ROOT", repo)
    monkeypatch.setattr(run_evaluation, "git_provenance", lambda root: {
        "git_commit": "test-commit", "git_status": ["?? agent.py"],
        "git_detection_notes": {"git_commit": None, "git_status": None},
    })
    monkeypatch.setattr(provenance.platform, "system", lambda: "Darwin" if gpu_device == "mps" else "Linux")
    monkeypatch.setattr(provenance, "_command", lambda *args: json.dumps({
        "SPDisplaysDataType": [{"sppci_model": "Test Apple GPU"}],
    }))

    parser = configparser.ConfigParser()
    parser.read_string("""
[player_a]
name = A
leaf_depth = 0
tracker_factory = pair_c.tracker_factories:Factory
[player_b]
name = B
leaf_depth = 0
tracker_factory = pair_c.tracker_factories:Factory
[match]
games = 1
alternating_colors = true
rules = standin
time_budget_ms = 1000
max_plies = 2
initial_fen =
seed = 17
seed_mode = fixed
[output]
directory = unused
""")
    rules_path = tmp_path / "rules.json"
    rules_bytes = json.dumps({
        "version": "crlf-to-lf-v1", "text_extensions": [".py"],
        "text_filenames": [], "binary_extensions": [".pt"], "default": "binary",
    }).encode("utf-8")
    rules_path.write_bytes(rules_bytes)
    parser.set("output", "hash_rules", str(rules_path))
    engine = tmp_path / "test-engine"
    engine.write_bytes(b"engine\r\nfixture; never executed")
    for side, device in (("a", "cpu"), ("b", gpu_device)):
        checkpoint = tmp_path / f"{side}.pt"
        checkpoint.write_bytes(b"checkpoint\r\nfixture; never loaded")
        section = f"player_{side}"
        parser.set(section, "factory", f"{__name__}:ProvenanceFactory")
        parser.set(section, "device", device)
        parser.set(section, "checkpoint_path", str(checkpoint))
        parser.set(section, "stockfish_path", str(engine))
        parser.set(section, "tracker_particles", "8")
        parser.set(section, "tracker_hypotheses", "2")
        parser.set(section, "tracker_rebuild_tries", "10")
    parser.set("match", "games", "1")
    parser.set("match", "max_plies", "2")
    parser.set("match", "rules", "standin")
    parser.set("match", "initial_fen", "")
    output = tmp_path / "results"
    parser.set("output", "directory", str(output))
    source = tmp_path / "config.ini"
    with source.open("w", encoding="utf-8", newline="\r\n") as stream:
        parser.write(stream)

    config = run_evaluation.load_config(source)
    rules_path.write_bytes(b"changed after loading")
    run_evaluation.run(config, source)
    report = json.loads((output / "provenance.json").read_text(encoding="utf-8"))

    assert set(report) == {
        "started_at", "python_version", "torch_version", "cuda_version", "cpu_model",
        "player_devices", "config_path", "checkpoint_paths", "stockfish", "sha256",
        "checkpoint_detection_notes", "git_commit", "git_status", "git_detection_notes", "hash_rules_path", "source_discovery",
    }
    for field in ("player_devices", "checkpoint_paths", "stockfish"):
        assert set(report[field]) == {"a", "b"}
    for side in ("a", "b"):
        assert set(report["player_devices"][side]) == {
            "device", "backend", "gpu_model", "detection_note",
        }
        assert set(report["stockfish"][side]) == {"path", "name", "author"}
    assert set(report["sha256"]) == {
        "config", "config_raw", "player_a_checkpoint", "player_b_checkpoint",
        "player_a_stockfish", "player_b_stockfish", "source_files",
    }
    assert (output / "evaluate_config.ini").read_bytes() == source.read_bytes()
    assert report["sha256"]["config"] == hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert report["sha256"]["config"] == provenance.sha256_text_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
    assert report["sha256"]["config_raw"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["hash_rules_path"] == str(rules_path.resolve())
    assert (output / "hash_rules.json").read_bytes() == rules_bytes
    assert report["cpu_model"] == "Test CPU"
    assert report["torch_version"] == "test-torch"
    assert report["cuda_version"] == fake_torch.version.cuda
    assert report["checkpoint_detection_notes"] == {"a": None, "b": None}
    assert report["git_commit"] == "test-commit"
    assert report["git_status"] == ["?? agent.py"]
    assert report["source_discovery"] == "git"
    assert report["git_detection_notes"] == {"git_commit": None, "git_status": None}
    for side in ("a", "b"):
        checkpoint = tmp_path / f"{side}.pt"
        assert report["checkpoint_paths"][side] == str(checkpoint.resolve())
        assert report["sha256"][f"player_{side}_checkpoint"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        assert report["stockfish"][side] == {
            "path": str(engine.resolve()), "name": "Test Stockfish", "author": "Test author",
        }
        assert report["sha256"][f"player_{side}_stockfish"] == hashlib.sha256(engine.read_bytes()).hexdigest()
    assert report["player_devices"]["a"] == {
        "device": "cpu", "backend": "cpu", "gpu_model": None, "detection_note": None,
    }
    assert report["player_devices"]["b"] == {
        "device": gpu_device, "backend": gpu_device.split(":")[0],
        "gpu_model": "Test GPU" if gpu_device.startswith("cuda") else "Test Apple GPU",
        "detection_note": None,
    }
    assert report["sha256"]["source_files"] == {
        "source.py": hashlib.sha256(b"first\nsecond\n").hexdigest(),
        "weights.pt": hashlib.sha256(binary_file.read_bytes()).hexdigest(),
        "unknown.dat": hashlib.sha256(unknown_file.read_bytes()).hexdigest(),
    }
    rules = json.loads(rules_bytes)
    original_hash = provenance.sha256_tracked_file(text_file, rules)
    text_file.write_bytes(b"first\nsecond\n")
    assert provenance.sha256_tracked_file(text_file, rules) == original_hash
    text_file.write_bytes(b"first\nchanged\n")
    assert provenance.sha256_tracked_file(text_file, rules) != original_hash
    text_file.write_bytes(b"x" * (1024 * 1024 - 1) + b"\r\nend\r")
    assert provenance.sha256_tracked_file(text_file, rules) == hashlib.sha256(
        b"x" * (1024 * 1024 - 1) + b"\nend\r"
    ).hexdigest()
