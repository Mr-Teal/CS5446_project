"""Replay complete games using private views only; measure exact tracker cost.

Usage: python -m pair_a_prep.benchmark_belief_tracker --input DIR --output DIR
No tracker budgets or internal history/state caps are enabled. sample_size
limits returned hypotheses only. The actual game path is used solely by the
external replay oracle, never to prune or seed the tracker's hidden candidates.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import asdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
from time import perf_counter
import sys
import chess

from .belief_tracker import BeliefTracker
from .rules_adapter import RulesAdapter


def memory_usage():
    if sys.platform != "win32":
        return {}
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("peak_rss", "rss", "qpp", "qp",
                                         "qnpp", "qnp", "commit", "peak_commit", "private")]
    c = Counters()
    c.cb = ctypes.sizeof(c)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"process_rss_bytes": c.rss, "process_peak_rss_bytes": c.peak_rss,
            "process_private_bytes": c.private}


def append(path, row):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_game(source, destination, *, sample_size=16, implementation="graph", player=None,
             backend="auto", prefix_plies=None):
    rules = RulesAdapter()
    with gzip.open(source, "rt", encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    start = next(e for e in events if e["event"] == "start")
    positions = [e for e in events if e["event"] == "position"]
    actions = [e["decision"]["move"] for e in events if e["event"] == "decision"]
    initial_fen = positions[0]["fen"]
    players = [player] if player else ["white", "black"]
    tracker_type = BeliefTracker
    if implementation == "reference":
        from .tests.reference_belief_tracker import BeliefTracker as tracker_type
    options = {"backend": backend} if implementation == "graph" else {}
    trackers = {p: tracker_type(initial_fen, sample_size=sample_size, **options) for p in players}
    state = rules.initial_state(initial_fen)
    for p, t in trackers.items():
        t.reset(p, start["agent_seeds"][p])
    trace = destination / (source.name.split(".")[0] + f"-{implementation}-{player or 'both'}.jsonl")
    if trace.exists():
        raise FileExistsError(trace)
    append(trace, {"event": "start", "source": str(source),
                   "source_sha256": sha256(source.read_bytes()).hexdigest(),
                   "seed": start["seed"], "implementation": implementation,
                   "sample_size": sample_size, "time_budget_ms": None,
                   "backend": getattr(next(iter(trackers.values())), "backend", "reference"),
                   "memory_budget_mb": None, "max_candidates": None,
                   "python": sys.version, "platform": platform.platform(),
                   "prefix_plies": prefix_plies,
                   "source_hashes": {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                       for name in ("belief_tracker.py", "_belief_graph.py", "_belief_native.py",
                                    "belief_kernel.cpp", "rules_adapter.py", "benchmark_belief_tracker.py")}})
    began = perf_counter()
    total_update = 0.0
    plies = len(actions) if prefix_plies is None else min(prefix_plies, len(actions))
    for ply in range(plies + 1):
        if ply:
            mover = rules.current_player(state)
            state = rules.apply_move(state, actions[ply - 1])
        else:
            mover = None
        if state.fen != positions[ply]["fen"]:
            raise AssertionError(f"referee replay mismatch at ply {ply}")
        for p, tracker in trackers.items():
            observed = rules.observe(state, p)
            own_move = actions[ply - 1] if p == mover else None
            append(trace, {"event": "updating", "ply": ply, "player": p,
                           "previous_history_count": tracker.population_size})
            update_start = perf_counter()
            belief = tracker.update(observed, own_move)
            ms = (perf_counter() - update_start) * 1000
            total_update += ms
            if implementation == "graph":
                stats = tracker.storage_stats()
                if not tracker.support_complete:
                    raise AssertionError("unbounded exact run lost support")
                # The true path must remain in the DAG, without enumerating it.
                if not contains_path(tracker, tuple(actions[:ply]), state.fen):
                    raise AssertionError("true history missing from exact support")
            else:
                stats = reference_storage(tracker)
            row = {"event": "update", "game": start["game"], "ply": ply,
                   "player": p, "update_ms": ms, **stats, **memory_usage(),
                   "returned_count": len(belief.hypotheses), "terminal": observed.terminal}
            append(trace, row)
            print(json.dumps({k: row[k] for k in ("game", "ply", "player", "history_count", "update_ms")}), flush=True)
    ended = rules.terminal(state)
    if ended is None and prefix_plies is None:
        raise AssertionError("source is not a complete game")
    summary = {"event": "complete" if ended else "prefix_complete", "game": start["game"], "plies": plies,
               "winner": ended.winner if ended else None, "reason": ended.reason if ended else None,
               "total_update_ms": total_update,
               "wall_seconds": perf_counter() - began, **memory_usage()}
    append(trace, summary)
    print(json.dumps(summary), flush=True)


def reference_storage(tracker):
    seen, stack, total = set(), [tracker.__dict__], 0
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        total += sys.getsizeof(obj)
        if isinstance(obj, dict):
            stack.extend(obj.keys())
            stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        elif hasattr(obj, "__dict__") and not isinstance(obj, type):
            stack.append(obj.__dict__)
    return {"owned_bytes": total, "history_count": tracker.population_size,
            "state_count": tracker.population_size, "support_complete": True}


def contains_path(tracker, moves, fen):
    # Follow the known path backwards through the DAG; oracle only, not inference.
    from ._belief_graph import position_key
    board = chess.Board(fen)
    key = (position_key(board, effective_ep=False), board.halfmove_clock, board.fullmove_number)
    reachable = [n.paths for n in tracker._nodes
                 if (position_key(n.board, effective_ep=False), n.board.halfmove_clock,
                     n.board.fullmove_number) == key]
    for move in reversed(moves):
        reachable = {parent for node in reachable for parent, action in node.incoming if action == move}
        if not reachable:
            return False
    return any(not node.incoming for node in reachable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--games", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--sample-size", type=int, default=16)
    parser.add_argument("--implementation", choices=("graph", "reference"), default="graph")
    parser.add_argument("--player", choices=("white", "black"))
    parser.add_argument("--backend", choices=("auto", "native", "python"), default="auto")
    parser.add_argument("--prefix-plies", type=int)
    parser.add_argument("--isolated", action="store_true", help="fresh Pixi worker process for each game")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.isolated:
        plan = {"games": args.games, "input": str(args.input), "sample_size": args.sample_size,
                "implementation": args.implementation, "backend": args.backend,
                "time_budget_ms": None, "memory_budget_mb": None, "max_candidates": None,
                "player": args.player, "prefix_plies": args.prefix_plies}
        (args.output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        failures = []
        for game in args.games:
            command = ["pixi", "run", "--locked", "-e", "darkchess", "python", "-X", "utf8",
                       "-m", "pair_a_prep.benchmark_belief_tracker", "--input", str(args.input),
                       "--output", str(args.output), "--games", str(game), "--sample-size", str(args.sample_size),
                       "--implementation", args.implementation, "--backend", args.backend]
            if args.player:
                command += ["--player", args.player]
            if args.prefix_plies is not None:
                command += ["--prefix-plies", str(args.prefix_plies)]
            with (args.output / f"game-{game:03d}.console.log").open("w", encoding="utf-8") as log:
                code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
            append(args.output / "batch.jsonl", {"game": game, "exit_code": code, "command": command})
            if code:
                failures.append(game)
        if failures:
            raise SystemExit(f"failed games: {failures}")
        return
    for game in args.games:
        run_game(args.input / f"game-{game:03d}.jsonl.gz", args.output,
                 sample_size=args.sample_size, implementation=args.implementation, player=args.player,
                 backend=args.backend, prefix_plies=args.prefix_plies)


if __name__ == "__main__":
    main()
