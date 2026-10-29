"""Warm/cold initialization bundles on identical frozen private-projection trees."""

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import platform

import chess
import numpy

from fow_shared.evaluation import MatchConfig, play_game
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker
from .chess_projection import project_chess
from .chess_search import SearchBudgetError, TreeCapacityError
from .chess_subgame_agent import ChessSubgameAgent
from .frozen_search import compare_frozen
from .provenance import source_manifest, NORMALIZATION, git_revision
from .rules_adapter import RulesReferee


class PreparationLeaf:
    """Apply the source agent's evaluator-call cap during offline preparation."""
    def __init__(self, evaluator, limit):
        self.evaluator, self.limit, self.calls = evaluator, limit, 0
        self.name = evaluator.name

    def evaluate_children(self, fen):
        if self.calls >= self.limit:
            raise SearchBudgetError("frozen target preparation evaluator limit")
        self.calls += 1
        return self.evaluator.evaluate_children(fen)


class SnapshotAgent(ChessSubgameAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshots = []

    def act(self, turn):
        previous = deepcopy(self.saved)
        decision = super().act(turn)
        if previous is not None:
            self.snapshots.append((previous, turn, decision.move, decision.diagnostics["fallback"]))
        return decision


def run(starts=None, seeds=(17, 29), checkpoints=(0, 1, 4, 8)):
    from pairb.material import MaterialEvaluator
    if starts is None:
        starts = (("kings", "7k/8/8/8/8/8/8/K7 w - - 0 1", 4),
                  ("pawns", "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1", 4),
                  ("rook_pawn", "7k/6p1/8/8/8/8/1P6/KR6 w - - 0 1", 4))
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3,
        rounds=6, final_rounds=1, max_nodes=10000, max_evaluator_calls=512, stop_on_time=False)
    games, comparisons, failures = [], [], []
    for name, fen, cap in starts:
        for seed in seeds:
            agents = {p: SnapshotAgent(MaterialEvaluator(), config, fen) for p in ("white", "black")}
            trackers = {p: BeliefTracker(fen, sample_size=3, max_candidates=2000) for p in agents}
            game = play_game(RulesReferee(fen), agents, trackers,
                MatchConfig(10000, cap, seed, "paper_fow_v1_proposed", "material", 0))
            games.append(dict(id=name, seed=seed, public_initial_fen=fen,
                capped=game.stopped_at_ply_limit, outcome=None if game.stopped_at_ply_limit else game.winner,
                moves=[row.move for row in game.plies]))
            snapshots = sorted([entry for agent in agents.values() for entry in agent.snapshots],
                               key=lambda entry: entry[1].observation.ply)
            for previous, turn, actual_move, fallback in snapshots:
                identity = dict(game=name, seed=seed, ply=turn.observation.ply,
                                player=turn.observation.player, actual_source_move=actual_move,
                                actual_source_fallback=bool(fallback))
                preparation_leaf = PreparationLeaf(MaterialEvaluator(), config.max_evaluator_calls)
                try:
                    projection = project_chess(turn, preparation_leaf, initial_fen=fen,
                        depth=config.initial_depth, max_nodes=config.max_nodes, saved=previous)
                except (SearchBudgetError, TreeCapacityError) as error:
                    failures.append(dict(**identity, error=type(error).__name__, message=str(error)))
                    continue
                for mode in ("resolve", "maxmargin"):
                    comparison = compare_frozen(previous, projection, mode=mode,
                        checkpoints=checkpoints, evaluator_name="material")
                    comparisons.append(dict(**identity, comparison=comparison,
                        preparation_evaluator_calls=preparation_leaf.calls,
                        input_hypotheses=[dict(fen=h.fen, candidate_moves=h.candidate_moves, weight=h.weight)
                                          for h in turn.belief.hypotheses]))
    summary = {}
    for mode in ("resolve", "maxmargin"):
        deltas, aligned_deltas = [], []
        for entry in comparisons:
            comparison = entry["comparison"]
            if comparison["mode"] != mode:
                continue
            gaps = {row["method"]: row["checkpoints"][-1]["profiles"]["last"]["security"]["finite_gap"]
                    for row in comparison["methods"]}
            deltas.append(gaps["heuristic_warm"]-gaps["seeded_cold"])
            aligned_deltas.append(gaps["heuristic_warm"]-gaps["round_aligned_seeded_cold"])
        def counts(values):
            return dict(warm_lower_gap=sum(x < -1e-10 for x in values),
                warm_higher_gap=sum(x > 1e-10 for x in values), tied=sum(abs(x) <= 1e-10 for x in values))
        summary[mode] = dict(comparisons=len(deltas),
            versus_seeded_cold=counts(deltas), versus_round_aligned_seeded_cold=counts(aligned_deltas))
    return dict(scope="fixed sampled gadget diagnostics, not playing strength or a causal regret-only ablation",
        python=platform.python_version(), chess=chess.__version__, numpy=numpy.__version__,
        base_commit_at_execution=git_revision(),
        source_hash_convention=NORMALIZATION, source_sha256=source_manifest(),
        rules_id="paper_fow_v1_proposed", source_config=asdict(config),
        tracker=dict(sample_size=3, max_candidates=2000), checkpoints=checkpoints,
        target_stage="projection preparation before any new CFR, growth or mode switching",
        round_control="equal added rounds, not equal total training, arithmetic or time",
        selection_scope="targets from the existing heuristic-warm self-play trajectory",
        games=games, comparisons=comparisons, preparation_failures=failures, summary=summary,
        live_agent_defaults_changed=False, projected_training_labels_enabled=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), games=len(report["games"]),
        preparation_failures=len(report["preparation_failures"]), summary=report["summary"])))


if __name__ == "__main__":
    main()
