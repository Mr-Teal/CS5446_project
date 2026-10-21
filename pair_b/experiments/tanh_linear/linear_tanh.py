"""Bryan's question on PR #8: how much of the value-error gap between the linear correction and
Network 1 is the output transform rather than the board reader?

Fits the same linear correction, on the same 1,217 inputs (19 planes x 64 squares, plus d1), inside
Network 1's output: v = tanh(atanh(clip(d1, 0.999)) + X @ w + b). Loss: mean squared error in value
space plus alpha * ||w||^2 (b unpenalised), as for the plain ridge fit. Damped Gauss-Newton
(Levenberg-Marquardt), alpha picked on d2-v2's validation games, scored on d2-check's train
bucket: the same rows as the plain linear correction and Network 1 this morning.

    python linear_tanh.py <d2-v2> <d2-check> <plain linear best.npz> <net1 checkpoint dir> <out dir>

Needs PR #8's code on PYTHONPATH (pairb.linear, pairb.linear_workflow) and torch for Network 1.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from pairb.belief_eval import paired_difference
from pairb.data import ENCODING, unpack
from pairb.evaluate import predict as net1_predict
from pairb.linear import LinearCorrection
from pairb.linear_workflow import load_dataset, mask_split, metrics
from pairb.metrics import paired_regret_difference
from pairb.net1 import D1_CLIP, Network1

ALPHAS = (1e-5, 1e-4, 1e-3)
CHUNK = 8192


def design(arrays):
    """float32 inputs with the same columns as the plain linear model: planes, then d1."""
    n = len(arrays["y"])
    x = np.empty((n, 19 * 64 + 1), dtype=np.float32)
    for s in range(0, n, CHUNK):
        x[s:s + CHUNK, :-1] = unpack(arrays["planes"][s:s + CHUNK]).reshape(-1, 19 * 64)
    x[:, -1] = arrays["d1"]
    return x


def base_logit(d1):
    return np.arctanh(np.clip(np.asarray(d1, dtype=np.float64), -D1_CLIP, D1_CLIP))


def predict(x, z0, w, b):
    out = np.empty(len(z0))
    for s in range(0, len(z0), CHUNK):
        out[s:s + CHUNK] = np.tanh(z0[s:s + CHUNK] + x[s:s + CHUNK].astype(np.float64) @ w + b)
    return out


def loss(x, z0, y, w, b, alpha):
    return float(np.mean((predict(x, z0, w, b) - y) ** 2) + alpha * w @ w)


def fit(x, z0, y, alpha, w, b, *, iters=40, tol=1e-10):
    """Levenberg-Marquardt on mean((tanh(z0 + x w + b) - y)^2) + alpha |w|^2."""
    n, k = x.shape
    lam, current = 1e-3, loss(x, z0, y, w, b, alpha)
    history = [current]
    for _ in range(iters):
        jtj = np.zeros((k + 1, k + 1))
        jtr = np.zeros(k + 1)
        for s in range(0, n, CHUNK):
            xc = x[s:s + CHUNK].astype(np.float64)
            v = np.tanh(z0[s:s + CHUNK] + xc @ w + b)
            jc = np.column_stack((xc, np.ones(len(xc)))) * (1 - v * v)[:, None]
            jtj += jc.T @ jc
            jtr += jc.T @ (v - y[s:s + CHUNK])
        grad = 2 * jtr / n
        grad[:k] += 2 * alpha * w
        hess = 2 * jtj / n
        hess[np.arange(k), np.arange(k)] += 2 * alpha
        while True:
            step = np.linalg.solve(hess + lam * np.diag(np.maximum(np.diag(hess), 1e-12)), -grad)
            new = loss(x, z0, y, w + step[:k], b + step[k], alpha)
            if new < current:
                w, b, lam = w + step[:k], b + step[k], max(lam / 3, 1e-9)
                break
            lam *= 4
            if lam > 1e8:
                return w, b, history
        history.append(new)
        if current - new < tol * max(current, 1e-12):
            break
        current = new
    return w, b, history


def main():
    v2, check, plain_path, net_dir, out = (Path(a) for a in sys.argv[1:6])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    fit_arrays, fit_source = load_dataset(v2)
    train, val = mask_split(fit_arrays, "train"), mask_split(fit_arrays, "val")
    x_train, x_val = design(train), design(val)
    z_train, z_val = base_logit(train["d1"]), base_logit(val["d1"])
    y_train, y_val = train["y"].astype(np.float64), val["y"].astype(np.float64)
    print(f"loaded d2-v2: {len(y_train)} train rows, {len(y_val)} val rows ({time.time() - t0:.0f} s)", flush=True)

    w, b, candidates = np.zeros(x_train.shape[1]), 0.0, []
    for alpha in ALPHAS:  # warm start each alpha from the previous fit
        t = time.time()
        w, b, history = fit(x_train, z_train, y_train, alpha, w, b)
        pv = predict(x_val, z_val, w, b)
        candidates.append({"alpha": alpha, "w": w.copy(), "b": b, "iterations": len(history) - 1,
                           "train_loss": history[-1], "val_mse": float(np.mean((pv - y_val) ** 2)),
                           "val_mae": float(np.mean(np.abs(pv - y_val)))})
        print(f"alpha {alpha:g}: {len(history) - 1} iterations, val MSE {candidates[-1]['val_mse']:.7f}, "
              f"val MAE {candidates[-1]['val_mae']:.6f} ({time.time() - t:.0f} s)", flush=True)
    best = min(candidates, key=lambda c: c["val_mse"])

    eval_arrays, eval_source = load_dataset(check)
    data = mask_split(eval_arrays, "train")
    y, games, parents = data["y"].astype(np.float64), data["game_id"], data["parent"]
    preds = {"tanh_linear": predict(design(data), base_logit(data["d1"]), best["w"], best["b"]),
             "linear": LinearCorrection.load(plain_path).predict(data["planes"], data["d1"], packed=True),
             "d1": data["d1"].astype(np.float64)}
    ckpt = torch.load(Path(net_dir) / "best.pt", map_location="cpu", weights_only=True)
    if ckpt.get("encoding") != ENCODING:
        raise ValueError("Network 1 checkpoint has incompatible encoding")
    net = Network1(**ckpt["config"])
    net.load_state_dict(ckpt["state_dict"])
    preds["network"] = net1_predict(net, torch.from_numpy(data["planes"]), torch.from_numpy(data["d1"])).numpy()

    err = {k: np.abs(v - y) for k, v in preds.items()}
    pairs = (("tanh_linear", "linear"), ("tanh_linear", "network"), ("tanh_linear", "d1"), ("network", "linear"))
    bands = {"close |y|<0.3": np.abs(y) < 0.3, "middle 0.3-0.9": (np.abs(y) >= 0.3) & (np.abs(y) <= 0.9),
             "decided |y|>0.9": np.abs(y) > 0.9}
    report = {
        "question": "linear correction inside tanh(atanh(d1) + ...) versus the plain linear correction and Network 1",
        "fit": {"data": fit_source["dataset"], "sha256": fit_source["sha256"], "train_rows": len(y_train),
                "val_rows": len(y_val), "selected_alpha": best["alpha"],
                "candidates": [{k: v for k, v in c.items() if k != "w"} for c in candidates]},
        "eval": {"data": eval_source["dataset"], "sha256": eval_source["sha256"], "split": "train",
                 "rows": len(y), "decisions": int(len(np.unique(parents))), "games": int(len(np.unique(games)))},
        "scorers": {k: metrics(v, data) for k, v in preds.items()},
        "mae_difference": {f"{a} - {c}": paired_difference(err[a], err[c], games) for a, c in pairs},
        "regret_difference": {f"{a} - {c}": paired_regret_difference(parents, preds[a], preds[c], y, games=games)
                              for a, c in pairs},
        "bands": {name: {"share": float(m.mean()), **{k: float(e[m].mean()) for k, e in err.items()}}
                  for name, m in bands.items()},
        "seconds": round(time.time() - t0),
    }
    np.savez_compressed(out / "tanh-linear.npz", w=best["w"], b=best["b"], alpha=best["alpha"])
    (out / "tanh-linear-d2-check-train.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("scorers", "mae_difference", "bands")}, indent=2))


if __name__ == "__main__":
    main()
