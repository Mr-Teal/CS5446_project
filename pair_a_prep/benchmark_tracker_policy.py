"""Measure one private observation through the shipped evaluation tracker factory.

Prepare the exact private prefix outside timing; apply the requested budget only
to the target update. Each CLI invocation should use a fresh Pixi process.
"""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import importlib.util
from pathlib import Path
import platform
import sys
from time import perf_counter

from fow_shared.contracts import Observation
from pairb.rules import pick_rules
from .benchmark_belief_tracker import memory_usage
from .evaluation_factories import HistoryTrackerFactory
from .evaluation_tracking import TrackingBudgetError


def decode(data):
    return Observation(**{**data, "visible_squares": tuple(data["visible_squares"]),
                          "legal_moves": tuple(data["legal_moves"])})


def run(args):
    if args.tracker_source is not None:
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
        graph = load("pair_a_prep._benchmark_reference_graph", args.tracker_source.with_name("_belief_graph.py"))
        baseline = load("pair_a_prep._benchmark_reference_tracker", args.tracker_source)
        for name in ("ObservationFilter", "PathNode", "StateNode", "history_id", "position_key",
                     "position_bit", "repetition_paths", "successors"):
            setattr(baseline, name, getattr(graph, name))
        from . import evaluation_factories
        evaluation_factories.BeliefTracker = baseline.BeliefTracker
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["player"] == args.player
            and r["seed"] == args.seed and r["observation"]["ply"] <= args.ply]
    if [r["observation"]["ply"] for r in rows] != list(range(args.ply + 1)):
        raise ValueError("input must contain exactly one contiguous private prefix through the target")
    if args.output.exists():
        raise FileExistsError(args.output)
    settings = dict(public_initial_fen=args.initial_fen, sample_size=str(args.sample_size),
        max_candidates="none", tracker_policy="budgeted-exact", tracker_backend=args.backend,
        tracker_slice_ms=str(args.slice_ms), tracker_total_ms=str(args.total_ms),
        tracker_memory_mb=str(args.memory_mb), tracker_max_resumes=str(args.max_resumes))
    policy = HistoryTrackerFactory(settings).create_tracker(pick_rules("teal"), args.initial_fen)
    policy.reset(args.player, rows[0]["tracker_seed"])
    tracker = policy.tracker
    for row in rows[:-1]:
        tracker.update(decode(row["observation"]), row["own_move"])
    before = dict(histories=tracker.population_size, states=tracker.state_count)
    assert tracker.support_complete
    error, belief = None, None
    started = perf_counter()
    try:
        belief = policy.update(decode(rows[-1]["observation"]), rows[-1]["own_move"])
    except TrackingBudgetError as exc:
        error = str(exc)
    elapsed = (perf_counter() - started) * 1000
    process = memory_usage()
    result = policy.last_update
    metadata = None if result is None else {
        key: getattr(result, key) for key in result.__dataclass_fields__ if key != "belief"}
    signature = None if belief is None else sha256(
        json.dumps(asdict(belief), sort_keys=True).encode()).hexdigest()
    inventory_started = perf_counter()
    owned = tracker.storage_stats()
    diagnostic_inventory_ms = (perf_counter() - inventory_started) * 1000
    from ._belief_memory import budget_inventory
    inventory_started = perf_counter()
    structural_bytes = budget_inventory(tracker)
    structural_inventory_ms = (perf_counter() - inventory_started) * 1000
    assert structural_bytes >= owned["owned_bytes"], "Structural inventory undercounts reachable objects"
    report = dict(kind="fixed_private_update_not_a_match", input_sha256=sha256(args.input.read_bytes()).hexdigest(),
        seed=args.seed, tracker_seed=rows[0]["tracker_seed"], player=args.player, ply=args.ply,
        settings=settings, actual_backend=tracker.backend, prefix=before,
        outcome="complete" if belief is not None else "failed", error=error,
        policy_stop=policy.policy_stop, calls=policy.update_calls, wall_ms=elapsed,
        result=metadata, signature=signature, process_after_update=process,
        owned_after_update=owned, python=platform.python_version(),
        structural_bytes_after_update=structural_bytes,
        diagnostic_inventory_ms=diagnostic_inventory_ms, structural_inventory_ms=structural_inventory_ms,
        platform=platform.platform(), logical_memory_is_not_rss=True,
        tracker_source_sha256=sha256((args.tracker_source or Path(__file__).with_name("belief_tracker.py")).read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("actual_backend", "ply", "outcome", "policy_stop", "calls", "wall_ms", "signature")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--player", choices=("white", "black"), default="black")
    parser.add_argument("--seed", type=int, default=18)
    parser.add_argument("--ply", type=int, default=9)
    parser.add_argument("--initial-fen", default="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--backend", choices=("python", "native"), default="native")
    parser.add_argument("--slice-ms", type=float, default=5000)
    parser.add_argument("--total-ms", type=float, default=5000)
    parser.add_argument("--memory-mb", type=float, default=512)
    parser.add_argument("--max-resumes", type=int, default=0)
    parser.add_argument("--tracker-source", type=Path, help="frozen baseline tracker with adjacent _belief_graph.py")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
