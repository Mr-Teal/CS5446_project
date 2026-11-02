"""Self-play label collection: one validated part per game, no labels for openings or fallbacks."""

import json

import pytest

from fow_shared.recording import read_records
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.label_run import collect
from pair_a_prep.tests.test_chess_search import KINGS, ConstantLeaf


def small_config():
    return AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False,
                         max_nodes=2000, max_evaluator_calls=256)


def test_collect_writes_one_validated_part_per_game_and_resumes(tmp_path):
    from pairb.label_validation import validate
    settings = dict(games=2, seed=17, evaluator=ConstantLeaf(), config=small_config(), time_budget_ms=1000,
                    max_states=1000, sample_size=4, opening_range=(1, 1), max_plies=6,
                    initial_fen=KINGS, log=lambda *args: None)
    identity, proto, summaries = collect(tmp_path, **settings)
    parts = sorted(tmp_path.glob("part-*.jsonl"))
    assert [p.name for p in parts] == ["part-0000.jsonl", "part-0001.jsonl"]
    assert len(summaries) == 2
    for summary in summaries:
        # Every ply is one decision: an unlabelled opening move, a labelled solve, or a fallback.
        assert summary["opening_plies"] == 1
        assert summary["records"] + summary["fallbacks"] + summary["opening_plies"] == summary["plies"]
        assert summary["records"] > 0
    records = [record for part in parts for record in read_records(part)]
    assert len(records) == sum(s["records"] for s in summaries)
    for record in records:
        belief = record.agent_input.belief
        assert len(record.hypothesis_values) == len(belief.hypotheses)
        assert record.root_value == pytest.approx(sum(h.weight*v for h, v in zip(belief.hypotheses, record.hypothesis_values)))
        assert set(record.decision.root_policy) == set(record.agent_input.observation.legal_moves)
        assert record.game_id.startswith(identity) and record.config_id == identity
        assert any(k.startswith("played_policy:") for k in record.decision.diagnostics)
        assert record.agent_input.observation.ply >= 1  # the opening ply is never labelled
    report = validate(tmp_path, require_played_policy=True)
    assert report.errors == []
    progress = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert [row["index"] for row in progress] == [0, 1]
    # A second run over the same folder finds both parts and plays nothing.
    assert collect(tmp_path, **settings)[2] == []
    assert proto["tracker"]["implementation"] == "tail-guarded-exact-v1"


def test_opening_length_comes_from_the_game_seed_and_both_colours_share_it(tmp_path):
    _, _, summaries = collect(tmp_path, games=3, seed=40, evaluator=ConstantLeaf(), config=small_config(),
                              time_budget_ms=1000, max_states=1000, sample_size=4, opening_range=(2, 8),
                              max_plies=4, initial_fen=KINGS, log=lambda *args: None)
    openings = [s["opening_plies"] for s in summaries]
    assert all(2 <= k <= 8 for k in openings)
    # With a 4-ply cap, every ply before the opening length is unlabelled.
    for summary in summaries:
        assert summary["records"] == max(0, summary["plies"] - summary["opening_plies"]) - summary["fallbacks"]
