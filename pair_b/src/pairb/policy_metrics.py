"""Policy network metrics against a mixing teacher (stage 2): how close a move distribution comes to the solver's.

The teacher is the solver's root strategy over the 4096 mirrored slots of pairb.moves. Its support is the slots it
gives more than SUPPORT. A label is one-hot when its top move has at least ONE_HOT, and genuinely mixed when its
purify_loss (our value against a best response to the mixed strategy minus that against the same strategy with the
top move played outright) exceeds MIXING_WORKS: there the mixing does work. The thresholds are the depth
measurement's (pair_a_prep/experiments/depth_measure_2026-11-12).
"""
import numpy as np

from .policy_net import CE_FLOOR

SUPPORT = 0.01
ONE_HOT = 0.999
MIXING_WORKS = 0.005


def teacher_metrics(probs: np.ndarray, teacher: np.ndarray) -> dict:
    """Per position, predicted distributions (n, 4096) against the teacher's: cross-entropy, total-variation
    distance, the predicted mass on the teacher's support, and whether the predicted top slot is in it."""
    support = teacher > SUPPORT
    top = probs.argmax(1)
    return {"ce_teacher": -(teacher * np.log(np.maximum(probs, CE_FLOOR))).sum(1),
            "tv_teacher": 0.5 * np.abs(probs - teacher).sum(1),
            "mass_on_support": (probs * support).sum(1),
            "top_in_support": support[np.arange(len(top)), top].astype(np.float64)}


def pure_teacher_metrics(slots: np.ndarray, teacher: np.ndarray) -> dict:
    """The same for a mover that plays one slot per position outright (no cross-entropy: it would be infinite
    wherever the teacher mixes): its distance from the teacher is 1 - the teacher's probability of that slot."""
    p = teacher[np.arange(len(slots)), slots]
    inside = (p > SUPPORT).astype(np.float64)
    return {"tv_teacher": 1.0 - p, "mass_on_support": inside, "top_in_support": inside}


def uniform_teacher_metrics(legal: np.ndarray, teacher: np.ndarray) -> dict:
    """The same for a uniform distribution over the legal slots; its top slot is a random legal slot, so
    top_in_support is the expected share, the support's size over the number of legal slots."""
    n_legal = legal.sum(1)
    out = teacher_metrics(legal / n_legal[:, None], teacher)
    out["top_in_support"] = (teacher > SUPPORT).sum(1) / n_legal
    return out


def label_kinds(arrays: dict, positions: np.ndarray) -> dict:
    """Boolean masks over `positions`: one_hot (teacher top move >= ONE_HOT) and mixing_works
    (purify_loss > MIXING_WORKS; False where the row has no purification test)."""
    s = arrays["move_start"]
    top = np.array([arrays["last"][s[i]:s[i + 1]].max() for i in positions])
    purify = arrays["purify"][positions]
    return {"one_hot": top >= ONE_HOT, "mixing_works": np.nan_to_num(purify, nan=-np.inf) > MIXING_WORKS}
