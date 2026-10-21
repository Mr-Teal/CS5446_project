"""End-to-end runs of scripts/train_belief_net.py and eval_belief_net.py on a tiny dataset (D6).

The dataset needs no Stockfish: positions from seeded random games, beliefs from
pairb.standin_beliefs, labels from the piece-value evaluator, and "d1" a shifted copy of them.
"""
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import chess
import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from fow_shared.recording import write_records
from pairb.belief_net import BeliefNetwork
from pairb.data import split_of
from pairb.material import MaterialEvaluator
from pairb.standin_beliefs import make_turn, record_for

ROOT = Path(__file__).resolve().parents[1]


def game_ids():
    """Five training games, two validation games and one test game."""
    want, found = {"train": 5, "val": 2, "test": 1}, []
    for i in range(1000):
        g = f"g-{i:06d}"
        if want[split_of(g)]:
            want[split_of(g)] -= 1
            found.append(g)
    return found


def tiny_dataset(folder: Path, drop_d1_in=None):
    """drop_d1_in: a split whose first belief loses its quick-Stockfish values."""
    folder.mkdir()
    rng, ev, records, dropped = random.Random(0), MaterialEvaluator(), [], False
    for g in game_ids():
        board = chess.Board()
        for ply in range(30):
            moves = list(board.legal_moves)
            if not moves or board.is_game_over():
                break
            board.push(rng.choice(moves))
            if ply % 10 == 9:
                turn = make_turn(board.copy(stack=False), random.Random(ply), n_hypotheses=4, ply=ply + 1)
                values = ev.evaluate_boards([h.fen for h in turn.belief.hypotheses], turn.observation.player)
                d1 = {f"d1:{i}": max(-1.0, min(1.0, v + 0.05)) for i, v in enumerate(values)}
                if split_of(g) == drop_d1_in and not dropped:
                    d1, dropped = {}, True
                records.append(record_for(turn, values, ply, g, "test-material", diagnostics=d1))
    write_records(folder / "part-00.jsonl", records)
    (folder / "manifest.json").write_text(json.dumps({"dataset": folder.name, "created": "2026-10-18", "records": len(records)}))
    return records


@pytest.fixture(scope="module", params=[[], ["--use-d1"]], ids=["pure", "with-d1"])
def run(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("belief")
    records = tiny_dataset(tmp / "d6")
    out = tmp / "run"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "train_belief_net.py"), "--data", str(tmp / "d6"),
                    "--out", str(out), "--blocks", "1", "--channels", "8", "--embed", "16", "--epochs", "2",
                    "--batch", "4", "--device", "cpu", "--workers", "1", "--cache-dir", str(tmp / "cache"),
                    *request.param], check=True, capture_output=True, text=True)
    return tmp / "d6", out, records


# Catches: test games used for training or model selection, or beliefs and boards silently dropped.
def test_trains_on_exactly_the_train_and_validation_beliefs(run):
    _, out, records = run
    used = json.loads((out / "splits.json").read_text())
    for split in ("train", "val"):
        assert set(used[split]) == {r.game_id for r in records if split_of(r.game_id) == split}
    assert any(split_of(r.game_id) == "test" for r in records)  # so the check means something
    n = json.loads((out / "summary.json").read_text())["n"]
    for split in ("train", "val"):
        mine = [r for r in records if split_of(r.game_id) == split]
        assert n[split] == {"beliefs": len(mine), "boards": sum(len(r.agent_input.belief.hypotheses) for r in mine)}
    assert n["test_held_out"]["beliefs"] == sum(split_of(r.game_id) == "test" for r in records)


def test_reports_the_network_and_quick_stockfish_on_validation(run):
    _, out, _ = run
    summary = json.loads((out / "summary.json").read_text())
    for key in ("val", "baseline"):
        assert 0 <= summary[key]["board_mae"] <= 2 and 0 <= summary[key]["root_mae"] <= 2
    assert len((out / "metrics.jsonl").read_text().splitlines()) == 2


# Catches: a checkpoint that cannot be rebuilt into a working network (the evaluator loads it).
def test_best_checkpoint_loads_into_a_network(run):
    _, out, _ = run
    ckpt = torch.load(out / "best.pt", map_location="cpu")
    net = BeliefNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    planes, weights, belief, d1 = torch.zeros(3, 32, 8, 8), torch.tensor([0.5, 0.5, 1.0]), torch.tensor([0, 0, 1]), torch.zeros(3)
    assert net.eval()(planes, weights, belief, 2, d1).shape == (3,)


