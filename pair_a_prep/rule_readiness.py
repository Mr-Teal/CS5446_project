"""Effective EP-rule readiness and transparent metadata-only archive correction."""

from copy import deepcopy
from pathlib import Path

from .provenance import normalized_sha256
from .subgame_validation import rule_history_checks


LEGACY_PENDING = "PR37 effective EP repetition"


def effective_rule_metadata():
    checks = rule_history_checks()
    passed = bool(checks) and all(row["status"] == "passed" for row in checks)
    return dict(pending_rule_difference=None if passed else "shared FoW effective-EP repetition check unresolved",
        rule_readiness=dict(scope="shared FoW-effective EP repetition fixture, not every rule",
                            status="passed" if passed else "unresolved", checks=checks))


def correct_ep_archive_metadata(report, original_bytes):
    """Correct only a known stale field, preserving execution provenance/arrays.

    Backfill is permitted only if the recorded shared-rule bytes equal the
    currently exercised implementation and its declared EP check passes.
    The generator's old execution hash is intentionally not rewritten.
    """
    result = deepcopy(report)
    if result.get("pending_rule_difference") is None:
        return result
    if result.get("pending_rule_difference") != LEGACY_PENDING:
        raise ValueError("not the known hardcoded EP metadata defect")
    if report.get("source_hash_convention") != "sha256_utf8_source_bytes_crlf_to_lf_v1":
        raise ValueError("a normalized execution source manifest is required")
    from fow_shared import values
    actual = normalized_sha256(Path(values.__file__).read_bytes())
    recorded = report.get("source_sha256", {}).get("fow_shared/values.py")
    if recorded != actual:
        raise ValueError("execution shared-rule source differs; do not relabel historical readiness")
    current = effective_rule_metadata()
    if current["rule_readiness"]["status"] != "passed":
        raise ValueError("effective rule check must pass before correcting resolved metadata")
    result.update(current)
    result.setdefault("metadata_corrections", []).append(dict(
        correction="hardcoded_EP_pending_field_v1", original_pending=LEGACY_PENDING,
        corrected_pending=None, verified_shared_rule_sha256=actual,
        pre_correction_sha256_lf=normalized_sha256(original_bytes),
        reason="recorded shared-rule bytes match the implementation passing the EP history check",
        measured_arrays_unchanged=True, execution_source_manifest_unchanged=True,
        timing_rerun=False))
    return result


def correct_linked_clock_metadata(audit, original_audit_bytes, clock, corrected_clock_bytes):
    """Update a linked audit after a proven metadata-only clock correction."""
    from .provenance import artifact_sha256, ARTIFACT_HASH_CONVENTION
    result = deepcopy(audit)
    link = result["clock_artifact"]
    digest = artifact_sha256(corrected_clock_bytes)
    if link.get("hash_convention") != ARTIFACT_HASH_CONVENTION:
        raise ValueError("portable clock link convention required")
    if audit.get("source_sha256") != clock.get("source_sha256"):
        raise ValueError("audit and clock must retain the same execution source manifest")
    if link["sha256"] != digest:
        corrections = [row for row in clock.get("metadata_corrections", [])
                       if row.get("correction") == "hardcoded_EP_pending_field_v1"]
        if not corrections or link["sha256"] != corrections[0]["pre_correction_sha256_lf"]:
            raise ValueError("old link does not identify the pre-correction clock artifact")
        result.setdefault("metadata_corrections", []).append(dict(
            correction="linked_clock_EP_metadata_v1", original_clock_sha256=link["sha256"],
            corrected_clock_sha256=digest,
            pre_correction_audit_sha256_lf=artifact_sha256(original_audit_bytes),
            measured_arrays_unchanged=True, execution_source_manifest_unchanged=True, timing_rerun=False))
        link["sha256"] = digest
    link["rule_readiness"] = deepcopy(clock.get("rule_readiness"))
    link["pending_rule_difference"] = clock.get("pending_rule_difference")
    return result
