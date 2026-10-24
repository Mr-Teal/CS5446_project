"""Small, reproducibility-checked TrainingRecord pilots for the chess prototype."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter
import tracemalloc

from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.recording import read_records, write_records
from .belief_tracker import BeliefTracker
from .rules_adapter import RulesReferee
from .search_agent import FixedDepthPCFRAgent, SearchConfig


KINGS = "7k/8/8/8/8/8/8/K7 w - - 0 1"


def git_metadata(root):
    """Optional provenance; an archive is not a clean Git checkout.

    Reject metadata from an enclosing repository as well. Source hashes remain
    the provenance available for ZIP downloads or machines without Git.
    """
    metadata = dict(commit=None, git_status=None, git_metadata_available=False, git_errors={})

    def read(arguments):
        return subprocess.check_output(["git", *arguments], cwd=root, text=True,
                                       stderr=subprocess.PIPE, timeout=5)

    def unavailable(key, exc):
        detail = getattr(exc, "stderr", None) or str(exc)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        metadata["git_errors"][key] = detail.strip()

    try:
        repository = Path(read(["rev-parse", "--show-toplevel"]).strip()).resolve()
        if repository != root.resolve():
            metadata["git_errors"]["repository"] = "source root is not the Git repository root"
            return metadata
    except (OSError, subprocess.SubprocessError) as exc:
        unavailable("repository", exc)
        return metadata
    for key, arguments in (("commit", ["rev-parse", "HEAD"]),
                           ("git_status", ["status", "--short"])):
        try:
            value = read(arguments)
            metadata[key] = value.strip() if key == "commit" else value
        except (OSError, subprocess.SubprocessError) as exc:
            unavailable(key, exc)
    metadata["git_metadata_available"] = not metadata["git_errors"]
    return metadata


def semantic_records(records):
    """Ignore measured runtime only; keep hypotheses, policies, values and moves."""
    objects = [asdict(record) for record in records]
    for obj in objects:
        diagnostics = obj["decision"]["diagnostics"]
        diagnostics.pop("elapsed_ms", None)
        diagnostics.pop("over_budget", None)
    return objects


def pilot_configuration(evaluator, *, initial_fen, config, max_plies,
                        sample_size, max_candidates, d1=None):
    """Identify the whole pilot protocol, separate from the agent configuration.

    Output paths, batch size and base seed are not protocol identity: extending
    a batch retains its existing game IDs; each game's seed identifies that game.
    Optional D1 feature generation is part of the exported-data configuration.
    """
    def leaf_settings(leaf):
        if leaf is None:
            return None
        return {"name": leaf.name, **{key: getattr(leaf, key) for key in (
            "depth", "new_game_each_call", "call_timeout_s") if hasattr(leaf, key)}}

    return dict(version=2,
                agent_config_id=FixedDepthPCFRAgent(evaluator, config, initial_fen).config_id,
                search=asdict(config), initial_fen=initial_fen,
                leaf=leaf_settings(evaluator), d1_features=leaf_settings(d1),
                tracker=dict(implementation="exact-history-v1", sample_size=sample_size,
                             max_candidates=max_candidates, weighting="uniform_feasible_histories"),
                match=dict(rules_id="paper_fow_v1_proposed", max_plies=max_plies,
                           time_budget_ms=1000,
                           seeds="game=base+2*index; white=game; black=game+1"))


def pilot_config_id(configuration):
    payload = json.dumps(configuration, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "pcfr-pilot-v2:" + sha256(payload.encode("utf-8")).hexdigest()[:16]


def collect(evaluator, *, initial_fen=KINGS, config=None, games=2, max_plies=6,
            seed=17, sample_size=4, max_candidates=2000, d1=None):
    """Use the shared runner; each agent receives its own tracker and history."""
    config = config or SearchConfig(stop_on_time=False)
    if config.stop_on_time:
        raise ValueError("reproducible label pilots require stop_on_time=False")
    for name, value in dict(games=games, max_plies=max_plies,
                            sample_size=sample_size, max_candidates=max_candidates).items():
        if type(value) is not int or value < 1:
            raise ValueError(name + " must be a positive integer")
    protocol = pilot_configuration(evaluator, initial_fen=initial_fen, config=config,
                                    max_plies=max_plies, sample_size=sample_size,
                                    max_candidates=max_candidates, d1=d1)
    identifier = pilot_config_id(protocol)
    records, summaries = [], []
    for game_index in range(games):
        game_seed = seed + 2 * game_index
        game_records, updates = [], []
        game_id = f"pcfr-pilot-v2-{identifier.rsplit(':', 1)[-1]}-{game_seed}"

        class RecordingAgent(FixedDepthPCFRAgent):
            def act(self, turn):
                record = replace(self.label(turn, game_id), config_id=identifier)
                if d1 is not None:
                    # D1 is a separate input feature, not a replacement for solver labels.
                    values = tuple(d1.evaluate_boards(
                        [h.fen for h in turn.belief.hypotheses], turn.observation.player))
                    diagnostics = dict(record.decision.diagnostics)
                    diagnostics.update({f"d1:{i}": v for i, v in enumerate(values)})
                    record = replace(record, decision=replace(record.decision, diagnostics=diagnostics))
                game_records.append(record)
                return record.decision

        class MeasuredTracker(BeliefTracker):
            def update(self, observation, own_move=None):
                start = perf_counter()
                belief = super().update(observation, own_move)
                updates.append(dict(player=observation.player, ply=observation.ply,
                                    population_size=self.population_size,
                                    returned=len(belief.hypotheses),
                                    elapsed_ms=(perf_counter() - start) * 1000))
                return belief

        agents = {p: RecordingAgent(evaluator, config, initial_fen) for p in ("white", "black")}
        trackers = {p: MeasuredTracker(initial_fen, sample_size=sample_size,
                                      max_candidates=max_candidates) for p in agents}
        if hasattr(evaluator, "new_game"):
            evaluator.new_game()
        start = perf_counter()
        result = play_game(RulesReferee(initial_fen), agents, trackers,
                           MatchConfig(1000, max_plies, game_seed,
                                       "paper_fow_v1_proposed", evaluator.name,
                                       getattr(evaluator, "depth", 0)))
        records.extend(game_records)
        summaries.append(dict(game_id=game_id, seed=game_seed, records=len(game_records),
                              # A diagnostic ply cap is not evidence of an actual draw.
                              outcome=None if result.stopped_at_ply_limit else result.winner,
                              stopped_at_ply_limit=result.stopped_at_ply_limit,
                              wall_ms=(perf_counter() - start) * 1000,
                              tracker_updates=updates))
    return records, summaries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evaluator", choices=("material", "stockfish-d1"), default="material")
    parser.add_argument("--stockfish", default="stockfish")
    parser.add_argument("--include-d1", action="store_true")
    parser.add_argument("--initial-fen", default=KINGS)
    parser.add_argument("--games", type=int, default=2)
    parser.add_argument("--max-plies", type=int, default=6)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--max-nodes", type=int, default=5000)
    parser.add_argument("--sample-size", type=int, default=4)
    parser.add_argument("--max-candidates", type=int, default=2000)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("output already exists; choose a fresh directory")
    args.out.mkdir(parents=True)
    report = dict(status="running", created=datetime.now(timezone.utc).isoformat(),
                  settings={**vars(args), "out": str(args.out)},
                  commit=None, git_status=None, git_metadata_available=False, git_errors={},
                  source_sha256={},
                  limitations=["Fixed-depth sampled-root game, not complete Obscuro or KLUSS.",
                               "Small public-start fixtures, not a strength or training-quality study.",
                               "Exact tracker capacity does not bound rejected-successor work.",
                               "Peak memory below is Python allocations, not process RSS."])
    try:
        # All fallible setup after creating the output belongs under reporting.
        from contextlib import ExitStack

        root = Path(__file__).resolve().parents[1]
        report.update(python=sys.version, platform=platform.platform(), **git_metadata(root))
        source_paths = [root / "pair_a_prep" / name for name in (
            "label_pilot.py", "search_agent.py", "chess_search.py", "pcfr.py", "toy_games.py",
            "rules_adapter.py", "belief_tracker.py")]
        source_paths += [root / "fow_shared" / name for name in (
            "contracts.py", "values.py", "evaluation.py", "recording.py")]
        report["source_sha256"] = {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
                                    for p in source_paths}
        from pairb.label_validation import validate
        from pairb.material import MaterialEvaluator
        from pairb.stockfish import StockfishEvaluator

        config = SearchConfig(args.depth, args.rounds, args.max_nodes, stop_on_time=False)
        report["settings"]["config"] = asdict(config)
        settings = dict(initial_fen=args.initial_fen, config=config, games=args.games,
                        max_plies=args.max_plies, seed=args.seed, sample_size=args.sample_size,
                        max_candidates=args.max_candidates)
        with ExitStack() as stack:
            d1 = (stack.enter_context(StockfishEvaluator(1, args.stockfish, new_game_each_call=True))
                  if args.include_d1 or args.evaluator == "stockfish-d1" else None)
            leaf = d1 if args.evaluator == "stockfish-d1" else MaterialEvaluator()
            source_paths.append(Path(inspect.getfile(type(leaf))))
            if d1 is not None:
                source_paths.append(Path(inspect.getfile(type(d1))))
                report["engine"] = dict(name=d1.engine.id, threads=1, hash_mb=16, depth=1,
                                        new_game_each_call=True,
                                        sha256=sha256(Path(shutil.which(args.stockfish) or args.stockfish).read_bytes()).hexdigest())
            protocol = pilot_configuration(leaf, d1=d1, **{
                key: value for key, value in settings.items() if key not in ("games", "seed")})
            report["pilot_configuration"] = protocol
            report["config_id"] = pilot_config_id(protocol)
            report["source_sha256"] = {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
                                        for p in source_paths}
            tracemalloc.start()
            records, games = collect(leaf, d1=d1, **settings)
            repeat, _ = collect(leaf, d1=d1, **settings)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            if semantic_records(records) != semantic_records(repeat):
                raise ValueError("fixed-work repeat changed a hypothesis, strategy, value or move")
            part = args.out / "part-000.jsonl"
            write_records(part, records)
            if semantic_records(list(read_records(part))) != semantic_records(records):
                raise ValueError("TrainingRecord JSONL round trip changed semantic fields")
            manifest = dict(created=report["created"], records=len(records), config_id=records[0].config_id,
                            prototype=True, label_definition="raw_profile_continuation_no_gadget",
                            evaluator=leaf.name, include_d1=d1 is not None,
                            pilot_configuration=protocol,
                            sha256=sha256(part.read_bytes()).hexdigest())
            (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            checked = validate(args.out, require_d1=args.include_d1, require_played_policy=True)
            if checked.errors:
                raise ValueError("Pair B label acceptance failed: " + "; ".join(checked.errors))
            report.update(status="passed", records=len(records), games=games,
                          repeat_semantics_identical=True, jsonl_roundtrip=True,
                          python_peak_bytes=peak, validation=dict(errors=checked.errors, warnings=checked.warnings),
                          max_search_nodes=max(r.decision.diagnostics["search_nodes"] for r in records),
                          max_population=max(u["population_size"] for g in games for u in g["tracker_updates"]))
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        (args.out / "report.json").write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + "\n",
                                              encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "records", "max_search_nodes", "max_population")}, indent=2))


if __name__ == "__main__":
    main()
