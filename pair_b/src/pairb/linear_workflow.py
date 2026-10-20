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

CONTENT_KEY = "sha1 of the game's sorted unique parent FENs, one per line; first 16 hex characters"


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


def content_keys(arrays):
    """{game_id: content key} for every game in `arrays` (CONTENT_KEY). Generated datasets all
    number their games g-000000, g-000001, ..., so across two datasets one ID is usually two
    different games; the positions a game decides at say which game it is."""
    fens = {}
    for game, parent in zip(arrays["game_id"].tolist(), arrays["parent"].tolist()):
        fens.setdefault(game, set()).add(parent.rsplit("|", 1)[1])  # parent is "<game_id>|<parent FEN>"
    return {game: hashlib.sha1("\n".join(sorted(f)).encode()).hexdigest()[:16] for game, f in fens.items()}


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
    keys = content_keys(arrays)
    splits = {"train": games["train"], "val": games["val"], "test_held_out_games": len(games["test"]),
              # parallel to the train and val ID lists, for evaluations on other datasets
              "content_keys": {"definition": CONTENT_KEY,
                               **{s: [keys[g] for g in games[s]] for s in ("train", "val")}}}
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
    fitted = model.metadata.get("splits", {})
    id_overlap = {s: len(games & set(fitted.get(s, []))) for s in ("train", "val")}
    evidence = bool(model.metadata.get("source")) and all(key in fitted for key in ("train", "val"))
    # Validation on the original run is expected, but is explicitly not independent evidence.
    same_source = source["sha256"] == model.metadata.get("source", {}).get("sha256")
    stored = fitted.get("content_keys", {})
    if same_source or not all(isinstance(stored.get(s), list) for s in ("train", "val")):
        # The fitting dataset itself: an ID is a game. A model saved without content keys can
        # only be checked by ID, which over-counts on another dataset.
        basis, seen = "game_id", id_overlap
    else:
        # Another dataset: the same ID may be a different game, so compare the games themselves.
        keys = list(content_keys(data).values())
        fitted_keys = {s: set(stored[s]) for s in ("train", "val")}
        basis, seen = "content", {s: sum(k in fitted_keys[s] for k in keys) for s in ("train", "val")}
    if (seen["train"] or (seen["val"] and not same_source)) and not allow_seen_games:
        raise ValueError(f"evaluation games overlap fitting/selection games (compared by {basis}); use a "
                         "disjoint dataset or explicitly pass --allow-seen-games for diagnostics only")
    pred = model.predict(data["planes"], data["d1"], packed=True)
    return {"source": source, "split": split, "n": len(data["y"]), "games": len(games),
            "fitting_game_overlap": seen["train"], "selection_game_overlap": seen["val"],
            "overlap_basis": basis, "game_id_overlap": id_overlap,
            "independent_games": not (seen["train"] or seen["val"]) if evidence else None,
            "split_evidence_available": evidence,
            "bootstrap": {"resamples": n_boot, "seed": 0, "unit": "whole games"},
            "linear": metrics(pred, data), "baseline": metrics(data["d1"], data),
            "material": metrics(material_prediction(data["planes"]), data),
            "regret_difference": paired_regret_difference(data["parent"], pred, data["d1"], data["y"],
                                                          games=data["game_id"], n_boot=n_boot),
            "runtime": runtime()}


def network_split_evidence(splits, model, data, report, *, allow_seen_games=False):
    """Network 1's overlap with the evaluated games (`data`, the rows `report` scored), from its
    splits.json, which lists game IDs only. When its train and val games are the linear model's,
    the linear model's overlap in `report` holds for it too (by content on another dataset);
    otherwise its IDs are compared with the evaluated games' IDs."""
    if not isinstance(splits, dict) or not all(
            isinstance(splits.get(k), list) and all(isinstance(g, str) for g in splits[k]) for k in ("train", "val")):
        raise ValueError("Network 1 split evidence must contain train and val game lists")
    games = set(data["game_id"].tolist())
    id_overlap = {k: len(games & set(splits[k])) for k in ("train", "val")}
    fitted = model.metadata.get("splits", {})
    same_games = report["split_evidence_available"] and all(set(splits[k]) == set(fitted[k]) for k in ("train", "val"))
    if same_games:
        overlaps = {"train": report["fitting_game_overlap"], "val": report["selection_game_overlap"]}
        basis = report["overlap_basis"]
    else:
        overlaps, basis = id_overlap, "game_id"
    if any(overlaps.values()) and not allow_seen_games:
        raise ValueError(f"Network 1 evaluation overlaps fitting/selection games (compared by {basis}); "
                         "use --allow-seen-games for diagnostics only")
    return {"overlaps": overlaps, "overlap_basis": basis, "game_id_overlap": id_overlap,
            "same_games_as_linear": same_games, "independent_games": not any(overlaps.values())}
