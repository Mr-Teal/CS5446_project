"""Scoring the belief network on dataset arrays (D6). Shared by the training and evaluation scripts.

Boards the fog-of-war rules decide take their exact label, as the evaluator gives them, and are
left out of the board error. A belief's position value is the weighted mean of its board values
(pair_b/docs/label_definitions.md), compared with the record's root_value.
"""
import numpy as np
import torch

from .belief_data import belief_batches, rows_of


def require_d1(arrays: dict, beliefs: np.ndarray) -> None:
    """Raise ValueError if a board the rules do not decide has no quick-Stockfish value: a network
    that reads d1 must never be fed a made-up one."""
    rows, _ = rows_of(arrays, beliefs)
    missing = np.isnan(arrays["d1"][rows]) & ~arrays["rule"][rows]
    if missing.any():
        n_beliefs = len(np.unique(arrays["belief"][rows][missing]))
        raise ValueError(f"{int(missing.sum())} boards in {n_beliefs} beliefs have no quick-Stockfish value "
                         "(d1:<i> diagnostics); a network that reads d1 needs one for every board the rules "
                         "do not decide")


@torch.no_grad()
def predict(net, arrays: dict, beliefs: np.ndarray, device, max_boards: int = 4096, planes=None) -> np.ndarray:
    """The network's value of every board of `beliefs`, in rows_of order, at most `max_boards`
    boards per pass. `planes` may hold arrays["planes"] already on the device."""
    if net.use_d1:
        require_d1(arrays, beliefs)
    net.eval()
    out = []
    for chunk in belief_batches(np.bincount(arrays["belief"]), beliefs, max_boards):
        rows, local = rows_of(arrays, chunk)
        x = planes[torch.from_numpy(rows).to(device)] if planes is not None else torch.from_numpy(arrays["planes"][rows]).to(device)
        d1 = torch.from_numpy(np.nan_to_num(arrays["d1"][rows])).to(device) if net.use_d1 else None
        out.append(net(x.float(), torch.from_numpy(arrays["weight"][rows]).to(device),
                       torch.from_numpy(local).to(device), len(chunk), d1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def errors(pred: np.ndarray, arrays: dict, beliefs: np.ndarray) -> tuple[dict, np.ndarray]:
    """Board and position errors of `pred` (rows_of order) against the labels, and each belief's
    position error (for paired comparisons)."""
    rows, local = rows_of(arrays, beliefs)
    y, w, rule = arrays["y"][rows], arrays["weight"][rows], arrays["rule"][rows]
    value = np.where(rule, y, pred)
    engine = ~rule
    err = np.abs(value - y)
    total = max(float(w[engine].sum()), 1e-12)
    root_err = np.abs(np.bincount(local, weights=w * value, minlength=len(beliefs)) - arrays["root"][beliefs])
    metrics = {"board_mae": round(float((w * err)[engine].sum()) / total, 6),
               "board_mse": round(float((w * err ** 2)[engine].sum()) / total, 6),
               "root_mae": round(float(root_err.mean()), 6), "beliefs": int(len(beliefs)), "boards": int(engine.sum())}
    return metrics, root_err


def baseline_pred(arrays: dict, beliefs: np.ndarray) -> np.ndarray | None:
    """Quick Stockfish's value of every board, when the records carry it ("d1:<i>" diagnostics)."""
    rows, _ = rows_of(arrays, beliefs)
    d1 = arrays["d1"][rows]
    return None if np.isnan(d1[~arrays["rule"][rows]]).any() else np.nan_to_num(d1)


def paired_difference(a: np.ndarray, b: np.ndarray, groups: np.ndarray, n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean of a - b over beliefs, with a 95% bootstrap interval that resamples whole games
    (`groups`, one game_id per belief): beliefs from one game are correlated, so resampling them
    one by one would make the interval too narrow. Negative means a errs less."""
    diff = a - b
    keys, game = np.unique(groups, return_inverse=True)
    sums, counts = np.bincount(game, weights=diff), np.bincount(game)
    pick = np.random.default_rng(seed).integers(0, len(keys), size=(n_boot, len(keys)))
    boots = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return {"mean": float(diff.mean()), "ci95": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))],
            "beliefs": int(len(diff)), "games": int(len(keys)), "resampled": "games"}
