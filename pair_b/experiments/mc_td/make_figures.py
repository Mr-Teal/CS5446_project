"""Learning-curve figures and the markdown tables, from results.json only (no repo imports).

    python make_figures.py <results.json> <out dir>

Writes curve-value-error.png, curve-outcome-error.png and tables.md. Needs matplotlib (the repo's
venv has none; any Python with matplotlib and NumPy will do, since this reads only the JSON).
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

LABELS = {"distil": "Distil (d11 labels)", "mc": "MC (game result)", "td0": "TD(0)", "tdlambda": "TD(λ), λ = 0.8"}
STYLE = {"distil": dict(color="#1f77b4", marker="o"), "mc": dict(color="#d62728", marker="s"),
         "td0": dict(color="#2ca02c", marker="^"), "tdlambda": dict(color="#9467bd", marker="D")}


def curve(results, key, ylabel, title, ref, ref_label, path):
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=150)
    games = [p["games"] for p in results["curves"]]
    for m, label in LABELS.items():
        ys = [key(p["methods"][m]) for p in results["curves"]]
        ax.plot(games, ys, label=label, linewidth=2, markersize=6, **STYLE[m])
    ax.axhline(ref, color="0.4", linestyle="--", linewidth=1.3, label=ref_label)
    ax.set_xscale("log")
    ax.set_xticks(games)
    ax.set_xticklabels([f"{g:,}" for g in games])
    ax.minorticks_off()
    ax.set_xlabel("training games (first N of d2-v2's train bucket)", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9.5, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    results = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    ref = results["references"]
    curve(results, lambda r: r["value"]["mae"], "mean |v - d11| (lower is better)",
          "Value error against careful Stockfish (d2-check, 94,963 positions)",
          ref["d1"]["value"]["mae"], "quick Stockfish d1 alone", out / "curve-value-error.png")
    curve(results, lambda r: r["outcome"]["mse"], "mean (v - result)² (lower is better)",
          "Outcome error on d2-check trajectories (finished games)",
          ref["d1"]["outcome"]["mse"], "quick Stockfish d1 alone", out / "curve-outcome-error.png")

    lines = []
    full = results["curves"][-1]
    lines.append(f"Full data: {full['games']:,} train-bucket games ({full['distil_rows']:,} Distil rows; "
                 f"{full['trajectory_rows']:,} trajectory rows from {full['trajectory_games']:,} finished games).\n")
    lines.append("| Method | alpha | rounds (best / run) | value error | value error, played moves | outcome MSE | "
                 "top-1 | value lost |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m, label in LABELS.items():
        r = full["methods"][m]
        sel = r["selected"]
        rounds = f"{sel['best_round']} / {sel['rounds_run']}" if "best_round" in sel else "-"
        lines.append(f"| {label} | {sel['alpha']:g} | {rounds} | {r['value']['mae']:.4f} | "
                     f"{r['value_on_trajectory']['mae']:.4f} | {r['outcome']['mse']:.4f} | "
                     f"{r['value']['choice']['top1']:.3f} | {r['value']['choice']['regret']:.4f} |")
    d1 = ref["d1"]
    lines.append(f"| quick Stockfish d1 alone | - | - | {d1['value']['mae']:.4f} | - | {d1['outcome']['mse']:.4f} | "
                 f"{d1['value']['choice']['top1']:.3f} | {d1['value']['choice']['regret']:.4f} |")
    lines.append(f"| v = 0 | - | - | - | - | {ref['zero']['outcome']['mse']:.4f} | - | - |")
    lines.append("")
    lines.append("| Difference (a - b) | value error | 95% CI | outcome MSE | 95% CI | value lost | 95% CI |")
    lines.append("|---|---|---|---|---|---|---|")
    for key, d in results["intervals_full_data"].items():
        a, b = key.split(" - ")
        name = f"{LABELS[a].split(' (')[0]} - {LABELS[b].split(' (')[0]}"
        v, o, g = d["value_error"], d["outcome_error"], d["regret"]
        lines.append(f"| {name} | {v['mean']:+.4f} | [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}] | "
                     f"{o['mean']:+.4f} | [{o['ci95'][0]:+.4f}, {o['ci95'][1]:+.4f}] | "
                     f"{g['mean']:+.4f} | [{g['ci95'][0]:+.4f}, {g['ci95'][1]:+.4f}] |")
    lines.append("")
    lines.append("| Games | " + " | ".join(f"{LABELS[m]} value / outcome" for m in LABELS) + " |")
    lines.append("|---" * (len(LABELS) + 1) + "|")
    for p in results["curves"]:
        cells = [f"{p['methods'][m]['value']['mae']:.4f} / {p['methods'][m]['outcome']['mse']:.4f}" for m in LABELS]
        lines.append(f"| {p['games']:,} | " + " | ".join(cells) + " |")
    (out / "tables.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
