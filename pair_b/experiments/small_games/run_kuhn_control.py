"""Kuhn poker: Nash gap against rounds for PCFR+ and for the same solver with zero predictions.

    python pair_b/experiments/small_games/run_kuhn_control.py --out pair_b/experiments/small_games/kuhn-gap-vs-rounds.json

Run from a repository root that has Pair A's `pair_a_prep/pcfr.py` and `toy_games.py` on the path (their
branch, or main once #15 merges), with Pair A's environment (NumPy and SciPy). Both solvers use the
alternating schedule and PCFR+'s quadratic averaging; the control differs only in `predictive=False`, so
it is "PCFR+ with zero predictions", not the published CFR+. Writes one JSON with, for each solver, the
last and average iterate's value and Nash gap at log-spaced checkpoints, plus the LP value for reference.
Pair A's code is imported, never changed. About a second.
"""
import argparse
import json
import sys
from pathlib import Path

CHECKPOINTS = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000, 2000]


def curve(predictive: bool, rounds: list[int]) -> list[dict]:
    from pair_a_prep.pcfr import PCFRPlus
    from pair_a_prep.toy_games import kuhn_poker
    solver = PCFRPlus(kuhn_poker(), predictive=predictive, schedule="alternating")
    done, out = 0, []
    for target in rounds:
        solver.run(target - done)
        done = target
        m = solver.metrics()
        out.append({"rounds": m["rounds"], "last": dict(m["last"]), "average": dict(m["average"])})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=2000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference", help="Pair A's pcfr_alternating_reference.json, for the LP value of Kuhn poker")
    args = ap.parse_args()
    rounds = [r for r in CHECKPOINTS if r <= args.rounds]
    if rounds[-1] != args.rounds:
        rounds.append(args.rounds)
    report = {"game": "kuhn_poker", "schedule": "alternating", "averaging_power": 2,
              "solvers": {"pcfr_plus": curve(True, rounds),
                          "zero_predictions": curve(False, rounds)},
              "note": "zero_predictions is PCFR+ with predictive=False: the same quadratic averaging and "
                      "alternating schedule, so not the published CFR+"}
    report["oracle_value"] = (json.loads(Path(args.reference).read_text())["games"]["kuhn"]["oracle_value"]
                              if args.reference else -1 / 18)
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new file")
    out.write_text(json.dumps(report, indent=1) + "\n")
    for name, points in report["solvers"].items():
        print(name, " ".join(f"{p['rounds']}:{p['last']['nash_gap']:.2e}/{p['average']['nash_gap']:.2e}" for p in points))


if __name__ == "__main__":
    main()
