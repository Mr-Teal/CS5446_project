"""Check that mc_td.py's 750-column design fits the same model as the 1,217 inputs.

    python check_reparam.py <d2-check> <runs/linear-tanh/linear_tanh.py> <out.json>

Fits d11 on the first 8,000 of d2-check's val-bucket rows with linear_tanh.fit on
pairb.linear.features' 1,217 columns, and with mc_td.fit on the 750 columns, both from zero with the
same alpha, then compares losses, weights (mapped back to 1,217) and predictions on every val-bucket
row. It touches no train-bucket (evaluation) or test-bucket row.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_td  # noqa: E402
from pairb.linear_workflow import load_dataset, mask_split  # noqa: E402


def main():
    check, ref_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    spec = importlib.util.spec_from_file_location("linear_tanh", ref_path)
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    arrays, source = load_dataset(check)
    test_rows = mask_split(arrays, "val")
    fit_rows = {k: v[:8000] for k, v in test_rows.items()}
    y = fit_rows["y"].astype(np.float64)
    report = {"data": source["dataset"], "sha256": source["sha256"], "fit_rows": len(y),
              "compare_rows": len(test_rows["y"]), "fits": []}
    for alpha in (1e-4, 1e-2):
        t = time.time()
        x_full = ref.design(fit_rows)
        z0 = ref.base_logit(fit_rows["d1"])
        w, b, hist_full = ref.fit(x_full, z0, y, alpha, np.zeros(x_full.shape[1]), 0.0)
        t_full = time.time() - t
        t = time.time()
        rows = mc_td.Rows(mc_td.design(fit_rows["planes"], fit_rows["d1"]), fit_rows["d1"])
        c, b2, hist_red = mc_td.fit(rows, y, alpha, np.zeros(mc_td.K), 0.0)
        t_red = time.time() - t
        w2 = mc_td.full_weights(c)
        p_full = ref.predict(ref.design(test_rows), ref.base_logit(test_rows["d1"]), w, b)
        p_red = mc_td.predict(mc_td.Rows(mc_td.design(test_rows["planes"], test_rows["d1"]), test_rows["d1"]), c, b2)
        p_mapped = ref.predict(ref.design(test_rows), ref.base_logit(test_rows["d1"]), w2, b2)
        report["fits"].append({
            "alpha": alpha,
            "full_1217": {"iterations": len(hist_full) - 1, "loss": hist_full[-1], "seconds": round(t_full, 1)},
            "reduced_750": {"iterations": len(hist_red) - 1, "loss": hist_red[-1], "seconds": round(t_red, 1)},
            "loss_difference": hist_red[-1] - hist_full[-1],
            "max_abs_weight_difference": float(np.max(np.abs(w2 - w))),
            "intercept_difference": float(b2 - b),
            "max_abs_prediction_difference": float(np.max(np.abs(p_red - p_full))),
            "mean_abs_prediction_difference": float(np.mean(np.abs(p_red - p_full))),
            "mapped_weights_reproduce_reduced_predictions": float(np.max(np.abs(p_mapped - p_red))),
            "mae_vs_d11_on_compare_rows": {"full": float(np.mean(np.abs(p_full - test_rows["y"]))),
                                "reduced": float(np.mean(np.abs(p_red - test_rows["y"])))},
        })
        print(json.dumps(report["fits"][-1], indent=2), flush=True)
    out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
