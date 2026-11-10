"""Self-play label collection for Pair B's belief network.

Implements pair_b/docs/label_definitions.md with the sampled subgame agent:

  - one TrainingRecord per solver decision, for both colours, split by game_id;
  - 2 to 8 random opening plies per game (drawn from the game seed), played
    through the shared runner so both trackers see every observation from ply 0;
    those plies write no record;
  - the tail-guarded exact tracker, so a long game is not lost to memory;
  - a budget failure plays the anytime fallback and writes no record, because a
    fallback policy is not a label.

One part file per game (part-NNNN.jsonl) so a killed run keeps its finished
games, progress.jsonl as it goes, manifest.json at the end, then Pair B's own
validator over the folder. Running again with the same output skips games whose
part file exists. A game that dies (the guarded tracker finding no candidate
after a prune, a contract violation) is written as far as it got, logged with
its error in progress.jsonl, and the run continues.

The agent's clock is the move budget as in play; tracking is outside it, as in
the paper. A clocked run is therefore not bit-reproducible; --no-clock fixes the
round count and is for tests.

    python -m pair_a_prep.label_run --out runs/labels-01 --games 50 --seed 5001 \\
        --evaluator material --time-budget-ms 5000 --max-states 96000

Self-play with the belief network as the leaf (no engine at play time; the records are then labels of the
search with the network inside it, the ReBeL-style loop):

    python -m pair_a_prep.label_run --out runs/selfplay-g1 --games 50 --seed 90001 \\
        --evaluator belief_network --checkpoint pair_b/checkpoints/<run>/best.pt --device cuda
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import sys

import chess.engine
from time import perf_counter

from fow_shared.contracts import Decision
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.recording import write_records
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker
from .chess_search import SearchBudgetError, TreeCapacityError
from .chess_subgame_agent import ChessSubgameAgent
from .rules_adapter import RulesReferee
from .tail_guard import TailGuardedBeliefTracker


class RevivingLeaf:
    """A leaf evaluator whose engine is reopened after a timed-out or dead call.

    Pair B's StockfishEvaluator closes the engine when one call exceeds call_timeout_s and raises
    TimeoutError; every later call then fails with EngineTerminatedError, so without this one slow
    call ends the game and every remaining game of the run (labels-sf8 tasks 5 and 6, 2026-11-09).
    Here the failing call revives the engine and raises SearchBudgetError instead, so only that
    move falls back and the game goes on with a fresh engine.
    """

    def __init__(self, make):
        self.make = make
        self.base = make()
        self.revivals = 0

    def __getattr__(self, key):
        return getattr(self.base, key)

    def evaluate_children(self, fen):
        try:
            return self.base.evaluate_children(fen)
        except (TimeoutError, chess.engine.EngineError) as exc:
            try:
                self.base.close()
            except Exception:
                pass
            self.base = self.make()
            self.revivals += 1
            print(f"leaf revived ({self.revivals}) after {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            raise SearchBudgetError(f"leaf call failed and the engine was reopened: {type(exc).__name__}") from exc

    def close(self):
        self.base.close()

RULES_ID = "paper_fow_v1_proposed"


class LabelAgent(ChessSubgameAgent):
    """Random moves for the opening plies, then one label per decision."""

    def __init__(self, evaluator, config, initial_fen, *, game_id, protocol_id, opening_plies, opening_seed, records):
        super().__init__(evaluator, config, initial_fen)
        self.game_id = game_id
        self.protocol_id = protocol_id
        self.opening_plies = opening_plies
        self.opening_rng = Random(opening_seed)
        self.records = records
        self.fallbacks = 0
        self.opening_moves = 0

    def act(self, turn):
        moves = turn.observation.legal_moves
        if turn.observation.ply < self.opening_plies:
            self.opening_moves += 1
            policy = dict.fromkeys(moves, 1/len(moves))
            decision = Decision(self.opening_rng.choice(moves), policy, dict(opening=1., fallback=0.))
            decision.validate_for(turn.observation)
            return decision
        started = perf_counter()
        try:
            record = self.label(turn, self.game_id)
        except (SearchBudgetError, TreeCapacityError) as exc:
            self.fallbacks += 1
            print(f"fallback game={self.game_id} ply={turn.observation.ply} after {perf_counter() - started:.1f}s: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return self.fallback_decision(turn, exc, started)
        # Records carry the protocol identity, as the pilot did; the agent's own
        # configuration identity goes in the manifest. The validator requires every
        # record in a folder to agree with its manifest.
        record = replace(record, config_id=self.protocol_id)
        self.records.append(record)
        return record.decision


def make_tracker(initial_fen, sample_size, max_states):
    inner = BeliefTracker(initial_fen, sample_size=sample_size, max_candidates=None)
    inner.evaluation_policy = "exact"
    return TailGuardedBeliefTracker(inner, max_states)


def protocol(config, evaluator, *, time_budget_ms, max_states, sample_size, opening_range,
             max_plies, initial_fen):
    leaf = {"name": evaluator.name, **{key: getattr(evaluator, key) for key in
                                       ("depth", "new_game_each_call", "call_timeout_s") if hasattr(evaluator, key)}}
    return dict(version=1, agent=ChessSubgameAgent.name, search=asdict(config), leaf=leaf,
                engine=getattr(evaluator, "handoff_identity", None),
                tracker=dict(implementation="tail-guarded-exact-v1", sample_size=sample_size, max_states=max_states),
                match=dict(rules_id=RULES_ID, time_budget_ms=time_budget_ms, max_plies=max_plies,
                           initial_fen=initial_fen, opening_plies=list(opening_range),
                           seeds="game=base+2*index; white=game; black=game+1"),
                label_definition="pair_b/docs/label_definitions.md")


def protocol_id(proto):
    return "solver-labels-v1:" + sha256(json.dumps(proto, sort_keys=True, default=str).encode()).hexdigest()[:16]


def collect(out, *, games, seed, evaluator, config, time_budget_ms, max_states, sample_size,
            opening_range=(2, 8), max_plies=200, initial_fen=None, log=print):
    """Play `games` self-play games and write one part file each. Returns (id, protocol, summaries)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lo, hi = opening_range
    if not (0 <= lo <= hi):
        raise ValueError("opening_range must be 0 <= min <= max")
    proto = protocol(config, evaluator, time_budget_ms=time_budget_ms, max_states=max_states,
                     sample_size=sample_size, opening_range=opening_range, max_plies=max_plies,
                     initial_fen=initial_fen)
    identity = protocol_id(proto)
    summaries = []
    for index in range(games):
        game_seed = seed + 2*index
        part = out / f"part-{index:04d}.jsonl"
        if part.exists():
            log(f"game {index}: {part.name} exists, skipping")
            continue
        game_id = f"{identity}-{game_seed}"
        opening = Random(game_seed).randint(lo, hi)
        records = []
        agents = {player: LabelAgent(evaluator, config, initial_fen, game_id=game_id, protocol_id=identity,
                                     opening_plies=opening, opening_seed=game_seed + offset, records=records)
                  for offset, player in enumerate(("white", "black"))}
        trackers = {player: make_tracker(initial_fen, sample_size, max_states) for player in agents}
        if hasattr(evaluator, "new_game"):
            evaluator.new_game()
        started = perf_counter()
        result, error = None, None
        try:
            result = play_game(RulesReferee(initial_fen), agents, trackers,
                               MatchConfig(time_budget_ms, max_plies, game_seed, RULES_ID,
                                           evaluator.name, getattr(evaluator, "depth", 0)))
        except Exception as exc:
            # One dead game must not end the run. The tail guard can prune the
            # true history, after which an observation may match no retained
            # hypothesis (BeliefBudgetError from the tracker); whatever the cause,
            # the decisions labelled before it are labels, the part file is still
            # written so a resume skips this game, and the error goes to progress.
            error = f"{type(exc).__name__}: {exc}"
        write_records(part, records)
        # Every ply is exactly one opening move, one label or one fallback.
        plies = (len(result.plies) if result is not None else
                 sum(agent.opening_moves + agent.fallbacks for agent in agents.values()) + len(records))
        summary = dict(index=index, game_id=game_id, seed=game_seed, opening_plies=opening,
                       plies=plies, records=len(records),
                       fallbacks=sum(agent.fallbacks for agent in agents.values()),
                       guards=sum(tracker.guards for tracker in trackers.values()),
                       winner=None if result is None or result.stopped_at_ply_limit else result.winner,
                       stopped_at_ply_limit=result is not None and result.stopped_at_ply_limit,
                       wall_s=round(perf_counter()-started, 1), part=part.name, error=error)
        summaries.append(summary)
        with (out / "progress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(summary) + "\n")
        log(f"game {index}: seed {game_seed}, {summary['plies']} plies, {summary['records']} records, "
            f"{summary['fallbacks']} fallbacks, {summary['guards']} guards, {summary['wall_s']} s"
            + (f"; FAILED {error}" if error else ""))
    return identity, proto, summaries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--games", type=int, default=50)
    parser.add_argument("--seed", type=int, default=5001)
    parser.add_argument("--evaluator", choices=("material", "stockfish", "belief_network"), default="material")
    parser.add_argument("--checkpoint", default="", help="best.pt of the belief network, for --evaluator belief_network")
    parser.add_argument("--device", default="cpu", help="torch device of the belief network leaf (cpu, cuda)")
    parser.add_argument("--stockfish", default="/usr/games/stockfish")
    parser.add_argument("--stockfish-sha256", default="")
    parser.add_argument("--leaf-depth", type=int, default=1, help="Stockfish search depth per leaf call")
    parser.add_argument("--stockfish-call-timeout-s", type=float, default=2.0,
                        help="seconds before one engine call is abandoned; raise it with the depth")
    parser.add_argument("--time-budget-ms", type=int, default=5000)
    parser.add_argument("--expansion-fraction", type=float, default=0.7,
                        help="share of the move clock in which the tree may still be built or grown")
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--max-states", type=int, default=96000)
    parser.add_argument("--sample-size", type=int, default=16)
    parser.add_argument("--opening-plies", type=int, nargs=2, default=(2, 8), metavar=("MIN", "MAX"))
    parser.add_argument("--initial-fen", default=None)
    parser.add_argument("--solver-rounds", type=int, default=1024)
    parser.add_argument("--max-nodes", type=int, default=16384)
    parser.add_argument("--max-evaluator-calls", type=int, default=4096)
    parser.add_argument("--growth-headroom", type=int, default=1024,
                        help="nodes under --max-nodes that in-turn growth leaves free for the next turn's fresh "
                             "roots; at native speed a move fills the cap and 0 made ~13 %% of decisions fall back")
    parser.add_argument("--no-clock", action="store_true", help="fixed rounds, reproducible; for tests")
    parser.add_argument("--commit", default="", help="source commit to record; inside a container the "
                        "worktree's .git pointer resolves to a host path git cannot read")
    args = parser.parse_args(argv)

    from .evaluation_factories import _load_leaf
    settings = {"leaf_evaluator": args.evaluator}
    if args.evaluator == "stockfish":
        settings.update(leaf_depth=str(args.leaf_depth), stockfish_path=args.stockfish,
                        stockfish_sha256=args.stockfish_sha256,
                        stockfish_call_timeout_s=str(args.stockfish_call_timeout_s))
    elif args.evaluator == "belief_network":
        if not args.checkpoint:
            parser.error("--evaluator belief_network requires --checkpoint")
        # The checkpoint's sha256 enters the protocol through the leaf's handoff identity, so every
        # generation of self-play labels gets its own config_id.
        settings.update(checkpoint_path=args.checkpoint, device=args.device)
    leaf = RevivingLeaf(lambda: _load_leaf(settings))
    config = AnytimeConfig(growth="one_sided", rounds=args.solver_rounds, max_nodes=args.max_nodes,
                           max_evaluator_calls=args.max_evaluator_calls, stop_on_time=not args.no_clock,
                           expansion_fraction=args.expansion_fraction, growth_headroom=args.growth_headroom,
                           initial_depth=1, max_depth=2, rounds_per_stage=2, final_rounds=2,
                           schedule="alternating")
    created = datetime.now(timezone.utc).isoformat()
    # Taken while the evaluator is open: a Stockfish leaf is closed before the manifest.
    agent_config_id = ChessSubgameAgent(leaf, config, args.initial_fen).config_id
    try:
        identity, proto, summaries = collect(
            args.out, games=args.games, seed=args.seed, evaluator=leaf, config=config,
            time_budget_ms=args.time_budget_ms, max_states=args.max_states,
            sample_size=args.sample_size, opening_range=tuple(args.opening_plies),
            max_plies=args.max_plies, initial_fen=args.initial_fen)
    finally:
        if hasattr(leaf, "close"):
            leaf.close()
    from pairb.label_validation import validate
    report = validate(args.out, require_played_policy=True)
    progress = [json.loads(line) for line in (args.out / "progress.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    from .label_pilot import git_metadata
    manifest = dict(created=created, finished=datetime.now(timezone.utc).isoformat(),
                    config_id=identity, protocol=proto, agent_config_id=agent_config_id,
                    commit_recorded=args.commit or None,
                    games=len(progress), records=sum(row["records"] for row in progress),
                    fallbacks=sum(row["fallbacks"] for row in progress),
                    guards=sum(row["guards"] for row in progress),
                    failed=sum(1 for row in progress if row.get("error")),
                    validation=dict(files=report.files, errors=len(report.errors),
                                    warnings=len(getattr(report, "warnings", []))),
                    **git_metadata(Path(__file__).resolve().parents[1]))
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"{manifest['games']} games ({manifest['failed']} failed), {manifest['records']} records, "
          f"{manifest['fallbacks']} fallbacks, {manifest['guards']} guards; validation errors: {len(report.errors)}")
    for error in report.errors[:10]:
        print("  error:", error)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
