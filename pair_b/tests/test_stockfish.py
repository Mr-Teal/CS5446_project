"""StockfishEvaluator against the real engine (D1 spec v0.3 §3).

Values follow fow_shared's rule: from the acting player's point of view. For evaluate_children
that is the player to move at the node; for evaluate_boards it is the player named in the call.
"""
import shutil

import chess
import pytest

from pairb.stockfish import StockfishEvaluator

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")

# White: Kg6, Qf1. Black: Kh8. Qf1-f7 stalemates Black, Qf1-f8 mates.
STALEMATE_OR_MATE = "7k/8/6K1/8/8/8/8/5Q2 w - - 0 1"
# The same position with colours swapped: Black to move; Qf8-f2 stalemates White, Qf8-f1 mates.
STALEMATE_OR_MATE_BLACK = "5q2/8/8/8/8/6k1/8/7K b - - 0 1"


# Catches: a king-capturable board sent to Stockfish (the engine process dies).
def test_evaluate_boards_scores_king_capture_by_rule_and_keeps_engine_alive():
    with StockfishEvaluator(depth=1) as ev:
        values = ev.evaluate_boards(["4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", chess.STARTING_FEN], "white")
    assert values[0] == 1.0
    assert -0.2 < values[1] < 0.2  # the start position is roughly level


# Catches: values reported from the wrong player's side.
def test_evaluate_boards_reports_values_from_the_named_players_view():
    # After 1.e4 e5 2.Nf3 Nc6 3.Nc3, Black to move: White is slightly better.
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R b KQkq - 3 3"
    with StockfishEvaluator(depth=11) as ev:
        (for_white,) = ev.evaluate_boards([fen], "white")
        (for_black,) = ev.evaluate_boards([fen], "black")
    assert 0 < for_white < 0.2 and for_black == -for_white


# Catches: a typo'd colour silently treated as one side (fow_shared spells colours "white"/"black").
def test_evaluate_boards_rejects_an_unknown_player():
    with StockfishEvaluator(depth=1) as ev:
        with pytest.raises(ValueError):
            ev.evaluate_boards([chess.STARTING_FEN], "w")


# Catches: MultiPV not set, so only the best move comes back.
def test_children_scores_has_one_entry_per_legal_move():
    with StockfishEvaluator(depth=1) as ev:
        scores = ev.children_scores(chess.Board())
    assert sorted(scores) == sorted(["a2a3", "a2a4", "b2b3", "b2b4", "c2c3", "c2c4", "d2d3", "d2d4",
                                     "e2e3", "e2e4", "f2f3", "f2f4", "g2g3", "g2g4", "h2h3", "h2h4",
                                     "b1a3", "b1c3", "g1f3", "g1h3"])


# Catches: child values reported from White's side instead of the moving player's.
def test_evaluate_children_reports_values_from_the_moving_players_view():
    # Black to move; Qb1xa1 wins White's undefended queen, so it is good for Black.
    with StockfishEvaluator(depth=1) as ev:
        values = ev.evaluate_children("4k3/8/8/8/8/7K/8/Qq6 b - - 0 1")
    assert values["b1a1"] > 0.5


# Catches: children decided by fog-of-war rules scored with Stockfish's chess verdict
# (Stockfish calls the stalemate a draw).
def test_evaluate_children_applies_fog_rules_to_children():
    with StockfishEvaluator(depth=1) as ev:
        values = ev.evaluate_children(STALEMATE_OR_MATE)
    assert values["f1f7"] == 1.0  # stalemate: White, who delivered it, wins
    assert values["f1f8"] == 1.0  # checkmate


# Catches: rule values (+1 for the side that delivers stalemate or mate) left in White's view.
def test_evaluate_children_applies_fog_rules_from_the_moving_players_view():
    with StockfishEvaluator(depth=1) as ev:
        values = ev.evaluate_children(STALEMATE_OR_MATE_BLACK)
    assert values["f8f2"] == 1.0  # Black stalemates White and wins
    assert values["f8f1"] == 1.0  # Black mates


# Teal's example: python-chess calls this checkmate, but fog rules let White castle out of check.
CASTLE_ESCAPE = "8/8/8/8/8/4k3/4q3/4K2R w K - 0 1"


# Catches: fog-only moves (castling out of check, moving into check) missing from the children.
def test_evaluate_children_covers_fog_of_war_moves():
    with StockfishEvaluator(depth=1) as ev:
        values = ev.evaluate_children(CASTLE_ESCAPE)
    assert values["e1g1"] > -1.0       # castling out of check reaches an unattacked square
    assert values["e1d1"] == -1.0      # moving into check loses the king next move
    assert values["e1f2"] == -1.0


