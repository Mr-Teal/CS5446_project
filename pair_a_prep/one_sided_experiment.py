"""Reproducible engineering checks; capped games are never scored as draws."""

from dataclasses import asdict
import argparse
from .provenance import source_manifest, NORMALIZATION, git_revision
import json
from pathlib import Path
import platform

from fow_shared.contracts import AgentInput, Belief, Hypothesis
from fow_shared.evaluation import MatchConfig, play_game
from pairb.material import MaterialEvaluator
from .anytime_agent import AnytimeConfig, AnytimePCFRAgent
from .belief_tracker import BeliefTracker
from .rules_adapter import RulesAdapter, RulesReferee


START = "7k/8/8/8/8/8/8/K7 w - - 0 1"
OUT = Path(__file__).with_name("results") / "one_sided_reference.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = dict(rounds=12, rounds_per_stage=2, final_rounds=2,
                  initial_depth=1, max_depth=3, max_nodes=512,
                  max_evaluator_calls=32, stop_on_time=False)
    rules = RulesAdapter()
    state = rules.initial_state(START)
    turn = AgentInput(rules.observe(state, "white"),
                      Belief("white", 0, (Hypothesis(state.fen, 1.0, "public-start"),)), 10000)
    rows = []
    for mode in ("uniform", "one_sided"):
        for seed in (17, 29, 41):
            agent = AnytimePCFRAgent(MaterialEvaluator(), AnytimeConfig(growth=mode, **config), START)
            agent.reset("white", seed)
            decision = agent.act(turn)
            rows.append(dict(mode=mode, seed=seed, config_id=agent.config_id,
                             move=decision.move, policy=decision.root_policy,
                             diagnostics=decision.diagnostics))
    games = []
    for selected_side in ("white", "black"):
        players = {side: AnytimePCFRAgent(MaterialEvaluator(), AnytimeConfig(
            growth="one_sided" if side == selected_side else "uniform", **config), START)
                   for side in ("white", "black")}
        trackers = {side: BeliefTracker(START, sample_size=3, max_candidates=2000) for side in players}
        result = play_game(RulesReferee(START), players, trackers,
                           MatchConfig(10000, 6, 17, "paper_fow_v1_proposed", "material", 0))
        games.append(dict(one_sided_colour=selected_side,
                          outcome=None if result.stopped_at_ply_limit else result.winner,
                          capped=result.stopped_at_ply_limit,
                          plies=[asdict(ply) for ply in result.plies],
                          final_diagnostics={side: agent.last_result.decision.diagnostics
                                             for side, agent in players.items()}))
    sources = source_manifest()
    report = dict(purpose="engineering smoke, not playing-strength evidence", python=platform.python_version(),
                  initial_fen=START, config=config, rules_id="paper_fow_v1_proposed",
                  evaluator="material", source_sha256=sources, source_hash_convention=NORMALIZATION,
                  base_commit_at_execution=git_revision(), root_checks=rows, games=games)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(output=str(output), root_checks=len(rows), games=len(games),
                          capped=sum(g["capped"] for g in games),
                          over_budget=sum(p["over_budget"] for g in games for p in g["plies"]))))


if __name__ == "__main__":
    main()
