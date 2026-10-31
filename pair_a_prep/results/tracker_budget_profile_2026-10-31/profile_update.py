"""Profile one fixed private update; each invocation runs in a fresh process."""
import argparse
from dataclasses import asdict
import hashlib
import json
from math import inf
from pathlib import Path
from time import perf_counter

from fow_shared.contracts import Observation
from pair_a_prep import belief_tracker as module
from pair_a_prep.belief_tracker import BeliefTracker

HERE = Path(__file__).resolve().parent


def observation(data):
    return Observation(**{**data, "visible_squares": tuple(data["visible_squares"]),
                          "legal_moves": tuple(data["legal_moves"])})


def run(args):
    rows = [json.loads(line) for line in Path(args.input).read_text().splitlines()]
    rows = [row for row in rows if row["player"] == "black" and row["observation"]["ply"] <= 9]
    tracker = BeliefTracker(sample_size=3, backend="python")
    tracker.reset("black", rows[0]["tracker_seed"])
    for row in rows[:-1]: tracker.update(observation(row["observation"]), row["own_move"])
    assert tracker.population_size == 8841 and tracker.state_count == 2388
    original_stats, original_output = tracker.storage_stats, tracker._make_belief
    original_successors, original_repetition = module.successors, module.repetition_paths
    phases = dict(memory_ms=0., output_ms=0., transitions_ms=0., repetition_ms=0.)

    def measured(key, function):
        def call(*a, **kw):
            began = perf_counter()
            try: return function(*a, **kw)
            finally: phases[key] += (perf_counter() - began) * 1000
        return call

    def successors(*a, **kw):
        stream = original_successors(*a, **kw)
        while True:
            began = perf_counter()
            try: child = next(stream)
            except StopIteration:
                phases["transitions_ms"] += (perf_counter() - began) * 1000
                return
            phases["transitions_ms"] += (perf_counter() - began) * 1000
            yield child

    if not args.no_instrument:
        tracker.storage_stats = measured("memory_ms", original_stats)
        tracker._make_belief = measured("output_ms", original_output)
        module.successors = successors
        module.repetition_paths = measured("repetition_ms", original_repetition)
    target = rows[-1]
    calls = []
    began = perf_counter()
    budgeted = args.slice_ms is not None
    status = "unknown"
    result = None
    for index in range(args.max_calls):
        remaining = args.total_ms - (perf_counter() - began) * 1000 if budgeted else inf
        if remaining <= 0:
            status = "total_time"
            break
        time_budget = min(remaining, args.slice_ms) if budgeted else None
        previous = dict(phases)
        call_start = perf_counter()
        if index == 0:
            result = tracker.update_budgeted(observation(target["observation"]), target["own_move"],
                time_budget_ms=time_budget, memory_budget_mb=args.memory_mb)
        else:
            result = tracker.resume(time_budget_ms=time_budget, memory_budget_mb=args.memory_mb)
        call_ms = (perf_counter() - call_start) * 1000
        row = {key: value for key, value in asdict(result).items() if key != "belief"}
        row.update(call=index + 1, wall_ms=call_ms,
                   phases={key: phases[key] - previous[key] for key in phases})
        calls.append(row)
        if (perf_counter() - began) * 1000 > args.total_ms and budgeted:
            status = "total_time"
            break
        if result.status == "complete":
            status = "complete"
            break
        if result.stopped_by != "time":
            status = result.stopped_by or "incomplete"
            break
    else: status = "call_limit"
    wall = (perf_counter() - began) * 1000
    owned = original_stats()
    signature = None
    if result is not None and result.belief is not None and result.status == "complete":
        signature = hashlib.sha256(json.dumps(asdict(result.belief), sort_keys=True).encode()).hexdigest()
    summary = dict(instrumented=not args.no_instrument,
        slice_ms=args.slice_ms, total_ms=args.total_ms if budgeted else None,
        memory_mb=args.memory_mb, max_calls=args.max_calls, status=status, wall_ms=wall,
        phases=phases, residual_ms=wall - sum(phases.values()), calls=calls,
        final_owned=owned, signature=signature)
    Path(args.output).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key not in ("calls", "final_owned")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice-ms", type=float)
    parser.add_argument("--total-ms", type=float, default=5000)
    parser.add_argument("--memory-mb", type=float)
    parser.add_argument("--max-calls", type=int, default=10000)
    parser.add_argument("--output", required=True)
    parser.add_argument("--input", default=str(HERE / "private-stream.jsonl"))
    parser.add_argument("--no-instrument", action="store_true")
    run(parser.parse_args())
