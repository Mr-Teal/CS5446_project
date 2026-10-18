"""Practice beliefs for the belief network (D6), made without Pair A's tracker.

The true board plus alternatives that move the opponent's unseen pieces to other unseen squares.
Every hypothesis must look exactly like the truth to the player: same squares seen, same pieces
on them, same legal moves.
"""
import random

import chess
import pytest

from fow_shared.contracts import TrainingRecord
from fow_shared.features import encode_belief
from fow_shared.values import standard_fen
from pairb.observe import observe, visible_squares
from pairb.standin_beliefs import make_turn, record_for

MIDDLEGAME = "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 2 9"   # White to move
BLACK_TO_MOVE = "r2qkb1r/ppp2ppp/2n1bn2/3pp3/4P3/2NP1N2/PPP1BPPP/R1BQK2R b KQkq - 3 6"
POSITIONS = [chess.STARTING_FEN, MIDDLEGAME, BLACK_TO_MOVE]


def boards_of(turn):
    return [chess.Board(h.fen) for h in turn.belief.hypotheses]


# Catches: a hypothesis the player could tell apart from the truth, which a real tracker would
# never keep (a piece moved into view, or onto a square that changes the player's legal moves).
@pytest.mark.parametrize("fen", POSITIONS)
def test_every_hypothesis_looks_exactly_like_the_truth_to_the_player(fen):
    truth = chess.Board(fen)
    turn = make_turn(truth, random.Random(1), n_hypotheses=8, ply=10)
    want = turn.observation
    for board in boards_of(turn):
        got = observe(board, want.player, ply=10)
        assert (got.visible_squares, got.visible_pieces, got.legal_moves) == \
               (want.visible_squares, want.visible_pieces, want.legal_moves)
    encode_belief(turn, lambda b: sorted(visible_squares(b, not b.turn)))  # raises on any contradiction


# Catches: the truth left out, duplicates, or own pieces and piece counts changed.
@pytest.mark.parametrize("fen", [MIDDLEGAME, BLACK_TO_MOVE])
def test_the_truth_is_kept_and_only_unseen_opponent_pieces_move(fen):
    truth = chess.Board(fen)
    turn = make_turn(truth, random.Random(2), n_hypotheses=8, ply=10)
    fens = [h.fen for h in turn.belief.hypotheses]
    assert standard_fen(truth) in fens and len(set(fens)) == len(fens) > 1
    me = truth.turn
    for board in boards_of(turn):
        assert board.turn == me
        assert board.occupied_co[me] == truth.occupied_co[me] and board.pieces(chess.KING, me) == truth.pieces(chess.KING, me)
        for kind in chess.PIECE_TYPES:
            assert len(board.pieces(kind, not me)) == len(truth.pieces(kind, not me))
        assert not board.pieces(chess.PAWN, not me) & (chess.BB_RANK_1 | chess.BB_RANK_8)


# Catches: weights that do not sum to one, or the belief and observation naming different turns.
def test_the_belief_is_uniform_over_its_hypotheses():
    turn = make_turn(chess.Board(MIDDLEGAME), random.Random(3), n_hypotheses=6, ply=16)
    n = len(turn.belief.hypotheses)
    assert all(h.weight == pytest.approx(1 / n) for h in turn.belief.hypotheses)
    assert (turn.belief.player, turn.belief.ply, turn.observation.ply) == ("white", 16, 16)


# Catches: hidden pieces invented where the player in fact sees every opponent piece.
def test_nothing_hidden_means_a_single_hypothesis():
    board = chess.Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")  # the rook sees Black's only piece
    turn = make_turn(board, random.Random(4), n_hypotheses=8)
    assert [h.fen for h in turn.belief.hypotheses] == [standard_fen(board)]


# Catches: a run that cannot be repeated from its seed.
def test_the_same_seed_gives_the_same_belief():
    a = make_turn(chess.Board(MIDDLEGAME), random.Random(5), n_hypotheses=8)
    b = make_turn(chess.Board(MIDDLEGAME), random.Random(5), n_hypotheses=8)
    assert a == b


# Catches: a record whose position value is not the weighted mean of its board values.
def test_a_record_carries_the_values_and_their_weighted_mean():
    turn = make_turn(chess.Board(MIDDLEGAME), random.Random(6), n_hypotheses=4)
    n = len(turn.belief.hypotheses)
    values = tuple([0.5] * (n - 1) + [-0.5])
    record = record_for(turn, values, seed=6, game_id="g-000006", label="standin-stockfish-d11")
    assert isinstance(record, TrainingRecord) and record.game_id == "g-000006"
    assert record.hypothesis_values == values
    assert record.root_value == pytest.approx((0.5 * (n - 1) - 0.5) / n)
