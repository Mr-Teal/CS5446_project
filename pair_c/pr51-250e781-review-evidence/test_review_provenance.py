import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import chess.engine
import pytest
import torch

from pair_c import agent_factories, provenance, run_evaluation
from pairb.stockfish import StockfishEvaluator

ROOT = Path(os.environ["PR51_ROOT"])
ENGINE = Path(os.environ["PR51_ENGINE"])
PAWN = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_file(tmp_path, kind="custom-material"):
    parser = configparser.ConfigParser()
    parser.read(ROOT / "pair_c" / "evaluate_config.ini", encoding="utf-8")
    for side in ("a", "b"):
        section = "player_" + side
        parser.set(section, "device", "cpu")
        parser.set(section, "stockfish_path", str(ENGINE))
        parser.set(section, "tracker_particles", "8")
        parser.set(section, "tracker_hypotheses", "2")
        if kind == "custom-material":
            parser.set(section, "factory", "pair_a_prep.evaluation_factories:SearchFactory")
            parser.set(section, "tracker_factory", "pair_a_prep.evaluation_factories:HistoryTrackerFactory")
            parser.set(section, "search_mode", "fixed")
            parser.set(section, "public_initial_fen", PAWN)
            parser.set(section, "leaf_depth", "0")
        elif kind == "material-stockfish":
            parser.set(section, "scorer_id", "material" if side == "a" else "stockfish-d1")
            parser.set(section, "leaf_depth", "0" if side == "a" else "1")
    parser.set("match", "initial_fen", PAWN)
    parser.set("match", "rules", "teal")
    parser.set("match", "games", "1")
    parser.set("match", "max_plies", "2")
    parser.set("output", "directory", str(tmp_path / "results"))
    path = tmp_path / "input.ini"
    with path.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    return parser, path


@pytest.fixture
def engines(monkeypatch):
    opened = []
    original = chess.engine.SimpleEngine.popen_uci

    def launch(*args, **kwargs):
        engine = original(*args, **kwargs)
        opened.append(engine)
        return engine

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", launch)
    yield opened
    for engine in opened:
        if not engine.returncode.done():
            engine.close()
        engine.returncode.result(timeout=5)


def test_custom_material_does_not_claim_unused_network_weights(tmp_path):
    _, source = config_file(tmp_path)
    summary = run_evaluation.run(run_evaluation.load_config(source), source)
    assert summary["games_completed"] == 1
    report = json.loads((tmp_path / "results" / "provenance.json").read_text())
    assert report["checkpoint_paths"] == {"a": None, "b": None}, report["checkpoint_paths"]
    assert report["sha256"]["player_a_checkpoint"] is None
    assert report["sha256"]["player_b_checkpoint"] is None


def test_custom_material_ignores_nonexistent_unused_checkpoint(tmp_path):
    parser, source = config_file(tmp_path)
    parser.set("player_a", "checkpoint_path", str(tmp_path / "not-loaded.pt"))
    with source.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    summary = run_evaluation.run(run_evaluation.load_config(source), source)
    assert summary["games_completed"] == 1


def test_relative_path_lookup_preserves_launchable_engine(tmp_path, monkeypatch, engines):
    folder = tmp_path / "bin"
    folder.mkdir()
    local_engine = folder / "review-stockfish.exe"
    shutil.copyfile(ENGINE, local_engine)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "bin" + os.pathsep + os.environ["PATH"])
    found = shutil.which(local_engine.name)
    assert found is not None and Path(found).resolve() == local_engine
    assert not Path(found).is_absolute()
    with StockfishEvaluator(depth=1, path=found) as baseline:
        assert baseline.alive()
    agent = agent_factories.Factory({
        "scorer_id": "stockfish-d1", "leaf_depth": "1",
        "stockfish_path": local_engine.name,
    }).load_model()
    try:
        assert agent.scorer.alive()
        assert Path(agent.scorer.provenance_executable_path) == local_engine
    finally:
        agent.scorer.close()


