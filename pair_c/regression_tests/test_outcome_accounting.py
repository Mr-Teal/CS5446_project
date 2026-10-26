"""Ply limits are successful attempts, not observed terminal draws."""

import configparser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pair_c import run_evaluation


def record(winner, capped=False, status="completed"):
    return dict(game=1, status=status, winner=winner, player_a_color="white",
                stopped_at_ply_limit=capped, player_by_color={"white": "a", "black": "b"},
                plies=[dict(player="white", elapsed_ms=1.0, over_budget=False)], error="failure")


def test_mixed_results_score_only_terminal_outcomes():
    config = run_evaluation.load_config(Path(run_evaluation.__file__).with_name("evaluate_config.ini"))
    rows = [record("white"), record("black"), record("draw"), record(None, True),
            record(None, status="failed")]
    summary = run_evaluation.summarize(rows, config)
    assert (summary["games_completed"], summary["games_scored"], summary["games_capped"],
            summary["games_failed"]) == (4, 3, 1, 1)
    assert (summary["player_a_wins"], summary["draws"], summary["player_a_losses"]) == (1, 1, 1)
    assert summary["player_a_win_rate"] == pytest.approx(1 / 3)
    assert summary["player_a_score_rate"] == 0.5
    assert summary["timing"]["player_a"]["moves"] == 4


def test_cli_only_capped_games_has_no_outcome_rate(tmp_path):
    parser = configparser.ConfigParser()
    parser.read(Path(run_evaluation.__file__).with_name("evaluate_config.ini"), encoding="utf-8")
    for side in ("a", "b"):
        section = "player_" + side
        parser.set(section, "factory", "pair_c.regression_tests.test_failure_exit_status:Factory")
        parser.set(section, "fail_first_game", "false")
        parser.set(section, "tracker_particles", "8")
        parser.set(section, "tracker_hypotheses", "2")
    parser.set("match", "games", "2")
    parser.set("match", "max_plies", "1")
    parser.set("match", "initial_fen", "7k/8/8/8/8/8/8/K7 w - - 0 1")
    output = tmp_path / "results"
    parser.set("output", "directory", str(output))
    source = tmp_path / "config.ini"
    with source.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    process = subprocess.run([sys.executable, str(Path(run_evaluation.__file__)), str(source)],
                             cwd=run_evaluation.ROOT, capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stdout + process.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    records = [json.loads(row) for row in (output / "games.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["games_capped"] == 2 and summary["games_scored"] == 0
    assert summary["games_completed"] == 2 and summary["games_failed"] == 0
    assert summary["draws"] == 0 and summary["player_a_score_rate"] is None
    assert all(row["winner"] is None and row["stopped_at_ply_limit"] for row in records)
    assert "Win rate: unavailable" in process.stdout
