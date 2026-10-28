"""Review issue 1: factories reset before each of two real short games."""

import configparser
from pathlib import Path

from pair_c import run_evaluation
from fow_shared.contracts import Decision


class LegalMoveAgent:
    def __init__(self, name):
        self.name = name

    def reset(self, player, seed):
        pass

    def act(self, turn):
        moves = turn.observation.legal_moves
        move = moves[0]
        return Decision(move, {candidate: float(candidate == move) for candidate in moves})


class RecordingFactory:
    events = []

    def __init__(self, settings):
        self.name = settings["name"]

    def load_model(self):
        return LegalMoveAgent(self.name)

    def reset_game(self):
        self.events.append(("reset_game", self.name))


def test_reset_game_before_each_game(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(RecordingFactory, "events", events)

    parser = configparser.ConfigParser()
    parser.read(Path(run_evaluation.__file__).with_name("evaluate_config.ini"), encoding="utf-8")
    for side in ("a", "b"):
        parser.set(f"player_{side}", "factory", f"{__name__}:RecordingFactory")
        parser.set(f"player_{side}", "name", side.upper())
    parser.set("match", "games", "2")
    parser.set("match", "max_plies", "2")
    parser.set("match", "rules", "standin")
    parser.set("match", "initial_fen", "")
    parser.set("output", "directory", str(tmp_path / "results"))
    source = tmp_path / "evaluate_config.ini"
    with source.open("w", encoding="utf-8") as stream:
        parser.write(stream)

    real_play_game = run_evaluation.play_game
    games_started = 0

    def record_game_boundary(*args, **kwargs):
        nonlocal games_started
        games_started += 1
        events.append(("game_start", games_started))
        result = real_play_game(*args, **kwargs)
        events.append(("game_end", games_started))
        return result

    monkeypatch.setattr(run_evaluation, "play_game", record_game_boundary)
    summary = run_evaluation.run(run_evaluation.load_config(source), source)

    assert summary["games_completed"] == 2, summary["failed_games"]
    assert events == [
        ("reset_game", "A"), ("reset_game", "B"),
        ("game_start", 1), ("game_end", 1),
        ("reset_game", "A"), ("reset_game", "B"),
        ("game_start", 2), ("game_end", 2),
    ]