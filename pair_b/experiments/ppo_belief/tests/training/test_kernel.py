"""The belief sampler: exact while it is under its cap, honest above it, and the team's 32 planes."""
import ctypes as C
import random

import chess
import numpy as np

from fow_shared.contracts import AgentInput, Belief, Hypothesis
from fow_shared.features import encode_belief
from fow_shared.values import _available_fog_moves, fog_position_key, standard_fen
from fowppo_belief import belief, env as E
import pairb.belief_ablation as ablation  # the team's collapse of the 32 planes to one board
from pairb.observe import observe, visible_squares  # Pair B's Python rules for what a player sees

NAMES = {chess.WHITE: "white", chess.BLACK: "black"}
NO_LIMIT = 10 ** 9
NONE = 2 ** 64 - 1

dll = belief.dll
dll.zs_create.argtypes, dll.zs_create.restype = [C.POINTER(belief.Packed), C.c_int, C.c_uint64], C.c_void_p
dll.zs_destroy.argtypes, dll.zs_destroy.restype = [C.c_void_p], None
dll.zs_count.argtypes, dll.zs_count.restype = [C.c_void_p], C.c_uint64
dll.zs_validate.argtypes, dll.zs_validate.restype = [C.c_void_p, C.POINTER(belief.View)], C.c_int
dll.zs_update.argtypes, dll.zs_update.restype = [C.c_void_p, C.POINTER(belief.View), C.c_int, C.c_double], C.c_int
dll.zs_index.argtypes, dll.zs_index.restype = [C.c_void_p, C.POINTER(belief.Packed)], C.c_uint64


def walk(games, seed, cap, max_plies=200, stop_above=10 ** 9):
    """Random fog-legal games. Yields (game, move, captured, mover) after every ply, and
    (game, None, -1, None) at the start of each game. The samplers are in game.samplers.
    A game is left as soon as a sampler holds more than `stop_above` positions."""
    rng = random.Random(seed)
    for g in range(games):
        samplers = (belief.create(), belief.create())
        try:
            game = E.Game(samplers, seed * 1000 + g, cap)
            yield game, None, -1, None
            for _ in range(max_plies):
                board = game.board
                move = rng.choice(list(E.legal_actions(board).values()))
                mover = board.turn
                captured = -1
                if board.is_en_passant(move):
                    captured = move.to_square + (-8 if mover == chess.WHITE else 8)
                elif board.occupied_co[not mover] & chess.BB_SQUARES[move.to_square]:
                    captured = move.to_square
                if game.play(move) is not None:
                    break
                yield game, move, captured, mover
                if max(belief.counters(handle)["boards"] for handle in samplers) > stop_above:
                    break
        finally:
            for handle in samplers:
                belief.destroy(handle)


def test_under_the_cap_the_sample_is_the_teams_exact_information_set():
    """Against the team's own C++ tracker (zs_*), fed the same views: the same positions at every ply."""
    compared = 0
    trackers = {}
    for game, move, captured, mover in walk(games=60, seed=11, cap=NO_LIMIT, max_plies=60, stop_above=3000):
        if move is None:
            for handle in trackers.values():
                dll.zs_destroy(handle)
            start = belief.pack(game.board)
            trackers = {color: dll.zs_create(C.byref(start), int(color), 1) for color in NAMES}
            for color, handle in trackers.items():
                assert dll.zs_validate(handle, C.byref(belief.observe(game.board, color)))
            continue
        for color, handle in trackers.items():
            own = color == mover
            view = belief.observe(game.board, color, -1 if own else captured)
            assert dll.zs_update(handle, C.byref(view), belief.encode_move(move) if own else -1, -1.0)
            rows = belief.sample(game.samplers[color])
            assert len(rows) == dll.zs_count(handle), (game.board.fen(), game.ply)
            for blob, weight, _ in rows:
                assert dll.zs_index(handle, C.byref(belief.Packed.from_buffer_copy(blob))) != NONE
                assert weight > 0
            assert belief.weight_of(game.samplers[color], game.board) > 0  # the true position is always there
            compared += 1
    for handle in trackers.values():
        dll.zs_destroy(handle)
    assert compared > 600


def python_histories(moves, viewer, plies):
    """{position key: number of move histories} that fit `viewer`'s views of the game `moves`, after
    `plies` plies, by trying every move with Pair B's Python observe(): no C++ involved."""
    def shown(board, ply):
        view = observe(board, NAMES[viewer], ply)
        return view.side_to_move, tuple(sorted(view.visible_pieces.items())), view.legal_moves, view.terminal

    true = chess.Board()
    states = {fog_position_key(true): (true.copy(), 1)}
    for ply in range(1, plies + 1):
        own = true.turn == viewer
        true_move = moves[ply - 1]
        true.push(true_move)
        target = shown(true, ply)
        following = {}
        for board, count in states.values():
            for move in ([true_move] if own else _available_fog_moves(board)):
                child = board.copy()
                child.push(move)
                if shown(child, ply) == target:
                    key = fog_position_key(child)
                    following[key] = (child, following.get(key, (None, 0))[1] + count)
        states = following
    return {key: count for key, (_, count) in states.items()}


def test_weights_count_the_move_histories_that_fit_what_the_player_saw():
    """Against a brute-force count in Python with Pair B's observe(): the same positions, each with
    its share of the histories. This also checks the C++ rules against the Python rules."""
    checked = 0
    history = []
    for game, move, _, _ in walk(games=10, seed=5, cap=NO_LIMIT, max_plies=4):
        if move is None:
            history = []
            continue
        history.append(move)
        for color in NAMES:
            expected = python_histories(history, color, len(history))
            total = sum(expected.values())
            rows = belief.sample(game.samplers[color])
            got = {fog_position_key(belief.board_of(blob)): weight for blob, weight, _ in rows}
            assert set(got) == set(expected), (game.board.fen(), NAMES[color])
            for key, count in expected.items():
                assert abs(got[key] - count / total) < 1e-9
            assert abs(2 ** belief.log2_population(game.samplers[color]) - total) < 1e-6 * total
            checked += 1
    assert checked >= 60


