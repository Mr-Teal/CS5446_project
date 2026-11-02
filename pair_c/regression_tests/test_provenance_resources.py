"""Actual resource declarations, custom evaluator wrappers and path resolution."""

import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from pairb.material import MaterialEvaluator
from pairb.stockfish import StockfishEvaluator
from pair_c import agent_factories, provenance, run_evaluation


@pytest.mark.parametrize("existing", [True, False])
def test_unused_custom_checkpoint_is_not_hashed(tmp_path, monkeypatch, existing):
    checkpoint = tmp_path / "unused.pt"
    if existing:
        checkpoint.write_bytes(b"never loaded")
    source = tmp_path / "input.ini"
    source.write_bytes(b"original configuration\r\n")
    config = {"players": {
        side: {"factory": "custom:Factory", "checkpoint_path": str(checkpoint)}
        for side in ("a", "b")
    }}
    config["hash_rules_path"] = tmp_path / "rules.json"
    config["hash_rules"] = {"text_extensions": [".py"], "text_filenames": [], "binary_extensions": []}
    players = {side: SimpleNamespace(evaluator=MaterialEvaluator()) for side in ("a", "b")}
    virtual_source = tmp_path / "example.py"
    virtual_source.write_bytes(b"print('example')\n")
    monkeypatch.setattr(run_evaluation, "ROOT", tmp_path)
    monkeypatch.setattr(run_evaluation, "cpu_model", lambda: "Test CPU")
    monkeypatch.setattr(run_evaluation, "discover_sources", lambda root: ("git", ["example.py"], None))
    monkeypatch.setattr(run_evaluation, "git_provenance", lambda root: {
        "git_commit": "test-commit", "git_status": [" M example.py"], "git_detection_notes": {},
    })
    report = run_evaluation.collect_provenance(config, source, "test-start", players)
    assert report["sha256"]["source_files"] == {
        "example.py": hashlib.sha256(virtual_source.read_bytes()).hexdigest(),
    }
    assert report["checkpoint_paths"] == {"a": None, "b": None}
    assert report["sha256"]["player_a_checkpoint"] is None
    assert report["sha256"]["player_b_checkpoint"] is None
    assert all(report["checkpoint_detection_notes"].values())
    assert report["sha256"]["config"] == hashlib.sha256(b"original configuration\n").hexdigest()


@pytest.mark.parametrize("location", ["agent", "scorer", "evaluator", "agent-with-evaluator"])
def test_explicit_loaded_checkpoint_path_is_hashed(tmp_path, location):
    path = tmp_path / "loaded.pt"
    path.write_bytes(b"loaded checkpoint bytes")
    component = SimpleNamespace(provenance_checkpoint_path=path)
    if location == "agent-with-evaluator":
        component.evaluator = MaterialEvaluator()
        agent = component
    else:
        agent = component if location == "agent" else SimpleNamespace(**{location: component})
    assert provenance.checkpoint_provenance(agent) == (
        str(path.resolve()), hashlib.sha256(path.read_bytes()).hexdigest(), None,
    )


def test_explicit_no_checkpoint_and_missing_loaded_file(tmp_path):
    assert provenance.checkpoint_provenance(SimpleNamespace(provenance_checkpoint_path=None)) == (
        None, None, None,
    )
    with pytest.raises(FileNotFoundError):
        provenance.checkpoint_provenance(SimpleNamespace(
            provenance_checkpoint_path=tmp_path / "missing-loaded.pt",
        ))


@pytest.mark.parametrize("location", ["agent", "scorer", "evaluator", "nested-scorer", "nested-evaluator"])
def test_engine_discovery_uses_actual_component(tmp_path, location):
    path = tmp_path / "engine.exe"
    path.write_bytes(b"test engine bytes")
    engine = SimpleNamespace(
        engine=SimpleNamespace(id={"name": "Test engine", "author": "Test author"}),
        provenance_executable_path=str(path),
    )
    if location == "agent":
        agent = engine
    elif location.startswith("nested-"):
        agent = SimpleNamespace(**{location.removeprefix("nested-"): SimpleNamespace(stockfish=engine)})
    else:
        agent = SimpleNamespace(**{location: engine})
    assert provenance.stockfish_provenance(agent) == (
        {"path": str(path.resolve()), "name": "Test engine", "author": "Test author"},
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_evaluator_used_when_scorer_is_none():
    class OwnedStockfish(StockfishEvaluator):
        def __init__(self):
            pass
    agent = SimpleNamespace(scorer=None, evaluator=OwnedStockfish())
    assert provenance.player_device(agent, None) == {
        "device": "cpu", "backend": "cpu", "gpu_model": None, "detection_note": None,
    }


def test_evaluator_tensor_device_takes_precedence():
    net = SimpleNamespace(parameters=lambda: iter([SimpleNamespace(device="cpu")]))
    agent = SimpleNamespace(evaluator=SimpleNamespace(net=net, device="cuda:2"))
    assert provenance.player_device(agent, None)["device"] == "cpu"


@pytest.mark.parametrize("scorer_id,module_name,class_name", [
    ("network1", "pairb.network_evaluator", "NetworkEvaluator"),
    ("belief", "pairb.belief_evaluator", "BeliefNetworkEvaluator"),
])
def test_builtin_factory_records_the_path_passed_to_loader(
    tmp_path, monkeypatch, scorer_id, module_name, class_name,
):
    from importlib import import_module

    calls = []
    scorer = SimpleNamespace(name="test-network", stockfish=None)

    def load(path, **kwargs):
        calls.append(path)
        return scorer

    monkeypatch.setattr(getattr(import_module(module_name), class_name), "from_checkpoint", load)
    path = tmp_path / "actual.pt"
    agent = agent_factories.Factory({
        "scorer_id": scorer_id, "leaf_depth": "1", "checkpoint_path": str(path),
    }).load_model()
    assert calls == [path.resolve()]
    assert agent.scorer.provenance_checkpoint_path == path.resolve()


def test_builtin_material_explicitly_declares_no_checkpoint():
    agent = agent_factories.Factory({
        "scorer_id": "material", "leaf_depth": "0", "checkpoint_path": "unused.pt",
    }).load_model()
    assert provenance.checkpoint_provenance(agent) == (None, None, None)


def test_relative_path_result_is_resolved_from_current_directory(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    path = bin_dir / "test-engine.exe"
    path.write_bytes(b"not executed")
    seen = []

    def load(depth, *, path, **kwargs):
        seen.append(path)
        return SimpleNamespace(name="test-stockfish")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_factories.shutil, "which", lambda value: str(Path("bin") / path.name))
    monkeypatch.setattr(agent_factories, "StockfishEvaluator", load)
    agent = agent_factories.Factory({
        "scorer_id": "stockfish-d1", "leaf_depth": "1", "stockfish_path": path.name,
    }).load_model()
    assert seen == [str(path.resolve())]
    assert agent.scorer.provenance_executable_path == str(path.resolve())


def test_source_hashes_track_current_bytes_and_deletions(tmp_path):
    rules = {"text_extensions": [".py"], "text_filenames": [], "binary_extensions": []}
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    path = tmp_path / "tracked file.py"
    path.write_bytes(b"original\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", path.name], check=True, capture_output=True)
    assert provenance.source_file_hashes(tmp_path, rules) == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.write_bytes(b"modified\r\n")
    (tmp_path / "untracked.py").write_bytes(b"not tracked\n")
    assert provenance.source_file_hashes(tmp_path, rules) == {
        path.name: hashlib.sha256(b"modified\n").hexdigest(),
    }
    path.unlink()
    assert provenance.source_file_hashes(tmp_path, rules) == {path.name: None}
