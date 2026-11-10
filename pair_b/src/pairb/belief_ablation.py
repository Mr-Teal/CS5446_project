"""Input ablations of the belief network's state representation (D6).

What the network is allowed to see of a belief:

"full"         every sampled hypothesis board with the shared 32 planes: the network as designed.
"marginals"    no sampled boards. One pseudo-board per belief: what the observation shows, plus the
               belief tracker's marginal planes (enemy piece probabilities, population) and the
               belief-weighted average of the planes that differ per hypothesis. Asks whether sampling
               joint hypotheses adds anything over the marginals.
"observation"  one pseudo-board per belief holding only what the observation shows: own pieces, enemy
               pieces on our visible squares, the two visibility planes, capture recency, ply, search
               depth, own castling rights, en passant. Every hidden plane is zero. Asks whether the
               belief adds anything over the fogged board ("pure fog").

A collapsed pseudo-board carries the position label (the weighted mean of the hypothesis labels, which
equals the record's root_value), weight 1, and is rule-decided only when every hypothesis board is. Board
error and position error therefore coincide for the collapsed modes, and their position error is
directly comparable with the full network's position error on the same beliefs.

Plane roles were checked on the solver-v2-sf8-g237 arrays (2026-11-10): planes 0-5, 12-20, 23-27 and 30
are identical across the hypotheses of a belief; 6-11, 21, 22, 28, 29 and 31 differ; enemy pieces on
our visible squares agree across hypotheses, as the encoder enforces.
"""
from __future__ import annotations

import numpy as np

MODES = ("full", "marginals", "observation")
# Evaluation-only modes that imitate how the search uses the leaf at play time: chess_search.py asks
# evaluate_children(fen) for one concrete board at a time, and BeliefNetworkEvaluator._alone turns each board
# into a belief of one hypothesis (weight 1, probability planes = that board's own enemy pieces, population 1).
#   "alone"            every stored board scored as such a one-board belief (for networks trained on "full")
#   "alone-marginals"  the same, then collapsed the way the "marginals" network was trained (hidden enemy
#                      pieces removed from planes 6-11, kept only in the probability planes)
LEAF_MODES = ("alone", "alone-marginals")
# fow_shared.features.PLANE_NAMES indices
OBSERVED = [0, 1, 2, 3, 4, 5, 12, 13, 23, 24, 25, 26, 27, 30]  # from the observation and public information
ENEMY = [6, 7, 8, 9, 10, 11]                                   # enemy pieces: kept only on our visible squares
MARGINAL = [14, 15, 16, 17, 18, 19, 20]                        # belief-tracker marginals (same on every hypothesis)
HYPOTHESIS = [21, 22, 28, 29, 31]                              # differ per hypothesis: averaged in "marginals"
VISIBLE = 12


def collapse(arrays: dict[str, np.ndarray], mode: str) -> dict[str, np.ndarray]:
    """Return `arrays` unchanged for "full", or one pseudo-board per belief for the other modes."""
    if mode not in MODES and mode not in LEAF_MODES:
        raise ValueError(f"unknown input mode {mode!r}; one of {MODES + LEAF_MODES}")
    if mode == "full":
        return arrays
    if mode in LEAF_MODES:
        return _alone(arrays, masked=(mode == "alone-marginals"))
    belief, planes, weight = arrays["belief"], arrays["planes"], arrays["weight"]
    n = len(arrays["root"])
    starts = np.searchsorted(belief, np.arange(n), side="left")
    ends = np.searchsorted(belief, np.arange(n), side="right")
    out = np.zeros((n, planes.shape[1], 8, 8), dtype=planes.dtype)
    rule = np.zeros(n, dtype=bool)
    for b, (s, e) in enumerate(zip(starts, ends)):
        first = planes[s].astype(np.float32)
        q = np.zeros_like(first)
        q[OBSERVED] = first[OBSERVED]
        q[ENEMY] = first[ENEMY] * first[VISIBLE][None]
        if mode == "marginals":
            q[MARGINAL] = first[MARGINAL]
            q[HYPOTHESIS] = np.tensordot(weight[s:e].astype(np.float32),
                                         planes[s:e][:, HYPOTHESIS].astype(np.float32), axes=(0, 0))
        out[b] = q
        rule[b] = bool(arrays["rule"][s:e].all())
    out_arrays = {"planes": out, "weight": np.ones(n, dtype=np.float32), "belief": np.arange(n, dtype=np.int64),
                  "y": arrays["root"].astype(np.float32).copy(), "d1": np.full(n, np.nan, dtype=np.float32),
                  "rule": rule, "root": arrays["root"], "game_id": arrays["game_id"]}
    for key in ("policy", "legal", "player"):  # one row per belief already, so they carry over unchanged
        if key in arrays:
            out_arrays[key] = arrays[key]
    return out_arrays


def _alone(arrays: dict[str, np.ndarray], masked: bool) -> dict[str, np.ndarray]:
    """Every stored board as a belief of its own, as the leaf evaluator presents boards to the network
    during search. Its label stays its own hypothesis value, which is also the one-board position value."""
    planes = arrays["planes"].astype(np.float32).copy()
    planes[:, MARGINAL[:6]] = planes[:, ENEMY]          # probability 1 on this board's own enemy pieces
    planes[:, 20] = 0.0                                  # population 1: log2(1) / 15
    if masked:
        planes[:, ENEMY] *= planes[:, VISIBLE][:, None]  # hidden pieces only in the probability planes
    n = len(arrays["y"])
    game_id = arrays["game_id"][arrays["belief"]]
    out_arrays = {"planes": planes.astype(arrays["planes"].dtype), "weight": np.ones(n, dtype=np.float32),
                  "belief": np.arange(n, dtype=np.int64), "y": arrays["y"], "d1": arrays["d1"], "rule": arrays["rule"],
                  "root": arrays["y"].astype(np.float32), "game_id": game_id}
    if "player" in arrays:
        out_arrays["player"] = arrays["player"][arrays["belief"]]
    return out_arrays
