"""Pair B without torch (Intel Macs have no torch build): the tests that need it skip, the rest run."""
from no_torch import PAIR_B, run_without_torch


# Catches: a test file that imports torch (or a pairb module that does) before checking it is there,
# which breaks collection on a machine without torch instead of skipping that file.
def test_pair_b_tests_skip_cleanly_without_torch():
    r = run_without_torch(
        "import pytest, sys; sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', "
        "'tests/test_net1.py', 'tests/test_material.py']))", PAIR_B)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipped" in r.stdout and "error" not in r.stdout.lower()
