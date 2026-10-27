"""Record hand-checkable gift partitions and immutable chess lineage evidence."""

import argparse
from dataclasses import asdict
from .provenance import source_manifest, NORMALIZATION, git_revision, artifact_sha256, ARTIFACT_HASH_CONVENTION
from hashlib import sha256
import json
from pathlib import Path

from pairb.material import MaterialEvaluator
from fow_shared.evaluation import MatchConfig, play_game
from .anytime_agent import AnytimeConfig
from .belief_tracker import BeliefTracker
from .rules_adapter import RulesReferee
from .subgame_validation import RecordedAgent
from .subgame_boundaries import BoundaryRoot, derive_boundaries
from .toy_games import Node, terminal


ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clock-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    examples = []
    for keep, drop, chance in ((0., 1., .5), (1., -1., .25)):
        root = Node(player=1, infoset="J", children={
            "L": Node(player=0, infoset="I", children={"keep": terminal(keep), "drop": terminal(drop)}),
            "R": terminal(0)})
        profile = ({"I": {"keep": chance, "drop": 1-chance}}, {"J": {"L": .5, "R": .5}})
        boundary = derive_boundaries(root, profile, (BoundaryRoot("keep", ("L", "keep"), "cut-J"),))
        examples.append(dict(keep=keep, drop=drop, own_keep=chance, gifts=boundary.gifts,
                             alternates=boundary.alternate_player0, audit=boundary.audit))
    fen = "7k/8/8/8/8/8/8/K7 w - - 0 1"
    config = AnytimeConfig(growth="one_sided", initial_depth=3, max_depth=3,
        rounds=4, final_rounds=1, max_nodes=2000, max_evaluator_calls=256, stop_on_time=False)
    agents = {p: RecordedAgent(MaterialEvaluator(), config, fen) for p in ("white", "black")}
    trackers = {p: BeliefTracker(fen, sample_size=3, max_candidates=2000) for p in agents}
    result = play_game(RulesReferee(fen), agents, trackers,
        MatchConfig(10000, 6, 17, "paper_fow_v1_proposed", "material", 0))
    sources = source_manifest(("pair_a_prep/data/subgame_positions.json",))
    clock_path = args.clock_report
    clock = json.loads(clock_path.read_text(encoding="utf-8"))
    if clock.get("source_hash_convention") != NORMALIZATION:
        raise ValueError("clock report must use the current normalized source convention")
    if clock["source_sha256"] != sources:
        raise ValueError("clock source snapshot differs; rerun the clock probe on this source")
    for name, digest in sources.items():
        if name in clock["source_sha256"]:
            assert clock["source_sha256"][name] == digest, "clock snapshot differs: "+name
    report = dict(scope="local-CF partition and audit-only lineage, not exact ancestor payment lifting",
        source_sha256=sources, source_hash_convention=NORMALIZATION,
        base_commit_at_execution=git_revision(), examples=examples,
        clock_artifact=dict(path=clock_path.name, sha256=artifact_sha256(clock_path.read_bytes()),
                            hash_convention=ARTIFACT_HASH_CONVENTION,
                            live_summary=clock["live_summary"], turn_runs=len(clock["turn_runs"]),
                            turn_overruns=sum(r["caller_over_budget"] for r in clock["turn_runs"]),
                            turn_fallbacks=sum(r["diagnostics"]["fallback"] for r in clock["turn_runs"])),
        game=dict(public_initial_fen=fen, seed=17, config=asdict(config),
            capped=result.stopped_at_ply_limit, outcome=None if result.stopped_at_ply_limit else result.winner,
            actions=sorted([row for agent in agents.values() for row in agent.actions], key=lambda row: row["ply"]),
            final_ledgers={p: asdict(agent.saved.gift_ledger) for p, agent in agents.items()}))
    path = args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(path), gifts=[row["gifts"] for row in examples],
                          ledger_events={p: len(agent.saved.gift_ledger.events) for p, agent in agents.items()},
                          clock=report["clock_artifact"])))


if __name__ == "__main__":
    main()
