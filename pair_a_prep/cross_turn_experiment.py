"""Record bounded live-turn warm starts and independently specified toy boundaries."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import platform

from fow_shared.evaluation import MatchConfig, play_game
from pairb.material import MaterialEvaluator
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker
from .cross_turn import RetainedPCFRAgent
from .rules_adapter import RulesReferee
from .subgame_boundaries import BoundaryRoot, BoundarySession, derive_boundaries
from .toy_games import Node, terminal


START = "7k/8/8/8/8/8/8/K7 w - - 0 1"


def main():
    rows = []
    for growth in ("uniform", "one_sided"):
        config = AnytimeConfig(initial_depth=3, max_depth=3, rounds=4,
            final_rounds=1, max_nodes=2000, max_evaluator_calls=256,
            stop_on_time=False, growth=growth)
        agents = {side: RetainedPCFRAgent(MaterialEvaluator(), config, START)
                  for side in ("white", "black")}
        trackers = {side: BeliefTracker(START, sample_size=3, max_candidates=2000) for side in agents}
        result = play_game(RulesReferee(START), agents, trackers,
            MatchConfig(10000, 4, 17, "paper2021_fow_no_moves_draw_v1", "material", 0))
        rows.append(dict(growth=growth, config=asdict(config),
            capped=result.stopped_at_ply_limit, outcome=None if result.stopped_at_ply_limit else result.winner,
            plies=[asdict(p) for p in result.plies],
            last_turn={side: dict(config_id=agent.config_id,
                diagnostics=agent.last_result.decision.diagnostics) for side, agent in agents.items()}))
    root = Node(player=1, infoset="opponent", children={
        "mistake": Node(player=0, infoset="own-A", children={"x": terminal(1), "y": terminal(0)}),
        "safe": Node(player=0, infoset="own-B", children={"x": terminal(-1), "y": terminal(0)})})
    profile = ({"own-A": {"x": 1., "y": 0.}, "own-B": {"x": 1., "y": 0.}},
               {"opponent": {"mistake": .25, "safe": .75}})
    boundaries = derive_boundaries(root, profile, (
        BoundaryRoot("A", ("mistake",), "JA"), BoundaryRoot("B", ("safe",), "JB")))
    session = BoundarySession(boundaries)
    for _ in range(6):
        session.step()
    sources = {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("cross_turn.py", "warm_start.py", "subgame_boundaries.py",
                     "anytime_agent.py", "cross_turn_experiment.py")}
    report = dict(scope="synthetic engineering checks, not playing strength or complete Obscuro",
        python=platform.python_version(), public_initial_fen=START, seed=17,
        source_sha256=sources, games=rows,
        toy=dict(alternates=boundaries.alternate_player0, gifts=boundaries.gifts,
                 alpha=boundaries.group_prior, transitions=session.transitions,
                 final_mode=session.mode, rounds=session.solver.rounds))
    path = Path(__file__).with_name("results") / "cross_turn_reference.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(path), games=len(rows),
        last_turn_reused=[{side: data["diagnostics"]["retention:reused_roots"]
                          for side, data in row["last_turn"].items()} for row in rows],
        transitions=session.transitions)))


if __name__ == "__main__":
    main()
