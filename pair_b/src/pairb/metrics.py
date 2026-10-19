"""Metrics for scorers (D3).

Move choice is measured among sibling children of one parent. Values are in the child's
side-to-move view, i.e. the opponent of the player choosing, so the best child is the one with
the lowest value.
"""
import numpy as np


def _per_parent_regret(group, pred, y) -> np.ndarray:
    """Value lost at each parent (in group order) by choosing the child `pred` calls best."""
    def first_per_group(order):
        g = group[order]
        keep = np.ones(len(order), dtype=bool)
        keep[1:] = g[1:] != g[:-1]
        return order[keep]

    chosen = first_per_group(np.lexsort((pred, group)))
    best = first_per_group(np.lexsort((y, group)))
    return y[chosen] - y[best]


def _arrays(parents, *values):
    _, group = np.unique(np.asarray(parents), return_inverse=True)
    return (group, *(np.asarray(v, dtype=np.float64) for v in values))


def choice_metrics(parents, pred, y) -> dict:
    """top1: share of parents where the chosen child is as good as the best one;
    regret: mean value lost by the choice."""
    group, pred, y = _arrays(parents, pred, y)
    regret = _per_parent_regret(group, pred, y)
    return {"top1": float(np.mean(regret <= 1e-9)), "regret": float(np.mean(regret)), "parents": int(len(regret))}


def paired_regret_difference(parents, pred, base, y, games=None, n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean regret of `pred` minus that of `base` on the same parents, with a 95% bootstrap
    interval. Negative means `pred` chooses better.

    With `games` (the game of each row) the interval resamples whole games: parents from one
    game are correlated, so resampling them one by one makes the interval too narrow. Without
    it, each parent is resampled on its own."""
    group, pred, base, y = _arrays(parents, pred, base, y)
    diff = _per_parent_regret(group, pred, y) - _per_parent_regret(group, base, y)
    if games is None:
        game = np.arange(len(diff))
    else:
        first_row = np.unique(group, return_index=True)[1]  # one row per parent, in group order
        game = np.unique(np.asarray(games)[first_row], return_inverse=True)[1]
    sums, counts = np.bincount(game, weights=diff), np.bincount(game)
    pick = np.random.default_rng(seed).integers(0, len(sums), size=(n_boot, len(sums)))
    boots = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return {"mean": float(diff.mean()), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
            "parents": int(len(diff)), "games": int(len(sums)), "resampled": "parents" if games is None else "games"}
