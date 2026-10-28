"""The rules wrapper and the referee: one small rules interface that the referee and the belief
tracker both use, with Pair B's stand-in (python-chess, pairb.observe, fow_shared.values) or Teal's
RulesAdapter behind it.

A finished game is reported as (winner, reason), with Teal's reason names: king_capture,
fifty_move and threefold_repetition.
"""
import dataclasses
import random
import sys

import chess
import pytest

from fow_shared.contracts import Belief, Decision, Hypothesis
from fow_shared.evaluation import MatchConfig, play_game
from pairb.observe import observe
from pairb.rules import GameReferee, StandinRules, StandinState, pick_rules, teal_available

KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"   # Re2xe8 takes the king
FIFTY_MOVE = "8/8/8/4k3/8/8/3Q4/4K3 w - - 100 80"  # the halfmove clock has already reached 100
NO_BLACK_KING = "8/8/8/8/8/8/8/4K3 w - - 0 1"       # a start that is already decided: Black has no king
# (start FEN, moves played, how the game ends: (winner, reason))
FINISHED = [
    ("7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1", [], ("draw", "no_legal_moves")),
    (KING_CAPTURE, ["e2e8"], ("white", "king_capture")),
    (FIFTY_MOVE, [], ("draw", "fifty_move")),
    (chess.STARTING_FEN, ["g1f3", "g8f6", "f3g1", "f6g8"] * 2, ("draw", "threefold_repetition")),
    (NO_BLACK_KING, [], ("white", "king_capture")),  # the side to move has won, not lost
]


def play(rules, fen, moves):
    state = rules.initial_state(fen)
    for move in moves:
        state = rules.apply_move(state, move)
    return state


# Catches: the stand-in's view drifting from pairb.observe, or built for the wrong ply.
def test_standin_matches_pairb_observe():
    rules = StandinRules()
    s = rules.initial_state()
    for mv in ["e2e4", "e7e5", "g1f3"]:
        s = rules.apply_move(s, mv)
    for player in ("white", "black"):
        assert rules.observe(s, player) == observe(rules.board(s), player, ply=3)


# Catches: a wrong winner or reason name, a game ending too early (threefold, not twofold), and a
# finished game whose two views disagree with the result.
@pytest.mark.parametrize("fen, moves, result", FINISHED)
def test_standin_terminal(fen, moves, result):
    rules = StandinRules()
    state = rules.initial_state(fen)
    for move in moves:
        assert rules.terminal(state) is None  # still going before the last move
        state = rules.apply_move(state, move)
    assert rules.terminal(state) == result
    assert rules.legal_moves(state) == ()
    for player in ("white", "black"):
        want = 0.0 if result[0] == "draw" else 1.0 if result[0] == player else -1.0
        view = rules.observe(state, player)
        assert (view.terminal, view.outcome) == (True, want)


# Catches: a game in progress reported as finished.
def test_a_game_in_progress_has_no_result():
    rules = StandinRules()
    assert rules.terminal(rules.initial_state()) is None
    assert rules.terminal(play(rules, KING_CAPTURE, [])) is None


# Catches: an illegal move accepted, a move accepted after the end, the two failures not told apart,
# or a failed move changing the state.
def test_apply_rejects_illegal_and_finished():
    rules = StandinRules()
    start = rules.initial_state()
    for bad in ["e2e5", "e7e5", "e1e1", "zzzz", ""]:  # a triple step, the other side's pawn, a king standing still, junk
        with pytest.raises(ValueError, match="not a legal move"):
            rules.apply_move(start, bad)
    assert (rules.board(start).fen(), start.ply) == (chess.STARTING_FEN, 0)
    over = play(rules, KING_CAPTURE, ["e2e8"])
    with pytest.raises(ValueError, match="game is over"):
        rules.apply_move(over, "e8e7")


# Catches: push_uci used instead of push; it refuses moves that only fog-of-war rules allow.
@pytest.mark.parametrize("fen, move, after", [
    ("4k3/8/8/8/8/5r2/8/R3K2R w KQ - 0 1", "e1g1", "4k3/8/8/8/8/5r2/8/R4RK1 b - - 1 1"),  # castles through check
    ("4k3/8/8/8/8/5r2/8/4K3 w - - 0 1", "e1f1", "4k3/8/8/8/8/5r2/8/5K2 b - - 1 1"),      # king steps onto an attacked square
])
def test_fog_only_moves_are_played(fen, move, after):
    with pytest.raises(ValueError):
        chess.Board(fen).push_uci(move)  # the premise: ordinary chess refuses this move
    rules = StandinRules()
    assert rules.board(rules.apply_move(rules.initial_state(fen), move)).fen() == after