def team_picture(game, color, capture_square):
    """The team's planes for the sampler's positions: fow_shared.features.encode_belief on a Belief
    made of the kept positions and their weights, collapsed by the team's "marginals" mode."""
    handle = game.samplers[color]
    rows = belief.sample(handle)
    hypotheses = tuple(Hypothesis(standard_fen(belief.board_of(blob, round(half))), weight, history_id=str(i))
                       for i, (blob, weight, half) in enumerate(rows))
    total = sum(h.weight for h in hypotheses)
    hypotheses = tuple(Hypothesis(h.fen, h.weight / total, h.history_id) for h in hypotheses)
    population = max(len(rows), round(2 ** min(belief.log2_population(handle), 200.0)))
    view = observe(game.board, NAMES[color], game.ply)
    turn = AgentInput(view, Belief(NAMES[color], game.ply, hypotheses, population), 1000)
    recency = {} if capture_square < 0 else {chess.square_name(capture_square): 1.0}
    planes, weights = encode_belief(turn, lambda board: sorted(visible_squares(board, not board.turn)),
                                    capture_recency=recency)
    arrays = {"planes": planes, "weight": weights, "belief": np.zeros(len(weights), dtype=np.int64),
              "root": np.zeros(1, dtype=np.float32), "rule": np.zeros(len(weights), dtype=bool), "game_id": np.array(["g"])}
    return ablation.collapse(arrays, "marginals")["planes"][0]


def check_pictures(cap, games, seed, max_boards, wanted, min_captures):
    compared = captures = 0
    for game, move, captured, mover in walk(games=games, seed=seed, cap=cap, max_plies=70, stop_above=max_boards):
        color = game.board.turn
        handle = game.samplers[color]
        state = belief.counters(handle)
        if state["blank"] or state["boards"] > max_boards:
            continue
        mine = belief.planes(handle).reshape(32, 8, 8)[:, ::-1, :].astype(np.float32) / 255  # the team's row order
        team = team_picture(game, color, captured)
        tolerance = np.full(32, 0.5 / 255 + 1e-4, dtype=np.float32)
        tolerance[E.P_CLOCK] += 0.006  # the team's clock is a whole number per position; ours is their mean
        # The team's Belief takes a whole number of histories. After pruning or repair ours is an
        # estimate with a fraction, so that plane is compared with the estimate itself as well.
        estimate = min(max(belief.log2_population(handle), 0.0) / 15, 1.0)
        assert abs(float(mine[E.P_POPULATION, 0, 0]) - estimate) <= 0.5 / 255 + 1e-6
        if state["prunes"] or state["repairs"]:
            tolerance[E.P_POPULATION] = 0.04
        difference = np.abs(mine - team).reshape(32, 64).max(axis=1)
        assert (difference <= tolerance).all(), (game.board.fen(), [int(i) for i in np.flatnonzero(difference > tolerance)])
        compared += 1
        captures += captured >= 0
    assert compared >= wanted and captures >= min_captures


def test_the_picture_is_the_teams_encoder_on_the_kept_positions():
    check_pictures(cap=NO_LIMIT, games=60, seed=21, max_boards=300, wanted=300, min_captures=1)


def test_the_picture_is_the_teams_encoder_after_pruning_and_repair_too():
    check_pictures(cap=24, games=12, seed=22, max_boards=10 ** 6, wanted=400, min_captures=10)


def test_every_kept_position_fits_the_view_after_pruning_and_repair():
    for cap in (4, 64):
        moves = repairs = blank = 0
        last = {}
        for game, move, _, _ in walk(games=60, seed=30 + cap, cap=cap):
            if move is None:  # a new game: its samplers start counting from zero
                repairs += sum(last.values())
                last = {}
            for color in NAMES:
                handle = game.samplers[color]
                assert belief.check(handle) == 0, game.board.fen()
                state = belief.counters(handle)
                assert state["boards"] <= cap
                moves += 1
                blank += state["blank"]
                last[handle] = state["repairs"]
        repairs += sum(last.values())
        assert repairs > 100  # the sample did lose the true position, and was rebuilt
        assert blank < 0.02 * moves


def test_self_play_step_gives_each_sampler_only_its_own_view():
    """bs_step, which is handed the true board, must leave the samplers exactly as bs_update does
    when it is handed nothing but the two players' views."""
    seed, cap = 41, 32
    mirrors = {}
    compared, number = 0, -1
    for game, move, captured, mover in walk(games=25, seed=seed, cap=cap):
        if move is None:
            number += 1
            for handle in mirrors.values():
                belief.destroy(handle)
            mirrors = {color: belief.create() for color in NAMES}
            for color, handle in mirrors.items():  # the seeds Game gives its own samplers
                belief.reset(handle, chess.Board(), color, (seed * 1000 + number) * 2 + color, cap)
            continue
        for color, handle in mirrors.items():
            own = color == mover
            belief.update(handle, belief.observe(game.board, color, -1 if own else captured), move if own else None, game.ply)
            assert belief.sample(handle) == belief.sample(game.samplers[color])
            assert np.array_equal(belief.planes(handle), belief.planes(game.samplers[color]))
            compared += 1
    for handle in mirrors.values():
        belief.destroy(handle)
    assert compared > 2000
