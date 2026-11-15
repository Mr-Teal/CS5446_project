"""Under Teal's rules (the rules of these matches) the network must be shown what training showed it.

The network was trained in fowppo.env, which uses fow_shared.values. The matches use `rules = teal`.
So random games are played in the training environment and in a GameReferee over Teal's rules at the
same time, move by move, and the network's input is compared at every ply. The stand-in rules are
checked in the same way.
"""
import random

import chess
import numpy as np
import pytest

from fow_shared.evaluation import MatchConfig, play_game
from fowppo import env as E
from fowppo.agent import NoBelief, ObservationMemory, action_table
from pairb.rules import GameReferee, pick_rules
from ppo_player import NoBeliefFactory, PpoFactory

NAMES = {chess.WHITE: "white", chess.BLACK: "black"}
PLY_CAP = 200


def new_game(rules):
    referee = GameReferee(rules)
    referee.reset(0)
    memories = {color: ObservationMemory(color) for color in NAMES}
    for color, memory in memories.items():
        memory.see(referee.observe(NAMES[color]))
    return referee, memories


@pytest.mark.parametrize("rules_name", ["teal", "standin"])
def test_referee_observations_give_the_training_planes(rules_name):
    rules = pick_rules(rules_name)
    vec = E.VecFow(1)
    rng = random.Random(11)
    referee, memories = new_game(rules)
    games = captures = castlings = promotions = en_passants = 0
    for _ in range(6000):
        game = vec.games[0]
        color = game.board.turn
        view = referee.observe(NAMES[color])
        assert referee.current_player() == NAMES[color]
        # 1. The 25 planes built from the referee's observations equal the training planes.
        assert np.array_equal(memories[color].planes(), vec.obs[0]), (game.board.fen(), game.ply)
        # 2. The referee's legal moves, less under-promotions, are the training environment's moves.
        table = action_table(view)
        assert {a: chess.Move.from_uci(u) for a, u in table.items()} == vec.tables[0], game.board.fen()
        captures += int(vec.obs[0][E.P_LOSS].sum())
        action = rng.choice(sorted(vec.tables[0]))
        move = vec.tables[0][action]
        castlings += int(game.board.is_castling(move))
        en_passants += int(game.board.is_en_passant(move))
        promotions += int(move.promotion is not None)
        plies_after = game.ply + 1
        _, done = vec.step(np.array([action]))
        referee.apply(move.uci())
        # 3. Both sides agree on when the game is over (the 200-ply cap belongs to the match loop).
        if done[0]:
            assert referee.is_terminal() or plies_after >= PLY_CAP, (move, plies_after)
            games += 1
            referee, memories = new_game(rules)
        else:
            assert not referee.is_terminal(), (move, plies_after)
            for viewer, memory in memories.items():
                memory.see(referee.observe(NAMES[viewer]))
    assert games >= 20 and captures > 200  # whole games, with captures, were compared
    print(f"{rules_name}: {games} games, {captures} captures seen, {castlings} castlings, "
          f"{en_passants} en passant, {promotions} promotions")


@pytest.mark.parametrize("rules_name", ["teal", "standin"])
@pytest.mark.parametrize("line", [
    "e2e4 a7a6 e4e5 d7d5 e5d6 e7d6 g1f3 c8g4",            # White captures en passant
    "a2a3 d7d5 a3a4 d5d4 e2e4 d4e3 d2e3 d8d1",            # Black captures en passant; queens meet
    "e2e4 e7e5 g1f3 g8f6 f1c4 f8c5 e1g1 e8g8 d2d4 e5d4",  # both sides castle
])
def test_scripted_lines_with_en_passant_and_castling(rules_name, line):
    """Random games rarely contain an en passant capture, so three fixed lines are compared too."""
    rules = pick_rules(rules_name)
    vec = E.VecFow(1)
    referee, memories = new_game(rules)
    special = 0
    for uci in line.split():
        game = vec.games[0]
        color = game.board.turn
        assert np.array_equal(memories[color].planes(), vec.obs[0]), (uci, game.board.fen())
        table = action_table(referee.observe(NAMES[color]))
        assert {a: chess.Move.from_uci(u) for a, u in table.items()} == vec.tables[0], (uci, game.board.fen())
        move = chess.Move.from_uci(uci)
        special += int(game.board.is_en_passant(move) or game.board.is_castling(move))
        action = next(a for a, m in vec.tables[0].items() if m == move)
        _, done = vec.step(np.array([action]))
        referee.apply(uci)
        assert not done[0] and not referee.is_terminal()
        for viewer, memory in memories.items():
            memory.see(referee.observe(NAMES[viewer]))
    color = vec.games[0].board.turn
    assert np.array_equal(memories[color].planes(), vec.obs[0])
    assert special >= 1


CHECKPOINT = "checkpoints/ppo-selfplay-12h/final.pt"  # relative to the package folder


def test_factory_player_finishes_games_in_the_match_loop():
    settings = {"checkpoint_path": CHECKPOINT, "move_choice": "sample"}
    factory = PpoFactory(settings)
    agent = factory.load_model()
    assert agent.provenance_checkpoint_path.is_file()
    rules = pick_rules("teal")
    trackers = NoBeliefFactory(settings)
    for seed in (1, 2):
        factory.reset_game()
        referee = GameReferee(rules)
        config = MatchConfig(time_budget_ms=5000, max_plies=PLY_CAP, seed=seed, rules_id=rules.name,
                             engine_id="ppo-self", leaf_depth=0)
        result = play_game(referee, {"white": agent, "black": agent},
                           {"white": trackers.create_tracker(rules), "black": trackers.create_tracker(rules)},
                           config)
        assert result.stopped_at_ply_limit or referee.result() is not None
        assert len(result.plies) > 10


def test_factory_refuses_a_missing_checkpoint_and_an_unknown_move_choice():
    with pytest.raises(FileNotFoundError):
        PpoFactory({"checkpoint_path": "checkpoints/no-such-run/final.pt"}).load_model()
    with pytest.raises(ValueError):
        PpoFactory({"checkpoint_path": CHECKPOINT, "move_choice": "greedy"}).load_model()
    with pytest.raises(ValueError):
        NoBeliefFactory({}).create_tracker(None, initial_fen=chess.STARTING_FEN)
