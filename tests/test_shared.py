from dataclasses import replace

import chess
import numpy as np
import pytest

from fow_shared.contracts import AgentInput, Belief, Decision, HistoryEvent, Hypothesis, Observation, TrainingRecord
from fow_shared.features import PLANE_NAMES, encode_belief
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.recording import read_records, write_records


def sample_turn():
    first = chess.Board()
    second = first.copy()
    second.remove_piece_at(chess.D8)  # Different hidden state; same selected observations.
    obs = Observation(
        player="white", ply=0, visible_squares=("e1", "a2", "b3"),
        visible_pieces={"e1": "K", "a2": "P", "b3": None},
        legal_moves=("a2a3", "a2a4"), halfmove_clock=0,
    )
    belief = Belief("white", 0, (Hypothesis(first.fen(), 0.5),
                                  Hypothesis(second.fen(), 0.5)), population_size=2)
    return AgentInput(obs, belief, 1000)


def test_contract_rejects_illegal_action_and_wrong_weights():
    turn = sample_turn()
    with pytest.raises(ValueError):
        Decision("e2e4", {"a2a3": 1.0, "a2a4": 0.0}).validate_for(turn.observation)
    with pytest.raises(ValueError):
        replace(turn.belief, hypotheses=(Hypothesis(turn.belief.hypotheses[0].fen, 0.9),))
    same_fen = turn.belief.hypotheses[0].fen
    Belief("white", 0, (Hypothesis(same_fen, 0.5, "path-a"),
                        Hypothesis(same_fen, 0.5, "path-b")))


def test_feature_planes_are_perspective_consistent_and_no_referee_board():
    turn = sample_turn()
    planes, weights = encode_belief(turn, lambda board: ("a2",))
    assert planes.shape == (2, 32, 8, 8)
    assert len(PLANE_NAMES) == 32
    np.testing.assert_allclose(weights, [0.5, 0.5])
    assert planes[0, 0, 6, 0] == 1  # Our pawn on a2.
    assert planes[0, 13].sum() == 0  # No observed enemy piece.
    assert planes[0, 18, 0, 3] == pytest.approx(0.5)  # Hidden queen on d8.
    np.testing.assert_array_equal(planes[0, 18], planes[1, 18])
    bad_obs = replace(turn.observation, visible_pieces={"e1": "K", "a2": "P", "b3": "p"})
    with pytest.raises(ValueError, match="contradicts"):
        encode_belief(replace(turn, observation=bad_obs), lambda board: ())


def test_teacher_record_round_trips(tmp_path):
    start = sample_turn()
    turn = AgentInput(replace(start.observation, ply=2), replace(start.belief, ply=2),
                      1000, (HistoryEvent(start.observation, "a2a3"),))
    decision = Decision("a2a3", {"a2a3": 0.6, "a2a4": 0.4}, {"search_nodes": 120.0})
    record = TrainingRecord(turn, decision, 0.1, (0.2, 0.0), 42, "zs21", "depth1")
    path = tmp_path / "labels.jsonl"
    write_records(path, [record])
    assert list(read_records(path)) == [record]


def test_common_match_loop_passes_only_agent_input_and_records_move():
    turn = sample_turn()

    class Referee:
        def reset(self, seed):
            self.ply = 0

        def current_player(self):
            return "white" if self.ply == 0 else "black"

        def is_terminal(self):
            return self.ply == 2

        def winner(self):
            return "white"

        def observe(self, player):
            moves = (("a2a3", "a2a4") if self.ply == 0 and player == "white"
                     else ("a7a6",) if self.ply == 1 and player == "black" else ())
            return replace(turn.observation, player=player, ply=self.ply, legal_moves=moves)

        def apply(self, move):
            assert move == ("a2a3" if self.ply == 0 else "a7a6")
            self.ply += 1

    class Tracker:
        def reset(self, player, seed):
            pass

        def update(self, observation):
            return replace(turn.belief, player=observation.player, ply=observation.ply)

    class Agent:
        name = "stub"

        def reset(self, player, seed):
            self.player = player

        def act(self, turn_input):
            assert isinstance(turn_input, AgentInput)
            if self.player == "white":
                assert not turn_input.history
                return Decision("a2a3", {"a2a3": 1.0, "a2a4": 0.0})
            assert len(turn_input.history) == 1
            assert turn_input.history[0].observation.ply == 0
            assert turn_input.history[0].own_move is None
            return Decision("a7a6", {"a7a6": 1.0})

    config = MatchConfig(1000, 100, 7, "fow-v1", "stockfish-19", 1)
    result = play_game(Referee(), {"white": Agent(), "black": Agent()},
                       {"white": Tracker(), "black": Tracker()}, config)
    assert result.winner == "white"
    assert len(result.plies) == 2
    assert result.plies[0].move == "a2a3"
    assert result.plies[1].move == "a7a6"
