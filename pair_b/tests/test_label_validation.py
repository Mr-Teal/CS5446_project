"""Acceptance regressions for the Pair A -> Pair B label handoff."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys

import chess
import pytest

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, TrainingRecord
from fow_shared.recording import write_records
from pairb.data import split_of
from pairb.label_validation import validate
from pairb.observe import observe


def example(board=None):
    board = board or chess.Board()
    player = "white" if board.turn else "black"
    obs = observe(board, player)
    legal = obs.legal_moves
    policy = {m: 1 / len(legal) for m in legal}
    hypotheses = (Hypothesis(board.fen(), 0.25, "a"), Hypothesis(board.fen(), 0.75, "b"))
    turn = AgentInput(obs, Belief(player, 0, hypotheses, population_size=None), 100)
    diagnostics = {f"played_policy:{m}": p for m, p in policy.items()}
    return TrainingRecord(turn, Decision(legal[0], policy, diagnostics), 0.25, (-0.5, 0.5),
                          42, "obscuro", "pilot-v1-hash", "game-1")


def export(tmp_path, records=None, name="part-000.jsonl"):
    records = [example()] if records is None else records
    path = tmp_path / name
    write_records(path, records)
    return path


def mutate(tmp_path, change):
    obj = asdict(example())
    change(obj)
    path = tmp_path / "part-000.jsonl"
    path.write_text(json.dumps(obj) + "\n")
    return path


def test_valid_same_fen_different_histories_unknown_population_and_empty_file(tmp_path):
    export(tmp_path)
    (tmp_path / "part-empty.jsonl").touch()
    report = validate(tmp_path)
    assert not report.errors
    assert (report.records, report.files, len(report.games)) == (1, 2, 1)
    assert any("manifest" in w for w in report.warnings)


@pytest.mark.parametrize("field", ["game_id", "agent_name", "config_id"])
def test_blank_label_identifiers_rejected(tmp_path, field):
    report = validate(mutate(tmp_path, lambda o: o.update({field: "  "})))
    assert any(field in e for e in report.errors)


@pytest.mark.parametrize("delta,valid", [(0.5e-6, True), (2e-6, False)])
def test_weighted_root_tolerance_and_physical_line(tmp_path, delta, valid):
    record = replace(example(), root_value=0.25 + delta)
    path = export(tmp_path, [record])
    path.write_text("\n" + path.read_text())
    report = validate(path)
    assert (not report.errors) == valid
    if not valid:
        assert any(f"{path}:2: root_value" in e for e in report.errors)


@pytest.mark.parametrize("change,message", [
    (lambda o: o.update(hypothesis_values=[0]), "one value"),
    (lambda o: o.update(root_value=2), "[-1, 1]"),
    (lambda o: o["decision"].update(root_policy={}), "legal actions"),
    (lambda o: o["decision"].update(move="a1a8"), "unavailable move"),
    (lambda o: o["agent_input"]["belief"]["hypotheses"][0].update(weight=0), "positive"),
    (lambda o: o["agent_input"]["belief"]["hypotheses"][0].update(weight=0.5), "sum to one"),
])
def test_existing_contracts_still_enforced(tmp_path, change, message):
    report = validate(mutate(tmp_path, change))
    assert any(message in e and "line 1" in e for e in report.errors)


def test_schema_error_stops_only_its_file(tmp_path):
    (tmp_path / "part-000.jsonl").write_text("{}\n")
    export(tmp_path, name="part-001.jsonl")
    report = validate(tmp_path)
    assert report.errors and report.records == 1


@pytest.mark.parametrize("diagnostics,fragment", [
    ({"played_policy:a2a3": 1.0}, "exactly"),
    ({"played_policy:a2a3": -1.0}, "probabilities"),
    ({"d1:2": 0.0}, "index"),
    ({"d1:-1": 0.0}, "index"),
    ({"d1:00": 0.0}, "index"),
    ({"d1:0": 1.1}, "[-1, 1]"),
])
def test_diagnostic_errors(tmp_path, diagnostics, fragment):
    record = replace(example(), decision=replace(example().decision, diagnostics=diagnostics))
    report = validate(export(tmp_path, [record]))
    assert any(fragment in e for e in report.errors)


def test_missing_played_policy_warns_but_d1_is_opt_in(tmp_path):
    r = example()
    path = export(tmp_path, [replace(r, decision=replace(r.decision, diagnostics={}))])
    assert not validate(path).errors
    assert any("played_policy" in w for w in validate(path).warnings)
    assert sum("required" in e for e in validate(path, require_d1=True).errors) == 2


def test_complete_d1_and_black_rule_exception(tmp_path):
    r = example()
    d = {**r.decision.diagnostics, "d1:0": -0.2, "d1:1": 0.3}
    assert not validate(export(tmp_path, [replace(r, decision=replace(r.decision, diagnostics=d))]), require_d1=True).errors
    # A king capture is available to Black; no D1 engine value is needed.
    rule = example(chess.Board("8/8/8/8/8/8/4k3/4K3 b - - 0 1"))
    assert not validate(export(tmp_path, [rule]), require_d1=True).errors


def test_played_move_must_have_positive_mass(tmp_path):
    r = example()
    d = {f"played_policy:{m}": float(m == r.agent_input.observation.legal_moves[-1])
         for m in r.agent_input.observation.legal_moves}
    report = validate(export(tmp_path, [replace(r, decision=replace(r.decision, diagnostics=d))]))
    assert any("positive probability" in e for e in report.errors)


def test_encoder_detects_visible_contradiction(tmp_path):
    def change(obj):
        obj["agent_input"]["observation"]["visible_pieces"]["a1"] = "Q"
    assert any("contradicts observed piece" in e for e in validate(mutate(tmp_path, change)).errors)


def test_custom_pattern_and_single_file_manifest_scope(tmp_path):
    path = export(tmp_path, name="labels.jsonl")
    (tmp_path / "manifest.json").write_text(json.dumps({"records": 10, "created": "today", "config_id": "pilot-v1-hash"}))
    for source, pattern in ((path, "part-*.jsonl"), (tmp_path, "*.jsonl")):
        report = validate(source, pattern=pattern)
        assert not report.errors
        assert any("count not compared" in w for w in report.warnings)


@pytest.mark.parametrize("content", ['{"records":2}', '[]', 'not-json'])
def test_bad_manifest(tmp_path, content):
    export(tmp_path)
    (tmp_path / "manifest.json").write_text(content)
    assert any("manifest" in e for e in validate(tmp_path).errors)


def test_empty_dataset_fails(tmp_path):
    export(tmp_path, [])
    assert any("no records" in e for e in validate(tmp_path).errors)


def test_training_split_evidence_and_wrong_assignment(tmp_path):
    games = {name: next(f"g{i}" for i in range(1000) if split_of(f"g{i}") == name)
             for name in ("train", "val", "test")}
    export(tmp_path, [replace(example(), game_id=g) for g in games.values()])
    path = tmp_path / "splits.json"
    evidence = {"train": [games["train"]], "val": [games["val"]], "test_held_out_games": 1}
    path.write_text(json.dumps(evidence))
    report = validate(tmp_path, splits=path)
    assert not report.errors
    assert any("no explicit test" in w for w in report.warnings)
    evidence["train"] = [games["test"]]
    path.write_text(json.dumps(evidence))
    assert any("belongs to test" in e for e in validate(tmp_path, splits=path).errors)


def test_split_overlap(tmp_path):
    game = next(f"g{i}" for i in range(100) if split_of(f"g{i}") == "train")
    export(tmp_path, [replace(example(), game_id=game)])
    path = tmp_path / "splits.json"
    path.write_text(json.dumps({"train": [game], "val": [game]}))
    assert any("more than one split" in e for e in validate(tmp_path, splits=path).errors)


def test_valid_manifest_and_black_encoder(tmp_path):
    board = chess.Board()
    board.push_uci("e2e4")
    export(tmp_path, [example(board)])
    (tmp_path / "manifest.json").write_text(json.dumps({
        "records": 1, "created": "2026-10-19", "config_id": "pilot-v1-hash"}))
    report = validate(tmp_path)
    assert not report.errors and not report.warnings


def test_played_policy_sum(tmp_path):
    r = example()
    diagnostics = {key: value / 2 for key, value in r.decision.diagnostics.items()}
    report = validate(export(tmp_path, [replace(r, decision=replace(r.decision, diagnostics=diagnostics))]))
    assert any("sum to one" in e for e in report.errors)


@pytest.mark.parametrize("text", ["null", "[]", '{"agent_input":null}', "{", "NaN"])
def test_malformed_json_shapes_are_reported(tmp_path, text):
    (tmp_path / "part-000.jsonl").write_text(text + "\n")
    assert validate(tmp_path).errors


def test_nonfinite_diagnostics_rejected_by_shared_contract(tmp_path):
    path = mutate(tmp_path, lambda o: o["decision"]["diagnostics"].update({"d1:0": float("nan")}))
    assert any("finite" in e for e in validate(path).errors)


def test_cli_without_torch_or_engine_and_no_input_writes(tmp_path):
    path = export(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    root = Path(__file__).resolve().parents[2]
    # A fresh process: fail immediately if the CLI tries importing torch.
    code = ("import runpy,sys; sys.modules['torch']=None; "
            f"sys.argv=['validate_labels.py',{str(path)!r}]; "
            f"runpy.run_path({str(root / 'pair_b/scripts/validate_labels.py')!r},run_name='__main__')")
    env = {**os.environ, "PATH": "", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "PASS: 1 parsed records" in result.stdout
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    path.write_text("{}\n")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 1 and "schema/read error" in result.stdout
