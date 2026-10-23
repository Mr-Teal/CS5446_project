"""Draw the Kuhn-poker Nash-gap figure as SVG, with no third-party library.

    python make_gap_figure.py --curves kuhn-gap-vs-rounds.json --out kuhn-gap-vs-rounds.svg [--reference pcfr_alternating_reference.json] [--check]

`--curves` is the file run_kuhn_control.py writes. `--reference` is Pair A's committed
pcfr_alternating_reference.json: with it, `--check` compares the PCFR+ curve with the reference at the
checkpoints they share (rounds 1, 10, 100, 1000, 2000) and fails if any gap differs by more than 1e-9.
Gaps at or below the floor of the log axis (1e-7) are drawn on the floor line; a gap below 1e-12 (zero up to
rounding: one machine prints 0, another about 3e-17) gets a hollow marker.
"""
import argparse
import json
import math
import sys
from pathlib import Path

FLOOR = 1e-7
ZERO = 1e-12  # below this a gap is zero up to rounding, and gets a hollow marker
SERIES = [("pcfr_plus", "last", "PCFR+, last iterate", "#1f4e9c", ""),
          ("pcfr_plus", "average", "PCFR+, average iterate", "#1f4e9c", "6 4"),
          ("zero_predictions", "last", "zero predictions, last iterate", "#b5531c", ""),
          ("zero_predictions", "average", "zero predictions, average iterate", "#b5531c", "6 4")]


def draw(curves: dict, out: Path) -> dict:
    width, height, left, right, top, bottom = 720, 420, 70, 20, 40, 70
    rounds = sorted({p["rounds"] for s in curves["solvers"].values() for p in s})
    x0, x1 = math.log10(rounds[0]), math.log10(rounds[-1])
    ylo, yhi = math.log10(FLOOR), 0.0

    def X(r):
        return left + (math.log10(r) - x0) / (x1 - x0) * (width - left - right)

    def Y(gap):
        return top + (yhi - math.log10(max(gap, FLOOR))) / (yhi - ylo) * (height - top - bottom)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'font-family="Helvetica, Arial, sans-serif" font-size="12">',
             f'<rect width="{width}" height="{height}" fill="white"/>',
             f'<text x="{left}" y="22" font-size="14" font-weight="bold">Kuhn poker: Nash gap against rounds (alternating updates)</text>']
    for e in range(int(ylo), 1):
        y = Y(10 ** e)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#ddd"/>')
        label = "1e-7 or less" if e == int(ylo) else f"1e{e}"
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{label}</text>')
    for r in (1, 10, 100, 1000):
        if r <= rounds[-1]:
            x = X(r)
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}" stroke="#eee"/>')
            parts.append(f'<text x="{x:.1f}" y="{height - bottom + 16}" text-anchor="middle">{r}</text>')
    parts.append(f'<text x="{(left + width - right) / 2:.1f}" y="{height - bottom + 34}" text-anchor="middle">rounds</text>')
    parts.append(f'<text transform="translate(16,{(top + height - bottom) / 2:.1f}) rotate(-90)" text-anchor="middle">Nash gap</text>')
    drawn = {}
    for solver, which, label, colour, dash in SERIES:
        points = curves["solvers"][solver]
        pts = [(X(p["rounds"]), Y(p[which]["nash_gap"])) for p in points]
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(f'<polyline points="{d}" fill="none" stroke="{colour}" stroke-width="2" stroke-dasharray="{dash}"/>')
        for (x, y), p in zip(pts, points):
            exact = p[which]["nash_gap"] < ZERO
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{"white" if exact else colour}" stroke="{colour}"/>')
        drawn[f"{solver}/{which}"] = [(p["rounds"], p[which]["nash_gap"]) for p in points]
    for i, (_, _, label, colour, dash) in enumerate(SERIES):
        y = height - bottom - 70 + i * 16
        parts.append(f'<line x1="{left + 12}" y1="{y}" x2="{left + 40}" y2="{y}" stroke="{colour}" stroke-width="2" stroke-dasharray="{dash}"/>')
        parts.append(f'<text x="{left + 46}" y="{y + 4}">{label}</text>')
    parts.append(f'<text x="{left + 12}" y="{height - bottom - 78}" font-size="11" fill="#555">hollow marker: a gap below 1e-12 (zero up to rounding)</text>')
    parts.append('</svg>\n')
    out.write_text("\n".join(parts))
    return drawn


def check(curves: dict, reference: dict) -> None:
    ref = {p["rounds"]: p for p in reference["games"]["kuhn"]["trace"]}
    worst = 0.0
    for p in curves["solvers"]["pcfr_plus"]:
        if p["rounds"] in ref:
            for which in ("last", "average"):
                diff = abs(p[which]["nash_gap"] - ref[p["rounds"]][which]["nash_gap"])
                worst = max(worst, diff)
                print(f"rounds {p['rounds']:5d} {which:7s} gap {p[which]['nash_gap']:.3e} reference {ref[p['rounds']][which]['nash_gap']:.3e}")
    if worst > 1e-9:
        sys.exit(f"the PCFR+ curve differs from the reference by {worst:.1e}")
    print("PCFR+ matches the committed reference at every shared checkpoint")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--curves", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    curves = json.loads(Path(args.curves).read_text())
    drawn = draw(curves, Path(args.out))
    if args.check:
        for name, points in drawn.items():
            print(name, " ".join(f"{r}:{g:.2e}" for r, g in points))
        if args.reference:
            check(curves, json.loads(Path(args.reference).read_text()))


if __name__ == "__main__":
    main()
