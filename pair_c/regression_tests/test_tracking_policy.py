"""Tracker telemetry survives failure and follows identity across colour swaps."""

import configparser
import json
from pathlib import Path

import pytest

from pair_c import run_evaluation


@pytest.mark.parametrize("fails", [False, True])
def test_real_runner_budget_policy_records_every_update(tmp_path, fails):
    parser = configparser.ConfigParser()
    parser.read(Path(run_evaluation.__file__).with_name("evaluate_config.ini"))
    fen = "7k/8/8/8/8/8/8/K7 w - - 0 1"
    for side in ("a", "b"):
        section = "player_" + side
        for key, value in {
            "factory": "pair_c.regression_tests.test_reset_game:RecordingFactory",
            "tracker_factory": "pair_a_prep.evaluation_factories:HistoryTrackerFactory",
            "public_initial_fen": fen, "leaf_depth": "0", "tracker_policy": "budgeted-exact",
            "tracker_slice_ms": "0" if fails else "1000", "tracker_total_ms": "2000",
            "tracker_memory_mb": "64", "tracker_max_resumes": "0",
        }.items(): parser.set(section, key, value)
    for key, value in {"games": "2", "max_plies": "2", "rules": "teal", "initial_fen": fen}.items():
        parser.set("match", key, value)
    output = tmp_path / "results"
    parser.set("output", "directory", str(output))
    source = tmp_path / "config.ini"
    with source.open("w") as stream: parser.write(stream)
    summary = run_evaluation.run(run_evaluation.load_config(source), source)
    games = [json.loads(line) for line in (output / "games.jsonl").read_text().splitlines()]
    updates = [json.loads(line) for line in (output / "tracker_updates.jsonl").read_text().splitlines()]
    assert all(row["policy"] == "budgeted-exact" for row in updates)
    assert len(updates) == sum(len(game["tracker_updates"]) for game in games)
    assert all(row["elapsed_ms"] >= 0 for row in updates)
    if fails:
        assert summary["games_failed"] == summary["tracking"]["failed_updates"] == 2
        assert summary["games_scored"] == 0 and summary["player_a_score_rate"] is None
        assert all(row["outcome"] == "failed" and row["policy_stop"] == "resume_limit" for row in updates)
        # The first colour's tracker fails: its player identity swaps each game.
        assert summary["tracking"]["player_a"]["updates"] == summary["tracking"]["player_b"]["updates"] == 1
    else:
        assert summary["games_failed"] == 0 and summary["games_capped"] == 2
        assert len(updates) == 12  # Both views at initial state and after both plies.
        assert all(row["outcome"] == "returned" and row["status"] == "complete" for row in updates)
        assert summary["tracking"]["player_a"]["updates"] == summary["tracking"]["player_b"]["updates"] == 6
    assert sum(row["elapsed_ms"] for row in updates) == pytest.approx(
        summary["tracking"]["player_a"]["total_ms"] + summary["tracking"]["player_b"]["total_ms"])


def test_atomic_tracker_failure_does_not_reuse_previous_ply_metadata():
    from types import SimpleNamespace
    from pair_c.tracking import RecordingTracker
    class Tracker:
        last_update = SimpleNamespace(status="complete", support_complete=True)
        def update(self, observation, own_move=None):
            raise ValueError("capacity exhausted")
    rows = []
    tracker = RecordingTracker(Tracker(), "white", rows.append)
    with pytest.raises(ValueError): tracker.update(SimpleNamespace(ply=8))
    assert rows[0]["ply"] == 8 and rows[0]["outcome"] == "failed"
    assert rows[0]["status"] is None and rows[0]["support_complete"] is None
