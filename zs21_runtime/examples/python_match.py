"""Short real-agent integration example; a ply cap is unfinished, never a draw."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pair_a_prep.zs21.agent import PaperAgent
from pair_a_prep.zs21.config import load
from pair_a_prep.zs21.engine import EnginePool
from pair_a_prep.zs21.model import Referee
from pair_a_prep.zs21.rule_profile import RULES_ID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plies", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, help="optional fixed work for an interface smoke test")
    parser.add_argument("--output", type=Path, default=ROOT / "zs21_runtime/out/python-smoke.json")
    args = parser.parse_args()
    runtime, referee, records = load(), Referee(), []
    seconds = runtime["data"]["experiment"]["seconds_per_move"]
    with EnginePool(runtime["engine"]) as pool:
        agents = {p: PaperAgent(p, 2106+i, pool, baseline=p == "black", max_rounds=args.max_rounds,
                               **runtime["agent_kwargs"]) for i, p in enumerate(("white", "black"))}
        try:
            turn_start = perf_counter()
            for p, agent in agents.items():
                agent.observe(referee.observe(p), deadline=turn_start+seconds)
            while len(records) < args.plies and not referee.is_terminal():
                player = referee.current_player()
                decision = agents[player].act(turn_start+seconds)
                if perf_counter() > turn_start+seconds:
                    raise TimeoutError("late action")
                decision.validate_for(referee.observe(player))
                records.append(dict(player=player, decision=asdict(decision),
                                    elapsed_seconds=perf_counter()-turn_start))
                referee.apply(decision.move)
                turn_start = perf_counter()
                for viewer in (player, "black" if player == "white" else "white"):
                    agents[viewer].observe(referee.observe(viewer), decision.move if viewer == player else None,
                                           deadline=turn_start+seconds if viewer != player else None)
        finally:
            for agent in agents.values():
                agent.close()
    report = dict(rules_id=RULES_ID, status="completed" if referee.is_terminal() else "unfinished_smoke",
                  winner=referee.winner() if referee.is_terminal() else None,
                  max_rounds=args.max_rounds, plies=records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(dict(status=report["status"], winner=report["winner"], actions=len(records))))


if __name__ == "__main__":
    main()
