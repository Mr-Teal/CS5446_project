"""Bounded richer-position checks with complete run metadata and capped outcomes."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess

import chess
import numpy

from fow_shared.contracts import AgentInput, Belief, Hypothesis, HistoryEvent
from fow_shared.evaluation import MatchConfig, play_game
from pairb.material import MaterialEvaluator
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker, BeliefCapacityError
from .chess_subgame_agent import ChessSubgameAgent
from .rules_adapter import RulesAdapter, RulesReferee


ROOT = Path(__file__).parent
CASES = ROOT / "data/subgame_positions.json"


def fixture_turn(case):
    """Use a declared consistent hypothetical path, never an inferred posterior."""
    rules = RulesAdapter()
    state = rules.initial_state(case["fen"])
    for move in case.get("candidate_moves", []):
        state = rules.apply_move(state, move)
    player = rules.current_player(state)
    state = rules.initial_state(case["fen"])
    history = []
    moves = tuple(case.get("candidate_moves", ()))
    for move in moves:
        history.append(HistoryEvent(rules.observe(state, player),
                                    move if rules.current_player(state) == player else None))
        state = rules.apply_move(state, move)
    observation = rules.observe(state, player)
    belief = Belief(player, len(moves), (Hypothesis(state.fen, 1., "declared-fixture", moves),),
                    weighting="selected_consistent_fixture_not_full_posterior")
    return AgentInput(observation, belief, 10000, tuple(history)), state


class RecordedAgent(ChessSubgameAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.actions = []

    def act(self, turn):
        decision = super().act(turn)
        self.actions.append(dict(ply=turn.observation.ply, player=turn.observation.player,
            belief_sample=len(turn.belief.hypotheses), population=turn.belief.population_size,
            move=decision.move, raw_policy=decision.root_policy, diagnostics=decision.diagnostics,
            config_id=self.config_id))
        return decision


def run():
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    config = AnytimeConfig(growth="one_sided", initial_depth=1, max_depth=2,
        rounds=8, rounds_per_stage=2, final_rounds=2, max_nodes=1024,
        max_evaluator_calls=48, stop_on_time=False)
    roots = []
    rules = RulesAdapter()
    for case in cases:
        turn, state = fixture_turn(case)
        assert set(case["required_moves"]) <= set(turn.observation.legal_moves)
        terminal_checks = {}
        for move, reason in case.get("terminal_after", {}).items():
            outcome = rules.terminal(rules.apply_move(state, move))
            assert outcome is not None and outcome.reason == reason
            terminal_checks[move] = dict(winner=outcome.winner, reason=outcome.reason)
        agent = ChessSubgameAgent(MaterialEvaluator(), config, case["fen"])
        agent.reset(turn.observation.player, 17)
        record = agent.label(turn, "position-"+case["id"])
        roots.append(dict(id=case["id"], category=case["category"],
            player=turn.observation.player, move=record.decision.move,
            raw_policy=record.decision.root_policy, hypothesis_values=record.hypothesis_values,
            root_value=record.root_value, diagnostics=record.decision.diagnostics,
            config_id=agent.config_id, terminal_checks=terminal_checks))
    games = []
    starts = (("standard", chess.STARTING_FEN, 4),
              ("pawn_endgame", "7k/6p1/8/8/8/8/1P6/K7 w - - 0 1", 6),
              ("rook_endgame", "7k/6p1/8/8/8/8/1P6/KR6 w - - 0 1", 6))
    for name, fen, plies in starts:
        for seed in (17, 29):
            agents = {p: RecordedAgent(MaterialEvaluator(), config, fen) for p in ("white", "black")}
            trackers = {p: BeliefTracker(fen, sample_size=3, max_candidates=2000) for p in agents}
            error = None
            try:
                result = play_game(RulesReferee(fen), agents, trackers,
                    MatchConfig(10000, plies, seed, "paper2021_fow_no_moves_draw_v1", "material", 0))
            except BeliefCapacityError as exc:
                result = None
                error = dict(type=type(exc).__name__, message=str(exc))
            actions = sorted([row for agent in agents.values() for row in agent.actions], key=lambda row: row["ply"])
            games.append(dict(id=name, initial_fen=fen, seed=seed, max_plies=plies,
                status="tracker_capacity" if error else "capped" if result.stopped_at_ply_limit else "terminal",
                outcome=None if result is None or result.stopped_at_ply_limit else result.winner,
                error=error, plies=[] if result is None else [asdict(p) for p in result.plies],
                actions=actions, final_populations={p: tracker.population_size for p, tracker in trackers.items()}))
    sources = {name: sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        "chess_subgame_agent.py", "chess_projection.py", "search_policies.py", "subgame_validation.py",
        "pcfr.py", "subgame_boundaries.py", "warm_start.py", "chess_gadgets.py", "chess_search.py",
        "rules_adapter.py", "belief_tracker.py", "data/subgame_positions.json")}
    engine_source = Path(__import__("inspect").getfile(MaterialEvaluator))
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], check=True, text=True,
                                  capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    actions = [row for game in games for row in game["actions"]]
    return dict(scope="engineering validation, not strength, timing benchmark or full Obscuro",
        python=platform.python_version(), chess=chess.__version__, numpy=numpy.__version__,
        base_commit_at_execution=revision, source_sha256=sources,
        evaluator=dict(name="material", leaf_depth=0, source_sha256=sha256(engine_source.read_bytes()).hexdigest()),
        rules_id="paper2021_fow_no_moves_draw_v1", pending_rule_difference="PR37 effective EP repetition",
        config=asdict(config), tracker=dict(sample_size=3, max_candidates=2000, semantics="exact_history_fail_fast"),
        seed_roots=17, root_checks=roots, games=games,
        summary=dict(root_checks=len(roots), games=len(games),
            capped=sum(g["status"] == "capped" for g in games),
            terminal=sum(g["status"] == "terminal" for g in games),
            tracker_capacity=sum(g["status"] == "tracker_capacity" for g in games),
            actions=len(actions), fallbacks=sum(a["diagnostics"]["fallback"] for a in actions),
            over_budget=sum(a["diagnostics"]["over_budget"] for a in actions)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/subgame_positions_reference.json")
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), **report["summary"])))


if __name__ == "__main__":
    main()
