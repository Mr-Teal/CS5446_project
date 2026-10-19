"""Training/evaluation helpers for the NumPy baseline; no torch imports."""
import hashlib
import json
import platform
from pathlib import Path

import chess
import numpy as np

from .data import ENCODING, build_arrays, read_records, split_of
from .linear import fit_candidates
from .metrics import choice_metrics, paired_regret_difference


def write_json(path, value):
    with open(path, "x") as f:
        f.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def provenance(folder):
    folder = Path(folder)
    files = sorted(folder.glob("part-*.jsonl"))
    if not files:
        raise ValueError("no part-*.jsonl records found")
    manifest = folder / "manifest.json"
    if manifest.exists():
        files.append(manifest)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"dataset": folder.name, "files_sha256": hashes,
            "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}


def load_dataset(folder):
    source = provenance(folder)
    records = read_records(folder)
    if any(not isinstance(r.get("game_id"), str) or not r["game_id"].strip() for r in records):
        raise ValueError("every record must have a nonblank game_id")
    arrays = build_arrays(records)  # do not trust a cache keyed only by manifest metadata
    if not len(arrays["y"]):
        raise ValueError("dataset has no non-rule training rows")
    # Prevent associating read data with different bytes if a label run is still writing.
    if source != provenance(folder):
        raise ValueError("dataset changed while reading; use a finished label run")
    source["records"] = len(records)
    source["non_rule_rows"] = len(arrays["y"])
    source["rule_rows_excluded"] = len(records) - len(arrays["y"])
    return arrays, source


def mask_split(arrays, split):
    mask = np.array([split_of(g) == split for g in arrays["game_id"]])
    if not mask.any():
        raise ValueError(f"dataset has no non-rule rows in {split} split")
    return {k: v[mask] for k, v in arrays.items()}


def metrics(pred, arrays):
    y, d1 = arrays["y"], arrays["d1"]
    err = np.abs(np.asarray(pred) - y)
    def mean(values):
        return float(np.mean(values)) if len(values) else None
    return {"mse": mean(err ** 2), "mae": mean(err),
            "mae_close": mean(err[np.abs(y) < 0.3]),
            "mae_decided": mean(err[np.abs(y) > 0.9]),
            "mae_close_by_d1": mean(err[np.abs(d1) < 0.3]),
            "choice": choice_metrics(arrays["parent"], pred, y)}


def material_prediction(planes):
    counts = planes[:, :12].astype(np.float64).sum(axis=(2, 3))
    return np.tanh(((counts[:, :6] - counts[:, 6:]) @ np.array([100,300,300,500,900,0])) / 600)


def runtime():
    root = Path(__file__).resolve().parents[2]
    paths = sorted([*root.glob("src/pairb/*.py"), *root.glob("scripts/*.py"),
                    *root.parent.glob("fow_shared/*.py")])
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root.parent)).encode())
        digest.update(path.read_bytes())
    return {"python": platform.python_version(), "platform": platform.platform(),
            "numpy": np.__version__, "python_chess": chess.__version__,
            "source_sha256": digest.hexdigest()}


def train(folder, out, alphas):
    arrays, source = load_dataset(folder)
    training, validation = (mask_split(arrays, s) for s in ("train", "val"))
    candidates = fit_candidates(training["planes"], training["d1"], training["y"], alphas)
    rows = [metrics(m.predict(validation["planes"], validation["d1"], packed=True), validation)
            for m in candidates]
    best = min(range(len(rows)), key=lambda i: rows[i]["mse"])
    model = candidates[best]
    games = {s: sorted(set(arrays["game_id"][[split_of(g) == s for g in arrays["game_id"]]].tolist()))
             for s in ("train", "val", "test")}
    splits = {"train": games["train"], "val": games["val"], "test_held_out_games": len(games["test"])}
    model.metadata = {"source": source, "splits": splits, "encoding": ENCODING,
                      "selection": "minimum validation MSE after clipping; first alpha wins ties",
                      "runtime": runtime()}
    summary = {**model.metadata, "selected_alpha": model.alpha,
               "n_train": len(training["y"]), "n_val": len(validation["y"]),
               "candidates": [{"alpha": m.alpha, "validation": row} for m, row in zip(candidates, rows)],
               "validation_d1": metrics(validation["d1"], validation)}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    model.save(out / "best.npz")
    write_json(out / "splits.json", splits)
    write_json(out / "summary.json", summary)
    return summary


def evaluate(model, arrays, source, split, *, n_boot=2000, allow_seen_games=False):
    if n_boot < 1:
        raise ValueError("n_boot must be positive")
    data = mask_split(arrays, split)
    games = set(data["game_id"].tolist())
    trained = set(model.metadata.get("splits", {}).get("train", []))
    selected = set(model.metadata.get("splits", {}).get("val", []))
    seen_train, seen_val = games & trained, games & selected
    evidence = bool(model.metadata.get("source")) and all(
        key in model.metadata.get("splits", {}) for key in ("train", "val"))
    # Validation on the original run is expected, but is explicitly not independent evidence.
    same_source = source["sha256"] == model.metadata.get("source", {}).get("sha256")
    if (seen_train or (seen_val and not same_source)) and not allow_seen_games:
        raise ValueError("evaluation game IDs overlap fitting/selection games; use a disjoint dataset "
                         "or explicitly pass --allow-seen-games for diagnostics only")
    pred = model.predict(data["planes"], data["d1"], packed=True)
    return {"source": source, "split": split, "n": len(data["y"]), "games": len(games),
            "fitting_game_overlap": len(seen_train), "selection_game_overlap": len(seen_val),
            "independent_games": not bool(seen_train or seen_val) if evidence else None,
            "split_evidence_available": evidence,
            "bootstrap": {"resamples": n_boot, "seed": 0, "unit": "whole games"},
            "linear": metrics(pred, data), "baseline": metrics(data["d1"], data),
            "material": metrics(material_prediction(data["planes"]), data),
            "regret_difference": paired_regret_difference(data["parent"], pred, data["d1"], data["y"],
                                                          games=data["game_id"], n_boot=n_boot),
            "runtime": runtime()}
