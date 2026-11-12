"""The policy network (stage 1): its data join, its mirrored targets, its two designs and a short training run.

The fixture needs no solver: positions from seeded random games, beliefs from pairb.standin_beliefs, and
afterstate-q-v1 rows with random action values and strategies over each record's legal moves.
"""
import json
import random
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import chess
import numpy as np
import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from fow_shared.recording import write_records
from pairb.belief_data import build_arrays
from pairb.data import split_of
from pairb.moves import N_MOVES, policy_vector
from pairb.policy_data import dense_targets, load_positions, move_position
from pairb.policy_net import PolicyNetwork
from pairb.standin_beliefs import make_turn, record_for

ROOT = Path(__file__).resolve().parents[1]


def game_ids():
    """Three training games, two validation games and one test game."""
    want, found = {"train": 3, "val": 2, "test": 1}, []
    for i in range(1000):
        g = f"g-{i:06d}"
        if want[split_of(g)]:
            want[split_of(g)] -= 1
            found.append(g)
    return found


def records_of():
    rng, records = random.Random(0), []
    for g in game_ids():
        board = chess.Board()
        for ply in range(24):
            moves = list(board.legal_moves)
            if not moves or board.is_game_over():
                break
            board.push(rng.choice(moves))
            if ply % 6 in (4, 5):  # both colours in every game
                turn = make_turn(board.copy(stack=False), random.Random(ply), n_hypotheses=4, ply=ply + 1)
                values = [0.0] * len(turn.belief.hypotheses)
                record = record_for(turn, values, ply, g, "test-policy")
                played = rng.choice(turn.observation.legal_moves)  # not always the first move, so alignment matters
                records.append(replace(record, decision=replace(record.decision, move=played)))
    return records


def row_for(record, seed, error=None):
    rng = np.random.default_rng(seed)
    obs, hyps = record.agent_input.observation, record.agent_input.belief.hypotheses
    n = len(obs.legal_moves)
    mean, last = rng.dirichlet(np.ones(n)), rng.dirichlet(np.full(n, 0.3))
    return {"schema": "afterstate-q-v1", "game_id": record.game_id, "ply": obs.ply, "player": obs.player,
            "split": split_of(record.game_id), "moves": list(obs.legal_moves), "weights": [h.weight for h in hyps],
            "action_values": rng.uniform(-1, 1, (len(hyps), n)).tolist(), "policy_last": last.tolist(),
            "policy_mean": mean.tolist(), "played": record.decision.move, "error": error}


