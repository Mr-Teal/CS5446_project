"""Portable evidence must cover adjudication and leaf/search dependencies."""

from pair_a_prep.provenance import normalized_sha256, source_manifest, git_revision


def test_manifest_normalizes_checkout_eols_and_covers_runtime_dependencies(tmp_path):
    assert normalized_sha256(b"a\r\nb\r\n") == normalized_sha256(b"a\nb\n")
    manifest = source_manifest()
    assert {"fow_shared/values.py", "fow_shared/evaluation.py", "pair_b/src/pairb/material.py",
            "pair_b/src/pairb/values.py", "pair_a_prep/pcfr.py", "pair_a_prep/chess_search.py",
            "pair_a_prep/one_sided.py", "pair_a_prep/gadgets.py"} <= manifest.keys()
    assert not any("/tests/" in path or "/local_runs/" in path for path in manifest)
    assert git_revision(tmp_path) is None


def test_artifact_link_is_portable_across_git_checkout_newline_conversion():
    from pair_a_prep.provenance import artifact_sha256, ARTIFACT_HASH_CONVENTION
    from hashlib import sha256
    lf = b'{\n  "clock": 1\n}\n'
    crlf = lf.replace(b"\n", b"\r\n")
    assert ARTIFACT_HASH_CONVENTION == "sha256_utf8_artifact_bytes_crlf_to_lf_v1"
    assert artifact_sha256(lf) == artifact_sha256(crlf) == sha256(lf).hexdigest()
    assert artifact_sha256(lf) != artifact_sha256(lf.replace(b"1", b"2"))


def test_recorded_review_clock_link_survives_checkout_conversion():
    import json
    from pathlib import Path
    from pair_a_prep.provenance import artifact_sha256, ARTIFACT_HASH_CONVENTION
    results = Path(__file__).resolve().parents[1] / "results"
    report = json.loads((results / "gift_accounting_review_v2.json").read_text(encoding="utf-8"))
    link = report["clock_artifact"]
    lf = (results / link["path"]).read_bytes().replace(b"\r\n", b"\n")
    assert link["hash_convention"] == ARTIFACT_HASH_CONVENTION
    assert link["sha256"] == artifact_sha256(lf)
    assert link["sha256"] == artifact_sha256(lf.replace(b"\n", b"\r\n"))
