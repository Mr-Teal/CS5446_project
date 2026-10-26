"""Small fixed-work budget probes and capped short games, not strength tests."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter

from fow_shared.contracts import AgentInput, HistoryEvent
from fow_shared.evaluation import MatchConfig, play_game
from .anytime_agent import AnytimeConfig, AnytimePCFRAgent
from .belief_tracker import BeliefTracker
from .chess_search import SearchBudgetError, TreeCapacityError
from .label_pilot import KINGS, git_metadata
from .rules_adapter import RulesAdapter, RulesReferee
from .search_agent import FixedDepthPCFRAgent, SearchConfig


class MeteredLeaf:
    def __init__(self, base, cap):
        self.base, self.cap, self.calls = base, cap, 0
        self.name = base.name

    def evaluate_children(self, fen):
        if self.calls >= self.cap:
            raise SearchBudgetError("experiment evaluator cap")
        self.calls += 1
        return self.base.evaluate_children(fen)


def fixture_turn(fen, moves=(), player="white"):
    rules, tracker = RulesAdapter(), BeliefTracker(fen, sample_size=4, max_candidates=2000)
    tracker.reset(player, 17)
    state, history = rules.initial_state(fen), []
    view = rules.observe(state, player)
    belief = tracker.update(view)
    for move in moves:
        own_move = move if rules.current_player(state) == player else None
        history.append(HistoryEvent(view, own_move))
        state = rules.apply_move(state, move)
        view = rules.observe(state, player)
        belief = tracker.update(view, own_move)
    return AgentInput(view, belief, 1000, tuple(history))


def run_probe(turn, fen, method, nodes, calls, seed):
    from pairb.material import MaterialEvaluator
    leaf = MeteredLeaf(MaterialEvaluator(), calls)
    if method == "growth":
        agent = AnytimePCFRAgent(leaf, AnytimeConfig(
            rounds=12, rounds_per_stage=3, final_rounds=3, max_depth=3,
            max_nodes=nodes, max_evaluator_calls=calls, stop_on_time=False), fen)
    else:
        agent = FixedDepthPCFRAgent(leaf, SearchConfig(
            depth=int(method[-1]), rounds=12, max_nodes=nodes, stop_on_time=False), fen)
    agent.reset(turn.observation.player, seed)
    started = perf_counter()
    try:
        record = agent.label(turn, "budget-probe")
    except (SearchBudgetError, TreeCapacityError) as exc:
        return dict(status=type(exc).__name__, evaluator_calls=leaf.calls,
                    elapsed_ms=(perf_counter() - started) * 1000)
    d = record.decision.diagnostics
    return dict(status="ok", evaluator_calls=leaf.calls,
                elapsed_ms=(perf_counter() - started) * 1000,
                nodes=d["search_nodes"], rounds=d["solver_rounds"],
                depth=d.get("search_depth", int(method[-1]) if method != "growth" else 1),
                expansions=d.get("expansions", 0), move=record.decision.move,
                policy=dict(record.decision.root_policy), root_value=record.root_value,
                hypothesis_values=list(record.hypothesis_values),
                stop=[key for key in d if key.startswith(("stop:", "growth_stop:"))],
                config_id=record.config_id)


def short_game(growth_colour, seed):
    from pairb.material import MaterialEvaluator
    players = {}
    for colour in ("white", "black"):
        if colour == growth_colour:
            players[colour] = AnytimePCFRAgent(MaterialEvaluator(), AnytimeConfig(
                rounds=8, rounds_per_stage=2, final_rounds=2, max_nodes=512,
                max_evaluator_calls=16, stop_on_time=False), KINGS)
        else:
            players[colour] = FixedDepthPCFRAgent(MaterialEvaluator(), SearchConfig(
                depth=1, rounds=8, max_nodes=512, stop_on_time=False), KINGS)
    trackers = {p: BeliefTracker(KINGS, sample_size=4, max_candidates=2000) for p in players}
    started = perf_counter()
    result = play_game(RulesReferee(KINGS), players, trackers,
                       MatchConfig(1000, 6, seed, "paper_fow_v1_proposed", "material-1-3-3-5-9", 0))
    return dict(growth_colour=growth_colour, seed=seed, plies=len(result.plies),
                outcome=None if result.stopped_at_ply_limit else result.winner,
                stopped_at_ply_limit=result.stopped_at_ply_limit,
                elapsed_ms=(perf_counter() - started) * 1000,
                moves=[p.move for p in result.plies],
                budget_overruns=sum(p.over_budget for p in result.plies))


def timed_probe(milliseconds):
    from pairb.material import MaterialEvaluator
    turn = replace(fixture_turn(KINGS), time_budget_ms=milliseconds)
    player = AnytimePCFRAgent(MaterialEvaluator(), AnytimeConfig(), KINGS)
    player.reset("white", 17)
    decision = player.act(turn)
    return dict(time_budget_ms=milliseconds, move=decision.move,
                diagnostics=dict(decision.diagnostics))


def collect():
    fixtures = [
        ("kings-white", KINGS, (), "white"),
        ("hidden-black", KINGS, ("a1b1",), "black"),
        ("king-capture", "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", (), "white"),
    ]
    rows = []
    for name, fen, moves, player in fixtures:
        turn = fixture_turn(fen, moves, player)
        for nodes, calls in ((128, 4), (512, 16)):
            for method in ("fixed1", "fixed2", "growth"):
                runs = [run_probe(turn, fen, method, nodes, calls, 17) for _ in range(2)]
                semantic = [{k: v for k, v in run.items() if k != "elapsed_ms"} for run in runs]
                rows.append(dict(fixture=name, hypotheses=len(turn.belief.hypotheses),
                                 method=method, max_nodes=nodes, max_evaluator_calls=calls,
                                 repeat_matches=semantic[0] == semantic[1], runs=runs))
    root = Path(__file__).resolve().parents[1]
    sources = [root / "fow_shared" / (name + ".py") for name in ("values", "contracts", "evaluation")]
    sources += [root / "pair_b" / "src" / "pairb" / (name + ".py") for name in ("material", "values")]
    sources += [Path(__file__).with_name(name + ".py") for name in (
        "budget_experiments", "anytime_agent", "chess_search", "pcfr", "rules_adapter",
        "belief_tracker", "search_agent", "toy_games")]
    return dict(scope="fixed-work diagnostic probes, not win-rate or full Obscuro validation",
                evaluator="material", seed=17, rules="paper_fow_v1_proposed; no-move terminal_draw_v1",
                timing="clock disabled; 1000ms is diagnostic only; measured times are machine-dependent",
                limits="same caps, not equal actual work; failed expansion work counts in evaluator calls",
                environment=dict(python=sys.version, platform=platform.platform()),
                tracker=dict(sample_size=4, max_candidates=2000, implementation="exact-history"),
                source=git_metadata(root),
                hashes={str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in sources},
                probes=rows, short_games=[short_game("white", 17), short_game("black", 17)],
                timed_probes=[timed_probe(ms) for ms in (1, 10, 50)])


def summarize(report):
    result = {k: v for k, v in report.items() if k != "probes"}
    result["probes"] = []
    for row in report["probes"]:
        entry = {k: v for k, v in row.items() if k != "runs"}
        entry.update({k: v for k, v in row["runs"][0].items()
                      if k not in ("policy", "hypothesis_values", "elapsed_ms")})
        entry["median_elapsed_ms"] = median(r["elapsed_ms"] for r in row["runs"])
        result["probes"].append(entry)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if args.out.exists() or (args.summary is not None and args.summary.exists()):
        parser.error("an output already exists; choose new paths")
    if args.summary is not None and args.out.resolve() == args.summary.resolve():
        parser.error("raw and summary paths must differ")
    report = collect()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        with args.summary.open("x", encoding="utf-8") as stream:
            json.dump(summarize(report), stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(dict(probes=len(report["probes"]),
                          all_repeats_match=all(r["repeat_matches"] for r in report["probes"]),
                          short_games=report["short_games"])))


if __name__ == "__main__":
    main()
