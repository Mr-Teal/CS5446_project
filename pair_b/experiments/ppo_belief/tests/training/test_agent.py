"""In a match the network must be shown exactly what it was shown in training."""
import random

import chess
import numpy as np

from fow_shared.contracts import AgentInput, HistoryEvent
from fowppo_belief import belief, env as E
from fowppo_belief.agent import NoBelief, ObservedBelief, PpoAgent, action_table
from fowppo_belief.model import PolicyValueNet
from pairb.observe import observe  # Pair B's Python rules for what a player sees

NAMES = {chess.WHITE: "white", chess.BLACK: "black"}


def check_match_planes_equal_training_planes(cap, plies):
    """Training: the samplers follow the game through bs_step. A match: ObservedBelief is fed the
    team's Python observations and the player's own moves. Same seeds, so the planes must be equal
    cell for cell, through pruning and repair."""
    rng = random.Random(4)
    seed = 0
    samplers = (belief.create(), belief.create())
    games = captures = repairs = prunes = 0
    try:
        while plies > 0:
            seed += 1
            game = E.Game(samplers, seed, cap)
            watchers = {color: ObservedBelief(color, seed * 2 + color, cap) for color in NAMES}
            for color, watcher in watchers.items():
                watcher.see(observe(game.board, NAMES[color], 0))
            while plies > 0:
                board, color = game.board, game.board.turn
                view = observe(board, NAMES[color], game.ply)
                training = belief.planes(samplers[color])
                assert np.array_equal(watchers[color].planes(), training), (board.fen(), game.ply)
                table = E.legal_actions(board)
                assert {a: chess.Move.from_uci(u) for a, u in action_table(view).items()} == table
                captures += int(training[E.P_LOSS].sum() > 0)
                move = rng.choice(list(table.values()))
                plies -= 1
                if game.play(move) is not None:
                    break
                for viewer, watcher in watchers.items():
                    watcher.see(observe(game.board, NAMES[viewer], game.ply), move.uci() if viewer == color else None)
            for handle in samplers:
                state = belief.counters(handle)
                repairs, prunes = repairs + state["repairs"], prunes + state["prunes"]
            games += 1
    finally:
        for handle in samplers:
            belief.destroy(handle)
    return games, captures, repairs, prunes


def test_planes_from_team_observations_equal_training_planes():
    games, captures, repairs, prunes = check_match_planes_equal_training_planes(cap=E.BELIEF_CAP, plies=2500)
    assert games >= 10 and captures > 100 and prunes > 20  # whole games, with captures and pruning, were compared


def test_planes_stay_equal_through_many_repairs():
    games, captures, repairs, prunes = check_match_planes_equal_training_planes(cap=8, plies=4000)
    assert games >= 15 and repairs > 100


def test_agent_plays_a_legal_move_from_history_alone():
    torch_agent = PpoAgent(PolicyValueNet(blocks=1, channels=8), sample=True)
    torch_agent.reset("black", seed=3)
    board = chess.Board()
    history, tracker = [], NoBelief()
    tracker.reset("black", 0)
    for ply, uci in enumerate(("e2e4", "e7e5", "g1f3")):
        view = observe(board, "black", ply)
        history.append(HistoryEvent(view, uci if board.turn == chess.BLACK else None))
        board.push_uci(uci)
    view = observe(board, "black", 3)
    turn = AgentInput(view, tracker.update(view), 1000, tuple(history))
    decision = torch_agent.act(turn)
    decision.validate_for(view)
    assert decision.move in view.legal_moves
    assert decision.diagnostics["belief_boards"] > 1 and decision.diagnostics["belief_blank"] == 0
    assert torch_agent.act(turn).move in view.legal_moves  # asked again about the same turn: no fault