@pytest.mark.parametrize("kind", ["material-stockfish", "network-belief"])
def test_actual_cpu_models_engines_and_saved_values(tmp_path, engines, kind):
    _, source = config_file(tmp_path, kind)
    config = run_evaluation.load_config(source)
    expected_ini = source.read_bytes()
    summary = run_evaluation.run(config, source)
    output = config["output_dir"]
    report = json.loads((output / "provenance.json").read_text())
    assert summary["games_completed"] == summary["games_capped"] == 1
    assert summary["games_failed"] == summary["games_scored"] == 0
    assert (output / "evaluate_config.ini").read_bytes() == expected_ini
    assert report["sha256"]["config"] == hashlib.sha256(expected_ini).hexdigest()
    for side in ("a", "b"):
        device = report["player_devices"][side]
        assert device["device"] == device["backend"] == "cpu"
        assert device["gpu_model"] is None and device["detection_note"] is None
        if kind == "network-belief":
            checkpoint = ROOT / config["players"][side]["checkpoint_path"]
            assert report["checkpoint_paths"][side] == str(checkpoint.resolve())
            assert report["sha256"]["player_" + side + "_checkpoint"] == digest(checkpoint)
        else:
            assert report["checkpoint_paths"][side] is None
            assert report["sha256"]["player_" + side + "_checkpoint"] is None
        if kind == "network-belief" or side == "b":
            assert report["stockfish"][side]["name"] == "Stockfish 19"
            assert report["stockfish"][side]["path"] == str(ENGINE.resolve())
            assert report["sha256"]["player_" + side + "_stockfish"] == digest(ENGINE)
        else:
            assert report["stockfish"][side] is None
    assert len(report["sha256"]["source_files"]) == 550
    assert all(digest(ROOT.joinpath(*name.split("/"))) == value
               for name, value in report["sha256"]["source_files"].items())
    assert len(engines) == (1 if kind == "material-stockfish" else 2)
    assert all(engine.returncode.result(timeout=5) == 0 for engine in engines)


def test_tensor_placement_overrides_claimed_device():
    net = torch.nn.Linear(1, 1).cpu()
    agent = SimpleNamespace(scorer=SimpleNamespace(device="cuda:9", net=net))
    assert provenance.player_device(agent, torch) == {
        "device": "cpu", "backend": "cpu", "gpu_model": None, "detection_note": None,
    }


@pytest.mark.parametrize("value,index", [("cuda", 2), ("cuda:1", 1)])
def test_cuda_values_respect_logical_index(value, index):
    fake = SimpleNamespace(
        device=lambda value: SimpleNamespace(index=int(value.split(":")[1]) if ":" in value else None),
        cuda=SimpleNamespace(current_device=lambda: 2, get_device_name=lambda index: "GPU " + str(index)),
    )
    actual = provenance.player_device(SimpleNamespace(scorer=SimpleNamespace(device=value)), fake)
    assert actual == {
        "device": "cuda:" + str(index), "backend": "cuda",
        "gpu_model": "GPU " + str(index), "detection_note": None,
    }


@pytest.mark.parametrize("models", [["Apple Test"], ["GPU One", "GPU Two"]])
def test_mps_values_and_ambiguous_adapter_note(monkeypatch, models):
    monkeypatch.setattr(provenance.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(provenance, "_command", lambda *args: json.dumps({
        "SPDisplaysDataType": [{"sppci_model": model} for model in models],
    }))
    actual = provenance.player_device(SimpleNamespace(device="mps:0"), None)
    assert actual["device"] == "mps:0" and actual["backend"] == "mps"
    assert actual["gpu_model"] == (models[0] if len(models) == 1 else None)
    assert (actual["detection_note"] is None) == (len(models) == 1)


def test_dynamic_source_hash_values_and_untracked_exclusion(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked file.py"
    tracked.write_bytes(b"print('before')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", tracked.name], check=True)
    before = provenance.source_file_hashes(tmp_path)
    assert before == {tracked.name: digest(tracked)}
    tracked.write_bytes(b"print('after')\r\n")
    (tmp_path / "untracked.py").write_bytes(b"pass\n")
    after = provenance.source_file_hashes(tmp_path)
    assert after == {tracked.name: digest(tracked)} and after != before
    tracked.unlink()
    assert provenance.source_file_hashes(tmp_path) == {tracked.name: None}
