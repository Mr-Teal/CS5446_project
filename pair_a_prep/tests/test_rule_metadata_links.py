"""A metadata correction must not break linked immutable evidence."""

from copy import deepcopy
import json

import pytest

from pair_a_prep.provenance import artifact_sha256, ARTIFACT_HASH_CONVENTION
from pair_a_prep.rule_readiness import correct_linked_clock_metadata


def fixture():
    old_clock_bytes = b'{"original": "clock"}\n'
    clock = dict(source_sha256={"source": "execution"}, live_summary={"actions": 48},
        rule_readiness={"status": "passed"}, pending_rule_difference=None,
        metadata_corrections=[dict(correction="hardcoded_EP_pending_field_v1",
            pre_correction_sha256_lf=artifact_sha256(old_clock_bytes))])
    raw = json.dumps(clock).encode()
    audit = dict(source_sha256={"source": "execution"}, game={"actions": [{"elapsed_ms": 1.23}]},
        clock_artifact=dict(sha256=artifact_sha256(old_clock_bytes),
                            hash_convention=ARTIFACT_HASH_CONVENTION, live_summary={"actions": 48}))
    return audit, clock, raw


def test_link_update_preserves_execution_data_and_has_a_portable_new_digest():
    audit, clock, raw = fixture()
    before = deepcopy(audit)
    result = correct_linked_clock_metadata(audit, json.dumps(audit).encode(), clock, raw)
    assert audit == before
    assert result["game"] == before["game"] and result["source_sha256"] == before["source_sha256"]
    assert result["clock_artifact"]["sha256"] == artifact_sha256(raw)
    assert result["clock_artifact"]["rule_readiness"]["status"] == "passed"
    assert result["clock_artifact"]["pending_rule_difference"] is None
    assert result["metadata_corrections"][0]["timing_rerun"] is False
    assert correct_linked_clock_metadata(result, json.dumps(result).encode(), clock, raw) == result


def test_unrelated_old_link_and_execution_manifest_are_rejected():
    audit, clock, raw = fixture()
    audit["clock_artifact"]["sha256"] = "unrelated"
    with pytest.raises(ValueError, match="old link"):
        correct_linked_clock_metadata(audit, b"old audit", clock, raw)
    audit, clock, raw = fixture()
    audit["source_sha256"]["source"] = "different execution"
    with pytest.raises(ValueError, match="execution source"):
        correct_linked_clock_metadata(audit, b"old audit", clock, raw)


def test_corrected_post_main_archive_link_and_readiness_agree():
    from pathlib import Path
    results = Path(__file__).resolve().parents[1] / "results"
    audit = json.loads((results / "gift_accounting_post_main_reference.json").read_text(encoding="utf-8"))
    link = audit["clock_artifact"]
    raw = (results / link["path"]).read_bytes()
    clock = json.loads(raw)
    assert link["sha256"] == artifact_sha256(raw)
    assert link["rule_readiness"] == clock["rule_readiness"]
    assert link["pending_rule_difference"] is clock["pending_rule_difference"] is None
    assert audit["source_sha256"] == clock["source_sha256"]
    assert link["live_summary"] == clock["live_summary"]
    assert audit["metadata_corrections"][-1]["original_clock_sha256"] == clock["metadata_corrections"][-1]["pre_correction_sha256_lf"]
