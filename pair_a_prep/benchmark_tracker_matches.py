"""Trace the real Pair C runner, including failed prefixes and whole-turn cost.

This opt-in diagnostic leaves the shared runner's defaults unchanged. Private
observations/own actions and referee-applied moves are separate output streams.
"""

import argparse
import configparser
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from .benchmark_belief_tracker import memory_usage


class TurnBudgetError(RuntimeError):
    pass


class MatchTrace:
    def __init__(self, output, config, whole_turn_ms=None):
        self.output, self.config = output, config
        self.whole_turn_ms = whole_turn_ms
        self.turn_started = None

    def write(self, name, row):
        with (self.output / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"seed": self.config.seed, **row}) + "\n")

    def elapsed(self):
        return (perf_counter() - self.turn_started) * 1000

    def referee(self, inner):
        trace = self

        class TracedReferee:
            def __getattr__(self, name):
                return getattr(inner, name)

            def reset(self, seed):
                inner.reset(seed)
                trace.turn_started = perf_counter()

            def apply(self, move):
                player = inner.current_player()
                inner.apply(move)
                trace.turn_started = perf_counter()
                trace.write("referee.jsonl", {"event": "applied", "player": player,
                    "move": move, "ply": inner.observe(player).ply})

        return TracedReferee()

    def tracker(self, inner, player):
        trace = self

        class TracedTracker:
            def reset(self, player, seed):
                self.seed = seed
                inner.reset(player, seed)

            def update(self, observation, own_move=None):
                trace.write("private-stream.jsonl", {"player":player, "tracker_seed":self.seed,
                    "observation":asdict(observation), "own_move":own_move})
                policy = inner.tracker  # Pair C RecordingTracker wraps the factory result.
                original_total = getattr(policy, "total_ms", None)
                if trace.whole_turn_ms is not None and original_total is not None:
                    policy.total_ms = min(original_total, max(0, trace.whole_turn_ms - trace.elapsed()))
                began = perf_counter()
                error = None
                try:
                    return inner.update(observation, own_move)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    raise
                finally:
                    elapsed = (perf_counter() - began) * 1000
                    if original_total is not None:
                        policy.total_ms = original_total
                    result = getattr(policy, "last_update", None)
                    trace.write("updates.jsonl", {"player":player, "ply":observation.ply,
                        "wall_ms":elapsed, "error":error, **memory_usage(), "result":None if result is None else
                        {key:getattr(result,key) for key in result.__dataclass_fields__ if key != "belief"}})

        return TracedTracker()

    def agent(self, inner, player):
        trace = self

        class TracedAgent:
            def __getattr__(self, name):
                return getattr(inner, name)

            def act(self, turn):
                before = trace.elapsed()
                if trace.whole_turn_ms is not None:
                    remaining = int(trace.whole_turn_ms - before)
                    if remaining <= 0:
                        raise TurnBudgetError("tracking exhausted the whole-turn allowance")
                    turn = replace(turn, time_budget_ms=min(turn.time_budget_ms, remaining))
                began = perf_counter()
                decision = inner.act(turn)
                elapsed = (perf_counter() - began) * 1000
                whole = trace.elapsed()
                trace.write("actions.jsonl", {"player":player, "ply":turn.observation.ply,
                    "decision":asdict(decision), "agent_ms":elapsed, "pre_agent_ms":before,
                    "whole_turn_ms":whole, "input_budget_ms":turn.time_budget_ms,
                    "turn_over_budget":trace.whole_turn_ms is not None and whole > trace.whole_turn_ms})
                if trace.whole_turn_ms is not None and whole > trace.whole_turn_ms:
                    raise TurnBudgetError("agent exceeded the remaining whole-turn allowance")
                return decision

        return TracedAgent()


def run(args):
    from pair_c import run_evaluation as runner
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    parser = configparser.ConfigParser()
    parser.read(args.config, encoding="utf-8")
    for side in ("player_a", "player_b"):
        parser[side].update(stockfish_path=str(args.engine.resolve()), tracker_backend="native",
            tracker_slice_ms=str(args.tracker_ms), tracker_total_ms=str(args.tracker_ms),
            tracker_memory_mb=str(args.memory_mb), tracker_max_resumes="0", max_candidates="none")
    parser["match"].update(games=str(args.games), max_plies=str(args.max_plies), seed=str(args.seed))
    parser["output"]["directory"] = str(output / "runner")
    config_path = output / "config.ini"
    with config_path.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    config = runner.load_config(config_path)
    repo = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__), *[repo / "pair_a_prep" / name for name in
        ("belief_tracker.py", "_belief_graph.py", "_belief_memory.py", "evaluation_tracking.py", "evaluation_factories.py")]]
    (output / "plan.json").write_text(json.dumps({"seed":args.seed,"games":args.games,
        "max_plies":args.max_plies,"tracker_ms":args.tracker_ms,"logical_mib":args.memory_mb,
        "whole_turn_ms":args.whole_turn_ms,
        "clock_scope":"referee handoff through agent return; includes both serial tracker updates and tracing",
        "os_hard_deadline":False,"engine_sha256":sha256(args.engine.read_bytes()).hexdigest(),
        "source_sha256":{p.relative_to(repo).as_posix():sha256(p.read_bytes()).hexdigest() for p in source_paths}},indent=2),encoding="utf-8")
    original = runner.play_game

    def traced(referee, agents, trackers, config):
        trace = MatchTrace(output, config, args.whole_turn_ms)
        try:
            result = original(trace.referee(referee),
                {p:trace.agent(a,p) for p,a in agents.items()},
                {p:trace.tracker(t,p) for p,t in trackers.items()}, config)
            trace.write("attempts.jsonl", {"status":"capped" if result.stopped_at_ply_limit else "complete",
                "plies":len(result.plies),"winner":None if result.stopped_at_ply_limit else result.winner})
            return result
        except Exception as exc:
            trace.write("attempts.jsonl", {"status":"failed","error":f"{type(exc).__name__}: {exc}"})
            raise

    runner.play_game = traced
    try:
        summary = runner.run(config, config_path)
    finally:
        runner.play_game = original
    print(json.dumps({k:summary[k] for k in ("games_completed","games_scored","games_failed","games_capped")}))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--engine",type=Path,required=True)
    parser.add_argument("--seed",type=int,default=17)
    parser.add_argument("--games",type=int,default=2)
    parser.add_argument("--max-plies",type=int,default=400)
    parser.add_argument("--tracker-ms",type=float,default=5000)
    parser.add_argument("--memory-mb",type=float,default=512)
    parser.add_argument("--whole-turn-ms",type=float)
    args = parser.parse_args()
    summary = run(args)
    if summary["games_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
