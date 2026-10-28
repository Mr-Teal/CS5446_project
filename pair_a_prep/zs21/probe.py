"""Reproducible engine probes and bounded, explicitly non-match integration runs."""

import argparse
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
import json

import chess

from .engine import EnginePool
from .agent import PaperAgent
from .model import Referee
from .match import code_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--plies", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=8.)
    parser.add_argument("--rounds", type=int)
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(kind="integration_probe_not_formal_match", moves=[], source=code_manifest())
    with EnginePool(args.engine) as pool:
        report["engine"] = pool.metadata
        if not args.plies:
            cases = {
                "initial": chess.STARTING_FEN,
                "mover_checked": "4k3/8/8/8/8/8/4r3/4K3 w - - 0 1",
                "opponent_king_attacked": "4k3/4R3/8/8/8/8/8/4K3 w - - 0 1",
                "adjacent_kings": "8/8/8/8/8/4k3/4K3/8 w - - 0 1",
                "both_kings_attacked": "4k3/4R3/8/8/8/8/4r3/4K3 w - - 0 1",
                "checkmate": "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
                "stalemate": "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
                "castle_through_check": "4k3/8/8/8/2b5/8/8/4K2R w K - 0 1",
                "captured_black_king": "8/8/8/8/8/8/8/4K3 b - - 0 1",
            }
            boards = [chess.Board(fen) for fen in cases.values()]
            outputs = []
            timings = []
            for _ in range(2):
                start = perf_counter()
                outputs.append([asdict(e) for e in pool.evaluate(boards, "white")])
                timings.append(perf_counter()-start)
            report.update(cases=cases, outputs=outputs, seconds=timings,
                          repeat_equal=outputs[0] == outputs[1])
            start = perf_counter()
            pool.evaluate([chess.Board()] * 400, "white")
            report["steady_seconds_400_queries"] = perf_counter()-start
        else:
            referee = Referee()
            agents = {p: PaperAgent(p, 100+i, pool, baseline=(p=="black"), max_rounds=args.rounds)
                      for i, p in enumerate(("white", "black"))}
            start = perf_counter()
            for p, agent in agents.items():
                agent.observe(referee.observe(p))
            report["config"] = dict(seconds=args.seconds, rounds=args.rounds)
            try:
                for ply in range(args.plies):
                    mover = referee.current_player()
                    agent = agents[mover]
                    decision = agent.act(start + args.seconds)
                    elapsed = perf_counter() - start
                    record = dict(ply=ply, player=mover, seconds=elapsed, decision=asdict(decision),
                                  trace=agent.trace, timings=agent.timings)
                    report["moves"].append(record)
                    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
                    print(json.dumps({k: record[k] for k in ("ply", "player", "seconds", "decision")}), flush=True)
                    referee.apply(decision.move)
                    start = perf_counter()
                    next_player = referee.current_player()
                    # The newly acting player's clock includes delivery and all waiting.
                    agents[mover].observe(referee.observe(mover), decision.move)
                    agents[next_player].observe(referee.observe(next_player), deadline=start+args.seconds)
                    if referee.is_terminal():
                        report["outcome"] = referee.winner()
                        break
                else:
                    report["outcome"] = "probe_ply_limit_not_a_draw"
            except Exception as exc:
                import traceback
                report["error"] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc(),
                                       timings=agent.timings)
                raise
            finally:
                path.write_text(json.dumps(report, indent=2), encoding="utf-8")
                for agent in agents.values():
                    agent.close()
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(str(path), flush=True)


if __name__ == "__main__":
    main()
