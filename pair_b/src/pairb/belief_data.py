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

from .moves import legal_mask, policy_vector
from .observe import visible_squares
from .values import rule_value

ENCODING = "fow-shared-features-32+pairb-observe-v1"  # the shared planes, with Pair B's stand-in visibility
CACHE_VERSION = 4  # bump whenever build_arrays changes what it returns (3: policy + legal per belief; 4: player)


def opponent_visible(board: chess.Board) -> list[str]:
    """What the opponent sees on one hypothesis board: the encoder's visibility callback."""
    return sorted(visible_squares(board, not board.turn))


def build_arrays(records) -> dict[str, np.ndarray]:
    planes, weight, belief, y, d1, rule, policy, legal = [], [], [], [], [], [], [], []
    for b, r in enumerate(records):
        p, w = encode_belief(r.agent_input, opponent_visible)
        n = len(w)
        diagnostics = r.decision.diagnostics
        player = r.agent_input.observation.player
        to_player = 1.0 if player == "white" else -1.0
        # The solver's raw root policy over the observed legal moves, one row per belief, in the mirrored
        # move frame of pairb.moves: the policy head's target and its legal mask.
        policy.append(policy_vector(r.decision.root_policy, player).astype(np.float16))
        legal.append(legal_mask(r.agent_input.observation.legal_moves, player))
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
            "game_id": np.array([r.game_id for r in records]),
            # the acting player, +1 white / -1 black: the perspective a game result is turned into (record_outcomes)
            "player": np.array([1 if r.agent_input.observation.player == "white" else -1 for r in records], dtype=np.int8),
            "policy": np.stack(policy), "legal": np.stack(legal)}


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
    the folder. The cache key covers each file's name, size and modification time, plus the
    manifest's `created` and `records` when there is one (manifest.json is optional), so files
    rewritten under an unchanged manifest are read again."""
    folder = Path(folder)
    parts = sorted(folder.glob(pattern))
    stamp = "|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in parts)
    if (folder / "manifest.json").exists():
        manifest = json.loads((folder / "manifest.json").read_text())
        stamp += f"|{manifest.get('created')}|{manifest.get('records')}"
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


def game_outcomes(paths) -> dict[str, float]:
    """Each game's result from label_run's progress.jsonl rows, from White's side: +1 White won, -1 Black
    won, 0 a draw (winner null or "draw" and no error; label_run writes null for games stopped at the ply
    limit and passes on fow_shared's "draw"), NaN a game that died (`error` set), whose result is unknown.
    A game listed twice with different results is refused."""
    results: dict[str, float] = {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("error"):
                value = np.nan
            else:
                value = {"white": 1.0, "black": -1.0, "draw": 0.0, None: 0.0}[row.get("winner")]
            game = row["game_id"]
            if game in results and not (results[game] == value or (np.isnan(results[game]) and np.isnan(value))):
                raise ValueError(f"game {game} has two different results in {list(map(str, paths))}")
            results[game] = value
    return results


def record_outcomes(arrays: dict[str, np.ndarray], results: dict[str, float]) -> np.ndarray:
    """The final result of each belief's game, from its acting player's side (+1 win, 0 draw, -1 loss), as
    float32 indexed by belief; NaN when the game died or has no result in `results`."""
    white = np.array([results.get(g, np.nan) for g in arrays["game_id"]], dtype=np.float32)
    return white * arrays["player"].astype(np.float32)


def mixed_targets(arrays: dict[str, np.ndarray], outcome: np.ndarray, mix: float) -> np.ndarray:
    """The per-board training target (1 - mix) * y + mix * outcome of the board's belief, and y itself where
    that belief has no outcome. Mixing every board of a belief this way makes the belief-weighted mean of the
    targets (1 - mix) * root + mix * outcome."""
    o = outcome[arrays["belief"]]
    y = arrays["y"]
    return np.where(np.isnan(o), y, (1 - mix) * y + mix * np.nan_to_num(o)).astype(np.float32)


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
