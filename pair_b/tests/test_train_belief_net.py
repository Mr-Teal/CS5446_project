"""End-to-end runs of scripts/train_belief_net.py and eval_belief_net.py on a tiny dataset (D6).

The dataset needs no Stockfish: positions from seeded random games, beliefs from
pairb.standin_beliefs, labels from the piece-value evaluator, and "d1" a shifted copy of them.
"""
import json
import random
import subprocess
import sys
from pathlib import Path

import chess
import pytest
import torch

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


def tiny_dataset(folder: Path):
    folder.mkdir()
    rng, ev, records = random.Random(0), MaterialEvaluator(), []
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


# Catches: test games used for training, or beliefs and boards silently dropped.
def test_trains_on_exactly_the_train_and_validation_beliefs(run):
    _, out, records = run
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


# Catches: the test games being looked at during development by accident.
def test_eval_refuses_the_test_split_without_final(run):
    result = evaluate(run, "test")
    assert result.returncode != 0 and "--final" in result.stderr