def evaluate(run, split, *extra):
    data, out, _ = run
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_belief_net.py"), "--run", str(out),
                           "--data", str(data), "--split", split, "--device", "cpu", "--workers", "1",
                           "--cache-dir", str(out.parent / "cache"), *extra], capture_output=True, text=True)


def test_eval_compares_the_network_with_quick_stockfish_on_the_same_beliefs(run):
    _, out, _ = run
    assert evaluate(run, "val").returncode == 0
    report = json.loads((out / "eval-d6-val.json").read_text())
    assert report["split"] == "val" and report["network"]["beliefs"] == report["baseline"]["beliefs"] > 0
    assert len(report["root_mae_difference"]["ci95"]) == 2


# Catches: an evaluation that does not say which data, checkpoint, code, device and bootstrap
# made it (review T9).
def test_eval_reports_its_provenance(run):
    from pairb.provenance import data_source, git_commit
    data, out, _ = run
    assert evaluate(run, "val", "--n-boot", "200").returncode == 0
    report = json.loads((out / "eval-d6-val.json").read_text())
    assert report["bootstrap"] == {"resamples": 200, "seed": 0, "unit": "whole games"}
    assert report["device"] == "cpu" and report["runtime"]["torch"] == torch.__version__
    assert report["source"] == data_source(data)
    assert report["checkpoint_sha256"] == hashlib.sha256((out / "best.pt").read_bytes()).hexdigest()
    assert report["git_commit"] == git_commit()


# Catches: the test games being looked at during development by accident.
def test_eval_refuses_the_test_split_without_final(run):
    result = evaluate(run, "test")
    assert result.returncode != 0 and "--final" in result.stderr


def train(data, out, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "train_belief_net.py"), "--data", str(data),
                           "--out", str(out), "--blocks", "1", "--channels", "8", "--embed", "16", "--epochs", "1",
                           "--batch", "4", "--device", "cpu", "--workers", "1", "--cache-dir", str(out.parent / "cache"),
                           *extra], capture_output=True, text=True)


# Catches: a missing quick-Stockfish value silently fed to the network as 0 during training.
def test_training_with_d1_refuses_a_training_belief_without_quick_stockfish_values(tmp_path):
    tiny_dataset(tmp_path / "d6", drop_d1_in="train")
    result = train(tmp_path / "d6", tmp_path / "run", "--use-d1")
    assert result.returncode != 0 and "d1" in result.stderr


# Catches: the same during evaluation, where the network would be scored on made-up inputs.
def test_evaluating_a_d1_network_refuses_beliefs_without_quick_stockfish_values(tmp_path):
    tiny_dataset(tmp_path / "full")
    assert train(tmp_path / "full", tmp_path / "run", "--use-d1").returncode == 0
    tiny_dataset(tmp_path / "gappy", drop_d1_in="val")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_belief_net.py"), "--run", str(tmp_path / "run"),
                             "--data", str(tmp_path / "gappy"), "--split", "val", "--device", "cpu", "--workers", "1",
                             "--cache-dir", str(tmp_path / "cache")], capture_output=True, text=True)
    assert result.returncode != 0 and "d1" in result.stderr


# Catches: training that only works with every plane on the GPU, or steps that ignore the board cap.
def test_trains_with_planes_kept_on_the_host_and_steps_capped_by_boards(tmp_path):
    tiny_dataset(tmp_path / "d6")
    result = train(tmp_path / "d6", tmp_path / "run", "--planes-on", "host", "--max-boards", "6")
    assert result.returncode == 0, result.stderr[-500:]
    assert (tmp_path / "run" / "best.pt").exists()


# Catches: a trained belief network whose summary does not say which data files, checkpoint and
# code made it (review T9).
def test_summary_records_the_data_checkpoint_and_code_it_came_from(run):
    from pairb.provenance import data_source, git_commit
    data, out, _ = run
    summary = json.loads((out / "summary.json").read_text())
    assert summary["source"] == data_source(data)
    assert summary["checkpoint_sha256"] == hashlib.sha256((out / "best.pt").read_bytes()).hexdigest()
    assert summary["git_commit"] == git_commit()
    assert summary["runtime"]["torch"] == torch.__version__
