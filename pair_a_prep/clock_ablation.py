"""Clock-enabled and fixed-work purification ablations, without strength claims."""

import argparse
from dataclasses import asdict, replace
from .provenance import source_manifest, NORMALIZATION, git_revision
import json
from pathlib import Path
import platform
from statistics import median
from time import perf_counter

import chess
import numpy

from fow_shared.evaluation import MatchConfig, play_game
from pairb.material import MaterialEvaluator
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker, BeliefCapacityError
from .chess_subgame_agent import ChessSubgameAgent
from .rules_adapter import RulesAdapter, RulesReferee
from .subgame_validation import fixture_turn


ROOT = Path(__file__).parent
KINGS = "7k/8/8/8/8/8/8/K7 w - - 0 1"


def summarize(rows):
    groups = {}
    for row in rows:
        key = (row["case"], row["budget_ms"], row["purify"])
        groups.setdefault(key, []).append(row)
    return [dict(case=key[0], budget_ms=key[1], purify=key[2], samples=len(values),
        median_ms=median(r["caller_elapsed_ms"] for r in values),
        max_ms=max(r["caller_elapsed_ms"] for r in values),
        overruns=sum(r["caller_over_budget"] for r in values),
        median_overrun_ms=median(max(0., r["caller_elapsed_ms"]-key[1]) for r in values),
        fallbacks=sum(r["diagnostics"]["fallback"] for r in values),
        median_rounds=median(r["diagnostics"].get("solver_rounds_this_turn", 0.) for r in values),
        median_calls=median(r["diagnostics"].get("evaluator_calls", 0.) for r in values),
        median_policy_l1=median(r["raw_played_l1"] for r in values))
        for key, values in groups.items()]


def measure(agent, turn, case, budget, seed, repeat):
    turn = replace(turn, time_budget_ms=budget)
    started = perf_counter()
    decision = agent.act(turn)
    elapsed = (perf_counter()-started)*1000
    decision.validate_for(turn.observation)
    raw = decision.root_policy
    played = {a: decision.diagnostics["played_policy:"+a] for a in raw}
    return dict(case=case, budget_ms=budget, seed=seed, repeat=repeat,
        purify=agent.purify, config_id=agent.config_id, move=decision.move,
        caller_elapsed_ms=elapsed, caller_over_budget=elapsed > budget,
        raw_policy=raw, played_policy=played,
        raw_played_l1=sum(abs(raw[a]-played[a]) for a in raw), diagnostics=decision.diagnostics,
        stop_reason=agent.last_stop_reason,
        label_available=agent.last_result is not None and not decision.diagnostics.get("label_root_contract_pending", 0))


def prepare(seed):
    cold, _ = fixture_turn(dict(fen=chess.STARTING_FEN))
    warm_config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3,
        rounds=8, final_rounds=2, max_nodes=2000, max_evaluator_calls=256, stop_on_time=False)
    warmer = ChessSubgameAgent(MaterialEvaluator(), warm_config, KINGS)
    warmer.reset("white", seed)
    initial, _ = fixture_turn(dict(fen=KINGS))
    own_move = warmer.act(initial).move
    rules = RulesAdapter()
    after = rules.apply_move(rules.initial_state(KINGS), own_move)
    opponent_move = rules.legal_moves(after)[0]
    warm, _ = fixture_turn(dict(fen=KINGS, candidate_moves=(own_move, opponent_move)))
    return (("cold_standard", chess.STARTING_FEN, cold, None),
            ("warm_sampled_kings", KINGS, warm, warmer.saved))


