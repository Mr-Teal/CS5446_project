"""Under Teal's rules (the rules of these matches) the belief-input network must be shown what
training showed it.

The network was trained in fowppo.env, whose belief samplers are fed by the C++ rules. In a match the
player's sampler is fed the referee's observations instead. Random games are played in the training
environment and in a GameReferee at the same time, move by move, and the two pictures are compared
cell for cell (same sampler seeds), under `teal` and under `standin` rules.
"""
import random

import chess
import numpy as np
import pytest

from fow_shared.evaluation import MatchConfig, play_game
from pairb.rules import GameReferee, pick_rules
from ppo_belief_player import NoBeliefFactory, PpoBeliefFactory, belief_package

E, belief, agent = belief_package("env"), belief_package("belief"), belief_package("agent")
NAMES = {chess.WHITE: "white", chess.BLACK: "black"}
PLY_CAP = 200
CHECKPOINT = "checkpoints/ppo-belief-5h/final.pt"  # relative to the package folder


def compare(rules_name, cap, plies, line=None):
    rules = pick_rules(rules_name)
    rng = random.Random(11)
    samplers = (belief.create(), belief.create())
    seed = games = captures = repairs = prunes = specials = blank = 0
    try:
        while plies > 0:
            seed += 1
            game = E.Game(samplers, seed, cap)
            referee = GameReferee(rules)
            referee.reset(0)
            watchers = {color: agent.ObservedBelief(color, seed * 2 + color, cap) for color in NAMES}
            for color, watcher in watchers.items():
                watcher.see(referee.observe(NAMES[color]))
            script = list(line.split()) if line else None
            while plies > 0:
                board, color = game.board, game.board.turn
                view = referee.observe(NAMES[color])
                assert referee.current_player() == NAMES[color]
                training = belief.planes(samplers[color])
                # 1. The 32 planes built from the referee's observations equal the training planes.
                assert np.array_equal(watchers[color].planes(), training), (board.fen(), game.ply)
                # 2. The referee's legal moves, less under-promotions, are the training environment's moves.
                table = E.legal_actions(board)
                assert {a: chess.Move.from_uci(u) for a, u in agent.action_table(view).items()} == table, board.fen()
                captures += int(training[E.P_LOSS].sum() > 0)
                blank += belief.counters(samplers[color])["blank"]
                if script is not None:
                    if not script:
                        return games, captures, repairs, prunes, specials, blank
                    move = chess.Move.from_uci(script.pop(0))
                    assert move in table.values(), move
                else:
                    move = rng.choice(list(table.values()))
                specials += int(board.is_en_passant(move) or board.is_castling(move))
                plies -= 1
                ended = game.play(move)
                referee.apply(move.uci())
                # 3. Both sides agree on when the game is over (the 200-ply cap belongs to the match loop).
                if ended is not None:
                    assert referee.is_terminal() or game.ply >= PLY_CAP, (move, game.ply)
                    break
                assert not referee.is_terminal(), (move, game.ply)
                for viewer, watcher in watchers.items():
                    watcher.see(referee.observe(NAMES[viewer]), move.uci() if viewer == color else None)
            for handle in samplers:
                state = belief.counters(handle)
                repairs, prunes = repairs + state["repairs"], prunes + state["prunes"]
            games += 1
    finally:
        for handle in samplers:
            belief.destroy(handle)
    return games, captures, repairs, prunes, specials, blank


@pytest.mark.parametrize("rules_name", ["teal", "standin"])
def test_referee_observations_give_the_training_planes(rules_name):
    games, captures, repairs, prunes, specials, blank = compare(rules_name, E.BELIEF_CAP, 6000)
    assert games >= 20 and captures > 200 and prunes > 50  # whole games, with captures and pruning
    print(f"{rules_name}, cap {E.BELIEF_CAP}: {games} games, {captures} captures seen, {prunes} prunes, "
          f"{repairs} repairs, {specials} castlings or en passant, {blank} blank turns")


@pytest.mark.parametrize("rules_name", ["teal", "standin"])
def test_planes_stay_equal_through_many_repairs(rules_name):
    games, captures, repairs, prunes, specials, blank = compare(rules_name, 8, 6000)
    assert games >= 20 and repairs > 150
    print(f"{rules_name}, cap 8: {games} games, {repairs} repairs, {blank} blank turns")


@pytest.mark.parametrize("rules_name", ["teal", "standin"])
@pytest.mark.parametrize("line", [
    "e2e4 a7a6 e4e5 d7d5 e5d6 e7d6 g1f3 c8g4",            # White captures en passant
    "a2a3 d7d5 a3a4 d5d4 e2e4 d4e3 d2e3 d8d1",            # Black captures en passant; queens meet
    "e2e4 e7e5 g1f3 g8f6 f1c4 f8c5 e1g1 e8g8 d2d4 e5d4",  # both sides castle
])
def test_scripted_lines_with_en_passant_and_castling(rules_name, line):
    """Random games rarely contain an en passant capture, so three fixed lines are compared too."""
    games, captures, repairs, prunes, specials, blank = compare(rules_name, E.BELIEF_CAP, 10 ** 6, line)
    assert specials >= 1 and blank == 0


def test_factory_player_finishes_games_in_the_match_loop():
    settings = {"checkpoint_path": CHECKPOINT, "move_choice": "sample"}
    factory = PpoBeliefFactory(settings)
    player = factory.load_model()
    assert player.provenance_checkpoint_path.is_file()
    rules = pick_rules("teal")
    trackers = NoBeliefFactory(settings)
    for seed in (1, 2):
        factory.reset_game()
        referee = GameReferee(rules)
        config = MatchConfig(time_budget_ms=5000, max_plies=PLY_CAP, seed=seed, rules_id=rules.name,
                             engine_id="ppo-belief-self", leaf_depth=0)
        # Two players, as in a match: one sampler per colour.
        other = factory.load_model()
        result = play_game(referee, {"white": player, "black": other},
                           {"white": trackers.create_tracker(rules), "black": trackers.create_tracker(rules)}, config)
        assert result.stopped_at_ply_limit or referee.result() is not None
        assert len(result.plies) > 10
        assert sum(p.diagnostics["belief_blank"] for p in result.plies) == 0
        assert max(p.diagnostics["belief_boards"] for p in result.plies) > 1


def test_factory_refuses_a_missing_checkpoint_and_an_unknown_move_choice():
    with pytest.raises(FileNotFoundError):
        PpoBeliefFactory({"checkpoint_path": "checkpoints/no-such-run/final.pt"}).load_model()
    with pytest.raises(ValueError):
        PpoBeliefFactory({"checkpoint_path": CHECKPOINT, "move_choice": "greedy"}).load_model()
    with pytest.raises(ValueError):
        NoBeliefFactory({}).create_tracker(None, initial_fen=chess.STARTING_FEN)
