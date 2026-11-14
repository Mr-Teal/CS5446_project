"""Replay one failed or successful private tracker stream without an engine."""
import argparse
import configparser
import json
from pathlib import Path
from dataclasses import asdict
from pair_a_prep.rules_adapter import RulesAdapter

from fow_shared.contracts import Observation
from pair_a_prep.evaluation_factories import HistoryTrackerFactory
from pair_c.tracking import RecordingTracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--game", type=int, required=True)
    parser.add_argument("--player", choices=["white", "black"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read(args.directory / "evaluate_config.ini")
    games = [json.loads(x) for x in (args.directory / "games.jsonl").read_text().splitlines() if x.strip()]
    game = next(g for g in games if g["game"] == args.game)
    section = "player_" + game["player_by_color"][args.player]
    initial = config.get("match", "initial_fen", fallback="").strip() or None
    rules = type("Rules", (), {"name": "teal-rules-adapter"})()
    tracker = HistoryTrackerFactory(dict(config[section])).create_tracker(rules, initial)
    rows = [json.loads(x) for x in (args.directory / "tracker_updates.jsonl").read_text().splitlines() if x.strip()]
    rows = [r for r in rows if r["game"] == args.game and r["player"] == args.player]
    if not rows or any(not r.get("observation") for r in rows):
        raise ValueError("trace lacks complete private observations; cannot replay old aggregate-only records")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        def save(row):
            output.write(json.dumps(row) + "\n")
            output.flush()
        recorded = RecordingTracker(tracker, args.player, save)
        recorded.reset(args.player, game["seed"] + (args.player == "black"))
        history = []
        adapter = RulesAdapter()
        for row in rows:
            belief = recorded.update(Observation(**row["observation"]), row.get("own_move"))
            history.append(row)
            # Audit every returned path against ALL this player's private views.
            for hypothesis in belief.hypotheses:
                state = adapter.initial_state(initial)
                assert len(hypothesis.candidate_moves) == row["ply"]
                for index, past in enumerate(history):
                    if index:
                        move = hypothesis.candidate_moves[index - 1]
                        assert past.get("own_move") in (None, move)
                        state = adapter.apply_move(state, move)
                    actual = json.loads(json.dumps(asdict(adapter.observe(state, args.player))))
                    assert actual == past["observation"], "candidate violates private observation history"
                assert state.fen == hypothesis.fen
    print(f"Replayed {len(rows)} private updates; output: {args.output}")


if __name__ == "__main__":
    main()
