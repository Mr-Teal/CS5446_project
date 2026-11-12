"""Policy network data (stage 1): label records joined with the re-solve's move targets.

A position is one label record (fow_shared TrainingRecord) of a training or validation game. Its belief is
encoded exactly as pairb.belief_data.build_arrays encodes it (the shared planes, float16, normalised weights),
its legal moves in the mirrored move frame of pairb.moves, and from its afterstate-q-v1 row (a re-solve of the
same stored position) come the solver's average strategy (policy_mean), its last iteration (policy_last) and
Q*, the solver's value of each move for the whole belief: sum over boards of normalised weight x action_values.
Test-split games are skipped before anything is encoded or joined, and only counted.

Rows join records by (game_id, ply). Rows with an error are ignored and a later good row wins (folders in the
order given, files by name). Validation positions take their row from the validation folder only. Every joined
row must list the record's legal moves in the same order, its played move, player, split and weights.

Arrays (N positions, H boards, M moves over all positions):
  planes (H, 32, 8, 8) float16, weight (H,), belief (H,) position index of each board, sorted;
  game_id, player ("white"/"black"), split (N,), ply (N,), legal (N, 4096) bool, played (N,) index of the
  played move within the position's moves; move_start (N + 1,) offsets into the move arrays move (M,) UCI,
  slot (M,) pairb.moves slot, q, mean, last (M,); counts (JSON text).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from fow_shared.features import encode_belief
from fow_shared.recording import read_records

from .belief_data import ENCODING, opponent_visible
from .data import split_of
from .moves import N_MOVES, legal_mask, move_index, policy_vector

SCHEMA = "afterstate-q-v1"
CACHE_VERSION = 1
TARGETS = ("mean", "last")  # average strategy (policy_mean), last iteration (policy_last)


def _reduce(row: dict) -> dict:
    """What training and evaluation read from a good row; Q* replaces the per-board action values."""
    w = np.asarray(row["weights"], dtype=np.float64)
    values = np.asarray(row["action_values"], dtype=np.float64)
    if values.shape != (len(w), len(row["moves"])):
        raise ValueError(f"{row['game_id']} ply {row['ply']}: action_values {values.shape}, "
                         f"{len(w)} weights, {len(row['moves'])} moves")
    w = w / w.sum()
    return {"moves": list(row["moves"]), "played": row["played"], "player": row["player"], "split": row["split"],
            "weights": w, "q": w @ values, "mean": np.asarray(row["policy_mean"], dtype=np.float64),
            "last": np.asarray(row["policy_last"], dtype=np.float64)}


def read_target_rows(folders) -> tuple[dict, Counter]:
    """The good rows of each folder's resolve-*.jsonl, by (game_id, ply); a later good row replaces an earlier
    one. Rows of test games are skipped (counted, never kept)."""
    rows, counts = {}, Counter()
    for folder in folders:
        for path in sorted(Path(folder).glob("resolve-*.jsonl")):
            with open(path, encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    counts["lines"] += 1
                    if split_of(row["game_id"]) == "test":
                        counts["test_rows_skipped"] += 1
                        continue
                    if row.get("schema") != SCHEMA:
                        raise ValueError(f"{path}: schema {row.get('schema')!r}, expected {SCHEMA!r}")
                    if row.get("error") is not None:
                        counts["error_rows"] += 1
                        continue
                    key = (row["game_id"], int(row["ply"]))
                    counts["replaced_rows"] += key in rows
                    rows[key] = _reduce(row)
    return rows, counts


def _encode_part(path) -> dict:
    """Planes and facts of one record file's training and validation records; test records only counted."""
    planes, weight, size, facts = [], [], [], []
    test_games, test_records = set(), 0
    for r in read_records(path):
        if not r.game_id:
            raise ValueError(f"{path}: a record without game_id cannot be split")
        if split_of(r.game_id) == "test":
            test_games.add(r.game_id)
            test_records += 1
            continue
        p, w = encode_belief(r.agent_input, opponent_visible)
        obs = r.agent_input.observation
        planes.append(p.astype(np.float16))
        weight.append(w.astype(np.float32))
        size.append(len(w))
        facts.append((r.game_id, obs.ply, obs.player, list(obs.legal_moves), r.decision.move))
    return {"planes": np.concatenate(planes) if planes else np.zeros((0, 32, 8, 8), np.float16),
            "weight": np.concatenate(weight) if weight else np.zeros(0, np.float32),
            "size": size, "facts": facts, "test_games": test_games, "test_records": test_records}


