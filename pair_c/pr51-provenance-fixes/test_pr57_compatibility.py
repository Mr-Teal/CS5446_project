import importlib.util
import os
from pathlib import Path

import pytest

from pair_a_prep.evaluation_factories import SearchFactory

MODULE_PATH = Path(os.environ["PR51_ROOT"]) / "pair_c" / "provenance.py"
SPEC = importlib.util.spec_from_file_location("review_pr51_provenance", MODULE_PATH)
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)


@pytest.mark.parametrize("mode", ["fixed", "anytime", "retained", "subgame"])
def test_pr51_records_actual_pr57_engine(mode):
    agent = SearchFactory({
        "search_mode": mode, "leaf_evaluator": "stockfish", "leaf_depth": "1",
        "stockfish_path": os.environ["PR51_ENGINE"], "stockfish_expected_name": "Stockfish 19",
    }).load_model()
    try:
        assert agent.evaluator.alive()
        assert agent.evaluator.engine.id["name"] == "Stockfish 19"
        info, digest = provenance.stockfish_provenance(agent)
        assert info is not None, "PR51 returns no engine for a live PR57 Stockfish evaluator"
        assert info["name"] == "Stockfish 19"
        assert digest == agent.evaluator.handoff_identity["executable_sha256"]
        assert provenance.player_device(agent, None)["device"] == "cpu"
    finally:
        agent.close()
    assert not agent.evaluator.alive()
