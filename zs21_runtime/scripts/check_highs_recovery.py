"""Reproduce both historical Not Set cases and verify bounded recovery."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import scipy
from scipy.optimize._highspy._core import _Highs
from pair_a_prep.zs21.lp_diagnostics import load_form
from pair_a_prep.zs21.sequence_form import LinearProgramError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RUNTIME / "out/highs-recovery.json")
    args = parser.parse_args()
    report = dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                  highs=_Highs().version(), certificate_threshold=1e-8, cases=[])
    for stem in ("zs21_lp_not_set_game001_ply61", "zs21_lp_not_set_game006_ply68"):
        path = ROOT / "pair_a_prep/tests/fixtures" / (stem + ".npz")
        form = load_form(path)
        row = dict(fixture=path.relative_to(ROOT).as_posix(), sha256=sha256(path.read_bytes()).hexdigest())
        try:
            form.solve(refine=False)
        except LinearProgramError as exc:
            assert exc.retryable_not_set
            row["original_error"] = str(exc)
            row["original_attempts"] = form.solve_attempts
        else:
            raise AssertionError("The pinned failure was not reproduced in this environment")
        started = perf_counter()
        result = form.solve(deadline=started+30)
        row.update(seconds=perf_counter()-started, value=result.value, gap=result.upper-result.lower,
                   flow_error=result.flow_error, inequality_error=result.inequality_error,
                   attempts=result.precision_attempts)
        assert abs(row["gap"]) <= 1e-8 and row["flow_error"] <= 1e-8 and row["inequality_error"] <= 1e-8
        assert min(result.x.min(), result.y.min()) >= 0
        report["cases"].append(row)
    report["source_sha256"] = {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        "pair_a_prep/zs21/sequence_form.py", "pair_a_prep/tests/test_zs21_not_set.py",
        "zs21_runtime/scripts/check_highs_recovery.py")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(dict(output=str(args.output), recovered=len(report["cases"]),
                          gaps=[c["gap"] for c in report["cases"]])))


if __name__ == "__main__":
    main()