# Catches: apply_move changing the state it was given. A tracker branches one state into many.
def test_apply_move_leaves_the_old_state_alone():
    rules = StandinRules()
    first = rules.initial_state()
    a, b = rules.apply_move(first, "e2e4"), rules.apply_move(first, "d2d4")
    assert (first.ply, a.ply, b.ply) == (0, 1, 1)
    assert rules.board(first).fen() == chess.STARTING_FEN
    assert [m.uci() for m in rules.board(a).move_stack] == ["e2e4"]
    assert [m.uci() for m in rules.board(b).move_stack] == ["d2d4"]


# Catches: board() handing out the state's own board, so a caller's move changes the game, or
# dropping the move stack, so repetition could no longer be seen.
def test_board_is_an_independent_copy_with_the_full_move_stack():
    rules = StandinRules()
    state = play(rules, None, ["e2e4", "e7e5", "g1f3"])
    board = rules.board(state)
    assert [m.uci() for m in board.move_stack] == ["e2e4", "e7e5", "g1f3"]
    board.push(chess.Move.from_uci("b8c6"))  # a caller's change must not reach the game
    again = rules.board(state)
    assert again.fen() == "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    assert [m.uci() for m in again.move_stack] == ["e2e4", "e7e5", "g1f3"]


# Catches: unsorted or missing legal moves, and moves offered after the game has ended.
def test_legal_moves_are_sorted_uci_and_empty_when_the_game_is_over():
    rules = StandinRules()
    moves = rules.legal_moves(rules.initial_state())
    assert isinstance(moves, tuple) and len(moves) == 20 and list(moves) == sorted(moves)
    assert rules.legal_moves(play(rules, KING_CAPTURE, ["e2e8"])) == ()


# Catches: the side to move read from a move count instead of the board (a custom start can give Black the move).
def test_the_side_to_move_follows_the_board():
    rules = StandinRules()
    assert rules.current_player(rules.initial_state()) == "white"
    assert rules.current_player(play(rules, None, ["e2e4"])) == "black"
    assert rules.current_player(rules.initial_state("k7/8/1Q6/8/8/8/8/K7 b - - 0 1")) == "black"


# Catches: a position Teal's adapter refuses (no king at all, two kings of one colour) or a junk FEN
# being accepted as a start.
@pytest.mark.parametrize("fen", ["8/8/8/8/8/8/8/8 w - - 0 1", "4k3/8/8/8/8/8/8/3KK3 w - - 0 1", "not a fen"])
def test_initial_state_rejects_unplayable_positions(fen):
    with pytest.raises(ValueError):
        StandinRules().initial_state(fen)


# Catches: a state that can be reassigned, or a ply that does not start at 0.
def test_a_state_is_frozen_and_starts_at_ply_0():
    state = StandinRules().initial_state()
    assert isinstance(state, StandinState) and state.ply == 0
    assert state.board.fen() == chess.STARTING_FEN
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.ply = 1


# Catches: the choice of rules going wrong, or the name and label (the page names the rules in use) changing.
def test_pick_rules_auto():
    assert pick_rules().name == ("teal-rules-adapter" if teal_available() else "pairb-standin")


def test_pick_rules_standin():
    rules = pick_rules("standin")
    assert isinstance(rules, StandinRules)
    assert (rules.name, rules.label) == ("pairb-standin", "Pair B stand-in")


def test_pick_rules_rejects_an_unknown_choice():
    with pytest.raises(ValueError, match="auto"):
        pick_rules("fast")


# Catches: a missing adapter raising instead of reporting False, "auto" not falling back to the
# stand-in, or "teal" failing with another message. Blocks the import, so it holds where Teal's
# adapter is present too.
def test_without_teals_adapter_auto_falls_back_and_teal_is_refused(monkeypatch):
    monkeypatch.setitem(sys.modules, "pair_a_prep.rules_adapter", None)  # `import` now fails
    assert teal_available() is False
    assert pick_rules("auto").name == "pairb-standin"
    with pytest.raises(ValueError, match="Teal's rules adapter is not in this checkout"):
        pick_rules("teal")


# Catches: the Referee protocol broken: a winner named before the end, or none after it.
def test_referee_protocol():
    referee = GameReferee(StandinRules(), KING_CAPTURE)
    assert (referee.current_player(), referee.is_terminal(), referee.result(), referee.ply) == \
           ("white", False, None, 0)
    with pytest.raises(ValueError):
        referee.winner()
    referee.apply("e2e8")
    assert referee.is_terminal() and referee.winner() == "white"
    assert (referee.result(), referee.ply) == (("white", "king_capture"), 1)


# Catches: a drawn game reporting a colour as the winner.
def test_referee_names_a_draw():
    referee = GameReferee(StandinRules(), FIFTY_MOVE)
    assert referee.is_terminal() and referee.winner() == "draw"
    assert referee.result() == ("draw", "fifty_move")


