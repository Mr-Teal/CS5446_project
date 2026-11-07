"""Learned-leaf search: actual model/engine integration, ownership and provenance."""

from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from pairb.search_factory import Factory


def settings(**extra):
    return dict(search_mode="fixed", search_depth="2", solver_rounds="4",
                max_nodes="1024", stop_on_time="false", **extra)


def test_invalid_search_and_checkpoint_settings_do_not_open_resources(tmp_path, monkeypatch):
    import pairb.search_factory as module

    def unexpected(*args, **kwargs):
        pytest.fail("invalid settings opened an engine")

    monkeypatch.setattr(module, "_load_leaf", unexpected)
    path = tmp_path / "best.pt"
    path.write_bytes(b"not a network")
    cases = [({}, "checkpoint_path"),
             ({"checkpoint_path": str(path), "leaf_depth": "0"}, "leaf_depth"),
             ({"checkpoint_path": str(path), "checkpoint_sha256": "wrong"}, "checkpoint_sha256"),
             ({"checkpoint_path": str(path), "search_mode": "typo"}, "search_mode")]
    for options, message in cases:
        config = settings(leaf_evaluator="network1")
        config.update(options)
        with pytest.raises(ValueError, match=message):
            Factory(config).load_model()


def test_material_search_still_loads_without_torch(monkeypatch):
    import builtins
    original = builtins.__import__

    def without_torch(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("torch disabled")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_torch)
    agent = Factory(settings(leaf_evaluator="material")).load_model()
    try:
        assert agent.evaluator.name.startswith("material-")
    finally:
        agent.close()


@pytest.fixture
def model(tmp_path):
    torch = pytest.importorskip("torch")
    from pairb.data import ENCODING
    from pairb.net1 import Network1

    torch.set_num_threads(1)
    torch.manual_seed(17)
    net = Network1(blocks=1, channels=8)
    path = tmp_path / "best.pt"
    torch.save(dict(state_dict=net.state_dict(), config=net.config, encoding=ENCODING), path)
    return path


def test_bad_checkpoint_closes_the_validated_engine(tmp_path, monkeypatch, model):
    import pairb.search_factory as module

    class Engine:
        closed = 0

        def close(self):
            self.closed += 1

    engine = Engine()
    monkeypatch.setattr(module, "_load_leaf", lambda settings: engine)
    path = tmp_path / "bad.pt"
    path.write_bytes(b"not a network")
    with pytest.raises(Exception):
        Factory(settings(leaf_evaluator="network1", checkpoint_path=str(path), device="cpu")).load_model()
    assert engine.closed == 1


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")
def test_real_network_search_keeps_engine_settings_provenance_and_game_reset(model, monkeypatch):
    from pair_a_prep.evaluation_factories import HistoryTrackerFactory
    from pair_a_prep.rules_adapter import RulesAdapter
    from fow_shared.contracts import AgentInput
    from pair_c.provenance import checkpoint_provenance, stockfish_provenance

    fen = "7k/8/8/8/8/8/P6p/K7 w - - 0 1"
    factory = Factory(settings(leaf_evaluator="network1", checkpoint_path=str(model), device="cpu",
                               leaf_depth="1", public_initial_fen=fen,
                               stockfish_hash_mb="8", stockfish_call_timeout_s="3"))
    agent = factory.load_model()
    engine = agent.evaluator.stockfish
    try:
        assert engine.handoff_identity["hash_mb"] == 8 and engine.call_timeout_s == 3
        assert not engine.new_game_each_call
        resets = []
        original = engine.new_game

        def reset():
            resets.append(True)
            original()

        monkeypatch.setattr(engine, "new_game", reset)
        for seed in [17, 18]:
            factory.reset_game()
            agent.reset("white", seed)
            tracker = HistoryTrackerFactory(dict(public_initial_fen=fen, sample_size="2")).create_tracker(
                type("Rules", (), {"name": "teal-rules-adapter"})(), fen)
            tracker.reset("white", seed)
            rules = RulesAdapter()
            observation = rules.observe(rules.initial_state(fen), "white")
            belief = tracker.update(observation)
            turn = AgentInput(observation, belief, 5000)
            decision = agent.act(turn)
            assert decision.move in observation.legal_moves
            assert set(decision.root_policy) == set(observation.legal_moves)
            assert sum(decision.root_policy.values()) == pytest.approx(1.0)
        assert len(resets) == 2
        path, digest, note = checkpoint_provenance(agent)
        assert Path(path) == model.resolve()
        assert digest == sha256(model.read_bytes()).hexdigest() and note is None
        metadata, engine_digest = stockfish_provenance(agent)
        assert engine_digest == sha256(Path(engine.provenance_executable_path).read_bytes()).hexdigest()
        assert metadata["name"].startswith("Stockfish")
        assert ":leaf-" in agent.config_id
        with pytest.raises(RuntimeError, match="exactly one"):
            factory.load_model()
    finally:
        agent.close()
    assert not engine.alive()
