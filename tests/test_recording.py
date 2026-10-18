"""TrainingRecord.game_id: lets training, validation and test data be split by whole game."""
import json
from dataclasses import asdict

import chess

from fow_shared.contracts import AgentInput, Belief, Decision, HistoryEvent, Hypothesis, Observation, TrainingRecord
from fow_shared.recording import read_records, write_records


def record(**extra):
    obs = Observation(player="white", side_to_move="white", ply=0, visible_squares=(), visible_pieces={},
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


def test_whose_turn_it_was_survives_a_write_and_read_in_the_history(tmp_path):
    # White at ply 2: its view at ply 0 (White to move, played e2e4) and at ply 1 (Black to move).
    ply0 = Observation(player="white", side_to_move="white", ply=0, visible_squares=(),
                       visible_pieces={}, legal_moves=("e2e4", "d2d4"))
    ply1 = Observation(player="white", side_to_move="black", ply=1, visible_squares=(),
                       visible_pieces={}, legal_moves=())
    now = Observation(player="white", side_to_move="white", ply=2, visible_squares=(),
                      visible_pieces={}, legal_moves=("d2d4", "g1f3"))
    after_e4_e5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
    turn = AgentInput(now, Belief("white", 2, (Hypothesis(after_e4_e5, 1.0),)), 1000,
                      (HistoryEvent(ply0, "e2e4"), HistoryEvent(ply1)))
    rec = TrainingRecord(turn, Decision("g1f3", {"d2d4": 0.5, "g1f3": 0.5}), 0.0, (0.0,),
                         42, "zs21", "depth1", game_id="g-000003")
    path = tmp_path / "history.jsonl"
    write_records(path, [rec])
    (back,) = read_records(path)
    assert [e.observation.side_to_move for e in back.agent_input.history] == ["white", "black"]
    assert back == rec


def test_an_unknown_halfmove_clock_survives_a_write_and_read(tmp_path):
    from dataclasses import replace
    rec = record(game_id="g-000002")
    turn = rec.agent_input
    hidden = replace(rec, agent_input=replace(turn, observation=replace(turn.observation, halfmove_clock=None)))
    path = tmp_path / "hidden.jsonl"
    write_records(path, [hidden])
    (back,) = read_records(path)
    assert back.agent_input.observation.halfmove_clock is None and back == hidden
