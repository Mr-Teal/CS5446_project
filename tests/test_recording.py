"""TrainingRecord.game_id: lets training, validation and test data be split by whole game."""
import json
from dataclasses import asdict

import chess

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, Observation, TrainingRecord
from fow_shared.recording import read_records, write_records


def record(**extra):
    obs = Observation(player="white", ply=0, visible_squares=(), visible_pieces={},
                      legal_moves=("e2e4", "d2d4"), halfmove_clock=0)
    turn = AgentInput(obs, Belief("white", 0, (Hypothesis(chess.STARTING_FEN, 1.0),)), 1000)
    decision = Decision("e2e4", {"e2e4": 0.7, "d2d4": 0.3})
    return TrainingRecord(turn, decision, 0.05, (0.05,), 42, "zs21", "depth1", **extra)


def test_game_id_survives_a_write_and_read(tmp_path):
    path = tmp_path / "labels.jsonl"
    write_records(path, [record(game_id="g-000001")])
    (back,) = read_records(path)
    assert back.game_id == "g-000001" and back == record(game_id="g-000001")


def test_records_written_before_game_id_existed_still_load(tmp_path):
    old = asdict(record())
    del old["game_id"]
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps(old) + "\n")
    (back,) = read_records(path)
    assert back.game_id == ""
