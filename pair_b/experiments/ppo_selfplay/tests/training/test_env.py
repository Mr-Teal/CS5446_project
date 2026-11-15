"""The environment must play by the team's fog rules and must never show hidden pieces."""
import random

import chess
import numpy as np

from fow_shared.values import _available_fog_moves, terminal_score
from fowppo import env as E
from fowppo.moves import action_of, move_of
from team_observe_reference import visible_squares  # Pair B's observe.py, copied unchanged from main


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


def names(bitboard):
    return frozenset(chess.square_name(sq) for sq in chess.scan_forward(bitboard))


def test_seen_squares_match_the_team_rule():
    checked = 0
    for board in random_positions(games=60, seed=1):
        for color in (chess.WHITE, chess.BLACK):
            assert names(E.seen_bb(board, color)) == visible_squares(board, color), board.fen()
            checked += 1
    assert checked > 5000


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


def test_black_does_not_see_whites_first_move_but_remembers_the_start():
    vec = E.VecFow(1)
    vec.step(np.array([action_of(chess.Move.from_uci("e2e4"), black=False)]))
    obs = vec.obs[0]
    assert vec.seat[0] == 0  # Black to move
    assert obs[E.P_SEEN_ENEMY:E.P_SEEN_ENEMY + 6].sum() == 0  # no white piece is in view
    # Black's frame is mirrored: White's second rank is row 6, e-file is column 4.
    assert plane(obs, E.P_MEMORY)[6, 4] == 1  # the pawn is still remembered on e2
    assert plane(obs, E.P_MEMORY)[4, 4] == 0  # and nothing is known on e4
    assert plane(obs, E.P_AGE)[6, 4] > 0  # that memory is one ply old
    assert plane(obs, E.P_OWN)[1].sum() == 8  # Black's own pawns, on its own second row


def test_hidden_pieces_never_enter_the_view_planes():
    rng = random.Random(3)
    vec = E.VecFow(8)
    for _ in range(300):
        for i, game in enumerate(vec.games):
            color = game.board.turn
            seen = E.seen_bb(game.board, color)
            if color == chess.BLACK:
                seen = chess.flip_vertical(seen)
            seen_cells = np.array([(seen >> sq) & 1 for sq in range(64)], dtype=bool)
            obs = vec.obs[i]
            assert (obs[E.P_SEEN].astype(bool) == seen_cells).all()
            assert obs[E.P_SEEN_ENEMY:E.P_SEEN_ENEMY + 6][:, ~seen_cells].sum() == 0  # view: seen squares only
            assert obs[E.P_MEMORY:E.P_MEMORY + 6][:, seen_cells].sum() == 0  # memory: unseen squares only
            assert obs[E.P_AGE][seen_cells].sum() == 0
            enemy = game.board.occupied_co[not color]
            enemy_kings = game.board.kings & enemy & E.seen_bb(game.board, color)
            assert obs[E.P_SEEN_ENEMY + 5].sum() == bin(enemy_kings).count("1")
        vec.step(np.array([rng.choice(list(table)) for table in vec.tables]))


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
