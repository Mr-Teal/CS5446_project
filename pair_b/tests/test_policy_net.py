"""The policy network: its data join, its mirrored targets, its two designs and a short training run (stage 1);
label sets covering a subset of the positions in one folder, and the metrics against a mixing teacher (stage 2).

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
from pairb.moves import N_MOVES, legal_mask, move_index, policy_vector
from pairb.policy_data import dense_targets, game_subset, load_positions, move_position
from pairb.policy_metrics import label_kinds, pure_teacher_metrics, teacher_metrics, uniform_teacher_metrics
from pairb.policy_net import MOVE_TYPES, PolicyNetwork, conv_slots
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
@pytest.mark.parametrize("design", ["pooled", "pooled-conv"])
def test_pooled_gives_one_legal_distribution_per_belief_whatever_the_board_order(design):
    planes, weights, belief, legal = two_beliefs()
    m = nudged(design)
    p = m.belief_probs(planes, weights, belief, 2, legal)
    assert p.shape == (2, N_MOVES) and m(planes, weights, belief, 2, legal).shape == (2, N_MOVES)
    assert torch.allclose(p.sum(1), torch.ones(2), atol=1e-6) and (p[~legal] == 0).all()
    order = torch.tensor([2, 0, 1, 4, 3])
    assert torch.allclose(m.belief_probs(planes[order], weights[order], belief[order], 2, legal), p, atol=1e-6)
    assert torch.allclose(m.belief_probs(planes, 3 * weights, belief, 2, legal), p, atol=1e-6)  # weights normalised


# Catches: per-board boards influencing each other, or a belief distribution other than the weighted mean of
# each board's own softmax.
@pytest.mark.parametrize("design", ["per-board", "per-board-conv"])
def test_per_board_belief_distribution_is_the_weight_averaged_softmax_of_its_boards(design):
    planes, weights, belief, legal = two_beliefs()
    m = nudged(design)
    raw = 2 * weights  # not normalised: the network must normalise within each belief
    alone = torch.stack([m.belief_probs(planes[i:i + 1], raw[i:i + 1], torch.zeros(1, dtype=torch.long), 1,
                                        legal[belief[i]][None])[0] for i in range(5)])
    w = weights  # raw, normalised within each belief
    expect = torch.stack([(w[:3, None] * alone[:3]).sum(0), (w[3:, None] * alone[3:]).sum(0)])
    assert torch.allclose(m.belief_probs(planes, raw, belief, 2, legal), expect, atol=1e-6)
    assert m(planes, raw, belief, 2, legal).shape == (5, N_MOVES)


@pytest.mark.parametrize("design", ["pooled", "per-board", "pooled-conv"])
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


def subset_fixture(tmp: Path):
    """Records as above; one folder holding rows of both splits for every second training and validation record
    (validation rows carry a purification test, training rows a null one), one validation position whose only row
    is an error row, and a test row. Returns the records and the good rows by key."""
    records = records_of()
    (tmp / "records").mkdir()
    write_records(tmp / "records" / "part-00.jsonl", records)
    kept = [r for r in records if split_of(r.game_id) != "test"][::2]
    good = {}
    for i, r in enumerate(kept):
        row = row_for(r, i)
        row["purify_loss"] = (0.02 if i % 4 == 0 else 0.0) if row["split"] == "val" else None
        good[(r.game_id, r.agent_input.observation.ply)] = row
    errored = next(r for r in records if split_of(r.game_id) == "val" and (r.game_id, r.agent_input.observation.ply) not in good)
    rows = list(good.values()) + [{**row_for(errored, 50), "action_values": None, "error": "solver crashed"},
                                  row_for(next(r for r in records if split_of(r.game_id) == "test"), 99)]
    write_rows(tmp / "labels" / "resolve-0-of-1.jsonl", rows)
    return records, good


# Catches: a label set covering part of the positions refused (or silently padded), the wrong positions kept, the
# skipped ones not counted per split, and the purification test lost or invented.
def test_subset_keeps_exactly_the_positions_with_a_good_row_from_one_folder_of_both_splits(tmp_path):
    records, good = subset_fixture(tmp_path)
    with pytest.raises(ValueError, match="no good target row"):
        load_positions(tmp_path / "records", [tmp_path / "labels"], None, tmp_path / "cache", workers=1)
    a = load_positions(tmp_path / "records", [tmp_path / "labels"], None, tmp_path / "cache", workers=1, subset=True)
    assert {(g, int(p)) for g, p in zip(a["game_id"], a["ply"])} == set(good)
    assert set(a["split"].tolist()) == {"train", "val"}
    counts = json.loads(str(a["counts"]))
    for s in ("train", "val"):
        n = sum(split_of(r.game_id) == s for r in records)
        assert counts[f"{s}_positions_without_good_row_skipped"] == n - sum(row["split"] == s for row in good.values())
    assert counts["targets_error_rows_val"] == 1 and counts["targets_test_rows_skipped"] == 1
    assert counts["test_games_skipped"] == 1
    for i, (g, p) in enumerate(zip(a["game_id"], a["ply"])):
        row = good[(g, int(p))]
        if row["purify_loss"] is None:
            assert np.isnan(a["purify"][i])
        else:
            assert a["purify"][i] == row["purify_loss"]
        np.testing.assert_allclose(a["q"][a["move_start"][i]:a["move_start"][i + 1]], q_of(row))
    kinds = label_kinds(a, np.arange(len(a["game_id"])))
    assert kinds["mixing_works"].tolist() == [bool(row["purify_loss"]) for row in
                                              (good[(g, int(p))] for g, p in zip(a["game_id"], a["ply"]))]


# Catches: a row whose split field disagrees with its game's split (a validation game trained on).
def test_a_row_with_the_wrong_split_is_refused(tmp_path):
    _, good = subset_fixture(tmp_path)
    rows = [{**row, "split": "train" if row["split"] == "val" else row["split"]} for row in good.values()]
    write_rows(tmp_path / "labels" / "resolve-0-of-1.jsonl", rows)
    with pytest.raises(ValueError, match="split"):
        load_positions(tmp_path / "records", [tmp_path / "labels"], None, tmp_path / "cache", workers=1, subset=True)


def test_a_two_epoch_run_on_a_subset_label_folder(tmp_path):
    _, good = subset_fixture(tmp_path)
    out = tmp_path / "run"
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "train_policy_net.py"), "--design", "pooled",
                           "--target", "last", "--out", str(out), "--records", str(tmp_path / "records"),
                           "--targets", str(tmp_path / "labels"), "--subset", "--cache-dir", str(tmp_path / "cache"),
                           "--blocks", "1", "--channels", "8", "--embed", "16", "--hidden", "32", "--epochs", "2",
                           "--batch", "4", "--device", "cpu", "--workers", "1"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "positions without a good row skipped: train" in done.stdout
    summary = json.loads((out / "summary.json").read_text())
    for split in ("train", "val"):
        assert summary["n"][split]["positions"] == sum(row["split"] == split for row in good.values())


# Catches: metrics that reward the wrong thing: support counted from the prediction instead of the teacher, a top
# move taken from the teacher, total variation off by the factor 1/2.
def test_teacher_metrics_on_hand_computed_cases():
    teacher = np.zeros((2, N_MOVES))
    teacher[:, [0, 1]] = [0.6, 0.4]
    teacher[1, 5] = 0.005  # below the support threshold
    teacher[1, :2] = [0.6, 0.395]
    probs = np.zeros((2, N_MOVES))
    probs[0, [0, 1, 2]] = [0.5, 0.1, 0.4]
    probs[1, [0, 1, 5]] = [0.2, 0.1, 0.7]
    m = teacher_metrics(probs, teacher)
    np.testing.assert_allclose(m["ce_teacher"][0], -(0.6 * np.log(0.5) + 0.4 * np.log(0.1)))
    np.testing.assert_allclose(m["tv_teacher"], [0.4, 0.5 * (0.4 + 0.295 + 0.695)])
    np.testing.assert_allclose(m["mass_on_support"], [0.6, 0.3])
    assert m["top_in_support"].tolist() == [1.0, 0.0]
    pure = pure_teacher_metrics(np.array([1, 5]), teacher)
    np.testing.assert_allclose(pure["tv_teacher"], [0.6, 0.995])
    assert pure["top_in_support"].tolist() == [1.0, 0.0] and pure["mass_on_support"].tolist() == [1.0, 0.0]
    legal = np.zeros((2, N_MOVES), dtype=bool)
    legal[:, :4] = True
    legal[1, 5] = True
    uni = uniform_teacher_metrics(legal, teacher)
    np.testing.assert_allclose(uni["mass_on_support"], [0.5, 0.4])
    np.testing.assert_allclose(uni["top_in_support"], [0.5, 0.4])
    np.testing.assert_allclose(uni["ce_teacher"], [np.log(4), np.log(5)])
    np.testing.assert_allclose(uni["tv_teacher"][0], 0.5 * (0.35 + 0.15 + 0.25 + 0.25))


# Catches: one-hot and genuinely mixed labels told apart by the wrong field or threshold, or a missing
# purification test counted as mixing.
def test_label_kinds_use_the_top_probability_and_the_purification_loss():
    arrays = {"move_start": np.array([0, 2, 4, 6]), "last": np.array([0.9995, 0.0005, 0.6, 0.4, 0.5, 0.5]),
              "purify": np.array([0.0, 0.02, np.nan])}
    kinds = label_kinds(arrays, np.array([0, 1, 2]))
    assert kinds["one_hot"].tolist() == [True, False, False]
    assert kinds["mixing_works"].tolist() == [False, True, False]


# Catches: a position labelled twice across a shard's part files (one solve silently replacing another) when the
# label set is meant to hold each position once.
def test_unique_refuses_a_position_that_appears_twice_across_part_files(tmp_path):
    _, good = subset_fixture(tmp_path)
    again = next(iter(good.values()))
    write_rows(tmp_path / "labels" / "resolve-0-of-1-p0.jsonl", [{**again, "error": "solver crashed"}])
    args = (tmp_path / "records", [tmp_path / "labels"], None, tmp_path / "cache")
    with pytest.raises(ValueError, match="appears twice"):
        load_positions(*args, workers=1, subset=True, unique=True)
    assert len(load_positions(*args, workers=1, subset=True)["game_id"]) == len(good)  # default: the good row stays


def train(tmp: Path, out: Path, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "train_policy_net.py"), "--design", "pooled",
                           "--target", "last", "--out", str(out), "--records", str(tmp / "records"),
                           "--targets", str(tmp / "labels"), "--subset", "--unique", "--cache-dir", str(tmp / "cache"),
                           "--blocks", "1", "--channels", "8", "--embed", "16", "--hidden", "32", "--batch", "4",
                           "--device", "cpu", "--workers", "1", *extra], capture_output=True, text=True)


# Catches: --init ignored (fine-tuning silently from scratch), a checkpoint of another design or size accepted, or
# the starting checkpoint missing from the run's record.
def test_init_starts_from_the_checkpoint_and_refuses_a_mismatch(tmp_path):
    subset_fixture(tmp_path)
    base = tmp_path / "base"
    assert train(tmp_path, base, "--epochs", "2").returncode == 0
    ckpt = torch.load(base / "best.pt", map_location="cpu", weights_only=True)
    done = train(tmp_path, tmp_path / "ft", "--epochs", "1", "--lr", "3e-4", "--init", str(base / "best.pt"))
    assert done.returncode == 0, done.stderr
    first = json.loads((tmp_path / "ft" / "metrics.jsonl").read_text().splitlines()[0])
    assert first["epoch"] == 0 and first["val_ce_last"] == pytest.approx(ckpt["val"]["val_ce"], abs=1e-5)
    summary = json.loads((tmp_path / "ft" / "summary.json").read_text())
    assert summary["init"]["checkpoint"] == str(base / "best.pt") and summary["init"]["epoch"] == ckpt["epoch"]
    assert summary["init"]["sha256"] == json.loads((base / "summary.json").read_text())["checkpoint_sha256"]
    assert summary["best_epoch"] == 1  # epoch 0 is logged, never kept as the run's own result
    wrong = train(tmp_path, tmp_path / "wrong", "--epochs", "1", "--hidden", "16", "--init", str(base / "best.pt"))
    assert wrong.returncode != 0 and "do not match" in wrong.stderr and not (tmp_path / "wrong").exists()


def every_chess_move_slot() -> set:
    """The slot of every from-to pair any chess move can make, for both colours: queen and knight moves from every
    square of an empty board (rook, bishop, king and pawn moves, promotions included, are queen moves), and
    castling."""
    slots = set()
    for player in ("white", "black"):
        for square in chess.SQUARES:
            for piece in (chess.QUEEN, chess.KNIGHT):
                board = chess.Board(None)
                board.set_piece_at(square, chess.Piece(piece, chess.WHITE))
                for target in board.attacks(square):
                    slots.add(move_index(chess.square_name(square) + chess.square_name(target), player))
        for uci in ("e1g1", "e1c1", "e8g8", "e8c8"):
            slots.add(move_index(uci, player))
    return slots


# Catches: a convolutional output that cannot express some legal move (a missing or off-by-one offset, a frame
# that is not the mirrored one), or one that writes two logits into the same slot.
def test_the_convolutional_output_reaches_every_move_slot_exactly_once():
    src, dst = conv_slots()
    assert len(MOVE_TYPES) == 64 and len(set(MOVE_TYPES)) == 64
    assert len(set(src.tolist())) == len(src) and len(set(dst.tolist())) == len(dst)
    assert set(dst.tolist()) == every_chess_move_slot()  # 1,456 queen and 336 knight from-to pairs, nothing else
    rng = random.Random(3)
    for _ in range(20):  # legal moves of real positions, both colours, through pairb.moves' own mask
        board = chess.Board()
        for _ in range(rng.randrange(1, 60)):
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
        player = "white" if board.turn == chess.WHITE else "black"
        legal = legal_mask([m.uci() for m in board.legal_moves], player)
        assert set(np.flatnonzero(legal).tolist()) <= set(dst.tolist())


# Catches: learning-curve subsets that are not nested (a 25 % run seeing games the 50 % run lacks) or not the
# share asked for.
def test_game_subsets_are_nested_and_of_the_asked_size():
    games = [f"g-{i:06d}" for i in range(392)]
    quarter, half, everything = (game_subset(games, f) for f in (0.25, 0.5, 1.0))
    assert len(quarter) == 98 and len(half) == 196 and everything == set(games)
    assert quarter <= half <= everything and game_subset(list(reversed(games)), 0.25) == quarter
    with pytest.raises(ValueError):
        game_subset(games, 0)


def test_train_fraction_trains_on_a_share_of_the_training_games_only(tmp_path):
    _, good = subset_fixture(tmp_path)
    done = train(tmp_path, tmp_path / "half", "--epochs", "1", "--train-fraction", "0.5")
    assert done.returncode == 0, done.stderr
    n = json.loads((tmp_path / "half" / "summary.json").read_text())["n"]
    train_games = {g for (g, _), row in good.items() if row["split"] == "train"}
    assert n["train"]["games"] == len(game_subset(train_games, 0.5)) < len(train_games)
    assert n["val"]["positions"] == sum(row["split"] == "val" for row in good.values())
