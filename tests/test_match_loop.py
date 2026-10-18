"""play_game hands each belief tracker its own last move, and checks whose turn each snapshot names."""
import chess
import pytest

from fow_shared.contracts import Belief, Decision, Hypothesis, Observation
from fow_shared.evaluation import MatchConfig, play_game

MOVES = ("e2e4", "e7e5", "g1f3")  # the game ends after these three plies


class ScriptedReferee:
    def __init__(self, wrong_side_at_ply=None):
        self.wrong_side_at_ply = wrong_side_at_ply

    def reset(self, seed):
        self.ply = 0

    def current_player(self):
        return "white" if self.ply % 2 == 0 else "black"

    def is_terminal(self):
        return self.ply == len(MOVES)

    def winner(self):
        return "draw"

    def observe(self, player):
        to_move = self.current_player()
        if self.ply == self.wrong_side_at_ply and player != to_move:
            to_move = player  # a referee bug: the waiting player is told it is their turn
        moves = (MOVES[self.ply],) if player == to_move and not self.is_terminal() else ()
        return Observation(player=player, side_to_move=to_move, ply=self.ply, visible_squares=(),
                           visible_pieces={}, legal_moves=moves)

    def apply(self, move):
        assert move == MOVES[self.ply]
        self.ply += 1


class RecordingTracker:
    def reset(self, player, seed):
        self.player, self.calls = player, []

    def update(self, observation, own_move=None):
        self.calls.append((observation.ply, own_move))
        return Belief(self.player, observation.ply, (Hypothesis(chess.STARTING_FEN, 1.0),))


class ScriptedAgent:
    name = "scripted"

    def reset(self, player, seed):
        self.histories = []

    def act(self, turn):
        self.histories.append(turn.history)
        move = turn.observation.legal_moves[0]
        return Decision(move, {move: 1.0})


def play(referee):
    agents = {"white": ScriptedAgent(), "black": ScriptedAgent()}
    trackers = {"white": RecordingTracker(), "black": RecordingTracker()}
    play_game(referee, agents, trackers, MatchConfig(1000, 10, 7, "fow-v1", "stockfish-19", 1))
    return agents, trackers


def test_each_tracker_is_told_its_own_last_move_and_never_the_opponents():
    agents, trackers = play(ScriptedReferee())
    # (ply of the new snapshot, own move that led to it). No update after the final ply.
    assert trackers["white"].calls == [(0, None), (1, "e2e4"), (2, None)]
    assert trackers["black"].calls == [(0, None), (1, None), (2, "e7e5")]
    # The history pins the same move to the snapshot BEFORE it: White's ply-0 view, then e2e4.
    history = agents["white"].histories[-1]
    assert [(e.observation.ply, e.own_move) for e in history] == [(0, "e2e4"), (1, None)]


def test_a_snapshot_naming_the_wrong_side_to_move_stops_the_game():
    with pytest.raises(ValueError, match="side to move"):
        play(ScriptedReferee(wrong_side_at_ply=1))
