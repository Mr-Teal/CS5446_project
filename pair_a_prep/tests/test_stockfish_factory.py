"""Owned engine configuration, identity, reset and failure cleanup."""

from hashlib import sha256
from types import SimpleNamespace

import pytest

from pair_a_prep.evaluation_factories import SearchFactory


@pytest.fixture
def engine(tmp_path, monkeypatch):
    import pairb.stockfish
    opened = []
    class FakeStockfish:
        def __init__(self, depth, path, hash_mb, new_game_each_call, call_timeout_s):
            self.depth, self.path, self.hash_mb = depth, path, hash_mb
            self.new_game_each_call, self.call_timeout_s = new_game_each_call, call_timeout_s
            self.engine = SimpleNamespace(id={"name": "Stockfish Test", "author": "test"})
            self.name = "stockfish-test-d"+str(depth)
            self.resets = self.closed = 0
            opened.append(self)
        def evaluate_children(self, fen):
            from pairb.material import MaterialEvaluator
            return MaterialEvaluator().evaluate_children(fen)
        def alive(self):
            return self.closed == 0
        def new_game(self):
            self.resets += 1
        def close(self):
            self.closed += 1
    monkeypatch.setattr(pairb.stockfish, "StockfishEvaluator", FakeStockfish)
    path = tmp_path / "stockfish-test.exe"
    path.write_bytes(b"test binary, not executed")
    settings = dict(leaf_evaluator="stockfish", leaf_depth="1", stockfish_path=str(path),
                    stockfish_expected_name="Stockfish Test")
    return path, settings, opened


@pytest.mark.parametrize("mode", ["fixed", "anytime", "retained", "subgame"])
def test_engine_options_identity_ownership_and_per_game_reset(engine, mode):
    path, settings, opened = engine
    factory = SearchFactory({**settings, "search_mode": mode})
    agent = factory.load_model()
    try:
        leaf = opened[0]
        assert agent.evaluator is leaf
        assert leaf.depth == 1 and leaf.hash_mb == 16 and leaf.call_timeout_s == 2
        assert leaf.new_game_each_call
        assert leaf.provenance_executable_path == str(path.resolve())
        assert leaf.handoff_identity["executable_sha256"] == sha256(path.read_bytes()).hexdigest()
        assert ":leaf-" in agent.config_id
        factory.reset_game()
        factory.reset_game()
        assert leaf.resets == 2
        with pytest.raises(RuntimeError, match="exactly one"):
            factory.load_model()
    finally:
        agent.close()
    assert leaf.closed == 1


def test_binary_and_settings_affect_identity_but_relocating_identical_bytes_does_not(engine, tmp_path):
    path, settings, _ = engine
    copy = tmp_path / "relocated.exe"
    copy.write_bytes(path.read_bytes())
    other = tmp_path / "different.exe"
    other.write_bytes(b"different engine build")
    variations = [settings, {**settings, "stockfish_path": str(copy)},
        {**settings, "stockfish_path": str(other)}, {**settings, "stockfish_hash_mb": "32"},
        {**settings, "stockfish_new_game_each_call": "false"}, {**settings, "stockfish_call_timeout_s": "3"}]
    agents = [SearchFactory(s).load_model() for s in variations]
    try:
        ids = [agent.config_id for agent in agents]
        assert ids[0] == ids[1]
        assert len(set(ids)) == 5
    finally:
        for agent in agents:
            agent.close()


@pytest.mark.parametrize("extra", [{"stockfish_sha256": "wrong"}, {"leaf_depth": "0"},
    {"stockfish_hash_mb": "0"}, {"stockfish_call_timeout_s": "nan"},
    {"stockfish_new_game_each_call": "maybe"}, {"leaf_evaluator": "typo"}])
def test_bad_options_fail_before_engine_launch(engine, extra):
    _, settings, opened = engine
    with pytest.raises(ValueError):
        SearchFactory({**settings, **extra}).load_model()
    assert not opened


