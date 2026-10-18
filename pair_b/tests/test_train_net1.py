"""End-to-end run of scripts/train_net1.py on a tiny dataset (D3, and the D7 retrain command)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import torch

from pairb.data import read_records, split_of
from pairb.net1 import Network1

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("net1")
    data, out = tmp / "d2", tmp / "run"
    # 14 games: g-000002 and g-000005 fall in the validation split, g-000013 in the test split.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_d2.py"), "--games", "14", "--parents-per-game", "1",
                    "--max-plies", "30", "--label-depth", "3", "--workers", "2", "--out", str(data)],
                   check=True, capture_output=True, text=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "train_net1.py"), "--data", str(data), "--out", str(out),
                    "--blocks", "1", "--channels", "8", "--epochs", "2", "--batch", "64", "--device", "cpu",
                    "--cache-dir", str(tmp / "cache")],
                   check=True, capture_output=True, text=True)
    return data, out


# Catches: test-split games used for training or model selection, or training rows silently dropped.
def test_trains_on_exactly_the_train_and_validation_games(run):
    data, out = run
    summary = json.loads((out / "summary.json").read_text())
    usable = [r for r in read_records(data) if r["rule"] is None]
    games = {split: {r["game_id"] for r in usable if split_of(r["game_id"]) == split} for split in ("train", "val", "test")}
    assert games["test"], "the tiny dataset must contain a test game for this check to mean anything"
    used = json.loads((out / "splits.json").read_text())
    assert set(used["train"]) == games["train"] and set(used["val"]) == games["val"]
    assert summary["n"]["train"] == sum(split_of(r["game_id"]) == "train" for r in usable)
    assert summary["n"]["val"] == sum(split_of(r["game_id"]) == "val" for r in usable)


def test_reports_the_network_and_the_depth1_baseline_on_validation(run):
    _, out = run
    summary = json.loads((out / "summary.json").read_text())
    for key in ("val", "baseline"):
        assert 0 <= summary[key]["mae"] <= 2 and 0 <= summary[key]["mse"] <= 4
        assert 0 <= summary[key]["choice"]["top1"] <= 1 and summary[key]["choice"]["regret"] >= 0
    assert len((out / "metrics.jsonl").read_text().splitlines()) == 2


# Catches: a checkpoint that cannot be rebuilt into a working network (needed by D4 and D7).
def test_best_checkpoint_loads_into_a_network(run):
    _, out = run
    ckpt = torch.load(out / "best.pt", map_location="cpu")
    net = Network1(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    assert net(torch.zeros(2, 19, 8, 8), torch.tensor([0.1, -0.1])).shape == (2,)


def evaluate(run, split, *extra):
    data, out = run
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_net1.py"), "--run", str(out), "--data", str(data),
                           "--split", split, "--cache-dir", str(out.parent / "cache"), *extra],
                          capture_output=True, text=True)


def test_eval_compares_the_network_with_the_depth1_baseline_on_the_same_parents(run):
    _, out = run
    assert evaluate(run, "val").returncode == 0
    report = json.loads((out / "eval-d2-val.json").read_text())
    assert report["material"]["choice"]["parents"] == report["network"]["choice"]["parents"]
    assert report["regret_difference"]["games"] >= 1
    assert set(report) >= {"network", "baseline", "regret_difference", "split"}
    assert report["split"] == "val" and len(report["regret_difference"]["ci95"]) == 2
    assert report["network"]["choice"]["parents"] == report["baseline"]["choice"]["parents"]


# Catches: the test games being looked at during development by accident.
def test_eval_refuses_the_test_split_without_final(run):
    result = evaluate(run, "test")
    assert result.returncode != 0 and "--final" in result.stderr


# Catches: a network trained on different input planes being evaluated and silently misread.
def test_eval_refuses_a_checkpoint_for_other_input_planes(run):
    data, out = run
    other = out.parent / "other-run"
    other.mkdir(exist_ok=True)
    ckpt = torch.load(out / "best.pt", map_location="cpu")
    torch.save({**ckpt, "encoding": "other-planes"}, other / "best.pt")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_net1.py"), "--run", str(other), "--data", str(data),
                             "--split", "val", "--cache-dir", str(out.parent / "cache")], capture_output=True, text=True)
    assert result.returncode != 0 and "planes" in result.stderr