def build_positions(records, train_targets, val_targets, workers: int = 6, pattern: str = "part-*.jsonl") -> dict:
    parts = sorted(Path(records).glob(pattern))
    if not parts:
        raise ValueError(f"no record files in {records} matching {pattern!r}")
    if workers > 1 and len(parts) > 1:
        with Pool(min(workers, len(parts))) as pool:
            pieces = list(pool.imap(_encode_part, parts))
    else:
        pieces = [_encode_part(p) for p in parts]
    planes = np.concatenate([p.pop("planes") for p in pieces])
    weight = np.concatenate([p.pop("weight") for p in pieces])
    sizes = [n for p in pieces for n in p["size"]]
    facts = [f for p in pieces for f in p["facts"]]
    test_games = set().union(*(p["test_games"] for p in pieces))
    counts = Counter({"record_files": len(parts), "test_games_skipped": len(test_games),
                      "test_records_skipped": sum(p["test_records"] for p in pieces)})
    del pieces

    train_rows, train_counts = read_target_rows(train_targets)
    val_rows, val_counts = read_target_rows([val_targets])
    for name, c in (("train_folders", train_counts), ("val_folder", val_counts)):
        for k, v in c.items():
            counts[f"{name}_{k}"] = v

    n = len(facts)
    legal = np.zeros((n, N_MOVES), dtype=bool)
    player = np.empty(n, dtype="U5")
    split = np.empty(n, dtype="U5")
    played = np.zeros(n, dtype=np.int64)
    move_start = np.zeros(n + 1, dtype=np.int64)
    move, slot, q, mean, last = [], [], [], [], []
    offset = 0
    for i, (game, ply, colour, legal_moves, played_move) in enumerate(facts):
        s = split_of(game)
        row = (val_rows if s == "val" else train_rows).pop((game, ply), None)
        where = f"{game} ply {ply}"
        if row is None:
            raise ValueError(f"{where} ({s}): no good target row")
        if row["moves"] != legal_moves:
            raise ValueError(f"{where}: row moves differ from the record's legal_moves")
        if row["played"] != played_move:
            raise ValueError(f"{where}: row played {row['played']}, record decision.move {played_move}")
        if row["player"] != colour or row["split"] != s:
            raise ValueError(f"{where}: row player/split {row['player']}/{row['split']}, record {colour}/{s}")
        w = weight[offset:offset + sizes[i]]
        if len(row["weights"]) != len(w) or not np.allclose(row["weights"], w, atol=1e-5):
            raise ValueError(f"{where}: row weights differ from the record's hypothesis weights")
        offset += sizes[i]
        legal[i] = legal_mask(legal_moves, colour)
        for kind in TARGETS:  # the check the stage asks for: mirrored targets live on legal slots, sum to 1
            vec = policy_vector(dict(zip(legal_moves, row[kind])), colour)
            if (row[kind] < 0).any() or vec[~legal[i]].any() or abs(vec.sum() - 1.0) > 1e-6:
                raise ValueError(f"{where}: {kind} target is not a distribution on the legal slots")
        player[i], split[i] = colour, s
        played[i] = legal_moves.index(played_move)
        move_start[i + 1] = move_start[i] + len(legal_moves)
        move += legal_moves
        slot += [move_index(m, colour) for m in legal_moves]
        q.append(row["q"])
        mean.append(row["mean"])
        last.append(row["last"])
    for name, rows in (("train_folders", train_rows), ("val_folder", val_rows)):
        left = Counter(split_of(g) for g, _ in rows)
        for s, c in left.items():
            counts[f"{name}_unused_{s}_rows"] = c
    for s in ("train", "val"):
        counts[f"{s}_positions"] = int((split == s).sum())
        counts[f"{s}_games"] = len({f[0] for f, sp in zip(facts, split) if sp == s})
    return {"planes": planes, "weight": weight,
            "belief": np.repeat(np.arange(n), sizes).astype(np.int64),
            "game_id": np.array([f[0] for f in facts]), "ply": np.array([f[1] for f in facts], dtype=np.int32),
            "player": player, "split": split, "legal": legal, "played": played, "move_start": move_start,
            "move": np.array(move), "slot": np.array(slot, dtype=np.int64),
            "q": np.concatenate(q), "mean": np.concatenate(mean), "last": np.concatenate(last),
            "counts": np.array(json.dumps(dict(sorted(counts.items()))))}


def load_positions(records, train_targets, val_targets, cache_dir, workers: int = 6,
                   pattern: str = "part-*.jsonl") -> dict:
    """build_positions, cached in cache_dir under a key covering every input file's name, size and mtime."""
    files = sorted(Path(records).glob(pattern))
    for folder in [*train_targets, val_targets]:
        files += sorted(Path(folder).glob("resolve-*.jsonl"))
    stamp = "|".join(f"{p.resolve()}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in files)
    order = "|".join(str(Path(f).resolve()) for f in [*train_targets, "val:", val_targets])
    key = hashlib.sha1(f"{stamp}|{order}|{pattern}|{ENCODING}|{CACHE_VERSION}".encode()).hexdigest()[:12]
    path = Path(cache_dir) / f"positions-{Path(records).name}-{key}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    arrays = build_positions(records, train_targets, val_targets, workers, pattern)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return arrays


def counts_of(arrays: dict) -> dict:
    return json.loads(str(arrays["counts"]))


def move_position(arrays: dict) -> np.ndarray:
    """The position index of each entry of the move arrays."""
    return np.repeat(np.arange(len(arrays["move_start"]) - 1), np.diff(arrays["move_start"]))


def dense_targets(arrays: dict, kind: str, positions: np.ndarray | None = None) -> np.ndarray:
    """(len(positions), 4096) float32 target distributions in the mirrored slots (promotion variants of one
    pawn move add up, as pairb.moves.policy_vector does)."""
    if kind not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}")
    n = len(arrays["move_start"]) - 1
    positions = np.arange(n) if positions is None else np.asarray(positions)
    local = np.full(n, -1, dtype=np.int64)
    local[positions] = np.arange(len(positions))
    pos = local[move_position(arrays)]
    keep = pos >= 0
    out = np.zeros((len(positions), N_MOVES), dtype=np.float32)
    np.add.at(out, (pos[keep], arrays["slot"][keep]), arrays[kind][keep].astype(np.float32))
    return out
