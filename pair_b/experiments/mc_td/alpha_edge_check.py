"""Check the bottom of the alpha grid at full data: Distil, MC and TD(lambda) picked 1e-5, the
smallest value tried. Fits alpha = 1e-6 for each, the same way as mc_td.py (Distil and MC plain fits
from zero; TD(lambda) fitted value iteration with the same stopping rule and cap), and reports the
validation error that would decide between them and the evaluation scores.

    python alpha_edge_check.py <d2-v2> <d2-check> <d2-v2 trajectories> <d2-check trajectories> <out.json>
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_td  # noqa: E402
from pairb.linear_workflow import load_dataset, mask_split, metrics  # noqa: E402

ALPHA = 1e-6


def main():
    v2, check, traj_v2, traj_check, out = (Path(a) for a in sys.argv[1:6])
    t0 = time.time()
    arrays, _ = load_dataset(v2)
    train, val = mask_split(arrays, "train"), mask_split(arrays, "val")
    del arrays
    d_train = mc_td.Rows(mc_td.design(train["planes"], train["d1"]), train["d1"])
    d_val = mc_td.Rows(mc_td.design(val["planes"], val["d1"]), val["d1"])
    y_train, y_val = train["y"].astype(np.float64), val["y"].astype(np.float64)
    del train["planes"], val["planes"]
    tr, _ = mc_td.load_trajectories(traj_v2, "train")
    va, _ = mc_td.load_trajectories(traj_v2, "val")
    r_train = mc_td.Rows(mc_td.design(tr["planes"], tr["d1"]), tr["d1"])
    r_val = mc_td.Rows(mc_td.design(va["planes"], va["d1"]), va["d1"])
    check_arrays, _ = load_dataset(check)
    value = mask_split(check_arrays, "train")
    del check_arrays
    value_rows = mc_td.Rows(mc_td.design(value["planes"], value["d1"]), value["d1"])
    ev, _ = mc_td.load_trajectories(traj_check, "train")
    ev_rows = mc_td.Rows(mc_td.design(ev["planes"], ev["d1"]), ev["d1"])

    def scores(c, b):
        pv, po = mc_td.predict(value_rows, c, b), mc_td.predict(ev_rows, c, b)
        m = metrics(pv, value)
        return {"value_mae": m["mae"], "choice": m["choice"], "outcome_mse": mc_td.mse(po, ev["z"])}

    report = {"alpha": ALPHA, "methods": {}}
    t = time.time()
    c, b, hist = mc_td.fit(d_train, y_train, ALPHA, np.zeros(mc_td.K), 0.0)
    report["methods"]["distil"] = {"iterations": len(hist) - 1, "val_mse": mc_td.mse(mc_td.predict(d_val, c, b), y_val),
                                   **scores(c, b), "seconds": round(time.time() - t, 1)}
    print("distil", report["methods"]["distil"], flush=True)
    t = time.time()
    c, b, hist = mc_td.fit(r_train, tr["z"], ALPHA, np.zeros(mc_td.K), 0.0)
    report["methods"]["mc"] = {"iterations": len(hist) - 1, "val_mse": mc_td.mse(mc_td.predict(r_val, c, b), va["z"]),
                               **scores(c, b), "seconds": round(time.time() - t, 1)}
    print("mc", report["methods"]["mc"], flush=True)
    t = time.time()
    best, cands = mc_td.td_path(r_train, tr["z"], mc_td.td_levels(tr["dist"]), tr["last_target"], r_val, va["z"],
                                mc_td.LAMBDA, (ALPHA,), mc_td.MAX_ROUNDS)
    report["methods"]["tdlambda"] = {"rounds_run": best["rounds_run"], "best_round": best["best_round"],
                                     "val_mse": best["val_mse"], **scores(best["c"], best["b"]),
                                     "seconds": round(time.time() - t, 1)}
    print("tdlambda", report["methods"]["tdlambda"], flush=True)
    report["seconds"] = round(time.time() - t0, 1)
    out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
