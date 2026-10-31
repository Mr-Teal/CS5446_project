"""Capture actual private-turn projection diagnostics without changing decisions."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform

import numpy as np

from fow_shared.evaluation import MatchConfig, play_game
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker, BeliefCapacityError
from .chess_subgame_agent import ChessSubgameAgent
from .pcfr import PredictiveRMPlus
from .provenance import source_manifest, NORMALIZATION, git_revision
from .rules_adapter import RulesReferee
from .transition_audit import audit_transition


class AuditedAgent(ChessSubgameAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trace = []

    def act(self, turn):
        previous = self.saved
        decision = super().act(turn)
        row = dict(ply=turn.observation.ply, player=turn.observation.player,
            move=decision.move, config_id=self.config_id, diagnostics=decision.diagnostics,
            status="fallback" if decision.diagnostics["fallback"] else "cold" if previous is None else "projected",
            transition=None)
        if row["status"] == "projected":
            row["transition"] = audit_transition(previous, self.last_projection)
        self.trace.append(row)
        return decision


def aggregate_state_counterexample():
    """One aggregated minimizer need not identify reweighted history feedback."""
    utilities = (((2., 0.), (0., 0.)), ((0., 0.), (2., 0.)))
    def state(weights, rows):
        item = PredictiveRMPlus(2, predictive=False)
        item.next_strategy()
        item.observe(sum(w*np.array(u) for w, u in zip(weights, rows)))
        return item
    old = [state((.5, .5), rows) for rows in utilities]
    target = [state((.9, .1), rows) for rows in utilities]
    first_target_regrets = [item.regrets.tolist() for item in target]
    for item in target:
        item.next_strategy()
        item.observe([0., 1.])
    return dict(scope="aggregated minimizer alone; not an impossibility proof for offline replay",
        old_weights=[.5, .5], target_weights=[.9, .1], histories=utilities,
        old_regrets=[item.regrets.tolist() for item in old],
        old_predictors=[item.previous_utility.tolist() for item in old],
        target_regrets=first_target_regrets,
        next_policies_after_shared_feedback=[item.next_strategy().tolist() for item in target])


def run(starts=None, seeds=(17, 29)):
    from pairb.material import MaterialEvaluator
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3,
        rounds=6, final_rounds=1, max_nodes=10000, max_evaluator_calls=512, stop_on_time=False)
    if starts is None:
        starts = (("kings", "7k/8/8/8/8/8/8/K7 w - - 0 1", 4),
                  ("pawns", "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1", 4),
                  ("rook_pawn", "7k/6p1/8/8/8/8/1P6/KR6 w - - 0 1", 4))
    games = []
    for name, fen, cap in starts:
        for seed in seeds:
            agents = {p: AuditedAgent(MaterialEvaluator(), config, fen) for p in ("white", "black")}
            trackers = {p: BeliefTracker(fen, sample_size=3, max_candidates=2000) for p in agents}
            error, result = None, None
            try:
                result = play_game(RulesReferee(fen), agents, trackers,
                    MatchConfig(10000, cap, seed, "paper_fow_v1_proposed", "material", 0))
            except BeliefCapacityError as exc:
                error = dict(type=type(exc).__name__, message=str(exc))
            actions = sorted([row for agent in agents.values() for row in agent.trace], key=lambda row: row["ply"])
            games.append(dict(id=name, public_initial_fen=fen, seed=seed, max_plies=cap,
                status="tracker_capacity" if error else "capped" if result.stopped_at_ply_limit else "terminal",
                outcome=None if result is None or result.stopped_at_ply_limit else result.winner,
                error=error, actions=actions))
    actions = [row for game in games for row in game["actions"]]
    audits = [row["transition"] for row in actions if row["transition"] is not None]
    return dict(scope="short private-turn transition diagnostics, not strength or timing evidence",
        python=platform.python_version(), base_commit_at_execution=git_revision(),
        source_hash_convention=NORMALIZATION, source_sha256=source_manifest(),
        rules_id="paper_fow_v1_proposed", evaluator="material", config=asdict(config),
        tracker=dict(sample_size=3, max_candidates=2000, semantics="exact_history_fail_fast"),
        games=games, aggregate_counterexample=aggregate_state_counterexample(),
        summary=dict(games=len(games), actions=len(actions), transitions=len(audits),
            capped=sum(game["status"] == "capped" for game in games),
            terminal=sum(game["status"] == "terminal" for game in games),
            tracker_capacity=sum(game["status"] == "tracker_capacity" for game in games),
            fallbacks=sum(row["status"] == "fallback" for row in actions),
            full_game_affine=sum(audit["full_game_affine"]["verified"] for audit in audits),
            own_cf_nonuniform=sum(audit["cf_scales"][0]["positive_rows"] > 1 and
                not audit["cf_scales"][0]["uniform_positive_ratios"] for audit in audits),
            own_no_positive_scale_rows=sum(audit["cf_scales"][0]["positive_rows"] == 0 for audit in audits),
            transitions_with_new_own_support=sum(audit["cf_scales"][0]["new_positive_from_zero_source"] > 0 for audit in audits),
            own_new_support=sum(audit["cf_scales"][0]["new_positive_from_zero_source"] for audit in audits),
            fresh_roots=sum(audit["fresh_roots"] for audit in audits),
            local_affine_roots=sum(audit["local_affine_roots"] for audit in audits)),
        agent_solver_configuration_changed=False, cumulative_state_transfer_enabled=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), **report["summary"])))


if __name__ == "__main__":
    main()
