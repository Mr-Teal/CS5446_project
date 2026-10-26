"""Compatibility smoke test for the repository's existing AgentInput interface."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fow_shared.evaluation import MatchConfig, play_game
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.zs21.config import load
from pair_a_prep.zs21.engine import EnginePool
from pair_a_prep.zs21.integration import SharedAgent
from pair_a_prep.zs21.model import Referee
from pair_a_prep.zs21.rule_profile import RULES_ID


def main():
    runtime = load()
    config = MatchConfig(time_budget_ms=16000, max_plies=2, seed=2106,
                         rules_id=RULES_ID, engine_id="stockfish13-zs21-v6", leaf_depth=1)
    with EnginePool(runtime["engine"]) as pool:
        agents = {p: SharedAgent(pool, baseline=p == "black", max_rounds=1, **runtime["agent_kwargs"])
                  for p in ("white", "black")}
        trackers = {p: BeliefTracker(sample_size=200) for p in agents}
        try:
            result = play_game(Referee(), agents, trackers, config)
        finally:
            for agent in agents.values():
                agent.close()
    report = dict(interface="fow_shared", status="unfinished_smoke" if result.stopped_at_ply_limit else "completed",
                  winner=None if result.stopped_at_ply_limit else result.winner,
                  plies=[asdict(ply) for ply in result.plies])
    target = ROOT / "zs21_runtime/out/shared-smoke.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(dict(status=report["status"], actions=len(result.plies))))


if __name__ == "__main__":
    main()
