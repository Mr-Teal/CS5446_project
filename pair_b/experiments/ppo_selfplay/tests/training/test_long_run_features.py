"""Mixed opponents and worker processes must not change the game the learner plays."""
import random

import numpy as np

from fowppo import env as E
from fowppo.procvec import ProcVec


def test_a_scripted_rival_owns_one_colour_and_plays_its_own_move():
    vec = E.VecFow(32, rivals={"greedy": 1.0}, seed=5)
    rng = random.Random(0)
    scripted_moves = 0
    for _ in range(150):
        rival_to_move = [vec.seat[i] == vec.rival[i][1] for i in range(vec.n)]
        assert [c == E.SCRIPTED for c in vec.control] == rival_to_move
        chosen = [vec.tables[i][vec.scripted[i]] if rival_to_move[i] else None for i in range(vec.n)]
        boards = [game.board for game in vec.games]
        _, done = vec.step(np.array([rng.choice(sorted(table)) for table in vec.tables]))  # ignored on rival turns
        for i in range(vec.n):
            if chosen[i] is not None:
                assert boards[i].peek() == chosen[i]  # the rival's own choice was played
                scripted_moves += 1
    assert scripted_moves > 1000


def test_rival_mix_follows_the_given_chances():
    vec = E.VecFow(4000, rivals={"self": 0.5, "past": 0.25, "random": 0.25}, seed=1)
    kinds = [E.RIVALS[kind] for kind, _ in vec.rival]
    assert abs(kinds.count("self") / 4000 - 0.5) < 0.04
    assert abs(kinds.count("past") / 4000 - 0.25) < 0.04
    assert "greedy" not in kinds
    past_white = [i for i, (kind, color) in enumerate(vec.rival) if E.RIVALS[kind] == "past" and color]
    assert all(vec.control[i] == E.PAST for i in past_white)  # White moves first, and White is the past network


def test_worker_processes_play_the_same_games_as_one_process():
    n = 12
    plain = E.VecFow(n, shaping=0.02)
    spread = ProcVec(n, workers=3, shaping=0.02)
    rng = random.Random(7)
    try:
        finished = 0
        for _ in range(260):
            for name in ("obs", "mask", "phi", "seat", "control"):
                assert np.array_equal(getattr(plain, name), getattr(spread, name)), name
            actions = np.array([rng.choice(sorted(table)) for table in plain.tables])
            term_a, done_a = plain.step(actions)
            term_b, done_b = spread.step(actions)
            assert np.array_equal(term_a, term_b) and np.array_equal(done_a, done_b)
            finished += int(done_a.sum())
        assert finished > 0 and sorted(plain.finished) == sorted(spread.finished)
    finally:
        spread.close()


def test_random_openings_vary_the_start_and_keep_the_views_honest():
    import chess

    vec = E.VecFow(300, opening=(2, 8), seed=3)
    plies = [game.ply for game in vec.games]
    assert min(plies) >= 2 and max(plies) <= 8 and len(set(plies)) == 7
    assert len({game.board.fen() for game in vec.games}) > 250
    for i, game in enumerate(vec.games):
        color = game.board.turn
        assert vec.seat[i] == color
        seen = E.seen_bb(game.board, color)
        assert game.seen[color] == seen  # the view was refreshed after the last opening move
        if color == chess.BLACK:
            seen = chess.flip_vertical(seen)
        cells = np.array([(seen >> sq) & 1 for sq in range(64)], dtype=bool)
        assert (vec.obs[i][E.P_SEEN].astype(bool) == cells).all()
        assert vec.obs[i][E.P_SEEN_ENEMY:E.P_SEEN_ENEMY + 6][:, ~cells].sum() == 0
        assert vec.obs[i][E.P_PLY][0] == game.ply * 255 // E.MAX_PLIES
