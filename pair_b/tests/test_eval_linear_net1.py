"""scripts/eval_linear.py --net1-run: Network 1 scored on the linear correction's rows (needs torch)."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from pairb.data import ENCODING
from pairb.linear import LinearCorrection
from pairb.linear_workflow import load_dataset, mask_split, metrics, train, value_error_difference
from pairb.metrics import paired_regret_difference
from pairb.net1 import D1_CLIP, Network1
from test_linear_workflow import dataset

ROOT = Path(__file__).resolve().parents[2]
BIAS = 0.5  # the tiny network's last layer has zero weights, so it returns tanh(atanh(d1) + BIAS)
N_BOOT = 50


def close(got, want, tol=1e-6):
    """got == want, but floats (also inside dicts and lists) only to within tol."""
    if isinstance(want, dict):
        return got.keys() == want.keys() and all(close(got[k], want[k], tol) for k in want)
    if isinstance(want, list):
        return len(got) == len(want) and all(close(g, w, tol) for g, w in zip(got, want))
    return abs(got - want) <= tol if isinstance(want, float) else got == want


def eval_linear(*args):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "pair_b" / "src"), str(ROOT)])}
    return subprocess.run([sys.executable, str(ROOT / "pair_b" / "scripts" / "eval_linear.py"), *map(str, args)],
                          env=env, text=True, capture_output=True)


@pytest.fixture
def runs(tmp_path):
    """A linear run and a tiny Network 1 checkpoint (the format train_net1.py saves) on the fixture data."""
    dataset(tmp_path / "data")
    train(tmp_path / "data", tmp_path / "linear", [0.01])
    net = Network1(blocks=1, channels=8)
    torch.nn.init.constant_(net.fc2.bias, BIAS)
    (tmp_path / "net1").mkdir()
    torch.save({"encoding": ENCODING, "config": net.config, "state_dict": net.state_dict()},
               tmp_path / "net1" / "best.pt")
    return tmp_path


# Catches: the path that wrote the committed comparison breaking unseen where torch is missing:
# Network 1 scored on other rows or with the wrong depth-1 input, its paired differences against
# the linear correction wrong, or its split evidence ignored.
def test_network_1_is_scored_on_the_linear_rows_with_its_split_evidence(runs):
    splits = json.loads((runs / "linear" / "splits.json").read_text())
    (runs / "same.json").write_text(json.dumps({"train": splits["train"], "val": splits["val"]}))
    common = ["--run", runs / "linear", "--data", runs / "data", "--split", "test", "--final",
              "--n-boot", N_BOOT, "--net1-run", runs / "net1"]
    done = eval_linear(*common, "--net1-splits", runs / "same.json", "--out", runs / "eval.json")
    assert done.returncode == 0, done.stderr
    report = json.loads((runs / "eval.json").read_text())

    arrays, _ = load_dataset(runs / "data")
    data = mask_split(arrays, "test")
    d1 = torch.from_numpy(data["d1"]).clamp(-D1_CLIP, D1_CLIP)
    network = torch.tanh(torch.atanh(d1) + BIAS).numpy()
    linear = LinearCorrection.load(runs / "linear" / "best.npz").predict(data["planes"], data["d1"], packed=True)
    assert close(report["network"], metrics(network, data))
    assert report["network"]["mae"] != pytest.approx(report["baseline"]["mae"])  # not the depth-1 value again
    assert close(report["linear_minus_network_regret"],
                 paired_regret_difference(data["parent"], linear, network, data["y"], games=data["game_id"],
                                          n_boot=N_BOOT))
    difference = report["linear_minus_network_mae"]
    assert close(difference, value_error_difference(linear, network, data, N_BOOT))
    assert difference["mean"] == pytest.approx(report["linear"]["mae"] - report["network"]["mae"], abs=1e-6)
    assert difference["positions"] == report["n"] and difference["games"] == report["games"]
    assert report["network_checkpoint_sha256"] == hashlib.sha256((runs / "net1" / "best.pt").read_bytes()).hexdigest()
    evidence = report["network_split_evidence"]
    assert evidence["same_games_as_linear"] and evidence["independent_games"]
    assert evidence["overlaps"] == {"train": 0, "val": 0} and evidence["overlap_basis"] == "game_id"
    assert evidence["splits_sha256"] == hashlib.sha256((runs / "same.json").read_bytes()).hexdigest()

    # Network 1 trained on the evaluated games: its split file says so, and the guard stops the run.
    (runs / "seen.json").write_text(json.dumps({"train": sorted(set(data["game_id"].tolist())), "val": []}))
    refused = eval_linear(*common, "--net1-splits", runs / "seen.json", "--out", runs / "refused.json")
    assert refused.returncode != 0 and "Network 1 evaluation overlaps" in refused.stderr
    assert not (runs / "refused.json").exists()
    allowed = eval_linear(*common, "--net1-splits", runs / "seen.json", "--allow-seen-games",
                          "--out", runs / "allowed.json")
    assert allowed.returncode == 0, allowed.stderr
    evidence = json.loads((runs / "allowed.json").read_text())["network_split_evidence"]
    assert not evidence["same_games_as_linear"] and not evidence["independent_games"]
    assert evidence["overlaps"] == {"train": report["games"], "val": 0}
