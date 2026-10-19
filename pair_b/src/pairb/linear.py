"""Ridge correction of depth-1 values using Network 1's 19-plane encoding.

v_hat = clip(d1 + X @ coef + intercept, -1, 1), where X concatenates flattened
float board planes and d1. Fit the *unclipped* residual y-d1 with objective
mean((X @ coef + intercept - (y-d1))**2) + alpha * ||coef||**2.
The intercept is unpenalized. This is a linear correction with output clipping,
not Network 1's nonlinear tanh/atanh residual parameterization.
"""
import json
from dataclasses import dataclass, field

import numpy as np

from .data import ENCODING, unpack
from .encode import N_PLANES

FEATURES = N_PLANES * 64 + 1
FORMAT = "linear-d1-ridge-v1"


def features(planes, d1, *, packed=False):
    planes, d1 = np.asarray(planes), np.asarray(d1, dtype=np.float64)
    if d1.ndim != 1 or planes.shape != (len(d1), N_PLANES, 8, 8):
        raise ValueError("expected planes (N,19,8,8) and d1 (N,)")
    x = unpack(planes) if packed else planes
    x = np.column_stack((x.reshape(len(d1), N_PLANES * 64), d1)).astype(np.float64)
    if not np.isfinite(x).all() or np.any(np.abs(d1) > 1):
        raise ValueError("inputs must be finite, with d1 in [-1,1]")
    return x


@dataclass
class LinearCorrection:
    coef: np.ndarray
    intercept: float
    alpha: float
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.coef = np.asarray(self.coef, dtype=np.float64)
        if (self.coef.shape != (FEATURES,) or not np.isfinite(self.coef).all()
                or not np.isfinite(self.intercept) or not np.isfinite(self.alpha) or self.alpha <= 0
                or not isinstance(self.metadata, dict)):
            raise ValueError("invalid linear coefficients, intercept or positive ridge alpha")

    def predict(self, planes, d1, *, packed=False):
        planes, d1 = np.asarray(planes), np.asarray(d1, dtype=np.float64)
        if d1.ndim != 1 or planes.shape != (len(d1), N_PLANES, 8, 8):
            raise ValueError("expected planes (N,19,8,8) and d1 (N,)")
        result = np.empty(len(d1), dtype=np.float64)
        for start in range(0, len(d1), 4096):
            end = start + 4096
            x = features(planes[start:end], d1[start:end], packed=packed)
            result[start:end] = np.clip(d1[start:end] + x @ self.coef + self.intercept, -1, 1)
        return result

    def save(self, path):
        # No pickle; refuse overwrites like the existing training scripts.
        with open(path, "xb") as f:
            np.savez_compressed(f, coef=self.coef, intercept=self.intercept, alpha=self.alpha,
                                format=FORMAT, encoding=ENCODING,
                                metadata=json.dumps(self.metadata, allow_nan=False))

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as z:
            if str(z["format"]) != FORMAT or str(z["encoding"]) != ENCODING:
                raise ValueError("incompatible linear checkpoint format or board encoding")
            return cls(z["coef"], float(z["intercept"]), float(z["alpha"]),
                       json.loads(str(z["metadata"])))


def fit_candidates(planes, d1, y, alphas, *, batch=4096):
    """Fit all positive ridge penalties from one training-only eigendecomposition."""
    planes, d1 = np.asarray(planes), np.asarray(d1, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    alphas = list(alphas)
    if (d1.ndim != 1 or not len(d1) or planes.shape != (len(d1), N_PLANES, 8, 8)
            or batch < 1 or y.shape != (len(d1),) or not np.isfinite(y).all()
            or np.any(np.abs(y) > 1) or not alphas
            or any(not np.isfinite(a) or a <= 0 for a in alphas)):
        raise ValueError("need training rows, bounded finite targets and positive finite alphas")
    residual = y - d1
    offset = float(residual.mean())
    gram = np.zeros((FEATURES, FEATURES), dtype=np.float64)
    sums, rhs = np.zeros(FEATURES), np.zeros(FEATURES)
    # Accumulate sufficient statistics without a full (N,1217) float64 design matrix.
    for start in range(0, len(d1), batch):
        end = start + batch
        x = features(planes[start:end], d1[start:end], packed=True)
        sums += x.sum(axis=0)
        gram += x.T @ x
        rhs += x.T @ residual[start:end]
    mean = sums / len(d1)
    gram = gram / len(d1) - np.outer(mean, mean)
    rhs = rhs / len(d1) - mean * offset
    vals, vecs = np.linalg.eigh(gram)
    vals = np.maximum(vals, 0)  # numerical roundoff of a positive semidefinite matrix
    projected = vecs.T @ rhs
    models = []
    for alpha in alphas:
        coef = vecs @ (projected / (vals + alpha))
        models.append(LinearCorrection(coef, float(offset - mean @ coef), float(alpha)))
    return models