def test_identity_mismatch_and_agent_construction_failure_close_the_engine(engine):
    _, settings, opened = engine
    with pytest.raises(ValueError, match="UCI identity"):
        SearchFactory({**settings, "stockfish_expected_name": "another version"}).load_model()
    assert opened[-1].closed == 1
    with pytest.raises(ValueError, match="reserve fraction"):
        SearchFactory({**settings, "search_mode": "subgame", "submission_reserve_fraction": ".9"}).load_model()
    assert opened[-1].closed == 1


def test_partial_engine_constructor_failure_is_cleaned_up(engine, monkeypatch):
    import pairb.stockfish
    _, settings, opened = engine
    base = pairb.stockfish.StockfishEvaluator
    class FailsAfterOpening(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            raise ValueError("configure failure")
    monkeypatch.setattr(pairb.stockfish, "StockfishEvaluator", FailsAfterOpening)
    with pytest.raises(ValueError, match="configure failure"):
        SearchFactory(settings).load_model()
    assert opened[-1].closed == 1


def test_real_pair_c_handoff_wrapper_and_pinned_production_config(engine, tmp_path):
    import configparser
    from pathlib import Path
    from pair_a_prep.stockfish_handoff import run
    path, settings, opened = engine
    parser = configparser.ConfigParser()
    parser.read(Path(__file__).resolve().parents[1]/"data/pair_c_stockfish_smoke.ini", encoding="utf-8")
    for side in ("a", "b"):
        parser.set("player_"+side, "stockfish_expected_name", "Stockfish Test")
    incoming = tmp_path/"input.ini"
    with incoming.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    output = tmp_path/"handoff"
    report = run(incoming, output, str(path))
    assert report["status"] == "passed"
    assert report["source_config_sha256"] == sha256(incoming.read_bytes()).hexdigest()
    assert report["effective_config_sha256"] == sha256(Path(report["effective_config"]).read_bytes()).hexdigest()
    assert {"pair_c/run_evaluation.py", "pair_c/agent_api.py", "pair_c/tracker_api.py"} <= report["source_sha256"].keys()
    assert report["summary"]["games_capped"] == 2
    assert report["summary"]["games_scored"] == 0
    assert report["summary"]["player_a_win_rate"] is None
    assert report["factory_reset_events"] == 4
    assert report["diagnostics"]["actions"] == 8
    assert report["diagnostics"]["fallbacks"] == 0
    assert {row["identity"] for row in report["loaded"]} == {"a", "b"}
    assert all(not row["engine_alive_after_close"] for row in report["engine_close_checks"])
    assert all(item.closed == 1 and item.resets == 2 for item in opened)
    pinned = configparser.ConfigParser()
    pinned.read(report["pinned_config"], encoding="utf-8")
    for side in ("a", "b"):
        assert pinned.get("player_"+side, "factory").endswith(":SearchFactory")
        assert pinned.get("player_"+side, "stockfish_sha256") == sha256(path.read_bytes()).hexdigest()
    from pair_c.run_evaluation import load_config, run as production_run
    summary = production_run(load_config(Path(report["pinned_config"])), Path(report["pinned_config"]))
    assert summary["games_completed"] == 2 and summary["games_failed"] == 0
    import json
    records = [json.loads(line) for line in
               (output/"pinned-evaluation"/"games.jsonl").read_text(encoding="utf-8").splitlines()]
    plies = [ply for record in records for ply in record["plies"]]
    assert len(plies) == 8
    assert all("evaluator_calls" in ply["diagnostics"] for ply in plies)
    subgame = [ply for record in records for ply in record["plies"]
               if record["player_by_color"][ply["player"]] == "a"]
    assert len(subgame) == 4
    assert all(ply["diagnostics"]["fallback"] == 0 for ply in subgame)
    assert all(ply["diagnostics"]["search_nodes"] == ply["search_nodes"] for ply in plies)
    with pytest.raises(FileExistsError, match="fresh"):
        run(incoming, output, str(path))
