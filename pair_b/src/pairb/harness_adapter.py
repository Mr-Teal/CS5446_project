"""The belief network as a scorer for Bryan's evaluator harness (pair_b_prep.harness, PR #3).

The harness opens a scorer through a factory, build(config), that returns a bundle: the evaluator, a
make_turn that builds genuine fow_shared turns from the harness's probe specs, metadata for the report,
and close. PR #3's real_adapter does this for piece values, Stockfish and Network 1; this does it for the
belief network, so one harness run can cover all five scorers:

    python -m pair_b_prep.harness --adapter pairb.harness_adapter:build --config belief.json --out DIR

The config is JSON, as for real_adapter:
    checkpoint      a best.pt written by scripts/train_belief_net.py (required)
    source_commit   the revision of this code the run is about, given by whoever runs it and never
                    guessed (required; recorded, not checked)
    device          "cpu", "mps" or "cuda"; null or missing lets pairb pick: cuda, then mps, then cpu
    stockfish_path  a command on the PATH or the path of the engine; "stockfish" if missing

The checkpoint is a network that also reads quick Stockfish's value, so the evaluator starts a Stockfish
process. The harness calls close() when it is done, even after a failed check, and that stops it.
"""
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

from pair_b_prep.adapter_example import make_turn

from .belief_data import ENCODING


def build(config: dict) -> SimpleNamespace:
    """The harness's bundle for the belief network described by `config`.

    KeyError for a missing checkpoint or source_commit, and FileNotFoundError for a missing Stockfish or
    checkpoint file. All of them come before the evaluator is built, so a bad config leaves no engine
    running.
    """
    checkpoint = Path(config["checkpoint"])
    source_commit = config["source_commit"]
    engine = shutil.which(config.get("stockfish_path", "stockfish"))
    if engine is None:
        raise FileNotFoundError("Stockfish not found; set stockfish_path or PATH")
    checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    # Imported here: belief_evaluator imports torch, and this module can be loaded without it.
    from .belief_evaluator import BeliefNetworkEvaluator
    # ucinewgame before every engine call, so no answer depends on an earlier one: the checks compare a
    # board scored alone with the same board scored in a batch.
    evaluator = BeliefNetworkEvaluator.from_checkpoint(
        checkpoint, stockfish_path=engine, device=config.get("device"), new_game_each_call=True)
    metadata = dict(demo_only=False, checkpoint_sha256=checkpoint_sha256, device=evaluator.device,
                    evaluator=evaluator.name, source_commit=source_commit, encoding=ENCODING)
    return SimpleNamespace(evaluator=evaluator, make_turn=make_turn, metadata=metadata, close=evaluator.close)
