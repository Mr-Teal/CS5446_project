"""Current rules must be measured, and historical measurements not relabelled."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from fow_shared import values
from pair_a_prep.provenance import normalized_sha256, NORMALIZATION
from pair_a_prep.rule_readiness import effective_rule_metadata, correct_ep_archive_metadata, LEGACY_PENDING


def fixture():
    return dict(pending_rule_difference=LEGACY_PENDING, source_hash_convention=NORMALIZATION,
        source_sha256={"fow_shared/values.py": normalized_sha256(Path(values.__file__).read_bytes()),
                       "pair_a_prep/clock_ablation.py": "original-execution-generator"},
        base_commit_at_execution="original-commit", turn_runs=[{"caller_elapsed_ms": 1.234}],
        games=[{"actions": [{"over_budget": False}]}], summary={"count": 1})


def test_merged_effective_rule_is_resolved():
    result = effective_rule_metadata()
    assert result["pending_rule_difference"] is None
    assert result["rule_readiness"]["status"] == "passed"
    assert result["rule_readiness"]["checks"][0]["actual_terminal"] is None


def test_failed_effective_check_cannot_be_reported_resolved(monkeypatch):
    monkeypatch.setattr(values, "terminal_score", lambda board: ("repetition", 0.))
    result = effective_rule_metadata()
    assert result["pending_rule_difference"] is not None
    assert result["rule_readiness"]["status"] == "unresolved"


def test_metadata_correction_preserves_every_execution_field_and_records_original_digest():
    old = fixture()
    before = deepcopy(old)
    raw = json.dumps(old, indent=2).encode()
    result = correct_ep_archive_metadata(old, raw)
    for key, value in before.items():
        if key != "pending_rule_difference":
            assert result[key] == value
    assert result["pending_rule_difference"] is None
    assert old == before
    correction = result["metadata_corrections"][0]
    assert correction["pre_correction_sha256_lf"] == normalized_sha256(raw)
    assert correction["timing_rerun"] is False
    assert correct_ep_archive_metadata(result, json.dumps(result).encode()) == result


def test_different_historical_rule_bytes_are_not_assumed_resolved():
    old = fixture()
    old["source_sha256"]["fow_shared/values.py"] = "old-unmerged-rules"
    with pytest.raises(ValueError, match="do not relabel historical"):
        correct_ep_archive_metadata(old, b"old report")


def test_clock_generator_emits_effective_merged_rule_metadata_without_running_matches():
    from pair_a_prep.clock_ablation import run
    result = run(budgets=(), seeds=(), repeats=0)
    assert result["pending_rule_difference"] is None
    assert result["rule_readiness"]["status"] == "passed"
    assert result["turn_runs"] == [] and result["games"] == []