# Catches: reset ignoring the custom start, or leaving the ply counter or the position behind.
def test_referee_reset_goes_back_to_the_start_position():
    referee = GameReferee(StandinRules(), "k7/8/1Q6/8/8/8/8/K7 b - - 0 1")
    start = referee.true_board().fen()
    referee.apply(referee.observe("black").legal_moves[0])
    assert referee.ply == 1 and referee.true_board().fen() != start
    referee.reset(7)
    assert (referee.true_board().fen(), referee.ply, referee.current_player()) == (start, 0, "black")


# Catches: a rejected move still advancing the game, or a ply that can be written to.
def test_referee_rejects_a_bad_move_without_changing_the_game():
    referee = GameReferee(StandinRules())
    with pytest.raises(ValueError):
        referee.apply("e2e5")
    assert (referee.ply, referee.current_player(), referee.true_board().fen()) == (0, "white", chess.STARTING_FEN)
    with pytest.raises(AttributeError):
        referee.ply = 3


# Catches: true_board() handing out the referee's own board, or observe() not giving each side its view.
def test_referee_hands_out_copies_and_each_sides_view():
    referee = GameReferee(StandinRules())
    referee.apply("e2e4")
    board = referee.true_board()
    board.push(chess.Move.from_uci("a7a6"))  # a caller's change must not reach the game
    assert [m.uci() for m in referee.true_board().move_stack] == ["e2e4"]
    for player in ("white", "black"):
        assert referee.observe(player) == observe(referee.true_board(), player, ply=1)


class TakeTheKing:
    """An agent that plays e2e8 when it can, which ends the game, and otherwise its first legal move."""
    name = "take-the-king"

    def reset(self, player, seed):
        pass

    def act(self, turn):
        moves = turn.observation.legal_moves
        move = "e2e8" if "e2e8" in moves else moves[0]
        return Decision(move, {m: float(m == move) for m in moves})


class FixedBelief:
    """A tracker that believes in one position; play_game only needs it to answer."""

    def reset(self, player, seed):
        self.player = player

    def update(self, observation, own_move=None):
        return Belief(self.player, observation.ply, (Hypothesis(KING_CAPTURE, 1.0),))


# Catches: the referee not working as play_game's Referee (reset(seed), observe, apply, winner).
def test_the_referee_runs_a_game_through_play_game():
    referee = GameReferee(StandinRules(), KING_CAPTURE)
    result = play_game(referee, {"white": TakeTheKing(), "black": TakeTheKing()},
                       {"white": FixedBelief(), "black": FixedBelief()},
                       MatchConfig(1000, 10, 0, "pairb-standin", "none", 0))
    assert result.winner == "white" and len(result.plies) == 1 and not result.stopped_at_ply_limit


def _without_captured_square(observation):
    return dataclasses.replace(observation, captured_own_piece_at=None)


# Catches: any drift between the stand-in and Teal's adapter, or a board() that is not an
# independent copy with the full move stack. The stand-in does not fill captured_own_piece_at, so it
# is cleared on both sides.
@pytest.mark.skipif(not teal_available(), reason="Teal's rules adapter is not in this checkout")
def test_teal_and_standin_agree():
    teal, standin = pick_rules("teal"), pick_rules("standin")
    assert (teal.name, teal.label) == ("teal-rules-adapter", "Teal's RulesAdapter")

    def check(t, s, plies):
        assert teal.current_player(t) == standin.current_player(s)
        assert teal.legal_moves(t) == standin.legal_moves(s)
        assert teal.board(t).fen() == standin.board(s).fen()
        assert teal.terminal(t) == standin.terminal(s)
        for player in ("white", "black"):
            assert _without_captured_square(teal.observe(t, player)) == \
                   _without_captured_square(standin.observe(s, player))
        for rules, state in ((teal, t), (standin, s)):
            board = rules.board(state)
            assert len(board.move_stack) == plies  # the whole history comes with the board
            board.clear_stack()  # a caller's change must not reach the state
            assert len(rules.board(state).move_stack) == plies

    for seed in range(10):  # seeded random games of up to 40 plies
        rng = random.Random(seed)
        t, s = teal.initial_state(), standin.initial_state()
        check(t, s, 0)
        for plies in range(1, 41):
            if standin.terminal(s) is not None:
                break
            move = rng.choice(standin.legal_moves(s))
            t, s = teal.apply_move(t, move), standin.apply_move(s, move)
            check(t, s, plies)
    for fen, moves, result in FINISHED:  # one of each way a game ends
        t, s = play(teal, fen, moves), play(standin, fen, moves)
        check(t, s, len(moves))
        assert teal.terminal(t) == result
    for rules in (teal, standin):  # both refuse junk and illegal moves, and any move after the end
        for bad in ("", "zzzz", "e2e5"):
            with pytest.raises(ValueError):
                rules.apply_move(rules.initial_state(), bad)
        with pytest.raises(ValueError):
            rules.apply_move(play(rules, KING_CAPTURE, ["e2e8"]), "e8e7")
