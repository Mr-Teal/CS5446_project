"""Self-play label collection: one validated part per game, no labels for openings or fallbacks."""

import hashlib
import json

import pytest

from fow_shared.recording import read_records
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.label_run import collect, main
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


def test_main_with_the_network_leaf_records_the_checkpoint_identity(tmp_path):
    """--evaluator belief_network: the leaf is the belief network, with no engine, and the checkpoint's hash is
    part of the protocol (so each self-play generation has its own config_id); the run otherwise writes the
    same validated records as a material or Stockfish run."""
    torch = pytest.importorskip("torch")
    from pairb.belief_data import ENCODING
    from pairb.belief_net import BeliefNetwork
    net = BeliefNetwork(blocks=1, channels=8, embed=16, use_d1=False)
    checkpoint = tmp_path / "belief-tiny" / "best.pt"
    checkpoint.parent.mkdir()
    torch.save({"state_dict": net.state_dict(), "config": net.config, "encoding": ENCODING}, checkpoint)
    out = tmp_path / "labels"
    code = main(["--out", str(out), "--games", "1", "--seed", "17", "--evaluator", "belief_network",
                 "--checkpoint", str(checkpoint), "--device", "cpu", "--initial-fen", KINGS,
                 "--opening-plies", "1", "1", "--max-plies", "6", "--max-states", "1000", "--sample-size", "4",
                 "--no-clock", "--solver-rounds", "4", "--max-nodes", "2000", "--max-evaluator-calls", "256",
                 "--time-budget-ms", "1000"])
    assert code == 0
    manifest = json.loads((out / "manifest.json").read_text())
    engine = manifest["protocol"]["engine"]
    assert engine["kind"] == "belief_network"
    assert engine["checkpoint_sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert manifest["protocol"]["leaf"]["name"].startswith("belief-tiny")
    records = list(read_records(out / "part-0000.jsonl"))
    assert records and all(record.config_id == manifest["config_id"] for record in records)
    assert manifest["validation"]["errors"] == 0


def test_main_requires_a_checkpoint_for_the_network_leaf(tmp_path):
    with pytest.raises(SystemExit):
        main(["--out", str(tmp_path), "--evaluator", "belief_network"])