class Recorded(ChessSubgameAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def act(self, turn):
        started = perf_counter()
        decision = super().act(turn)
        elapsed = (perf_counter()-started)*1000
        self.rows.append(dict(ply=turn.observation.ply, player=turn.observation.player,
            move=decision.move, caller_elapsed_ms=elapsed,
            caller_over_budget=elapsed > turn.time_budget_ms,
            diagnostics=decision.diagnostics, raw_policy=decision.root_policy))
        self.rows[-1]["stop_reason"] = self.last_stop_reason
        return decision


def run(budgets=(20, 100, 500), seeds=(17, 29), repeats=2, reserve=.1):
    config = AnytimeConfig(growth="one_sided", initial_depth=1, max_depth=3,
        rounds=64, rounds_per_stage=4, final_rounds=4, max_nodes=512,
        max_evaluator_calls=32, expansion_fraction=.6, stop_on_time=True)
    rows, fixed_pairs, games = [], [], []
    for seed in seeds:
        cases = prepare(seed)
        for name, fen, turn, snapshot in cases:
            controls = []
            for purify in (False, True):
                agent = ChessSubgameAgent(MaterialEvaluator(), replace(config, rounds=12,
                    final_rounds=2, stop_on_time=False), fen, purify=purify,
                    submission_reserve_fraction=reserve)
                agent.reset("white", seed)
                agent.saved = snapshot
                controls.append(measure(agent, turn, name, 10000, seed, 0))
            assert controls[0]["raw_policy"] == controls[1]["raw_policy"]
            fixed_pairs.append(dict(case=name, seed=seed, same_raw_policy=True, runs=controls))
        for budget in budgets:
            for repeat in range(repeats):
                # Alternate condition order to reduce a fixed first-run bias.
                order = (False, True) if (repeat+seed) % 2 else (True, False)
                for purify in order:
                    for name, fen, turn, snapshot in cases:
                        agent = ChessSubgameAgent(MaterialEvaluator(), config, fen, purify=purify,
                                                 submission_reserve_fraction=reserve)
                        agent.reset("white", seed)
                        agent.saved = snapshot
                        rows.append(measure(agent, turn, name, budget, seed, repeat))
            fen = "7k/6p1/8/8/8/8/1P6/K7 w - - 0 1"
            for purify in (False, True):
                agents = {p: Recorded(MaterialEvaluator(), config, fen, purify=purify,
                                     submission_reserve_fraction=reserve) for p in ("white", "black")}
                trackers = {p: BeliefTracker(fen, sample_size=3, max_candidates=2000) for p in agents}
                error = None
                try:
                    result = play_game(RulesReferee(fen), agents, trackers,
                        MatchConfig(budget, 4, seed, "paper_fow_v1_proposed", "material", 0))
                except BeliefCapacityError as exc:
                    result, error = None, dict(type=type(exc).__name__, message=str(exc))
                actions = sorted([r for agent in agents.values() for r in agent.rows], key=lambda r: r["ply"])
                games.append(dict(seed=seed, budget_ms=budget, purify=purify, initial_fen=fen,
                    status="tracker_capacity" if error else "capped" if result.stopped_at_ply_limit else "terminal",
                    outcome=None if result is None or result.stopped_at_ply_limit else result.winner,
                    error=error, actions=actions,
                    final_populations={p: tracker.population_size for p, tracker in trackers.items()}))
    sources = source_manifest(("pair_a_prep/data/subgame_positions.json",))
    actions = [r for game in games for r in game["actions"]]
    return dict(scope="clock-enabled engineering ablation; no hard real-time guarantee or strength claim",
        python=platform.python_version(), numpy=numpy.__version__, chess=chess.__version__,
        source_sha256=sources, source_hash_convention=NORMALIZATION,
        base_commit_at_execution=git_revision(), evaluator="material", leaf_depth=0,
        rules_id="paper_fow_v1_proposed", pending_rule_difference="PR37 effective EP repetition",
        config=asdict(config), budgets_ms=budgets, seeds=seeds, repeats=repeats,
        submission_reserve_fraction=reserve,
        warm_preparation="outside measured call; shared readonly saved blueprint, no hidden referee input",
        clock_measurement="caller surrounds act including output/snapshot finalization; tracker excluded",
        tracker=dict(sample_size=3, max_candidates=2000),
        fixed_work_pairs=fixed_pairs, turn_runs=rows, summary=summarize(rows), games=games,
        live_summary=dict(games=len(games), actions=len(actions),
            overruns=sum(r["caller_over_budget"] for r in actions),
            fallbacks=sum(r["diagnostics"]["fallback"] for r in actions),
            capped=sum(g["status"] == "capped" for g in games),
            terminal=sum(g["status"] == "terminal" for g in games),
            tracker_capacity=sum(g["status"] == "tracker_capacity" for g in games)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--submission-reserve-fraction", type=float, default=.1)
    args = parser.parse_args()
    report = run(reserve=args.submission_reserve_fraction)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), turn_runs=len(report["turn_runs"]),
        turn_overruns=sum(r["caller_over_budget"] for r in report["turn_runs"]),
        turn_fallbacks=sum(r["diagnostics"]["fallback"] for r in report["turn_runs"]),
        live=report["live_summary"])))


if __name__ == "__main__":
    main()