def q_of(row):
    w = np.asarray(row["weights"]) / np.sum(row["weights"])
    return w @ np.asarray(row["action_values"])


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def fixture(tmp: Path, mutate=None):
    """Records in two part files; target rows in a training folder (with a decoy for each validation position,
    an earlier superseded row, an error row and a test row) and a validation folder. Returns the true rows."""
    records = records_of()
    (tmp / "records").mkdir()
    write_records(tmp / "records" / "part-00.jsonl", records[: len(records) // 2])
    write_records(tmp / "records" / "part-01.jsonl", records[len(records) // 2:])
    true = {(r.game_id, r.agent_input.observation.ply): row_for(r, i) for i, r in enumerate(records)
            if split_of(r.game_id) != "test"}
    if mutate:
        mutate(true)
    train_rows, val_rows = [], []
    for i, ((g, ply), row) in enumerate(true.items()):
        if row["split"] == "val":
            val_rows.append(row)
            train_rows.append({**row, "action_values": (-np.asarray(row["action_values"])).tolist()})  # decoy
        else:
            stale = {**row, "action_values": np.zeros_like(row["action_values"]).tolist()}
            train_rows += [stale, row, {**stale, "error": "solver crashed"}]  # later good row wins, error ignored
    test = next(r for r in records if split_of(r.game_id) == "test")
    train_rows.append(row_for(test, 99))
    write_rows(tmp / "t-train" / "resolve-0-of-1.jsonl", train_rows)
    write_rows(tmp / "t-val" / "resolve-0-of-1.jsonl", val_rows)
    return records, true


def load(tmp):
    return load_positions(tmp / "records", [tmp / "t-train"], tmp / "t-val", tmp / "cache", workers=1)


# Catches: targets attached to the wrong position or move, validation rows taken from the training folders,
# error or superseded rows used, and test games encoded at all.
def test_join_aligns_moves_and_rows_and_skips_the_test_split(tmp_path):
    records, true = fixture(tmp_path)
    a = load(tmp_path)
    counts = json.loads(str(a["counts"]))
    test_records = [r for r in records if split_of(r.game_id) == "test"]
    assert test_records and counts["test_games_skipped"] == 1 and counts["test_records_skipped"] == len(test_records)
    assert counts["train_folders_test_rows_skipped"] == 1 and counts["train_folders_error_rows"] > 0
    assert len(a["game_id"]) == len(true) and not any(split_of(g) == "test" for g in a["game_id"])
    kept = build_arrays([r for r in records if split_of(r.game_id) != "test"])  # the value network's encoding
    np.testing.assert_array_equal(a["planes"], kept["planes"])
    np.testing.assert_array_equal(a["weight"], kept["weight"])
    np.testing.assert_array_equal(a["belief"], kept["belief"])
    starts = a["move_start"]
    for i, (g, ply) in enumerate(zip(a["game_id"], a["ply"])):
        row = true[(g, int(ply))]
        s, e = starts[i], starts[i + 1]
        assert a["move"][s:e].tolist() == row["moves"]
        assert a["move"][s + a["played"][i]] == row["played"]
        np.testing.assert_allclose(a["q"][s:e], q_of(row))
        np.testing.assert_allclose(a["mean"][s:e], row["policy_mean"])
        assert a["split"][i] == split_of(g)


@pytest.mark.parametrize("change, match", [
    (lambda row: row["moves"].reverse(), "moves differ"),
    (lambda row: row.update(played=next(m for m in row["moves"] if m != row["played"])), "played"),
])
def test_a_misaligned_row_is_refused(tmp_path, change, match):
    def mutate(true):
        change(next(iter(true.values())))
    fixture(tmp_path, mutate)
    with pytest.raises(ValueError, match=match):
        load(tmp_path)


# Catches: a target mirrored differently from the legal mask (Black's moves flipped one way, its mask another).
def test_mirrored_targets_sit_on_legal_slots_and_sum_to_one_for_both_colours(tmp_path):
    _, true = fixture(tmp_path)
    a = load(tmp_path)
    assert set(a["player"].tolist()) == {"white", "black"}
    for kind, field in (("mean", "policy_mean"), ("last", "policy_last")):
        dense = dense_targets(a, kind)
        assert (dense[~a["legal"]] == 0).all()
        np.testing.assert_allclose(dense.sum(1), 1.0, atol=1e-6)
        for i, (g, ply) in enumerate(zip(a["game_id"], a["ply"])):
            row = true[(g, int(ply))]
            np.testing.assert_allclose(dense[i], policy_vector(dict(zip(row["moves"], row[field])), a["player"][i]), atol=1e-7)
    some = np.array([2, 0])
    np.testing.assert_array_equal(dense_targets(a, "mean", some), dense_targets(a, "mean")[some])
    assert len(move_position(a)) == len(a["move"])


def nudged(design):
    torch.manual_seed(0)
    m = PolicyNetwork(design, blocks=1, channels=8, embed=16, hidden=32)
    with torch.no_grad():
        for p in m.parameters():
            p.add_(0.1 * torch.randn_like(p))
    return m.eval()


def two_beliefs():
    torch.manual_seed(1)
    planes = torch.rand(5, 32, 8, 8)
    weights = torch.tensor([0.5, 0.25, 0.25, 0.6, 0.4])
    belief = torch.tensor([0, 0, 0, 1, 1])
    legal = torch.zeros(2, N_MOVES, dtype=torch.bool)
    legal[0, [3, 70, 500, 4000]] = True
    legal[1, [9, 1000]] = True
    return planes, weights, belief, legal


# Catches: a pooled network that answers per board, leaks probability onto illegal slots, or depends on the
# order in which a belief's boards arrive.
def test_pooled_gives_one_legal_distribution_per_belief_whatever_the_board_order():
    planes, weights, belief, legal = two_beliefs()
    m = nudged("pooled")
    p = m.belief_probs(planes, weights, belief, 2, legal)
    assert p.shape == (2, N_MOVES) and m(planes, weights, belief, 2, legal).shape == (2, N_MOVES)
    assert torch.allclose(p.sum(1), torch.ones(2), atol=1e-6) and (p[~legal] == 0).all()
    order = torch.tensor([2, 0, 1, 4, 3])
    assert torch.allclose(m.belief_probs(planes[order], weights[order], belief[order], 2, legal), p, atol=1e-6)
    assert torch.allclose(m.belief_probs(planes, 3 * weights, belief, 2, legal), p, atol=1e-6)  # weights normalised


# Catches: per-board boards influencing each other, or a belief distribution other than the weighted mean of
# each board's own softmax.
def test_per_board_belief_distribution_is_the_weight_averaged_softmax_of_its_boards():
    planes, weights, belief, legal = two_beliefs()
    m = nudged("per-board")
    raw = 2 * weights  # not normalised: the network must normalise within each belief
    alone = torch.stack([m.belief_probs(planes[i:i + 1], raw[i:i + 1], torch.zeros(1, dtype=torch.long), 1,
                                        legal[belief[i]][None])[0] for i in range(5)])
    w = weights  # raw, normalised within each belief
    expect = torch.stack([(w[:3, None] * alone[:3]).sum(0), (w[3:, None] * alone[3:]).sum(0)])
    assert torch.allclose(m.belief_probs(planes, raw, belief, 2, legal), expect, atol=1e-6)
    assert m(planes, raw, belief, 2, legal).shape == (5, N_MOVES)


@pytest.mark.parametrize("design", ["pooled", "per-board"])
def test_a_two_epoch_run_trains_on_train_and_validation_positions_only(tmp_path, design):
    records, true = fixture(tmp_path)
    out = tmp_path / "run"
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "train_policy_net.py"), "--design", design,
                           "--target", "mean", "--out", str(out), "--records", str(tmp_path / "records"),
                           "--train-targets", str(tmp_path / "t-train"), "--val-targets", str(tmp_path / "t-val"),
                           "--cache-dir", str(tmp_path / "cache"), "--blocks", "1", "--channels", "8", "--embed", "16",
                           "--hidden", "32", "--epochs", "2", "--patience", "5", "--batch", "4", "--device", "cpu",
                           "--workers", "1"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "test games skipped: 1" in done.stdout
    assert len((out / "metrics.jsonl").read_text().splitlines()) == 2
    summary = json.loads((out / "summary.json").read_text())
    for split in ("train", "val"):
        assert summary["n"][split]["positions"] == sum(row["split"] == split for row in true.values())
    assert 1 <= summary["best_epoch"] <= 2 and summary["val"]["val_ce"] > 0
    ckpt = torch.load(out / "best.pt", map_location="cpu", weights_only=True)
    net = PolicyNetwork(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    planes, weights, belief, legal = two_beliefs()
    assert torch.allclose(net.eval().belief_probs(planes, weights, belief, 2, legal).sum(1), torch.ones(2), atol=1e-5)
