"""Review issue 4: saved provenance schema for CPU and GPU players."""

import configparser
import json
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
    """Check keys only; simulate hardware while retaining real output writing."""
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
    # The schema must not depend on the checkout's tracked paths or file contents.
    monkeypatch.setattr(run_evaluation, "source_file_hashes", lambda root: {})
    monkeypatch.setattr(provenance.platform, "system", lambda: "Darwin" if gpu_device == "mps" else "Linux")
    monkeypatch.setattr(provenance, "_command", lambda *args: json.dumps({
        "SPDisplaysDataType": [{"sppci_model": "Test Apple GPU"}],
    }))

    parser = configparser.ConfigParser()
    parser.read(Path(run_evaluation.__file__).with_name("evaluate_config.ini"), encoding="utf-8")
    engine = tmp_path / "test-engine"
    engine.write_bytes(b"engine fixture; never executed")
    for side, device in (("a", "cpu"), ("b", gpu_device)):
        checkpoint = tmp_path / f"{side}.pt"
        checkpoint.write_bytes(b"checkpoint fixture; never loaded")
        section = f"player_{side}"
        parser.set(section, "factory", f"{__name__}:ProvenanceFactory")
        parser.set(section, "device", device)
        parser.set(section, "checkpoint_path", str(checkpoint))
        parser.set(section, "stockfish_path", str(engine))
        parser.set(section, "tracker_particles", "8")
        parser.set(section, "tracker_hypotheses", "2")
    parser.set("match", "games", "1")
    parser.set("match", "max_plies", "2")
    parser.set("match", "rules", "standin")
    parser.set("match", "initial_fen", "")
    output = tmp_path / "results"
    parser.set("output", "directory", str(output))
    source = tmp_path / "config.ini"
    with source.open("w", encoding="utf-8") as stream:
        parser.write(stream)

    run_evaluation.run(run_evaluation.load_config(source), source)
    report = json.loads((output / "provenance.json").read_text(encoding="utf-8"))

    assert set(report) == {
        "started_at", "python_version", "torch_version", "cuda_version", "cpu_model",
        "player_devices", "config_path", "checkpoint_paths", "stockfish", "sha256",
    }
    for field in ("player_devices", "checkpoint_paths", "stockfish"):
        assert set(report[field]) == {"a", "b"}
    for side in ("a", "b"):
        assert set(report["player_devices"][side]) == {
            "device", "backend", "gpu_model", "detection_note",
        }
        assert set(report["stockfish"][side]) == {"path", "name", "author"}
    assert set(report["sha256"]) == {
        "config", "player_a_checkpoint", "player_b_checkpoint",
        "player_a_stockfish", "player_b_stockfish", "source_files",
    }
    # Intentionally do not inspect values or the dynamic source_files mapping.
