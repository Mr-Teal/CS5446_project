"""Kuhn poker: Nash gap against rounds for PCFR+ and for the same solver with zero predictions.

    python pair_b/experiments/small_games/run_kuhn_control.py --out pair_b/experiments/small_games/kuhn-gap-vs-rounds.json

Run from a repository root that has Pair A's `pair_a_prep/pcfr.py` and `toy_games.py` on the path (their
branch, or main once #15 merges), with Pair A's environment (NumPy and SciPy). Both solvers use the
alternating schedule and PCFR+'s quadratic averaging; the control differs only in `predictive=False`, so
it is "PCFR+ with zero predictions", not the published CFR+. Writes one JSON with, for each solver, the
last and average iterate's value and Nash gap at log-spaced checkpoints, a summary of the last iterate's
gap over every round (the checkpoints can miss its dips), the LP value for reference, and the SHA-256 of
the Pair A files that ran with the Python and NumPy versions. Pair A's code is imported, never changed.
About a minute and a half: the metrics are computed after every round.
"""
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

CHECKPOINTS = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000, 2000]
GAP_LEVELS = (0.02, 1e-12)  # the levels the README's sentences use


def curve(predictive: bool, rounds: list[int]) -> tuple[list[dict], list[float]]:
    """The checkpoints' metrics, and the last iterate's Nash gap after every round."""
    from pair_a_prep.pcfr import PCFRPlus
    from pair_a_prep.toy_games import kuhn_poker
    solver = PCFRPlus(kuhn_poker(), predictive=predictive, schedule="alternating")
    keep, out, gaps = set(rounds), [], []
    for r in range(1, rounds[-1] + 1):
        solver.run(1)
        m = solver.metrics()
        assert m["rounds"] == r, (m["rounds"], r)
        gaps.append(m["last"]["nash_gap"])
        if r in keep:
            out.append({"rounds": m["rounds"], "last": dict(m["last"]), "average": dict(m["average"])})
    return out, gaps


def every_round(gaps: list[float]) -> dict:
    """The last iterate's gap over all rounds: its minimum and where, how many rounds are below each
    level, the first round from which it stays below (None if it does not), and how many rounds print
    as exactly 0 (which depends on the machine's floating point; Pair A's run gives about 3e-17)."""
    low = min(range(len(gaps)), key=gaps.__getitem__)
    below = {}
    for level in GAP_LEVELS:
        stays = None
        for i in range(len(gaps) - 1, -1, -1):
            if gaps[i] >= level:
                break
            stays = i + 1
        below[f"{level:g}"] = {"rounds": sum(g < level for g in gaps), "stays_below_from_round": stays}
    return {"rounds": len(gaps), "min": gaps[low], "min_round": low + 1, "below": below,
            "exactly_zero_rounds": sum(g == 0.0 for g in gaps)}


def provenance() -> dict:
    import numpy
    import pair_a_prep.pcfr
    import pair_a_prep.toy_games
    files = {f"pair_a_prep/{Path(m.__file__).name}": hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
             for m in (pair_a_prep.pcfr, pair_a_prep.toy_games)}
    return {"pair_a_sha256": files, "python": platform.python_version(), "numpy": numpy.__version__,
            "platform": platform.platform()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=2000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference", help="Pair A's pcfr_alternating_reference.json, for the LP value of Kuhn poker")
    args = ap.parse_args()
    rounds = [r for r in CHECKPOINTS if r <= args.rounds]
    if rounds[-1] != args.rounds:
        rounds.append(args.rounds)
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new file")
    (plus, plus_gaps), (zero, zero_gaps) = curve(True, rounds), curve(False, rounds)
    report = {"game": "kuhn_poker", "schedule": "alternating", "averaging_power": 2,
              "solvers": {"pcfr_plus": plus, "zero_predictions": zero},
              "note": "zero_predictions is PCFR+ with predictive=False: the same quadratic averaging and "
                      "alternating schedule, so not the published CFR+"}
    report["oracle_value"] = (json.loads(Path(args.reference).read_text())["games"]["kuhn"]["oracle_value"]
                              if args.reference else -1 / 18)
    report["last_gap_every_round"] = {"pcfr_plus": every_round(plus_gaps), "zero_predictions": every_round(zero_gaps)}
    report["provenance"] = provenance()
    out.write_text(json.dumps(report, indent=1) + "\n")
    for name, points in report["solvers"].items():
        print(name, " ".join(f"{p['rounds']}:{p['last']['nash_gap']:.2e}/{p['average']['nash_gap']:.2e}" for p in points))


if __name__ == "__main__":
    main()
