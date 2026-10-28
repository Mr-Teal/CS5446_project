"""Private views, special moves and the real referee/runner boundary."""

from dataclasses import asdict

import chess
import pytest

from fow_shared.contracts import Belief, Decision, Hypothesis
from fow_shared.evaluation import MatchConfig, play_game
from pair_a_prep.fixtures import compare_result, load_suite
from pair_a_prep.rules_adapter import RulesAdapter, RulesReferee


@pytest.mark.parametrize("case", load_suite()["cases"], ids=lambda c: c["id"])
def test_complete_fixture_expectations(case):
    rules = RulesAdapter()
    state = rules.initial_state(case.get("initial_fen", case["fen"]))
    for move in case.get("moves_uci", []):
        state = rules.apply_move(state, move)
    obs = rules.observe(state, case["player"])
    result = asdict(obs)
    ended = rules.terminal(state)
    result["winner"] = ended.winner if ended else None
    assert compare_result(case, result) == []


def test_off_turn_view_and_detached_snapshot():
    rules = RulesAdapter()
    state = rules.initial_state()
    black = rules.observe(state, "black")
    assert black.side_to_move == "white" and black.legal_moves == ()
    assert "e5" in black.visible_squares and "e2" not in black.visible_squares
    white = rules.observe(state, "white")
    white.visible_pieces.clear()
    assert rules.observe(state, "white").visible_pieces["e1"] == "K"
    assert rules.observe(state, "white").halfmove_clock is None
    with pytest.raises(ValueError):
        rules.observe(state, "w")


def test_capture_notification_is_private_and_lasts_one_ply():
    rules = RulesAdapter()
    state = rules.initial_state("7k/8/8/5n2/4P3/8/8/K7 w - - 0 1")
    state = rules.apply_move(state, "e4f5")
    assert rules.observe(state, "black").captured_own_piece_at == "f5"
    assert rules.observe(state, "white").captured_own_piece_at is None
    state = rules.apply_move(state, "h8g8")
    assert rules.observe(state, "black").captured_own_piece_at is None


def test_hidden_enemy_positions_do_not_change_private_view():
    rules = RulesAdapter()
    a = rules.initial_state("7k/8/8/8/8/8/4P3/K7 w - - 0 1")
    b = rules.initial_state("6k1/8/8/8/8/8/4P3/K7 w - - 27 1")
    assert rules.observe(a, "white") == rules.observe(b, "white")


def test_referee_king_capture_terminal_views_and_reset():
    referee = RulesReferee("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
    with pytest.raises(ValueError):
        referee.winner()
    referee.apply("e2e8")
    assert referee.winner() == "white"
    for player, value in [("white", 1.0), ("black", -1.0)]:
        obs = referee.observe(player)
        assert obs.terminal and obs.outcome == value and obs.legal_moves == ()
    with pytest.raises(ValueError):
        referee.apply("e1e2")
    referee.reset(seed=1)
    assert not referee.is_terminal() and referee.observe("white").ply == 0


def test_full_runner_game_with_real_referee_and_terminal_tracker_updates():
    # Publicly scripted demonstration, not a belief tracker or strength baseline.
    moves = ["e2e4", "f7f6", "d1h5", "g7g5", "h5e8"]

    class ScriptedAgent:
        name = "rules-smoke-script"

        def reset(self, player, seed):
            pass

        def act(self, turn):
            legal = turn.observation.legal_moves
            return Decision(moves[turn.observation.ply], {m: 1 / len(legal) for m in legal})

    class ProbeTracker:
        def reset(self, player, seed):
            self.player, self.calls = player, []

        def update(self, observation, own_move=None):
            self.calls.append((observation, own_move))
            # Placeholder satisfies the shared shape only; never used for choice.
            return Belief(self.player, observation.ply, (Hypothesis(chess.STARTING_FEN, 1.0),))

    trackers = {p: ProbeTracker() for p in ("white", "black")}
    result = play_game(RulesReferee(), {p: ScriptedAgent() for p in trackers}, trackers,
                       MatchConfig(1000, 20, 17, "paper_fow_v1_proposed", "none", 1))
    assert result.winner == "white" and not result.stopped_at_ply_limit
    for player, tracker in trackers.items():
        assert len(tracker.calls) == 6
        obs, own_move = tracker.calls[-1]
        assert obs.terminal and obs.ply == 5
        assert own_move == ("h5e8" if player == "white" else None)
