"""Review issue 2: the real CLI reports game failures after saving all results."""

import configparser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pair_c import run_evaluation
from fow_shared.contracts import Decision


class ConfigurableAgent:
    def __init__(self, name, fail_first_game):
        self.name = name
        self.fail_first_game = fail_first_game
        self.game = 0

    def reset(self, player, seed):
        self.game += 1

    def act(self, turn):
        if self.fail_first_game and self.game == 1:
            raise RuntimeError("intentional agent failure")
        moves = turn.observation.legal_moves
        move = moves[0]
        return Decision(move, {candidate: float(candidate == move) for candidate in moves})


class Factory:
    def __init__(self, settings):
        self.settings = settings

    def load_model(self):
        return ConfigurableAgent(self.settings["name"], self.settings["fail_first_game"] == "true")

    def reset_game(self):
        pass


@pytest.mark.parametrize(
    "fail_first_game, expected_exit_code",
    [(False, 0), (True, 1)],
    ids=["all-successful", "one-failure"],
)
def test_cli_exit_status_preserves_results(tmp_path, fail_first_game, expected_exit_code):
    parser = configparser.ConfigParser()
    parser.read(Path(run_evaluation.__file__).with_name("evaluate_config.ini"), encoding="utf-8")
    for side in ("a", "b"):
        parser.set(f"player_{side}", "factory",
                   "pair_c.regression_tests.test_failure_exit_status:Factory")
        parser.set(f"player_{side}", "name", side.upper())
        parser.set(f"player_{side}", "fail_first_game",
                   "true" if side == "a" and fail_first_game else "false")
    parser.set("match", "games", "2")
    parser.set("match", "max_plies", "2")
    parser.set("match", "rules", "standin")
    parser.set("match", "alternating_colors", "true")
    parser.set("match", "initial_fen", "")
    output_dir = tmp_path / "results"
    parser.set("output", "directory", str(output_dir))
    source = tmp_path / "evaluate_config.ini"
    with source.open("w", encoding="utf-8") as stream:
        parser.write(stream)

    process = subprocess.run(
        [sys.executable, str(Path(run_evaluation.__file__)), str(source)],
        cwd=run_evaluation.ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == expected_exit_code, process.stdout + process.stderr

    records = [json.loads(line) for line in
               (output_dir / "games.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert [record["game"] for record in records] == [1, 2]
    assert [record["status"] for record in records] == [
        "failed" if fail_first_game else "completed", "completed",
    ]
    if fail_first_game:
        assert records[0]["error"] == "RuntimeError: intentional agent failure"
    assert summary["games_completed"] == (1 if fail_first_game else 2)
    assert summary["games_failed"] == (1 if fail_first_game else 0)
    assert "Results after" in process.stdout
    assert f"Results: {output_dir}" in process.stdout
