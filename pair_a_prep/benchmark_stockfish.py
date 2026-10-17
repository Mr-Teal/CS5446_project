"""Measure raw Stockfish UCI calls independently of Pair B's evaluator.

Only orthodox-valid positions enter the engine. FoW positions with a missing
king or an immediately capturable enemy king belong in rules tests instead.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
from time import perf_counter

import chess
import chess.engine


DEFAULT_CORPUS = Path(__file__).parent / "data" / "benchmark_positions.json"


def load_positions(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    positions = []
    for item in data["positions"]:
        board = chess.Board(item.get("fen", chess.STARTING_FEN))
        for uci in item.get("moves_uci", []):
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f"illegal corpus move {uci} in {item['id']}")
            board.push(move)
        # In particular, STATUS_OPPOSITE_CHECK excludes capturable enemy kings.
        if not board.is_valid() or board.is_game_over(claim_draw=False):
            raise ValueError(f"unsafe or finished ordinary-chess position: {item['id']}")
        positions.append({"id": item["id"], "category": item["category"], "fen": board.fen()})
    if not positions or len({p["id"] for p in positions}) != len(positions):
        raise ValueError("corpus needs unique position IDs")
    return positions


def raw_lines(infos: list, board: chess.Board) -> list:
    result = []
    for info in infos:
        score = info.get("score")
        pov = score.pov(board.turn) if score is not None else None
        result.append({"multipv": info.get("multipv", 1), "depth": info.get("depth"),
                       "cp": pov.score() if pov is not None and not pov.is_mate() else None,
                       "mate": pov.mate() if pov is not None and pov.is_mate() else None,
                       "pv": [move.uci() for move in info.get("pv", [])],
                       "engine_time_ms": info.get("time", 0) * 1000,
                       "nodes": info.get("nodes"), "nps": info.get("nps"),
                       "hashfull": info.get("hashfull"),
                       "lowerbound": info.get("lowerbound", False),
                       "upperbound": info.get("upperbound", False)})
    return result


def summarize(records: list) -> list:
    groups = {}
    for row in records:
        if row.get("type") == "trial" and row["status"] == "ok":
            groups.setdefault((row["depth"], row["mode"]), []).append(row["wall_ms"])
    result = []
    for (depth, mode), values in sorted(groups.items()):
        result.append({"depth": depth, "mode": mode, "trials": len(values),
                       "mean_ms": statistics.mean(values), "median_ms": statistics.median(values),
                       "p95_ms_nearest_rank": sorted(values)[math.ceil(0.95 * len(values)) - 1]})
    return result


def run(args) -> dict:
    positions = load_positions(args.positions)
    executable = args.engine.expanduser().resolve(strict=True)
    jobs = [(p, depth, mode, repetition) for p in positions for depth in args.depths
            for mode in args.modes for repetition in range(args.repeats)]
    random.Random(args.seed).shuffle(jobs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental loss of previous measurements.
    stream = args.output.open("x", encoding="utf-8", newline="\n")
    def emit(row):
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
    records = []
    try:
        started = perf_counter()
        with chess.engine.SimpleEngine.popen_uci(str(executable), timeout=args.timeout) as engine:
            startup_ms = (perf_counter() - started) * 1000
            engine.configure({"Threads": args.threads, "Hash": args.hash_mb})
            if "UCI_AnalyseMode" in engine.options:
                engine.configure({"UCI_AnalyseMode": True})
            metadata = {"type": "run", "run_label": args.label,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "engine_id": engine.id, "engine_path": str(executable),
                "engine_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "corpus_sha256": hashlib.sha256(args.positions.read_bytes()).hexdigest(),
                "platform": platform.platform(), "cpu": platform.processor(),
                "logical_cpus": os.cpu_count(), "python": platform.python_version(),
                "python_chess": chess.__version__, "threads": args.threads, "hash_mb": args.hash_mb,
                "depths": args.depths, "modes": args.modes, "repeats": args.repeats,
                "seed": args.seed, "timeout_seconds": args.timeout, "startup_ms": startup_ms,
                "hash_policy": "clear TT before each trial; other process state may persist",
                "score_perspective": "side_to_move_at_root", "score_conversion": "none",
                "scope": "ordinary-chess call costs only; not FoW strength or teacher labels"}
            emit(metadata)
            # Untimed warmup loads the embedded NNUE network before measured trials.
            engine.analyse(chess.Board(positions[0]["fen"]), chess.engine.Limit(depth=1))
            for position, depth, mode, repetition in jobs:
                board = chess.Board(position["fen"])
                legal_count = board.legal_moves.count()
                multipv = legal_count if mode == "all" else 1
                if multipv > engine.options["MultiPV"].max:
                    raise ValueError("engine's MultiPV limit cannot cover this position")
                engine.configure({"Clear Hash": None})
                engine.ping()
                started = perf_counter()
                try:
                    infos = engine.analyse(board, chess.engine.Limit(depth=depth),
                                           multipv=multipv, game=object())
                    elapsed = (perf_counter() - started) * 1000
                    lines = raw_lines(infos, board)
                    roots = {line["pv"][0] for line in lines if line["pv"]}
                    if len(roots) != multipv:
                        raise RuntimeError("engine did not return the requested distinct root moves")
                    row = {"type": "trial", "status": "ok", "position_id": position["id"],
                           "category": position["category"], "fen": position["fen"],
                           "depth": depth, "mode": mode, "repetition": repetition,
                           "multipv": multipv, "legal_move_count": legal_count,
                           "wall_ms": elapsed, "lines": lines}
                except (chess.engine.EngineError, RuntimeError) as exc:
                    emit({"type": "trial", "status": "error", "position_id": position["id"],
                          "depth": depth, "mode": mode, "error": str(exc)})
                    raise
                emit(row)
                records.append(row)
        summary = {"type": "summary", "groups": summarize(records), "successful_trials": len(records)}
        emit(summary)
        return summary
    finally:
        stream.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--positions", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="local-pilot")
    parser.add_argument("--depths", nargs="+", type=int, default=[1, 11])
    parser.add_argument("--modes", nargs="+", choices=["best", "all"], default=["best", "all"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=16)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if min(args.depths + [args.repeats, args.threads, args.hash_mb, args.timeout]) <= 0:
        parser.error("depths and resource limits must be positive")
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
