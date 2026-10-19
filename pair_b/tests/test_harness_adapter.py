"""The belief network's adapter for Bryan's evaluator harness (pair_b_prep, PR #3).

The adapter needs torch, Stockfish (the belief checkpoint is a use_d1 network, so its evaluator starts
one) and PR #3's make_turn. This file skips without torch and without pair_b_prep, which a branch that
does not hold PR #3 has not got. There the evidence is a run of the real harness on a merge of the two,
which is also what the Fog Lab Tests tab does. Every test that builds closes what it built.
"""
import contextlib
import hashlib
import shutil
from collections import Counter

import chess
import chess.engine
import pytest

from no_torch import PAIR_B

pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there
pytest.importorskip("pair_b_prep")  # Bryan's harness is PR #3: skip where it is not merged

from pair_b_prep import adapter_example
from pair_b_prep.harness import run_checks
from pairb.belief_data import ENCODING
from pairb.belief_evaluator import BeliefNetworkEvaluator
from pairb.harness_adapter import build
from pairb.network_evaluator import pick_device

NEEDS_STOCKFISH = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")
CHECKPOINT = PAIR_B / "checkpoints" / "belief-v1-d1" / "best.pt"
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # a stand-in: the adapter records the revision, never checks it


def config(**changes) -> dict:
    return {"checkpoint": str(CHECKPOINT), "device": "cpu", "source_commit": COMMIT, **changes}


def without(key) -> dict:
    return {k: v for k, v in config().items() if k != key}


@contextlib.contextmanager
def opened(cfg):
    """build(cfg), closed afterwards whatever the test finds."""
    bundle = build(cfg)
    try:
        yield bundle
    finally:
        bundle.close()


# Catches: a part of the bundle missing (the harness reads evaluator, make_turn and metadata, and calls
# close), a make_turn other than Bryan's (his probe specs would build the wrong turns), an evaluator
# that is not the belief network, and an engine that remembers earlier calls (the checks compare a
# board scored alone with the same board in a batch).
@NEEDS_STOCKFISH
def test_the_bundle_has_what_the_harness_reads():
    with opened(config()) as bundle:
        assert {"evaluator", "make_turn", "metadata", "close"} <= set(vars(bundle))
        assert bundle.make_turn is adapter_example.make_turn
        assert isinstance(bundle.evaluator, BeliefNetworkEvaluator)
        assert bundle.evaluator.stockfish.new_game_each_call is True
        assert len(bundle.evaluator.evaluate_children(chess.STARTING_FEN)) == 20


# Catches: a key dropped or renamed (the report holds the metadata as written), and a hash, name, device
# or revision that is not the one this run used.
@NEEDS_STOCKFISH
def test_metadata_records_what_the_run_used():
    with opened(config()) as bundle:
        assert bundle.metadata == {
            "demo_only": False,
            "checkpoint_sha256": hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest(),
            "device": "cpu",
            "evaluator": bundle.evaluator.name,
            "source_commit": COMMIT,
            "encoding": ENCODING,
        }
        assert bundle.evaluator.device == "cpu"
        assert bundle.evaluator.name.startswith("belief-v1-d1+")


# Catches: a null device sent on as the text "None" or forced to the CPU. The Tests tab sends null, and
# the report must name the device the network really ran on.
@NEEDS_STOCKFISH
@pytest.mark.parametrize("cfg", [config(device=None), without("device")], ids=["null", "missing"])
def test_a_null_or_missing_device_lets_pairb_choose(cfg):
    with opened(cfg) as bundle:
        assert bundle.evaluator.device == pick_device(None)
        assert bundle.metadata["device"] == bundle.evaluator.device


# Catches: close not reaching the evaluator, which would leave a Stockfish process behind after every run.
@NEEDS_STOCKFISH
def test_close_stops_the_engine():
    bundle = build(config())
    bundle.close()
    with pytest.raises(chess.engine.EngineTerminatedError):
        bundle.evaluator.stockfish.engine.ping()


# Catches: a run that goes on without saying which revision or checkpoint it measured, and a missing key
# found only after the network is loaded and the engine is running (an engine left behind).
@pytest.mark.parametrize("key", ["checkpoint", "source_commit"])
def test_the_required_keys_are_checked_before_anything_starts(key, monkeypatch):
    def not_reached(*args, **kwargs):
        pytest.fail("the network was loaded although the config was incomplete")

    monkeypatch.setattr(BeliefNetworkEvaluator, "from_checkpoint", not_reached)
    with pytest.raises(KeyError, match=key):
        build(without(key))


# Catches: an engine that is not there surfacing as an obscure error from inside python-chess.
def test_a_missing_stockfish_is_named():
    with pytest.raises(FileNotFoundError, match="Stockfish not found"):
        build(config(stockfish_path="no-such-engine"))


# Catches: the adapter and the harness disagreeing: it is Bryan's own checks that the Tests tab reports,
# and a belief network that cannot pass them through this bundle is not checked at all.
@NEEDS_STOCKFISH
def test_bryans_checks_run_on_the_bundle_and_pass():
    with opened(config()) as bundle:
        results = run_checks(bundle)
    failed = [(r["name"], r["detail"]) for r in results if r["status"] == "fail"]
    assert not failed
    assert Counter(r["status"] for r in results) == {"pass": 16, "manual": 2}
