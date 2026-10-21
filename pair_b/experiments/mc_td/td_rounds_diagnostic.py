"""Diagnostic for the 15-round cap: run fitted value iteration past it at full data.

    python td_rounds_diagnostic.py <d2-v2 trajectories.jsonl> <d2-check> <d2-check trajectories.jsonl>
                                   <results.json> <out.json> [--rounds 40]

For TD(0) and TD(lambda) at the alpha results.json selected at full data, runs the same rounds as
mc_td.td_path (same start, same warm starts, same fits) but without the stopping rule, and scores
every round on the validation trajectories and on d2-check's evaluation rows. The main results keep
the brief's rule (stop when validation error stops improving, cap 15); this only shows what the cap
costs.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_td  # noqa: E402
from pairb.linear_workflow import load_dataset, mask_split  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    for name in ("traj_v2", "check", "traj_check", "results", "out"):
        ap.add_argument(name, type=Path)
    ap.add_argument("--rounds", type=int, default=40)
    a = ap.parse_args()
    traj_v2, check, traj_check, results_path, out, rounds = a.traj_v2, a.check, a.traj_check, a.results, a.out, a.rounds
    results = json.loads(results_path.read_text())
    full = results["curves"][-1]
    t0 = time.time()
    train, _ = mc_td.load_trajectories(traj_v2, "train")
    val, _ = mc_td.load_trajectories(traj_v2, "val")
    rows, rows_val = (mc_td.Rows(mc_td.design(d["planes"], d["d1"]), d["d1"]) for d in (train, val))
    arrays, _ = load_dataset(check)
    value = mask_split(arrays, "train")
    del arrays
    value_rows = mc_td.Rows(mc_td.design(value["planes"], value["d1"]), value["d1"])
    ev, _ = mc_td.load_trajectories(traj_check, "train")
    ev_rows = mc_td.Rows(mc_td.design(ev["planes"], ev["d1"]), ev["d1"])
    levels = mc_td.td_levels(train["dist"])
    y_value = value["y"].astype(np.float64)
    report = {"rounds_cap_in_main_run": mc_td.MAX_ROUNDS, "rounds_run_here": rounds, "methods": {}}
    for method, lam in (("td0", 0.0), ("tdlambda", mc_td.LAMBDA)):
        alpha = full["methods"][method]["selected"]["alpha"]
        c, b = np.zeros(mc_td.K), 0.0
        v = mc_td.predict(rows, c, b)
        history = []
        for r in range(1, rounds + 1):
            t = time.time()
            y = mc_td.td_targets(v, levels, train["last_target"], lam)
            c, b, hist = mc_td.fit(rows, y, alpha, c, b)
            v_prev, v = v, mc_td.predict(rows, c, b)
            pv, po = mc_td.predict(value_rows, c, b), mc_td.predict(ev_rows, c, b)
            history.append({"round": r, "iterations": len(hist) - 1,
                            "val_mse": mc_td.mse(mc_td.predict(rows_val, c, b), val["z"]),
                            "value_mae": float(np.mean(np.abs(pv - y_value))),
                            "outcome_mse": mc_td.mse(po, ev["z"]),
                            "mean_abs_change_in_train_values": float(np.mean(np.abs(v - v_prev))),
                            "seconds": round(time.time() - t, 1)})
            print(method, json.dumps(history[-1]), flush=True)
        report["methods"][method] = {"alpha": alpha, "history": history}
    report["seconds"] = round(time.time() - t0, 1)
    out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
