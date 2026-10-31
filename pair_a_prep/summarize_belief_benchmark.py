"""Produce auditable JSON and Markdown tables from complete tracker game replays."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean


def percentile(values, q):
    ordered = sorted(values)
    at = (len(ordered) - 1) * q
    lo = int(at)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] * (hi - at) + ordered[hi] * (at - lo) if hi != lo else ordered[lo]


def distribution(rows, field):
    groups = defaultdict(list)
    for row in rows:
        value = row[field]
        exponent = len(str(value)) - 1 if value else -1
        groups[exponent].append(row)
    result = []
    for exponent, group in sorted(groups.items()):
        times = [r["update_ms"] for r in group]
        memory = [r["owned_bytes"] / 2 ** 20 for r in group]
        result.append({"range": f"[10^{exponent}, 10^{exponent + 1})", "count": len(group),
                       "probability": len(group) / len(rows), "mean_update_ms": mean(times),
                       "median_update_ms": percentile(times, .5), "p95_update_ms": percentile(times, .95),
                       "max_update_ms": max(times), "mean_owned_mib": mean(memory),
                       "median_owned_mib": percentile(memory, .5), "max_owned_mib": max(memory)})
    return result


def table(rows, columns):
    lines = ["| " + " | ".join(label for _, label, _ in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(formatter(row[key]) for key, _, formatter in columns) + " |")
    return "\n".join(lines)


def summarize(directory, expected_games):
    all_rows, games, manifests, incomplete = [], [], [], []
    for path in sorted(directory.glob("game-*-graph-both.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        completed = [r for r in records if r["event"] == "complete"]
        if not completed:
            incomplete.append(path.name)
            continue
        start, final = records[0], completed[-1]
        updates = [r for r in records if r["event"] == "update"]
        if len(updates) != 2 * (final["plies"] + 1):
            raise ValueError(f"missing updates: {path}")
        if not all(r["support_complete"] for r in updates):
            raise ValueError(f"inexact full-game run: {path}")
        if sum(r["terminal"] for r in updates) != 2:
            raise ValueError(f"missing terminal observations: {path}")
        previous = {}
        for row in updates:
            prior = previous.get(row["player"], {"history_count": 1, "state_count": 1})
            row["input_history_count"] = prior["history_count"]
            row["input_state_count"] = prior["state_count"]
            row["decision_turn"] = (not row["terminal"] and (row["ply"] % 2 == 0) == (row["player"] == "white"))
            previous[row["player"]] = row
        all_rows.extend(updates)
        games.append({"game": final["game"], "seed": start["seed"], "plies": final["plies"],
                      "updates": len(updates), "winner": final["winner"], "reason": final["reason"],
                      "max_histories": max(r["history_count"] for r in updates),
                      "max_states": max(r["state_count"] for r in updates),
                      "total_update_seconds": sum(r["update_ms"] for r in updates) / 1000,
                      "median_update_ms": percentile([r["update_ms"] for r in updates], .5),
                      "p95_update_ms": percentile([r["update_ms"] for r in updates], .95),
                      "max_update_ms": max(r["update_ms"] for r in updates),
                      "max_owned_mib": max(r["owned_bytes"] for r in updates) / 2 ** 20,
                      "process_peak_rss_mib": final.get("process_peak_rss_bytes", 0) / 2 ** 20,
                      "wall_seconds_with_audits": final["wall_seconds"]})
        manifests.append({"file": path.name, "sha256": sha256(path.read_bytes()).hexdigest(), "start": start})
    if len(games) != expected_games or incomplete:
        raise ValueError(f"expected {expected_games} completed games, got {len(games)}; incomplete={incomplete}")
    versions = {json.dumps(m["start"]["source_hashes"], sort_keys=True) for m in manifests}
    if len(versions) != 1:
        raise ValueError("benchmark source changed between games")
    decision_rows = [r for r in all_rows if r["decision_turn"]]
    summary = {"games": games, "completed_games": len(games), "updates": len(all_rows),
               "decision_turn_updates": len(decision_rows), "manifests": manifests,
               "history_size_distribution": distribution(all_rows, "history_count"),
               "stored_state_distribution": distribution(all_rows, "state_count"),
               "input_state_distribution": distribution(all_rows, "input_state_count"),
               "decision_turn_history_distribution": distribution(decision_rows, "history_count"),
               "decision_turn_state_distribution": distribution(decision_rows, "state_count")}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (directory / "updates.jsonl").open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row) + "\n")
    number = lambda v: f"{v:,}" if isinstance(v, int) else f"{v:,.0f}"
    decimal = lambda v: f"{v:,.2f}"
    columns = [("range", "Size range", str), ("count", "Updates", number),
               ("probability", "Empirical frequency", lambda v: f"{v:.2%}"),
               ("median_update_ms", "Median ms", decimal), ("p95_update_ms", "P95 ms", decimal),
               ("mean_owned_mib", "Mean owned MiB", decimal), ("max_owned_mib", "Max owned MiB", decimal)]
    sections = ["# Full-game BeliefTracker measurements\n",
        f"A frozen implementation replayed {len(games)} existing complete ZS21 agent/baseline games, with {len(all_rows)} private observation updates across both players, including {len(decision_rows)} decision-turn observations. This is tracker replay validation, not new training or a new tournament.",
        "Every game ran from the standard start through the referee's terminal observation. Time, memory and internal history limits were None; prune was never called. The output sample of 16 limits returned data only. An external audit verified true-history membership after every update.",
        "Histories count complete candidate paths. Stored states count current board/counter nodes; the DAG also retains shared past nodes and edges. Owned memory counts reachable Python objects once each. Process peak RSS includes both trackers, the interpreter, audit temporaries and allocator retention; it is not an individual update's exclusive peak. Timing covers update() only, excluding observation generation and external audits. MiB=2^20 bytes.",
        "## Per-game results\n",
        table(games, [("game", "Source game", number), ("plies", "Plies", number),
                      ("max_histories", "Peak histories", number), ("max_states", "Peak state nodes", number),
                      ("total_update_seconds", "Total update s", decimal), ("p95_update_ms", "P95 ms", decimal),
                      ("max_owned_mib", "Peak tracker-owned MiB", decimal),
                      ("process_peak_rss_mib", "Process peak RSS MiB", decimal)]),
        "## Grouped by output history count\n", table(summary["history_size_distribution"], columns),
        "## Grouped by output stored-state count\n", table(summary["stored_state_distribution"], columns),
        "## Grouped by input stored-state count\n", table(summary["input_state_distribution"], columns),
        "Update cost depends on incoming nodes, available moves, filtering strength and historical-path filtering. A small output can follow a large input, so output history count alone cannot predict runtime.",
        "## Decision-turn observations only\n", table(summary["decision_turn_state_distribution"], columns),
        "## Interpretation and limits\n",
        "Each frequency is the number of updates in its bin divided by the table's total update count. These are empirical frequencies for preselected games 0-9 under their particular policies. Longer games contribute more observations, and adjacent observations are correlated. They are not universal probabilities for FoW positions. JSON also includes means, maximum times and decision-turn history-size frequencies. Interrupted development pilots are excluded.",
        "Raw traces are in game-*.jsonl; merged per-update data are in updates.jsonl. summary.json records seeds, source/game hashes, budgets and all statistics."]
    (directory / "report.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    print(json.dumps({"completed_games": len(games), "updates": len(all_rows),
                      "max_history_count": max(r["history_count"] for r in all_rows),
                      "max_state_count": max(r["state_count"] for r in all_rows),
                      "max_owned_mib": max(r["owned_bytes"] for r in all_rows) / 2 ** 20,
                      "total_update_seconds": sum(r["update_ms"] for r in all_rows) / 1000}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expected-games", type=int, default=10)
    args = parser.parse_args()
    summarize(args.directory, args.expected_games)
