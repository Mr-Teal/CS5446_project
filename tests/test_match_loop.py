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
        over = self.is_terminal()
        moves = (MOVES[self.ply],) if player == to_move and not over else ()
        return Observation(player=player, side_to_move=to_move, ply=self.ply, visible_squares=(),
                           visible_pieces={}, legal_moves=moves, terminal=over, outcome=0.0 if over else None)

    def apply(self, move):
        assert move == MOVES[self.ply]
        self.ply += 1


class RecordingTracker:
    def reset(self, player, seed):
        self.player, self.calls = player, []

    def update(self, observation, own_move=None):
        self.calls.append((observation.ply, own_move, observation.terminal))
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
    # (ply of the new snapshot, own move that led to it, game over). The move that ends the
    # game still reaches both trackers, with the final snapshot.
    assert trackers["white"].calls == [(0, None, False), (1, "e2e4", False), (2, None, False), (3, "g1f3", True)]
    assert trackers["black"].calls == [(0, None, False), (1, None, False), (2, "e7e5", False), (3, None, True)]
    # The history pins the same move to the snapshot BEFORE it: White's ply-0 view, then e2e4.
    history = agents["white"].histories[-1]
    assert [(e.observation.ply, e.own_move) for e in history] == [(0, "e2e4"), (1, None)]


def test_a_snapshot_naming_the_wrong_side_to_move_stops_the_game():
    with pytest.raises(ValueError, match="side to move"):
        play(ScriptedReferee(wrong_side_at_ply=1))


def test_diagnostics_snapshot_preserves_fallback_without_inventing_missing_values():
    from dataclasses import asdict
    import json

    class DiagnosticAgent(ScriptedAgent):
        def reset(self, player, seed):
            super().reset(player, seed)
            self.calls = 0
            self.values = {}

        def act(self, turn):
            move = turn.observation.legal_moves[0]
            self.calls += 1
            self.values.clear()
            self.values.update(fallback=float(self.calls == 1), search_nodes=0.0,
                               evaluator_calls=float(self.calls * 3), custom_work=7.0)
            return Decision(move, {move: 1.0}, self.values)

    white, black = DiagnosticAgent(), ScriptedAgent()
    result = play_game(ScriptedReferee(), {"white": white, "black": black},
                       {side: RecordingTracker() for side in ("white", "black")},
                       MatchConfig(1000, 10, 7, "fow-v1", "test", 0))
    white.values.clear()
    rows = json.loads(json.dumps([asdict(ply) for ply in result.plies]))
    assert rows[0]["diagnostics"] == dict(fallback=1.0, search_nodes=0.0,
                                          evaluator_calls=3.0, custom_work=7.0)
    assert rows[1]["diagnostics"] == {}
    assert rows[2]["diagnostics"] == dict(fallback=0.0, search_nodes=0.0,
                                          evaluator_calls=6.0, custom_work=7.0)
    assert all(row["search_nodes"] == 0.0 for row in rows)
