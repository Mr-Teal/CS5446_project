"""Belief records (fow_shared TrainingRecord JSONL) to flat per-board arrays for the belief network.

Each board of each belief is one row: its 32 planes from the shared encoder, its weight, the index
of its belief, its label (hypothesis_values), quick Stockfish's value when the record carries it
("d1:<i>" diagnostics) and whether the fog-of-war rules decide it. The same reader takes Pair B's
practice beliefs now and Pair A's solver labels later, as both use Teal's record format.
"""
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
CACHE_VERSION = 1  # bump whenever build_arrays changes what it returns


def opponent_visible(board: chess.Board) -> list[str]:
    """What the opponent sees on one hypothesis board: the encoder's visibility callback."""
    return sorted(visible_squares(board, not board.turn))


def build_arrays(records) -> dict[str, np.ndarray]:
    planes, weight, belief, y, d1, rule = [], [], [], [], [], []
    for b, r in enumerate(records):
        p, w = encode_belief(r.agent_input, opponent_visible)
        n = len(w)
        diagnostics = r.decision.diagnostics
        planes.append(p.astype(np.float16))
        weight.append(w.astype(np.float32))
        belief.append(np.full(n, b, dtype=np.int64))
        y.append(np.asarray(r.hypothesis_values, dtype=np.float32))
        d1.append(np.array([diagnostics.get(f"d1:{i}", np.nan) for i in range(n)], dtype=np.float32))
        rule.append(np.array([rule_value(chess.Board(h.fen)) is not None for h in r.agent_input.belief.hypotheses]))
    return {"planes": np.concatenate(planes), "weight": np.concatenate(weight), "belief": np.concatenate(belief),
            "y": np.concatenate(y), "d1": np.concatenate(d1), "rule": np.concatenate(rule),
            "root": np.array([r.root_value for r in records], dtype=np.float32),
            "game_id": np.array([r.game_id for r in records])}


def _part_arrays(path) -> dict[str, np.ndarray]:
    return build_arrays(list(read_records(path)))


def _merge(parts: list[dict]) -> dict[str, np.ndarray]:
    offsets = np.cumsum([0] + [len(p["root"]) for p in parts[:-1]])
    merged = {k: np.concatenate([p[k] for p in parts]) for k in parts[0] if k != "belief"}
    merged["belief"] = np.concatenate([p["belief"] + o for p, o in zip(parts, offsets)])
    return merged


def load_arrays(folder, cache_dir, workers: int = 8) -> dict[str, np.ndarray]:
    """build_arrays for a dataset folder, one part file per process, cached outside the folder."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    key = hashlib.sha1(f"{folder.resolve()}|{manifest['created']}|{manifest['records']}|{ENCODING}|{CACHE_VERSION}"
                       .encode()).hexdigest()[:12]
    path = Path(cache_dir) / f"{folder.name}-{key}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    parts = sorted(folder.glob("part-*.jsonl"))
    if workers > 1 and len(parts) > 1:
        with Pool(min(workers, len(parts))) as pool:
            pieces = pool.map(_part_arrays, parts)
    else:
        pieces = [_part_arrays(p) for p in parts]
    arrays = _merge([p for p in pieces if len(p["root"])])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return arrays


def rows_of(arrays: dict[str, np.ndarray], beliefs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The board rows of the given beliefs, and each row's position among them (for one batch)."""
    belief = arrays["belief"]
    starts = np.searchsorted(belief, beliefs, side="left")
    ends = np.searchsorted(belief, beliefs, side="right")
    rows = np.concatenate([np.arange(s, e) for s, e in zip(starts, ends)])
    local = np.repeat(np.arange(len(beliefs)), ends - starts)
    return rows, local
