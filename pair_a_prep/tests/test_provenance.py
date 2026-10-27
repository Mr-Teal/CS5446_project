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
