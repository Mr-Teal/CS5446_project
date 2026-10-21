"""Add the replay checks, the reparameterisation check, the round-cap diagnostic, seeds and the
compute tally to results.json, so the write-up quotes one file. Every key mc_td.py wrote is kept.

    python assemble_results.py   (run in this folder, after mc_td.py and td_rounds_diagnostic.py)
"""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    path = HERE / "results.json"
    results = json.loads(path.read_text())
    replay = {}
    for name in ("trajectories-d2-v2-train-val.jsonl", "trajectories-d2-check-train.jsonl"):
        manifest_path = HERE / "cache" / f"{name}.manifest.json"
        m = json.loads(manifest_path.read_text())
        assert m["out_sha256"] == sha256(HERE / "cache" / name), f"{name} changed since its manifest"
        finals = {}
        for line in (HERE / "cache" / name).read_text().splitlines():
            g = json.loads(line)
            key = f"{g['termination']} / fog rule at the end: {g['final_rule']}"
            finals[key] = finals.get(key, 0) + 1
        replay[m["dataset"]] = {"file": f"cache/{name}", "sha256": m["out_sha256"],
                                "games_jsonl_sha256": m["games_jsonl_sha256"], "splits": m["splits"],
                                "stockfish": m["stockfish"], "value_conversion": m["value_conversion"],
                                "summary": m["summary"], "endings": finals, "seconds": m["seconds"]}
    reparam = json.loads((HERE / "check-reparam.json").read_text())
    diag = json.loads((HERE / "td-rounds-diagnostic.json").read_text())
    diag_summary = {}
    for method, d in diag["methods"].items():
        h = d["history"]
        best = h[0]
        stop = None
        for row in h[1:]:
            if row["val_mse"] < best["val_mse"]:
                best = row
            elif stop is None:
                stop = row["round"]
        diag_summary[method] = {"alpha": d["alpha"], "round_15": h[14], "best_validation_round": best,
                                "first_non_improving_round_without_cap": stop, "round_40": h[-1]}
    stopped = (HERE / "run-1-narrow-grid-stopped.log").read_text()
    stopped_fit_seconds = sum(float(s) for s in re.findall(r"^  \w+: .*\(([\d.]+) s\)$", stopped, flags=re.M))
    results["replay"] = replay
    results["reparameterisation_check"] = {"file": "check-reparam.json", "sha256": sha256(HERE / "check-reparam.json"),
                                           **reparam}
    results["td_rounds_diagnostic"] = {"file": "td-rounds-diagnostic.json",
                                       "sha256": sha256(HERE / "td-rounds-diagnostic.json"),
                                       "rounds_run": diag["rounds_run_here"], "summary": diag_summary,
                                       "seconds": diag["seconds"]}
    edge = json.loads((HERE / "alpha-edge-check.json").read_text())
    full = {m: x for m, x in results["curves"][-1]["methods"].items()}
    results["alpha_edge_check"] = {
        "file": "alpha-edge-check.json", "sha256": sha256(HERE / "alpha-edge-check.json"), "alpha": edge["alpha"],
        "methods": {m: {**x, "selected_alpha_in_main_run": full[m]["selected"]["alpha"],
                        "main_run_val_mse": full[m]["selected"]["val_mse"],
                        "would_be_selected": x["val_mse"] < full[m]["selected"]["val_mse"],
                        "value_mae_change": x["value_mae"] - full[m]["value"]["mae"],
                        "outcome_mse_change": x["outcome_mse"] - full[m]["outcome"]["mse"]}
                    for m, x in edge["methods"].items()},
        "seconds": edge["seconds"]}
    results["seeds"] = {"games": "each game's own seed in games.jsonl (dataset seed x 1,000,000 + index: d2-v2 2026, "
                                 "d2-check 7), replayed with pairb.d2.play_game",
                        "bootstrap": 0, "fits": "deterministic: no random numbers in fitting or selection"}
    results["compute_seconds"] = {
        "replay_d2_check": replay["d2-check"]["seconds"],
        "replay_d2_check_first_attempt_discarded": 68.8,  # a counting bug in its summary; rerun with the fix
        "replay_d2_v2": replay["d2-v2"]["seconds"],
        "smoke_test_quick_mode": 47.7,
        "first_full_run_stopped": round(stopped_fit_seconds + 44, 1),  # fits logged + about 44 s of loading
        "main_run": results["timings_seconds"]["total"],
        "td_rounds_diagnostic": diag["seconds"],
        "alpha_edge_check": edge["seconds"],
        "note": "replay and run times are measured; the stopped run is its logged fit times plus the main run's "
                "loading time; the reparameterisation check took a few seconds",
    }
    results["compute_seconds"]["total"] = round(sum(v for v in results["compute_seconds"].values()
                                                    if isinstance(v, (int, float))), 1)
    results["assembled_by"] = {"script": "assemble_results.py", "sha256": sha256(Path(__file__))}
    results["scripts_sha256"] = {p.name: sha256(p) for p in sorted(HERE.glob("*.py"))}
    path.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({k: results[k] for k in ("compute_seconds", "seeds")}, indent=2))
    print(json.dumps(diag_summary, indent=2))


if __name__ == "__main__":
    main()
