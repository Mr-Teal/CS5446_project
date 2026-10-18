"""D2 stand-in dataset pieces: game play, parent choice, labelling (D1 spec §6)."""
import shutil

import chess
import pytest

from pairb.d2 import game_end, label_parent, pick_parents, play_game
from pairb.stockfish import StockfishEvaluator

needs_engine = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")

# White: Kg6, Qf1. Black: Kh8. 21 queen moves + 6 king moves (g7, h7 touch Black's king) = 27.
STALEMATE_OR_MATE = "7k/8/6K1/8/8/8/8/5Q2 w - - 0 1"


def board_after(sans):
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


# Catches: games ended by chess verdicts where fog-of-war differs (stalemate), or repetition missed.
@pytest.mark.parametrize("board, want", [
    (chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"), ("checkmate", 1)),
    (chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), ("stalemate", 1)),
    (chess.Board("8/8/8/4k3/8/8/3Q4/4K3 w - - 100 80"), ("fifty-move", 0)),
    (board_after(["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8"]), ("repetition", 0)),
    (chess.Board(), None),
])
def test_game_end_scores_results_from_whites_view(board, want):
    assert game_end(board) == want


# Catches: parents taken from the opening, or the final (finished) position used as a parent.
def test_pick_parents_takes_only_unfinished_positions_after_the_opening():
    assert pick_parents(n_moves=10, k=5, seed=1, min_ply=8) == [8, 9]
    assert pick_parents(n_moves=8, k=5, seed=1, min_ply=8) == []


# Catches: parent choice that changes between runs.
def test_pick_parents_is_reproducible_and_distinct():
    picks = pick_parents(n_moves=100, k=3, seed=4, min_ply=8)
    assert picks == pick_parents(n_moves=100, k=3, seed=4, min_ply=8)
    assert len(set(picks)) == 3 and picks == sorted(picks)
    assert all(8 <= p <= 99 for p in picks)


@needs_engine
def test_play_game_is_reproducible_from_its_seed():
    with StockfishEvaluator(depth=1) as ev:
        first = play_game(7, ev.engine, max_plies=40)
        again = play_game(7, ev.engine, max_plies=40)
        other = play_game(8, ev.engine, max_plies=40)
    assert first == again
    assert first[0] != other[0]


@needs_engine
def test_play_game_draws_its_random_move_rate_from_the_given_range():
    with StockfishEvaluator(depth=1) as ev:
        rates = [play_game(seed, ev.engine, max_plies=4, eps_range=(0.01, 0.02))[1]["eps"] for seed in range(5)]
    assert all(0.01 <= r <= 0.02 for r in rates)


@needs_engine
def test_play_game_plays_legal_moves_and_reports_how_it_ended():
    with StockfishEvaluator(depth=1) as ev:
        moves, info = play_game(11, ev.engine, max_plies=40)
    board = chess.Board()
    for uci in moves:
        assert chess.Move.from_uci(uci) in board.legal_moves
        board.push_uci(uci)
    if info["termination"] == "max-plies":
        assert len(moves) == 40 and info["result"] is None
    else:
        assert game_end(board) == (info["termination"], info["result"])


@needs_engine
def test_label_parent_gives_one_record_per_move_with_rules_applied():
    with StockfishEvaluator(depth=1) as ev1, StockfishEvaluator(depth=3) as ev3:
        records = label_parent(chess.Board(STALEMATE_OR_MATE), "g-000001", 30, ev1, ev3)
    assert len(records) == 27
    by_move = {r["move"]: r for r in records}

    stalemate = by_move["f1f7"]
    assert stalemate["fen"] == "7k/5Q2/6K1/8/8/8/8/8 b - - 1 1"
    assert stalemate["rule"] == {"name": "forced-loss", "v": 1.0}
    assert stalemate["d1"] is None and stalemate["d11"] is None
    assert stalemate["id"] == "d2-g-000001-030-f1f7"
    assert stalemate["ply"] == 31 and stalemate["game_id"] == "g-000001"
    assert stalemate["parent_fen"] == STALEMATE_OR_MATE

    assert by_move["f1f8"]["rule"] == {"name": "forced-loss", "v": 1.0}

    normal = by_move["f1a6"]  # White keeps the queen: winning
    assert normal["rule"] is None
    assert normal["d1"]["v"] > 0.5 and normal["d11"]["v"] > 0.5

    for r in records:
        child = chess.Board(STALEMATE_OR_MATE)
        child.push_uci(r["move"])
        assert r["fen"] == child.fen()
