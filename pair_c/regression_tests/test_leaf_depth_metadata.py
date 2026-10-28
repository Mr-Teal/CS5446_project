"""Reject scorer/depth disagreement before loading an engine or checkpoint."""

import pytest

from pair_c.agent_factories import Factory
from pairb.material import MaterialEvaluator


@pytest.mark.parametrize("scorer,wrong", [
    ("material", 1), ("stockfish-d1", 11), ("stockfish-d11", 1),
    ("network1", 11), ("belief", 0),
])
def test_mismatched_metadata_is_rejected_before_loading(scorer, wrong):
    with pytest.raises(ValueError, match="requires leaf_depth="):
        Factory(dict(scorer_id=scorer, leaf_depth=str(wrong))).load_model()


def test_valid_stockfish_depth_reaches_constructor(monkeypatch):
    from pair_c import agent_factories
    observed = []
    def fake(depth, **kwargs):
        observed.append(depth)
        return MaterialEvaluator()
    monkeypatch.setattr(agent_factories, "StockfishEvaluator", fake)
    Factory(dict(scorer_id="stockfish-d11", leaf_depth="11")).load_model()
    assert observed == [11]


def test_material_needs_no_engine_or_network():
    factory = Factory(dict(scorer_id="material", leaf_depth="0"))
    agent = factory.load_model()
    factory.reset_game()
    assert isinstance(agent.scorer, MaterialEvaluator)
