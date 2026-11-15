"""The environment must play by the team's fog rules and must never show hidden pieces."""
import random

import chess
import numpy as np

from fow_shared.values import _available_fog_moves, terminal_score
from fowppo_belief import belief, env as E
from fowppo_belief.moves import action_of, move_of
from pairb.observe import visible_squares  # Pair B's Python rules for what a player sees


def random_positions(games, seed, max_plies=120):
    """Boards from random fog-legal play, each with its move history."""
    rng = random.Random(seed)
    for _ in range(games):
        board = chess.Board()
        for _ in range(max_plies):
            if terminal_score(board) is not None:
                break
            yield board
            board.push(rng.choice(_available_fog_moves(board)))


def cells(bitboard, color):
    """A bitboard as 64 cells in `color`'s frame (own side first)."""
    if color == chess.BLACK:
        bitboard = chess.flip_vertical(bitboard)
    return np.array([(bitboard >> sq) & 1 for sq in range(64)], dtype=bool)


def names_bb(names):
    return sum(chess.BB_SQUARES[chess.parse_square(name)] for name in names)


def test_every_legal_move_has_one_action_and_comes_back():
    promotions = 0
    for board in random_positions(games=60, seed=2, max_plies=200):
        black = board.turn == chess.BLACK
        seen_actions = set()
        for move in _available_fog_moves(board):
            if move.promotion not in (None, chess.QUEEN):
                continue  # the agent always promotes to a queen
            action = action_of(move, black)
            assert 0 <= action < 4096 and action not in seen_actions
            seen_actions.add(action)
            assert move_of(action, board) == move, (board.fen(), move)
            promotions += move.promotion is not None
    assert promotions > 0  # the walk reached promotions, so that branch was checked


def plane(obs, index):
    return obs[index].reshape(8, 8)  # row = rank from the player's own side, column = file a-h


def test_black_does_not_see_whites_first_move_but_weighs_all_twenty():
    vec = E.VecFow(1)
    vec.step(np.array([action_of(chess.Move.from_uci("e2e4"), black=False)]))
    obs = vec.obs[0]
    assert vec.seat[0] == 0  # Black to move
    assert obs[E.P_SEEN_ENEMY:E.P_SEEN_ENEMY + 6].sum() == 0 and obs[E.P_ANY_ENEMY].sum() == 0  # no white piece is in view
    assert belief.count(vec.games[0].samplers[chess.BLACK]) == 20  # White's twenty first moves all fit
    pawns = plane(obs, E.P_PROBABILITY)
    # Black's frame is mirrored: White's second rank is row 6, e-file is column 4.
    assert pawns[6, 4] == round(255 * 18 / 20)  # the e-pawn is still at home in 18 of the 20
    assert pawns[4, 4] == round(255 * 1 / 20) and pawns[5, 4] == round(255 * 1 / 20)  # e4 and e3: one each
    assert plane(obs, E.P_PROBABILITY + 5)[7, 4] == 255  # the white king has not moved
    assert plane(obs, E.P_OWN)[1].sum() == 8 * 255  # Black's own pawns, on its own second row
    assert obs[E.P_POPULATION][0] == round(255 * np.log2(20) / 15)
    assert obs[E.P_PLY][0] == round(255 * 1 / 200) and obs[E.P_DEPTH].sum() == 0


def test_hidden_pieces_never_enter_the_view_planes():
    rng = random.Random(3)
    vec = E.VecFow(8)
    blank = 0
    for _ in range(300):
        for i, game in enumerate(vec.games):
            color = game.board.turn
            board = game.board
            seen = cells(names_bb(visible_squares(board, color)), color)  # the team's Python rule
            obs = vec.obs[i]
            assert ((obs[E.P_SEEN] == 255) == seen).all() and set(np.unique(obs[E.P_SEEN])) <= {0, 255}
            assert obs[E.P_SEEN_ENEMY:E.P_SEEN_ENEMY + 6][:, ~seen].sum() == 0  # view: seen squares only
            assert obs[E.P_ANY_ENEMY][~seen].sum() == 0
            enemy = board.occupied_co[not color]
            kinds = (board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings)
            for k, kind in enumerate(kinds):
                in_view = cells(kind & enemy, color) & seen
                assert ((obs[E.P_SEEN_ENEMY + k] == 255) == in_view).all()
                assert (obs[E.P_OWN + k] == 255).sum() == (kind & board.occupied_co[color]).bit_count()
                # a piece in view is certain; a square in view without it is certainly not that piece
                assert (obs[E.P_PROBABILITY + k][in_view] == 255).all()
                assert obs[E.P_PROBABILITY + k][seen & ~in_view].sum() == 0
            state = belief.counters(game.samplers[color])
            blank += state["blank"]
            if not state["blank"]:  # one enemy king somewhere: the 64 rounded cells add up to about 1
                assert abs(int(obs[E.P_PROBABILITY + 5].sum()) - 255) <= 32
        vec.step(np.array([rng.choice(list(table)) for table in vec.tables]))
    assert blank == 0


def test_capturing_the_king_wins_and_restarts_the_game():
    vec = E.VecFow(1)
    rewards = []
    for uci in ("e2e4", "f7f6", "d1h5", "a7a6", "h5e8"):
        black = vec.games[0].board.turn == chess.BLACK
        term_r, done = vec.step(np.array([action_of(chess.Move.from_uci(uci), black)]))
        rewards.append((float(term_r[0]), bool(done[0])))
    assert rewards == [(0.0, False)] * 4 + [(1.0, True)]
    assert vec.finished == [(5, 1, "king-captured")]  # 5 plies, White won
    assert vec.games[0].board.fen() == chess.STARTING_FEN and vec.seat[0] == 1
    assert belief.count(vec.games[0].samplers[chess.WHITE]) == 1  # the new game's samplers start again


def test_material_potential_is_the_movers_piece_balance():
    board = chess.Board("4k3/8/8/8/8/8/8/QR2K3 w - - 0 1")
    assert E.material_balance(board, chess.WHITE) == 14
    assert E.material_balance(board, chess.BLACK) == -14


def test_scripted_greedy_player_takes_the_king_when_it_can():
    vec = E.VecFow(1)
    for uci in ("e2e4", "f7f6", "d1h5", "a7a6"):
        black = vec.games[0].board.turn == chess.BLACK
        vec.step(np.array([action_of(chess.Move.from_uci(uci), black)]))
    action = E.scripted_action(vec, 0, "greedy", random.Random(0))
    assert move_of(action, vec.games[0].board) == chess.Move.from_uci("h5e8")
