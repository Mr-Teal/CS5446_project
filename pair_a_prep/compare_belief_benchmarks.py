"""Paired speed/memory comparison on identical bounded opening prefixes.

This deliberately does not pretend that the frozen enumerating reference can
finish the full, astronomically large history sets in the new exact benchmark.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--plies", type=int, default=6)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for repeat in range(args.repeats):
        order = ("reference", "graph") if repeat % 2 == 0 else ("graph", "reference")
        for implementation in order:
            directory = args.output / f"repeat-{repeat}-{implementation}"
            command = ["pixi", "run", "--locked", "-e", "darkchess", "python", "-X", "utf8",
                       "-m", "pair_a_prep.benchmark_belief_tracker", "--input", str(args.input),
                       "--output", str(directory), "--prefix-plies", str(args.plies),
                       "--implementation", implementation, "--backend", "native", "--isolated"]
            subprocess.run(command, check=True)
            rows = {}
            for path in directory.glob("game-*.jsonl"):
                for line in path.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    if row["event"] == "update":
                        rows[row["game"], row["ply"], row["player"]] = row
            snapshots[repeat, implementation] = rows
        old, new = snapshots[repeat, "reference"], snapshots[repeat, "graph"]
        assert old.keys() == new.keys()
        assert all(old[key]["history_count"] == new[key]["history_count"] for key in old)
    records = []
    for game in range(10):
        times, memory = {}, {}
        for implementation in ("reference", "graph"):
            trials = [[r for key, r in snapshots[repeat, implementation].items() if key[0] == game]
                      for repeat in range(args.repeats)]
            times[implementation] = median(sum(r["update_ms"] for r in rows) for rows in trials)
            memory[implementation] = median(max(r["owned_bytes"] for r in rows) for rows in trials) / 2 ** 20
        records.append({"game": game, "prefix_plies": args.plies,
                        "reference_median_total_ms": times["reference"],
                        "graph_median_total_ms": times["graph"],
                        "speedup": times["reference"] / times["graph"],
                        "reference_peak_owned_mib": memory["reference"],
                        "graph_peak_owned_mib": memory["graph"]})
    report = {"repeats": args.repeats, "prefix_plies": args.plies,
              "kind": "paired_opening_prefix_benchmark_not_full_game_speedup",
              "history_counts_identical": True,
              "reference_source_sha256": sha256(Path(__file__).with_name("tests").joinpath(
                  "reference_belief_tracker.py").read_bytes()).hexdigest(),
              "games": records,
              "aggregate_speedup": sum(r["reference_median_total_ms"] for r in records) /
                                   sum(r["graph_median_total_ms"] for r in records)}
    (args.output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Paired tracker comparison", "",
             f"Both trackers process every private observation in the first {args.plies} plies of games 0-9. Each implementation runs {args.repeats} times, with alternating run order. Time, memory and internal history limits are None; output sample size is 16. Entries are medians across repetitions of total update time and peak owned memory per prefix. History counts agree at every step.",
             "", "| Game | Reference ms | Graph ms | Speedup | Reference MiB | Graph MiB |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in records:
        lines.append(f"| {row['game']} | {row['reference_median_total_ms']:.2f} | {row['graph_median_total_ms']:.2f} | "
                     f"{row['speedup']:.2f} | {row['reference_peak_owned_mib']:.3f} | {row['graph_peak_owned_mib']:.3f} |")
    lines += ["", f"The aggregate update-time ratio is {report['aggregate_speedup']:.2f}x for these short prefixes. This is not a full-game speedup guarantee; full-game results are reported separately in full-games/report.md. Memory measures retained objects, not process RSS."]
    (args.output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
