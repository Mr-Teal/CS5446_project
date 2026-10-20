"""Belief records (fow_shared TrainingRecord JSONL) to flat per-board arrays for the belief network.

Each board of each belief is one row: its 32 planes from the shared encoder, its weight, the index
of its belief, its label (hypothesis_values), quick Stockfish's value when the record carries it
("d1:<i>" diagnostics; a board the fog-of-war rules decide takes its rule value, as the evaluator
feeds it) and whether the rules decide it. The same reader takes Pair B's practice beliefs now and
Pair A's solver labels later, as both use Teal's record format.
"""
from __future__ import annotations

import hashlib
import json
from multiprocessing import Pool
from pathlib import Path

import chess
import numpy as np

from fow_shared.features import encode_belief
from fow_shared.recording import read_records

from .observe import visible_squares
from .values import rule_value

ENCODING = "fow-shared-features-32+pairb-observe-v1"  # the shared planes, with Pair B's stand-in visibility
CACHE_VERSION = 2  # bump whenever build_arrays changes what it returns


def opponent_visible(board: chess.Board) -> list[str]:
    """What the opponent sees on one hypothesis board: the encoder's visibility callback."""
    return sorted(visible_squares(board, not board.turn))


def build_arrays(records) -> dict[str, np.ndarray]:
    planes, weight, belief, y, d1, rule = [], [], [], [], [], []
    for b, r in enumerate(records):
        p, w = encode_belief(r.agent_input, opponent_visible)
        n = len(w)
        diagnostics = r.decision.diagnostics
        to_player = 1.0 if r.agent_input.observation.player == "white" else -1.0
        rules = [rule_value(chess.Board(h.fen)) for h in r.agent_input.belief.hypotheses]
        quick = [diagnostics.get(f"d1:{i}", np.nan) for i in range(n)]
        quick = [to_player * rv[1] if rv is not None and np.isnan(q) else q for q, rv in zip(quick, rules)]
        planes.append(p.astype(np.float16))
        weight.append(w.astype(np.float32))
        belief.append(np.full(n, b, dtype=np.int64))
        y.append(np.asarray(r.hypothesis_values, dtype=np.float32))
        d1.append(np.array(quick, dtype=np.float32))
        rule.append(np.array([rv is not None for rv in rules]))
    return {"planes": np.concatenate(planes), "weight": np.concatenate(weight), "belief": np.concatenate(belief),
            "y": np.concatenate(y), "d1": np.concatenate(d1), "rule": np.concatenate(rule),
            "root": np.array([r.root_value for r in records], dtype=np.float32),
            "game_id": np.array([r.game_id for r in records])}


def _part_arrays(path) -> dict[str, np.ndarray] | None:
    records = list(read_records(path))
    return build_arrays(records) if records else None  # an empty part file adds nothing


def _merge(parts: list[dict]) -> dict[str, np.ndarray]:
    offsets = np.cumsum([0] + [len(p["root"]) for p in parts[:-1]])
    merged = {k: np.concatenate([p[k] for p in parts]) for k in parts[0] if k != "belief"}
    merged["belief"] = np.concatenate([p["belief"] + o for p, o in zip(parts, offsets)])
    return merged


def load_arrays(folder, cache_dir, workers: int = 8, pattern: str = "part-*.jsonl") -> dict[str, np.ndarray]:
    """build_arrays for a folder of record files (`pattern`), one file per process, cached outside
    the folder. manifest.json is optional; without it the cache key comes from the files themselves."""
    folder = Path(folder)
    parts = sorted(folder.glob(pattern))
    if (folder / "manifest.json").exists():
        manifest = json.loads((folder / "manifest.json").read_text())
        stamp = f"{manifest.get('created')}|{manifest.get('records')}"
    else:
        stamp = "|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in parts)
    key = hashlib.sha1(f"{folder.resolve()}|{pattern}|{stamp}|{ENCODING}|{CACHE_VERSION}".encode()).hexdigest()[:12]
    path = Path(cache_dir) / f"{folder.name}-{key}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    if workers > 1 and len(parts) > 1:
        with Pool(min(workers, len(parts))) as pool:
            pieces = pool.map(_part_arrays, parts)
    else:
        pieces = [_part_arrays(p) for p in parts]
    pieces = [p for p in pieces if p is not None]
    if not pieces:
        raise ValueError(f"no records in {folder} matching {pattern!r}")
    arrays = _merge(pieces)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return arrays


def belief_batches(sizes: np.ndarray, order: np.ndarray, max_boards: int, max_beliefs: int | None = None) -> list[np.ndarray]:
    """Whole beliefs, in `order`, grouped so a batch holds at most `max_boards` boards (a belief
    larger than that goes alone) and at most `max_beliefs` beliefs. `sizes` gives each belief's
    number of boards, indexed by belief id."""
    batches, current, boards = [], [], 0
    for b in order:
        n = int(sizes[b])
        if current and (boards + n > max_boards or (max_beliefs and len(current) >= max_beliefs)):
            batches.append(np.array(current))
            current, boards = [], 0
        current.append(b)
        boards += n
    if current:
        batches.append(np.array(current))
    return batches


def rows_of(arrays: dict[str, np.ndarray], beliefs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The board rows of the given beliefs, and each row's position among them (for one batch)."""
    belief = arrays["belief"]
    starts = np.searchsorted(belief, beliefs, side="left")
    ends = np.searchsorted(belief, beliefs, side="right")
    rows = np.concatenate([np.arange(s, e) for s, e in zip(starts, ends)])
    local = np.repeat(np.arange(len(beliefs)), ends - starts)
    return rows, local
