import chess
import pytest

from pair_a_prep.rules_adapter import RulesAdapter
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.zs21.model import PositionTracker, position_key, Referee, DrawMemory, SearchRules


def test_position_tracker_matches_history_oracle_short_game():
    referee = Referee()
    exact = {p: BeliefTracker() for p in ("white", "black")}
    compact = {p: PositionTracker(p, 17) for p in exact}
    for p in exact:
        exact[p].reset(p, 17)
    moves = [None, "e2e4", "d7d5", "e4d5", "g8f6"]
    for move in moves:
        mover = referee.current_player()
        if move:
            referee.apply(move)
        for p in exact:
            own = move if p == mover else None
            view = referee.observe(p)
            belief = exact[p].update(view, own)
            compact[p].update(view, own)
            assert {position_key(chess.Board(h.fen)) for h in belief.hypotheses} == {
                position_key(c.state._board) for c in compact[p].candidates}


def test_possible_draw_counts_each_ply_once_and_sticks():
    rules = SearchRules()
    state = rules.initial_state()
    memory = DrawMemory.empty()
    view = rules.observe(state, "white")
    memory = memory.advance(view)
    assert memory.advance(view) is memory
    for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
        ours = rules.current_player(state) == "white"
        state = rules.apply_move(state, move)
        memory = memory.advance(rules.observe(state, "white"), move if ours else None)
    assert memory.capped
    assert memory.value(1.) == 0
    assert memory.value(-.6) == -.6


def test_effective_ep_keeps_capture_exposing_king():
    board = chess.Board("4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    first = position_key(board)
    board.ep_square = None
    assert position_key(board) != first


def test_referee_repetition_and_no_false_checkmate():
    ref = Referee()
    for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
        ref.apply(move)
    assert ref.winner() == "draw"
    mate = Referee("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
    assert not mate.is_terminal()
    assert mate.observe("black").legal_moves