# Catches: a king-capture position sent to Stockfish (it crashes) instead of being scored by rule.
def test_evaluate_children_takes_the_king_when_it_can():
    with StockfishEvaluator(depth=1) as ev:
        values = ev.evaluate_children("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
        assert values["e2e8"] == 1.0
        assert ev.evaluate_boards([chess.STARTING_FEN], "white")  # the engine is still alive


# Catches: a board with no orthodox move scored as Stockfish's "mated" although fog rules allow an escape.
def test_evaluate_boards_looks_one_move_ahead_when_orthodox_chess_has_no_move():
    with StockfishEvaluator(depth=1) as ev:
        (value,) = ev.evaluate_boards([CASTLE_ESCAPE], "white")
    assert value > -1.0


def test_evaluate_children_of_a_finished_game_is_empty():
    with StockfishEvaluator(depth=1) as ev:
        assert ev.evaluate_children("8/8/8/8/8/8/8/4K3 b - - 0 1") == {}         # Black's king is gone
        assert ev.evaluate_children("8/8/8/4k3/8/8/3Q4/4K3 w - - 100 80") == {}  # fifty-move draw


# Catches: boards from different beliefs mixed in a batch, or values from the wrong side.
def test_evaluate_beliefs_answers_each_belief_with_its_own_boards():
    from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation

    def turn(player, fens):
        obs = Observation(player=player, side_to_move=player, ply=6, visible_squares=(), visible_pieces={},
                          legal_moves=(), halfmove_clock=0)
        hyps = tuple(Hypothesis(f, 1 / len(fens)) for f in fens)
        return AgentInput(obs, Belief(player, 6, hyps), 1000)

    white = turn("white", ["4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", chess.STARTING_FEN])
    black = turn("black", ["4k3/4r3/8/8/8/8/8/4K3 b - - 0 1"])
    with StockfishEvaluator(depth=1) as ev:
        answers = ev.evaluate_beliefs([white, black])
        start_for_white = ev.evaluate_boards([chess.STARTING_FEN], "white")[0]
    assert len(answers) == 2
    assert answers[0].hypothesis_values == (1.0, start_for_white)
    assert answers[1].hypothesis_values == (1.0,)   # Black to move takes the king: +1 for Black
    for answer, t in zip(answers, (white, black)):
        answer.validate_for(t)


def teals_repetition_board():
    """Teal's example on PR #4: Black to move; Kh8-g8 would make the third Kg6/Qf7/Kg8 position."""
    board = chess.Board("6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1")
    for uci in ["f7f6", "g8h8", "f6f7", "h8g8", "f7f6", "g8h8", "f6f7"]:
        board.push(chess.Move.from_uci(uci))
    return board


# Catches: each move's result judged without the game's history, so a threefold-repetition draw
# reads as White taking the king (+1).
def test_children_values_keeps_the_history_so_a_repetition_draw_is_seen():
    with StockfishEvaluator(depth=1) as ev:
        values = ev.children_values(teals_repetition_board())
    assert values["h8g8"] == (0.0, True)


# Catches: the moves that led to a position sent to Stockfish with it. python-chess replays them,
# and a fog-only move among them (here castling out of check) is illegal for Stockfish.
def test_a_position_reached_by_a_fog_only_move_is_sent_to_stockfish_alone():
    from fow_shared.values import fog_legal_moves
    board = chess.Board("8/8/8/8/8/4k3/4q3/4K2R w K - 0 1")
    board.push(chess.Move.from_uci("e1g1"))
    board.push(chess.Move.from_uci("e3d3"))
    with StockfishEvaluator(depth=1) as ev:
        values = ev.children_values(board)
    assert sorted(values) == sorted(m.uci() for m in fog_legal_moves(board))
    assert all(-1 <= v <= 1 for v, _ in values.values())


# Catches: a board with no orthodox move, no fog-legal move and no rule result (every piece blocked)
# crashing a search with max() of no children. It is scored as a draw, and flagged as decided.
def test_a_board_with_no_move_and_no_rule_result_is_scored_as_a_draw(monkeypatch):
    import pairb.stockfish as sf
    stalemated = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert not any(stalemated.generate_legal_moves())
    monkeypatch.setattr(sf, "rule_value", lambda board: None)
    monkeypatch.setattr(sf, "fog_legal_moves", lambda board: [])
    with StockfishEvaluator(depth=1) as ev:
        assert ev.board_value(stalemated) == (0.0, True)


# Catches: a search's leftovers (the engine's hash) changing the values of a later, unrelated game
# when the evaluator keeps its hash between calls, as inside a search (Bryan's probe on #16).
def test_new_game_clears_what_earlier_searches_left():
    fen = "r1bq1bn1/pppppkp1/n2r1p2/7p/2PP4/7N/PPQNPPPP/1RB1KB1R w K - 2 7"
    with StockfishEvaluator(depth=1, new_game_each_call=False) as fresh:
        want = fresh.evaluate_children(fen)
    with StockfishEvaluator(depth=1, new_game_each_call=False) as used:
        used.evaluate_children(chess.STARTING_FEN)
        used.new_game()
        assert used.evaluate_children(fen) == want


def kill(evaluator):
    """SIGKILL the evaluator's Stockfish process, as a crash would."""
    import os, signal, time
    os.kill(evaluator.engine.protocol.transport.get_pid(), signal.SIGKILL)
    time.sleep(0.3)


# Catches: a dead engine (a crash mid-batch) making close() raise, so a run's exit stack ends with a
# traceback instead of its summary line; and no way to ask whether the engine is still there.
def test_a_dead_engine_is_reported_by_alive_and_closed_without_raising():
    ev = StockfishEvaluator(depth=1, new_game_each_call=False)
    assert ev.alive() is True
    kill(ev)
    assert ev.alive() is False
    ev.close()  # must not raise
    ev.close()  # nor twice
