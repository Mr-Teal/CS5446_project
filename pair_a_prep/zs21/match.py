"""Audited matches: one shared four-worker pool, alternating colors, no fake draws."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
from time import perf_counter
import traceback

import chess
import numpy
import scipy

from .agent import PaperAgent
from .engine import EnginePool
from .model import Referee, BudgetError
from .config import load
from .rule_profile import RULES_ID


def code_manifest():
    directory = Path(__file__).parent
    names = ("agent.py", "engine.py", "gadget.py", "match.py", "model.py", "sequence_form.py",
             "native_tracker.py", "config.py", "rule_profile.py", "replay.py", "ui.py",
             "protocol.py", "integration.py", "serve.py",
             "native/inference.cpp", "native/inference.dll")
    files = [directory / name for name in names]
    files.extend(directory.parent / name for name in ("rules_adapter.py", "toy_games.py", "interface_draft.py"))
    files.extend(directory.parents[1] / "fow_shared" / name for name in ("contracts.py", "values.py"))
    return {str(p.relative_to(directory.parents[1])): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def play_game(pool, *, game, seed, paper_color, seconds, path, max_plies=None, agent_kwargs=None):
    referee = Referee()
    seeds = {"white": seed * 2 + 1, "black": seed * 2 + 2}
    agents = {p: PaperAgent(p, seeds[p], pool, baseline=p != paper_color, **(agent_kwargs or {})) for p in seeds}
    result = dict(game=game, seed=seed, agent_seeds=seeds, paper_color=paper_color,
                  seconds_per_move=seconds, status="running", plies=0, rules_id=RULES_ID)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        def write(record):
            stream.write(json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n")
            stream.flush()
        write(dict(event="start", **result))
        start = perf_counter()
        try:
            views = {p: referee.observe(p) for p in agents}
            for p, agent in agents.items():
                agent.observe(views[p], deadline=start+seconds)
            write(dict(event="position", ply=0, fen=referee._state.fen,
                       observations={p: asdict(v) for p, v in views.items()}))
            while not referee.is_terminal():
                if max_plies is not None and result["plies"] >= max_plies:
                    raise RuntimeError("administrative ply limit; unfinished, not a draw")
                mover = referee.current_player()
                agent = agents[mover]
                decision = agent.act(start+seconds)
                elapsed = perf_counter()-start
                if elapsed > seconds:
                    raise BudgetError(f"late action submission: {elapsed:.6f}s")
                decision.validate_for(views[mover])
                write(dict(event="decision", ply=result["plies"], player=mover,
                           elapsed_seconds=elapsed, decision=asdict(decision), trace=agent.trace,
                           tracker=agent.tracker.last_stats, timings=agent.timings))
                referee.apply(decision.move)
                start = perf_counter()
                result["plies"] += 1
                next_player = referee.current_player()
                views = {p: referee.observe(p) for p in agents}
                agents[mover].observe(views[mover], decision.move)
                agents[next_player].observe(views[next_player], deadline=start+seconds)
                write(dict(event="position", ply=result["plies"], fen=referee._state.fen,
                           observations={p: asdict(v) for p, v in views.items()}))
                path.with_suffix(".progress.json").write_text(json.dumps(dict(game=game, plies=result["plies"],
                    last_elapsed=elapsed, paper_color=paper_color, latest=decision.diagnostics)), encoding="utf-8")
            winner = referee.winner()
            result.update(status="completed", winner=winner,
                          paper_result="draw" if winner == "draw" else "win" if winner == paper_color else "loss",
                          reason=referee._rules.terminal(referee._state).reason)
        except Exception as exc:
            result.update(status="failed", error_type=type(exc).__name__, error=str(exc),
                          traceback=traceback.format_exc(), current_timings=getattr(agent,"timings",{}))
        finally:
            for agent in agents.values():
                agent.close()
        write(dict(event="finish", **result))
    return result


def summarize(results):
    totals = {color: {key: 0 for key in ("win", "draw", "loss")} for color in ("white", "black", "total")}
    for r in results:
        if r["status"] == "completed":
            totals[r["paper_color"]][r["paper_result"]] += 1
            totals["total"][r["paper_result"]] += 1
    return dict(wdl=totals, completed=sum(totals["total"].values()),
                failed=sum(r["status"] == "failed" for r in results), games=results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine")
    parser.add_argument("--config")
    parser.add_argument("--variant", choices=("main", "sixfold"), default="main")
    parser.add_argument("--output", required=True)
    parser.add_argument("--games", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--max-plies", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    runtime = load(args.config, args.variant)
    defaults = runtime["data"]["experiment"]
    args.games = defaults["games"] if args.games is None else args.games
    args.seed = defaults["seed"] if args.seed is None else args.seed
    args.seconds = defaults["seconds_per_move"] if args.seconds is None else args.seconds
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = code_manifest()
    engine = Path(args.engine or runtime["engine"]).resolve()
    config = dict(games=args.games, seed=args.seed, seconds=args.seconds, max_plies=args.max_plies,
                  source=source, engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                  engine=str(engine), python=platform.python_version(), platform=platform.platform(),
                  numpy=numpy.__version__, scipy=scipy.__version__, chess=chess.__version__,
                  runtime=runtime, value_variant=args.variant, rules_id=RULES_ID)
    manifest_path, summary_path = output / "manifest.json", output / "summary.json"
    results = []
    if args.resume:
        if json.loads(manifest_path.read_text(encoding="utf-8"))["config"] != config:
            raise ValueError("resume requires identical source, engine, environment and configuration")
        results = json.loads(summary_path.read_text(encoding="utf-8"))["games"]
        if any(r["status"] != "completed" for r in results):
            raise ValueError("failed run is immutable; fix and start a new named run")
    elif manifest_path.exists():
        raise ValueError("output already exists; use --resume or a new run directory")
    if not args.resume:
        repository = Path(__file__).resolve().parents[2]
        for relative in source:
            target = output / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((repository/relative).read_bytes())
        (output/"runtime.toml").write_bytes(Path(runtime["path"]).read_bytes())
        (output/"paper_2021.toml").write_bytes((Path(runtime["path"]).parent/"paper_2021.toml").read_bytes())
    with EnginePool(engine) as pool:
        if not args.resume:
            manifest_path.write_text(json.dumps(dict(created_utc=datetime.now(timezone.utc).isoformat(),
                                                     config=config, engine=pool.metadata), indent=2), encoding="utf-8")
        for game in range(len(results), args.games):
            if code_manifest() != source:
                raise RuntimeError("algorithm files changed during run")
            result = play_game(pool, game=game, seed=args.seed+game, paper_color="white" if game%2==0 else "black",
                               seconds=args.seconds, max_plies=args.max_plies,
                               path=output / f"game-{game:03d}.jsonl.gz", agent_kwargs=runtime["agent_kwargs"])
            results.append(result)
            summary_path.write_text(json.dumps(summarize(results), indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
            if result["status"] != "completed":
                raise SystemExit(1)


if __name__ == "__main__":
    main()
